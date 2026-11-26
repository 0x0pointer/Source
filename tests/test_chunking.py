"""Unit tests for the parts of source_rag that don't need the real embedding model.

A FakeEmbedder (deterministic, no fastembed) lets us exercise the real build / incremental
/ search / tag-filter code paths too, so these run anywhere numpy + pytest are installed —
no model download, no onnxruntime.
"""
import importlib
import hashlib

import numpy as np

import source_rag as R


# ───────────────────────── fake embedder (dependency injection) ─────────────────────────

class FakeEmbedder:
    model_name = "fake"
    dim = 16

    def _vec(self, text: str) -> np.ndarray:
        seed = int.from_bytes(hashlib.sha256(text.encode()).digest()[:8], "big")
        v = np.random.default_rng(seed).standard_normal(self.dim).astype(np.float32)
        return v / (np.linalg.norm(v) or 1.0)

    def passages(self, texts):
        return (np.vstack([self._vec(t) for t in texts]) if texts
                else np.zeros((0, self.dim), dtype=np.float32))

    def query(self, text):
        return self._vec(text)


# ───────────────────────── frontmatter / tags ─────────────────────────

def test_split_frontmatter():
    fm, rest = R._split_frontmatter("---\ntags: [a]\n---\n# Title\nbody")
    assert fm == "tags: [a]"
    assert rest == "# Title\nbody"
    assert R._split_frontmatter("no frontmatter") == ("", "no frontmatter")
    assert R._split_frontmatter("---\nunterminated\n") == ("", "---\nunterminated\n")


def test_parse_tags_inline_list():
    assert R._parse_tags('tags: [alpha, "beta", note]') == ["alpha", "beta", "note"]


def test_parse_tags_csv():
    assert R._parse_tags("tags: alpha, beta") == ["alpha", "beta"]


def test_parse_tags_block_list():
    assert R._parse_tags("title: x\ntags:\n  - alpha\n  - beta\nother: y") == ["alpha", "beta"]


def test_parse_tags_strips_hash_and_none():
    assert R._parse_tags("tags: [#alpha, beta]") == ["alpha", "beta"]
    assert R._parse_tags("no tags here") == []


# ───────────────────────── markdown cleaning ─────────────────────────

def test_clean_markdown_strips_frontmatter_and_wikilinks():
    out = R.clean_markdown("---\ntags: [x]\n---\nsee [[METHODOLOGY|the playbook]] and [[QUICKSTART]]")
    assert out == "see the playbook and QUICKSTART"


# ───────────────────────── sectioning / chunking ─────────────────────────

def test_sections_are_fence_aware():
    md = "# A\n\ntext\n\n```\n# not a heading\nmore\n```\n\n# B\n\nend"
    secs = list(R._sections(md))
    assert [h for h, _ in secs] == ["A", "B"]


def test_heading_trail_is_hierarchical():
    md = "# Top\n\nintro\n\n## Sub\n\ndetail"
    trails = [h for h, _ in R._sections(md)]
    assert trails == ["Top", "Top > Sub"]


def test_split_long_overlaps():
    block = ("word " * 60).strip()           # ~300 chars
    body = "\n\n".join([block] * 8)           # ~2400 chars > MAX_CHARS
    pieces = list(R._split_long(body))
    assert len(pieces) >= 2
    assert any("…" in p for p in pieces[1:])  # overlap marker carried across the split


def test_chunk_file_drops_tiny_sections(tmp_path):
    p = tmp_path / "n.md"
    p.write_text("# Real Heading\n\nThis body is clearly long enough to keep.\n\n# x\n\nhi")
    chunks = R.chunk_file(tmp_path, p)
    assert any(c.heading == "Real Heading" for c in chunks)
    assert all(len(c.text) >= 20 for c in chunks)


def test_embed_input_uses_title_and_heading():
    c = R.Chunk("refs/my-note.md", "Some Heading", "the body")
    assert R.embed_input(c).startswith("my note — Some Heading")


def test_instance_defaults_to_source_and_honors_env_on_reload(monkeypatch):
    monkeypatch.delenv("INSTANCE", raising=False)
    reloaded = importlib.reload(R)
    assert reloaded.INSTANCE == "source"
    assert reloaded.MCP_NAME == "source"

    monkeypatch.setenv("INSTANCE", "eng-a")
    reloaded = importlib.reload(R)
    assert reloaded.INSTANCE == "eng-a"
    assert reloaded.MCP_NAME == "eng-a"

    monkeypatch.delenv("INSTANCE", raising=False)
    importlib.reload(R)


