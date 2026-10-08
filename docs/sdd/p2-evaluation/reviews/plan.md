# Review: p2-evaluation plan (plan lens)

Reviewer: `harness:reviewer`, fresh context. Base: the plan at `1d85408`. Verdict: **fix then re-review**.

## Executed

| Command | Result |
|---|---|
| `npm run check:backend` (background run) | exit 4: `ImportError: DLL load failed while importing _result_cy: An Application Control policy has blocked this file` |
| `npm run check:backend` (foreground rerun) | 74 passed in 13.30 s |
| `npm run check:all` | check:hooks 395/395, check:agent-hooks 7/7, check:backend 74 passed, check:licenses 40/40, check:spend 90/90 |
| the plan's per-file pytest commands | refused by the reviewer's read-only shell (not on the allowlist) |
| `ls eval backend/loreos/evaluation` | No such file or directory (both) |

The baseline is green. The plan's new checks are red only because their files do not exist yet. That is inferred from the listing, not from a pytest run.

## Findings and their resolution

| Severity | Finding | Resolution in the revised plan |
|---|---|---|
| major | `redproof` refuses an untracked target and a dirty tree, so no task could run its mutation proof in a shared, uncommitted checkout | Each implementer gets its own worktree and commits there, and the main session cherry-picks |
| major | The phase 3 end check expected the dry run to exit 0, but the set and the key arrive in phase 4 | Phase 3 expects a non-zero exit naming `eval/questions.jsonl`; exit 0 moves to phase 4 |
| major | 3.1's acceptance ran `check:all`, which includes 3.2's red-first tests | Per-task checks run only the task's own files; the main session runs `check:all` per phase |
| major | No check for spec behaviour 6 (a corpus file not processed stops the run) | Added to 2.1, with no answer call made |
| major | The spend gate (preflight before `run.evaluate`) was untested | Added to 3.1: a failing preflight never reaches `evaluate`, and the sha is passed through |
| major | Judge failures were never sorted into classes; a broken judge could land a null-faithfulness result in `eval/results/` | `VerdictError` per row versus `openai.APIError` stopping the run. The destination also needs judge agreement and faithfulness to be non-null. The preflight checks model names against the free model list |
| minor | `check:backend` did not validate the committed calibration file | 1.1 validates both committed files, and `eval/corpus.json` |
| minor | Preflight tests left the order, the `smoke.preflight` call, invalid files and the token estimate unpinned | Added to 3.1; the estimate is pinned to what `fake_embed` receives from a real ingest |
| minor | The corpus hash rule had two owners, and `text_hash`'s CRLF fix would alter PDF bytes | `fetch.corpus_problems`, over raw bytes, is the one owner; `text_hash` is for questions and calibration only |
| minor | 30 was written in four tasks; a short draft would always fail validation | `dataset.CALIBRATION_ROWS`; 3.2 exits 1 on fewer eligible rows |
| minor | `git_sha` timing was unfixed, and Ctrl-C would lose paid output | The preflight records the sha, and the destination needs HEAD unchanged; partial writes happen on `BaseException` |
| minor | Usage was never exercised end to end, and `USAGE` was not reset per run | 2.1 seeds `USAGE`, checks the `usage` block and the note, and clears `USAGE` at the start |
| minor | Nothing tested that `fetch.main` writes `outline.txt` | 3.1 owns `test_eval_fetch.py` in window C, with that case |
| minor | 3.3 depends on 3.1's script | Dependency added |
| minor | `--limit` accepted 0 and negative numbers | argparse requires an integer of at least 1, with a test |
| minor | The judge prompt lived only in an uncommitted brief | The prompt is in the plan |
| minor | The 60 to 100 total was never checked | A destination rule in 2.1, with `MIN_QUESTIONS` and `MAX_QUESTIONS` in `dataset` |
| minor | 1.5 and 3.2 proved red-first by import failure only | Each has a behaviour mutation |
| minor | "A second run makes zero embed calls" cannot hold, since `search` embeds the question | The test asserts that no chunk text reaches `fake_embed` |
| minor | The workspace key left out `OPENAI_BASE_URL` | Added |
| minor | The new entry points lacked `sys.stdout.reconfigure(errors="replace")` | Added for `__main__`, `fetch` and `calibration` |
| minor | `fake_judge` could not raise, and the calibration denominator was undefined | `.reply` may be an exception; a verdict failure leaves the denominator |
| nit | `clean_at_preflight` was redundant | Replaced by `preflight_sha` |
| nit | `Citation` has no score | The facts line is fixed |
| nit | `.env.example` is under the `.env.*` ask rule | The main session edits it before window A |
| out of scope | The edit-tool deny does not stop a shell copy into `eval/results/` | `check:backend` fails on a committed result whose `destination` is not `results` or whose judge agreement is null (2.1), and a KNOWN-GAPS row records the remaining gap |

## What the review does NOT prove

- None of the plan's per-file pytest commands ran.
- Nothing contacted OpenAI, GitLab, the PDF hosts or Supabase.
- `redproof`'s refusals are inferred from its source, not from a run.
- The first `check:backend` failure (an Application Control block on SQLAlchemy's DLL) passed on rerun; its cause is unknown.

# Re-review: the revised plan (plan lens)

Reviewer: `harness:reviewer`, fresh context, at `64d0d1a`. Verdict: **fix then proceed**. The fixes are plan-text edits, and reading their diff confirms them.

Executed:
- `npm run check:all`: hooks 395/395 and agent-hooks 7/7. check:backend had 73 passed and 1 failed, the expected `test_config.py::test_env_example_lists_exactly_the_keys_settings_reads` (JUDGE_MODEL is in `.env.example` before task 1.5 lands).
- `check:spend` 90/90 and `check:licenses` 40/40, each run alone.

Every prior finding is resolved in the plan text. The new findings and their fixes:

| Severity | Finding | Fix |
|---|---|---|
| major | `redproof` inside a subagent, naming `backend/loreos/evaluation/...` or `llm.py` next to `uv ... python`, matches the spend pattern, and the guard denies it | The main session runs each `redproof` after the cherry-pick, approved at the ask. 1.6 (`parsing.py`) runs its own, with `--project` |
| major | No check that the judge gets only the cited passages under their original numbers (built in `run.py`); 1.5's mutation could not be written | 2.1 asserts the judge's passages for an answer citing [2] and [4], with a mutation that passes the hits. 1.5's mutation numbers the passages by position. `fake_judge.calls` records the passages |
| minor | The "every calibration row graded" destination rule could pass with 1 of 30 failures; more than 100 questions was untested | The rule reads `calibration_rows` and `calibration_judge_errors`; both cases are added |
| minor | The usage test conflicted with clearing `USAGE` at the start | A stale seed must vanish, and counts added during the run must appear |
| minor | `eval:calibration-draft`'s relative path resolved against `backend/` | Resolve against `INIT_CWD`, else the repo root, with a test |
| minor | Cherry-picked implementer commits could carry an attribution trailer | Read each message first, and re-commit with `-n` when needed |
| nit | testdb labels | Moved from 1.5 to 3.1's token case |
| nit | The call-time rule named only `CORPUS_DIR` | It now covers every `dataset` name |
