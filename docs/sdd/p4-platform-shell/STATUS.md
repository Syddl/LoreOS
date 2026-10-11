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

Window D:
- **Tasks:** 3.3 (the worker), plus 5.3, 5.4 and 5.5 (the Documents, Ask and Settings screens). Each goes to an implementer in its own worktree.
- **Redproofs the main session runs itself:** 3.3's, because `worker.py` and `llm.py` match the spend pattern.

## Blockers

None. P4 builds without OpenAI; its live rows (`db:verify-rls` on Supabase, a browser check of the UI) run near the end.

## Steps run differently

- Steps 1 and 2 (PRD and grilling) are covered by the v1 brief and its "Decisions confirmed by grilling". The brief leaves one open question to P4, the login method, which the spec revision puts to the operator.
- The branch starts from `main` at `faa149c` (P1 and P2 tooling merged). P2's baseline lands on `main` separately, from `p2-baseline`; P4 touches no evaluation file.

## Verification ledger

| date | branch | sha | suite | result | duration | not covered |
|---|---|---|---|---|---|---|
| 2026-10-11 (by hand, window A) | p4-platform-shell | 47ce731 | `npm run check:all` | PASS | 117 s | hooks 395/395, agent-hooks 7/7, backend 371 passed and 2 skipped, licenses 48/48, spend 123/123. Not covered: Supabase (`db:verify-rls` live, phase 7); CI on Linux; the unpushed tip |
| 2026-10-11 (by hand, window B) | p4-platform-shell | e13614f | `npm run check:all` | PASS | 168 s | hooks 395/395, agent-hooks 7/7, backend 454 passed and 2 skipped, licenses 48/48 (backend only until 5.6), spend 123/123, frontend typecheck, test and build. Not covered: the same as window A, and the frontend tree's licenses (5.6) |
| 2026-10-11 (by hand, window C) | p4-platform-shell | 817e257 | `npm run check:all` | PASS | 173 s | hooks 395/395, agent-hooks 7/7, backend 475 passed and 2 skipped, licenses 48/48 backend and 84/84 frontend, spend 123/123, frontend 18 tests, typecheck and build. Not covered: the same as window A |

## Port ledger

| Branch | Status | Reference |
|---|---|---|
| main | required | |
