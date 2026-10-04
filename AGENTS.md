# LoreOS

Read docs/sdd/v1/brief.md before any change: it holds the confirmed decisions and what v1 leaves out.

- Backend: Python, FastAPI, uv. Frontend and widget: TypeScript (strict), React, Vite.
- The database is any Postgres with pgvector, reached only through `DATABASE_URL`. No Supabase SDK, Auth or Storage.
- Call it "keyword search", never BM25.
- Never put a number in the README that a committed evaluation result file under `eval/results/` did not produce. Those files are written by the evaluation run, never by hand.
- No dependency under AGPL or another copyleft license.
- Every command that calls OpenAI is a root package.json script named `paid:<name>`; the guard asks before it runs. Never call OpenAI from a check, a test or a loop.
- No AI attribution anywhere: no Co-Authored-By trailers, no "Generated with" footers.

# Project harness

Read the project's README and architecture decisions before changes.
Project facts live in .harness/config.json when present, otherwise .claude/harness.json.
Use the checks, branches, spend, protected_paths, deploy, evidence and artifacts entries there.

Run the declared checks before claiming success. A partial run proves only what it exercises.
Preserve existing tests and prove fixes with the named failing assertion.
Stage explicit paths; inspect git diff --cached --name-only before committing.
Never force-push or hard-reset shared history.

For billable work, run cheap preflight first and obtain approval through a supported mechanism.
A blocked hook is not approval. On agents without hook-level approval, the action stays blocked;
the operator must use a separate supported mechanism. Do not bypass or respell the command.
Record work under the configured artifacts root and keep decisions in docs/decisions.

Size the process to the change with the Sizing table in the harness library's docs/LIFECYCLE.md.
Use the installed harness skills for their matching tasks. Resolve library references from the actual
skill's directory (follow a link to its real target); from the directory containing SKILL.md, go up two directories to reach the library root.
Reviewer restrictions come from the agent adapter. Report checks a reviewer cannot execute.
