# Review: p3-hybrid-search plan (plan lens)

## First review, of `c9f6cae`

Lens: plan (LIFECYCLE step 5). Reviewer: harness:reviewer, with fresh context and a read-only shell.

### Executed

```
npm run check:all            (tip c9f6cae, testdb on 127.0.0.1:54329)
check:hooks        395/395 checks passed
check:agent-hooks  7/7 installed adapter checks passed (offline)
check:backend      712 passed in 211.13s
check:licenses     48/48 installed backend packages pass; 84/84 frontend npm packages pass
check:spend        123/123 spend checks passed
check:frontend     tsc -b ok; vitest 7 files, 39 tests passed; vite build ok
exit code 0

git log --oneline main..HEAD   -> c9f6cae, 478cd96, db1a32c (docs only)
git check-ignore -v eval/results/x.json docs/sdd/p3-hybrid-search/scratch/x.log eval/scratch/x.json
                               -> only the scratch log is ignored; eval/results/*.json is NOT ignored
```

**Facts check.** Every planning fact the reviewer checked against the code was correct.

It found five facts missing from the plan:
- the worker also calls `startup_problems()`;
- `test_auth.py` pins every environment read outside `settings.py`;
- `ingest.py` imports from `retrieval`;
- `tree_clean()` counts untracked files, and `eval/results/` is not ignored;
- `test_eval_run.py` and `test_eval_cli.py` assume only `vector` mode exists.

### Findings

| Severity | Where | Impact | Fix | Owner |
|---|---|---|---|---|
| blocker | `evaluation/run.py` (`tree_clean`, `_scratch_reasons`), `preflight.py` | An untracked file counts as a dirty tree, and `eval/results/` is not ignored. With `--mode all`, mode 1 writes to `eval/results/`, so modes 2 and 3 go to scratch after paying. In the sweep, run 2's preflight refuses because run 1's result is untracked, and committing that result breaks "one SHA". | Ignore untracked `eval/results/*.json` in `tree_clean`; add a temp-repo check and a three-file `--mode all` check. Commit and write ledger rows only after the third run. | plan, then 2.2 |
| major | `test_answering.py`, `run.py`, `test_eval_run.py`, `test_eval_cli.py`, `test_eval_preflight.py` | After 2.1 and 2.2, existing tests go red in files no task owns. | Give each file to a task, and name each edit. | plan |
| major | `ingest.py` | A module-level `retrieval` → `rerank` → `ingest` → `retrieval` import is a cycle, and it breaks the api and the evaluation at import. | Import `ingest` inside `rerank()`. | 1.3 |
| minor | `test_auth.py`'s environment-read pin | Reading `FASTEMBED_CACHE_PATH` in `rerank.py` fails the pin. | Use fastembed's `define_cache_dir()`. | 1.3 |
| minor | `functools.cache` on `model()` | The result of the failure test depends on test order. | Add a `cache_clear` fixture. | 1.3 |
| minor | RRF ties | At k = 60, a realistic tie with different best ranks cannot be built from floats. | Use `Fraction`, and a k = 0 fixture. | 1.2 |
| minor | spec, acceptance row 6 | No check that the worker never loads the model. | Add the worker case. | 2.1 |
| minor | behaviour 8 | No check that `search_ms` covers the rerank. | Add a 50 ms sleep case. | 2.2 |
| minor | the result's `settings` | It lacks the reranker model and the RRF k. | Add `rerank_model` and `rrf_k`. | 2.2 |
| minor | CI cache | `~` in `FASTEMBED_CACHE_PATH` is not expanded. | Use an absolute path, keyed on the model. | 1.3 |
| minor | `check:compose` | It passes even when the bake failed, by downloading at startup. | Set `HF_HUB_OFFLINE=1` for the api. | phase 3 |
| minor | `test_chunking.py::test_defaults` | Decision 0009 turns it red before `--mode all`. | Update it at step 5 and run `check:all`. | phase 3 |
| minor | `smoke.py` | It would load the model after paying for ingest. | Load the model in `smoke.preflight` when the serving mode needs it. | phase 3 |
| minor | migration 0003 | It relies on the `PUBLIC` execute grant, and `array_to_string` is unqualified. | Grant execute to `loreos_app`, and use `pg_catalog.array_to_string`. | 1.1 |
| minor | spec Risks | The README line and the shortcode check have no step. | Add both, or hand the README line to P5. | plan |
| nit | `preflight._print_plan` | The `all` multiplier leaves out the question embeds. | Multiply them too. | 2.2 |
| nit | the plan's opening | It counts three protected paths; there are five. | List all five. | plan |
| nit | 1.1 | The phrase-operator sentence contradicts the probe. | Delete it. | plan |
| nit | 2.2 | The `workspace_name` case repeats an existing test. | Assert on `settings.chunk_tokens` and the chunk sizes instead. | 2.2 |
| nit | the plan's opening | redproof needs a clean tree. | Run it after each task's commit. | plan |
| nit | the CLI | `RERANK=maybe` prints a traceback. | Exit 2 with the message. | 2.2 |

Out of scope: the ask route's transaction stays open through the embedding, the draft and the rerank. That is P1's pattern.

### Verdict

Fix then re-review.

### Does NOT prove

- **Not run:** any paid command, `check:compose`, and `db:migrate` on Supabase.
- **Found by reading, not reproduced:** the blocker and the import cycle.
- **Not verified, needs install or network:** fastembed's API, wheels and licenses.
- **Reported by the main session, not run by the reviewer:** the testdb probes.
