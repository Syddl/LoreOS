## Report: fix wave 1 (P4 whole-branch review findings 1, 3, 7 and 12)

The fixes for all four findings are in commit `3c6807c` on `worktree-agent-a9c33a2e9eeedb47a`. It fast-forwarded from `a2cb7e7`. `npm run check:backend` passes: 700 passed, 2 skipped. All four red-proofs passed.

### Files touched

| File | Change |
|---|---|
| `backend/loreos/verify_rls.py` | The `policy` check now compares the whole policy. Two new checks: `other_policy` and `isolated`. |
| `backend/loreos/main.py` | The lifespan runs `verify_rls.problems()`. `BodyLimit` uses a 64 KB cap everywhere except the upload route. |
| `backend/tests/test_isolation.py` | 3 new negatives, revised expected sets, the `OnConnection` fake, and an engine/`database_url(` scan. |
| `backend/tests/test_app.py` | New tests for the startup check, the 100 KB login, the 100 KB upload and the chunked small cap. The probe app gets an echo on the upload path. |

### Old vs new

| Behaviour | Before | After |
|---|---|---|
| `policy` check | Passed if a policy named `workspace_isolation` existed on both tables. | On each table there must be exactly one `workspace_isolation` policy. It must be permissive and `for all`, with roles exactly `{loreos_app}`. Its using and with check conditions must equal the migration's, compared through `pg_get_expr`. |
| Other policies | Not seen. | `other_policy` fails if any policy with another name applies to `documents` or `chunks`. |
| Live isolation | Not checked. | `isolated` opens `workspace_session(uuid4())`, which uses its own connection and only reads. Both counts must be 0. If the switch or the read is refused (`DBAPIError`), the check fails. |
| api startup | Checked only the two keys. | If the keys pass, it then runs `verify_rls.problems()` on a `system_session`, logs each problem at ERROR and raises `RuntimeError` naming them. |
| Body cap | 20 MB + 64 KB on every route. | 64 KB on every route, for both the declared length and the counted bytes. Only POST on the upload route keeps `MAX_REQUEST_BYTES`. The 413 message reads "the request is over 64 KB; only a document upload may be larger". |
| Caller scan | Only `system_session(` and `engine()`. | It also flags `create_(async_)engine` or `database_url(` outside the allowlist. `db.py` is allowed because it builds the one engine. `settings.py` is allowed because it defines `database_url()`, the only reader of `DATABASE_URL`. A grep found no other reader. |

