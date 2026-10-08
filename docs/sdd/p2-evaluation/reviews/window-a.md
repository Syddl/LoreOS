# Review: window A, tasks 1.1 to 1.6 (correctness lens)

Reviewer: `harness:reviewer`, fresh context. Base `3878bb0`, tip `8ca01f6`. Verdict: **approve**, every task and overall.

## Executed

| Command | Result |
|---|---|
| `npm run check:backend` | 194 passed, 2 skipped (the questions and calibration files are not written yet) |
| `npm run check:all` | green through `check:spend` 90/90 |

The reviewer recomputed every hand value in the metrics fixture:
- recall@5 8/15, MRR@10 0.37, citation accuracy 3/7 pooled (5/12 per question);
- unanswerable refused 1/2, answerable refused 1/5;
- faithfulness 3/4, agreement 3/5;
- the confusion cells, and the percentiles.

## Findings and their resolution

| Severity | Finding | Resolution |
|---|---|---|
| minor | `llm.judge`: a reply outside the `Verdict` schema raises `pydantic.ValidationError`, which is in neither failure class, so one row would stop a paid run | `8b8acbc`: caught as `VerdictError`, counted as `responses_without_usage`, with a test |
| minor | `llm.draft_answer`: a length or content-filter stop was billed but not counted in `USAGE` | `8b8acbc`: counted, then re-raised unchanged, with a test |
| minor | `parsing.HTML_TAG` strips any bracketed span (`## x < 5 and y > 3` becomes `x  3`) | Sent to task 1.7, which owns `parsing.py` in window B: real tags and comments only |
| minor | `fetch`: a present file with the wrong hash stays in place when its re-download fails | Task 3.1, which owns `fetch.py` next: unlink it on a failed re-fetch, with a test |
| nit | `fetch._target` accepts the corpus directory itself (`file: "."`) | Task 3.1: `root in target.parents`; also refused by the manifest validator since `2020f00` |
| nit | `manifest_problems` accepted `C:/x.md` | `2020f00`: drive letters and `.` or empty segments are refused, with tests |

## What the review does NOT prove

- No redproof was re-run; the main session's proofs (all PASS) were taken as reported.
- Nothing ran against real OpenAI, GitLab or Wayback. `fetch.main()` was untested at review time.
- The timing bounds were checked on this machine only.
- `summarize` was tested only on hand-built rows; task 2.1 writes the real ones.
