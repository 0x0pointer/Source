#!/usr/bin/env python3
"""Measure search quality against a fixed question set (eval/questions.json).

    .venv/bin/python eval_retrieval.py                 # compare configs on the current index
    .venv/bin/python eval_retrieval.py --rerankers Xenova/ms-marco-MiniLM-L-6-v2,jinaai/jina-reranker-v1-tiny-en

A question counts as a hit when a returned chunk comes from the expected note AND its
heading trail ends with the expected heading (or matches an "also_acceptable" section).
  hit@1  right section ranked first        hit@3  right section in the top 3 (default k)
  MRR    1/rank of the first right section, averaged (1.0 = always first)
Re-run it after big note changes, or before switching models.
"""
import argparse
import json
import os
import time
from pathlib import Path

os.environ.setdefault("HF_HUB_OFFLINE", "1")
import source_rag as R  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--questions", default=str(R.HERE / "eval" / "questions.json"))
ap.add_argument("--rerankers", default=R.DEFAULT_RERANKER)
ap.add_argument("--verbose", "-v", action="store_true", help="print every miss")
a = ap.parse_args()

qs = [q for q in json.loads(Path(a.questions).read_text()) if q.get("ok", True)]
idx = R.Index()


def norm(s: str) -> str:
    return " ".join(s.lower().replace("*", "").replace("`", "").split())


def is_hit(q, h) -> bool:
    last = norm(h["heading"].split(" > ")[-1]) if h["heading"] else ""
    targets = [(q["expected_path"], q["expected_heading"])]
    for alt in q.get("also_acceptable", []):
        if "::" in alt:
            p, hd = alt.split("::", 1)
            targets.append((p.strip(), hd.strip().lstrip("#").strip()))
    return any(h["path"] == p and (last == norm(hd) or norm(hd) in norm(h["heading"])) for p, hd in targets)


def run(name, **kw):
    hits1 = hits3 = 0
    mrr = 0.0
    chars = 0
    t0 = time.time()
    by_kind: dict[str, list[int]] = {}
    misses = []
    for q in qs:
        res = idx.search(q["query"], k=10, **kw)
        rank = next((i + 1 for i, h in enumerate(res) if is_hit(q, h)), None)
        hits1 += rank == 1
        hits3 += bool(rank and rank <= 3)
        mrr += 1 / rank if rank else 0
        chars += sum(len(h["text"]) for h in res[:3])
        by_kind.setdefault(q["kind"], []).append(bool(rank and rank <= 3))
        if not (rank and rank <= 3):
            misses.append((q, res[:3]))
    n = len(qs)
    kinds = "  ".join(f"{k}:{sum(v)}/{len(v)}" for k, v in sorted(by_kind.items()))
    print(f"{name:42s} hit@1 {hits1 / n:5.0%}  hit@3 {hits3 / n:5.0%}  MRR {mrr / n:.2f}  "
          f"{(time.time() - t0) / n * 1000:5.0f} ms/q  ~{chars / n / 4:4.0f} tok@3   [{kinds}]")
    if a.verbose:
        for q, res in misses:
            print(f"    MISS [{q['kind']}] {q['query']!r}\n         want {q['expected_path']} › {q['expected_heading']}")
            for h in res:
                print(f"         got  {h['path']} › {h['heading'].split(' > ')[-1] if h['heading'] else '(top)'}")


print(f"{len(qs)} questions · index: {idx.meta['chunks']} chunks · embed model {idx.meta['model']}\n")
run("keyword only (BM25)", mode="keyword", rerank=False)
run("vector only", mode="vector", rerank=False)
run("hybrid (RRF), no rerank", mode="hybrid", rerank=False)
for rr in a.rerankers.split(","):
    idx.reranker = R.Reranker(rr, offline=True)
    run(f"hybrid + rerank {rr.split('/')[-1]}", mode="hybrid", rerank=True)
