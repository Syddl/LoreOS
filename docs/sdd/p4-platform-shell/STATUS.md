---
status: open
feature: p4-platform-shell
---

# Status: p4-platform-shell

The single carrier of state between sessions. Update it before a session ends; the session-start hook injects the open lines. Status is one of open, blocked, done.

## Open tasks

- Step 3, spec revised against P1 and P2: in progress. An audit of the draft spec against the merged code is running. Its findings become a "Revised against P1 and P2" section in `spec.md`, and the operator's decisions go into it.
- Step 4, plan: after the spec revision.
- Step 5, plan review by execution: after the plan.

## Next step

Fold the audit's findings into `spec.md` (section "Revised against P1 and P2"), put the open decisions to the operator, then write `plan.md`.

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
