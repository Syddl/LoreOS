# Review: p5-readme-demo plan (plan lens)

## First review, of `14651af`

Reviewer: harness:reviewer, with fresh context and a read-only shell.

### Executed

```
npm run check:all at 14651af: check:hooks 395/395 · check:agent-hooks 7/7 · check:backend 798 passed in 283.97s ·
check:licenses 67/67 + 84/84 · check:spend 123/123 · check:frontend 39 tests, build ok
```

The reviewer checked the facts against these files, by read-only grep:
- the result files' keys and the `c221b3a3` group;
- `retrieval.py`;
- the glossary in `harness.json`;
- `check-wiring.mjs`;
- `run.py`, `smoke.py` and `ingest.py`;
- 0002's grants;
- the pins in `test_isolation.py` and `test_auth.py`;
- `check-spend.mjs`;
- `Shell.tsx`.

### Findings

**Majors:**
1. **check-wiring.** It never reads `check:all`, and `check:all` is not a CI step. Placed as the plan said, `check:readme` would break the CI order check.
2. **1.1 could not go green with the files it owned.** The tagline uses a glossary word. 1.3's red-first was not real.
3. **1.2 was missing owned files.** `demo.py` needs `SYSTEM_SESSION_FILES` and `ENV_READS_ALLOWED` entries, and a spec row naming its read.
4. **`_ingest(name, corpus)`** looks a workspace up by name or creates one, and has no per-file function. Calling it would ignore `--workspace`.
5. **Glossary matching was undefined.** `org` appears in the required license URLs, and a substring match would hit "forget".
6. **The recording would publish the operator's email**, which the header shows at 640 px and wider.
7. **Group selection was undefined.** One plausible reading refuses on today's files, since the 22688aeb 500/50 file shares hashes and settings with the comparison group.

**Minors:**
- the number format, and `null` with no fixture;
- judge agreement is per file;
- the corpus file count has no source in the result files;
- the redproof could not catch a `buildBlock` mutation;
- the link check had no task;
- the embedding model was not checked before spend;
- "operator-owned" was not checked, and the `eval-` prefix has another owner;
- `npm_config_dry_run` would be refused;
- the redproof needs an empty workspace;
- the number rule was narrowed without a decision.

**Nits:**
- the owned files overlap;
- the spend-guard row's trigger has fired;
- a missing file and a wrong hash both need tests;
- `--workspace` is npm's own option.

### Verdict

Fix then re-review.

### Does NOT prove

- **check-wiring** was not executed; its result is reasoned from its source.
- **Not run:** paid commands, the browser and CI.

## Re-review, of `cd51ec5`

Reviewer: harness:reviewer, with fresh context and a read-only shell. `npm run check:all` at `cd51ec5` was green (798 backend tests).

**All seven majors are resolved.**
- **check-wiring:** the order check passes with the plan's placement.
- **The group selection** picks `c221b3a3` over all seven files: P2's baseline and the sweep files form incomplete groups of their own.
- **The glossary rule** passes the license URLs and fails "organization's".
- **The owner check** works under `system_session`, and the model listing is right.

**Findings:**
- **Minors:**
  - the duplicate rule's scope, so that an old duplicate does not block the README forever;
  - plurals and line-wrapped phrases;
  - an empty glossary should fail closed;
  - the loader should reuse `_check_models`, with its two branches, rather than repeat it;
  - decision 0011 needs the operator's approval.
- **Nits:**
  - the `eval-*` fixture needs an owner;
  - the spec rows on the duplicate refusal and the links;
  - the `check:all` grep;
  - `--workspace-id` should be parsed as a UUID;
  - CR should be stripped on read.

**Verdict: merge.** The minors are carried into the tasks:
- **In 1.1's drafts:** an old duplicate is ignored, plurals and wrapped phrases fail, and an empty glossary refuses.
- **In 1.2:** it reuses `_check_models`, gives the fixture an owner, and parses the id as a UUID.
- **The operator's approval:** the operator approved decision 0011 on 2026-10-14.
