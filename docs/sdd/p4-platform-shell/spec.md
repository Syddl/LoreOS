# Spec: P4 platform shell

Phase P4 of [the v1 brief](../v1/brief.md). Draft written before P1 started: when P4 starts, re-read it against what P1 and P2 built, then plan. P4 can run beside P3 once P2 is merged.
Sizing: an auth and data-isolation surface, so every lifecycle step runs and the whole-branch review is by an independent reviewer.

## Summary

P4 turns the local slice into something a team can self-host. It adds workspaces isolated by Postgres row-level security, accounts with login, API keys, a worker that ingests with retries, DOCX and single-URL import, the web UI, and a `docker compose up` that starts the api and worker.
Kill switch: none. Running without isolation or login would be wrong in every deployment; a check pins that no environment key turns either off.

## Interfaces

| Interface | Kind | Owner file | Contract |
|---|---|---|---|
| `users` | table | migration | `id, email unique (stored lowercased), password_hash (argon2id), created_at` |
| `memberships` | table | migration | `(user_id, workspace_id) pk, role check (role in ('owner','member'))` |
| `sessions` | table | migration | `id` (sha256 of the cookie token), `user_id, created_at, expires_at` |
| `invites` | table | migration | `token_hash, workspace_id, created_by, expires_at, used_at` |
| `api_keys` | table | migration | `id, workspace_id, kind ('secret'; P6 adds 'publishable'), name, prefix, key_hash, created_at, last_used_at, revoked_at` |
| `rate_limits` | table | migration | `(bucket, window_start) pk, count`; fixed windows |
| `documents` additions | migration | | `kind` adds `docx` and `url`; `source_url`, `next_attempt_at`, `locked_until` |
| `loreos_app` | Postgres role | migration | `NOLOGIN`, no `BYPASSRLS`, owns nothing; granted data rights on workspace tables; granted to the connecting role so it can switch to it. |
| RLS policies | migration | | On every table with a `workspace_id`: rows visible and writable only when `workspace_id = nullif(current_setting('app.workspace_id', true), '')::uuid`. |
| `workspace_session(workspace_id)` | async context manager | `backend/loreos/db.py` | Now also runs `SET LOCAL ROLE loreos_app` and sets `app.workspace_id` for the transaction. Callers unchanged. |
| `rate_limit(bucket, limit, window_s) -> (allowed, retry_after)` | function | `backend/loreos/ratelimit.py` | One upsert per call; P6 reuses it. |
| `current_member(request, workspace_id)` | FastAPI dependency | `backend/loreos/auth.py` | Session cookie or `Authorization: Bearer lo_sk_...`; returns user or key, workspace and role; 401 or 404. |
| Auth routes | routes | `backend/loreos/routes/auth.py` | `POST /api/auth/signup`, `POST /api/auth/login`, `POST /api/auth/logout`, `GET /api/me`, `POST /api/invites/{token}/accept` |
| Workspace routes | routes | `backend/loreos/routes/workspaces.py` | `GET, POST /api/workspaces`; under `/api/workspaces/{id}`: `members`, `invites`, `api-keys` (owner only) |
| Document and ask routes | routes | `backend/loreos/routes/documents.py` | Under `/api/workspaces/{id}`: `POST documents` (file or `{url}`), `GET documents`, `GET documents/{doc}`, `DELETE documents/{doc}` (owner), `POST ask`. Replace P1's unscoped routes. |
| `GET /api/health` | route | `backend/loreos/main.py` | 200 when the database answers; the compose healthcheck. |
| Worker | process | `backend/loreos/worker.py` | `python -m loreos.worker`; claims, processes and retries documents. |
| Admin CLI | process | `backend/loreos/admin.py` | `python -m loreos.admin reset-password <email>` prompts for a new password and ends that user's sessions. |
| `npm run db:verify-rls` | root script | `package.json` | Read-only assertions on roles and policies against `DATABASE_URL`. Free. |
| Image | file | `Dockerfile` | Node stage builds `frontend/dist`; Python stage installs from `uv.lock`, copies `dist`, bakes the tiktoken encoding and the reranker model; runs as a non-root user. |
| Compose | file | `docker-compose.yml` | `migrate` (one-shot `alembic upgrade head`), `api` (after `migrate`, `127.0.0.1:8000:8000`, healthcheck), `worker` (after `migrate`); `env_file: .env`; P1's `testdb` stays under profile `test`. |
| UI | app | `frontend/` | React, Vite, strict TypeScript, Tailwind, shadcn; built to `frontend/dist`, served by FastAPI at `/` with a fallback to `index.html` for non-`/api` paths. Own `package.json` and lockfile. |
| Root scripts | package.json | `package.json` | `dev:web`, `check:frontend`, `check:compose`, `db:verify-rls` |

