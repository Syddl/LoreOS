# Review: p1-thin-slice second fix wave re-review

Lens: security re-review of `fabc8df` (fix(guard): exempt only the exact free forms of a paid entry)
Reviewer: reviewer subagent, fresh context, read-only shell. An automated commit security review of the same commit ran alongside.

## Executed

```
npm run check:spend   -> 57/57 (on a working tree that already held the next fix, so not HEAD's patterns)
npm run check:hooks   -> 395/395
npm run check:backend -> 74 passed (11.18s)
```

## Findings

| Severity | Where | Impact | Fix | Response |
|---|---|---|---|---|
| major | `.claude/harness.json` patterns | Anchoring with `^` dropped spellings the previous patterns asked for: `$out = npm run paid:smoke`, `cmd /c npm ...`, `Measure-Command { ... }`, `% { irm ... }`, `try { irm ... }`, `uv.exe run ...` (the automated review: "control regression") | Boundary class instead of `^`; grep naming a command asks | Fixed: boundary class with quotes; grep and commit messages naming a paid command ask, as the plain pattern always did |
| minor | `.claude/harness.json` patterns | Free forms exempt for any `paid:<name>` and for evaluation and demo, not only smoke (the automated review: "allowlist semantic escape") | Exempt only smoke | Fixed with a lookbehind inside each negative lookahead |
| minor | `docs/KNOWN-GAPS.md` | Row overstated coverage: pnpm, yarn, bun, `node --run`, npm abbreviations, `npm.ps1`, a quoted program path, `pwsh -c`/`powershell -Command`/`cmd /c`, normalised URLs | Catch or list | Caught, each with a fixture; npm's five abbreviations confirmed to run scripts in a scratch package; the HTTP pattern now fails closed on `/api` or port 8000; the row lists only what remains |

Every new fixture ran red against the previous patterns first (11, then 8), then green: `check:spend` 73/73.

## Verdict

fix then re-review. Final re-review: [branch-rereview-3.md](branch-rereview-3.md).

## Does NOT prove

npm.ps1's handling of `--` was observed on this machine only (it passed `--` through). `paid:smoke`, `db:migrate` and `dev:api` were not run.
