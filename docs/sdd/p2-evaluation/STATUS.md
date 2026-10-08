---
status: open
feature: p2-evaluation
---

# Status: p2-evaluation

The single carrier of state between sessions. Update it before a session ends; the session-start hook injects the open lines. Status is one of open, blocked, done.

## Open tasks

- **Steps 4 to 7: done.**
  - Plan review and re-review: [reviews/plan.md](reviews/plan.md).
  - Tasks 1.1 to 1.7, 2.1, 3.1 and 3.2 are implemented, each by a fresh implementer in its own worktree, cherry-picked, and mutation-proven.
  - Task reviews: [reviews/window-a.md](reviews/window-a.md) and [reviews/window-b.md](reviews/window-b.md). Their fixes are applied with tests.
  - 3.3 (data and docs) is done by the main session.
- **Step 7 for window C** (3.1, 3.2) was folded into the step 9 whole-branch review, which read those files in full.
- **Step 9**: done, verdict "fix then merge" ([reviews/branch.md](reviews/branch.md)).
- **Step 10**: done.
  - The fixes are in `dc95b19`, `3378a9e`, `863f2aa`, `bbb8051` and `66121ab`.
  - Their re-review said merge ([reviews/branch.md](reviews/branch.md)).
- **Step 11**: claim-green PASS on the pushed tip `3f765ba0`.
- **Step 12**: a draft PR, at the operator's choice. It is marked ready once the baseline is committed on this branch, and merged with a merge commit so the result's `git_sha` stays on `main`.
- **Steps 13 and 14**: open until the baseline lands and the PR merges.
- **Step 8 and phase 4**, the operator's part:
  1. Done: Claude drafted `eval/questions.jsonl` at the operator's request ([decision 0004](../../decisions/0004-evaluation-set-drafted-by-claude.md)).
     - It holds 81 questions, 15 of them unanswerable.
     - Five agents drafted it, and two independent fact-checkers reviewed it, with 8 fixes applied.
     - Every label resolves in the fetched corpus (`test_committed_labels_resolve_in_the_fetched_corpus`).
  2. Set `OPENAI_API_KEY`.
  3. `npm run paid:eval -- --dry-run`.
  4. Run 1 (to scratch).
  5. `npm run eval:calibration-draft -- <run 1 file>`, then grade the 30 rows.
  6. Run 2 (the baseline, to `eval/results/`), committed.

## Next step

Once `OPENAI_API_KEY` is set (and `npm run eval:fetch` has run on that machine): `npm run paid:eval -- --dry-run`, then run 1.

## Blockers

- `OPENAI_API_KEY` is empty in `.env`. It blocks the paid runs (phase 4) and P1's `paid:smoke`, not the build.

## Steps run differently

- **Steps 1 to 3**: the brief and the drafted spec existed. The spec was revised against P1 and research before planning; its section "Revised against P1" lists each change.
- **Step 6, the mutation proofs**: the main session ran `redproof` after each cherry-pick, with the operator approving each ask. Inside a subagent, the spend guard refuses a command naming `loreos/evaluation` or `llm.py` next to `uv ... python`.
  - Tasks 1.6 and 1.7 (`parsing.py`) ran their own.
  - All passed: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6 (two), 1.7, 2.1 (two), 3.1, 3.2, and the window B fix (wrapped API error).
- **Step 6, the worktree base**: the Agent tool created each worktree from `main`, not `p2-evaluation`. Every implementer fast-forwarded to `p2-evaluation` before changing anything, and each cherry-pick applied cleanly.
- **Step 10, the fix waves**: the main session made the review fixes itself, each red then green: `8b8acbc`, `2020f00`, `08564b9`, `f3826ad` and `999bc79`. The one exception was the `HTML_TAG` fix, which went to task 1.7's implementer. They were small and touched files whose tasks had closed. The step 9 review covers them.
- **Task 1.7** was added during window B, after 1.6 found P1's `HEADING` regex quadratic on hostile Markdown.

## Verification ledger

| date | branch | sha | suite | result | duration | not covered |
|---|---|---|---|---|---|---|
| 2026-10-08 (by hand, live) | p2-evaluation | 999bc79 | `npm run eval:fetch` against GitLab and Wayback | PASS | | 48 of 48 files downloaded, every sha256 matched; `outline.txt` written (790 sections). Not covered: a re-fetch after a host changes bytes |
| 2026-10-08 (by hand, live) | p2-evaluation | 999bc79 | `npm run paid:eval -- --dry-run`, approved at the ask | PASS (expected exit 1) | | It stopped at the first preflight step, naming the missing `eval/questions.jsonl`; no paid call. Not covered: every later preflight step against Supabase and OpenAI (needs the set and the key) |
| 2026-10-08T12:46:44.454Z | p2-evaluation | 3f765ba0 | `npm run check:all` | PASS | 89.9 s | phase 4: the operator's evaluation set, the paid runs (run 1, calibration, baseline) against real OpenAI and Supabase; the preflight past its first step against live services; CI on Linux |
| 2026-10-08 (by hand, live) | p2-evaluation | e2ae8e8 | `npm run paid:eval -- --dry-run` with the committed 81-question set, approved at the ask | PASS (expected exit 1) | | It passed the set, calibration, corpus-hash and label checks against the real corpus, then stopped at the missing `OPENAI_API_KEY`. It stopped with a traceback; `b799710` turns that into a preflight message. No paid call. Not covered: the database, migration and model checks, and the plan (they need the key) |
| 2026-10-08T14:38:50.296Z | p2-evaluation | b7997100 | `npm run check:all` | PASS | 93.6 s | the paid runs (run 1, calibration, baseline) against real OpenAI and Supabase; the preflight past the key check (no OPENAI_API_KEY yet) |

## Port ledger

| Branch | Status | Reference |
|---|---|---|
| main | required | until the P2 PR merges |
