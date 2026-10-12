---
status: open
feature: p4-platform-shell
---

# Status: p4-platform-shell

The single carrier of state between sessions. Update it before a session ends; the session-start hook injects the open lines. Status is one of open, blocked, done.

## Open tasks

- Step 3, spec revised against P1 and P2: done (2026-10-11). An independent audit read the draft against the merged code, and its findings are in `spec.md`, section "Revised against P1 and P2". The operator decided three things: login with email and password ([decision 0006](../../decisions/0006-login-email-and-password.md)), MPL-2.0 allowed unmodified ([decision 0007](../../decisions/0007-mpl-2-0-dependencies-unmodified.md)), and the spend guard gating the worker and `docker compose up`. The engineering calls follow the audit's recommendations, listed in the same section, for the operator to veto.
- Step 4, plan: done (2026-10-11). `plan.md` drafted by the Plan agent: 7 phases, 25 tasks in windows A to F, plus the live rows in phase 7.
  - The main session took four of the planner's open questions as engineering calls:
    - testdb's owner role is created by conftest's bootstrap, since CI's service container starts before checkout and cannot read an init file;
    - the compose guard also asks on `start`, `restart` and `run`, since each one starts the worker;
    - Origin is required on every write without a Bearer key, login included. Spec behaviour 9 now says so;
    - the worker checks the grants at startup, and a stop releases its claim. The first draft also capped connections at 10; plan review removed that cap (see below).
  - The fifth, verifying the live rows early against a throwaway Supabase project, is left to the operator. The default is the merge window.
- Step 5, plan review by execution:
  - **First review**: "fix then re-review", with 6 majors, 10 minors and 3 nits ([reviews/plan.md](reviews/plan.md)). The reviewer ran `check:all` green at `a05f789`.
  - **Revision** `5ebbbac`: answers every finding. The plan's last section maps each one to its change.
  - **Re-review** of `5ebbbac`: "fix then re-review", appended to `reviews/plan.md`.
    - Findings 1, 5 and 17 were not resolved.
    - It found new defects F1 to F10. F1, uvicorn's concurrency cap counting idle sockets, made the main session drop the connection cap from v1, with a KNOWN-GAPS row.
  - **Second revision** `f24c0dc`: answers F1 to F10, mapped in the plan's last section.
  - **Third review** of `f24c0dc`: **merge**, appended to `reviews/plan.md`. Its seven minors, N1 to N7, are folded into their tasks; the plan's last section maps them. Step 5 is done.
