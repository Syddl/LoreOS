# Review: p1-thin-slice plan

Lens: plan
Reviewer: reviewer subagent, fresh context, read-only shell.

## Executed

```
npm run check:hooks        -> 395/395 passed
npm run check:agent-hooks  -> 7/7 passed
git rev-parse HEAD origin/main -> both f7cbe21 (no branch commits yet)
check-wiring.mjs           -> not run (not on the reviewer allowlist); read: line 202 fails a check: script with no file unless meta
```

## Findings

| Severity | Where | Impact | Fix | Response |
|---|---|---|---|---|
| major | plan 2.5 | Live spend fixtures in `scripts/check-hooks.mjs`, a library template that `init --update-guard` overwrites | Project-owned `scripts/check-spend.mjs` as `check:spend` | Taken |
| major | plan design, 4.1 | `meta_scripts` exempts the backend checks from CI coverage; 4.1's red-first could never fail | Thin `.mjs` wrappers | Taken: `check-backend.mjs`, `check-licenses.mjs` |
| major | plan 3.1 | No check on behaviour 10's ranking (operator, order, k, workspace filter) | Ranking test with `fake_embed` | Taken: `test_retrieval.py` |
| major | plan design, 3.1 | Store-stage failure, key scrub and idempotent rerun untested; "replaces chunks" unstated | Tests for each; delete inside the savepoint | Taken |
| major | plan 2.5 | POST `/api/ask` and `/api/documents` spend through curl/Invoke-RestMethod without an ask | Spend regex with fixtures | Taken |
| minor | plan 2.2-2.4 | Red-first named only `ModuleNotFoundError` | Name an assertion against a stub | Taken |
| minor | plan 1.1/2.3 | `fake_embed` in conftest had no owner | Move to 1.1 | Taken |
| minor | plan design | `answer_from_hits(q, [])` behaviour unstated | State and test it | Taken |
| minor | plan 2.1, 3.1 | Behaviours 1, 5-8, 12, 14, 21 had no named check | Name each | Taken: parsing, chunking, answering and `test_config.py` |
| nit | plan design | Schema name repeated; cached OpenAI client outlives its loop | `search_path`; per-loop client | Client: taken (built per call). Schema: kept explicit, reason in the plan |

Out of scope: `backend/` scaffolding existed before approval; `httpx` absent from dev deps (TestClient uses httpx2 here, so the plan was corrected instead).

## Verdict

fix then re-review. Fixes applied to plan.md the same day; the task reviews at step 7 cover the re-review, because the changes add checks and move none of the design.

## Does NOT prove

`check-wiring.mjs` and `lint-harness` were read, not run. Nothing of the backend was executed. Supabase facts, wheel availability and `.env` were not verified by the reviewer (the plan's facts section has the main session's readings).
