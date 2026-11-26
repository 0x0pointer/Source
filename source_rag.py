"""
source_rag — local, offline hybrid search over a folder of notes.

Build with build_index.py, query with query.py / mcp_server.py. Nothing leaves your
machine: the only network access is the one-time model download from Hugging Face
into ./models at build time; queries run offline from there.

Index = a single SQLite file:
  meta        model name / dim / schema version / build info (a query refuses a mismatch)
  files       one row per source file: path + content hash (drives incremental rebuilds)
  chunks      one row per chunk: path, heading trail, text, tags, float32 embedding
  chunks_fts  FTS5 keyword index (exact terms: identifiers, error codes, flags)

Search = vector cosine + FTS5 BM25, fused with Reciprocal Rank Fusion. Semantic
search finds "how do I roll back a failed migration"; keyword search finds an exact
token like "ERR_CONN_4021". You want both.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

# ── branding: rename this ONE token to rebrand the whole tool. Everything below
#    (the index filename, the env vars, the default vault folder, the MCP server
#    name) is derived from it. The only things it can't reach are this module's
#    filename (source_rag.py) and the `import source_rag` lines in the other files.
BRAND = "source"

HERE = Path(__file__).resolve().parent
DEFAULT_DB = HERE / "index" / f"{BRAND}.sqlite"
DEFAULT_VAULT = HERE / BRAND
DEFAULT_MODELS = HERE / "models"
VAULT_ENV = f"{BRAND.upper()}_VAULT"
DB_ENV = f"{BRAND.upper()}_DB"
INSTANCE_ENV = "INSTANCE"
INSTANCE = (os.environ.get(INSTANCE_ENV, BRAND) or BRAND).strip() or BRAND
MCP_NAME = INSTANCE

DEFAULT_MODEL = "BAAI/bge-small-en-v1.5"   # 384-dim, ~64 MB, fast on CPU
DEFAULT_RERANKER = "Xenova/ms-marco-MiniLM-L-6-v2"   # cross-encoder, ~80 MB; "none" disables
RERANK_POOL = 20      # how many fused candidates the reranker re-scores

SKIP_DIRS = {".obsidian", ".git", ".venv", "venv", "env", "site-packages",
             "__pycache__", "node_modules", ".trash", ".DS_Store"}
DEFAULT_EXTS = {".md", ".txt"}

MAX_CHARS = 1400      # target chunk size
OVERLAP_CHARS = 200   # carried over when a long section is split

SCHEMA_VERSION = 2    # bump when the DB layout changes (forces a full rebuild on reuse)


# ───────────────────────────── loading ─────────────────────────────

def iter_files(root: Path, exts: set[str]):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not d.startswith("."))
        for fn in sorted(filenames):
            p = Path(dirpath) / fn
            if p.suffix.lower() in exts:
                yield p


def read_text(p: Path) -> str:
    if p.suffix.lower() == ".pdf":
        from pypdf import PdfReader  # optional dependency, host-side only
        reader = PdfReader(str(p))
        return "\n\n".join(f"# Page {i + 1}\n{(pg.extract_text() or '').strip()}"
                           for i, pg in enumerate(reader.pages))
    return p.read_text(errors="replace")


_WIKILINK = re.compile(r"!?\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|([^\]]+))?\]\]")
_LIST_ITEM = re.compile(r"\s*-\s+")


def _split_frontmatter(text: str) -> tuple[str, str]:
    """Return (frontmatter_body, rest); frontmatter_body is '' when there is none.
    Plain string scan — no regex backtracking over the whole document."""
    if not text.startswith("---\n"):
        return "", text
    end = text.find("\n---\n", 4)
    return ("", text) if end == -1 else (text[4:end], text[end + 5:])


def clean_markdown(text: str) -> str:
    _, body = _split_frontmatter(text)
    # [[note|alias]] -> alias, [[note]] -> note (keeps the words searchable)
    return _WIKILINK.sub(lambda m: (m.group(2) or m.group(1)).strip(), body)


def _tags_from_value(rest: str, following: list[str]) -> list[str]:
    if rest.startswith("[") and rest.endswith("]"):     # tags: [a, b]
        return rest[1:-1].split(",")
    if rest and not rest.startswith("#"):               # tags: a, b
        return rest.split(",")
    out = []                                            # tags:\n  - a\n  - b
    for line in following:
        if _LIST_ITEM.match(line):
            out.append(_LIST_ITEM.sub("", line, count=1))
        elif line.strip():
            break
    return out


def _parse_tags(frontmatter: str) -> list[str]:
    """Pull `tags:` out of YAML frontmatter without a yaml dependency."""
    lines = frontmatter.splitlines()
    raw: list[str] = []
    for i, line in enumerate(lines):
        m = re.match(r"\s*tags\s*:\s*(.*)", line, re.I)
        if m:
            raw = _tags_from_value(m.group(1).strip(), lines[i + 1:])
            break
    return [t for t in (x.strip().strip("\"'").lstrip("#").strip() for x in raw) if t]


def file_tags(p: Path) -> list[str]:
    """Frontmatter tags for a Markdown file (empty for other file types)."""
    if p.suffix.lower() != ".md":
        return []
    fm, _ = _split_frontmatter(p.read_text(errors="replace"))
    return _parse_tags(fm) if fm else []


# ───────────────────────────── chunking ─────────────────────────────

@dataclass
class Chunk:
    path: str
    heading: str
    text: str


_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")


def _sections(md: str):
    """Yield (heading_trail, body) per heading section; never splits inside ``` fences."""
    trail: list[tuple[int, str]] = []
    buf: list[str] = []
    in_fence = False

    def flush():
        body = "\n".join(buf).strip()
        if body:
            yield " > ".join(h for _, h in trail), body

    for line in md.splitlines():
        if line.lstrip().startswith(("```", "~~~")):
            in_fence = not in_fence
        m = None if in_fence else _HEADING.match(line)
        if m:
            yield from flush()
            buf = []
            level, title = len(m.group(1)), m.group(2).strip()
            trail = [(lv, t) for lv, t in trail if lv < level] + [(level, title)]
        else:
            buf.append(line)
    yield from flush()


