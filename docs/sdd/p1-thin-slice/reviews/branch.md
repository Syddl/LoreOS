# Review: p1-thin-slice whole branch

Lens: whole-branch, correctness and security
Reviewer: reviewer subagent, fresh context, read-only shell. Tip `f52d672`.

## Executed

```
npm run check:all (run 1) -> exit 0: hooks 395/395, agent-hooks 7/7, backend 59 passed (8.81s), licenses 40/40, spend 15/15
npm run check:all (run 2) -> exit 0: same counts, backend 8.55s
git merge-base -> refused by the reviewer allowlist; git log/diff origin/main..HEAD used instead
```

## Findings

| Severity | file:line | Impact | Fix | Response |
|---|---|---|---|---|
| blocker | `backend/loreos/smoke.py`, `.claude/harness.json` exempt | `paid:smoke -- --dry-run` or `-h` ran the paid flow unasked (the guard exempts any subcommand containing the token) | smoke: `--dry-run` preflight only, `--help` usage, refuse other args; test it | Fixed in `6386464`; `tests/test_smoke.py` |
| major | `.claude/harness.json` exempt `-h` | `-h` hides in `--header` and `employee-handbook.md`, so paid posts got no ask | Drop `-h`; fixtures | Fixed in `6386464`; fixtures in `check-spend.mjs` |
| minor | `.claude/harness.json` patterns | `-F`/`-d` with the `i` flag match `-f`/`-D`; bundled flags, `--module`, `-mloreos`, `$r = irm`, `-Method:Post`, PS 5.1 curl alias missed | Widen patterns, fixtures, KNOWN-GAPS | Fixed in `6386464`: HTTP pattern now fails closed on any client naming a paid route |
| minor | `backend/loreos/ingest.py` | A failed rerun of a processed document keeping stale chunks was unchecked | Test it | Fixed in `5ee06c2` |
| minor | `backend/loreos/ingest.py` | Configured-key scrub unproven (test keys all matched `sk-`) | Non-`sk-` key case | Fixed in `5ee06c2` |
| minor | `backend/loreos/answering.py` | `TOP_K` (behaviour 10's five chunks) unchecked | Six-plus chunks, assert five reach the draft | Fixed in `5ee06c2` |
| minor | `backend/loreos/main.py` | A multipart body is received and spooled in full before the 413 | Reject on Content-Length first | Fixed in `5ee06c2` |
| nit | `backend/tests/test_local_only.py` | Cross-origin ask asserted on fakes an empty workspace never calls | Upload first | Fixed in `5ee06c2` |
| nit | `backend/loreos/llm.py` | Walrus falsy on a 0-dimension vector | `is not None` | Fixed in `5ee06c2` |

Also fixed in `5ee06c2`, from the automated security review of `4971b51`: the Origin check compared hostnames, so a page on another local port passed. An Origin must now equal the Host.

Out of scope, also fixed in `6386464`: `npm run-script paid:smoke` and `npm.cmd run paid:smoke` were unasked.

## Verdict

fix then re-review. Re-review of the fix wave: [branch-rereview.md](branch-rereview.md).

## Does NOT prove

Bypass spellings were read from `guard.mjs`, not run by the reviewer (the main session's fixtures then confirmed all twelve red before the fix). `paid:smoke`, `db:migrate` and `dev:api` were not run. The testdb-stopped path was not observed. CI was not seen. Browser Origin behaviour was taken from the Fetch spec.
