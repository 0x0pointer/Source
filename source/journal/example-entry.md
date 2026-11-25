---
tags: [journal, troubleshooting]
---
# Run — example entry (2026-01-15)

> **Skeleton.** This shows what one run log looks like and how it feeds the methodology. A journal
> entry is the raw, honest record of a single task: what you tried, what happened, what actually
> worked. It's allowed to be messy. Only the **confirmed** parts get promoted up into
> `../METHODOLOGY.md` / `../refs/`.

Context: example service v2.3, default config, single-node. Inputs: a request that returns the wrong
cached value for non-default locales.
Goal: the response matches the locale of the request.

## Phase 1 — Reproduce
- Repro (reliable, 5/5):
  ```
  curl -s 'http://localhost:8080/greeting?locale=fr' | head -1
  ```
- Expected: a French greeting. Actual: the English one, every time after the first English request.
- Exact output included the header `X-Cache: HIT` and the token `ERR_CONN_4021` in the debug log — the
  kind of exact string worth recording verbatim, because that's what keyword search matches later.

## Phase 2 — Diagnose
- Hypothesis 1: translation data missing for `fr`. Check: direct lookup returns the French string →
  **killed** (data is fine).
- Hypothesis 2: the cache key ignores locale. Check: two requests with different `locale` produce the
  same cache key in the log → **confirmed**.
- Root cause: the cache key is built from the path only and omits the `locale` query parameter, so the
  first response is served to every locale.

## Phase 3 — Fix
- Change: include `locale` in the cache key.
- Rejected: disabling the cache for this route (fixes the symptom, loses the performance; doesn't
  address the cause).

## Phase 4 — Verify
- Re-ran the Phase 1 repro: `locale=fr` now returns the French greeting, `X-Cache: MISS` on first
  call then `HIT` on the second same-locale call.
- Neighbour check: `locale=de` and the default (no `locale`) still correct.

## What cleared each phase (promote the CONFIRMED ones)
- Phase 1: a single reliable curl repro + the exact `X-Cache`/error tokens. → general enough to stay
  in the journal.
- Phase 2: "a symptom is not a cause — trace the cache key, don't trust the data." (confidence:
  proven) → **promoted** to `METHODOLOGY.md` Phase 2.
- Phase 3: include all response-varying inputs in the cache key. (confidence: proven) → candidate for
  a `refs/` entry if it recurs.
- Phase 4: re-run the original repro as the proof. (proven) → already in `METHODOLOGY.md` Phase 4.
