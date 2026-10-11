# Report: fix wave 2, review finding 2. A systemic failure after a paid call is now counted

Fixed and committed as `b7152a5`. The new tests went red before the fix and pass after it, and `npm run check:backend` is fully green: 695 passed, 2 skipped.

## Files touched

| File | Change |
|---|---|
| `backend/loreos/worker.py` | edited: in `record_failure`, a systemic failure now counts when the stage is `store` or the error is an `EmbeddingDimensionError`. A failure outside the stages that happens before the processing step returns is now labelled `lock`, not `store`. |
| `backend/tests/test_worker.py` | edited: a `revoked()` helper and 3 new tests |

## Old vs new

| Behaviour | Before | After |
|---|---|---|
| `EmbeddingDimensionError` (its first batch is paid) | `pending`, attempts 0, retried every 300 s with no end | counted. It backs off +30 s, then +120 s, and is `failed` at attempt 3, after exactly 3 embed calls. The worker still pauses 300 s each time. |
| Missing grant at `store` (sqlstate 42501, after the embedding is bought) | `pending`, attempts 0 | `pending`, attempts 1, retry in +30 s, error `store: systemic: ProgrammingError: …` |
| `AuthenticationError` or `insufficient_quota` at embed (nothing paid yet) | `pending`, attempts 0 | unchanged |
| Database error before the stages start (opening the session, or the `select … for update` row lock) | labelled `store`, uncounted | labelled `lock`, uncounted. Without this, the new rule would have counted these, and nothing was paid for them. |
| Log line | `worker failed … stage=<s> class=systemic` and `worker paused class=systemic` | unchanged. It names the class, and `run_once` still returns `systemic`. |

The decision uses the exception class and the stage only, never the message. `classify` is unchanged.

## How tested

**Red, before the fix:**
```
uv --directory backend run python -m pytest tests/test_worker.py
FAILED tests/test_worker.py::test_a_dimension_error_after_its_paid_batch_is_counted_so_the_document_fails_at_the_third
FAILED tests/test_worker.py::test_a_missing_grant_at_store_after_the_embedding_is_bought_is_counted
FAILED tests/test_worker.py::test_a_missing_grant_at_the_row_lock_before_any_spend_stays_uncounted
3 failed, 48 passed in 26.07s
```
- The dimension and store cases failed with `assert ('pending', 0) == ('pending', 1)`.
- The lock case failed because the error began with `store: systemic: ProgrammingError: …` instead of `lock: …`.
- I then changed one assertion in each grant test: SQLAlchemy 2.1's message does not include the asyncpg class name, so they now check for `permission denied for table chunks` (or `documents`).

**Green, after the fix:**
```
uv --directory backend run python -m pytest tests/test_worker.py
51 passed in 19.09s

npm run check:backend
695 passed, 2 skipped in 240.61s (0:04:00)
```

**What the new tests do:**
- The store and lock tests use real grants. The test revokes `insert on loreos.chunks` (or `update on loreos.documents`) from `loreos_app`, commits the revoke, and grants it back in a `finally`.
- The `AuthenticationError` and `insufficient_quota` tests still pass unchanged, with `pending` and attempts 0.

**Red-proof (not run, as instructed).** Each `--find` string occurs exactly once in `backend/loreos/worker.py` (checked with `grep -c`).
1. To make a post-spend systemic failure uncounted again:
   - `--find`: `counted = klass != "systemic" or stage == "store" or isinstance(error, llm.EmbeddingDimensionError)`
   - `--replace`: `counted = klass != "systemic"`
   - This turns red `test_a_dimension_error_after_its_paid_batch_is_counted_so_the_document_fails_at_the_third` and `test_a_missing_grant_at_store_after_the_embedding_is_bought_is_counted`.
2. To put back the old `store` label for failures before the stages:
   - `--find`: `else ("lock" if count is None else "store", e)`
   - `--replace`: `else ("store", e)`
   - This turns red `test_a_missing_grant_at_the_row_lock_before_any_spend_stays_uncounted`.

## Limitations

- **Billing is decided per class, not per call.** If an `AuthenticationError` or `insufficient_quota` arrives on a second or later batch of a large document (over 100 chunks), earlier batches were already paid, but it stays uncounted as before. The brief scopes this rule to class and stage.
- **Commit-time failures.** A database error at the commit after the stages is labelled `store`, and would be counted if systemic. No test covers that path: commit errors are not class 42 or 3F in practice.
- **New stage name.** `lock` is a new value in the stored `error` text and in the `stage=` log field. The plan's list of stages (fetch, parse, embed, store, plus lease) does not mention it.
- **No real run.** No real OpenAI call was made and the worker was not run for real.

## Findings outside the owned files

- `docs/sdd/p4-platform-shell/plan.md`, "The worker": the systemic row says "`pending`, not counted", and the stage list lacks `lock`. Both need updating to this behaviour. Suggested owner: dispatcher.
- `docs/KNOWN-GAPS.md`: the review's alternative was a row for the endless loop. It is no longer needed, but a cost line could be added: up to 3 bought batches per document per deployment fault. Suggested owner: dispatcher.
