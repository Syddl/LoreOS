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
- **Step 11**: claim-green PASS on the pushed tips `3f765ba0` and `b7997100`.
- **Step 12**: done. PR #3 (the tooling and the evaluation set) merged into main as `faa149c`, a merge commit, with CI green. The operator chose to merge before the baseline, because OpenAI is not reachable yet.
- **Steps 13 and 14**: open until the baseline lands from the `p2-baseline` branch. Merge it with a merge commit, so the result's `git_sha` stays on `main`.
- **Step 8 and phase 4**, the operator's part:
  1. Done: Claude drafted `eval/questions.jsonl` at the operator's request ([decision 0004](../../decisions/0004-evaluation-set-drafted-by-claude.md)).
     - It holds 81 questions, 15 of them unanswerable.
     - Five agents drafted it, and two independent fact-checkers reviewed it, with 8 fixes applied.
     - Every label resolves in the fetched corpus (`test_committed_labels_resolve_in_the_fetched_corpus`).
  2. Done: `OPENAI_API_KEY` set (2026-10-11).
  3. Done: `npm run paid:eval -- --dry-run` passed (ledger).
  4. Done: run 1, to scratch, on the third attempt (ledger). The first two stopped on connection resets, fixed in `5f3e7a8`.
  5. Done (2026-10-12): Claude graded the 30 rows at the operator's request ([decision 0008](../../decisions/0008-calibration-graded-by-claude.md)).
     - The result is 29 faithful and 1 unfaithful (q066), graded blind from each row's passages. The reason for each is in [calibration-grades.md](calibration-grades.md).
     - Judge agreement in the baseline therefore measures agreement with Claude's grades, not a person's.
  6. Done (2026-10-12): run 2 wrote the baseline, `eval/results/20261012T054918Z-vector-6852dcac.json` (destination `results`).
     - **Retrieval:** Recall@5 0.909, MRR@10 0.825.
     - **Answers:** citation accuracy 0.705, unanswerable refused 1.0, answerable refused 0.061.
     - **Judge:** faithfulness 0.903 by `gpt-6-luna`. Judge agreement is 1.0 with Claude's grades: 29 of 29 faithful and 1 of 1 unfaithful (q066).
     - **Latency:** search p50 1307 ms, p95 1838 ms.
     - **Cost:** $0.1256.

## Next step

Push `p2-baseline`, claim green on the pushed tip, open the PR, and merge it with a **merge commit** once CI is green. Then close P2 (steps 13 and 14).

## Spend

- **Cap**: $5 of OpenAI for closing P1 and P2, set by the operator ([decision 0005](../../decisions/0005-cheaper-judge-and-a-spend-cap.md)). The judge is `gpt-6-luna`, the answers `gpt-5.4-mini`.
- **Estimate**, an upper bound per full run:
  - 81 answer calls and 81 judge calls (111 in the baseline, with the 30 calibration rows), each up to about 3,500 input tokens.
  - About $0.50 a run.
  - Embedding the corpus once: 195,274 tokens in 920 chunks, under $0.01.
- **Run 1**: `npm run paid:eval`, detached, logging to `docs/sdd/p2-evaluation/scratch/run1.log`. The result goes to `docs/sdd/p2-evaluation/scratch/<stamp>-vector-<sha>.json`, since no calibration file exists yet.
- **Baseline (run 2)**: the same command at a clean, committed tree. It logs to `scratch/run2.log`, and the result goes to `eval/results/`.
- After each run: its `usage`, priced, against this estimate.
- **Actual so far**:
  - Run 1 cost $0.1255; with its two stopped attempts, $0.1259. Priced from each result file's `usage` at aggregator prices: embedding $0.02, answers $0.75 / $4.50, judge $0.10 / $0.50 per 1M tokens.
  - `paid:smoke` cost under $0.01.
  - The baseline (run 2) cost $0.1256, reusing run 1's corpus embeddings.
  - Total: about $0.26 of the $5 cap.
  - The estimate was high because the answers and grades are short: 5,713 answer output tokens and 5,573 judge output tokens over 81 questions.

## Blockers

None. `OPENAI_API_KEY` is set (2026-10-11).

## Steps run differently

- **Steps 1 to 3**: the brief and the drafted spec existed. The spec was revised against P1 and research before planning; its section "Revised against P1" lists each change.
- **Step 6, the mutation proofs**: the main session ran `redproof` after each cherry-pick, with the operator approving each ask. Inside a subagent, the spend guard refuses a command naming `loreos/evaluation` or `llm.py` next to `uv ... python`.
  - Tasks 1.6 and 1.7 (`parsing.py`) ran their own.
  - All passed: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6 (two), 1.7, 2.1 (two), 3.1, 3.2, and the window B fix (wrapped API error).
