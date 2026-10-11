# Review: p4-platform-shell plan (plan lens)

Lens: plan. Reviewer: harness:reviewer, with fresh context and a read-only shell. Subject: `C:/Users/justine/Documents/code/loreos/.claude/worktrees/p4-platform-shell/docs/sdd/p4-platform-shell/plan.md` at `a05f789`.

## Executed

```
git status --short        -> clean
git log --oneline -8      -> tip a05f789
git merge-base HEAD main  -> refused by the reviewer shell (not on the allowlist)
npm run check:all         -> exit 0
  check:hooks 395/395, check:agent-hooks 7/7
  check:backend 330 passed, 2 skipped in 48.38 s (uv created backend/.venv, 40 packages)
  check:licenses 40/40, check:spend 98/98
git diff main...p2-baseline -- backend/loreos/db.py ... settings.py
  -> do_connect listener inside engine(), 3 attempts, RETRIES; DEFAULT_JUDGE_MODEL "gpt-6-luna"
```

**Facts confirmed by reading:**
- the db layer (`db.py:14-28`);
- `process()`: `attempts + 1` up front (`ingest.py:95`), the savepoint around the store step (`:105`), and `failed` recorded in the same transaction (`:113`);
- the constraints in 0001;
- conftest (`:16`, `:35-43`, `:53`, `:61-65`, `:126-132`);
- the exact-set and default pins in `test_config.py`;
- MPL handling in `check_licenses.py:11-17`;
- the spend-pattern behaviour (check-spend cases);
- the check-wiring rules (`check-wiring.mjs:185-260`, which never reads the `check:all` command);
- redproof refuses a dirty tracked tree and an untracked target (`redproof.mjs:203-207`);
- httpcore2 2.13.1: `network_backend` (`connection_pool.py:60`) and `server_hostname` = origin host (`connection.py:136`);
- httpx2 decoders yield at most 1 MiB per step for gzip, brotli and zstd (`_decoders.py:52-250`), so a gzip bomb is held to bounded memory.

**Red-first claims.** I judged these by reading only. Two are wrong: findings 3 and 4, plus the `paid:worker` count in finding 8.

## Findings

