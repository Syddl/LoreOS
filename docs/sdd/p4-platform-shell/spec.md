# Spec: P4 platform shell

Phase P4 of [the v1 brief](../v1/brief.md). Drafted before P1 started, then re-read against what P1 and P2 built and revised (2026-10-11). The section "Revised against P1 and P2" lists every change from the draft and its reason.
Sizing: an auth and data-isolation surface, so every lifecycle step runs and the whole-branch review is by an independent reviewer.

## Summary

P4 turns the local slice into something a team can self-host. It adds:
- workspaces isolated by Postgres row-level security;
- accounts with email and password login ([decision 0006](../../decisions/0006-login-email-and-password.md));
- API keys;
- a worker that ingests with retries;
- DOCX and single-URL import;
- the web UI;
- a `docker compose up` that starts the api and the worker.

Kill switch: none. Running without isolation or login would be wrong in every deployment; a check pins that no environment key turns either off.

## Interfaces

Every new table lives in the `loreos` schema, beside P1's (decision 0002).

| Interface | Kind | Owner file | Contract |
|---|---|---|---|
| `loreos.users` | table | migration | `id, email unique (stored lowercased), password_hash (argon2id), created_at` |
| `loreos.memberships` | table | migration | `(user_id, workspace_id) pk, role check (role in ('owner','member'))` |
| `loreos.sessions` | table | migration | `id` (sha256 of the cookie token), `user_id, created_at, expires_at` |
| `loreos.invites` | table | migration | `token_hash, workspace_id, created_by, expires_at, used_at` |
| `loreos.api_keys` | table | migration | `id, workspace_id, kind ('secret'; P6 adds 'publishable'), name, prefix, key_hash, created_at, last_used_at, revoked_at` |
| `loreos.rate_limits` | table | migration | `(bucket, window_start) pk, count`; fixed windows |
| `loreos.documents` changes | migration | | `kind` check adds `docx` and `url`; `content` becomes nullable (a URL document has none until fetched); new `source_url`, `next_attempt_at`, `locked_until` |
| `loreos_app` | Postgres role | migration | `NOLOGIN`, no `BYPASSRLS`, owns nothing. `USAGE` on schema `loreos` and on the schema holding `vector`; `SELECT, INSERT, UPDATE, DELETE` on `documents` and `chunks` only. Created only if absent (roles are cluster-wide); `grant loreos_app to current_user with set true`. |
| RLS policies | migration | | On `documents` and `chunks`: rows visible and writable only when `workspace_id = nullif(current_setting('app.workspace_id', true), '')::uuid`. Auth tables get no policy; `loreos_app` has no rights on them. |
| `workspace_session(workspace_id)` | async context manager | `backend/loreos/db.py` | Also runs `select set_config('role','loreos_app',true), set_config('app.workspace_id',:w,true)` in one round trip. Callers unchanged. |
| `system_session()` | async context manager | `backend/loreos/db.py` | One transaction as the connecting role, with no role switch. The only callers: login, session and key lookup, signup's first-user check, invite accept, the workspace, member, invite and key routes, `rate_limit`, the worker's claim and failure records, `admin.py`, `verify_rls`, the health check, and the workspace lookup and creation P2 already does through `engine()`. A source scan pins this list. These routes have no RLS behind them, so every statement carries `workspace_id = :w`. |
| `ingest.enqueue(session, workspace_id, filename, data)` and `ingest.enqueue_url(session, workspace_id, url)` | functions | `backend/loreos/ingest.py` | Store a `pending` document and return it. A URL document's `sha256` is the hash of the normalised URL, so the same URL is queued again. `ingest.ingest()` stays inline for the evaluation and `paid:smoke`. |
| `rate_limit(bucket, limit, window_s) -> Slot(allowed, retry_after, window_start)` and `refund(bucket, window_start)` | functions | `backend/loreos/ratelimit.py` | One upsert per call; `refund` returns a slot to the window it was counted in. P6 reuses both. |
| `current_member(request, workspace_id)` | FastAPI dependency | `backend/loreos/auth.py` | Session cookie or `Authorization: Bearer lo_sk_...`; returns user or key, workspace and role; 401 or 404. |
| Auth routes | routes | `backend/loreos/routes/auth.py` | `POST /api/auth/signup`, `POST /api/auth/login`, `POST /api/auth/logout`, `GET /api/me`, `POST /api/invites/accept` (the token in the body, never in a URL path) |
| Workspace routes | routes | `backend/loreos/routes/workspaces.py` | `GET, POST /api/workspaces`; under `/api/workspaces/{id}`: `members`, `invites`, `api-keys` (owner only) |
| Document and ask routes | routes | `backend/loreos/routes/documents.py` | Under `/api/workspaces/{id}`: `POST documents` (file or `{url}`), `GET documents`, `GET documents/{doc}`, `DELETE documents/{doc}` (owner), `POST ask`. They replace P1's unscoped routes. `ask` returns every `Answer` field through one mapping (`text` as `answer`), so P3's `retrieval_mode` passes through. |
| `GET /api/health` | route | `backend/loreos/main.py` | 200 when the database answers; the compose healthcheck. |
| Worker | process | `backend/loreos/worker.py` | `python -m loreos.worker`, run as `npm run paid:worker`. It claims, processes and retries documents. |
| DOCX and HTML parsers | modules | `backend/loreos/parse_docx.py`, `backend/loreos/parse_html.py` | New modules. `parsing.py` gains only the dispatch to them, because its source text keys the evaluation workspace. |
| URL fetch | module | `backend/loreos/fetch_url.py` | `httpx2` (declared directly; no `httpx`) with a custom `httpcore2` network backend that connects to the checked address, with TLS SNI on the host name. |
| Admin CLI | process | `backend/loreos/admin.py` | `python -m loreos.admin reset-password <email>` prompts for a new password and ends that user's sessions. |
| `npm run db:verify-rls` | root script | `package.json` | `python -m loreos.verify_rls`, not a `scripts/check-*.mjs` file, since CI has no `DATABASE_URL`. Read-only assertions against `DATABASE_URL`. Free. |
| `ALLOWED_HOSTS` | env | `backend/loreos/settings.py`, `.env.example` | Comma-separated hosts the api answers; default `localhost,127.0.0.1`. Replaces P1's `LOCAL_HOSTS`. |
| Image | files | `Dockerfile`, `.dockerignore` | Node stage builds `frontend/dist`. Python stage (`python:3.14-slim`) installs from `uv.lock`, copies `dist`, bakes the tiktoken encoding (`TIKTOKEN_CACHE_DIR`) and runs as a non-root user. `.dockerignore` excludes `.env`, `.claude/`, `backend/.venv`, `node_modules` and `eval/corpus`. |
| Compose | file | `docker-compose.yml` | `migrate` (one-shot `alembic upgrade head`), `api` (after `migrate`, `127.0.0.1:8000:8000`, a Python healthcheck), `worker` (after `migrate`); `env_file: .env` with `required: false`. P1's `testdb` stays under profile `test`. |
| UI | app | `frontend/` | React, Vite, strict TypeScript, Tailwind, shadcn. Built to `frontend/dist` and served by FastAPI at `/`, falling back to `index.html` for non-`/api` paths. Own `package.json` and lockfile. |
| Root scripts | package.json | `package.json` | `dev:web`, `paid:worker`, `check:frontend`, `check:compose`, `db:verify-rls` |
| Spend guard | config | `.claude/harness.json`, `scripts/check-spend.mjs` | `worker` joins the interpreter spend pattern; `docker compose ... up` asks unless it names only `testdb`. Operator decision, 2026-10-11. |