## Behaviour

Isolation
1. Every read and write of workspace data runs inside `workspace_session`, as `loreos_app`, with `app.workspace_id` set. With the setting missing, every policy matches no row: isolation fails closed.
2. The connecting role (`postgres` on Supabase) owns the tables and may carry `BYPASSRLS`, so policies alone would not bind it; the role switch is what makes RLS apply. Application filters on `workspace_id` stay as a second layer.
3. Claiming a worker job is the one query that runs without a workspace context; it reads only document `id` and `workspace_id`, then processes inside that document's workspace session.

Accounts and login
4. Signup is open only while no user exists. The first account becomes owner of a new workspace and of every workspace with no owner, including P1's default. Every later account joins through an invite.
5. An owner creates an invite link: single use, expires after 7 days, stored as a hash. Accepting it while logged out creates the account; logged in, it adds the membership.
6. Passwords are hashed with argon2id and must be at least 12 characters. Unknown email and wrong password get the same error and take comparable time.
7. Login sets an `HttpOnly`, `SameSite=Lax` session cookie holding 32 random bytes, `Secure` when the request arrived over HTTPS; the database keeps only its hash; it expires after 14 days; logout deletes it.
8. Login is limited to 5 failures per email and 20 per client IP per 15 minutes; past that it gets 429 with `Retry-After`.
9. A cookie-authenticated `POST`, `PUT`, `PATCH` or `DELETE` must carry an `Origin` equal to the app's own origin, or it gets 403.
10. Roles: a member uploads, lists and asks; an owner also deletes documents and manages members, invites and API keys.

API keys
11. An owner creates a secret key (`lo_sk_` and 32 random bytes) shown once; the database keeps its sha256 and an 8-character prefix for display. A revoked key gets 401.
12. A key reaches only its own workspace's document and ask routes. A key used on another workspace's path gets 404, and a key on member or key routes gets 403.

Worker and ingestion
13. Upload stores the document as `pending` and returns 202 (a duplicate as in P1, a failed duplicate re-queued with 202). The worker claims the oldest due `pending` document, or a `processing` one whose lease ran out, with `FOR UPDATE SKIP LOCKED`; it sets `processing`, a 10-minute lease and `attempts + 1`.
14. Failures are classified before handling. Permanent ones (unsupported type, parse error, no text, URL refused, HTTP 4xx) fail at once. Transient ones (OpenAI rate limit, 5xx or timeout, network error, HTTP 5xx, lost database connection) return to `pending` after 30 s, then 2 min; the third failure is final. `error` always holds the latest stage, class and message, and the UI shows it.
15. Processing replaces the document's chunks in one transaction, so a retry after a crash never duplicates chunks.
16. DOCX: python-docx; paragraphs styled `Title` or `Heading 1` to `Heading 9` start sections and build the heading path; tables become text rows in document order.
17. URL import fetches one page in the worker; there is no crawl. Only `http` and `https` are allowed. Every address the host resolves to must be public: loopback, private, link-local (including 169.254.169.254), CGNAT, multicast and unspecified addresses are refused. The connection goes to the address that passed the check, and every redirect (at most 5) is checked again. Limits: 10 s and 5 MB. HTML becomes sections by `h1` to `h6` with script, style, nav, header, footer and aside removed. A `text/plain` page is read as TXT and a PDF as PDF; any other content type fails with its name. Submitting the same URL again re-fetches it.

