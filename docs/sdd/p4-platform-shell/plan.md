# Plan: p4-platform-shell

Implements [spec.md](spec.md), as revised against P1 and P2. Sizing: this phase is an auth and data-isolation surface, so all fourteen lifecycle steps run and step 9 is done by an independent reviewer. Step 5's first review returned "fix then re-review" ([reviews/plan.md](reviews/plan.md)). This revision answers every finding; the table at the end maps each one to its change.

## Facts read before planning

- **The db layer.**
  - `db.engine()` is a cached NullPool engine. `workspace_session(workspace_id)` is plain `engine().begin()`, with no role switch.
  - `p2-baseline` (not on `main` yet) adds a `do_connect` listener inside `engine()`. It retries `ConnectionResetError` up to 3 attempts and counts them in `RETRIES`.
  - P4 edits only the session context managers, so the listener merges beside P4's change without overlap.
- **Settings** are read when used. `tests/test_config.py` pins two things:
  - the exact set of `_env("...")` names in `settings.py` equals the keys in `.env.example`;
  - each model default equals its example line.

  `p2-baseline` changes `DEFAULT_JUDGE_MODEL` to `gpt-6-luna` in `settings.py` and in `.env.example`.
- **main.py** serves P1's unscoped routes on `DEFAULT_WORKSPACE_ID`:
  - `TrustedHostMiddleware(LOCAL_HOSTS)`;
  - an Origin rule that lets a request with no `Origin` through;
  - a 413 for a declared `Content-Length` over the cap. Otherwise the route calls `file.read(cap + 1)`, after Starlette has already spooled the body;
  - an `/api/ask` response built from four named fields.
- **ingest.py.**
  - `ingest()` deduplicates by sha256 within a workspace and reprocesses a `failed` duplicate inline.
  - `process()` adds 1 to `attempts` before it starts and deletes the chunks. It records any failure as `failed` in the same transaction, with a savepoint around the store step.
  - A failed document has no chunks, because search does not filter by status.
  - `_scrub` removes keys from error text.
- **The evaluation workspace key** hashes the source text of `parsing.py`, `chunking.py` and `ingest.py`, plus `inspect.getsource` of `llm.embed` and `retrieval.vector_literal`. Every P4 edit to those files gives the next evaluation a new key.
- **Migration 0001.**
  - `documents.kind` has an inline check, which Postgres names `documents_kind_check`.
  - `content` is `bytea not null`, with `unique (workspace_id, sha256)`.
  - Chunks reference `(document_id, workspace_id)`.
  - `create extension if not exists vector` does nothing on Supabase, where `vector` lives in the `extensions` schema.
  - `downgrade` raises.
- **conftest.py** connects as the `postgres` superuser to `loreos_test` on 127.0.0.1:54329.
  - `sql()` runs one event loop per statement.
  - `clean` empties documents and every workspace except the default one.
  - `client` is a `TestClient` that does not run the lifespan.
- **P1 and P2 assertions the spec changes:**
  - `test_documents_api.py`: 201 and 200 responses, `attempts` 1 and 2, a 415 for `.docx`, and error text without a failure class.
  - `test_ask_api.py`: the unscoped `/api/ask`, and exact equality on the refusal dict.
  - `test_local_only.py`: Host, Origin and the declared-length 413, all on P1 routes.
  - `test_ingest.py`: `attempts` 2.
  - `test_licenses.py`: MPL allowed for certifi only.
- **check_licenses.py** reads the installed distributions. Its `COPYLEFT` regex includes MPL, and `MPL_ALLOWED = {"certifi"}`.
- **The guard's spend pattern for interpreters** needs python or uv, then `loreos`, then a paid module word.
  - `tests/test_ingest.py` does not match, because `_` is a word character.
  - `backend/loreos/ingest.py` matches, and `worker.py` will match once 1.4 lands.
  - An absolute worktree path contains `loreos`.
  - The guard asks before an edit to a protected path, and an implementer subagent cannot answer an ask.
- **check-wiring** (in the harness library) requires:
  - a `check:<topic>` script naming each `scripts/check-*.mjs` file, and a file behind each `check:*` script;
  - a CI step for each, in package.json order;
  - `check:all` last.

  It never reads `check:all`'s command, so `check:compose` can be a CI step and stay out of `check:all`.
- **CI** runs one `checks` job. testdb is a service container (pg17, user `postgres`) that starts before checkout, so no repo file can feed its init.
- **httpx2 2.13.1.**
  - `AsyncHTTPTransport` takes no network backend, but `httpcore2.AsyncConnectionPool(network_backend=...)` does.
  - httpcore2's connection passes the origin host as TLS `server_hostname`.
  - So a pool whose backend dials the checked IP keeps SNI and the certificate check on the host name.
- **Installed versions:**
  - backend: Starlette 1.7.0, FastAPI 0.142.2, SQLAlchemy 2.1.3, Python 3.14.3, uv 0.11.3;
  - Docker 29.6 and Compose v5.2, which support `env_file` with `required: false`, `!reset`, `!override` and `up --wait`;
  - Node 22.22 and npm 10.9.
- **Corpus sizes.** The largest text file is `handbook/values/_index.md`: 116 KB, about 60 chunks, one embedding request. The largest PDF is 6 MB and 40 pages.
- **Disk.** `df` shows 20 GB free on C: today, not 23.
- **Repo settings.** `.gitattributes` is `* text=auto eol=lf`. `.gitignore` ignores `dist/` and `node_modules/`. There is no root lockfile.

## Design choices inside the spec

- **testdb's init is conftest's bootstrap.** The session `db` fixture connects as `postgres` to the `postgres` database. Then it:
  1. creates `testdb_owner` (`LOGIN CREATEROLE BYPASSRLS`) when absent, catching both `duplicate_object` and `unique_violation`;
  2. **drops and recreates** the test database, then sets `testdb_owner` as owner and installs `vector` in `public`. Every session therefore migrates from empty, so a changed migration file always reaches the database: this is what lets 1.2's mutation and P3's re-pointed `down_revision` go red.
     - **The name** is `loreos_test_` plus the checkout directory name, with every character outside `[a-z0-9_]` replaced by `_`, cut to 63 bytes, and always quoted. The bootstrap asserts the prefix before it drops anything.
     - **The admin connection** is hard-coded to `postgres@127.0.0.1:54329`, never read from the environment, so it can never point at Supabase. It runs in autocommit, which `DROP` and `CREATE DATABASE` require.
     - **No `FORCE`.** When another session is connected to this checkout's database, such as a second pytest run in the same checkout, the bootstrap stops, naming the database, rather than killing that session.
     - **Role drift.** After creating the roles, the bootstrap runs `alter role loreos_app nologin nobypassrls nosuperuser`. Roles are cluster-wide, so a role left wrong by one checkout is reset rather than leaking into the next.
     - **Removed worktrees** leave their databases behind. testdb runs on tmpfs, so restarting the container clears them.
  3. migrates, then runs every test connected as `testdb_owner`.
  4. **pins every `_env` key** that `settings.py` reads to a test value, so a `.env` in the checkout changes no test. Today these are `ALLOWED_HOSTS` and the model keys.

  Why not a container init file:
  - CI's service container starts before checkout, so it cannot mount one.
  - The one container on port 54329 is shared by every checkout, P3's included, and a checkout without the file may have started it.

  Why one database per checkout:
  - Parallel implementer worktrees never share `clean`.
  - P3's and P4's Alembic histories never meet in one `alembic_version`.

  `docker-compose.yml` and `ci.yml` do not change for this.
- **Revision id `0002_platform`** (file `0002_platform_shell.py`), not `0002`. A database at P3's own `0002` then shows up as a second head, which fails loudly, and never passes for P4's revision.
- **`loreos_app` is created inside `exception when duplicate_object or unique_violation`.** Roles are cluster-wide, and two worktrees can migrate at the same time. Concurrent `create role` statements fail with `unique_violation`, not `duplicate_object`.
- **The role switch.** `workspace_session` first runs `select set_config('role','loreos_app',true), set_config('app.workspace_id',:w,true)`.
  - Both settings are transaction-local. So no code ends the transaction inside a session: sessions commit only when their context exits.
    - A `commit`, a `rollback` other than a savepoint's, or a `reset role` or `set role` would drop the switch, and later statements would run as the owner, bypassing RLS.
    - A source scan in 1.3 pins this.
  - Each of `documents` and `chunks` gets one policy, `workspace_isolation`: `for all to loreos_app using (...) with check (...)`.
  - RLS is enabled but not forced. The table owner bypasses it, in `system_session` and in `sql()`, as behaviour 2 expects.
- **No connection cap in v1.**
  - The api opens one connection per session, one session after another within a request. The worker handles one document at a time.
  - A burst of concurrent requests beyond Supavisor's client limit gets connection errors: a 500 for those requests, which is not data loss.
  - Both caps tried in review failed:
    - a `db.MAX_CONNECTIONS` semaphore deadlocks on nested sessions (first review, finding 2);
    - uvicorn's `--limit-concurrency` counts idle keep-alive sockets, so two browser tabs polling the documents list get plain-text 503s (re-review, F1).

    A correct cap needs an acquire timeout, a JSON 503 and a guard against nested sessions. That is more code than a learning build's traffic justifies.
  - 6.2 adds a KNOWN-GAPS row. It triggers when users report 500s under load, or when a deployment expects more concurrent users than the pooler's client limit.
  - The live row records the pool size.
  - **Row-lock waits.** Deleting or re-queueing a document can wait on the worker's row lock for minutes. So both run with `set local lock_timeout = '2s'`, and a timeout answers 409 "the document is being processed; try again shortly".
- **Attempts and errors.**
  - `ingest.run_stages()` locks the row (`select ... for update`), replaces the chunks and marks the document `processed`. On failure it raises `StageError`; it never records anything.
  - `ingest.process()` keeps P1's inline contract for `ingest()`, which the evaluation and `paid:smoke` use. It records `failed`, adds 1 to `attempts` and writes P1's error text, `<stage>: <Exception>: <message>`.
  - The worker writes `<stage>: <class>: <Exception>: <message>`.
  - Recording `failed` always deletes the document's chunks, on both paths.
  - A success never adds to `attempts`. So a processed document has `attempts` 0, and a failed rerun has 1.
- **The worker.**
  - **Claim.** One statement in `system_session`, `for update skip locked`. It takes the oldest due `pending` row, or a `processing` row whose lease ran out.
    - An expired lease adds 1 to `attempts`, with error `lease: transient: the worker stopped before finishing (lease expired)`.
    - At the third attempt the row becomes `failed` without processing. Otherwise it is processed under a new 10-minute lease.
  - **Row lock.** `run_stages` holds the row lock for the whole processing transaction. So a live worker's row is skipped even after its lease has run out.
  - **Idle timeout.** The processing transaction sets `idle_in_transaction_session_timeout` to `10min` locally, matching the lease.
  - **Recording a failure.** The worker records in a new `system_session`, after the rollback:

    | Class | Effect |
    |---|---|
    | permanent | `failed`, `attempts` +1 |
    | transient | `attempts` +1, then `pending` with `next_attempt_at` +30 s, then +2 min; `failed` at the third |
    | systemic | `pending`, not counted. `run_once` returns `systemic`, and `main` sleeps 300 s |

  - **Fenced writes.** Recording a failure and releasing a claim both update `where id = :d and locked_until = :claimed_lease`. A stale worker, one whose transaction was killed by the idle timeout, then changes nothing on a row that another worker has claimed since. Zero rows updated is logged, not raised.
  - **Stopping.** `CancelledError` or `KeyboardInterrupt` releases the claim (back to `pending`, lease cleared, not counted), then re-raises. On Linux a SIGTERM handler cancels the main task, so `docker compose stop` releases the claim the same way.
  - **Startup.** The worker checks `settings.startup_problems()` and `verify_rls.problems()`, and exits naming any problem. Without the grant check, a missing grant would fail every store after the embedding is paid for, then retry as systemic every 5 minutes.
  - **Database errors.** A database error during claim or record is logged, then the loop sleeps 2 s and carries on.
  - **Classification** (`worker.classify`), by exception class, status and error code:

    | Class | Exceptions |
    |---|---|
    | permanent | `parsing.UnsupportedType`; `parsing.ParseError`, including the DOCX cap; `fetch_url.Refused`, `TooLarge`, `UnsupportedContent`; `HTTPStatus` 4xx; `openai.BadRequestError` other than `model_not_found` |
    | systemic | `openai.AuthenticationError`, `PermissionDeniedError`, `NotFoundError`; `RateLimitError` with `code == "insufficient_quota"`; `BadRequestError` with `model_not_found`; `llm.EmbeddingDimensionError`; a database error whose asyncpg `sqlstate` is `42501` or in class `42` or `3F` |
    | transient | every other `RateLimitError`; `InternalServerError`, `APITimeoutError`, `APIConnectionError`; `HTTPStatus` 5xx; `TimeoutError`; `httpx2.TransportError`; `OSError`; SQLAlchemy `OperationalError` or `InterfaceError`, or `connection_invalidated`; anything unclassified, bounded by the three attempts |

  - **Dimension check.** `llm.embed` checks the vector size after the first batch. A wrong `EMBEDDING_MODEL` then buys one batch per systemic retry, not the whole document.
