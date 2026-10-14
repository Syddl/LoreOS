# Review: p5-readme-demo, whole branch (step 9)

Lens: whole branch, with spend and public-release concerns. Reviewer: harness:reviewer, with fresh context and a read-only shell. Range: `ef9617e..a3bbb8c` (PR #9).

## Executed

```
npm run check:all   run 1: 395/395 · 7/7 · check:backend 810 passed in 307.13s · 67/67 + 84/84 · 125/125 · 39 tests, build ok · check:readme 29/29
npm run check:all   run 2: the same, check:backend 810 passed in 323.82s
```

**The table**, compared by hand against the three `c221b3a3` result files: every cell and the caption match. The default marker matches `retrieval.DEFAULT_MODE`.

**The README against the code** matches:
- the config table, against `.env.example` and `settings.py`;
- the curl paths, headers and bodies, and the answer's JSON;
- every "How it works" step;
- Features and Contributing.

**The rest:**
- **Prose:** no quality, latency or cost number (decision 0011), no em-dash, and no glossary word outside a URL.
- **Links:** all 15 relative links resolve.
- **Mermaid:** the syntax is valid.
- **Secrets:** none in the tracked files or in the history scan.
- **Commit messages:** no AI attribution.

## Findings

| Severity | Where | Impact | Fix | Owner |
|---|---|---|---|---|
| minor | README, Security | "Report a vulnerability" appears only once private vulnerability reporting is turned on in the repo settings. | Turn it on before going public. | operator |
| minor | `check-readme.mjs` fixtures | Every mode carried the same metrics, so a row filled from another mode's file would pass. | Use different values per mode, and assert a literal line per row. | main session |
| minor | `check-readme.mjs` fixtures | Only a mixed SHA had a refusal case, none for the calibration hash or the settings. | Add both. | main session |
| minor | `test_demo.py` | No test made a file fail. Behaviour 5 says the run reports it, goes on, and exits 1. | Add the test. | main session |
| nit | README, Without Docker | It did not say each command needs its own terminal, or which address to open. | Say both. | main session |
| nit | README, API | Only an owner can create a key. | Say "a workspace owner". | main session |
| nit | README, Demo | The demo needs uv. | Say so. | main session |
| nit | README, Development | The api and the worker spend too, not only `paid:` scripts. | Reword. | main session |
| nit | README, License | The calibration rows and the result files quote CC BY-SA 4.0 passages. | Add a bullet. | main session |
| nit | `readme-table.mjs` | The marker reads `DEFAULT_MODE` only, not `DEFAULT_RERANK`. | Optional. `test_config.py` pins the default to `on`. | main session |
| nit | older docs on main | Several tracked docs hold absolute machine paths with the operator's Windows user name. | The operator's call. | operator |

## Verdict

Merge.

## Does NOT prove

- **Not run:** paid commands, `check:compose` and CI on Linux.
- **Not run, only traced:** the curl examples, against the routes.
- **Not rendered:** the Mermaid diagram.
- **Not checked:** the repo's settings.

## Fix wave

The main session fixed every main-session minor and nit except the optional `DEFAULT_RERANK` marker, in the commit that records this file. STATUS has the redproofs. The two operator items are in the PR's notes.
