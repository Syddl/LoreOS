# Review: p1-thin-slice third fix wave re-review

Lens: security re-review of `91f3af1` (fix(guard): match paid commands at word boundaries, exempt only smoke)
Reviewer: reviewer subagent, fresh context, read-only shell. An automated commit security review of the same commit reported two allowlist semantic escapes and one parser differential, without details.

## Executed

```
npm run check:spend -> 73/73
npm run check:hooks -> 395/395
npm run check:all   -> hooks 395/395, agent-hooks 7/7, backend 74 passed, licenses 40/40, spend 73/73
```

## Findings

| Severity | Where | Impact | Fix | Response |
|---|---|---|---|---|
| minor | `.claude/harness.json` module pattern | `python -c "from loreos import smoke; smoke.cli([])"` and one-liners calling answering, ingest or llm unasked | Interpreter plus loreos plus a paid module name | Fixed: any Python interpreter or uv command mentioning loreos and smoke, evaluation, demo, answering, ingest or llm asks |
| minor | `.claude/harness.json` npm pattern | `node ...\npm-cli.js run paid:smoke` unasked | `npm[\w.-]*` | Fixed |
| minor | `package.json` | The exemption assumes paid:smoke runs loreos.smoke; nothing pinned it | Pin the script body | Fixed: check-spend asserts it (mutation-proven) |
| minor | `.claude/harness.json` HTTP pattern | httpie alternative matched prose (`http 413 for /api/documents`) | Require a URL argument | Fixed |
| minor | `.claude/harness.json` module pattern | `uvx ruff check backend/loreos/smoke.py` asks | Narrow, or accept | Accepted as fail-closed; fixture records it |
| nit | `scripts/check-spend.mjs` header | Stale description | Update | Fixed |

Automated findings, read as the likely classes since no details came with them:

- Allowlist escape: text around a free form changes what runs. `npm --script-shell=x run paid:smoke -- --dry-run`, `python -c "<code>" -m loreos.smoke --dry-run`, and runners that pass `--` differently. Fixed: the only exemption is the whole subcommand `npm run paid:smoke -- --dry-run|--help`.
- Parser differential: curl reads `:08000` as port 8000. Fixed with `:0*8000`. PowerShell backtick escapes inside a name are deliberate obfuscation, and now have their own KNOWN-GAPS entry.

The new fixtures ran red against `91f3af1` first (11), then green: `check:spend` 87/87, including the script-body pin.

## Verdict

merge (the reviewer's verdict on `91f3af1`; no blocker or major). The minors and the automated findings are fixed in the next commit.

## Does NOT prove

How pnpm, yarn and bun pass `--` was taken from documentation, not run here. Since their free forms now ask, it no longer matters. `paid:smoke`, `db:migrate` and `dev:api` were not run.