- **Sizing the idle timeout.**
  - Corpus worst case: one embedding request, a few seconds idle in transaction.
  - Upload cap worst case, a 20 MB TXT file: about 5M tokens, about 11k chunks and about 110 embedding requests, so a few minutes idle.
  - The local 10-minute setting covers that, frees a hung worker's row lock within one lease, and makes Supabase's own default irrelevant. `db:verify-rls` still prints that default for the record.
- **Origin.**
  - Every `POST`, `PUT`, `PATCH` or `DELETE` without an `Authorization: Bearer` header needs an `Origin` whose `host:port` equals `Host`. Otherwise, or with no `Origin`, it gets 403.
  - That covers cookie-authenticated writes (behaviour 9), plus login, signup and invite acceptance, which also closes login CSRF.
  - A request with a Bearer header is authenticated by the key alone, and `current_member` never falls back to the cookie.
- **Login rate limit: reserve first, refund on success.**
  - Before verifying, login calls `rate_limit` on both buckets: `login:email:<normalize_email(email)>` (5) and `login:ip:<client host>` (20).
    - The call adds 1 and refuses past the limit, so N parallel guesses can never all pass.
    - A refusal returns 429 with the larger `Retry-After`, and no verification runs.
  - A successful login calls `ratelimit.refund` on both buckets (`count = count - 1`), so only failures stay counted, as behaviour 8 requires.
    - `rate_limit` returns the `window_start` it counted in, and `refund` takes it. A login that straddles a window boundary therefore refunds its own reservation, never one in the next window.
    - Two concurrent successes each refund their own reservation. The floor at 0 keeps a count from going below what is reserved.
  - The email bucket keys on the normalised email, so case variants share one bucket.
  - Behind compose without `FORWARDED_ALLOW_IPS`, every client shares the Docker gateway's address, so 20 failures lock out all logins. 6.2 adds a KNOWN-GAPS row for this. Its fix is setting `FORWARDED_ALLOW_IPS` to the proxy's own address, never `*`, which would let a spoofed `X-Forwarded-For` rotate the IP bucket.
  - Signup and invite acceptance both refuse a password under 12 characters with 422 (behaviour 6).
  - The first draft's peek-then-count let a burst through (planning review, finding 1).
- **Invite tokens never appear in a URL path.** Accepting is `POST /api/invites/accept {token, ...}`. The UI link is `/invite#<token>`; the fragment never reaches the server, so no access log records a live token.
- **Upload limit.**
  - `main.BodyLimit` wraps ASGI `receive`. It counts body bytes and raises `HTTPException(413)` past `MAX_REQUEST_BYTES`, so a chunked upload stops at the cap too.
  - The declared-length 413 stays.
  - `MAX_UPLOAD_BYTES` lives in `routes/documents.py`, and `main.py` imports it.
- **Hosts.**
  - `TrustedHostMiddleware(allowed_hosts=settings.allowed_hosts())` reads the setting at import. That is safe because `_env` loads `.env` itself.
  - The compose healthcheck sends the first `ALLOWED_HOSTS` entry as `Host`.
- **Pinning the URL connection.**
  - For each hop, `fetch_url` builds an `httpx2.AsyncClient(trust_env=False, follow_redirects=False)`. Its transport has its own `httpcore2.AsyncConnectionPool` over a backend that dials the checked address.
  - The whole fetch, redirects included, runs under `asyncio.timeout(TIMEOUT_S)`.
  - Tests inject `resolve`, plus a `dial` hook that records the dialled address and redirects it to a local server.
- **Frontend.**
  - A small pathname router, about 30 lines, instead of react-router.
  - The citation panel is shadcn's `Sheet`, built on Radix Dialog: focus moves into the panel and returns to the marker when it closes.
  - The documents list polls every 2 s while any document is `pending` or `processing`.
  - vitest mocks `fetch`.
  - 5.1 installs every dependency and shadcn component the screens use. A screen task that needs another one reports it, and the main session adds it, since the lockfile is protected.
- **Licenses.** The rule stays in `check_licenses.problems()`. `scripts/check-licenses.mjs` runs `npm ls --omit=dev --all --json --long --prefix frontend`; `--long` adds each package's `license`. It pipes the JSON to `check_licenses.py --npm-tree -`, which reads it with `json.load(sys.stdin.buffer)`: on Windows a text-mode stdin decodes in the ANSI code page, and `--long` output carries non-ASCII descriptions.
- **check:compose never reads `.env`.**
  - It passes `--env-file scripts/compose-check.env`, an empty file.
  - An override file resets `env_file`, sets its own `environment:`, adds a `checkdb` service, and publishes the api on 127.0.0.1:18000 (`!override`).
  - Before anything starts, it runs `docker compose ... config --format json`. It stops unless every service's `DATABASE_URL` points at `checkdb`, `OPENAI_API_KEY` is the fake one, and `OPENAI_BASE_URL` is the unroutable one. If the reset ever regressed, `migrate` would otherwise run against `.env`'s Supabase from a free check.
  - It runs in its own CI job, not in `check:all`.
- **The guard lands in phase 1**, before `worker.py` exists, so no session can start the worker without an ask.
- **Process.** P2's, with P4's constraints:
  - **Worktree setup.** Each implementer works in its own worktree. The Agent tool bases worktrees on `main`, so the implementer first runs `git merge --ff-only p4-platform-shell`. Then it runs a real `uv --directory backend sync --locked` and, for a frontend task, `npm ci --prefix frontend`, with no node_modules junctions.
  - **Commands.** Pytest runs with relative paths (`uv --directory backend run ...`), and worktree names contain no paid module word.
  - **Commits.** The implementer commits its owned paths explicitly, with no attribution trailer. The main session reads the message, cherry-picks, re-commits with `-n` when needed, then removes the worktree, since disk is short.
  - **Redproof.** `redproof` runs after the commit, because it refuses a dirty tree or an untracked target.
    - The main session runs it for `smoke.py`, `ingest.py`, `worker.py` and `llm.py`, which match the spend pattern, and for its own tasks.
    - Implementers run the rest themselves, with `--project` set to their worktree.
  - **Checks.** Each acceptance check runs only the task's own tests and the existing ones it names. The main session runs `npm run check:all` at the end of each window, with testdb up and, once 5.1 has landed, `npm ci --prefix frontend` done.
  - **Line endings.** Every new check that reads text splits lines with `splitlines()` or `/\r?\n/`, because a file written on Windows can carry CRLF until it is committed.
- **Moved P1 assertions.** AGENTS.md says to preserve tests, so P1's assertions move to the scoped routes:
  - **test_local_only.py:**
    - 4.1 copies the foreign-Host case into `test_auth.py`.
    - 4.4 moves the rest to the scoped routes: a cross-origin upload stores and embeds nothing; a cross-origin ask buys nothing; a same-origin post is accepted; a declared body over the cap is refused before parsing.
    - 4.4 then deletes the file.
  - **test_documents_api.py and test_ask_api.py:** the same cases on `/api/workspaces/{workspace_id}/...` (4.4). Values change only where the spec changes them:
    - 202 and `pending` before `drain()`, and `attempts` 0 after it;
    - the failed-duplicate case goes through a permanent parse failure and is re-queued with `attempts` 0;
    - error text carries the failure class;
    - the 415 case uses `.pptx`.

## Phases

| Phase | Goal | Depends on | Check at the end |
|---|---|---|---|
| 1 | Schema, roles, RLS, the db layer, the spend guard | none | Main session: `npm run check:all` green after window A |
| 2 | Auth core, rate limit, parsers, URL fetch, smoke grant check | phase 1 | `npm run check:all` green |
| 3 | Enqueue and the stage pipeline, worker, admin | phase 2 | `npm run check:all` green |
| 4 | Routes | phase 3 | `npm run check:all` green; the route-path check below finds nothing; `test_local_only.py` is gone with every moved case present |
| 5 | Frontend, running beside phases 2 to 4 | 5.1 needs phase 1. The screens need only the HTTP contract | `npm run check:all` green, with `check:frontend` and the frontend tree in `check:licenses` |
| 6 | Image, compose, CI, docs | phases 3, 4, 5 | `npm run check:compose` green; `npm run check:all` green; both CI jobs green on the pushed tip |
| 7 | Live rows (operator, in the merge window) | phase 6, claim-green | The ledger rows below |

The phase 4 route-path check, kept out of the table because a table cell would turn its `|` into a literal: `rg -n -e 'api/documents' -e 'api/ask' backend/tests`.
- The patterns carry no leading `/`, because Git Bash rewrites an argument that starts with `/` into a Windows path (re-review, F9).
- The new routes contain `api/workspaces/`, so neither pattern matches them.

Phase 7 runs in the P4 worktree, with the main checkout's `.env` copied in. `settings.ENV_FILE` resolves to the worktree root; `.gitignore` covers it, and conftest pins every key, so the tests ignore it. Delete the copy after phase 7.

Phase 7, in order. Each step is a ledger row by hand:
1. `npm run db:migrate` against Supabase, in the window "Merge timing" allows. The guard does not ask, because it is free. The main session asks the operator in chat first, since it changes the shared database.
2. `npm run db:verify-rls`: no problem. Record `pg_has_role(...,'SET')`, `USAGE` on `extensions`, and the printed timeout.
3. `npm run paid:smoke -- --dry-run`, then `npm run paid:smoke` (each one asks).
4. `docker compose up -d` (asks). Check that `migrate` exits 0, the api is healthy and the worker is running. Then a browser at `http://localhost:8000`:
   - sign up, then upload a PDF and a URL and see both reach `processed`;
   - ask, and open a citation by keyboard;
   - create and revoke a key;
   - accept an invite in a private window.

   Save a screenshot to STATUS.
5. Read the Supavisor pool size in the dashboard, and record it in the KNOWN-GAPS row on the connection cap.
6. Record the image size from `docker system df` against free disk.

## Parallel windows

| Window | Tasks | Shared files (must be none) |
|---|---|---|
| start | 1.1, then 1.2 (main session, in order) | n/a |
| A | 1.3; 1.4 (main session) | none: `package.json` belongs to 1.3 |
| B | 2.1, 2.2, 2.3, 2.4, 2.5; 5.1 (main session) | none: `test_documents_api.py` belongs to 2.3; `package.json` and `ci.yml` belong to 5.1 |
| C | 3.1, 3.2, 5.2, 5.6 | none: `test_documents_api.py` belongs to 3.1 |
| D | 3.3, 5.3, 5.4, 5.5 | none: `conftest.py`, `llm.py` and `package.json` belong to 3.3 |
| E1 | 4.1 | n/a |
| E2 | 4.2, 4.3, 4.4 | none: `test_auth.py` belongs to 4.2; `test_isolation.py`, `test_documents_api.py` and `test_local_only.py` belong to 4.4 |
| E3 | 4.5 | n/a |
| F | 6.1, then 6.2 (main session) | n/a |

The files that force this order, with one owner per window:
- **`main.py`**: 4.1 alone. P1's routes leave it in one task, and the routers fill in afterwards.
- **`settings.py`, `.env.example`, `test_config.py`**: 1.1 alone, touched once.
- **`pyproject.toml` and `uv.lock`**: 1.1 alone. `frontend/package-lock.json` belongs to 5.1 alone.
- **The migration**: 1.2 alone.
- **`conftest.py`**: 1.2 (start), 3.3 (D), 4.1 (E1).
- **`package.json`**: 1.3 (A), 5.1 (B), 3.3 (D), 6.1 (F).
- **Test files shared across windows**:
  - `test_documents_api.py`: 2.3 (B), 3.1 (C), 4.4 (E2);
  - `test_auth.py`: 2.2 (B), 4.1 (E1), 4.2 (E2), 4.5 (E3);
  - `test_isolation.py`: 1.3 (A), 4.4 (E2).
- **`ci.yml`**: 5.1 and 6.1, both main session.

