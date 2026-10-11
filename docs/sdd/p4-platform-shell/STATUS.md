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
    - the worker checks the grants at startup, a stop releases its claim, and `MAX_CONNECTIONS` is 10.
  - The fifth, verifying the live rows early against a throwaway Supabase project, is left to the operator. The default is the merge window.
- Step 5, plan review by execution: next, by an independent reviewer.
- P3 needs decision 0007 (tqdm) and the shared-file rules in the spec's Risks. P3 starts from `main`, so it reads them from this branch until P4 merges.

## Next step

Step 5: an independent reviewer reviews `plan.md` by execution, running the checks it names against this tree, and writes `reviews/plan.md`.

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
