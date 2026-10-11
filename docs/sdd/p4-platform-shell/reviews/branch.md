**P4 whole-branch review (`p4-platform-shell` at `313de88`, base `faa149c`), security lens**

## Executed
- **`npm run check:all`: PASS.**
  - hooks 395/395, agent-hooks 7/7.
  - backend 692 passed, 2 skipped (243 s).
  - licenses 48/48 backend and 84/84 frontend; spend 123/123.
  - frontend 6 files, 36 tests, typecheck and build.
- **`npm run check:compose`: PASS.**
  - The resolved config points every service at checkdb, the fake key and the unroutable OpenAI URL.
  - `/api/health` is 200, and `/` and `/login` serve the app.
  - No `.env*` under `/app`; the worker is running; the image is 93 MB.
  - Side effect: the local `loreos:local` tag now holds this tip's build (see finding 8).
- **Read-only inspection:**
  - `git diff faa149c...HEAD` and the security files in full: db, auth, both route files, main, ratelimit, fetch_url, the parsers, worker, verify_rls, admin, the migration, the Dockerfile and compose, check-compose, the frontend api, Shell, Settings and Invite.
  - The tests for isolation, auth, the app shell, the worker and URL fetch.
  - httpx2's decoders: each decode step is capped at 1 MiB, so `TooLarge` stops a decompression bomb.
  - The P1 tests from the deleted `test_local_only.py` all reappear on the scoped routes.
  - `git ls-files --eol`: every file is LF.
  - Attribution grep over the commit messages: 0 hits.
  - `git log -3 main`: main is still at `faa149c`.
  - `git diff main...p2-baseline`: it touches `db.py`.
- **Refused by the read-only shell:** `git merge-base main HEAD` and `echo`.

## Findings

| # | Sev | file:line | Impact | Fix | Owner |
|---|---|---|---|---|---|
| 1 | major | `backend/loreos/verify_rls.py:72` | The `policy` check only asks whether a policy *named* `workspace_isolation` exists on both tables. It never checks the condition, the command, the roles or whether the policy is permissive, nor that no other policy applies. An extra permissive policy would make RLS useless while `db:verify-rls`, the smoke preflight and the worker's startup check all print ok. Supabase's dashboard templates create exactly that kind (`to public using (true)`). This check is the only live proof of the isolation row on Supabase. The app's own `workspace_id` filters remain, as the second layer. | Assert the exact policy set in `pg_policy`: one permissive `for all` policy per table, roles `{loreos_app}`, condition equal to the migration's, and no other policy. Add a check: inside `workspace_session(uuid4())` both counts are 0. Add negative tests for an extra `using (true)` policy and for a changed condition. | implementer (1.3) |
| 2 | minor | `backend/loreos/worker.py:102` | A systemic failure raised after the first paid call (`EmbeddingDimensionError`, or a missing-grant error at store) never counts as an attempt. The document comes back every 300 s and buys another 100-input embedding batch each time, with no end. The plan accepts this, but KNOWN-GAPS records neither the loop nor its cost per occurrence, which its own rule requires. | Count an attempt when a systemic failure happens at the embed or store stage, so a document stops after 3 batches. Or stop claiming until restart. Otherwise add the KNOWN-GAPS row with its cost. | implementer (3.3), dispatcher for KNOWN-GAPS |
| 3 | minor | `backend/loreos/main.py:35` | At startup the api checks only the two keys. `verify_rls` runs in the worker and in smoke, but not in the process that serves workspace data. A `loreos_app` with BYPASSRLS, or a missing policy, would serve with only the app filters. | Call `verify_rls.problems()` in the api's startup, beside `startup_problems()`. | implementer (4.1) |
| 4 | minor | `backend/loreos/auth.py:239`; `docs/KNOWN-GAPS.md:9` | Behind compose and a TLS proxy without `FORWARDED_ALLOW_IPS`, uvicorn does not trust `X-Forwarded-Proto` from the Docker gateway, so the session cookie is never `Secure`. The KNOWN-GAPS row names only the shared login bucket. | Mark the cookie Secure when the URL scheme or the Origin (which login requires) is https. Or add this impact to the row and to `.env.example`. | implementer (2.2) or dispatcher |
| 5 | minor | `backend/loreos/routes/workspaces.py:92` | No route or screen changes a role, so every workspace has exactly one owner forever. The 409's advice, "make another member an owner first", cannot be followed, and an owner can never hand a workspace over. The two-owners test creates its second owner with SQL. | Add a role change on members (owner only, same row lock), or reword the 409 and record the gap. | implementer (4.3) |
| 6 | minor | `.dockerignore:2` | `.env` and `.env.*` match only at the build context's root. A `backend/.env`, `frontend/.env.local` or `eval/.env` enters the context. The Node stage copies `frontend/` whole, and Vite builds `VITE_*` values into `dist`. check:compose's probe only looks for files named `.env*` under `/app` in the final image. | Use `**/.env` and `**/.env.*`. | dispatcher (6.1) |
| 7 | minor | `backend/loreos/main.py:23` | The 20 MB body cap applies to every route. FastAPI parses a JSON body before running dependencies. So login, signup, invite accept, and also ask and create-workspace before their auth check, parse up to 20 MB on the event loop without credentials. Login's rate limit runs after the parse. | A small cap, such as 64 KB, on every path except `POST …/documents`. | implementer (4.1) |
| 8 | minor | `scripts/compose-check.yml:16` | The check tags its build `loreos:local`, the tag the real stack runs. A later `docker compose up` without `--build`, from any checkout, runs whichever tree last ran the check, against the real `.env`. | Set `image: loreos-check:local` in the override. | dispatcher (6.1) |
| 9 | minor | `docker-compose.yml:38`; `docs/KNOWN-GAPS.md:7` | `restart: unless-stopped` restarts the worker, which spends, whenever Docker starts, with no command for the guard to ask on. `docker start` or `docker restart <container>` is not matched either. The spend-guard row lists only `docker run`. | Add both to the row, or use `restart: on-failure`. | dispatcher |
| 10 | minor | `docs/sdd/p4-platform-shell/spec.md:175` | `p2-baseline` also rewrites `db.py` (connect retry, `event` import) next to P4's import and session changes. The merge note names only `settings.py` and `.env.example`, and the reviewed tip has not met that merge yet. | After p2-baseline lands, merge main, resolve `db.py`, and re-run `check:all` including `test_db.py`. | dispatcher |
| 11 | nit | `backend/loreos/fetch_url.py:116` | IPv4-compatible `::a.b.c.d` addresses are, as I read CPython's `ipaddress`, outside its private list, so `_public` probably lets them through. They are not routable on Linux today. | Refuse `::/96`, or judge it by its last 32 bits as NAT64 is. | implementer (2.4) |
| 12 | nit | `backend/tests/test_isolation.py:249` | The caller scan matches only `system_session(` and `engine()`. A direct `create_async_engine(settings.database_url())` elsewhere would open a session RLS does not bind, unseen. | Also match `create_async_engine` and `database_url(`. | implementer |
| 13 | nit | `frontend/src/components/Shell.tsx:133` | Logging out with an expired session shows "log in first" instead of going to `/login`. | Treat a 401 there as logged out. | implementer (5.2) |
| 14 | nit | `frontend/src/screens/Invite.tsx:10` | The live invite token stays in browser history as `/invite#<token>`. | Drop the fragment with `history.replaceState` once it is read. | implementer (5.2) |