Every window ends green, with one exception. Between E1 and E2, `test_documents_api.py`, `test_ask_api.py` and `test_local_only.py::test_a_same_origin_post_is_allowed` stay red: they call P1 routes that 4.1 removes, and 4.4 closes them.

## Handoff contracts

| From | To | Handoff |
|---|---|---|
| 1.1 | all | **Settings**:<br>- `settings.DEFAULT_ALLOWED_HOSTS = "localhost,127.0.0.1"`.<br>- `settings.allowed_hosts() -> list[str]`.<br>- `settings.startup_problems() -> list[str]`: the message of each failing `database_url()` or `openai_api_key()`, each with its fix.<br>**Imports**: `argon2`, `docx`, `bs4`, `httpx2`, `httpcore2`. |
| 1.2 | all backend | **Tables**, schema `loreos`:<br>- `users(id uuid pk, email text unique check (email = lower(email)), password_hash, created_at)`.<br>- `memberships(user_id, workspace_id, role check in ('owner','member'), created_at)`, primary key `(user_id, workspace_id)`, cascading from both.<br>- `sessions(id text pk, user_id cascade, created_at, expires_at)`.<br>- `invites(token_hash text pk, workspace_id cascade, created_by on delete set null, created_at, expires_at, used_at)`.<br>- `api_keys(id uuid pk, workspace_id cascade, kind check in ('secret'), name, prefix, key_hash unique, created_at, last_used_at, revoked_at)`.<br>- `rate_limits(bucket, window_start timestamptz, count int)`, primary key `(bucket, window_start)`.<br>**`documents`**: `kind` in (`md`, `txt`, `pdf`, `docx`, `url`); `content` nullable; new `source_url text`, `next_attempt_at timestamptz` and `locked_until timestamptz`.<br>**Role and policy**: `loreos_app`, policy `workspace_isolation`.<br>**conftest**: `TEST_OWNER = "testdb_owner"`, `TEST_DATABASE`, `ADMIN_URL`. `sql()` runs as the owner. `clean` also empties `users`, `invites`, `api_keys` and `rate_limits`. |
| 1.3 | all | **db**: `db.workspace_session(workspace_id)` (same signature), `db.system_session()`.<br>**verify_rls**: `verify_rls.problems(conn) -> list[str]`, `verify_rls.idle_timeout(conn) -> str`, `verify_rls.main() -> int`.<br>**Script**: `npm run db:verify-rls`.<br>**Allowlist**: `test_isolation.SYSTEM_SESSION_FILES`. |
| 1.4 | 3.3, 6.1 | The guard asks on:<br>- `paid:worker`;<br>- python or uv naming `loreos` and `worker`;<br>- `docker compose` `up`, `start`, `restart` or `run`, except an `up` whose only service is `testdb`. |
| 2.1 | 4.2 | - `async ratelimit.rate_limit(bucket, limit, window_s) -> Slot(allowed: bool, retry_after: int, window_start: datetime)`: one upsert that adds 1; allowed while `count <= limit`.<br>- `async ratelimit.refund(bucket, window_start) -> None`: subtracts 1 from that window's row, never below 0.<br>- `retry_after` is whole seconds to the window's end, 0 when allowed.<br>- `ratelimit._now` is the clock tests patch. |
| 2.2 | 3.2, 4.x | **Passwords**: `MIN_PASSWORD = 12`, `password_problem(pw) -> str \| None`, `hash_password`, `verify_password(hash, pw) -> bool`, `normalize_email`, `async authenticate(conn, email, pw) -> User \| None`.<br>**Sessions**: `User(id, email)`, `async create_user(conn, email, pw) -> UUID`, `SESSION_COOKIE = "loreos_session"`, `SESSION_DAYS = 14`, `async create_session(conn, user_id) -> str`, `async session_user(conn, token)`, `async delete_session(conn, token)`, `set_session_cookie(response, request, token)`, `clear_session_cookie(response)`.<br>**Keys**: `KEY_PREFIX = "lo_sk_"`, `async create_key(conn, workspace_id, name) -> tuple[UUID, str]`.<br>**Dependencies**:<br>- `Member(workspace_id, role, user_id \| None, key_id \| None)`.<br>- `current_member(request, workspace_id: UUID)`: 401 for missing or bad credentials, 404 for another workspace.<br>- `current_user(request) -> User`: cookie only, so 401 without a session and 403 for a Bearer.<br>- `require_owner(member) -> Member`: 403 for a member or a key.<br>Workspace routes name their path parameter `workspace_id`. |
| 2.3 | 3.1 | - `parsing.kind_of` maps `.docx` to `docx`, and the 415 text lists it.<br>- `parsing.parse(filename, data, kind=None)`: kind `html` only through `kind=`.<br>- `parse_docx.parse(data)`, with `parse_docx.MAX_UNPACKED_BYTES = 100 * 1024 * 1024`.<br>- `parse_html.parse(data)`.<br>- Each returns `list[Section]` and raises `parsing.ParseError`. |
| 2.4 | 3.1, 3.3 | - `fetch_url.normalise(url) -> str`, which raises `Refused`.<br>- `async fetch_url.fetch(url, *, resolve=None, dial=None) -> Fetched(content: bytes, kind: "html" \| "txt" \| "pdf", url: str)`.<br>- Exceptions: `Refused`, `TooLarge` and `UnsupportedContent` (each a `ValueError`); `HTTPStatus(Exception)` with `.status`. A timeout raises `TimeoutError`, and network failures raise `httpx2.TransportError`.<br>- Constants `MAX_BYTES`, `TIMEOUT_S`, `MAX_REDIRECTS`. |
| 3.1 | 3.3, 4.4 | - `ingest.enqueue(session, workspace_id, filename, data) -> Document`.<br>- `ingest.enqueue_url(session, workspace_id, url) -> Document`, which raises `fetch_url.Refused`.<br>- `ingest.StageError` with `.stage`; the cause is in `__cause__`.<br>- `async ingest.run_stages(session, workspace_id, document_id) -> int`.<br>- `ingest.record_failed(session, workspace_id, document_id, error)`: `failed`, `attempts` +1, chunks deleted.<br>- `ingest.scrub(message)`, renamed from `_scrub`.<br>- `ingest()`, `process()` and `Document` keep their signatures. |
| 3.3 | 4.x, 6.1 | **Worker**:<br>- `async worker.run_once() -> str \| None`: `processed`, `permanent`, `transient`, `systemic`, or None when nothing was due.<br>- `worker.classify(exc) -> str`.<br>- `LEASE`, `POLL_S = 2`, `BACKOFF_S = (30, 120)`, `MAX_ATTEMPTS = 3`, `SYSTEMIC_PAUSE_S = 300`.<br>- `npm run paid:worker`.<br>**llm**: `llm.EmbeddingDimensionError(ValueError)`.<br>**conftest**: `drain() -> list[str]`, which calls `run_once` until None.<br>**Log lines**: `worker claimed document=<id>`, `worker processed document=<id> chunks=<n>`, `worker failed document=<id> stage=<stage> class=<class>`, `worker paused class=systemic seconds=300`. |
| 4.1 | 4.2 to 4.5, 6.1 | **App**:<br>- `routes/{auth,workspaces,documents}.py` each export `router = APIRouter()`.<br>- `routes.documents.MAX_UPLOAD_BYTES`.<br>- `main.BodyLimit` and `main.DIST`, both read per request.<br>- `GET /api/health`.<br>**conftest**:<br>- `ORIGIN`, and `W`, the default workspace's path prefix.<br>- `make_user(email, role=None, workspace_id=DEFAULT_WORKSPACE_ID)` and `make_key(workspace_id)`.<br>- Fixture `client`: Origin header, no credentials.<br>- Fixtures `owner` and `member`: each a `SimpleNamespace(id, email, password, client)`.<br>- Fixture `key_client`: a Bearer key for the default workspace, with no Origin and no cookie. |
| 4.2 to 4.4 | 5.x | The HTTP contract below. |
| 5.1 | 5.2 to 5.6, 6.1 | - `frontend/` scripts `dev`, `typecheck`, `test`, `build`.<br>- The `@/` import alias maps to `src/`.<br>- `src/components/ui/{button,input,label,textarea,card,badge,alert,table,sheet,dialog,dropdown-menu}`.<br>- `src/lib/utils.cn`.<br>- Root scripts `dev:web` and `check:frontend`. |
| 5.2 | 5.3 to 5.5 | - `src/api.ts`: one function per route, and `ApiError(status, detail, retryAfter)`.<br>- `src/router.ts`: `usePath()`, `navigate(to)`, `Link`.<br>- Screen props: `Documents({workspaceId, role})`, `Ask({workspaceId})`, `Settings({workspaceId})`. |

The HTTP contract. Every error is `{detail: str}`, and a 429 carries `Retry-After`. The session cookie is `loreos_session`.

```
Me       = {user: {id, email}, workspaces: [{id, name, role}]}
Document = {id, filename, kind, status, error, attempts, chunk_count, created_at, processed_at}
Answer   = {found, answer, reason, citations: [{n, chunk_id, document_id, filename, heading_path, page, text}], ...every other Answer field}

POST /api/auth/signup  {email, password, workspace_name?}  201 Me + cookie | 403 closed | 422
POST /api/auth/login   {email, password}                   200 Me + cookie | 401 | 429
POST /api/auth/logout                                      204, cookie cleared
GET  /api/me                                               200 Me | 401
POST /api/invites/accept  {token, email, password} logged out, {token} logged in
                                                           201 Me + cookie | 200 Me | 404 | 409 email taken | 422 password under 12
GET  /api/workspaces                                       [{id, name, role}]
POST /api/workspaces   {name}                              201 {id, name, role: "owner"}
under /api/workspaces/{workspace_id}:
  GET    members                  [{user_id, email, role}]                                  owner
  DELETE members/{user_id}        204 | 409 last owner                                      owner
  POST   invites                  201 {token, expires_at}                                   owner
  GET    invites                  [{created_at, expires_at, created_by}] (pending only)     owner
  POST   api-keys {name}          201 {id, name, prefix, key, created_at} (key shown once)  owner
  GET    api-keys                 [{id, name, prefix, created_at, last_used_at, revoked_at}] owner
  DELETE api-keys/{key_id}        204 | 404                                                 owner
  POST   documents  multipart file | {url}   202 Document | 200 Document (duplicate) | 413 | 415 | 422
  GET    documents                [Document]
  GET    documents/{document_id}  Document | 404
  DELETE documents/{document_id}  204 | 404                                                 owner
  POST   ask {question}           Answer
GET /api/health                   200 {"status": "ok"} | 503
```

## Tasks

### Task 1.1: Dependencies and settings (main session)

- Files owned: `backend/pyproject.toml`, `backend/uv.lock`, `backend/loreos/settings.py`, `.env.example`, `backend/tests/test_config.py`
- Depends on: none. If `p2-baseline` has landed, merge `main` first and resolve these three files by hand.
- Change:
  - Run `uv --directory backend add argon2-cffi python-docx beautifulsoup4 httpx2 httpcore2`. Never add `httpx`.
  - `settings.allowed_hosts()` and `settings.startup_problems()` follow the contract.
  - `.env.example` gains `ALLOWED_HOSTS=localhost,127.0.0.1`, and a comment explaining that uvicorn reads `FORWARDED_ALLOW_IPS` (settings does not).
  - `test_config.py` adds `ALLOWED_HOSTS` to the exact set and pins its default. It also checks that `startup_problems()` names each blank key.
- Acceptance check, all must pass:
  - `uv --directory backend sync --locked` exits 0;
  - `uv --directory backend run python -c "import argon2, docx, bs4, httpx2, httpcore2"` exits 0;
  - `uv --directory backend run python -m pytest tests/test_config.py` is green;
  - `npm run check:licenses` is green, since every new package is MIT or BSD.
- Red first: with the `.env.example` line added first, the exact-set test fails until `settings.py` reads the key. Mutation: `startup_problems` skips `openai_api_key()`, and the blank-key case goes red.
- Skills to load: superpowers:test-driven-development
- Predicted size: 5 files, about 50 lines plus the lock, 30 minutes

### Task 1.2: Test database owner and migration 0002 (main session)

