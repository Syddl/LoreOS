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


---

# Review: p4-platform-shell, re-review of the fix wave (`313de88..d0f3975`)

Lens: security
Reviewer: harness:reviewer, fresh context, read-only shell.

## Executed

```
npm run check:all
PASS: hooks 395/395, agent-hooks 7/7, backend 705 passed / 2 skipped (247 s),
licenses 48/48 + 84/84, spend 123/123, frontend 7 files / 38 tests, tsc, vite build

npm run check:compose
PASS: config points at checkdb + fake key; build tagged only "loreos-check:local";
api healthy (so its new startup verify_rls passed on checkdb); / and /login serve;
no .env under /app; worker running; image 93 MB; stack removed
```

I also did read-only inspection:
- I read `git diff 313de88 d0f3975` and these files in full: verify_rls, main, worker, auth, fetch_url, documents and workspaces routes, ingest.run_stages, migration 0002, compose, the check override, check-compose.mjs, `.dockerignore`, Invite, router, and the new and changed tests.
- I read the private-network lists in CPython 3.14's `ipaddress.py`.
- I read moby's `daemon/internal/restartmanager/restartmanager.go` and `daemon/daemon.go` (restore) through WebFetch.

## Resolution of findings 1 to 14

| # | Resolution |
|---|---|
| 1 | **Resolved.** <ul><li>`policy` requires both policies to be named `workspace_isolation`, permissive, `polcmd='*'`, `polroles={loreos_app}`, with both expressions equal to the migration's. Names are unique per table, and `other_policy` refuses any other name, so exactly two policies exist.</li><li>A restrictive or `to public` policy under another name trips `other_policy`. Recreated under the same name, it trips `policy` (`polpermissive` or `polroles`).</li><li>FORCE RLS binds only owners, and `owner` already refuses a loreos_app that owns or inherits an owner. FORCE on the connecting role fails closed: system_session then sees 0 rows.</li><li>`isolated` runs the real `workspace_session` path.</li><li>Any remaining bypass needs DDL by the owner (triggers, rules, a shadowed `current_setting` or `=` on search_path). That is outside this check's misconfiguration model.</li><li>The PG17 string: exact comparison can only fail falsely, never pass falsely. I know of no change in how these expression nodes are rendered between PG13 and PG17, but it is unverified on Supabase.</li><li>Tests and report agree: 3 new negatives, and `isolated` added to 5 more.</li></ul> |
| 2 | **Resolved.** Code and the 3 real-grant tests agree. A systemic failure later than batch 1 of the embed stage stays uncounted, but its retry fails free at batch 1. |
| 3 | **Resolved.** The lifespan runs `isolation_problems()`, and a test pins it. In my check:compose run the api started healthy with it. |
| 4 | **Resolved.** The Origin's scheme is read only on cookie writes (login, signup, invite accept), which the same-host Origin rule already gates. A client spoofing it only marks its own cookie Secure. |
| 5 | **Not resolved.** The no-handover gap is recorded nowhere: KNOWN-GAPS has no row for it. The new text "owners cannot be removed" is false once a second owner exists. |
| 6 | **Resolved** (`**/.env`, `**/.env.*`). No check fails if reverted. |
| 7 | **Resolved.** <ul><li>`UPLOAD` carries the router's full prefixed path, and `Match.FULL` needs POST.</li><li>`add_document` reads its body only after `current_member`, and it is the only route that reads a body itself.</li><li>Trailing-slash and HEAD requests get the 64 KB cap.</li><li>Tests cover chunked, declared and a 100 KB login (0 `rate_limits` rows).</li></ul> |
| 8 | **Resolved.** Seen in my run: only `loreos-check:local` was named. No check fails if reverted. |
| 9 | **Not resolved, because** `on-failure` opens a new unasked-start path (Findings, row 1). |
| 10 | **Resolved** as a spec note. main is still at `faa149c`, so the merge itself is pending. |
| 11 | **Resolved.** `::` becomes 0.0.0.0 and `::1` becomes 0.0.0.1. Both fall in IPv4 `0.0.0.0/8`, so both are refused. `::ffff:` addresses are outside `::/96` and are unwrapped first. A sibling prefix remains (Findings, row 4). |
| 12 | **Resolved.** |
| 13 | **Resolved**, with a test. |
| 14 | **Resolved** for session history. The custom router keeps `null` state, so `replaceState(null, …)` loses nothing. |

On the specific questions:
- **API needs the database at startup:** this fails closed. With no database, uvicorn exits and compose's `unless-stopped` restarts the api. No secret is logged, and I found no new defect.
- **`lock` stage:** no UI or parser reads the stage values.

## Findings

