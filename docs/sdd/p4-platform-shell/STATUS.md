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
- Step 6, implementation: next. The start window runs 1.1, then 1.2, both in the main session.
- **For P3's spec revision**, which starts from `main`, so it reads these from this branch until P4 merges:
  - decision 0007, for tqdm;
  - the shared-file rules in this spec's Risks;
  - a requirement change: P3 behaviour 7 loads the reranker in the api only, not the worker, which never searches.

## Next step

Task 1.1 (main session): `uv --directory backend add argon2-cffi python-docx beautifulsoup4 httpx2 httpcore2`, then `settings.allowed_hosts()` and `startup_problems()`, the `ALLOWED_HOSTS` line in `.env.example` and `test_config.py`. Red first. `uv.lock` and `.env.example` ask the operator.

## Blockers

None. P4 builds without OpenAI; its live rows (`db:verify-rls` on Supabase, a browser check of the UI) run near the end.

## Steps run differently

- Steps 1 and 2 (PRD and grilling) are covered by the v1 brief and its "Decisions confirmed by grilling". The brief leaves one open question to P4, the login method, which the spec revision puts to the operator.
- The branch starts from `main` at `faa149c` (P1 and P2 tooling merged). P2's baseline lands on `main` separately, from `p2-baseline`; P4 touches no evaluation file.

## Verification ledger

| date | branch | sha | suite | result | duration | not covered |
|---|---|---|---|---|---|---|

## Port ledger

| Branch | Status | Reference |
|---|---|---|
| main | required | |