- Files owned: `backend/alembic/versions/0002_platform_shell.py`, `backend/tests/conftest.py`, `backend/tests/test_schema.py`
- Depends on: none
- Change:
  - **conftest**:
    - the bootstrap described in "Design choices";
    - `DATABASE_URL` points at `testdb_owner` and `TEST_DATABASE`;
    - an unreachable testdb, or a failed bootstrap, stops the run with the command that starts testdb;
    - the test database is dropped and recreated every session, under a sanitised, quoted name;
    - every `_env` key is pinned;
    - `clean` also empties the new tables.
  - **Migration**: `revision = "0002_platform"`, `down_revision = "0001"`. `downgrade` raises, as 0001's does.
    - The six tables.
    - The `documents` changes, dropping and re-adding `documents_kind_check`.
    - `loreos_app`, `NOLOGIN`, created inside a handler for `duplicate_object` and `unique_violation`.
    - `grant loreos_app to current_user with set true`.
    - `USAGE` on `loreos` and on the schema that `pg_extension` gives for `vector`.
    - DML on `documents` and `chunks` only.
    - RLS enabled, with `workspace_isolation` on both tables.
  - **test_schema**:
    - columns and constraints: kind accepts `docx` and `url`, `content` is nullable, an uppercase email is refused, the role check holds;
    - `loreos_app` exists, with `rolcanlogin` and `rolbypassrls` both false;
    - there is exactly one Alembic head;
    - the tests' own role is not a superuser;
    - the test database name for a checkout called `p4-platform-shell` is `loreos_test_p4_platform_shell`, and a 100-character name is cut to 63 bytes;
    - with `ALLOWED_HOSTS=evil` in `os.environ` before the bootstrap, `settings.allowed_hosts()` inside a test returns the pinned value.
- Acceptance check:
  - `uv --directory backend run python -m pytest tests/test_schema.py` is green.
  - Then `npm run check:backend` is green: every P1 and P2 test passes as `testdb_owner`. RLS is on, but the owner bypasses it until 1.3.
- Red first:
  - The new cases fail with `relation "loreos.users" does not exist`, and the superuser case fails on the old conftest.
  - Mutation: drop `'docx'` from the kind check, and the kind case goes red. This works only because the bootstrap recreates the database each session; on a persisted database at head, the edited migration would never run.
- Skills to load: harness:authoring-a-check, codebase-design
- Predicted size: 3 files, about 230 lines, 75 minutes

### Task 1.3: Role switch, system sessions and the RLS assertions

- Files owned: `backend/loreos/db.py`, `backend/loreos/verify_rls.py`, `backend/tests/test_isolation.py`, `package.json`
- Depends on: 1.2
- Change:
  - **Sessions.**
    - `workspace_session` runs the one `set_config` statement first.
    - `system_session()` is one transaction as the connecting role.
    - There is no connection cap in v1 (see "Design choices").
    - `engine()` is untouched, since the `p2-baseline` listener lives there.
  - **verify_rls.problems(conn)**, read-only, checks that `loreos_app`:
    - exists, cannot log in, has no `BYPASSRLS` and is not a superuser;
    - owns no relation;
    - has no right on `workspaces` or on any auth table, and has DML on `documents` and `chunks`;
    - is subject to RLS with `workspace_isolation` on both tables;
    - can be switched to: `pg_has_role(current_user,'loreos_app','SET')` is true;
    - has `USAGE` on `loreos` and on `vector`'s schema.
  - **verify_rls.main()** prints each problem or `ok`, prints `idle_in_transaction_session_timeout`, and exits 1 on any problem.
  - **package.json** gains `db:verify-rls`: `uv --directory backend run python -m loreos.verify_rls`.
- Acceptance check: `uv --directory backend run python -m pytest tests/test_isolation.py tests/test_retrieval.py tests/test_ingest.py tests/test_eval_run.py` green. The existing callers now run as `loreos_app`. The new file sets up two workspaces with documents and chunks through `sql()`, and checks:
  - **inside A's session**:
    - `current_user` is `loreos_app`, and unfiltered counts equal A's;
    - inserting a row for B raises the RLS check, and updating B's rows touches 0 rows;
    - selecting from `loreos.users` is refused;
  - **with the role switched and no workspace set**, both counts are 0;
  - **verify_rls**: `problems()` returns `[]` on the migrated database.
    - **How the negatives run.** Every negative runs as `postgres`, connected to this checkout's `TEST_DATABASE`, never the `postgres` database: there, every `loreos` check would fail anyway and prove nothing. Each one is inside a transaction that is rolled back; role attributes and grants are transactional.
    - **What each asserts.** `problems() == [expected]`, exactly one problem, so a negative cannot pass on some other failure.
    - **The negatives** are parametrised, one per assertion in `problems()`:
      - `revoke usage on schema loreos from loreos_app`;
      - `alter table loreos.chunks disable row level security`;
      - `drop policy workspace_isolation on loreos.documents`;
      - `grant select on loreos.users to loreos_app`;
      - `revoke delete on loreos.chunks from loreos_app`, for the DML check;
      - `alter role loreos_app bypassrls`;
      - `alter role loreos_app login`;
      - `alter role loreos_app superuser`;
      - `alter table loreos.rate_limits owner to loreos_app`;
      - `revoke usage on schema public from loreos_app` **and** `revoke usage on schema public from public`. On testdb `vector` lives in `public`, which grants `USAGE` to PUBLIC, and `has_schema_privilege` counts that grant;
      - for the SET option: create a role, grant `loreos_app` to it `with set false`, `set local role` to it, and `problems()` names the `SET` option.
    - **Coverage pin.** A test asserts that the parametrisation has one case per message `problems()` can emit;
  - **source scan**: `system_session(` and `engine()` appear only in `SYSTEM_SESSION_FILES`:
    - `db.py`, `auth.py`, `ratelimit.py`, `worker.py`, `admin.py`, `verify_rls.py`, `smoke.py`;
    - `main.py`, for the health check only;
    - `routes/auth.py`, `routes/workspaces.py`, `evaluation/run.py`;
  - **nothing ends a session's transaction early**, because the role and the workspace setting are transaction-local. The scan covers `backend/loreos/`:
    - no `.commit(` or `.rollback(`, except a savepoint's (`begin_nested`);
    - no SQL text containing `commit`, `rollback`, `reset role` or `set role` outside `db.py`;
    - the scan is mutation-proven by inserting `await session.commit()` into `ingest.run_stages`.
- Red first: on the old `db.py`, the session runs as `testdb_owner` and the unfiltered count is A + B. The implementer's `redproof` removes `set_config('role','loreos_app',true)`, and the count case goes red.
- Skills to load: codebase-design, harness:authoring-a-check, superpowers:test-driven-development
- Predicted size: 4 files, about 280 lines, 80 minutes

### Task 1.4: Spend guard for the worker and compose (main session)

- Files owned: `.claude/harness.json`, `scripts/check-spend.mjs`
- Depends on: none
- Change:
  - **Spend patterns.** The interpreter pattern's module list gains `worker`. A new pattern asks for `docker compose` and `docker-compose` with `up`, `start`, `restart`, `run` or `watch`, except an `up` whose only service is `testdb`.
  - **Platform.** The disk quirk says about 20 GB free, not 23.
  - **Evidence.**
    - `jobs` names `next_attempt_at` and `locked_until`.
    - `logs` names the worker's log lines and `docker compose logs worker`.
    - `doctor` adds `docker compose ps`.
    - The `main` per-branch layout fact drops "Not created yet".
  - **New cases in check-spend.mjs.**
    - Ask: `npm run paid:worker`, `uv --directory backend run python -m loreos.worker`, `py -m loreos.worker`, `docker compose up`, `docker compose up -d`, `docker compose up -d api worker`, `docker compose up -d testdb worker`, `docker compose -f docker-compose.yml up --build`, `docker compose start worker`, `docker compose restart`, `docker compose run --rm worker`, `docker compose watch`, `docker compose --profile test up -d` (no service named, so every default service starts too), `docker-compose up`.
    - No decision (free): `docker compose --profile test up -d testdb`, `docker compose up -d testdb`, `docker compose --profile test up -d --force-recreate testdb`, `docker compose ps`, `docker compose logs worker`, `docker compose build`, `npm run check:compose`, `npm run db:verify-rls`, `uv --directory backend run python -m loreos.admin reset-password a@example.com`, `uv --directory backend run python -m pytest tests/test_worker.py`, `npm run dev:web`.
- Acceptance check: `npm run check:spend` and `npm run check:hooks` green.
- Red first: before the config edit, the worker and compose cases print `no decision` where `ask` is wanted. Mutation: remove `worker` from the module list, and its two interpreter cases go red. `npm run paid:worker` stays `ask` through the generic `paid:` pattern.
- Skills to load: harness:authoring-a-check
- Predicted size: 2 files, about 60 lines, 30 minutes

### Task 2.1: Rate limit

- Files owned: `backend/loreos/ratelimit.py`, `backend/tests/test_ratelimit.py`
- Depends on: 1.3
- Change:
  - `rate_limit` runs one `insert ... on conflict (bucket, window_start) do update set count = rate_limits.count + 1 returning count` in `system_session`.
  - Windows are fixed, computed from `_now()`.
  - `refund(bucket, window_start)` subtracts 1 from that window's row, floored at 0.
  - Old windows are never pruned: a `ponytail:` comment names the ceiling, and 6.2 adds a KNOWN-GAPS row.
- Acceptance check: `uv --directory backend run python -m pytest tests/test_ratelimit.py` green:
  - with limit 3, three calls are allowed and the fourth is refused, with `retry_after` in 1 to 60;
  - `refund` after a call lets one more call through, and a refund on an empty bucket leaves 0;
  - a call at 59 s into a 60 s window, with the clock then moved past the boundary, refunds the first window and leaves the second untouched;
  - the next window allows again (patched clock);
  - 10 concurrent calls count exactly 10;
  - buckets are independent.
- Red first: import failure. The implementer's `redproof` changes `count <= limit` to `count < limit`, and the 3-of-3 case goes red.
- Skills to load: superpowers:test-driven-development
- Predicted size: 2 files, about 100 lines, 25 minutes

### Task 2.2: Passwords, sessions, keys and current_member

- Files owned: `backend/loreos/auth.py`, `backend/tests/test_auth.py`
- Depends on: 1.1, 1.3
- Change:
  - **Hashing and tokens.**
    - Passwords go through `argon2.PasswordHasher()` defaults (argon2id).
    - `authenticate` verifies a cached dummy hash for an unknown email, so both paths run one verification.
    - Session tokens and key bodies come from `secrets.token_urlsafe(32)`. The database stores only their sha256 hex. A key's `prefix` is the first 8 characters of its random part.
  - **current_member.**
    - A Bearer header decides alone. Unknown, malformed or revoked gets 401; another workspace's key gets 404. Use updates `last_used_at`. A key's role is `member`.
    - Otherwise the cookie decides: no session or an expired one gets 401, and no membership gets 404.
    - Neither gets 401.
  - **set_session_cookie.** `HttpOnly`, `SameSite=Lax`, `Path=/`, `Max-Age` of 14 days. `Secure` only when `request.url.scheme == "https"`.
  - **Scope.** No routes. Lookups run in `system_session`.
- Acceptance check: `uv --directory backend run python -m pytest tests/test_auth.py` green, through a small FastAPI app built in the test:
  - **passwords**: a hash is argon2id and verifies; 11 characters are refused, naming 12; an email is lowercased and stripped;
  - **dummy hash**: an unknown email and a wrong password each call the hasher's `verify` once (spied), and both return None;
  - **storage**: the stored session id and key hash are the sha256 of the token, never the token itself; an expired session returns None;
  - **key format**: `lo_sk_` plus 43 base64url characters, and a prefix of 8 characters from the random part;
  - **current_member**: no credentials, 401; a member's cookie, its role; a non-member's cookie, 404; the workspace's own key, a key member; another workspace's key, 404; a revoked key, 401; a bad Bearer with a good cookie, 401;
  - **role dependencies**: `require_owner` gives a member 403 and a key 403; `current_user` with a Bearer gives 403;
  - **cookie flags**: correct over http and over https.
- Red first: import failure. The implementer's `redproof` skips the key's workspace comparison, and the other-workspace-key-404 case goes red.
- Skills to load: codebase-design, superpowers:test-driven-development
- Predicted size: 2 files, about 320 lines, 80 minutes

### Task 2.3: DOCX and HTML parsers

- Files owned: `backend/loreos/parsing.py`, `backend/loreos/parse_docx.py`, `backend/loreos/parse_html.py`, `backend/tests/test_parsing.py`, `backend/tests/test_parse_docx.py`, `backend/tests/test_parse_html.py`, `backend/tests/test_documents_api.py`
- Depends on: 1.1
- Change:
  - **parsing.py** gains only the `.docx` kind, the `kind=` argument and the dispatch, because its text keys the evaluation workspace.
  - **parse_docx.parse**:
    - sums `ZipInfo.file_size` first, and refuses a file over the cap before python-docx opens it;
    - walks `iter_inner_content()` in document order;
    - `Title` and `Heading 1` to `Heading 9` build the heading path, with `Title` above level 1;
    - a table becomes one line per row, cells joined with ` | `;
    - any python-docx failure becomes a `ParseError`.
  - **parse_html.parse**:
    - BeautifulSoup with `html.parser`;
    - drops `script`, `style`, `nav`, `header`, `footer` and `aside`;
    - `h1` to `h6` build the path the way Markdown headings do;
    - text before the first heading gets an empty path;
    - whitespace is collapsed;
    - no text at all is a `ParseError`.
  - **test_documents_api.py**: the 415 case uploads `slides.pptx` and expects `.docx` in the accepted list.