Design notes:
- **Expected condition:** `verify_rls.ISOLATION` holds the condition as Postgres 17 renders migration 0002's `ISOLATION`. The positive test on the migrated database (now on `ab` data) pins that the two agree.
- **How the upload route is recognised:** it is taken from the router itself (`documents.add_document`'s `APIRoute.matches`), so the path is not written out a second time in `main.py`.
- **Negatives and `isolated`:** in the negatives, `loreos.db.engine` is replaced by `OnConnection`, a savepoint on the admin connection. That lets `isolated` see the rolled-back change, and it avoids hanging on the AccessExclusiveLock that `create`/`alter policy` hold. The negatives now use `ab`, so a leak always has rows to show.

New negatives, as specified:
- **extra-policy:** expected `{other_policy, isolated}`.
- **condition-changed:** expected `{policy, isolated}`.
- **select-only:** expected `{policy}`.

Existing expectations that gained `isolated`: bypassrls, superuser, member-of-the-owner, rls-off and loreos-usage. no-set-option stays `{set_option}`: Postgres judges `SET ROLE` against the session user, which is postgres in that negative, so the session still opens there.

### How tested

Red first. The new `ISOLATION` constant was added on its own beforehand so the module loads. A temporary probe file `backend/loreos/zz_engine_probe.py` held a bare `create_async_engine(...)` call; it was deleted after the run and never committed.
```
uv --directory backend run python -m pytest tests/test_isolation.py tests/test_app.py -q -rf
FAILED tests/test_isolation.py::test_verify_rls_names_what_breaks_isolation[bypassrls]
FAILED ...[superuser]  ...[member-of-the-owner]  ...[rls-off]
FAILED ...[extra-policy]        AssertionError: assert [] == ['isolated', 'other_policy']
FAILED ...[condition-changed]   AssertionError: assert [] == ['isolated', 'policy']
FAILED ...[select-only]         AssertionError: assert [] == ['policy']
FAILED ...[no-set-option]  ...[loreos-usage]
FAILED tests/test_isolation.py::test_the_negatives_cover_every_check
FAILED tests/test_isolation.py::test_only_the_listed_files_build_an_engine_or_read_database_url
       AssertionError: assert {'zz_engine_probe.py'} == set()
FAILED tests/test_app.py::test_a_chunked_body_off_the_upload_path_stops_past_the_small_cap
FAILED tests/test_app.py::test_a_100_kb_json_body_to_login_is_refused_before_parsing
FAILED tests/test_app.py::test_startup_with_a_verify_rls_problem_raises_naming_it
```
The no-set-option failure above was my own wrong expectation of `isolated`. I corrected it with the reason in a comment.

Green:
```
uv --directory backend run python -m pytest tests/test_isolation.py tests/test_app.py
66 passed in 28.25s
npm run check:backend          (on 3c6807c, clean tree)
700 passed, 2 skipped in 257.88s (0:04:17)
```

Red-proofs (`redproof.mjs --project . --check "uv --directory backend run python -m pytest tests/test_isolation.py tests/test_app.py"`, each run with `--expect`):

1. In `verify_rls.py`, `and p.polname <> 'workspace_isolation') as other_policy` was replaced with `and false) as other_policy`.
```
FAILED tests/test_isolation.py::test_verify_rls_names_what_breaks_isolation[extra-policy]
  AssertionError: assert ['isolated'] == ['isolated', 'other_policy']
1 failed, 65 passed   | restored byte-identical | green after restore | redproof: PASS
```
2. In `main.py`, `settings.startup_problems() or await _isolation_problems()` was replaced with `settings.startup_problems()`.
```
FAILED tests/test_app.py::test_startup_with_a_verify_rls_problem_raises_naming_it  (DID NOT RAISE RuntimeError)
1 failed, 65 passed   | restored byte-identical | green after restore | redproof: PASS
```
3. In `main.py`, `MAX_BODY_BYTES = 64 * 1024` was replaced with `MAX_BODY_BYTES = MAX_UPLOAD_BYTES`.
```
FAILED tests/test_app.py::test_a_chunked_body_off_the_upload_path_stops_past_the_small_cap
FAILED tests/test_app.py::test_a_100_kb_json_body_to_login_is_refused_before_parsing  (assert 401 == 413)
2 failed, 64 passed   | restored byte-identical | green after restore | redproof: PASS
```
4. Extra proof, because the 100 KB upload case could not be red before the change: in `main.py`, `if UPLOAD.matches(scope)[0] is Match.FULL:` was replaced with `if False:`.
```
FAILED test_a_chunked_body_is_counted_across_messages_and_stops_past_the_cap
FAILED test_a_body_declared_over_the_cap_is_refused_by_the_real_app_before_routing
FAILED test_a_100_kb_upload_is_under_the_upload_cap
3 failed, 63 passed   | redproof: PASS
```

What the new tests do not exercise:
- `isolated` on a separate connection inside a negative. There it runs through the savepoint fake; the real separate-connection path runs only in the positive and startup tests.
- A case where `isolated` fails while every static check passes. No such case was found to build.

### Limitations

- **Two existing tests were edited.**
  - The declared-length test now posts to the upload path instead of `/api/nope`, because `/api/nope` now gets the 64 KB cap. Its assertions are unchanged.
  - `send_chunks` now posts to the upload path by default, so the existing chunked test's body is unchanged and stays green.
- **Supabase not run.** `ISOLATION` is Postgres 17's rendering. If Supabase's version renders the condition differently, `policy` will report a false problem rather than a false pass. Running `npm run db:verify-rls` against Supabase would settle it.
- **`isolated` proves nothing on a database with no rows.** The policy checks cover that case.
- **The api now needs the database at startup.** If the database is unreachable, the api no longer starts and answers 503 on health; it fails at startup with the connection error's traceback rather than a named problem. Compose starts the api after migrate. `npm run check:compose` and `check:all` were not run.
- **The upload route's JSON `{url}` form** shares the route, so it keeps the 20 MB cap. Its body is read only after `current_member` has authenticated the request.

### Findings outside the owned files

- `backend/loreos/worker.py:174`: `_rls_problems` does the same thing as `main._isolation_problems`. They could share one helper in `verify_rls`. Owner: implementer (3.3).
- `docs/sdd/p4-platform-shell/spec.md`:
  - Behaviour 13 and the Upload-limit rows mention only the 20 MB cap. Nothing records the 64 KB cap on other routes, the api's startup isolation check, or the new `other_policy` and `isolated` checks.
  - Row 1-3 should mention the exact policy and the live count.

  Owner: dispatcher.