## Behaviour

Isolation
1. Every read and write of documents and chunks runs inside `workspace_session`, as `loreos_app`, with `app.workspace_id` set. With the setting missing, every policy matches no row: isolation fails closed.
2. The connecting role (`postgres` on Supabase) owns the tables and may carry `BYPASSRLS`, so policies alone would not bind it; the role switch is what makes RLS apply. Application filters on `workspace_id` stay as a second layer.
3. Reads across workspaces go through `system_session()` and only from its listed callers. Auth tables are reached only there. The worker's claim writes status, lease and next attempt on the claimed row, then processes it inside that document's `workspace_session`.

Accounts and login
4. Signup is open only while no user exists. The first account becomes owner of a new workspace and of P1's default workspace. Evaluation workspaces (`eval-*`) stay ownerless and are never listed. Two concurrent first signups are serialised with `pg_advisory_xact_lock`.
5. An owner creates an invite link: single use, expires after 7 days, stored as a hash. The client builds the link from `window.location.origin` as `/invite#<token>`. The fragment never reaches the server or its access log. Accepting it while logged out creates the account; logged in, it adds the membership.
6. Passwords are hashed with argon2id (`argon2-cffi`) and must be at least 12 characters. Unknown email and wrong password get the same error and take comparable time.
7. Login sets an `HttpOnly`, `SameSite=Lax` session cookie holding 32 random bytes. It is `Secure` when the request arrived over HTTPS, as uvicorn reports it from `--proxy-headers` and `FORWARDED_ALLOW_IPS`. The database keeps only its hash; it expires after 14 days; logout deletes it.
8. Login is limited to 5 failures per email and 20 per client IP per 15 minutes; past that it gets 429 with `Retry-After`. Login reserves a slot in both buckets before verifying, so parallel guesses cannot all pass, and refunds them on success, so only failures stay counted. The email bucket keys on the normalised email.
9. The api answers only the hosts in `ALLOWED_HOSTS`. Every `POST`, `PUT`, `PATCH` or `DELETE` without an `Authorization: Bearer` key must carry an `Origin` whose host and port equal the request's `Host`, or it gets 403. That covers cookie-authenticated writes, plus login, signup and invite acceptance, which also closes login CSRF. A missing `Origin` is refused too; P1's rule passed it. A Bearer request is authenticated by its key alone and never falls back to the cookie.
10. Roles: a member uploads, lists and asks; an owner also deletes documents and manages members, invites and API keys.

