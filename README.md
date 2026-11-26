# Source

Local, offline search over a folder of Markdown notes, for Claude Code / opencode / any MCP client.

This is a **skeleton**: a working tool plus an empty-but-structured example vault, meant to be copied
and pointed at your own notes. The notes in `source/` are a plain folder of Markdown (it also opens as
an [Obsidian](https://obsidian.md) vault, but Obsidian isn't needed). Source turns that folder
into a small search index. A coding agent can then ask *"how do I verify a fix actually worked?"* in
the middle of a task and get back the two or three note sections that answer it, with their source —
a few hundred tokens instead of reading every note.

- **Private:** notes never leave the machine. No API keys, no cloud, no telemetry. The only network
  access is a one-time model download from Hugging Face during the first build.
- **Small:** a few hundred lines of Python, two local models (~152 MB) and one SQLite file.
- **Incremental:** editing one note and rebuilding only re-embeds that note.
- **Measured:** ship a question set in `eval/questions.json` and `eval_retrieval.py` tells you how
  often the right section comes back — so you can tune retrieval for *your* notes, not guess.

## How it works (short version)

```
source/*.md
   │ build_index.py   (incremental: unchanged files keep their embeddings)
   ├─ 1. split each note at its headings  → "chunks"
   ├─ 2. embed each chunk (bge-small)     → 384 numbers that capture its meaning
   └─ 3. store text + numbers + a keyword index in index/source.sqlite

question ─▶ search_notes()
   ├─ stage 1: meaning search (vectors) + exact-word search (BM25)
   │           merged with Reciprocal Rank Fusion  → ~20 candidates
   ├─ stage 2: a cross-encoder (MiniLM reranker) reads question + each candidate
   │           together and re-scores them      → best first
   └─ one result per note section, top k=3 returned with path › heading
```

Hybrid search matters because the two halves catch different things: meaning search finds *"roll back
a failed migration"* when the note says *"revert a broken deploy"*; keyword search finds an exact
token like `ERR_CONN_4021`. You want both, then a reranker to order what's left.

## Install

Requires Python 3.11+ and about 200 MB of disk space. The first build needs internet access;
everything after that runs offline.

```bash
git clone <your-remote>/source-rag.git ~/source-rag && cd ~/source-rag
make install                            # creates .venv and installs deps
make build                              # downloads models once (~152 MB), then indexes in seconds
make query Q="how do I verify a fix worked"
```

Prefer to do it by hand, or want the `source-build` / `source-query` / `source-http` commands on your PATH?

```bash
python3 -m venv .venv
.venv/bin/pip install -e .              # installs the package + the console scripts
.venv/bin/source-build
.venv/bin/source-query "how do I verify a fix worked"
.venv/bin/source-http --port 7801
```

If your platform blocks system-wide `pip install` (e.g. Debian/Kali PEP 668), always run things
through `.venv/bin/…`.

> **Heads-up on very new Pythons:** `fastembed` pulls in `onnxruntime`, which can lag the newest
> CPython release by a few months. If `pip install` can't resolve `onnxruntime`, use a Python in the
> 3.11–3.13 range. (The unit tests don't need either — see [Development](#development).)

### Connect it to your agent

**Claude Code** (available in every project):
```bash
claude mcp add source -s user -- ~/source-rag/.venv/bin/python ~/source-rag/mcp_server.py
claude mcp list                         # should show source ✓ connected
```

**opencode**: add this to `~/.config/opencode/opencode.json`, using absolute paths:
```json
{
  "mcp": {
    "source": {
      "type": "local",
      "enabled": true,
      "command": ["/home/you/source-rag/.venv/bin/python", "/home/you/source-rag/mcp_server.py"]
    }
  }
}
```

Then start a new session and ask something like *"check my notes for how to reproduce a flaky bug"*.
The agent calls `search_notes` by itself.

### Run multiple localhost instances for agent-smith

Source can also expose one `{vault, db}` pair over a tiny stdlib-only HTTP server, so agent-smith can
bind a different Source instance per engagement or environment.

> **Local trust boundary only:** `serve_http.py` binds to `127.0.0.1` on purpose. Do not expose it on a
> network interface; it has no authentication and `/ingest` can write notes into the selected vault.

Run one instance directly:

```bash
.venv/bin/python serve_http.py \
  --vault ~/engagements/acme/source \
  --db ~/engagements/acme/index/source.sqlite \
  --port 7801
```

Or use the helper that sets `INSTANCE`, `SOURCE_VAULT`, and `SOURCE_DB` for you:

```bash
./run_instance.sh acme-prod \
  --vault ~/engagements/acme/source \
  --db ~/engagements/acme/index/source.sqlite \
  --port 7801

./run_instance.sh acme-stage \
  --vault ~/engagements/acme-stage/source \
  --db ~/engagements/acme-stage/index/source.sqlite \
  --port 7802
```

agent-smith can then map `acme-prod -> http://127.0.0.1:7801` and
`acme-stage -> http://127.0.0.1:7802` in its own `sources.yaml`.

Endpoint shapes:

```http
GET /health
=> {"ready":true,"instance":"acme-prod","vault":"/...","db":"/...","meta":{...}}

GET /list
=> {"ready":true,"instance":"acme-prod","vault":"/...","db":"/...","meta":{...},
    "notes":[{"path":"findings/host-1.md","chunks":1}]}

GET /search?q=ssrf&k=3&mode=keyword&path=findings&tags=finding,critical
=> {"results":[{"rank":1,"path":"findings/host-1.md","heading":"Host 1","score":7.5,
                "text":"SSRF on the admin endpoint.","tags":"finding critical",
                "display":"### [1] findings/host-1.md › Host 1  (score 7.5)\nSSRF on the admin endpoint."}],
    "display":"### [1] findings/host-1.md › Host 1  (score 7.5)\nSSRF on the admin endpoint."}

POST /ingest
{"notes":[{"id":"findings/host-1","title":"Host 1","tags":["finding"],"text":"SSRF on the admin endpoint."}]}
=> writes `vault/findings/host-1.md`, incrementally rebuilds the index, and reloads it in-place
```

## Usage

### MCP tools (what the agent sees)

| Tool | What it does |
|---|---|
| `search_notes(query, k=3, mode="hybrid", path=None, rerank=True, tags=None)` | The best-matching note sections, each with `path › heading` and a score |
| `read_note(path)` | One whole note, when a section isn't enough |
| `list_notes()` | Every indexed note, plus when the index was built and with which models |

`mode` is `hybrid` (default), `vector` (meaning only) or `keyword` (exact words only).
`path` restricts to notes whose path contains that text (e.g. `"journal"`); `tags` restricts to
chunks whose frontmatter tags include all of the given tags.

### Terminal

```bash
.venv/bin/python query.py "how do I verify a fix worked"
.venv/bin/python query.py -k 5 --mode keyword "ERR_CONN_4021"
.venv/bin/python query.py --path refs/ "reference entry shape"
.venv/bin/python query.py --tag reference "entry shape"
.venv/bin/python query.py --no-rerank "..."     # skip stage 2 (a little faster)
.venv/bin/python query.py --list
```

### Keeping the index current

```bash
.venv/bin/python build_index.py          # incremental: only re-embeds changed notes
.venv/bin/python build_index.py --full   # rebuild everything from scratch
.venv/bin/python build_index.py --watch  # stay running, rebuild on every save
```

The MCP server loads the index on first use. Restart the agent session (or `/mcp` → reconnect in
Claude Code) to pick up a rebuilt index.

`serve_http.py` reloads its index after every successful `/ingest`, so new notes become searchable
without restarting the process.

### Tagging notes

Add YAML frontmatter tags to a note and they become a filter dimension (and they're stripped from the
indexed text, so they never pollute search):

```markdown
---
tags: [playbook, checklist]
---
# My note
```

Then `query.py --tag playbook "…"` or `search_notes(..., tags=["playbook"])`.

## Development

The chunking, indexing and search logic is covered by unit tests that inject a fake embedder, so they
run **without** the heavy ML dependencies or any model download — handy on a bleeding-edge Python too.

```bash
make install-dev        # adds pytest
make test               # == .venv/bin/python -m pytest
```

`.github/workflows/ci.yml` runs the same tests on Python 3.11 and 3.12.

## Quality

`eval_retrieval.py` runs the questions in `eval/questions.json` against the index and reports how
often the right section is ranked first (`hit@1`) and in the top 3 (`hit@3`). The skeleton ships a
handful of example questions across three kinds — **paraphrase** (deliberately avoids the note's
words), **exact_term** (identifiers, codes) and **scenario** (describes a situation) — so you can see
the shape. Replace them with questions about your own notes.

```bash
make eval               # == .venv/bin/python eval_retrieval.py -v   (-v lists every miss)
```

Typically each stage helps: keyword-only and vector-only trail hybrid (RRF), and adding the reranker
on top gives the best ordering for a few hundred ms per query. Run it on your own vault to get real
numbers before trusting any single configuration.

## Configuration

| Setting | How | Default |
|---|---|---|
| Notes folder | `build_index.py --vault PATH` or `SOURCE_VAULT=` | `./source` |
| File types | `--ext .md,.txt,.pdf` | `.md,.txt` |
| Embedding model | `--model NAME` (any fastembed text model) | `BAAI/bge-small-en-v1.5` |
| Reranker | `--reranker NAME`, or `none` to disable | `Xenova/ms-marco-MiniLM-L-6-v2` |
| Index location | `build_index.py --db PATH`, `SOURCE_DB=` for the MCP server | `./index/source.sqlite` |
| Instance name | `INSTANCE=` (used by MCP and `/health`) | `source` |

The models are recorded in the index, and queries always use the ones the index was built with.
Changing a model therefore means a full rebuild (the incremental cache invalidates automatically).

Skipped while indexing: `.obsidian/`, `.git/`, `.venv/`, `site-packages/`, `node_modules/`,
`__pycache__/` and any other hidden folder.

## Files

```
source/              the vault (source of truth) — see source/README.md for its structure
source_rag.py        everything: chunking, embedding, SQLite index, hybrid search, rerank
build_index.py       builds index/source.sqlite (incremental; --full, --watch)
query.py             terminal search (--mode, --path, --tag, --list)
mcp_server.py        MCP server (stdio) for Claude Code / opencode
serve_http.py        stdlib localhost HTTP service (/health, /list, /search, /ingest)
run_instance.sh      helper to launch one named HTTP instance under .venv
eval_retrieval.py    quality benchmark
eval/questions.json  the benchmark's questions with expected answers
tests/               unit tests (run without the ML deps, via a fake embedder)
examples/            optional helpers (e.g. make_sample_pdf.py to try PDF indexing)
pyproject.toml       packaging + console scripts + pytest config
Makefile             common tasks (install, build, watch, query, test, eval, clean)
requirements*.txt    runtime deps, and -dev adds pytest
.github/workflows/   CI (runs the unit tests)
index/  models/      built locally, git-ignored (the index holds your notes' full text)
```

## Troubleshooting

| Symptom | Fix |
|---|---|
| `index not found` | Run `build_index.py` first (`index/` isn't in git, so each machine builds its own). |
| `pip` can't resolve `onnxruntime` | Your Python is likely too new for a fastembed wheel yet — use Python 3.11–3.13. |
| Model errors on an offline machine | Searches load models from `./models` only. Run `build_index.py` once while online. |
| `No module named 'mcp.server.fastmcp'` | You have MCP SDK 2.x. Reinstall with `pip install "mcp<2"` (pinned in requirements). |
| `externally-managed-environment` | You ran system `pip`. Use `.venv/bin/pip`. |
| Agent doesn't use the tool | Check `claude mcp list`, then ask explicitly: "search my notes for …". |
| Results look outdated | Rebuild the index and reconnect the MCP server. |

## Limits

- It only finds what's written down. Results are your notes, not ground truth — verify against the
  live system.
- Images and screenshots in the vault aren't indexed. PDFs are, if you add `--ext .pdf`.
- `read_note` rebuilds a note from its chunks, so split sections can repeat ~200 characters at the
  joins.
- English-tuned models by default. Notes in other languages are found by keyword, less well by
  meaning — swap the embedding model if that matters.
```
