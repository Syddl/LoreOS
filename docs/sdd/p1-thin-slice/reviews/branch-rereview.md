# Review: p1-thin-slice fix wave re-review

Lens: whole-branch re-review, correctness and security
Reviewer: reviewer subagent, fresh context, read-only shell. Tip `5ee06c2`.

## Executed

```
npm run check:all   -> exit 0: hooks 395/395, agent-hooks 7/7, backend 73 passed (9.73s), licenses 40/40, spend 29/29
npm run check:spend -> 29/29
read npm 10.9.7 source: run-script ignores --dry-run; --help prints npm's help instead of running
```

The main session then ran a free reproduction: in a scratch package, `npm run x --dry-run` runs the script with `npm_config_dry_run=true` and no argument. `npm run check:spend --dry-run` printed all 29 cases.

## Findings

| Severity | file:line | Impact | Fix | Response |
|---|---|---|---|---|
| blocker | `backend/loreos/smoke.py`, `.claude/harness.json` exempt | `npm run paid:smoke --dry-run` (no `--`) ran the paid flow unasked, also in subagents | Treat `npm_config_dry_run` as `--dry-run`; test and fixture | Fixed: smoke reads it (`test_npm_dry_run_without_the_separator...`, mutation-proven); the exempt list is now empty and the npm pattern asks for this spelling |
| minor | `.claude/harness.json` exempt | `--dry-run` inside a curl body exempted a paid post | Exempt only exact free forms | Fixed: empty exempt list; negative lookaheads for `-- --dry-run`, `-- --help`, a lone module `--dry-run`/`--help` |
| minor | `.claude/harness.json` npm pattern | `npm run -s paid:smoke`, `npm --silent run paid:smoke` unasked | Allow flags around run | Fixed |
| minor | `.claude/harness.json` HTTP pattern | A client called by path unasked | Path prefix | Fixed: `/usr/bin/curl`, `/c/Windows/System32/curl.exe`, `C:\Windows\System32\curl.exe` |
| minor | `.claude/harness.json` module pattern | Unanchored: grep and commit messages naming it asked | Anchor at the command start | Fixed for all three patterns |
| minor | `backend/loreos/main.py` | A chunked upload is received whole before the 413 | KNOWN-GAPS row or byte counting | KNOWN-GAPS row, trigger P4 serving beyond 127.0.0.1 |

The fixtures for all of these were added first and ran red (nine unasked spellings and one false positive), then green after the change: `check:spend` 43/43.

Confirmed fixed from the first review: the `-h` exempt, the fail-closed HTTP pattern, `--module`/`-mloreos`, the `-f` false positive, failed rerun, configured-key scrub, TOP_K, the vacuous assertion, the walrus, and Origin by host and port.

## Verdict

fix then re-review. The second fix wave is commit `fix(guard): exempt only the exact free forms of a paid entry`; its re-review is [branch-rereview-2.md](branch-rereview-2.md).

## Does NOT prove

`paid:smoke`, `db:migrate` and `dev:api` were not run. CI and a live Codex session were not observed. The regex claims were replayed only through the fixtures the main session added.