- Acceptance check: `uv --directory backend run python -m pytest tests/test_parse_docx.py tests/test_parse_html.py tests/test_parsing.py tests/test_documents_api.py` green.
  - **DOCX**, with fixtures built in the test with python-docx:
    - the heading path comes from the styles;
    - table text appears in document order;
    - with `MAX_UNPACKED_BYTES` patched to 1 KB, a normal file is refused and `docx.Document` (patched to raise) is never called;
    - a non-zip `.docx` is a `ParseError`.
  - **HTML**:
    - nesting and sibling headings;
    - the text of each removed element is absent;
    - leading text is kept;
    - entities are decoded.
- Red first: import failure. The implementer's `redproof` treats `Title` as body text, and the heading-path case goes red. Neither file matches a spend pattern.
- Skills to load: superpowers:test-driven-development
- Predicted size: 7 files, about 260 lines, 60 minutes

### Task 2.4: URL fetch with a pinned address

- Files owned: `backend/loreos/fetch_url.py`, `backend/tests/test_fetch_url.py`
- Depends on: 1.1
- Change:
  - **normalise**:
    - only `http` and `https`;
    - a host is required, and userinfo is refused;
    - the fragment is dropped;
    - scheme and host are lowercased, and a default port is dropped;
    - an empty path becomes `/`.
  - **fetch, per hop**:
    1. Resolve every address, with `loop.getaddrinfo` unless `resolve` is injected.
    2. Unwrap `ipv4_mapped`, and refuse unless every address is `is_global` and not multicast.
    3. Connect to the first checked address, as "Pinning the URL connection" describes.
  - **Redirects and limits**:
    - at most 5 redirects, each normalised and checked again;
    - `asyncio.timeout(TIMEOUT_S)` around the whole fetch;
    - decoded bytes are counted from `aiter_bytes()`, and the fetch stops past 5 MB.
  - **Status and type**:
    - 4xx and 5xx raise `HTTPStatus`;
    - `text/html` and `application/xhtml+xml` map to `html`, `text/plain` to `txt` and `application/pdf` to `pdf`;
    - any other type raises `UnsupportedContent` naming it.
- Acceptance check: `uv --directory backend run python -m pytest tests/test_fetch_url.py` green.
  - **Setup**: an `http.server` runs on 127.0.0.1 in a thread, with a stub resolver. A "public" name resolves to a global address (`93.184.216.34`), which the `dial` hook records and redirects to the local server.
  - **Refused**:
    - `127.0.0.1`, `10.0.0.1`, `169.254.169.254` and `::ffff:127.0.0.1`;
    - a name that resolves to both a public and a private address, with `dial` never called;
    - a redirect to a private name, and a 6th redirect;
    - `ftp://`, and `http://user:pw@host/`.
  - **Pinned**: the dialled address is the checked one, and `HTTP_PROXY` set to an unroutable proxy does not stop a fetch.
  - **Limits**: a gzip body that inflates past the limit is `TooLarge`; a server slower than a patched `TIMEOUT_S` raises `TimeoutError`.
  - **Status and type**: 404 and 503 raise `HTTPStatus` with that status; `image/png` is `UnsupportedContent` naming it; html, plain and pdf map to their kinds.
- Red first: import failure. The implementer's `redproof` checks only the first resolved address, and the mixed-address case goes red.
- Skills to load: superpowers:test-driven-development
- Predicted size: 2 files, about 320 lines, 90 minutes

### Task 2.5: Smoke preflight checks the grants

- Files owned: `backend/loreos/smoke.py`, `backend/tests/test_smoke.py`
- Depends on: 1.3
- Change: after the migration-head check and before listing models, `preflight()` runs `verify_rls.problems()` on the same connection. On any problem it stops, naming each one and "run npm run db:verify-rls".
- Acceptance check: `uv --directory backend run python -m pytest tests/test_smoke.py` green, against testdb:
  - with `verify_rls.problems` patched to report missing `USAGE` on `extensions`, `preflight()` raises `SystemExit` naming it, and the fake `llm.client` is never called;
  - with the real check on testdb, it reaches the fake client;
  - the existing cases are unchanged.
- Red first: on the old preflight, the new case reaches the fake client. The main session's `redproof` removes the call (`smoke.py` matches the spend pattern), and the case goes red.
- Skills to load: superpowers:test-driven-development
- Predicted size: 2 files, about 50 lines, 20 minutes

### Task 3.1: Enqueue and the stage pipeline

- Files owned: `backend/loreos/ingest.py`, `backend/tests/test_ingest.py`, `backend/tests/test_documents_api.py`
- Depends on: 2.3, 2.4
- Change:
  - **enqueue**:
    - `kind_of` runs first;
    - a duplicate that is not `failed` comes back unchanged;
    - a `failed` duplicate goes back to `pending`, with `attempts` 0 and `error`, `next_attempt_at` and `locked_until` cleared;
    - otherwise a new `pending` row is stored with its content.
  - **enqueue_url**:
    - normalises the URL with `fetch_url.normalise`, and hashes the normalised URL with sha256;
    - an existing row is re-queued as above, so submitting again fetches again. The re-queue runs with `set local lock_timeout = '2s'`, so re-submitting a URL that the worker is processing raises the lock timeout (sqlstate `55P03`) rather than waiting minutes. 4.4 answers it with 409;
    - otherwise it stores a `url` row, with `filename` and `source_url` set to the normalised URL and no content.
  - **run_stages**:
    - takes `select ... for update` on the row first;
    - a `url` row fetches (stage `fetch`), stores the fetched bytes in `content`, and parses with `kind=fetched.kind`;
    - then parse, chunk and embed; replace the chunks; mark `processed` with `processed_at`, clearing `error`, `next_attempt_at` and `locked_until`;
    - a failure raises `StageError(stage)` from its cause, with no write.
  - **process and record_failed**:
    - `process` wraps `run_stages` in a savepoint, then calls `record_failed` with P1's error text;
    - `record_failed` sets `failed`, adds 1 to `attempts` and deletes the chunks.
  - **scrub**: `_scrub` becomes `scrub`.
  - **Existing assertions updated**, per "Attempts and errors":
    - `test_processing_again_replaces_the_chunks` expects `(0, "processed")`;
    - the failed rerun expects `("failed", 1)` and no chunks;
    - `test_documents_api.py`'s `attempts` values follow.
- Acceptance check: `uv --directory backend run python -m pytest tests/test_ingest.py tests/test_documents_api.py tests/test_eval_run.py` green, with these new cases:
  - **enqueue**: stores `pending`, and `fake_embed` receives nothing; a duplicate comes back unchanged; a failed duplicate is re-queued with `attempts` 0;
  - **URLs**: the same URL twice gives one row, re-queued; an `ftp://` URL raises `Refused` and stores nothing;
  - **URL processing**: a URL row goes through `run_stages` with `fetch_url.fetch` patched to return HTML; heading paths come from `h2`, and `content` is stored;
  - **failures**: a parse failure raises `StageError` with `stage == "parse"`, and the row is unchanged;
  - **row lock**: while `run_stages` is inside `fake_embed`, `select ... for update nowait` from another connection fails.
- Red first: the new cases fail, since `enqueue` does not exist yet. The main session's `redproof` removes `for update` (`ingest.py` matches the spend pattern), and the lock case goes red.
- Skills to load: codebase-design, superpowers:test-driven-development
- Predicted size: 3 files, about 250 lines, 70 minutes

### Task 3.2: Admin reset-password

- Files owned: `backend/loreos/admin.py`, `backend/tests/test_admin.py`
- Depends on: 2.2
- Change:
  - `python -m loreos.admin reset-password <email>` asks for the password twice with `getpass`.
  - It refuses a mismatch or a `password_problem`.
  - In one `system_session`, it updates `password_hash` and deletes that user's sessions.
  - An unknown email exits 1, naming it.
  - `sys.stdout.reconfigure(errors="replace")`.
- Acceptance check: `uv --directory backend run python -m pytest tests/test_admin.py` green, with `getpass` patched:
  - the new password verifies and the old one does not;
  - that user's sessions are gone, and another user's are kept;
  - an unknown email, a mismatch and an 11-character password each exit 1 and change nothing.
- Red first: import failure. The implementer's `redproof` skips the session delete, and that case goes red.
- Skills to load: superpowers:test-driven-development
- Predicted size: 2 files, about 100 lines, 25 minutes

### Task 3.3: Worker

- Files owned: `backend/loreos/worker.py`, `backend/loreos/llm.py`, `backend/tests/test_worker.py`, `backend/tests/conftest.py`, `package.json`
- Depends on: 3.1, 1.4
- Change:
  - `claim`, `classify`, `run_once`, recording a failure, release on stop, the startup checks and `main`, all as "The worker" describes.
  - `llm.EmbeddingDimensionError`, raised after the first batch.
  - conftest gains `drain()`.
  - `package.json` gains `paid:worker`: `uv --directory backend run python -m loreos.worker`.
- Acceptance check: `uv --directory backend run python -m pytest tests/test_worker.py tests/test_llm_judge.py tests/test_no_openai.py tests/test_ingest.py` green. The tests use `fake_embed`, a raising embed, and a patched `fetch_url.fetch`:
  - **transient** (`openai.APITimeoutError`): `attempts` 1, then 2, with `next_attempt_at` about +30 s, then about +120 s. The test makes each due with `sql()`. At 3 the row is `failed` with no chunks, and `error` names `embed: transient: APITimeoutError`;
  - **permanent** (a scanned PDF): `failed` at once, `attempts` 1, no chunks;
  - **systemic** (`AuthenticationError`, and `RateLimitError` with `insufficient_quota`): `pending`, `attempts` 0, and `run_once` returns `systemic`;
  - **classification**: one parametrized row per entry in the table;
  - **claims**: two concurrent `claim()` calls on one due row give exactly one job. With `LEASE` patched to 0, a row whose processing is paused inside `fake_embed` is not taken by a second `claim()`;
  - **lease**: an expired `processing` row is claimed with `attempts` +1, once, then processed. At `attempts` 2 it ends `failed` without processing;
  - **one transaction**: reprocessing a processed document whose second vector has the wrong size fails, and leaves the previous chunks intact;
  - **killed midway**: an unhandled `BaseException` inside `fake_embed` leaves the row `processing`. Once its lease runs out, the next `run_once` counts it once and leaves exactly the expected chunks;
  - **stopped**: `CancelledError` inside `fake_embed` leaves the row `pending` with `attempts` 0;
  - **fence**: a failure recorded, and a release, with a stale lease value (the row reclaimed meanwhile) change nothing, and the reclaimed row stays `processing` under the new lease;
  - **processing context**: inside `fake_embed` during processing, the probe reads `show idle_in_transaction_session_timeout` as `10min`, `current_user` as `loreos_app`, and `current_setting('app.workspace_id')` as the document's workspace (behaviour 3);
  - **startup**: a blank `OPENAI_API_KEY`, and a `verify_rls` problem, each exit naming the problem;
  - **dimension**: `llm.embed` raises `EmbeddingDimensionError` after one batch of wrong-size vectors.
- Red first: import failure. The main session runs three `redproof` mutations (`worker.py` matches the spend pattern):
  - count a systemic failure as a transient one, and the systemic case goes red;
  - drop the expired-lease branch from the claim, and the lease case goes red;
  - drop `and locked_until = :claimed_lease` from the failure record, and the fence case goes red.
- Skills to load: codebase-design, superpowers:test-driven-development
- Predicted size: 5 files, about 500 lines, 130 minutes

### Task 4.1: App shell