**Out of scope:** two simultaneous submissions of the same new URL or file both pass the duplicate check and hit `unique(workspace_id, sha256)`, so the second gets a 500. This is P1's pattern, which `enqueue_url` inherits.

**Lens questions answered, no other finding:**
- **Isolation:** every documents and ask route runs in `workspace_session`. Every `system_session` statement on one workspace's rows filters on `workspace_id`. Chunks carry a composite foreign key. The isolation tests can fail: the unfiltered counts and the update test go red without RLS.
- **Auth:**
  - The Origin rule exempts only Bearer requests, and the cookie routes refuse an `Authorization` header.
  - The rate limit reserves first and refunds only on success; the concurrent-guess test passed.
  - Invites are single-use (atomic update), and signup is serialised by an advisory lock.
  - The admin reset ends every session of that user.
- **SSRF guard:**
  - The connection dials the address that passed the check.
  - Every resolved address is checked, and so is every redirect hop.
  - IPv4-mapped and NAT64 addresses are unwrapped before the check.
  - Proxies and userinfo are refused, and there is one overall 10 s timeout.
- **Worker:** failure writes are fenced on the lease; `SKIP LOCKED` is proven; leases are recovered; a stop releases the claim.
- **Frontend:** an API key lives only in component state; the invite token rides in the fragment and the request body only; 401 goes to `/login` on Documents, Ask, Settings and the Shell.
- **P2 interplay:** the evaluation still calls `ingest()` inline through `workspace_session`. There is one migration head, `0002_platform`.
- **Process:** no AGPL or GPL dependency, no "BM25", no attribution, no CRLF.

## Verdict
**Fix then re-review.** Finding 1 is a major; the minors can be fixed in the same pass.

## Does NOT prove
- **Supabase:** live `db:verify-rls`, the `SET` grant, `USAGE` on `extensions`, and its idle timeout. Not run.
- **CI on Linux:** the branch is not pushed. The Linux path of the UI fallback and the SIGTERM release were not exercised.
- **HTTPS fetch:** no test or run of mine went over HTTPS through the pinned connection, so SNI and certificate checking are unproven.
- **Real OpenAI:** no call made, and no document reached the worker under compose.
- **Browser:** cookies, keyboard and focus beyond vitest with jsdom, and visual layout.
- **Redproof and mutation claims** in the task reports: not re-run, because that would modify files.
- **File ownership per task:** spot-checked only, not every commit against the plan's owned paths.
- **Finding 11** was not executed. The owner can check it with `uv --directory backend run python -c "import ipaddress; print(ipaddress.ip_address('::7f00:1').is_global)"`.
- **The p2-baseline merge** and its `db.py` resolution.
- **Refused commands:** `git merge-base` and `echo`. I took the base from the dispatch and from main still sitting at `faa149c`.

Key files:
- `C:/Users/justine/Documents/code/loreos/.claude/worktrees/p4-platform-shell/backend/loreos/verify_rls.py`
- `C:/Users/justine/Documents/code/loreos/.claude/worktrees/p4-platform-shell/backend/loreos/worker.py`
- `C:/Users/justine/Documents/code/loreos/.claude/worktrees/p4-platform-shell/backend/loreos/main.py`
- `C:/Users/justine/Documents/code/loreos/.claude/worktrees/p4-platform-shell/backend/loreos/auth.py`
- `C:/Users/justine/Documents/code/loreos/.claude/worktrees/p4-platform-shell/backend/loreos/routes/workspaces.py`
- `C:/Users/justine/Documents/code/loreos/.claude/worktrees/p4-platform-shell/.dockerignore`
- `C:/Users/justine/Documents/code/loreos/.claude/worktrees/p4-platform-shell/scripts/compose-check.yml`
- `C:/Users/justine/Documents/code/loreos/.claude/worktrees/p4-platform-shell/docs/KNOWN-GAPS.md`
