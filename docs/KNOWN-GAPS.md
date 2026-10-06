# Known gaps

Gaps accepted for now. A row leaves this table when its fix merges (link the PR or the decision) or when a decision rejects it.

| Gap | Impact | Owner | Trigger to fix |
|---|---|---|---|
| No frontend code or checks yet | A green suite says nothing about the UI or widget | frontend | P4 adds the first frontend checks to `check:all` and CI |
| An upload sent chunked, with no Content-Length, is received and spooled to a temp file in full before the 413; a declared length over 20 MB is refused first | A local client can fill the temp disk; nothing is stored or spent, and other sites' pages are refused earlier by the Origin check | backend | P4 serves the API beyond 127.0.0.1 |
| The spend guard matches command text: it asks for `paid:*` (any npm flags, run-script, npm.cmd), an interpreter running `loreos.<smoke\|evaluation\|demo>`, and curl, wget, httpie or Invoke-RestMethod/WebRequest naming `/api/ask` or `/api/documents`. A Python or Node one-liner that posts, a script file, a URL held in a variable, `Start-Process`, and `eval` or `bash -c` are not asked. | An unapproved post to the running dev API bills one embedding batch per upload or one embedding plus one answer per question, a fraction of a cent each | backend | A new paid route or entry module, or a session that spends through one of these spellings |
| Codex adapter installed, but its hooks are not yet trusted in the Codex CLI | Codex sessions run unguarded until trusted through `/hooks` | operator | The first Codex session in this repo |

Rules for this table:

- One row per gap. Facts, not narrative. No dates in a row; the git log has them.
- A gap with a fix in flight points at `docs/sdd/<feature>/STATUS.md`, not at a branch name.
- A security gap names the surface and the precondition under which it is exploitable.
- A gap that costs money when hit says how much per occurrence.