| Severity | file:line | Impact | Fix | Owner |
|---|---|---|---|---|
| minor | `docker-compose.yml:40`; `docs/KNOWN-GAPS.md:7` | <ul><li>Moby's `on-failure` branch checks only `exitCode != 0` and ignores `hasBeenManuallyStopped`.</li><li>At startup the daemon restarts every container where `cfg.AutoRestart && c.ShouldRestart()`. A container found dead on restore gets exit code 255.</li><li>So a worker whose last exit was non-zero starts and spends at the next Docker start, even after `docker compose stop`, with no command for the guard to ask on. Three ways to get there: the startup check's exit-1 loop; a SIGKILL after the 10 s stop grace, when `release()` waits on an unreachable database; or a host or VM kill.</li><li>`unless-stopped` never restarted a manually stopped worker.</li><li>The KNOWN-GAPS row says "a daemon restart does not start it".</li></ul> | Pick one:<ul><li>`restart: "no"` on the worker, so a crashed worker waits for an approved `up`;</li><li>or keep `on-failure` and rewrite the clause to name the non-zero-exit case, with `docker compose down` as the way to keep the worker stopped.</li></ul> | dispatcher |
| nit | `docs/sdd/p4-platform-shell/STATUS.md:111`; `scripts/check-compose.mjs:39` | <ul><li>"Each fix is red first, and each redproof PASS" overstates the proof. The fix-2 report says its redproof was not run. Fix-4 has none for the Shell fix. Findings 5, 6, 8 and 9 have no test that fails on revert.</li><li>Reverting 8 or 9 keeps both checks green: the image inspect would only print `NaN MB`.</li></ul> | <ul><li>Reword STATUS fix by fix.</li><li>In check-compose step 0, assert from the resolved config that every image is `loreos-check:local` and that the worker's `restart` is what the decision for row 1 sets.</li></ul> | dispatcher |
| nit | `backend/loreos/routes/workspaces.py:92`; `docs/KNOWN-GAPS.md` | Finding 5's text is wrong once two owners exist, and the gap (no role change, no ownership handover) has no row. | Text: "a workspace keeps at least one owner, and no route makes a member an owner yet". Add a KNOWN-GAPS row for the gap. | implementer (4.3) for the text; dispatcher for the row |
| nit | `backend/loreos/fetch_url.py:25` | <ul><li>A sibling of 11: IPv4-translated `::ffff:0:0:0/96` (RFC 2765) is in no CPython 3.14 private list and is not `ipv4_mapped`.</li><li>So `::ffff:0:7f00:1` passes `_public` and is dialled.</li><li>It is unroutable on Linux without a SIIT translator, the same reach as 11 had.</li></ul> | <ul><li>Add `ipaddress.ip_network("::ffff:0:0:0/96")` to `CARRIES_IPV4`.</li><li>Add a `translated.test` case beside `compat.test`.</li></ul> | implementer (2.4) |

Out of scope: the `isolated` count scans `loreos.chunks` without an index that starts with `workspace_id`, on every api and worker start. That is a performance cost, not this lens.

## Verdict

**Merge.** Only one minor and three nits remain, and each has an owner above.

## Does NOT prove

- **Supabase:** I did not run `db:verify-rls` live, and the PG15/17 rendering of `ISOLATION` is unverified there. A mismatch would stop both the api and the worker, with a "recreate it as 0002 does" message that does not fit the cause.
- **Docker restart behaviour:** this comes from reading moby's source, not from executing it. The owner can confirm it:
  1. Make the worker exit 1 (for example, point `DATABASE_URL` at nothing) under a fake key.
  2. Run `docker compose stop`.
  3. Restart Docker.
  4. Run `docker compose ps worker`.
- **The `::ffff:0:7f00:1` verdict** comes from the CPython source, not from a run. The owner can run `uv --directory backend run python -c "import ipaddress; print(ipaddress.ip_address('::ffff:0:7f00:1').is_global)"`.
- **Redproof claims:** not re-run, because that would modify files.
- **Browser:** not checked with a real browser: the Secure cookie through a real TLS proxy, the browser's global history after `replaceState`, and StrictMode.
- **Other platforms and services:** no CI on Linux, no real OpenAI call, and no document reached the compose worker.
- **`isolated` on a separate connection** failing while every static check passes: I could not build such a case, and neither could the fix-1 report.

Key files:
- `C:/Users/justine/Documents/code/loreos/.claude/worktrees/p4-platform-shell/docker-compose.yml`
- `C:/Users/justine/Documents/code/loreos/.claude/worktrees/p4-platform-shell/docs/KNOWN-GAPS.md`
- `C:/Users/justine/Documents/code/loreos/.claude/worktrees/p4-platform-shell/docs/sdd/p4-platform-shell/STATUS.md`
- `C:/Users/justine/Documents/code/loreos/.claude/worktrees/p4-platform-shell/scripts/check-compose.mjs`
- `C:/Users/justine/Documents/code/loreos/.claude/worktrees/p4-platform-shell/backend/loreos/routes/workspaces.py`
- `C:/Users/justine/Documents/code/loreos/.claude/worktrees/p4-platform-shell/backend/loreos/fetch_url.py`
- `C:/Users/justine/Documents/code/loreos/.claude/worktrees/p4-platform-shell/backend/loreos/verify_rls.py`
