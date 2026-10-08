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