- Files owned: `backend/loreos/main.py`, `backend/loreos/routes/__init__.py`, `backend/loreos/routes/auth.py`, `backend/loreos/routes/workspaces.py`, `backend/loreos/routes/documents.py` (the three routers empty, plus `MAX_UPLOAD_BYTES`), `backend/tests/conftest.py`, `backend/tests/test_app.py`, `backend/tests/test_auth.py`
- Depends on: 2.2, 3.3
- Change:
  - **main.py** drops P1's routes and `LOCAL_HOSTS`, and adds:
    - the lifespan: it logs each `startup_problems()` message at ERROR, then raises `RuntimeError` naming the keys;
    - `TrustedHostMiddleware` with `allowed_hosts()`;
    - the Origin rule;
    - `BodyLimit`, plus the declared-length 413;
    - `GET /api/health`: `select 1` through `engine().connect()`, and 503 on any error;
    - the three routers;
    - last, a `GET /{path:path}` fallback:
      - `api/...` gets a JSON 404;
      - a file inside `DIST` gets that file;
      - anything else gets `DIST/index.html`;
      - with no `DIST`, a 404 naming `npm run build --prefix frontend`.
  - **conftest**: the fixtures in the contract.
  - **test_auth.py**: gains P1's foreign-Host case, on `/api/health`, and the Origin cases.
- Acceptance check: `uv --directory backend run python -m pytest tests/test_app.py tests/test_auth.py` green:
  - **Host**: `evil.example:8000` gets 400;
  - **Origin**:
    - a write to any path with a foreign, `null` or missing Origin gets 403;
    - a same-host Origin gets past the middleware;
    - a Bearer write with no Origin gets past it;
    - a GET needs no Origin;
  - **BodyLimit**: a chunked body over the cap, sent to a test route that reads its body, gets 413;
  - **health**: 200, and 503 with the engine patched to fail;
  - **UI fallback**: with `DIST` patched to a temporary build:
    - `/` and `/login` return `index.html`, and `/assets/app.js` returns the file;
    - `/api/nope` returns a JSON 404;
    - an encoded `..` path never leaves `DIST`;
    - with no build, `/` returns the 404 naming the command;
  - **startup**: `with TestClient(app)` and a blank `OPENAI_API_KEY` raises, naming it.
- Red first: on the old `main.py`, a missing Origin gets through and there is no health route. The implementer's `redproof` restores P1's rule (a missing Origin passes), and that case goes red.
- Expected red until 4.4: the cases listed under "Parallel windows".
- Skills to load: codebase-design, superpowers:test-driven-development
- Predicted size: 8 files, about 340 lines, 80 minutes

### Task 4.2: Auth routes

- Files owned: `backend/loreos/routes/auth.py`, `backend/tests/test_auth.py`
- Depends on: 2.1, 2.2, 4.1
- Change:
  - **signup**, under `pg_advisory_xact_lock`:
    - refused with 403 once any user exists;
    - a password under 12 characters gets 422, naming the minimum;
    - otherwise creates the user and a workspace named `workspace_name` (default "My workspace");
    - adds owner memberships on that workspace and on `DEFAULT_WORKSPACE_ID`;
    - creates a session.
  - **login**, as "Login rate limit" describes:
    - `rate_limit` on both buckets per 900 s, before verifying: `login:email:<normalize_email(email)>` (5) and `login:ip:<client host>` (20);
    - either one refused gets 429, with the larger `Retry-After`, and no verification;
    - wrong credentials get one 401 body for both cases, and stay counted;
    - a success calls `refund` on both buckets.

    Each rate-limit call opens its own short `system_session`, before or after the `authenticate` session and never inside it.
  - **logout** deletes the session row and clears the cookie. **me** returns `Me`.
  - **invite accept** (`POST /api/invites/accept`, with the token in the body), in one transaction:
    1. `update ... set used_at = now() where token_hash = :h and used_at is null and expires_at > now() returning workspace_id`. No row gets 404.
    2. Logged in: add the membership, idempotently.
    3. Logged out: create the account and a session. A password under 12 characters gets 422, and an email already registered gets 409. In both cases the invite stays unused, because the transaction rolls back.
- Acceptance check: `uv --directory backend run python -m pytest tests/test_auth.py` green:
  - **signup**:
    - an 11-character password gets 422, and no user is stored;
    - the second signup gets 403;
    - two concurrent first signups, with `auth.create_user` patched to sleep 0.3 s first, give one 201 and one 403;
    - the first owner sees its new workspace and Default, and never an `eval-*` one;
  - **cookie and session**:
    - cookie flags are set on login, with `Secure` from an `https://` base URL;
    - logout deletes the row, and `/api/me` afterwards gets 401;
  - **rate limit**:
    - the 6th failure for one email gets 429 with `Retry-After`;
    - **concurrent guesses**: 20 wrong logins for one email call the hasher's `verify` at most 5 times. They are sent truly at once with `asyncio.gather` over an `httpx2` ASGI transport. The `verify` spy blocks on an `asyncio.Event`, set once every request has either reached `verify` or been answered. Under peek-then-count, all 20 would then pass the peek before any failure is written;
    - `A@Example.com` and `a@example.com` share one bucket;
    - after 20 failures across emails from one client, the next request gets 429;
    - **refund arithmetic**: after 4 failures, a correct password logs in, and its reservation is refunded (count 4 of 5). The next wrong password gets 401 (count 5), and the one after gets 429. A variant with `refund` patched to do nothing gets 429 on the attempt right after the success;
    - an unknown email and a wrong password give identical status and body;
  - **invites**:
    - an invite is single use: the second accept gets 404;
    - an expired invite gets 404;
    - a 409 leaves the invite usable, and so does a 422 for an 11-character password;
    - a logged-in accept adds the membership.
- Red first: the router is empty, so a GET gets 404 and a POST gets 405, from the GET catch-all. The implementer runs three `redproof` mutations:
  - remove the advisory lock, and the concurrent-signup case goes red;
  - replace the reservation with peek-then-count (read the bucket, verify, then count a failure), and the concurrent-guesses case goes red;
  - drop the `password_problem` call from invite accept, and its 422 case goes red.
- Skills to load: superpowers:test-driven-development
- Predicted size: 2 files, about 330 lines, 80 minutes

### Task 4.3: Workspace, member, invite and key routes

- Files owned: `backend/loreos/routes/workspaces.py`, `backend/tests/test_workspaces.py`, `backend/tests/test_keys.py`
- Depends on: 2.2, 4.1
- Change:
  - The routes in the contract, all in `system_session`, so there is no RLS behind them. Every statement on `memberships`, `invites` or `api_keys` therefore carries `and workspace_id = :w`, where `:w` is the path's workspace that `current_member` checked.
  - The members, invites and keys routes depend on `current_member`, then `require_owner`, and refuse keys.
  - Removing the last owner gets 409. The route first locks the workspace's owner rows (`select ... for update`), so two owners removing each other cannot both pass the count.
  - An invite is `token_urlsafe(32)`, stored as its sha256, and lasts 7 days.
  - Keys come from `auth.create_key`. The list never includes `key`, and revoking sets `revoked_at`.