def _split_long(body: str):
    """Split an oversized section on blank lines (fence-aware), with a little overlap."""
    if len(body) <= MAX_CHARS:
        yield body
        return
    blocks, cur, in_fence = [], [], False
    for line in body.splitlines():
        if line.lstrip().startswith(("```", "~~~")):
            in_fence = not in_fence
        if not line.strip() and not in_fence and cur:
            blocks.append("\n".join(cur)); cur = []
        else:
            cur.append(line)
    if cur:
        blocks.append("\n".join(cur))

    piece = ""
    for b in blocks:
        if piece and len(piece) + len(b) + 2 > MAX_CHARS:
            yield piece
            piece = piece[-OVERLAP_CHARS:] + "\n…\n" + b
        else:
            piece = f"{piece}\n\n{b}" if piece else b
    if piece:
        yield piece


def chunk_file(root: Path, p: Path) -> list[Chunk]:
    rel = str(p.relative_to(root))
    text = read_text(p)
    if p.suffix.lower() == ".md":
        text = clean_markdown(text)
    out = []
    for heading, body in _sections(text):
        for piece in _split_long(body):
            if len(piece.strip()) >= 20:
                out.append(Chunk(rel, heading, piece.strip()))
    return out


def embed_input(c: Chunk) -> str:
    """What gets embedded: file + heading trail give each chunk its context."""
    title = Path(c.path).stem.replace("-", " ").replace("_", " ")
    return f"{title} — {c.heading}\n\n{c.text}" if c.heading else f"{title}\n\n{c.text}"


def format_search_hit(hit: dict, rank: int) -> str:
    return f"### [{rank}] {hit['path']} › {hit['heading'] or '(top)'}  (score {hit['score']})\n{hit['text']}"


def format_search_hits(hits: list[dict]) -> str:
    if not hits:
        return "no matches"
    return "\n\n".join(format_search_hit(hit, i) for i, hit in enumerate(hits, 1))