API keys
11. An owner creates a secret key (`lo_sk_` and 32 random bytes, base64url) shown once. The database keeps its sha256 and, for display, the first 8 characters of the random part. A revoked key gets 401.
12. A key reaches only its own workspace's document and ask routes. A key used on another workspace's path gets 404, and a key on member or key routes gets 403.

Worker and ingestion
13. An upload stores the document as `pending` and returns 202. A duplicate returns the stored document, as in P1. A failed duplicate is queued again with 202 and `attempts` reset to 0. Uploads are limited to 20 MB: bytes are counted as they arrive, so a chunked upload stops at the limit too.
14. The worker polls every 2 s while idle. It claims the oldest due `pending` document, or a `processing` one whose lease ran out, with `FOR UPDATE SKIP LOCKED`, then sets `processing` and a 10-minute lease. The lease only recovers a crashed worker: the processing transaction holds the row lock, so no lease extension is needed. A lease that ran out counts as a transient failure, so a document that keeps killing the worker ends `failed`.
15. Failures are classified before handling, by exception class, status and error code, never by message:
    - **Permanent** (unsupported type, parse error, no text, URL refused, HTTP 4xx from the fetched site, a DOCX over the unpacked-size cap) fails at once.
    - **Transient** (OpenAI rate limit, 5xx or timeout, network error, HTTP 5xx, lost database connection, an expired lease) returns to `pending` after 30 s, then 2 min; the third failure is final.
    - **Systemic** (OpenAI 401 or 403, `insufficient_quota`, an unknown model, an embedding dimension mismatch) leaves the document `pending` with its attempt uncounted, and the worker backs off for 5 minutes and logs the class.

    `attempts` is counted once, when a failure is recorded. `error` always holds the latest stage, class and message, and the UI shows it.
16. Processing replaces the document's chunks in one transaction, so a retry after a crash never duplicates chunks.
17. DOCX uses python-docx. Paragraphs styled `Title` or `Heading 1` to `Heading 9` start sections and build the heading path, and tables become text rows in document order. The worker sums the zip members' unpacked sizes first and fails the document permanently over 100 MB.
18. URL import fetches one page in the worker; there is no crawl.
    - Only `http` and `https` are allowed. A URL carrying a user name or password is refused.
    - Every address the host resolves to must be public: `ipaddress.ip_address(a).is_global`, after unwrapping IPv4-mapped IPv6.
    - The connection goes to the address that passed the check. `trust_env` is off, so a proxy setting cannot route around it.
    - Redirects are followed by hand, at most 5, each checked again.
    - Limits: 10 s, and 5 MB of decoded bytes.
    - HTML becomes sections by `h1` to `h6`, with script, style, nav, header, footer and aside removed. A `text/plain` page is read as TXT and a PDF as PDF. Any other content type fails with its name.
    - The document's filename is the URL, which is what citations show. Submitting the same URL again fetches it again.