| Severity | Location | Impact | Fix | Owner |
|---|---|---|---|---|
| major | `plan.md:651-655`; `spec.md:67` | **Login rate limit can be beaten by concurrency.** Login does peek, then verify, then increment, so N parallel wrong guesses all pass the peek: the "5 per email" limit becomes as many guesses as one burst can fit. The bucket keys on the raw email, so case variants each get a fresh bucket. In compose, every client arrives from the Docker gateway (`FORWARDED_ALLOW_IPS` defaults to 127.0.0.1), so the IP bucket is shared by everyone and 20 failures lock out all logins. | Reserve first: `rate_limit` both buckets before verifying and refund on success (`count = count - 1`). Key on `normalize_email`. Test: 20 concurrent wrong logins for one email give at most 5 `verify` calls (spy). Add a KNOWN-GAPS row for the shared gateway IP. | main session (behaviour 8 wording), 4.2 |
| major | `plan.md:89-92`, `:241`, `:393` | **The connection semaphore can hang the api.** It has no acquire timeout and nothing forbids nesting. Login's natural shape (`authenticate(conn)` with the session open, then `rate_limit` opening its own `system_session`) holds one permit and waits for a second, so 10 concurrent bad logins freeze the process for good. Health uses `engine()` outside the cap, so the peak is 12, not 11. | In `db.py`, a ContextVar guard that raises when a task opens a session while it holds one, with a test. Acquire with a timeout and answer 503. Count health against the cap. | 1.3, 4.2 |
| major | `plan.md:70-73`, `:330`; `conftest.py:53` | **1.2's mutation cannot go red.** The per-checkout database persists and `upgrade head` does nothing once it is at `0002_platform`. Dropping `'docx'` from the migration file never reaches the database, so redproof fails. The same stale schema follows the P3 `down_revision` re-point. | The bootstrap drops and recreates `loreos_test_<checkout>` each session (`WITH (FORCE)`). Quote and sanitise the name: `p4-platform-shell` has hyphens, and identifiers truncate at 63 bytes. | 1.2 |
| major | `plan.md:727`, `:731`, `:982`; `answering.py:32-36` | **4.4's every-field test cannot fail on this branch.** `Answer` has exactly found, text, citations and reason, and P1's four-field mapping returns all four. The stated redproof stays green, and the claim that the test covers P3's `retrieval_mode` is unproven until P3 merges. | The test patches `answering.answer` to return a dataclass with an extra field and asserts that field appears in the JSON. | 4.4 |
| major | `plan.md:344-351`, `:359` | **`verify_rls` has one negative case.** The live Supabase row trusts all its other assertions: RLS enabled, policy present, BYPASSRLS, LOGIN, superuser, owns a relation, auth-table grants, the SET option, `USAGE` on vector's schema. Any of these could be a no-op and every test would stay green. | Add parametrised negatives inside a rolled-back transaction: `disable row level security`, `drop policy`, `grant select on loreos.users to loreos_app`, `alter role loreos_app bypassrls`, `owner to loreos_app`, `revoke usage on schema public`. | 1.3 |
| major | `plan.md:688-702` | **Possible IDOR in `routes/workspaces.py`, untested.** These routes run in `system_session`, with no RLS behind them. Nothing checks that `DELETE api-keys/{B's key}` or `DELETE members/{user}` on A's path returns 404 and leaves B alone. A missing `and workspace_id = :w` would revoke B's key or remove the user from every workspace. "Invite stored as its hash" also has no check. | Add these cases to `test_keys.py` and `test_workspaces.py`. Assert `invites.token_hash = sha256(token)`. | 4.3 |
| minor | `plan.md:739-745` | **The no-off-switch pin is narrow.** Setting env keys at request time cannot catch a switch read at import or one under an unlisted name. The `DATABASE_URL` and `ALLOWED_HOSTS` rows can never fail. | Add a source scan: `os.environ` or `getenv` only in `settings.py`, plus an allowlist (`ingest.scrub`'s key, smoke's `npm_config_dry_run`). | 4.5 |
| minor | `plan.md:381-384`; `harness.json:21`, `:113` | **1.4's red-first count is wrong.** `npm run paid:worker` already asks through the generic `paid:` regex, so removing `worker` turns two cases red, not three. Missing ask cases: `docker compose watch`, `docker compose --profile test up -d` with no service, and `npm run db:migrate`. Phase 7 says the operator approves the migration, but the guard does not ask. The disk quirk still says 23 GB. | Fix the claim. Add the cases and a `db:migrate` ask. Set the disk quirk to 20 GB. | 1.4 |
| minor | `plan.md:71`, `:85` | **Role creation races.** Two transactions running `create role` at once fail with `unique_violation` (23505), not `duplicate_object`. This hits `loreos_app` and the bootstrap's `testdb_owner`. | Catch both errors. | 1.2 |
| minor | `plan.md:106-114`, `:593` | **Worker writes have no fence.** Record-failure and release update by id only. A stale worker, after the 10-minute idle kill, can reset a row another worker has claimed since. Separately, nothing checks that processing runs as `loreos_app` in the document's workspace (behaviour 3). | Write `where locked_until = :claimed_lease`, with a test. Assert `current_user` and `app.workspace_id` in the idle-timeout probe. | 3.3 |
| minor | `plan.md:690` | Two owners removing each other at the same time both pass the last-owner count, leaving the workspace with no owner. | `select ... for update` on the workspace's owner rows before counting. | 4.3 |
| minor | `plan.md:262`, `:795` | The invite token sits in URL paths, so uvicorn's access log records a live secret. | Send the token in the POST body, and use `/invite#<token>` in the UI. | main session (contract), 4.2, 5.2 |
| minor | `plan.md:926-934` | `check:compose` never proves its env isolation. If the `!reset` regresses, `migrate` runs against `.env`'s Supabase from a free check. | Step 0: run `config --format json` and assert every service's `DATABASE_URL` is checkdb and the key is the fake one. | 6.1 |
| minor | `plan.md:892` | On Python 3.14 under Windows, piped stdin decodes in the ANSI code page (quirk 5). `--long` JSON carries non-ASCII descriptions, so the check can crash or produce mojibake. | Read with `json.load(sys.stdin.buffer)`. | 5.6 |
| minor | `plan.md:985`; P3 `spec.md:33` | P3 behaviour 7 loads the reranker in the api **and the worker**. P4 states "api only". | Record it in P3's STATUS as a requirement change. At merge, add a test that `import loreos.worker` does not import `rerank`. | main session |
| minor | `plan.md:189-201`; conftest | **Phase 7 names no checkout.** This worktree has no `.env`, and the main checkout is on another branch. conftest does not pin `ALLOWED_HOSTS` or the model keys, so a `.env` copied in changes the tests. | Name the checkout in phase 7. conftest sets every `_env` key. | main session, 1.2 |
| nit | `plan.md:184` | The raw `\|` makes the `rg` pattern a literal pipe, so the check can never find anything. | Move it out of the table: `rg -n -e '"/api/documents' -e '"/api/ask'`. | main session |
| nit | `plan.md:679`, `:703` | A POST to an unrouted path gets 405 from the GET catch-all, not 404. | Reword the red-first reason. | 4.2, 4.3 |
| nit | `spec.md:35`; `plan.md:688` | The plan sends member, invite, key and workspace-creation routes through `system_session`, beyond the spec's "only callers" list. | Record it in the spec's revision table. | main session |

Out of scope: P1's ask route holds its transaction across the OpenAI draft call. With the new 10-permit cap, slow asks now queue every other request (covered by the semaphore fix's timeout).

Window ownership: no file has two owners in any window. All protected paths are assigned to the main session. The spend patterns do not collide with the implementers' pytest commands.

## Verdict

Fix then re-review.

## Does NOT prove

- No per-task pytest, `redproof` or `check-wiring` run: the tests do not exist yet, and pytest and node scripts outside `check:*` are not on the allowlist. Red-first claims were judged by reading only.
- `git merge-base` was refused. I used `main...p2-baseline` instead.
- Nothing ran against Supabase: its Postgres major, the `SET` grant, the `extensions` schema, Supavisor's pool size.
- Not verified:
  - that `npm ls --long` emits `license`;
  - the Docker, Compose and Node versions;
  - free disk (`df` is not on the allowlist);
  - the corpus sizes;
  - shadcn and Vite 8 compatibility.
- I did not read P3's branch, only its spec on this tree.
- Not probed: whether a `commit()` inside `workspace_session` continues as the owner role, which would bypass RLS. It needs a test if anyone ever commits mid-session.