Shell
18. `docker compose up` with `DATABASE_URL` and `OPENAI_API_KEY` in `.env` runs migrations, then starts the api and the worker; the UI loads at `http://localhost:8000`. A missing key stops the service with the message naming it.
19. UI screens: signup and login, invite acceptance, workspace switcher and creation, documents (upload a file or a URL, status, the error of a failed document, delete for owners), ask (the answer with `[n]` markers as buttons; a marker opens a side panel with the passage, filename and heading path or page), and settings (members, invites, API keys shown once, revoke). Controls have labels, work from the keyboard, and the side panel takes and returns focus.
20. `check:licenses` also covers the frontend's production dependencies.

## Acceptance checks

| # | Behaviour | Check | Expected | Does NOT exercise |
|---|---|---|---|---|
| 1-2 | Isolation (the brief's test) | `npm run check:backend`, `tests/test_isolation.py` | Two workspaces with chunks; with A's key, list and ask return only A's ids; in A's session `select count(*) from chunks` with no filter equals A's count; with no workspace set it is 0; `loreos_app` has `rolbypassrls = false` and owns no table | Supabase's own role attributes (next row) |
| 1-2 | Isolation on Supabase | `npm run db:verify-rls` | Same role and policy assertions pass against `DATABASE_URL`; ledger row by hand | |
| 4-9 | Login | `tests/test_auth.py` | Second signup refused; invite single use and expiry; cookie flags; 429 on the 6th failure; foreign `Origin` gets 403 | Browser cookie handling (manual row) |
| pin | No off switch | `tests/test_auth.py` | No environment key makes an unauthenticated request succeed on any workspace route | |
| 10-12 | Roles and keys | `tests/test_keys.py` | Member gets 403 on key routes; revoked key 401; key on another workspace 404 | |
| 13-15 | Worker | `tests/test_worker.py` with fakes | Transient fake error retried twice then `failed` with the error; permanent fails at once; two workers never claim the same row; a run killed mid-way leaves no duplicate chunks | Real OpenAI outages |
| 16 | DOCX | `tests/test_parsing.py` | Heading path from styles; table text present | |
| 17 | URL guard | `tests/test_url_fetch.py` with a local server and a stub resolver | Loopback, private and metadata addresses refused, including after a redirect and when the name resolves to both a public and a private address; size and time limits hit | DNS answers that change between our check and the connection (pinned by design, reviewed) |
| 18 | Compose | `npm run check:compose` (CI and local; builds the image, `DATABASE_URL` on `testdb`, fake OpenAI key) | `/api/health` 200; `/` and `/login` return the app HTML | A real OpenAI call |
| 19 | UI | `npm run check:frontend` (typecheck, vitest, build) | Marker buttons map to citations; the build writes `frontend/dist/index.html` | Visual layout (manual row with a screenshot) |
| 20 | Licenses | `npm run check:licenses` | Passes on both lockfiles | |

## Kill switch

None. The `test_auth.py` row pins that no environment read disables auth or isolation. `HARNESS_HOOKS=off` is unrelated: it silences the agent guard, not the product.

## Not changing

- Retrieval, fusion, rerank and evaluation files: P3 owns them in this window.
- Publishable keys, allowed domains and the widget: P6. `rate_limit` is built here for login and reused there.
- Roles beyond owner and member; email sending; password reset by email; OAuth or SSO; the crawler; caching; Redis.

## Risks

- Supabase specifics: the plan checks that `postgres` can create `loreos_app`, grant it to itself and `SET ROLE` to it through the session pooler. `db:verify-rls` is the proof on the real database.
- The Supabase pooler caps connections; the api and worker pools are sized small (about 5 and 2) and the plan reads the project's actual limit.
- A 10-minute lease can expire on a very large document while it is still embedding; the worker extends the lease between batches.
- Pinning the URL connection to the checked address needs a custom httpx transport; the plan proves it with the mixed-address test.
- The image carries onnxruntime and the reranker model; its size is measured against the dev machine's free disk.
- P3 and P4 both add migrations; see P3's risks for the merge rule.