# ───────────────────────────── embedding ─────────────────────────────

class Embedder:
    def __init__(self, model: str = DEFAULT_MODEL, cache_dir: Path = DEFAULT_MODELS,
                 offline: bool = False):
        if offline:
            os.environ["HF_HUB_OFFLINE"] = "1"
        from fastembed import TextEmbedding
        self.model_name = model
        self.m = TextEmbedding(model_name=model, cache_dir=str(cache_dir))

    @staticmethod
    def _norm(vecs) -> np.ndarray:
        a = np.asarray(list(vecs), dtype=np.float32)
        return a / np.clip(np.linalg.norm(a, axis=1, keepdims=True), 1e-12, None)

    def passages(self, texts: list[str]) -> np.ndarray:
        return self._norm(self.m.passage_embed(texts))

    def query(self, text: str) -> np.ndarray:
        return self._norm(self.m.query_embed([text]))[0]


class Reranker:
    """Cross-encoder: reads (question, chunk) TOGETHER and scores how well the chunk
    answers it. Slower than vector search (one model pass per candidate), so it only
    re-scores the top RERANK_POOL candidates that hybrid search already found."""

    def __init__(self, model: str = DEFAULT_RERANKER, cache_dir: Path = DEFAULT_MODELS,
                 offline: bool = False):
        if offline:
            os.environ["HF_HUB_OFFLINE"] = "1"
        from fastembed.rerank.cross_encoder import TextCrossEncoder
        self.model_name = model
        self.m = TextCrossEncoder(model_name=model, cache_dir=str(cache_dir))

    def scores(self, query: str, docs: list[str]) -> list[float]:
        return [float(s) for s in self.m.rerank(query, docs)]


# ───────────────────────────── index (SQLite) ─────────────────────────────

