---
status: open
feature: p2-evaluation
---

# Status: p2-evaluation

The single carrier of state between sessions. Update it before a session ends; the session-start hook injects the open lines. Status is one of open, blocked, done.

## Open tasks

- Step 5: done. The plan review and its re-review are in [reviews/plan.md](reviews/plan.md); the re-review's fixes were applied to the plan.
- Window A (1.1 to 1.6): done and cherry-picked. Every mutation proof passed, and `check:all` is green. The step 7 review of window A is pending.
- Window B: 2.1 (the run) and 1.7 (a linear-time `HEADING` regex; 1.6 found the quadratic one). Then window C: 3.1 and 3.2; 3.3 is partly done.
- Phase 4, the operator's part:
  1. Write `eval/questions.jsonl`.
  2. Set `OPENAI_API_KEY`.
  3. Run 1 to scratch.
  4. `eval:calibration-draft`, then grade the 30 rows.
  5. Run 2 to `eval/results/` (the baseline).

## Next step

Integrate window B (2.1, 1.7) and the window A review, then window C.

## Blockers

- `OPENAI_API_KEY` is empty in `.env`. It blocks the paid runs (phase 4) and P1's `paid:smoke`, not the build.
- `eval/questions.jsonl` is not written. Only the operator writes it (brief decision 10).

## Steps run differently

- Steps 1 to 3: the brief and the drafted spec existed. The spec was revised against P1 and research before planning; its section "Revised against P1" lists each change.

## Verification ledger

| date | branch | sha | suite | result | duration | not covered |
|---|---|---|---|---|---|---|

## Port ledger

| Branch | Status | Reference |
|---|---|---|
| main | required | until the P2 PR merges |
