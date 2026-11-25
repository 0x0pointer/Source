#!/usr/bin/env python3
"""Build (or incrementally refresh) the embedding index on the HOST.

    .venv/bin/python build_index.py                       # vault = $SOURCE_VAULT or ./source
    .venv/bin/python build_index.py --vault ~/source --ext .md,.txt,.pdf
    .venv/bin/python build_index.py --full                # ignore the cache, rebuild everything
    .venv/bin/python build_index.py --watch               # rebuild automatically on file change

By default the build is incremental: unchanged files keep their existing embeddings, so a
rebuild after editing one note only re-embeds that note.
"""
import argparse
import os
import time
from pathlib import Path

import source_rag as R


def _snapshot(vault: Path, exts: set[str]) -> dict[str, float]:
    """path -> mtime for every indexed file (detects edits, adds and deletes)."""
    return {str(p): p.stat().st_mtime for p in R.iter_files(vault, exts)}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--vault", default=os.environ.get(R.VAULT_ENV, str(R.DEFAULT_VAULT)))
    ap.add_argument("--db", default=str(R.DEFAULT_DB))
    ap.add_argument("--model", default=R.DEFAULT_MODEL)
    ap.add_argument("--reranker", default=R.DEFAULT_RERANKER, help='cross-encoder model, or "none"')
    ap.add_argument("--ext", default=",".join(sorted(R.DEFAULT_EXTS)),
                    help="comma-separated extensions (add .pdf to include PDFs)")
    ap.add_argument("--full", action="store_true", help="force a full rebuild (ignore the incremental cache)")
    ap.add_argument("--watch", action="store_true", help="keep running and rebuild when files change")
    ap.add_argument("--interval", type=float, default=2.0, help="--watch poll interval in seconds")
    a = ap.parse_args(argv)

    vault = Path(a.vault).expanduser()
    exts = {e if e.startswith(".") else f".{e}" for e in a.ext.lower().split(",") if e}

    def once(full: bool):
        print(f"vault: {vault}  exts: {sorted(exts)}")
        meta = R.build(vault, Path(a.db), a.model, exts, R.DEFAULT_MODELS, reranker=a.reranker, full=full)
        print(f"index written: {a.db}")
        for k, v in meta.items():
            print(f"  {k:15s} {v}")
        return meta

    once(a.full)
    if not a.watch:
        return

    print(f"\nwatching {vault} (every {a.interval}s) — Ctrl-C to stop")
    last = _snapshot(vault, exts)
    try:
        while True:
            time.sleep(a.interval)
            cur = _snapshot(vault, exts)
            if cur != last:
                print("\nchange detected, rebuilding …")
                once(False)
                last = cur
    except KeyboardInterrupt:
        print("\nstopped.")


if __name__ == "__main__":
    main()
