---
tags: [playbook]
---
# Playbook — Reproduce → Diagnose → Fix → Verify

> This is a **skeleton**. The phases below (Reproduce → Diagnose → Fix → Verify) are a generic
> example cycle — replace them with the phases your own work actually follows. Keep the shape:
> ordered phases, each with concrete steps, exact commands, and decision rules. Promote a step here
> only once it has worked on a real run (see `README.md`).

Work the cycle in order. Most "stuck" loops come from a skipped or shallow **first** phase, so finish
each phase before moving on.

---

## Phase 1 — REPRODUCE (do this fully before changing anything)

**Lesson that keeps being relearned: you cannot fix what you cannot reproduce. Get a reliable repro
before touching the fix.**

### 1a. Capture the exact conditions
```
# TODO: the command(s) that trigger the problem, with the exact inputs
<your repro command here>
```
- Record the inputs, environment, and version — the things that change the outcome.
- A repro that only works "sometimes" is not done yet. Note what makes it flaky.

### 1b. Capture the evidence
- Save the exact error text / output, not a paraphrase. Exact strings (error codes, identifiers) are
  what keyword search will match later.
- Note what you *expected* vs what *happened*. The gap is the thing to explain.

> Deliverable for this phase: a one-command repro + the exact observed output. If you can't produce
> that, stay in Phase 1.

---

## Phase 2 — DIAGNOSE (find the cause, not just a symptom)

- Form a hypothesis, then find the cheapest check that would disprove it.
- Work from the evidence outward: the failing layer, then the layer it depends on.
- **A symptom is not a cause.** "It returns the wrong value" is a symptom; "the cache key omits the
  locale" is a cause. Keep going until you can name the mechanism.

> Deliverable: a named root cause you can point at in the code/config/data, plus how you confirmed it.

---

## Phase 3 — FIX (smallest change that addresses the cause)

- Prefer the minimal change that fixes the named cause over a broad rewrite.
- Note the alternatives you rejected and why — that reasoning is worth keeping.
- If the fix touches something risky or hard to reverse, say so and make it reversible.

> Deliverable: the change, plus a one-line statement of *why it addresses the Phase 2 cause*.

---

## Phase 4 — VERIFY (prove it, don't assume it)

- Re-run the **Phase 1 repro**. It must now pass. That is the primary evidence.
- Check you didn't break the neighbours (the nearest related cases).
- Record the before/after so the next person sees the proof, not just the claim.

> Deliverable: the repro command now passing, plus any side-effect checks.

---

## Answer / handoff format
When you record the result, be specific:
- name the thing exactly as the system presents it (the real identifier, not a paraphrase);
- give the concrete change + the observed result, never "should work in theory";
- keep each run's exact steps + evidence in its `journal/` file, so the pattern in what actually
  works becomes visible — then promote the confirmed steps up here.
