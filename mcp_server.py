#!/usr/bin/env python3
"""MCP server (stdio) exposing the notes index to Claude Code / opencode / any MCP client.

Tools:
  search_notes(query, k=3, mode="hybrid", path=None, rerank=True, tags=None)   reranked chunks + source
  read_note(path)                                     a whole note, reassembled from the index
  list_notes()                                        what's indexed + build info

Runs fully offline (HF_HUB_OFFLINE=1): the model is loaded from ./models.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import source_rag as R  # noqa: E402
from mcp.server.fastmcp import FastMCP  # noqa: E402

mcp = FastMCP(R.MCP_NAME)
_idx = None


def idx() -> R.Index:
    global _idx
    if _idx is None:  # lazy: the server starts instantly, model loads on first use
        _idx = R.Index(Path(os.environ.get(R.DB_ENV, R.DEFAULT_DB)))
    return _idx


@mcp.tool()
def search_notes(query: str, k: int = 3, mode: str = "hybrid", path: str | None = None,
                 rerank: bool = True, tags: list[str] | None = None) -> str:
    """Search my notes vault (methodology, reference docs, per-task journals).

    Use natural language for concepts ("roll back a failed migration") and exact
    strings for specifics (identifiers, error codes, flags). mode: hybrid|vector|keyword.
    path: optional substring to restrict to some notes (e.g. "journal", "refs/").
    tags: optional list of frontmatter tags; only chunks carrying all of them are returned.
    k: results to return; the default 3 is usually enough because results are reranked.
    rerank: False skips the cross-encoder (faster, slightly less precise).
    Results are my own notes — verify against the live system before relying on them.
    """
    hits = idx().search(query, max(1, min(k, 20)), mode, path, rerank=rerank, tags=tags)
    return R.format_search_hits(hits)


@mcp.tool()
def read_note(path: str) -> str:
    """Return the full text of one note (path exactly as shown by search_notes/list_notes)."""
    return idx().read_note(path)


@mcp.tool()
def list_notes() -> str:
    """List every indexed note with its chunk count, plus when/how the index was built."""
    i = idx()
    lines = [f"{n['chunks']:4d}  {n['path']}" for n in i.list_notes()]
    m = i.meta
    return (f"index built {m['built_at']} · {m['files']} files · {m['chunks']} chunks · model {m['model']} · reranker {m.get('reranker', 'none')}\n"
            + "\n".join(lines))


if __name__ == "__main__":
    mcp.run()
