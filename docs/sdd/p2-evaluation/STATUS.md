---
status: open
feature: p2-evaluation
---

# Status: p2-evaluation

The single carrier of state between sessions. Update it before a session ends; the session-start hook injects the open lines. Status is one of open, blocked, done.

## Open tasks

- Step 5: plan review of [plan.md](plan.md).
- Window A (tasks 1.1 to 1.6), then 2.1, then window C (3.1, 3.2, 3.3).
- Phase 4, the operator's part:
  1. Write `eval/questions.jsonl`.
  2. Set `OPENAI_API_KEY`.
  3. Run 1 to scratch.
  4. `eval:calibration-draft`, then grade the 30 rows.
  5. Run 2 to `eval/results/` (the baseline).

## Next step

Dispatch the plan reviewer (plan lens) on [plan.md](plan.md) against the current tree.

## Blockers

- `OPENAI_API_KEY` is empty in `.env`. It blocks the paid runs (phase 4) and P1's `paid:smoke`, not the build.
- `eval/questions.jsonl` is not written. Only the operator writes it (brief decision 10).

## Steps run differently

- Steps 1 to 3: the brief and the drafted spec existed. The spec was revised against P1 and research before planning; its section "Revised against P1" lists each change.
- Step 6: implementers in a parallel window write files and do not commit, because one shared index would let one task's commit take another's staged files. The main session commits each task alone, with explicit paths, after reading its diff and report.

## Verification ledger

| date | branch | sha | suite | result | duration | not covered |
|---|---|---|---|---|---|---|

## Port ledger

| Branch | Status | Reference |
|---|---|---|
| main | required | until the P2 PR merges |
