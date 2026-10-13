---
status: open
feature: p3-hybrid-search
---

# Status: p3-hybrid-search

The single carrier of state between sessions. Update it before a session ends; the session-start hook injects the open lines. Status is one of open, blocked, done.

## Open tasks

- Steps 1 and 2, PRD and grilling: covered by [the v1 brief](../v1/brief.md), decisions 4, 7, 8, 9 and 11, which the operator confirmed before P1.
- Step 3, spec revised against P1, P2 and P4: done (2026-10-14). The changes are in `spec.md`, section "Revised against P1, P2 and P4".
  - **Free probes behind it:**
    - fastembed 0.9.0 and onnxruntime 1.31.0 resolve for Python 3.14 on Windows and on manylinux.
    - fastembed lists 8 cross-encoders, with their licenses.
    - Two models were timed on 30 passages on the dev machine: `ms-marco-MiniLM-L-6-v2` took 2.3 to 2.7 s, and `jina-reranker-v1-turbo-en` took 3.1 s.
    - fastembed cuts both at 512 tokens.
  - **Engineering calls, for the operator to veto:**
    - the reranker model, `Xenova/ms-marco-MiniLM-L-6-v2`;
    - the default-mode rule in behaviour 9: a slower mode must win on Recall@5 or MRR@10 without losing on the other;
    - the tie rule for chunk size: when both metrics tie, the smaller chunk wins.
- Step 4, plan: done (2026-10-14), `plan.md`. It has two build phases (window A: 1.1 to 1.3; window B: 2.1, then 2.2), the paid measurement in phase 3, then review. The main session implements the tasks.
- Step 5, plan review by execution, recorded in [reviews/plan.md](reviews/plan.md):
  - **First review** of `c9f6cae`: "fix then re-review", with 1 blocker, 2 majors, 12 minors and 6 nits. `check:all` was green, with 712 backend tests. The blocker: an untracked result dirtied the tree, so `--mode all` could commit only one of its three files.
  - **Revision** `840abe1` answers each finding, mapped in the plan's last section.
  - **Re-review** of `840abe1`: **merge**. Its 5 minors and 5 nits are folded in. Step 5 is done.
- Step 6, implementation: next, task 1.1.

## Next step

Task 1.1: migration `0003_keyword_search` and `keyword_search`, red first.

## Blockers

None. Building the code costs nothing. The four paid runs (the chunk sweep, then `--mode all`) each ask, with a priced estimate, under the $5 cap of decision 0005.

## Verification ledger

| date | branch | sha | suite | result | duration | not covered |
|---|---|---|---|---|---|---|

## Port ledger

| Branch | Status | Reference |
|---|---|---|
| main | required | |
