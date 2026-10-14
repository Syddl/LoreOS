# Review: p3-hybrid-search, tasks 1.1 to 2.2 (step 7)

Lens: correctness, with security where it applies. Reviewer: harness:reviewer, with fresh context and a read-only shell. Range: `2ac35dd..4868804`.

## Executed

```
npm run check:all       exit 0
  check:hooks 395/395, check:agent-hooks 7/7,
  check:backend 786 passed in 279.43s (test_rerank.py with the real cached model),
  check:licenses 67/67 + 84/84, check:spend 123/123, check:frontend 39 tests, build ok
git status --porcelain --untracked-files=all   (empty after the suite)
```

The reviewer also read fastembed 0.9.0's installed source:
- `define_cache_dir()` creates the directory;
- a cached model loads without network access;
- a fresh download takes the hub's current revision.

## Findings

| Severity | Where | Impact | Fix | Owner |
|---|---|---|---|---|
| minor | `check_licenses.py`, License-File fallback | A package that declares nothing and ships only `AUTHORS` or `NOTICE` now passes. No copyleft package that used to fail now passes. | Accept the file text only when it names a permissive license; add an `AUTHORS` case that must fail. | 1.3 |
| minor | `rerank.py`, `model()` | The fastembed imports and `define_cache_dir()` run outside the `try`. An onnxruntime `ImportError`, or a `PermissionError` on the cache, escapes as a raw traceback, with no fix and no RERANK=off. | Move them inside the `try`, and test it. | 1.3 |
| minor | `retrieval.py`, `search()` and `keyword_search` | `keyword_search` runs after the paid embedding. A question holding NUL would fail in Postgres (22021) after the spend once a hybrid mode is the default. Not executed. | Run keyword search before the embedding, and replace NUL. | 1.1, 2.1 |
| minor | `evaluation/__main__.py`, `--chunk-tokens` | No ceiling. `--chunk-tokens 10000` would pay for some embeddings before the model's 8191-token limit stops ingest. | Cap the flag. | 2.2 |
| minor | `retrieval.py`, `tests/test_retrieval.py` | No test proves the rerank runs off the event loop (behaviour 4). | Assert that the fake rerank runs on another thread. | 2.1 |
| nit | migration 0003 | `@@` is not leakproof, so under RLS the planner may not use `chunks_tsv`. That is a performance question. | Run `explain` under `workspace_session`, and record the result. | 1.1 |
| nit | `spec.md`, acceptance row 7 | It names `tests/test_eval_modes.py`, which does not exist. | Point it at `test_eval_cli.py` and `test_eval_run.py`. | main session |
| nit | `evaluation/run.py`, `settings` | It records `rrf_k`, but not the fusion and rerank depths. | Add `fuse_depth` and `rerank_depth`. | 2.2 |
| nit | `tests/test_eval_run.py` | `search_ms >= 50` could pass on a slow runner without the rerank. | Sleep well above a search's own time. | 2.2 |

Out of scope: `NEAREST` orders by distance alone, with no `c.id` tiebreak, and it now feeds RRF.

## Verdict

Merge. There is no blocker or major. The minors and nits are fixed before phase 3. See the fix wave below.

## Does NOT prove

- **Not run:** Supabase, OpenAI and `check:compose`.
- **Not executed:** the NUL failure and the index plan.
- **Not observed:** CI on Linux.
- **Not re-run:** the redproofs.

## Fix wave

Each finding was fixed red first, in the commit that records this file; STATUS lists the commit.