- Step 6, implementation:
  - **1.1** done, `f9146d7`: `ALLOWED_HOSTS`, `startup_problems()`, and argon2-cffi, python-docx, beautifulsoup4, httpx2 and httpcore2. Red first on the exact key set; redproof PASS.
  - **1.2** done, `1db5430`: migration `0002_platform`, the per-checkout non-superuser test database, and every settings key pinned. `check:backend` 344 passed as `testdb_owner`. The redproof (`docx` dropped from the kind check) PASS, which proves the per-session recreate.
  - **1.4** done, `a584ef9`: the guard asks on the worker and on compose `up`, `start`, `restart`, `run` and `watch`, except a testdb-only `up`. check:spend 123/123; redproof PASS, with exactly the 2 interpreter cases red.
  - **1.3** done, `47ce731` (cherry-picked from the implementer's `f112b0c`; report in [tasks/1.3-report.md](tasks/1.3-report.md)): `workspace_session` runs as `loreos_app` with the workspace set; `system_session()`; `verify_rls` with 12 named checks; `test_isolation.py`.
    - Red first: the unfiltered counts were A + B.
    - Three redproofs PASS: the role switch, a commit, and a `reset role`.
    - The implementer found that the plan's `grant testdb_owner to loreos_app` negative makes a membership loop. The plan now revokes first.
  - **Window A** (phase 1) closed: `check:all` PASS at `47ce731` (ledger).
  - **Window B**, each implemented in its own worktree, cherry-picked, with a report under `tasks/`:

    | Task | Commit | What it adds | Proof |
    |---|---|---|---|
    | 2.1 | `973381a` | rate limit with refund | 7 tests; redproof PASS |
    | 2.2 | `5b11136` | auth core | 28 tests; redproof PASS |
    | 2.3 | `a419723` | DOCX and HTML parsers | redproof PASS |
    | 2.4 | `7a851ff` | URL fetch | 26 tests; redproof PASS |
    | 2.5 | `059d05b` | smoke preflight runs `verify_rls` | the main session's redproof PASS |
    | 5.1 | `be674a4`, `6c68438` | Vite 8, React 19, TypeScript 7, Tailwind 4, shadcn; `check:frontend` in `check:all` and CI | redproof PASS; check-wiring 8/8 |

    - **5.1 deviation:** shadcn's CLI now imports `cn` from its own `cn` package (MIT, by shadcn) instead of a local `lib/utils.ts`. `cn` replaces `clsx` and `tailwind-merge`, so both are dropped, and the 5.1 contract's `src/lib/utils.cn` is `cn` from `"cn"`.
    - **Fix from the 2.4 report**, `a9625ff`: a NAT64 address (`64:ff9b::/96`), which `ipaddress` calls global whatever IPv4 address it carries, is judged by that IPv4 address. Red first; redproof PASS.
  - **Window B closed:** `check:all` PASS at `e13614f` (ledger).
  - **Notes for later tasks**, from the window B reports:
    - **4.1:** the Origin exemption must cover only `Authorization: Bearer`. `current_member` sends any `Authorization` header down the key path and never falls back to the cookie (2.2).
    - **4.2 and 3.2:** `auth.create_user` and `hash_password` do not check length, so each caller calls `password_problem` (2.2).
    - **3.1:** `ingest.process` must pass `kind=fetched.kind` for URL documents (2.3).
    - **3.3:** `parse_html` takes about 10 s on a 5 MB page under bs4's `html.parser`, well inside the lease (2.3).
    - **Plan wording (2.4):** the proxy case proves the custom transport is kept. httpx2 ignores environment proxies whenever a transport is passed, so it does not test the `trust_env` flag.
  - **Window C**, each implemented in its own worktree, cherry-picked, with a report under `tasks/`:

    | Task | Commit | What it adds | Proof |
    |---|---|---|---|
    | 3.1 | the 3.1 cherry-pick | `enqueue`, `enqueue_url`, `run_stages`, `record_failed` | 10 new tests; the main session's two redproofs PASS (row lock, lock timeout) |
    | 3.2 | `f6090b8` | admin reset-password | 8 tests; redproof PASS |
    | 5.2 | the 5.2 cherry-pick | API client, router, shell, login, signup and invite screens | 18 frontend tests; redproof PASS |
    | 5.6 | `bb08230`, `bfd2c71` | MPL-2.0 allowed unmodified; the frontend production tree checked (84 packages) | three redproofs PASS |

    5.6 found two defects in its own first draft and fixed both:
    - npm repeats a package as a stub that lists no dependencies, so walking a name only once missed 14 packages;
    - a text-mode stdin on Windows silently garbles curly quotes, so a GPL license written with them passed.
  - **Main session fixes:** `test-setup.ts` now runs Testing Library's cleanup after every test (from the 5.2 report), and the 5.1 contract row no longer names `lib/utils`.
  - **Window D**, each implemented in its own worktree, cherry-picked, with a report under `tasks/`:

    | Task | What it adds | Proof |
    |---|---|---|
    | 3.3 | the worker: claim, classify, fenced record, release on stop, startup checks; `llm.EmbeddingDimensionError`; `paid:worker` | 48 tests; the main session's three redproofs PASS (systemic uncounted, expired lease, fence) |
    | 5.3 | Documents screen | 7 tests; redproof PASS |
    | 5.4 | Ask screen and citation panel | 5 tests; redproof PASS, after a test the redproof showed too weak was strengthened |
    | 5.5 | Settings screen | 6 tests; redproof PASS |

    - **Main session fix** `cd9fac6`: the `App.test.tsx` fixture answers the screens' list calls with `[]`. 5.3 and 5.5 both reported that it broke once the screens load data.
    - **3.3's own design calls**, kept:
      - a systemic failure sets `next_attempt_at` to +300 s;
      - a failure outside `run_stages` (the lock select, the session setup, the commit) is recorded as stage `store`.
    - **3.3 note:** the `llm.embed` edit changes the evaluation workspace key, as the plan's merge timing expects.
  - **Window D closed:** `check:all` PASS at `f32f211` (ledger).
  - **Window E1 and E2**, each implemented in its own worktree, cherry-picked, with a report under `tasks/`. Every redproof PASS.

    | Task | What it adds | Tests |
    |---|---|---|
    | 4.1 | the app shell: hosts, Origin (Bearer only), `BodyLimit`, health, a string-detail 422, the UI fallback | 98 |
    | 4.2 | signup, login (reserve and refund), logout, me, invite accept | 99 in `test_auth.py` |
    | 4.3 | workspace, member, invite and key routes, with cross-workspace guards and the last-owner lock | 32 |
    | 4.4 | document and ask routes under a workspace; P1's tests moved and `test_local_only.py` deleted; the brief's isolation test through the routes | 72 |

    - **4.1 found and fixed** a path in the UI fallback that leaked credentials on Windows. `/%5c%5chost%5cshare%5cx` decoded to a UNC path, so `resolve()` opened an SMB connection, and the dev account's NTLM hash could leak from any web page. The fallback now refuses rooted, drive and `..` paths before touching the filesystem, with a test.
    - **4.2 and 4.3 agree:** `Me` and `GET /api/workspaces` both hide `eval-*`, and both refuse a blank, long or `eval-` name.
  - **Window E2 closed:** `check:all` PASS at `a929684` (ledger).
  - **4.5** done (`e8aea62`): no environment key opens any of the 15 guarded routes, and only `settings.py` reads the environment, apart from an allowlist keyed on file and key. Its two redproofs PASS, plus the main session's `ingest.py` one.
  - **6.1** done (`ddc5276`):
    - `Dockerfile` (python:3.14-slim, the frontend built in a Node stage, the tiktoken encoding baked in, a non-root user) and `.dockerignore`;
    - compose with `migrate`, `api` and `worker`, with `env_file` optional;
    - `check:compose` under its own project, with its config asserted before anything starts, plus a CI job.

    `check:compose` PASS in about 84 s. The image `loreos:local` is 93 MB, against 19 GB free on C:. The redproof (the UI fallback answering 404) PASS.
  - **Simplifications** done (`db83b17`): one owner each for the workspace name rule and the workspace list (`loreos/workspaces.py`), for token hashing (`auth.token_hash`) and for the lock timeout (`ingest.LOCK_TIMEOUT`). The six affected test files pass, 226 tests.
  - **6.2** done:
    - KNOWN-GAPS loses the frontend-checks and chunked-upload rows.
    - It gains rows for the unpruned auth tables, the shared login IP bucket, the missing connection cap, and the file-versus-URL hash collision.
    - Its spend-guard row names the worker and compose spellings.
    - Decision 0002 points at 0007.
  - **Step 9, the whole-branch review** ([reviews/branch.md](reviews/branch.md), at `313de88`): "fix then re-review", with 1 major, 9 minors and 4 nits. The review ran `check:all` and `check:compose`, both PASS.
  - **Step 10, the fix wave** (reports `tasks/fix-1` to `fix-4`). The proof differs fix by fix:
    - **FW1** (findings 1, 3, 7, 12). Red first; four redproofs PASS.
      - `verify_rls` now checks the policy exactly (permissive, `for all`, `loreos_app` only, the migration's condition) and that no other policy exists. It also confirms that a session for an unknown workspace sees 0 rows.
      - The api runs it at startup.
      - Request bodies are capped at 64 KB, except uploads.
      - The caller scan also watches `create_async_engine` and `database_url(`.
    - **FW2** (finding 2): a systemic failure after a paid embedding counts as an attempt, so a document stops after 3 batches. A failure before the stages is labelled `lock`. Red first; the main session's two redproofs PASS.
    - **FW3** (finding 4): the cookie is `Secure` when the Origin is https. Red first; redproof PASS.
    - **FW4** (findings 13, 14): logout after expiry goes to `/login`, and the invite token leaves the browser history. Red first for both; redproof PASS for the invite fix only.
    - **Main session** (`40baf17`). Finding 11 has a red-first test. The others had no failing test until the re-review fixes below.
      - IPv4-compatible `::/96` addresses are judged by the IPv4 address they carry (finding 11, which was confirmed).
      - `.dockerignore` excludes nested `.env` files (6).
      - The check builds its own image tag, `loreos-check:local` (8).
      - The worker restart policy changes (9).
      - The last-owner 409 is reworded (5).
      - The spec and KNOWN-GAPS follow the fixes (10).
    - `e1fd29e`: one `verify_rls.isolation_problems()` for the api and the worker.
    - `check:all` PASS and `check:compose` PASS at `e1fd29e` (ledger).
  - **Step 9, the re-review** ([reviews/branch.md](reviews/branch.md), at `d0f3975`): **merge**, with 1 minor and 3 nits, each fixed:
    - **Worker restart:** the worker's `restart` is `"no"`. `on-failure` would restart a worker whose last exit was non-zero at the next Docker start, even after a stop.
    - **The check pins it:** `check:compose` now asserts from the resolved config every service's image (`loreos-check:local`), the worker's restart policy, and the four `.env` patterns in `.dockerignore`, so reverting 6, 8 or 9 fails the check.
    - **The last-owner text, and a gap row:** the 409 now says "a workspace keeps at least one, and no route makes a member an owner yet", and KNOWN-GAPS gains a row for the missing role change.
    - **One more IPv6 form:** IPv4-translated `::ffff:0:0:0/96` is judged like NAT64. Red first.
    - **This line:** reworded fix by fix.
  - **Simplifications from the E2 reports**, done in `db83b17`, apart from the last:
    - **Duplicated name rules:** `EVAL_NAME` and the `eval-` check live in both `routes/auth.py` and `routes/workspaces.py`. Move the check into `Name` and have `list_workspaces` call `workspaces_of`.
    - **Private helper used across modules:** `auth._sha256` is called from both route files; make it public.
    - **Duplicated timeout:** `'2s'` sits in both `ingest.py` and `routes/documents.py`; make it one `LOCK_TIMEOUT` constant.
    - **Signup lands in Default:** the oldest workspace comes first in the list, so a new user lands in Default rather than their own new workspace.
  - **Notes for later tasks**, from the window C reports:
    - **4.1:** install a handler for FastAPI's `RequestValidationError` that returns `{detail: "<message>"}` as a string. The default 422 returns a list, which `api.ts` shows as the status text (5.2).
    - **4.4:** `set local lock_timeout` lasts for the caller's whole transaction. The URL route's session should do nothing after `enqueue_url` (3.1).
    - **3.3:** `run_stages` returns the chunk count without logging it. The worker logs and builds its own error text, and calls `scrub` unless it goes through `record_failed` (3.1).
    - **5.3 to 5.5:** a 401 in the middle of a session must send the user to `/login`. The Shell checks the session only when it mounts (5.2).
    - **6.2:** decision 0002's license paragraph needs a pointer to 0007 (5.6).
    - **Whole-branch review:**
      - a `.txt` upload whose bytes equal a normalised URL hashes the same as that URL;
      - `ingest()` now processes a `pending` duplicate inline, so the evaluation always gets a processed document back (3.1).
- **For P3's spec revision**, which starts from `main`, so it reads these from this branch until P4 merges:
  - decision 0007, for tqdm;
  - the shared-file rules in this spec's Risks;
  - a requirement change: P3 behaviour 7 loads the reranker in the api only, not the worker, which never searches.

## Next step

Phase 7 is done (ledger). `main` was merged in at `71936b5`, after P2's baseline merged as `cd2106f`.

Next:
1. Claim green on the pushed tip, and see CI green on PR #4.
2. Mark PR #4 ready and merge it with a merge commit.
3. Close this file (steps 13 and 14, the port ledger) from the next branch off `main`, as P2's close rode on this one.
4. Still open: the Supavisor pool size, for the KNOWN-GAPS row on the connection cap. It needs the operator's Supabase dashboard.

## Blockers

None. P4 builds without OpenAI; its live rows (`db:verify-rls` on Supabase, a browser check of the UI) run near the end.

## Steps run differently

- Steps 1 and 2 (PRD and grilling) are covered by the v1 brief and its "Decisions confirmed by grilling". The brief leaves one open question to P4, the login method, which the spec revision puts to the operator.
- The branch starts from `main` at `faa149c` (P1 and P2 tooling merged). P2's baseline lands on `main` separately, from `p2-baseline`; P4 touches no evaluation file.
- Phase 7, the browser:
  - The Claude extension was not connected, so the operator ran the walkthrough.
  - The operator also asked for a better design. `1921145` restyles the screens: ink-blue type, a highlighter that marks only citation markers and their passages, a system serif for answers and passages, and Ask as the main column with Documents in a rail. No dependency was added.
  - It was checked with headless Edge screenshots against fixture API replies, in light, dark and at phone width. No backend was involved and nothing was spent.
  - It also fixes the cited passage, which rendered muted: `asChild` concatenated both colour classes.
  - The commits after the branch review, `776809b` and `1921145`, touch only the frontend. They were reviewed separately before the merge (below).

## Verification ledger

| date | branch | sha | suite | result | duration | not covered |
|---|---|---|---|---|---|---|
| 2026-10-11 (by hand, window A) | p4-platform-shell | 47ce731 | `npm run check:all` | PASS | 117 s | hooks 395/395, agent-hooks 7/7, backend 371 passed and 2 skipped, licenses 48/48, spend 123/123. Not covered: Supabase (`db:verify-rls` live, phase 7); CI on Linux; the unpushed tip |
| 2026-10-11 (by hand, window B) | p4-platform-shell | e13614f | `npm run check:all` | PASS | 168 s | hooks 395/395, agent-hooks 7/7, backend 454 passed and 2 skipped, licenses 48/48 (backend only until 5.6), spend 123/123, frontend typecheck, test and build. Not covered: the same as window A, and the frontend tree's licenses (5.6) |
| 2026-10-12 (by hand, after the re-review) | p4-platform-shell | ed8ae0b | `npm run check:all`; `npm run check:compose` | PASS; PASS | 324 s; about 60 s | hooks 395/395, agent-hooks 7/7, backend 706 passed and 2 skipped, licenses 48/48 and 84/84, spend 123/123, frontend 38 tests, typecheck and build. compose: the config pins the image tag, the worker's restart policy and the `.dockerignore` patterns. Redproofs PASS for the restart pin and the IPv4-translated prefix. Not covered: Supabase (phase 7), CI on Linux (unpushed), a browser |
| 2026-10-12 (by hand, after the fix wave) | p4-platform-shell | e1fd29e | `npm run check:all`; `npm run check:compose` | PASS; PASS | 323 s; 42 s | hooks 395/395, agent-hooks 7/7, backend 705 passed and 2 skipped, licenses 48/48 and 84/84, spend 123/123, frontend 38 tests, typecheck and build; compose healthy, UI served, no `.env` in the image, worker running, image 93 MB. Not covered: Supabase (phase 7), CI on Linux (unpushed), a browser |
| 2026-10-11 (by hand, window E2) | p4-platform-shell | a929684 | `npm run check:all` | PASS | 301 s | hooks 395/395, agent-hooks 7/7, backend 675 passed and 2 skipped, licenses 48/48 and 84/84, spend 123/123, frontend 36 tests, typecheck and build. Not covered: the same as window A |
| 2026-10-11 (by hand, window D) | p4-platform-shell | f32f211 | `npm run check:all` | PASS | 192 s | hooks 395/395, agent-hooks 7/7, backend 523 passed and 2 skipped, licenses 48/48 and 84/84, spend 123/123, frontend 36 tests, typecheck and build. Not covered: the same as window A; a real SIGTERM to the worker |
| 2026-10-11 (by hand, window C) | p4-platform-shell | 817e257 | `npm run check:all` | PASS | 173 s | hooks 395/395, agent-hooks 7/7, backend 475 passed and 2 skipped, licenses 48/48 backend and 84/84 frontend, spend 123/123, frontend 18 tests, typecheck and build. Not covered: the same as window A |
| 2026-10-11T17:37:12.521Z | p4-platform-shell | 5e27e799 | `npm run check:all` | PASS | 336.2 s | Supabase (db:migrate, db:verify-rls live: phase 7); check:compose (its own CI job, PASS locally at ed8ae0b); a browser; real OpenAI |
| 2026-10-11 (by hand, CI) | p4-platform-shell | 127cf36 | CI on Linux, PR #4, run 38160474883: the Checks and Compose jobs | PASS | 3m 2s; 57s | Supabase and the browser (phase 7); real OpenAI |
| 2026-10-12T06:08:28.092Z | p4-platform-shell | d79b201f | `npm run check:all` | PASS | 298.3 s | Supabase (db:migrate, db:verify-rls live: phase 7); check:compose (its own CI job; PASS locally on the merge); a browser; real OpenAI |
| 2026-10-12 (by hand, live, phase 7) | p4-platform-shell | d79b201f | `npm run db:migrate` on Supabase's session pooler | PASS | | `alembic current` went from `0001` to `0002_platform (head)`. Not covered: a rollback (downgrade raises by design) |
| 2026-10-12 (by hand, live, phase 7) | p4-platform-shell | d79b201f | `npm run db:verify-rls` on Supabase | PASS | | `ok`: every check holds, so the `SET` grant, `USAGE` on `extensions`, the exact policy (Supabase renders the condition as PG17 does) and the 0-row isolation count are all proven. `idle_in_transaction_session_timeout: 0` (off; the worker sets 10min locally). Not covered: the pooler's client limit |
| 2026-10-12 (by hand, live, phase 7) | p4-platform-shell | d79b201f | `npm run paid:smoke` (and `--dry-run`) on Supabase and OpenAI, approved at the ask; `scratch/smoke.log` | PASS | | Preflight ok at `0002_platform`, including `verify_rls`. The upload processed into 2 chunks through `workspace_session` as `loreos_app`. The answerable question was cited `[1]`, the unanswerable one refused, and the workspace deleted. Cost under $0.01. Not covered: the worker, the UI |
| 2026-10-12 (by hand, live, phase 7) | p4-platform-shell | cb4bbf5b, then 1921145 | `docker compose up -d --build --wait` on Supabase, approved at the ask | PASS | | Both times: `migrate` exited 0, the api healthy, the worker running. Stopped afterwards with `docker compose stop` |
| 2026-10-12 (by hand, live, phase 7) | p4-platform-shell | 776809b | The browser walkthrough at `http://localhost:8000`, by the operator | FAIL | | Switching workspace stacked each visited workspace's Documents and Ask instead of replacing them: the two siblings shared one React key. Fixed in `776809b`: red first (4 headings, not 1), redproof PASS |
| 2026-10-12 (by hand, live, phase 7) | p4-platform-shell | 1921145 | The browser walkthrough at `http://localhost:8000`, by the operator, after the fix and the design pass | PASS | | The operator signed up the first account; a PDF and a URL reached Ready; a cited answer, with the passage opened by keyboard and closed with Escape; an API key created and revoked; an invite link created. Not covered by hand: accepting an invite in a private window (backend and frontend tests cover it); a screenshot from the operator's browser |
| 2026-10-12 (by hand, phase 7) | p4-platform-shell | 1921145 | `docker system df`; free disk | recorded | | Images 2.141 GB (the LoreOS image is 93 MB), build cache 1.915 GB, volumes 122.9 MB. Free on C: 16 GB of 119 GB. Not recorded: the Supavisor pool size, which needs the operator's Supabase dashboard |
| 2026-10-12T06:51:00.367Z | p4-platform-shell | 3f572fd1 | `npm run check:all` | PASS | 300.9 s | Supabase and the browser (phase 7 rows, by hand); check:compose (its own CI job); real OpenAI |
| 2026-10-12T06:58:03.558Z | p4-platform-shell | 1042bf5d | `npm run check:all` | PASS | 294.0 s | Supabase and the browser (phase 7 rows, by hand); check:compose (its own CI job); real OpenAI |

## Port ledger

| Branch | Status | Reference |
|---|---|---|
| main | required | |
