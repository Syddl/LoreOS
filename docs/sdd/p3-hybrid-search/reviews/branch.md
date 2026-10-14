# Review: p3-hybrid-search, whole branch (step 9)

Lens: whole branch, with security and spend. Reviewer: harness:reviewer, with fresh context and a read-only shell. Range: `main` `2ac35dd`..`47eeb97`.

## Executed

```
npm run check:all   run 1 at 47eeb97: 395/395 · 7/7 · 796 passed in 282.55s · 67/67 + 84/84 · 123/123 · 39 tests, build ok · exit 0
npm run check:all   run 2 at 47eeb97: 395/395 · 7/7 · 796 passed in 280.99s · 67/67 + 84/84 · 123/123 · 39 tests, build ok · exit 0
git status --porcelain --untracked-files=all   (empty before and after both runs)
```

**The numbers.** Every number in decisions 0009 and 0010 matches its result file:
- Recall@5, MRR@10, citation accuracy, answerable refused, faithfulness, and p50/p95.
- The costs, recomputed from `usage` at the pinned prices: $0.1058, $0.1310, $0.1462, $0.1251, $0.1545 and $0.1383.
- The SHA, workspace and hashes the decisions claim.
- All seven files pass `result_problems`.

**Behaviour 9 and the fallback.** Behaviour 9 is applied correctly. The `off` → `vector` change is consistent everywhere except `plan.md`.

**The image.** fastembed loads from its cache first, so the real compose file needs no network. `HF_HUB_OFFLINE=1` forces cache-only, so a missing bake fails the check.

## Findings

| Severity | Where | Impact | Fix | Owner |
|---|---|---|---|---|
| minor | `smoke.py` (`preflight`), reached from `evaluation/preflight.py` | Now that the default is `hybrid_rerank`, `paid:eval --mode vector` or `--mode hybrid` loads the reranker through `smoke.preflight`, which spec behaviour 7 does not ask for. An offline host fails a vector-only preflight. The `pf` fixture hides it. Nothing is spent. | The caller decides: `smoke.preflight(reranker=...)`, which the evaluation passes as False, since it loads by mode itself. | main session |
| minor | `retrieval.py` (the rerank), KNOWN-GAPS | The rerank uses asyncio's default executor, the pool argon2 uses for login. Concurrent asks would queue logins behind reranks of several seconds. The KNOWN-GAPS row's "the other routes keep serving" is wrong. | Give the rerank its own small pool, and correct the row. | main session |
| minor | `Dockerfile` | Not executed. The `chown -R` in a later layer probably stores the model twice. The bake also sits after `COPY backend/`, so any source change downloads it again. | Bake and chown in one `RUN`, before the rest of the source. Compare with `docker history`. | main session |
| nit | decision 0010, KNOWN-GAPS | "The rerank adds about 2.3 s" is hybrid_rerank minus vector. The rerank alone is about 2.1 s over hybrid. | Say which. | main session |
| nit | STATUS, KNOWN-GAPS | The plan's "chunk size per mode" item and the eval-workspace pruning trigger have fired, with no question to the operator or pointer. | Add both. | main session |
| nit | `plan.md` | Two lines still say `off` serves `hybrid`. | Annotate them. | main session |
| nit | `ci.yml` | The comment says only `test_rerank.py` loads the real model. | Reword it. | main session |

## Verdict

Merge. There is no blocker or major. Merging still needs the operator's yes on decision 0010's default and the `vector` fallback.

## Does NOT prove

- **Not run:** paid commands, OpenAI, Supabase, Docker and CI on Linux; those were taken from STATUS.
- **Inferred from reading, not executed:** the three minors.
- **Not recomputed:** the per-question and shortcode counts.
- **Authenticity:** a forged result file would also pass `result_problems`.
- **Not audited:** native libraries inside the wheels.

## Fix wave

STATUS lists the fix commit.
