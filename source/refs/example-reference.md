---
tags: [reference]
---
# ref — Example reference topic

> **Skeleton.** A reference file is a deep-dive on one topic you reach for only when its **trigger**
> fires. Keep each entry in the same shape so it's skimmable and so search chunks it cleanly: a
> **Trigger** (what you see that should make you think of this), the **steps/chain**, and a
> **Status** (untested / confirmed, with a link to the journal entry that proved it).
>
> Status legend: **UNTESTED** = plausible, not yet proven on a real run. **CONFIRMED** = cleared a
> real run (link the journal entry).

---

## R1. Example entry — a known, recurring case
**Status:** CONFIRMED (see `../journal/example-entry.md`)

**Trigger:** what you observe during a run that points here — e.g. the repro output contains the
exact token `ERR_CONN_4021`, or a step takes far longer than its usual baseline.

**Chain:**
1. Confirm you're really in this case (the cheap check that rules it in or out).
2. The step that addresses it, with the exact command:
   ```
   # TODO: the concrete command for this case
   <command>
   ```
3. What "done" looks like for this case (the observable result).

**Notes / gotchas:** the one detail that cost time the first time — write it here so it costs nobody
time again.

---

## R2. Example entry — a second case (untested)
**Status:** UNTESTED

**Trigger:** TODO — what you'd see that makes this the right reference.

**Chain:** TODO — the steps you believe will work. Move this to CONFIRMED and link the journal entry
once it actually has.

---

## Adding a new entry
Copy the template from `templates.md`: **Trigger** → **Chain** (numbered, with exact commands) →
**Notes/gotchas** → **Status** (UNTESTED/CONFIRMED + journal link). Add the trigger to the
QUICKSTART "reference triggers" checklist too, so it's discoverable from the top.
