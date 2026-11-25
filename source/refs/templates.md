---
tags: [reference, template]
---
# ref — Templates (copy-paste these)

Keep entries uniform so they're skimmable and so Source chunks them on clean heading boundaries.

## Reference entry template (`refs/*.md`)

```markdown
## R<n>. <short name of the case>
**Status:** UNTESTED | CONFIRMED (link the journal entry)

**Trigger:** what you observe during a run that should make you reach for this entry.

**Chain:**
1. The cheap check that confirms you're in this case.
2. The step that addresses it, with the exact command.
3. What "done" looks like (the observable result).

**Notes / gotchas:** the detail that cost time the first time.
```

## Journal entry template (`journal/*.md`)

```markdown
---
tags: [journal]
---
# Run — <name / date>

Context: <environment, version, inputs — the things that change the outcome>.
Goal: <what "done" means for this run>.

## Phase 1 — Reproduce
- repro command + exact output (verbatim, not paraphrased).

## Phase 2 — Diagnose
- hypotheses tried, the check that confirmed/killed each, the named root cause.

## Phase 3 — Fix
- the change; alternatives rejected and why.

## Phase 4 — Verify
- repro re-run (now passing) + side-effect checks.

## What cleared each phase (promote the CONFIRMED ones into METHODOLOGY/refs)
- Phase 1: …
- Phase 2: …   (confidence: proven | untested)
- Phase 3: …
- Phase 4: …
```

## Eval question template (`../eval/questions.json`)
One object per question. `kind` is `paraphrase` (avoids the note's words), `exact_term` (an exact
identifier/code), or `scenario` (describes a situation). `expected_path` + `expected_heading` are the
section that should come back first.

```json
{
  "query": "the question, phrased the way you'd actually ask it",
  "kind": "paraphrase",
  "expected_path": "METHODOLOGY.md",
  "expected_heading": "Phase 1 — REPRODUCE (do this fully before changing anything)",
  "answer_snippet": "a short quote from the expected section, for your own reference",
  "ok": true,
  "also_acceptable": ["QUICKSTART.md :: 1. Reproduce (finish before changing anything)"]
}
```
