---
status: open
feature: p1-thin-slice
---

# Status: p1-thin-slice

The single carrier of state between sessions. Update it before a session ends; the session-start hook injects the open lines. Status is one of open, blocked, done.

## Open tasks

- Step 9: three review rounds so far ([reviews/](reviews/)). The re-review of `91f3af1` (spend patterns at word boundaries, smoke-only exemption) is running. An automated security review of the same commit reported two allowlist escapes and one parser differential without details. Likely candidates: the module-form exemption trusts trailing text (`python -c ... -m loreos.smoke --dry-run`); the npm exemption allows npm flags such as `--script-shell`; a port with leading zeros (`:08000`). Fix: exempt only the exact `npm run paid:smoke -- --dry-run|--help` subcommand, drop the module-form exemption, and match `:0*8000`.
- CI on the PR must go green on the pushed tip (row 18).
- `npm run db:migrate` against Supabase: first run on the real session pooler. Waiting on operator approval.
- `npm run paid:smoke` (row 16): needs `OPENAI_API_KEY` and the operator's yes at the ask prompt; its verification row is added by hand.
- Steps 13 to 14: ledger rows, close.

## Next step

Fold the `91f3af1` re-review and the automated findings into one guard fix on the PR, claim green again, then ask the operator for `db:migrate` and `paid:smoke`.

## Blockers

- `OPENAI_API_KEY` is empty in `.env`. It blocks only `paid:smoke`.

## Steps run differently

- Step 5: the plan review returned "fix then re-review" ([reviews/plan.md](reviews/plan.md)). The fixes added checks and moved no design, so the re-review was folded into the reviews of the implementation instead of run separately.
- Step 6: the main session implemented every task, in plan order, instead of a fresh implementer per task. The tasks were small and shared one design held in the plan. Each task's check was mutation-proven with the harness `redproof` script after its commit, so no reported green rests on a check that cannot fail. Recorded runs: parsing (heading stack, PDF page numbers), chunking (no split, no overlap; the first overlap mutation survived and the test was fixed), the no-OpenAI base URL, licenses (AGPL, the certifi exception), spend patterns (module, curl, PowerShell, the `-h` exempt), retrieval (workspace filter, order, no-chunks spend), ingest (savepoint, key scrub with and without `sk-`, duplicate spend, failed rerun), answering (no valid citation, top 5), smoke `--dry-run`, and the Host, Origin (host and port) and early-413 guards.
- Step 7: per-task reviews were folded into the step 9 whole-branch review, run by an independent reviewer.

## Verification ledger

| date | branch | sha | suite | result | duration | not covered |
|---|---|---|---|---|---|---|
| 2026-10-06T12:31:21.540Z | p1-thin-slice | a9692b89 | `npm run check:all` | PASS | 48.6 s | paid:smoke against real OpenAI; db:migrate on Supabase's session pooler; dev:api in a browser; the pending automated security findings on 91f3af1 (2 allowlist escapes, 1 parser differential) |

## Port ledger

| Branch | Status | Reference |
|---|---|---|
| main | required | until the P1 PR merges |