def test_format_search_hits_matches_existing_mcp_shape():
    hits = [
        {"path": "guide.md", "heading": "Guide", "score": 12.34, "text": "First result", "tags": "alpha"},
        {"path": "notes/top.md", "heading": "", "score": 8.0, "text": "Second result", "tags": ""},
    ]

    assert R.format_search_hits(hits) == (
        "### [1] guide.md › Guide  (score 12.34)\nFirst result\n\n"
        "### [2] notes/top.md › (top)  (score 8.0)\nSecond result"
    )
    assert R.format_search_hits([]) == "no matches"


# ───────────────────────── build + search (fake embedder) ─────────────────────────

def _vault(tmp_path):
    v = tmp_path / "vault"
    (v / "refs").mkdir(parents=True)
    (v / "guide.md").write_text(
        "---\ntags: [alpha, guide]\n---\n# Guide\n\n"
        "The cache key omits the locale, so every request gets the English response.\n")
    (v / "refs" / "ref.md").write_text(
        "---\ntags: [reference]\n---\n# Reference\n\n"
        "Reproduce the flaky bug reliably before changing anything. Token ERR_CONN_4021.\n")
    return v


def test_build_and_search(tmp_path):
    fake = FakeEmbedder()
    db = tmp_path / "idx.sqlite"
    meta = R.build(_vault(tmp_path), db, "fake", {".md"}, tmp_path / "models",
                   log=lambda *a: None, reranker="none", embedder=fake)
    assert meta["chunks"] >= 2
    assert meta["changed_files"] == 2 and meta["reused_files"] == 0

    idx = R.Index(db, embedder=fake)
    # keyword search is deterministic (doesn't depend on the fake vectors being meaningful)
    hits = idx.search("locale", k=3, mode="keyword", rerank=False)
    assert any("locale" in h["text"] for h in hits)
    # exact token via keyword
    assert idx.search("ERR_CONN_4021", k=3, mode="keyword", rerank=False)
    # hybrid path runs without error even with a fake embedder
    assert isinstance(idx.search("locale", k=3, mode="hybrid", rerank=False), list)


def test_path_and_tag_filters(tmp_path):
    fake = FakeEmbedder()
    db = tmp_path / "idx.sqlite"
    R.build(_vault(tmp_path), db, "fake", {".md"}, tmp_path / "models",
            log=lambda *a: None, reranker="none", embedder=fake)
    idx = R.Index(db, embedder=fake)

    only_refs = idx.search("bug", k=5, mode="keyword", rerank=False, path_filter="refs")
    assert only_refs and all(h["path"].startswith("refs/") for h in only_refs)

    tagged = idx.search("cache locale bug", k=5, mode="keyword", rerank=False, tags=["alpha"])
    assert tagged and all("alpha" in h["tags"].split() for h in tagged)

    assert idx.search("cache", k=5, mode="keyword", rerank=False, tags=["nonexistent"]) == []


def test_incremental_reuse(tmp_path):
    fake = FakeEmbedder()
    v = _vault(tmp_path)
    db = tmp_path / "idx.sqlite"
    kw = dict(log=lambda *a: None, reranker="none", embedder=fake)

    R.build(v, db, "fake", {".md"}, tmp_path / "models", **kw)
    # nothing changed → everything reused, nothing re-embedded
    m2 = R.build(v, db, "fake", {".md"}, tmp_path / "models", **kw)
    assert m2["reused_files"] == 2 and m2["changed_files"] == 0

    # edit one file → only that file is re-chunked/re-embedded
    (v / "guide.md").write_text("---\ntags: [alpha]\n---\n# Guide\n\nNew content about migrations.\n")
    m3 = R.build(v, db, "fake", {".md"}, tmp_path / "models", **kw)
    assert m3["changed_files"] == 1 and m3["reused_files"] == 1

    # --full ignores the cache and rebuilds everything
    m4 = R.build(v, db, "fake", {".md"}, tmp_path / "models", full=True, **kw)
    assert m4["reused_files"] == 0 and m4["changed_files"] == 2


def test_model_change_forces_full_rebuild(tmp_path):
    fake = FakeEmbedder()
    v = _vault(tmp_path)
    db = tmp_path / "idx.sqlite"
    R.build(v, db, "fake", {".md"}, tmp_path / "models", log=lambda *a: None,
            reranker="none", embedder=fake)
    # a different model name must invalidate the cache (embeddings aren't comparable)
    m = R.build(v, db, "other-model", {".md"}, tmp_path / "models", log=lambda *a: None,
                reranker="none", embedder=fake)
    assert m["reused_files"] == 0 and m["changed_files"] == 2
