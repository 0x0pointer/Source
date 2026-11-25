#!/usr/bin/env python3
"""Search the index from a terminal.

    python query.py "how do I roll back a failed migration"
    python query.py -k 8 --mode keyword "ERR_CONN_4021"
    python query.py --tag reference "entry shape"
    python query.py --list
"""
import argparse
from pathlib import Path

import source_rag as R


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("query", nargs="*")
    ap.add_argument("-k", type=int, default=3)
    ap.add_argument("--mode", choices=["hybrid", "vector", "keyword"], default="hybrid")
    ap.add_argument("--path", help="only notes whose path contains this")
    ap.add_argument("--tag", action="append", help="only chunks with this frontmatter tag (repeat = all of them)")
    ap.add_argument("--no-rerank", action="store_true", help="skip the cross-encoder (faster, less precise)")
    ap.add_argument("--db", default=str(R.DEFAULT_DB))
    ap.add_argument("--list", action="store_true", help="list indexed notes")
    a = ap.parse_args(argv)

    idx = R.Index(Path(a.db))
    if a.list:
        for n in idx.list_notes():
            print(f"{n['chunks']:4d}  {n['path']}")
        return
    if not a.query:
        ap.error("give a query or --list")

    hits = idx.search(" ".join(a.query), a.k, a.mode, a.path, rerank=not a.no_rerank, tags=a.tag)
    for i, h in enumerate(hits, 1):
        tag_note = f"   #{' #'.join(h['tags'].split())}" if h["tags"] else ""
        print(f"\n━━ {i}. {h['path']}  ›  {h['heading'] or '(top)'}   [{h['score']}]{tag_note}")
        print(h["text"][:900] + (" …" if len(h["text"]) > 900 else ""))


if __name__ == "__main__":
    main()