- Acceptance check: `uv --directory backend run python -m pytest tests/test_workspaces.py tests/test_keys.py` green:
  - **workspaces**: create and list; a workspace the user is not a member of, and any `eval-*` one, are never listed;
  - **members**:
    - list and remove; removing the last owner gets 409;
    - two owners removing each other at once leave exactly one owner;
    - on A's path, `DELETE members/{user}` for a user who is a member of B only gets 404, and the B membership stays;
  - **invites**:
    - listed while pending, and gone once used;
    - the stored `token_hash` is `sha256(token)`, and the token itself is stored nowhere;
  - **test_keys.py**:
    - a key is shown once and is absent from the list;
    - it is stored as its sha256, with a prefix of 8 characters from the random part;
    - a member gets 403 on the members, invites and keys routes, and so does a key;
    - a revoked key gets 401;
    - a key on another workspace's path gets 404;
    - on A's path, `DELETE api-keys/{B's key id}` by A's owner gets 404, and B's key still works.
- Red first: the router is empty, so a GET gets 404 and a POST gets 405. The implementer runs two `redproof` mutations:
  - drop `require_owner` from the key routes, and the member-403 case goes red;
  - drop `and workspace_id = :w` from the key revoke, and the B-key case goes red.
- Skills to load: superpowers:test-driven-development
- Predicted size: 3 files, about 330 lines, 80 minutes

### Task 4.4: Document and ask routes

- Files owned: `backend/loreos/routes/documents.py`, `backend/tests/test_documents_api.py`, `backend/tests/test_ask_api.py`, `backend/tests/test_isolation.py`, `backend/tests/test_local_only.py` (deleted)
- Depends on: 3.1, 3.3, 4.1
- Change:
  - **POST documents** reads `request` itself:
    - JSON `{url}` goes to `enqueue_url`, and a `Refused` gets 422;
    - a multipart `file` (`request.form(max_files=1)`) gets P1's filename cleanup, then the 413 and 415 checks, then `find_by_sha` and `enqueue`. A duplicate that is not `failed` gets 200, anything else 202;
    - any other content type gets 415.
  - **List, get and delete**: delete is owner only. All three run through `workspace_session`. Delete runs with `set local lock_timeout = '2s'`, and a lock timeout (sqlstate `55P03`) answers 409, "the document is being processed; try again shortly".
  - **ask** returns `asdict(answer)` with `text` renamed `answer`. That one mapping is what lets P3's `retrieval_mode` through.
  - **Moved assertions**: the P1 cases move as "Moved P1 assertions" lists, then `test_local_only.py` is deleted.
- Acceptance check: `uv --directory backend run python -m pytest tests/test_documents_api.py tests/test_ask_api.py tests/test_isolation.py` green:
  - every moved P1 case, with `drain()` between the upload and the processed state;
  - **upload limit**: 413 at 20 MB, both with `Content-Length` and with a chunked generator body. Nothing is stored and `fake_embed` is never called;
  - **roles**:
    - a member uploads, lists and asks, and gets 403 on delete;
    - an owner deletes;
    - a key lists and asks in its own workspace;
  - **URLs**: a URL is queued with 202 and kind `url`, and submitting it again gives 202 again;
  - **lock timeout**: while another connection holds the document row with `select ... for update`, delete gets 409 within about 2 s, and so does re-submitting a URL whose row is locked;
  - **ask fields**: `answering.answer` is patched to return a dataclass with P1's four fields plus an extra `retrieval_mode`, and the JSON carries `retrieval_mode`. Today `Answer` has exactly the four fields P1 mapped, so only an extra field can tell a field-by-field mapping from `asdict`;
  - **isolation**: two workspaces with chunks.
    - With A's key, the list returns only A's ids, and ask cites only A's chunk ids.
    - A's key on B's documents gets 404.
- Red first: the router is empty, so a GET gets 404 and a POST gets 405. The implementer's `redproof` builds the ask response from four named fields, as P1 did, and the extra-field case goes red.
- Skills to load: superpowers:test-driven-development
- Predicted size: 5 files, about 340 lines, 80 minutes

### Task 4.5: No off switch

- Files owned: `backend/tests/test_auth.py`
- Depends on: 4.2, 4.3, 4.4
- Change: one parametrized test over the routes in `main.app.routes` that start with `/api/workspaces`, plus `/api/me`. It asserts at least 15 such routes.
  - **Keys**: every key `settings.py` reads, plus `AUTH`, `AUTH_DISABLED`, `DISABLE_AUTH`, `NO_AUTH`, `LOGIN_REQUIRED`, `RLS` and `HARNESS_HOOKS`.
  - **Values**: each key is set to `off`, `false`, `0`, `1` and empty.
  - **Request**: no credentials, but with an Origin.
  - **Expected**: 401 every time.
  - **Source scan**, which also catches a switch read at import or under an unlisted name:
    - It matches `\benviron\b` and `getenv` under `backend/loreos/`, which also catches `from os import environ`.
    - Every hit outside `settings.py` must appear in an allowlist keyed on **file and key**, each entry with its reason. So a new read, even in an allowlisted file, fails. Today's entries:
      - `ingest.py`: `OPENAI_API_KEY`, which `scrub` removes from error text;
      - `smoke.py`: `npm_config_dry_run`;
      - `evaluation/__main__.py`: the `npm_config_*` loop and `npm_config_dry_run`;
      - `evaluation/calibration.py`: `INIT_CWD`.

      None of these can gate a route.
    - The scan prints what it found, so a new reader fails naming its file and key.
- Acceptance check: `uv --directory backend run python -m pytest tests/test_auth.py` green.
- Red first: the implementer runs three `redproof` mutations:
  - insert `if os.environ.get("DISABLE_AUTH") == "1": return Member(workspace_id, "owner", None, None)` at the top of `auth.current_member`, and both the request pin and the source scan go red;
  - insert a module-level `_OFF = os.getenv("LOREOS_OPEN")` in `auth.py`, and the source scan goes red;
  - add `os.environ.get("SKIP_SCRUB")` to `ingest.py`, an allowlisted file with a new key, and the source scan goes red.
- Skills to load: harness:authoring-a-check
- Predicted size: 1 file, about 70 lines, 30 minutes

### Task 5.1: Frontend scaffold and check:frontend (main session)

- Files owned:
  - `frontend/package.json`, `frontend/package-lock.json`, `frontend/index.html`, `frontend/vite.config.ts`, `frontend/tsconfig*.json`, `frontend/components.json`;
  - `frontend/src/main.tsx`, `frontend/src/App.tsx` (a placeholder), `frontend/src/index.css`, `frontend/src/lib/utils.ts`, `frontend/src/lib/utils.test.ts`, `frontend/src/test-setup.ts`, `frontend/src/components/ui/*`;
  - `scripts/check-frontend.mjs`, `package.json`, `.github/workflows/ci.yml`.
- Depends on: none (it runs in window B)
- Change:
  - **Stack**:
    - Vite 8, React 19, strict TypeScript, and Tailwind 4 through `@tailwindcss/vite`;
    - shadcn, with the components listed in the 5.1 contract;
    - dev dependencies: vitest, jsdom and Testing Library.
  - **Vite config**: `vite.config.ts` proxies `/api` to `127.0.0.1:8000` with `changeOrigin` false. The browser's Origin then equals the Host the api sees.
  - **frontend scripts**: `dev`; `typecheck` (`tsc -b`); `test` (`vitest run`); `build`.
  - **check-frontend.mjs**:
    - refuses, with "run npm ci --prefix frontend", when `frontend/node_modules` is missing;
    - runs typecheck, test and build, spawning with `shell` on win32 for `npm.cmd`;
    - then requires `frontend/dist/index.html` to exist.
  - **Root package.json**:
    - `dev:web` is `npm --prefix frontend run dev`;
    - `check:frontend` sits before `check:all` and is appended to its command.
  - **ci.yml**:
    - `npm ci --prefix frontend` runs after the backend install, with the setup-node cache keyed on `frontend/package-lock.json`;
    - `check:frontend` runs after `check:spend`.
- Acceptance check:
  - `npm run check:frontend` green;
  - `node <harness library>/scripts/check-wiring.mjs --project .` ok;
  - `npm ls --omit=dev --all --prefix frontend` lists no build tool: no vite, tailwindcss or lightningcss.
- Red first: before the scaffold, `check:frontend` exits 1, naming the missing install. The main session's `redproof` assigns a string to a `number` in `main.tsx`, and typecheck goes red.
- Skills to load: harness:authoring-a-check, frontend-design:frontend-design
- Predicted size: about 25 files, most of them generated, 60 minutes

### Task 5.2: API client, router, login screens and the shell

- Files owned:
  - `frontend/src/api.ts`, `frontend/src/api.test.ts`, `frontend/src/router.ts`, `frontend/src/App.tsx`;
  - `frontend/src/components/Shell.tsx`;
  - `frontend/src/screens/Login.tsx`, `Signup.tsx`, `Invite.tsx`, `Login.test.tsx`;
  - `frontend/src/screens/Documents.tsx`, `Ask.tsx`, `Settings.tsx`, as stubs.
- Depends on: 5.1, and the HTTP contract (not the backend routes)
- Change:
  - **api.ts**:
    - `fetch` with `credentials: "same-origin"`, JSON in and out;
    - `ApiError(status, detail, retryAfter)` on any non-2xx;
    - one function per route.
  - **router.ts**: `usePath`, `navigate` (`pushState` plus a `popstate` listener) and `Link`. The routes:
    - `/login`, `/signup` and `/invite`, which reads the token from `location.hash` and posts it in the body;
    - `/w/:id`, showing Documents and Ask;
    - `/w/:id/settings`, for owners;
    - `/` goes to the first workspace, or to `/login` on a 401.
  - **Shell**:
    - workspace switcher (a dropdown);
    - a create-workspace dialog;
    - a settings link for owners;
    - logout.

    Every control has a label and can be reached from the keyboard.
- Acceptance check: `npm --prefix frontend run typecheck` and `npm --prefix frontend test -- src/api.test.ts src/screens/Login.test.tsx` green:
  - `ApiError` carries the server's `detail` and `Retry-After`;
  - a JSON body sets the content type;
  - login shows the 401 detail and the 429 wait, and moves to the first workspace on success;
  - signup refuses an 11-character password before posting.
- Red first: import failure. The implementer's `redproof` makes `api.ts` resolve on a non-2xx, and the `ApiError` case goes red.
- Skills to load: frontend-design:frontend-design, superpowers:test-driven-development
- Predicted size: 12 files, about 450 lines, 100 minutes

### Task 5.3: Documents screen

- Files owned: `frontend/src/screens/Documents.tsx`, `frontend/src/screens/Documents.test.tsx`
- Depends on: 5.2
- Change:
  - **Inputs**: a file picker and a URL field, each labelled.
  - **List**: filename, kind, a status badge, chunk count, and the `error` of a failed document.
  - **Delete**: owners only, after a confirm.
  - **Polling**: `GET documents` every 2 s while any document is `pending` or `processing`, stopping when none is.
- Acceptance check: `npm --prefix frontend test -- src/screens/Documents.test.tsx` green, with fake timers and a mocked `fetch`:
  - a failed document shows its error;
  - delete appears only for an owner;
  - a URL submit posts `{url}`;
  - polling stops once every document has settled;
  - a 413 shows its detail.
- Red first: the stub renders no list. The implementer's `redproof` polls unconditionally, and the stop case goes red.
- Skills to load: frontend-design:frontend-design, superpowers:test-driven-development
- Predicted size: 2 files, about 230 lines, 60 minutes

### Task 5.4: Ask screen and citation panel

- Files owned: `frontend/src/screens/Ask.tsx`, `frontend/src/components/CitationPanel.tsx`, `frontend/src/screens/Ask.test.tsx`
- Depends on: 5.2
- Change:
  - **Question**: a labelled question box.
  - **Answer**: the text is split on `[n]`.
    - A marker with a matching citation becomes `<button aria-label="Source n">`.
    - A marker with no citation stays as text.
    - The refusal shows as plain text.
  - **CitationPanel** (a shadcn `Sheet`) shows:
    - the filename;
    - the heading path joined by ` > `, or `page n`;
    - the passage.

    Escape closes it, and focus returns to the marker.
- Acceptance check: `npm --prefix frontend test -- src/screens/Ask.test.tsx` green:
  - with citations numbered 2 and 4, `[4]` opens citation 4's filename and passage;
  - `[3]` is not a button;
  - the panel takes focus, and Escape returns it to the marker;
  - `found: false` renders the refusal with no buttons.

  `npm run check:frontend` also writes `frontend/dist/index.html` (spec row 20).
- Red first: import failure. The implementer's `redproof` looks citations up by position (`citations[n - 1]`), and the 2-and-4 case goes red.
- Skills to load: frontend-design:frontend-design, superpowers:test-driven-development
- Predicted size: 3 files, about 220 lines, 60 minutes

### Task 5.5: Settings screen

- Files owned: `frontend/src/screens/Settings.tsx`, `frontend/src/screens/Settings.test.tsx`
- Depends on: 5.2
- Change:
  - **Members**: a list, with remove.
  - **Invites**: create one and show `${window.location.origin}/invite#${token}` with a copy button; list the pending ones.
  - **API keys**:
    - create one with a name;
    - the key shows once, in an alert, until it is dismissed;
    - the list shows prefix, last use and revoked state;
    - revoke.
- Acceptance check: `npm --prefix frontend test -- src/screens/Settings.test.tsx` green:
  - the invite link uses `window.location.origin`;
  - a created key shows once, and is gone after dismiss and after a reload;
  - revoke sends `DELETE api-keys/{id}`;
  - a 409 on removing the last owner shows its detail.
- Red first: import failure. The implementer's `redproof` keeps the key in state after dismiss, and the shown-once case goes red.
- Skills to load: frontend-design:frontend-design, superpowers:test-driven-development
- Predicted size: 2 files, about 240 lines, 60 minutes

### Task 5.6: License rule, MPL-2.0 and the frontend tree

- Files owned: `backend/check_licenses.py`, `backend/tests/test_licenses.py`, `scripts/check-licenses.mjs`
- Depends on: 5.1
- Change:
  - **The rule** (decision 0007): `MPL` leaves `COPYLEFT`, and `MPL_ALLOWED` goes away.
  - **npm_packages(tree) -> list[(name, license)]**:
    - walks `dependencies` recursively, once per name and version;
    - reads `license` as a string, as a `{type}` object, or from the legacy `licenses` list;
    - a package with none gets "declares no license".
  - **`--npm-tree -`** reads that JSON from stdin as bytes (`json.load(sys.stdin.buffer)`) and applies `problems()` to it. A test pipes a tree with a non-ASCII description through a real subprocess.
  - **check-licenses.mjs**:
    - runs the backend check;
    - then runs `npm ls --omit=dev --all --json --long --prefix frontend` and pipes the output in;
    - a non-zero `npm ls` fails, naming `npm ci --prefix frontend`.
- Acceptance check: `uv --directory backend run python -m pytest tests/test_licenses.py` green, and `npm run check:licenses` green on both the backend and the frontend. The tests:
  - `lightningcss` under `MPL-2.0` and `tqdm` under `MPL-2.0 AND MIT` pass;
  - GPL, LGPL and AGPL fail;
  - a fixture tree with a nested duplicate, an object license and a missing license gives the right list and exactly one problem;
  - `test_mpl_is_allowed_for_certifi_only` becomes `test_mpl_is_allowed_unmodified`, since decision 0007 changes what it expects.
- Red first: the new MPL case fails on the old rule. The implementer's `redproof` puts `MPL` back into `COPYLEFT`, and that case goes red.
- Skills to load: harness:authoring-a-check, superpowers:test-driven-development
- Predicted size: 3 files, about 140 lines, 40 minutes

### Task 6.1: Image, compose and check:compose (main session)

- Files owned: `Dockerfile`, `.dockerignore`, `docker-compose.yml`, `scripts/check-compose.mjs`, `scripts/compose-check.yml`, `scripts/compose-check.env`, `package.json`, `.github/workflows/ci.yml`
- Depends on: 3.3, 4.1 to 4.4, 5.1
- Change:
  - **Dockerfile**:
    - **Node stage** (`node:22-slim`): `npm ci` and `npm run build` in `frontend`.
    - **Python stage** (`python:3.14-slim`):
      - copies `uv`, pinned to 0.11.3, and runs `uv sync --locked --no-dev` from `backend/uv.lock` with `UV_PYTHON_DOWNLOADS=never`;
      - copies `backend/` and `frontend/dist`;
      - sets `TIKTOKEN_CACHE_DIR` and fetches `cl100k_base` at build time;
      - runs as a non-root user;
      - `CMD` runs uvicorn on `0.0.0.0:8000` with `--proxy-headers`. There is no `--limit-concurrency`; see "No connection cap in v1".
  - **.dockerignore**: `.env`, `.env.*`, `.git`, `.claude/`, `.codex/`, `**/node_modules`, `backend/.venv`, `**/__pycache__`, `eval/corpus`, `frontend/dist`.
  - **docker-compose.yml**:
    - `migrate`: `python -m alembic upgrade head`.
    - `api`: starts after `migrate` completes; publishes `127.0.0.1:8000:8000`; a Python healthcheck that sends `Host` from `ALLOWED_HOSTS`; `restart: unless-stopped`.
    - `worker`: starts after `migrate`; runs `python -m loreos.worker`; `restart: unless-stopped`.
    - All three use one image, with `env_file: [{path: .env, required: false}]`.
    - `testdb` stays as it is, under profile `test`.
  - **check-compose.mjs**, with the override file and the empty env file, under project `loreos-check`:
    0. `config --format json`, and stop unless every service's `DATABASE_URL`, `OPENAI_API_KEY` and `OPENAI_BASE_URL` are the check's own values.
    1. `up --build --wait`.
    2. `/api/health` returns 200.
    3. `/` and `/login` contain `<div id="root">`.
    4. `.dockerignore` lists `.env`.
    5. No `.env*` exists under `/app` in the image, checked with `run --rm --no-deps --entrypoint python api -c ...`.
    6. `worker` is running.
    7. It prints the image size.
    8. `down` always runs, from a `finally`.
  - **package.json**: `check:compose` sits before `check:all` and stays out of its command.
  - **ci.yml**: a `compose` job after `checks` (checkout, Node, `npm run check:compose`), with a `timeout-minutes` that covers the build.
- Acceptance check:
  - `npm run check:compose` green;
  - check-wiring ok;
  - `npm run check:spend` still green;
  - `docker image ls loreos:local` and `docker system df` recorded in STATUS.
- Red first: before the Dockerfile exists, the build fails and the check exits 1. The main session's `redproof` (`--timeout 900`) makes the UI fallback return 404 instead of `index.html`, and the `/login` assertion goes red.
- Skills to load: harness:authoring-a-check
- Predicted size: 8 files, about 230 lines, 90 minutes

### Task 6.2: Docs (main session)

- Files owned: `docs/KNOWN-GAPS.md`, `docs/decisions/0002-parsing-and-driver-libraries.md`, `docs/sdd/p4-platform-shell/STATUS.md`
- Depends on: 6.1
- Change:
  - **KNOWN-GAPS loses** two closed rows: the frontend-checks row (closed by 5.1) and the chunked-upload row (closed by 4.1 and 4.4).
  - **KNOWN-GAPS gains**:
    - a row for expired sessions, used invites and old `rate_limits` windows, none of which is ever pruned;
    - a row for the shared login IP bucket. Behind compose without `FORWARDED_ALLOW_IPS`, every client shares the Docker gateway's address, so 20 failed logins from anyone lock out every login for 15 minutes. The fix is setting `FORWARDED_ALLOW_IPS` to the proxy's own address behind a proxy. Never `*`, which lets a spoofed `X-Forwarded-For` rotate the IP bucket;
    - a row for the missing connection cap. A burst of concurrent requests beyond Supavisor's client limit gets 500s. The trigger is users reporting 500s under load, or a deployment expecting more concurrent users than that limit. The row records the pool size that phase 7 reads;
    - in the spend-guard row, the worker and compose spellings the guard does not catch: `docker run` of the image through a shell, and a compose command held in a variable.
  - **Decision 0002's** license paragraph points at 0007.
  - **STATUS** records the windows, the ledgers and the image size.
- Acceptance check: `npm run check:all` green.
- Red first: none (docs only).
- Skills to load: none
- Predicted size: 3 files, 30 minutes

## How P3's shared files are handled

The spec's Risks name these shared files. Whichever of P3 and P4 merges second resolves them, in the main session:

- **Migration heads.**
  - P4's revision is `0002_platform`, on top of `0001`. The second branch to merge points its `down_revision` at the other's head. That is a protected-path edit.
  - `test_schema.py`'s one-head case stays red until that is done.
  - The two migrations touch different objects: P3 adds `chunks.tsv` and its index; P4 adds tables, `documents` columns, the role and RLS.
  - `loreos_app`'s table-level grants already cover P3's new column.
- **`settings.py`, `.env.example` and `test_config.py`.**
  - P3 adds `RERANK`. P4 adds `ALLOWED_HOSTS` and `startup_problems()`. The second merger keeps both by hand, and `test_config.py`'s exact set gains both keys.
  - `p2-baseline` changes the same files (`DEFAULT_JUDGE_MODEL` and its example line). P4 merges `main` after it lands, at a window boundary, never in the middle of a window.
- **`conftest.py`.**
  - P4 replaces the connection (the owner role and a database per checkout), extends `clean` and adds fixtures. P3's fixtures merge in beside them.
  - P3's tests that call P1's `/api/ask` move to `f"{W}/ask"`, using `key_client` or `owner`.
- **`pyproject.toml` and `uv.lock`.**
  - `pyproject.toml` is merged by hand.
  - `uv.lock` is regenerated with `uv --directory backend lock` and never merged as text. Then `uv sync --locked` and `npm run check:licenses`. fastembed's tqdm is allowed by decision 0007.
- **The ask response.**
  - P4 removes P1's `/api/ask`, so P3's edit to it is dropped at merge.
  - `routes/documents.py` returns every `Answer` field through `asdict`, so `retrieval_mode` comes through; 4.4's every-field test covers it.
  - The exact refusal dict in `test_ask_api.py` gains `retrieval_mode`.
- **The reranker.**
  - P3 behaviour 7 loads the model at startup, in the api only. At merge, that load goes into `main.py`'s lifespan.
  - `worker.py` never imports `rerank`. The worker imports `ingest`, which imports `retrieval`, so the merge must confirm that importing `loreos.retrieval` does not load the model. The merger adds a test that `import loreos.worker` leaves `loreos.rerank` out of `sys.modules`. P3's spec says the api **and the worker** load the model, so this is a requirement change for P3: P4's STATUS records it for P3's spec revision.
  - The Dockerfile's model bake line, and its cache directory, are added by whichever of P3 and P4 merges second. `check:compose` then measures the image again against free disk.
- **The caller scan.** A new `engine()` or `system_session()` call in P3's files fails `test_isolation.py`'s source scan; the scan watches all of `backend/loreos/`, including `evaluation/`. The merger adds the file to `SYSTEM_SESSION_FILES` only when it is a cross-workspace read the spec lists.

## Merge timing against P3's paid runs

- **What P4 changes for P3's evaluation.**
  - It re-keys the evaluation workspace, through edits to `ingest.py`, `parsing.py` and `llm.embed`.
  - It changes search latency, through the role-switch round trip and the policy check.

  So P3 takes P4 from `main` either before its first chunk-size run or after its `--mode all` run, never between them.
- **The Supabase migration belongs to the same moment.**
  - Once Supabase is at `0002_platform`, P3's preflight on a branch without P4 stops ("the database is at migration ... and the code at ...").
  - P3's own migration cannot apply until P3 rebases onto P4's.
  - So phase 7 runs only in that window.
- **Order:**
  1. claim-green on P4's pushed tip;
  2. the operator picks the window from P3's STATUS;
  3. merge `main` into P4 if P3 or `p2-baseline` has landed, resolve as the previous section says, and run `check:all` and `check:compose`;
  4. phase 7;
  5. merge the PR, and P3 merges `main` straight away.
- **Cost of the re-key.** The first evaluation after the merge re-embeds the corpus into a new `eval-*` workspace: about 0.25M tokens, under one cent.

## What this plan does NOT cover

| Item | Trigger that brings it back |
|---|---|
| Publishable keys, allowed domains, the widget and per-key rate limits | P6, which reuses `rate_limit` |
| Pruning sessions, used invites and old `rate_limits` windows (KNOWN-GAPS rows) | P6's per-request limits, or any of those tables passing about 100k rows |
| Changing a member's role, revoking a pending invite, deleting a workspace or an account | An operator asks for it |
| Email sending, password reset by email, OAuth, SSO, passkeys | Decision 0006's "Reopen only if" conditions |
| A connection pool (the spec's "Not changing") | Supavisor's limit, or connection setup time, showing up in latency |
| A worker that handles more than one document at a time, and an index for its claim | Queue waits of minutes, or `documents` passing about 50k rows |
| HTTPS, a reverse proxy, and guidance on `FORWARDED_ALLOW_IPS` | P5's README, or a deployment beyond 127.0.0.1 |
| Publishing the image, and multi-arch builds | P5's demo |
| The reranker model in the image | Whichever of P3 and P4 merges second |
| OCR, DOCX images and footnotes, JavaScript-rendered pages | A user document that needs them |
| Crawler, caching, Redis, roles beyond owner and member | The brief keeps them out of v1 |

## Planning review findings and their resolution

The first review is [reviews/plan.md](reviews/plan.md), on `a05f789`.

| # | Severity | Finding | Resolution |
|---|---|---|---|
| 1 | major | Peek-then-count lets a burst of login guesses through; raw-email buckets; a shared gateway IP | "Login rate limit": reserve first, refund on success, normalised email; 4.2 adds a concurrent-login test with a `verify` spy and a mutation; 6.2 adds the gateway KNOWN-GAPS row |
| 2 | major | The `MAX_CONNECTIONS` semaphore deadlocks on nested sessions | Semaphore dropped. The uvicorn cap that first replaced it failed re-review (F1), so v1 has no cap, with a KNOWN-GAPS row (6.2) |
| 3 | major | 1.2's mutation cannot go red on a persisted test database | The bootstrap drops and recreates the test database each session, under a sanitised, quoted name of at most 63 bytes |
| 4 | major | 4.4's every-field test cannot fail while `Answer` has four fields | The test returns a dataclass with an extra `retrieval_mode` |
| 5 | major | `verify_rls` has one negative case | 1.3 adds a negative per assertion, each in a rolled-back transaction, including the SET option |
| 6 | major | Possible cross-workspace changes in the `system_session` routes, untested; the invite hash unchecked | 4.3: `and workspace_id = :w` on every statement, cross-workspace delete tests, a mutation, and an invite-hash assertion |
| 7 | minor | The no-off-switch pin is narrow | 4.5 adds a source scan of environment reads, with an allowlist and reasons, and a mutation |
| 8 | minor | 1.4's red-first count is wrong; missing compose cases; `db:migrate`; disk | Count corrected; `watch` and `--profile test up -d` cases added. `db:migrate` stays unguarded but is asked in chat in phase 7. Disk quirk set to 20 GB |
| 9 | minor | Concurrent `create role` raises `unique_violation` | Both errors caught, in the migration and in the bootstrap |
| 10 | minor | Worker writes have no fence; behaviour 3 is unchecked in processing | Fenced on `locked_until`, with a test and a mutation; the processing probe asserts `current_user` and `app.workspace_id` |
| 11 | minor | The last-owner race | The owner rows are locked before counting, with a concurrent test |
| 12 | minor | Invite tokens in URL paths reach the access log | `POST /api/invites/accept {token}`; the UI link is `/invite#<token>` |
| 13 | minor | `check:compose` never proves its env isolation | Step 0 asserts the resolved config before anything starts |
| 14 | minor | ANSI-decoded stdin on Windows | `json.load(sys.stdin.buffer)`, tested through a subprocess |
| 15 | minor | P3 loads the reranker in the worker too | A requirement change for P3, recorded in STATUS; at merge, a test that `import loreos.worker` leaves `rerank` out |
| 16 | minor | Phase 7 names no checkout; a `.env` could change the tests | Phase 7 runs in the P4 worktree with `.env` copied in; conftest pins every key |
| 17 | nit | The `\|` in the phase 4 `rg` pattern | The check moved out of the table, with two `-e` patterns |
| 18 | nit | An unrouted POST gets 405, not 404 | The red-first wording in 4.2, 4.3 and 4.4 |
| 19 | nit | `system_session` callers beyond the spec's list | The spec's interface row now lists the workspace, member, invite and key routes |
| - | not probed | A commit inside a session would drop the role switch | 1.3's source scan for transaction ends (see re-review F8) |

