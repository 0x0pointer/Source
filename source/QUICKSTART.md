---
tags: [playbook, checklist]
---
# Quickstart — starting a run (summary checklist)

> **Skeleton.** Condensed from `METHODOLOGY.md` and `refs/*.md`. Each step points at the file with the
> detail. Mark a technique "proven" only once it has cleared a real run; everything else is "untested".

## 0. Setup
1. Note the environment / version you're working against. Write it down — it's the first thing that
   explains a surprising result later.
2. Open a `journal/<run-name>.md` and log every step as you go (copy the template in
   `refs/templates.md`).
3. Skim `METHODOLOGY.md` so you know the phase you're in.

## 1. Reproduce (finish before changing anything)
1. Get a **reliable** one-command repro (`METHODOLOGY.md` → Phase 1). A flaky repro isn't done.
2. Save the exact output — exact error codes/identifiers are what keyword search matches later.
3. Write down expected vs actual.

## 2. Check the reference triggers (`refs/`)
A run often reuses a known pattern. After reproducing, match what you see against the reference
triggers:
- Symptom looks like a known case documented in `refs/example-reference.md` → start from that entry.
- TODO: add your own trigger → reference mappings here as they emerge.

## 3. Diagnose
1. Hypothesis → cheapest disproving check.
2. Walk down the dependency chain until you can name the mechanism, not just the symptom.

## 4. Fix
1. Smallest change that addresses the named cause.
2. Record the alternatives you rejected and why.

## 5. Verify
1. Re-run the Phase 1 repro — it must pass now.
2. Check the nearest related cases didn't break.

## 6. Record & promote
1. In the journal entry, mark what cleared each phase and how confident you are (proven / untested).
2. Promote **only confirmed** steps into `METHODOLOGY.md` / `refs/`. Leave everything else in the
   journal.
3. Rebuild the index and spot-check a search (`../build_index.py` then `../query.py "…"`).

## Rules of thumb
- Finish the earlier phase before the later one — most dead ends are a shallow Reproduce/Diagnose.
- Exact strings go in the notes verbatim; they're what you'll search for under pressure.
- The journal holds the mess; the methodology holds only what's proven.
