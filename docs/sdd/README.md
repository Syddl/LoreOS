Feature work lives in one folder per feature, `docs/sdd/<feature>/`, holding the lifecycle artifacts (brief, spec, plan, tasks/, reviews/, measurement.md, pr-body.md); the chain and the templates are the harness library's LIFECYCLE doc and `templates/sdd/`.
`STATUS.md` in that folder is the only carrier of state between sessions: open tasks, next step, blockers, the verification ledger and the port ledger; a feature is done when its status is `done` and no ledger row is open.
Scratch output (review diffs, snapshots, logs) goes under `docs/sdd/<feature>/scratch/`, which git ignores.