- **Step 6, the worktree base**: the Agent tool created each worktree from `main`, not `p2-evaluation`. Every implementer fast-forwarded to `p2-evaluation` before changing anything, and each cherry-pick applied cleanly.
- **Step 10, the fix waves**: the main session made the review fixes itself, each red then green: `8b8acbc`, `2020f00`, `08564b9`, `f3826ad` and `999bc79`. The one exception was the `HTML_TAG` fix, which went to task 1.7's implementer. They were small and touched files whose tasks had closed. The step 9 review covers them.
- **Task 1.7** was added during window B, after 1.6 found P1's `HEADING` regex quadratic on hostile Markdown.
- **Phase 4, run 1 failures** (2026-10-11):
  - Two attempts stopped during ingest with `ConnectionResetError` (WinError 64), raised in the TLS handshake of a new connection to the Supabase pooler.
  - Triage: environment. A free probe reset 4 of 80 fresh connections (5%, about 1.7 s each). NullPool opens one per file and per question, about 200 a run, so a run almost never finished.
  - Fix `5f3e7a8`: `db.engine()` retries a reset during the connect, up to 3 attempts, since nothing has been sent yet. A refused login is not retried. The run's `notes` count the retries.
  - Red first: `ImportError` on `CONNECT_ATTEMPTS`. Mutation-proven with `redproof` (4 cases). `check:all` PASS.
  - Each retry resumed ingest from the files already processed, so no paid step was billed twice. The third attempt retried 4 resets and finished.

## Verification ledger

| date | branch | sha | suite | result | duration | not covered |
|---|---|---|---|---|---|---|
| 2026-10-08 (by hand, live) | p2-evaluation | 999bc79 | `npm run eval:fetch` against GitLab and Wayback | PASS | | 48 of 48 files downloaded, every sha256 matched; `outline.txt` written (790 sections). Not covered: a re-fetch after a host changes bytes |
| 2026-10-08 (by hand, live) | p2-evaluation | 999bc79 | `npm run paid:eval -- --dry-run`, approved at the ask | PASS (expected exit 1) | | It stopped at the first preflight step, naming the missing `eval/questions.jsonl`; no paid call. Not covered: every later preflight step against Supabase and OpenAI (needs the set and the key) |
| 2026-10-08T12:46:44.454Z | p2-evaluation | 3f765ba0 | `npm run check:all` | PASS | 89.9 s | phase 4: the operator's evaluation set, the paid runs (run 1, calibration, baseline) against real OpenAI and Supabase; the preflight past its first step against live services; CI on Linux |
| 2026-10-08 (by hand, live) | p2-evaluation | e2ae8e8 | `npm run paid:eval -- --dry-run` with the committed 81-question set, approved at the ask | PASS (expected exit 1) | | It passed the set, calibration, corpus-hash and label checks against the real corpus, then stopped at the missing `OPENAI_API_KEY`. It stopped with a traceback; `b799710` turns that into a preflight message. No paid call. Not covered: the database, migration and model checks, and the plan (they need the key) |
| 2026-10-08T14:38:50.296Z | p2-evaluation | b7997100 | `npm run check:all` | PASS | 93.6 s | the paid runs (run 1, calibration, baseline) against real OpenAI and Supabase; the preflight past the key check (no OPENAI_API_KEY yet) |
| 2026-10-11 (by hand, live) | p2-baseline | 307e32f | `npm run paid:eval -- --dry-run`, approved at the ask | PASS | | Every preflight step passed against Supabase and OpenAI, `gpt-6-luna` listed. Plan: 81 questions, at most 567,000 input tokens, corpus 195,274 tokens. No paid call. |
| 2026-10-11 (by hand, live) | p2-baseline | 307e32f | `npm run paid:eval` run 1, attempts 1 and 2; `scratch/run1.log`, `scratch/run1-retry.log` | FAIL (environment) | | Stopped in ingest on `ConnectionResetError`, at 2 and then 20 of 48 files processed. Partial results `scratch/20261011T105100Z-vector-307e32ff.json` and `scratch/20261011T105410Z-vector-307e32ff.json`. Fixed in `5f3e7a8`. |
| 2026-10-11 (by hand) | p2-baseline | 5f3e7a8 | `npm run check:all` | PASS | 102 s | 335 passed, 1 skipped (`judge_calibration.jsonl` not committed yet) |
| 2026-10-11 (by hand, live) | p2-baseline | 5f3e7a8 | `npm run paid:eval` run 1, attempt 3; `scratch/run1-retry2.log` | PASS (to scratch, as designed) | | `scratch/20261011T112034Z-vector-5f3e7a80.json`. 81 questions; 4 connect resets retried. Recall@5 0.909, MRR@10 0.825, citation accuracy 0.697, unanswerable refused 1.0, answerable refused 0.076, faithfulness 0.934 (judge `gpt-6-luna`, not yet calibrated). Cost $0.1255. Not covered: judge agreement (needs the graded rows), the committed baseline (run 2) |
| 2026-10-12 (by hand, live) | p2-baseline | 6852dca | `npm run paid:eval -- --dry-run`, approved at the ask | PASS | | All preflight steps passed, and the workspace was reused (0 corpus tokens). Plan: 81 answer and 111 judge calls. No paid call |
| 2026-10-12 (by hand, live) | p2-baseline | 6852dca | `npm run paid:eval`, run 2, the baseline; `scratch/run2.log` | PASS (to `eval/results/`) | | `eval/results/20261012T054918Z-vector-6852dcac.json`. Recall@5 0.909, MRR@10 0.825, citation accuracy 0.705, unanswerable refused 1.0, answerable refused 0.061, faithfulness 0.903, judge agreement 1.0 with Claude's grades (decision 0008). Cost $0.1256. Not covered: agreement with a person's grades; the answer model's variance between runs (one run) |

## Port ledger

| Branch | Status | Reference |
|---|---|---|
| main | done for the tooling and the set; the baseline is required | `faa149c` (PR #3, merge commit). The baseline follows from `p2-baseline` |
