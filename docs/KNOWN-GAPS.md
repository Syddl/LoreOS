# Known gaps

Gaps accepted for now. A row leaves this table when its fix merges (link the PR or the decision) or when a decision rejects it.

| Gap | Impact | Owner | Trigger to fix |
|---|---|---|---|
| No product code yet; `check:all` runs only the guard fixtures | A green suite says nothing about LoreOS itself | backend, frontend | P1 adds the first backend and frontend checks to `check:all` and CI |
| The spend guard catches only `npm run paid:*`; a direct `uv run` or `python` call to OpenAI is not asked | An unapproved evaluation or ingest run bills OpenAI | backend | The first script that calls OpenAI (P1) |
| Codex adapter installed, but its hooks are not yet trusted in the Codex CLI | Codex sessions run unguarded until trusted through `/hooks` | operator | The first Codex session in this repo |

Rules for this table:

- One row per gap. Facts, not narrative. No dates in a row; the git log has them.
- A gap with a fix in flight points at `docs/sdd/<feature>/STATUS.md`, not at a branch name.
- A security gap names the surface and the precondition under which it is exploitable.
- A gap that costs money when hit says how much per occurrence.
