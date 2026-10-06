# Known gaps

Gaps accepted for now. A row leaves this table when its fix merges (link the PR or the decision) or when a decision rejects it.

| Gap | Impact | Owner | Trigger to fix |
|---|---|---|---|
| No frontend code or checks yet | A green suite says nothing about the UI or widget | frontend | P4 adds the first frontend checks to `check:all` and CI |
| An upload sent chunked, with no Content-Length, is received and spooled to a temp file in full before the 413; a declared length over 20 MB is refused first | A local client can fill the temp disk; nothing is stored or spent, and other sites' pages are refused earlier by the Origin check | backend | P4 serves the API beyond 127.0.0.1 |
| The spend guard matches command text: it asks for `paid:*` in any runner and under any runner file name (npm and its abbreviations, pnpm, yarn, bun, node --run, npm-cli.js, a quoted path, any flags), a Python interpreter or uv whose command mentions loreos and a paid module (including a `-c` one-liner), and curl, wget, httpie or Invoke-RestMethod/WebRequest naming `/api` or port 8000, also inside quotes, blocks, pipelines, `$(...)`, `bash -c`, `cmd /c` and `pwsh -c`. Only the exact `npm run paid:smoke -- --dry-run\|--help` is free. Not asked: a one-liner that posts with its own HTTP library (Python, Node) without naming a loreos module, a script file, a URL, port or script name held in a variable, the dev API on another port with an encoded path, PowerShell backtick escapes inside a name (``pa`id``), `Start-Process`, and `eval` of built-up text. | An unapproved post to the running dev API bills one embedding batch per upload or one embedding plus one answer per question, a fraction of a cent each | backend | A new paid route or entry module, or a session that spends through one of these spellings |
| Codex adapter installed, but its hooks are not yet trusted in the Codex CLI | Codex sessions run unguarded until trusted through `/hooks` | operator | The first Codex session in this repo |

Rules for this table:

- One row per gap. Facts, not narrative. No dates in a row; the git log has them.
- A gap with a fix in flight points at `docs/sdd/<feature>/STATUS.md`, not at a branch name.
- A security gap names the surface and the precondition under which it is exploitable.
- A gap that costs money when hit says how much per occurrence.
