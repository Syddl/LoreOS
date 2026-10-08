# Review: window B, tasks 2.1 and 1.7, plus the window A fixes (correctness lens)

Reviewer: `harness:reviewer`, fresh context. Base `8ca01f6`, tip `0961beb`. Verdicts:
- Task 1.7: **merge**.
- Window A fixes `8b8acbc` and `2020f00`: **merge**.
- Task 2.1: **fix then re-review**.

## Executed

| Command | Result |
|---|---|
| `npm run check:backend` | 244 passed, 2 skipped |

The reviewer traced each destination, failure-class and usage test against its matching mutation. It found every one of these sound:
- the result shape and the row shape;
- atomic writes;
- test isolation from the real `eval/results/` and from OpenAI;
- linear time across every regex in `parsing.py` and chunking;
- the unchanged set of lines that are headings.

## Findings and their resolution

| Severity | Finding | Resolution |
|---|---|---|
| major | `llm.draft_answer` wraps a `BadRequestError` in a `RuntimeError`, so `run._ask` recorded a rejected answer request as `answer_error` and ran on through every question and the calibration (spec 7 says it stops) | `f3826ad`: `_ask` re-raises when the cause is an `openai.APIError`. A wrapped-error stop case is added, and its mutation proof passed |
| minor | The workspace key missed the pypdf and tiktoken versions and the code of the embed request and the stored vector text | `f3826ad`: added `KEYED_FUNCTIONS` (`llm.embed`, `retrieval.vector_literal`, captured at import so a test's fake never changes the key) and `KEYED_LIBRARIES` (pypdf, tiktoken), each with a test. The spec's Interfaces row is updated |
| minor | `llm.draft_answer`: a reply outside the schema was neither counted nor noted | `08564b9`: counted as `responses_without_usage`, then raised unchanged, with a test |
| nit | No test changed the source inputs of the key | `f3826ad`: a test case drops one module from `KEYED_SOURCES` |
| nit | A usage note could follow the "stopped" note | `f3826ad`: usage notes come first |
| nit | No test for the comment branch of `HTML_TAG` or `## Title {#id} ##` | `999bc79`: both cases added; they pass |
| nit | The calibration judging printed no progress | `f3826ad`: one line per calibration row |

## What the review does NOT prove

- No redproof was re-run by the reviewer.
- The `BadRequestError` gap was found by reading the code. The fix's test and its mutation proof were run by the main session.
- Nothing ran against real OpenAI or a cp1252 console.
