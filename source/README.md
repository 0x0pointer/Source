# source — methodology & reference vault (skeleton)

Working notes + reference material for a repeatable workflow. The end goal: distill a reusable
**playbook** (`METHODOLOGY.md` + `refs/`) from what you actually learn doing the work, so the next
run is faster and an agent can search it mid-task.

This folder is a plain folder of Markdown. It opens as an [Obsidian](https://obsidian.md) vault, but
Obsidian isn't required — Source (one level up) indexes the Markdown directly.

## The format decision (the reusable idea)

The structure has three layers, each a different kind of knowledge, and this folder mirrors them:

| File / folder | Role |
|---|---|
| `METHODOLOGY.md` | The ordered playbook — steps, exact commands, decision rules. The stable core. |
| `refs/*.md` | Deep-dive reference per topic. Lazy-loaded: you pull one in only when its trigger fires. |
| `journal/*.md` | One file per run/task: the raw log — what you tried, what happened, what actually worked. **This is the ground truth the playbook is distilled from.** |

**The one rule that makes it work:** *document the journal as you go, promote only **confirmed**
techniques into METHODOLOGY/refs.* A step earns its place in the methodology after it worked on a
real task — not because it "should" work. The journal keeps the messy truth; the methodology keeps
only what's proven.

Why this is worth copying: the journal captures detail while it's fresh and cheap, the methodology
stays short and trustworthy, and because everything is heading-structured Markdown, Source
chunks it cleanly and an agent can retrieve the exact section it needs.

## Index
- `QUICKSTART.md` — condensed, start-to-finish checklist for a new run. Points back at the detail.
- `METHODOLOGY.md` — the ordered playbook (living document).
- `refs/example-reference.md` — what a per-topic reference file looks like.
- `refs/templates.md` — copy-paste templates for adding a new reference entry or journal entry.
- `journal/example-entry.md` — what one run log looks like, and how it feeds the methodology.

## How to make this yours
1. Delete the example content and keep the headings as a scaffold.
2. Decide your phases in `METHODOLOGY.md` (the example uses Reproduce → Diagnose → Fix → Verify —
   replace with whatever cycle your work actually follows).
3. Start a `journal/<run-name>.md` on your first real task and log as you go.
4. After each run, promote the confirmed steps into `METHODOLOGY.md` / `refs/`.
5. Rebuild the index (`../build_index.py`) and search it (`../query.py "…"`).

## Tagging (optional)

Any note can carry YAML frontmatter tags. They're stripped from the indexed text (so they never
pollute search) but become a filter: `../query.py --tag playbook "…"`. The example notes here are
tagged `playbook`, `checklist`, `reference`, `template`, `journal` and `troubleshooting` so you can
try it immediately.

```markdown
---
tags: [playbook, checklist]
---
# My note
```