SCHEMA = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE files (path TEXT PRIMARY KEY, sha256 TEXT);
CREATE TABLE chunks (id INTEGER PRIMARY KEY, path TEXT, heading TEXT, text TEXT, tags TEXT, emb BLOB);
CREATE VIRTUAL TABLE chunks_fts USING fts5(path, heading, text, tokenize='unicode61 remove_diacritics 2');
"""


def _load_reusable(db_path: Path, model: str, reranker: str):
    """Return {rel_path: (sha256, [(heading, text, tags, emb_bytes), ...])} from an
    existing index, but only if it's safe to reuse (same schema version, embedding
    model and reranker). Otherwise None → the caller rebuilds everything."""
    if not db_path.exists():
        return None
    try:
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.OperationalError:
        return None
    try:
        meta = {k: json.loads(v) for k, v in con.execute("SELECT key, value FROM meta")}
        if (meta.get("schema_version") != SCHEMA_VERSION
                or meta.get("model") != model or meta.get("reranker") != reranker):
            return None
        hashes = dict(con.execute("SELECT path, sha256 FROM files"))
        by_path: dict[str, list] = {}
        for path, heading, text, tags, emb in con.execute(
                "SELECT path, heading, text, tags, emb FROM chunks ORDER BY id"):
            by_path.setdefault(path, []).append((heading, text, tags, emb))
        return {p: (hashes[p], rows) for p, rows in by_path.items() if p in hashes}
    except sqlite3.OperationalError:
        return None
    finally:
        con.close()


def build(vault: Path, db_path: Path, model: str, exts: set[str], cache_dir: Path,
          log=print, reranker: str = DEFAULT_RERANKER, full: bool = False,
          embedder=None) -> dict:
    """Build (or incrementally refresh) the index. Unchanged files keep their existing
    embeddings; only new/changed files are re-embedded. `full=True` forces a rebuild.
    `embedder` may be injected (tests) to avoid loading the real model."""
    vault = vault.expanduser().resolve()
    files = list(iter_files(vault, exts))
    if not files:
        raise SystemExit(f"no {sorted(exts)} files under {vault}")

    old = None if full else _load_reusable(db_path, model, reranker)
    own_embedder = embedder is None

    digest = hashlib.sha256()
    file_hashes: dict[str, str] = {}
    reused: dict[str, list] = {}       # rel -> [(heading, text, tags, emb_bytes), ...]
    new_items: list[tuple[Chunk, str]] = []   # (chunk, space-joined tags) needing embedding
    reused_files = changed_files = 0

    for p in files:
        rel = str(p.relative_to(vault))
        raw = p.read_bytes()
        digest.update(raw)
        h = hashlib.sha256(raw).hexdigest()
        if old and rel in old and old[rel][0] == h:
            reused[rel] = old[rel][1]
            file_hashes[rel] = h
            reused_files += 1
            log(f"  reuse {len(old[rel][1]):4d} chunks  {rel}")
            continue
        try:
            cs = chunk_file(vault, p)
            tags = " ".join(file_tags(p))
        except Exception as e:  # a broken PDF shouldn't kill the build
            log(f"  ! skipped {rel}: {e}")
            continue
        file_hashes[rel] = h
        changed_files += 1
        for c in cs:
            new_items.append((c, tags))
        log(f"  {len(cs):4d} chunks  {rel}")

    vecs = np.zeros((0, 1), dtype=np.float32)
    if new_items:
        if own_embedder:
            log(f"embedding {len(new_items)} new/changed chunks with {model} …")
            embedder = Embedder(model, cache_dir)
        t0 = time.time()
        vecs = embedder.passages([embed_input(c) for c, _ in new_items])
        log(f"  done in {time.time() - t0:.1f}s (dim={vecs.shape[1]})")
    if own_embedder and reranker != "none" and new_items:
        log(f"fetching reranker {reranker} (so searches work offline) …")
        Reranker(reranker, cache_dir)

    dim = int(vecs.shape[1]) if len(vecs) else next(
        (len(np.frombuffer(rows[0][3], dtype=np.float32)) for rows in reused.values() if rows), 0)

    db_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = db_path.with_suffix(".tmp")
    tmp.unlink(missing_ok=True)
    con = sqlite3.connect(tmp)
    con.executescript(SCHEMA)

    nid = 0

    def insert(path, heading, text, tags, emb_bytes):
        nonlocal nid
        con.execute("INSERT INTO chunks VALUES (?,?,?,?,?,?)", (nid, path, heading, text, tags, emb_bytes))
        con.execute("INSERT INTO chunks_fts(rowid, path, heading, text) VALUES (?,?,?,?)",
                    (nid, path, heading, text))
        nid += 1

    for rel, rows in reused.items():
        for heading, text, tags, emb in rows:
            insert(rel, heading, text, tags, emb)
    for (c, tags), v in zip(new_items, vecs):
        insert(c.path, c.heading, c.text, tags, v.tobytes())

    con.executemany("INSERT INTO files VALUES (?,?)", list(file_hashes.items()))
    meta = {"model": model, "reranker": reranker, "dim": dim, "chunks": nid,
            "files": len(file_hashes), "reused_files": reused_files,
            "changed_files": changed_files, "schema_version": SCHEMA_VERSION,
            "built_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "content_sha256": digest.hexdigest()[:16], "vault_name": vault.name}
    con.executemany("INSERT INTO meta VALUES (?,?)", [(k, json.dumps(v)) for k, v in meta.items()])
    con.commit()
    con.close()
    os.replace(tmp, db_path)   # atomic: a half-built index never replaces a good one
    return meta


class Index:
    def __init__(self, db_path: Path = DEFAULT_DB, cache_dir: Path = DEFAULT_MODELS,
                 offline: bool = True, embedder=None):
        if not db_path.exists():
            raise SystemExit(f"index not found: {db_path} (run build_index.py on the host)")
        self.con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, check_same_thread=False)
        self.meta = {k: json.loads(v) for k, v in self.con.execute("SELECT key, value FROM meta")}
        rows = self.con.execute("SELECT id, path, heading, text, tags, emb FROM chunks ORDER BY id").fetchall()
        self.rows = [(r[0], r[1], r[2], r[3], r[4] or "") for r in rows]
        self.mat = (np.vstack([np.frombuffer(r[5], dtype=np.float32) for r in rows])
                    if rows else np.zeros((0, self.meta.get("dim", 1) or 1), dtype=np.float32))
        # An injected embedder (tests) also skips the reranker, which would need the model.
        self.emb = embedder or Embedder(self.meta["model"], cache_dir, offline=offline)
        rr = self.meta.get("reranker", "none")   # older indexes have no reranker entry
        self.reranker = Reranker(rr, cache_dir, offline=offline) if rr != "none" and embedder is None else None

    def close(self):
        self.con.close()

    def _vector(self, q: str, k: int) -> list[int]:
        scores = self.mat @ self.emb.query(q)
        return list(np.argsort(-scores)[:k])

    def _keyword(self, q: str, k: int) -> list[int]:
        terms = re.findall(r"[\w.:/-]{2,}", q)
        if not terms:
            return []
        fts_q = " OR ".join('"' + t.replace('"', '""') + '"' for t in terms)
        try:
            return [r[0] for r in self.con.execute(
                "SELECT rowid FROM chunks_fts WHERE chunks_fts MATCH ? ORDER BY bm25(chunks_fts) LIMIT ?",
                (fts_q, k))]
        except sqlite3.OperationalError:
            return []

    def search(self, q: str, k: int = 3, mode: str = "hybrid", path_filter: str | None = None,
               rerank: bool = True, tags: list[str] | None = None):
        """Stage 1: vector + keyword candidates, fused with Reciprocal Rank Fusion.
        Stage 2 (if a reranker is installed): cross-encoder re-scores the top RERANK_POOL.
        path_filter keeps only notes whose path contains it; tags keeps only chunks whose
        frontmatter tags include ALL of the requested tags."""
        pool = max(k * 4, RERANK_POOL)
        fused: dict[int, float] = {}
        if mode in ("hybrid", "vector"):
            for r, i in enumerate(self._vector(q, pool)):
                fused[int(i)] = fused.get(int(i), 0) + 1 / (60 + r)
        if mode in ("hybrid", "keyword"):
            for r, i in enumerate(self._keyword(q, pool)):
                fused[int(i)] = fused.get(int(i), 0) + 1 / (60 + r)

        want = set(tags or [])
        cands = [i for i, _ in sorted(fused.items(), key=lambda kv: -kv[1])
                 if (not path_filter or path_filter.lower() in self.rows[i][1].lower())
                 and (not want or want <= set(self.rows[i][4].split()))]

        if rerank and self.reranker and cands:
            cands = cands[:max(RERANK_POOL, k)]
            docs = [embed_input(Chunk(self.rows[i][1], self.rows[i][2], self.rows[i][3])) for i in cands]
            rs = self.reranker.scores(q, docs)
            order = sorted(range(len(cands)), key=lambda j: -rs[j])
            ranked = [(cands[j], round(rs[j], 2)) for j in order]
        else:
            ranked = [(i, round(fused[i] * 1000, 2)) for i in cands]

        # One hit per section: a long section is stored as several chunks, and returning two
        # halves of the same section wastes a result slot (and tokens). Keep the best-ranked one.
        out, seen = [], set()
        for i, s in ranked:
            key = (self.rows[i][1], self.rows[i][2])
            if key in seen:
                continue
            seen.add(key)
            out.append({"path": self.rows[i][1], "heading": self.rows[i][2], "score": s,
                        "text": self.rows[i][3], "tags": self.rows[i][4]})
            if len(out) >= k:
                break
        return out

    def list_notes(self):
        return [{"path": p, "chunks": n} for p, n in
                self.con.execute("SELECT path, COUNT(*) FROM chunks GROUP BY path ORDER BY path")]

    def read_note(self, path: str) -> str:
        rows = self.con.execute("SELECT heading, text FROM chunks WHERE path = ? ORDER BY id", (path,)).fetchall()
        if not rows:
            raise ValueError(f"no note {path!r}; use list_notes")
        parts, last = [], None
        for heading, text in rows:
            if heading and heading != last:
                parts.append(f"## {heading}")
                last = heading
            parts.append(text)
        return "\n\n".join(parts)