The re-review is on `5ebbbac`, in the same review file.

| # | Severity | Finding | Resolution |
|---|---|---|---|
| F1 | major | uvicorn's `--limit-concurrency` counts idle keep-alive sockets: 503s for two browser tabs, outside the `{detail}` contract | No cap in v1 ("No connection cap in v1"), with a KNOWN-GAPS row. Delete and URL re-queue use `lock_timeout` 2 s and answer 409 (3.1, 4.4) |
| F2 | major | The refund test's arithmetic was wrong | 4.2: after 4 failures and a refunded success, the next failure gets 401 and the one after 429; without the refund, the next attempt gets 429 |
| F3 | major | `verify_rls` negatives: the `public` revoke cannot fire; no superuser or DML negative; the wrong database | Run as `postgres` against `TEST_DATABASE`, asserting exactly `[expected]`; revoke from PUBLIC too; add the superuser and DML cases, and a pin of one case per message |
| F4 | major | Invite accept enforces no password rule | 422 on signup and accept, each tested; a redproof on accept |
| F5 | minor | Recreating the test database: FORCE kills other runs; the deny list; autocommit; role drift; leftover databases | No FORCE, stopping with the database's name instead; the admin URL hard-coded with a prefix assertion; autocommit; role attributes reset at bootstrap; tmpfs clears leftovers |
| F6 | minor | A refund can hit the next window | `rate_limit` returns `window_start` and `refund` takes it; a boundary test |
| F7 | minor | The concurrent-login test may not test the race | Requests truly concurrent via `asyncio.gather` over an ASGI transport, with a gated `verify` spy; the mutation is peek-then-count |
| F8 | minor | The source scans miss `rollback`, SQL `commit` or `reset role`, `from os import environ`, and new keys in allowlisted files | The transaction scan covers them; the environment scan matches `\benviron\b` and keys its allowlist on file and key |
| F9 | minor | The `rg` check is vacuous in Git Bash | Patterns without a leading `/` |
| F10 | nit | STATUS, the session count, the mutation count, `FORWARDED_ALLOW_IPS` | Reworded: STATUS, 3.3 (three mutations), the KNOWN-GAPS row (the proxy's address, never `*`) |
