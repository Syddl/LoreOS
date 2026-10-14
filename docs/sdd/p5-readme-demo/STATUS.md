---
status: open
feature: p5-readme-demo
---

# Status: p5-readme-demo

The single carrier of state between sessions. Update it before a session ends; the session-start hook injects the open lines. Status is one of open, blocked, done.

## Open tasks

- Steps 1 and 2, PRD and grilling: covered by [the v1 brief](../v1/brief.md), decisions 3 and 11, and its rule that the README table comes only from committed result files.
- Step 3, the spec, revised against P1 to P4: done (2026-10-14). See "Revised against P1 to P4" in `spec.md`.
- Step 4, the plan: done. `plan.md` has 3 tasks and a live phase.
- Step 5, the plan review ([reviews/plan.md](reviews/plan.md)):
  - **First review:** "fix then re-review", with 7 majors (the check-wiring facts, the group selection, the glossary matching, the email in the recording, `_ingest`'s real shape, missing owned files, and 1.1's green), 10 minors and 4 nits.
  - **Revision** `cd51ec5`.
  - **Re-review: merge.** Its 5 minors went into the tasks. The operator approved decision 0011 on 2026-10-14.
- Step 6, implementation, by the main session, each redproof PASS:

  | Task | Commit | What it adds | Proof |
  |---|---|---|---|
  | 1.1 | `35acbd2` | `scripts/readme-table.mjs`, and `scripts/check-readme.mjs` (29 checks: fixture cases, then the real README's block, glossary and links), wired after `check:frontend` and into `check:all`. check-wiring 8/8 | red first on the empty block and on "organization"; redproofs: MRR read from the wrong key, and the `destination` filter dropped |
  | 1.2 | `f20b0e6` | `loreos.demo` and `paid:demo-load` (13 tests), `preflight.check_models(models)` shared with the evaluation, the pins in `test_auth.py` and `test_isolation.py`, and 2 `check-spend` cases | the pins red first; redproofs: the `eval-` refusal and the owner refusal |
  | 1.3 | `a197225` | the README, decision 0011, the AGENTS.md line, KNOWN-GAPS (the spend-guard and shortcode rows), and the `eval/README.md` wording | `check:readme` green; the prose is a review item |

## Next step

Phase 2:
1. claim-green;
2. the operator creates the "Demo" workspace and gives its id;
3. `paid:demo-load`, as a dry run, then the paid run, then the run again;
4. the recording.

## Blockers

None. The live phase needs the operator twice: to create the "Demo" workspace and give its id, and to log in for the recording.

## Verification ledger

| date | branch | sha | suite | result | duration | not covered |
|---|---|---|---|---|---|---|

## Port ledger

| Branch | Status | Reference |
|---|---|---|
| main | required | |