Shell
19. `docker compose up` with `DATABASE_URL` and `OPENAI_API_KEY` in `.env` runs migrations, then starts the api and the worker; the UI loads at `http://localhost:8000`. The api and the worker read both keys at startup and exit with a message naming any that is missing.
20. UI screens:
    - signup and login, and invite acceptance;
    - the workspace switcher and workspace creation;
    - documents: upload a file or a URL, its status, the error of a failed document, and delete for owners;
    - ask: the answer, with `[n]` markers as buttons. A marker opens a side panel with the passage, the filename, and the heading path or page.
    - settings: members, invites, API keys shown once, and revoke.

    Controls have labels and work from the keyboard. The side panel takes focus and returns it when it closes.
21. `check:licenses` also covers the frontend's production dependencies (`npm ls --omit=dev --all --json --prefix frontend`). MPL-2.0 is allowed for unmodified dependencies ([decision 0007](../../decisions/0007-mpl-2-0-dependencies-unmodified.md)); AGPL, GPL and LGPL stay refused.

## Acceptance checks

| # | Behaviour | Check | Expected | Does NOT exercise |
|---|---|---|---|---|
| 1-3 | Isolation (the brief's test) | `npm run check:backend`, `tests/test_isolation.py`, connected as a non-superuser owner role that testdb's init creates | Two workspaces with chunks. With A's key, list and ask return only A's ids. In A's session, `select count(*) from loreos.chunks` with no filter equals A's count; with no workspace set it is 0. `loreos_app` has `rolbypassrls = false`, owns no table and has no rights on the auth tables. | Supabase's own role attributes (next row) |
| 1-3 | Isolation on Supabase | `npm run db:verify-rls` | The same role and policy assertions pass against `DATABASE_URL`. `pg_has_role(current_user,'loreos_app','SET')` is true, `loreos_app` has `USAGE` on `vector`'s schema, and `idle_in_transaction_session_timeout` is printed. Ledger row by hand. | |
| 1 | Grants before spend | `tests/test_smoke.py` | `smoke.preflight()` stops, before any paid call, when `loreos_app` lacks `USAGE` on `vector`'s schema | |
| 4-9 | Login | `tests/test_auth.py` | The second signup is refused. An invite is single use and expires. The cookie flags are set. The 6th failure gets 429. A foreign or missing `Origin` gets 403, and a host outside `ALLOWED_HOSTS` gets 400. | Browser cookie handling (manual row) |
| pin | No off switch | `tests/test_auth.py` | No environment key makes an unauthenticated request succeed on any workspace route | |
| 10-12 | Roles and keys | `tests/test_keys.py` | Member gets 403 on key routes; revoked key 401; key on another workspace 404 | |
| 13 | Upload limit | `tests/test_documents_api.py` (P1's assertions moved to the scoped routes) | 413 at 20 MB, with and without `Content-Length`, before parsing | |
| 14-16 | Worker | `tests/test_worker.py` with fakes | A transient error is retried twice, then the document is `failed` with the error. A permanent error fails at once. A systemic error leaves the document `pending`, uncounted. Two workers never claim the same row. An expired lease counts once. A run killed midway leaves no duplicate chunks. | Real OpenAI outages |
| 17 | DOCX | `tests/test_parse_docx.py` | The heading path comes from the styles, table text is present, and a zip over the cap is refused before parsing | |
| 18 | URL guard | `tests/test_fetch_url.py` with a local server and a stub resolver | Loopback, private and metadata addresses are refused, including after a redirect, when the name resolves to both a public and a private address, and as IPv4-mapped IPv6. Userinfo is refused. The size limit (decoded) and the time limit are hit. | DNS answers that change between our check and the connection (pinned by design, reviewed) |
| 19 | Compose | `npm run check:compose`, in CI and on its own, not in `check:all`. It builds the image with explicit `environment:` overrides (its own database, a fake key, an unroutable `OPENAI_BASE_URL`) and never reads `.env` | `/api/health` 200; `/` and `/login` return the app HTML; the image holds no `.env` | A real OpenAI call |
| 20 | UI | `npm run check:frontend` (typecheck, vitest, build) | Marker buttons map to citations; the build writes `frontend/dist/index.html` | Visual layout (manual row with a screenshot) |
| 21 | Licenses | `npm run check:licenses` | It passes on the backend's installed environment and on the frontend's production dependencies. An MPL-2.0 package passes; a GPL fixture fails. | |
| pin | Spend guard | `npm run check:spend` | `npm run paid:worker`, `python -m loreos.worker` and `docker compose up` ask; `docker compose --profile test up -d testdb` does not | |

## Kill switch

None. The `test_auth.py` row pins that no environment read disables auth or isolation. `HARNESS_HOOKS=off` is unrelated: it silences the agent guard, not the product.

## Not changing

- Retrieval, fusion, rerank and evaluation files: P3 owns them in this window.
- Publishable keys, allowed domains and the widget: P6. `rate_limit` is built here for login and reused there.
- Roles beyond owner and member; email sending; password reset by email; OAuth or SSO; the crawler; caching; Redis.
- The connection pool and a connection cap: `db.engine()` keeps NullPool, with its connect retry (`p2-baseline`, `5f3e7a8`). v1 sets no connection cap. A burst beyond the pooler's client limit gets 500s, recorded as a KNOWN-GAPS row with its trigger. Both caps tried in plan review failed, and a correct one is more code than a learning build's traffic justifies.

## Revised against P1 and P2

| Draft said | Now | Why |
|---|---|---|
| Tables with no schema | Every table in `loreos`; `loreos_app` gets `USAGE` on `loreos` and on `vector`'s schema | P1 put everything in `loreos` (decision 0002). On Supabase `vector` lives in `extensions`, and the vector cast fails without `USAGE` after the embedding is paid for. testdb's `vector` sits in `public`, so only `db:verify-rls` and the smoke preflight can see the gap. |
| "Claiming a worker job is the one query that runs without a workspace context" | `system_session()` with a named list of callers | Login, session and key lookup, the workspace list, invites, signup, `rate_limit` and P2's workspace lookup all read across workspaces. |
| RLS "on every table with a `workspace_id`" | RLS on `documents` and `chunks`; auth tables only through `system_session()` | Policies on `memberships`, `invites` and `api_keys` would hide the rows that login and key lookup must find. Isolation of workspace data is what the brief tests. |
| `SET LOCAL ROLE` then set the workspace | One `select set_config(...)` for both | One round trip per session, as PostgREST does. |
| Upload returns 202 and the worker ingests | The route enqueues; `ingest.ingest()` stays inline | `paid:eval` and `paid:smoke` call `ingest()` and require `processed` on return. P3 owns the evaluation in this window. |
| The claim sets `attempts + 1` | `attempts` is counted once, when a failure is recorded; a re-queued failed duplicate resets it | P1's `process()` already increments it, so the claim would double-count. A SIGTERM during a large document would otherwise burn attempts. |
| `kind` adds `url`, dedup by content hash | URL documents hash the normalised URL, have nullable `content`, and the parser follows the fetched content type | A queued URL has no bytes yet, `content` was `not null`, and "submit again re-fetches" conflicts with content dedup. |
| The worker extends the lease between batches | No extension; the lease is for crash recovery, and an expired lease counts as a failure | The processing transaction holds the row lock, so `SKIP LOCKED` already skips it, and an extension from another connection would block on that lock. |
| Transient includes "OpenAI rate limit" | A third class, systemic: 401, 403, `insufficient_quota`, unknown model, dimension mismatch | `RateLimitError` also carries `insufficient_quota`, which no retry fixes; a bad key would fail every queued document. |
| `Origin` equal to "the app's own origin" | P1's Host-derived rule, `ALLOWED_HOSTS`, Origin required on cookie-authenticated writes | P1's `TrustedHostMiddleware` allows only localhost, so behind a domain the api would return 400. The Host-derived rule needs no `PUBLIC_URL`. |
| Upload size not stated | 20 MB, counted as bytes arrive | Closes the KNOWN-GAPS row on chunked uploads, whose trigger is "P4 serves the API beyond 127.0.0.1". |
| "Replace P1's unscoped routes" | Their tests' assertions move to the scoped routes | AGENTS: preserve existing tests. |
| Image bakes the reranker model | Tiktoken only; whichever of P3 and P4 merges second adds the model line | P4's branch has no fastembed, and P3 decides the model. |
| `env_file: .env`; `check:compose` with a fake key | `required: false`; `check:compose` passes its own `environment:`, its own database and an unroutable `OPENAI_BASE_URL`, outside `check:all` | CI has no `.env` and its testdb service already holds port 54329. A real `.env` must never reach a test or the image, so `.dockerignore` is new. |
| "Passes on both lockfiles" | The backend's installed environment, plus `npm ls --omit=dev` for the frontend | `check_licenses.py` reads installed distributions, not `uv.lock`. Vite 8 and Tailwind 4 need lightningcss (MPL-2.0), allowed unmodified by decision 0007. |
| "A custom httpx transport" | `httpx2` and `httpcore2`, declared directly | The lock already has them through `openai`, and decision 0002 names them. Adding `httpx` would duplicate the stack. |
| API and worker pools of about 5 and 2 | NullPool with capped concurrency | conftest's `sql()` runs one event loop per statement, so pooled asyncpg connections would bind to dead loops. Supavisor already pools on the server side. |
| Signup adopts "every workspace with no owner" | Only P1's default workspace | P2 creates ownerless `eval-*` workspaces, and P3 adds more. |
| "A missing key stops the service" | Both keys are read at startup | Settings are read when used, so the api would start and fail at the first upload. |
| "8-character prefix" | 8 characters of the random part | `lo_sk_` plus 2 characters identifies nothing. |
| Login limited to 5 failures | A slot reserved before verifying, refunded on success; the bucket keyed on the normalised email | `rate_limit` counts every call, so successes are refunded. Reading the buckets first and counting afterwards let a burst of parallel guesses through (plan review, finding 1). |
| `db:verify-rls` as a check | `python -m loreos.verify_rls` behind a root script | A `scripts/check-*.mjs` file is pulled into CI by the harness glob, and CI has no `DATABASE_URL`. |
| testdb as superuser | testdb's init creates a non-superuser owner role (`LOGIN CREATEROLE BYPASSRLS`), and conftest connects as it | A superuser can `SET ROLE` and use every schema, so missing grants pass the tests and fail on Supabase. |
| The worker starts unasked | `paid:worker`, and the guard asks on the worker and on `docker compose up` | It embeds every pending row through OpenAI. Operator decision, 2026-10-11. |
| `parsing.py` gains DOCX and HTML | New modules; `parsing.py` gains only the dispatch | `parsing.py`'s source text keys the evaluation workspace, so every edit re-embeds the corpus and leaves another `eval-*` workspace. |

## Risks

- **Supabase specifics.** `postgres` must be able to create `loreos_app`, grant it to itself with `SET`, and switch to it through the session pooler. On Postgres 16 and later the creator gets ADMIN but not SET unless granted. `db:verify-rls` is the proof on the real database.
- **The processing transaction stays open across every OpenAI call.** Supabase's `idle_in_transaction_session_timeout` could abort a large document. `db:verify-rls` prints it, and the plan sizes the timeout against the largest corpus file.
- **The pinned URL connection** needs a custom `httpcore2` network backend. The mixed-address test proves it.
- **The image size** is measured against the dev machine's free disk with `docker system df`; the build cache adds 2 to 3 times the image.
- **P3 and P4 share files.** Migration heads (the second to merge rebases its revision), `settings.py`, `.env.example`, `tests/test_config.py` (its exact key set), `tests/conftest.py`, `pyproject.toml` and `uv.lock` (re-locked, never merged by hand), and the ask route's response. P3 behaviour 7 loads the reranker at startup in the api only, since the worker never searches.
- **Merge timing against P3's paid runs.** RLS and any edit to `ingest.py` change the evaluation workspace key and the search latency. P4 merges before P3's first chunk-size run or after its `--mode all` run, never between them.
- **P2's baseline** merges to `main` from `p2-baseline` (decision 0005 changes the judge default). P4 then merges `main` in and resolves `settings.py` and `.env.example` by hand.
