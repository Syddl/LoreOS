# Known gaps

Gaps accepted for now. A row leaves this table when its fix merges (link the PR or the decision) or when a decision rejects it.

| Gap | Impact | Owner | Trigger to fix |
|---|---|---|---|
| No frontend code or checks yet | A green suite says nothing about the UI or widget | frontend | P4 adds the first frontend checks to `check:all` and CI |
| An upload sent chunked, with no Content-Length, is received and spooled to a temp file in full before the 413; a declared length over 20 MB is refused first | A local client can fill the temp disk; nothing is stored or spent, and other sites' pages are refused earlier by the Origin check | backend | P4 serves the API beyond 127.0.0.1 |
| The spend guard matches command text: it asks for `paid:*` in any runner and under any runner file name (npm and its abbreviations, pnpm, yarn, bun, node --run, npm-cli.js, a quoted path, any flags), a Python interpreter or uv whose command mentions loreos and a paid module (including a `-c` one-liner), and curl, wget, httpie or Invoke-RestMethod/WebRequest naming `/api` or port 8000, also inside quotes, blocks, pipelines, `$(...)`, `bash -c`, `cmd /c` and `pwsh -c`. No form is exempt, `--dry-run` included. Not asked: a one-liner that posts with its own HTTP library (Python, Node) without naming a loreos module, a script file, a URL, port or script name held in a variable, the dev API on another port with an encoded path, PowerShell backtick escapes inside a name (``pa`id``), `Start-Process`, and `eval` of built-up text. | An unapproved post to the running dev API bills one embedding batch per upload or one embedding plus one answer per question, a fraction of a cent each | backend | A new paid route or entry module, or a session that spends through one of these spellings |
| Evaluation workspaces (`eval-<key>`) are never pruned: each new key (a chunker, chunk-size, corpus or embedding-model change) leaves the old workspace, about 10 MB of documents, chunks and vectors | Database space on Supabase grows with every P3 configuration tried | backend | The database nears its plan's size limit, or P3 starts sweeping chunk sizes |
| Hugo shortcodes in the handbook corpus (`{{% panel %}}`, `{{% details %}}`, `{{< youtube >}}`) stay in chunk text, and text after a closing `details` stays under the heading inside it | Noise in embeddings and in keyword search, as for a user who uploads the same files | backend | P3's keyword search, if shortcode tokens show up among false hits |
| `ANSWER_MODEL` defaults to `gpt-5.4-mini`, a previous generation; its sibling `gpt-5.4-nano` is deprecated | A future deprecation breaks answers until the default changes; every result file records the model it used | backend | OpenAI announces a deprecation date for `gpt-5.4-mini`, or a change to the answer model is weighed in an evaluation |
| `eval/results/` is protected from the edit tools only. A shell copy can still place a scratch result there | A hand-placed result could be committed. `check:backend` fails on a committed result whose `destination` is not `results` or whose judge agreement is null, which catches a copied scratch file but not a forged one | backend | A result file is committed that the run did not write |
| Codex adapter installed, but its hooks are not yet trusted in the Codex CLI | Codex sessions run unguarded until trusted through `/hooks` | operator | The first Codex session in this repo |

Rules for this table:

- One row per gap. Facts, not narrative. No dates in a row; the git log has them.
- A gap with a fix in flight points at `docs/sdd/<feature>/STATUS.md`, not at a branch name.
- A security gap names the surface and the precondition under which it is exploitable.
- A gap that costs money when hit says how much per occurrence.
