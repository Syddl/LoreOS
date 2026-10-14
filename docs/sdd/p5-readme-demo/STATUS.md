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

- **Phase 2, live:**
  - **The demo load is done.** The operator created the "Demo" workspace in the UI. Its id is kept out of this file, since the repo goes public.
    - **The dry run** passed every preflight step: 48 files and 195,274 tokens to embed.
    - **The paid load** processed all 48 files, at about $0.004.
    - **The second run** found 48 of 48 files present and planned 0 files and 0 tokens, so it spent nothing.
    - Logs: `scratch/demo-dry.log`, `scratch/demo-load.log` and `scratch/demo-load-2.log`.
  - **The README was rewritten for a public repo** (`81c657b`), at the operator's request. It gained:
    - badges and a feature list;
    - a Mermaid diagram of ingest and ask;
    - a contributing and a security section.

    `check:readme` passes, 29 of 29.
  - **The pre-publication scan**, read-only: the tracked files and the whole git history hold no API key, password, connection string, Supabase host or `.env`. Commit metadata carries the operator's personal email, and the operator was told.
  - **The recording is open.** The Claude in Chrome extension was not connected, and the operator chose to connect it.

- **Steps 9 to 12:**
  - **[PR #9](https://github.com/Syddl/LoreOS/pull/9)** is open. CI on `a3bbb8c` passed both jobs, Checks and Compose.
  - **The independent whole-branch review** ([reviews/branch.md](reviews/branch.md)) returned **merge**. It ran `check:all` twice, both green (810 backend tests), and compared every cell of the table with the result files by hand.
  - **The fix wave** `25ba051`, with redproofs PASS:
    - **The check-readme fixtures** carry different values per mode, with a literal line for every row (a row filled from the first file goes red). They add refusal cases for mixed calibration rows and mixed settings. 32 checks.
    - **`test_demo.py`** gains a failing-file case: the run goes on, and exits 1 (dropping the count goes red).
    - **The README:** an owner creates keys; the demo needs uv; the api and the worker also spend; the dev steps need their own terminals; and a bullet on the CC BY-SA excerpts.
  - **Left to the operator:** turning on private vulnerability reporting before going public, and whether to scrub machine paths from older docs.

## Next step

claim-green on the fix wave's tip, and CI on PR #9. Then the operator merges. The recording follows in its own PR, once the browser extension connects.

## Blockers

The recording waits on the browser extension.

## Verification ledger

| date | branch | sha | suite | result | duration | not covered |
|---|---|---|---|---|---|---|
| 2026-10-14T14:45:00.607Z | p5-readme-demo | 6db4b7dc | `npm run check:all` | PASS | 348.1 s | the live demo load (paid) and the recording; check:compose (its own CI job); CI on Linux |
| 2026-10-14 (by hand, live) | p5-readme-demo | 9e9160d | `npm run paid:demo-load -- --workspace-id <Demo> --dry-run`, then the paid run, then the run again, each approved at the ask | PASS | | The dry run planned 48 files and 195,274 tokens. The load processed 48 of 48, about $0.004. The second run planned 0 files and 0 tokens. Not covered: the UI showing them (the recording) |
| 2026-10-14T15:07:38.973Z | p5-readme-demo | 4e90430b | `npm run check:all` | PASS | 379.8 s | the recording (waits on the browser extension); check:compose (its own CI job); CI on Linux |

## Port ledger

| Branch | Status | Reference |
|---|---|---|
| main | required | |
