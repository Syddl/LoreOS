# Review: p2-evaluation, whole branch (step 9, independent, with a security and spend focus)

Reviewer: `harness:reviewer`, fresh context. Base `origin/main` (`33f1564`), tip `736f138`. Verdict: **fix then merge**, with no blocker or major.

## Executed

| Command | Result |
|---|---|
| `npm run check:all`, run 1 | exit 0: hooks 395/395, agent-hooks 7/7, backend 309 passed and 2 skipped, licenses 40/40, spend 90/90 |
| `npm run check:all`, run 2 | exit 0, the same counts |

The environment overrides hold:
- conftest sets `DATABASE_URL`, the key and `OPENAI_BASE_URL=http://0.0.0.0:9/v1` before any import, and `settings` uses `setdefault`;
- `test_no_openai` passed in both runs;
- the CLI and calibration tests clear `npm_config_*` and `INIT_CWD`.

The reviewer read window C (preflight, CLI, calibration, fetch) in full, since it had no separate task review. It found the order, the spend traps, the free scripts, path safety, linear-time parsing and one owner per fact all sound. Every row of "Revised against P1" matches the code.

## Findings and their resolution

| Severity | Finding | Resolution |
|---|---|---|
| minor | `npm run paid:eval --lim=5` (an abbreviation npm takes as its own config) would start a full paid run | `863f2aa`: any `npm_config_<k>` whose flag is a prefix of `--limit` or `--mode` is refused with the `--` form. npm's own settings pass. Both have tests. A misspelling (`--limt`) is still swallowed (a `ponytail:` note) |
| minor | `tree_clean` obeyed `status.showUntrackedFiles=no`, so an uncommitted question set could go unseen | `863f2aa`: `git status --porcelain --untracked-files=normal`; the test sets that config |
| minor | The preflight's fallbacks (an unverified model list, broad labels) only printed, and `settings` did not show a non-OpenAI server | `863f2aa`: `preflight` returns `(sha, notes)`, which the run puts first in `notes`. `settings.openai_base_url_host` records the host only. The spec and the plan contracts are amended |
| minor | `HTML_TAG` stripped brackets inside code spans (``## `Vec<T>` API``) | `dc95b19`: tags are stripped only outside backtick spans, still linear. An unmatched backtick opens no span |
| minor | An agent could fill in `human` grades or questions with the edit tool | `bbb8051`: `eval/questions.jsonl` and `eval/judge_calibration.jsonl` are under `protected_paths.ask`. `check:spend` pins both, the deny on `eval/results/`, and an unguarded control |
| nit | The README missed the faithfulness rule, the need to commit the inputs first, and the merge method | `863f2aa`: all three added |
| nit | CC BY-SA 4.0 asks that modifications be indicated | `863f2aa`: the README says the passages are excerpted and their headings cleaned |
| nit | `fetch.main` did not validate the manifest, and reads were uncapped | `3378a9e`: the manifest is refused before any request, and each download is capped at 50 MB. Both have tests |
| nit | A run with verdict failures on answers still went to `results/` | `863f2aa`: any answer without a verdict sends the run to scratch, with its reason. Spec behaviour 5 is amended, with a test |
| nit | `paid:eval -- --limit 5` was not pinned as ask, and the free scripts were not pinned as free | `bbb8051`: pinned |
| nit | The ledger had no `check:all` row for the branch | The claim-green script writes it on the pushed tip (step 11) |

Out of scope, noted by the reviewer: P1's `answering.MARKER` (`\s*\[`) is quadratic on long whitespace, but it reads only model output.

## What the review does NOT prove

- No paid call ran, and no form of `paid:eval` ran except the main session's dry run (STATUS.md).
- Nothing contacted GitLab, Wayback, OpenAI or Supabase.
- No redproof was re-run.
- The npm abbreviation and git config behaviours came from knowledge of the tools. The fixes now have tests that exercise them.
- CI, Linux and a cp1252 console were not observed.
