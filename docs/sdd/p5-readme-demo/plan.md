# Plan: p5-readme-demo

Implements [spec.md](spec.md), as revised against P1 to P4. Step 5's first review returned "fix then re-review" ([reviews/plan.md](reviews/plan.md)). This revision answers every finding, and the table at the end maps each one to its change.

**Sizing.** P5 adds a spend surface (`paid:demo-load`), so all fourteen lifecycle steps run, each kept small, and step 9 is by an independent reviewer.

**How the tasks run.** The main session implements, red first, one task at a time, in the order 1.1, 1.2, 1.3. So `package.json` (1.1, then 1.2) and `README.md` (1.1, then 1.3) pass from task to task, never shared at once. Each redproof runs after its task's commit.

## Facts read before planning

- **The result files** are in `eval/results/`: P2's baseline, P3's chunk sweep at `22688aeb`, and the comparison at `c221b3a3`.
  - The comparison has one file per mode, sharing SHA, corpus, questions and calibration hashes, `settings`, `schema` and `destination: results`. Grouped by that exact tuple, no other complete three-mode group exists.
  - The 500/50 sweep file (`22688aeb`) shares the hashes and `settings` with the comparison, but not its SHA.
- **The keys:**
  - `settings`: `embedding_model`, `answer_model`, `judge_model`, `chunk_tokens`, `chunk_overlap`, `k`, `search_k`, `rrf_k`, `fuse_depth`, `rerank_depth`, `rerank_model` and `openai_base_url_host`. P2's baseline has only the first 7 plus the host.
  - The metrics: `recall_at_5`, `mrr_at_10`, `citation_accuracy`, `unanswerable_refused`, `answerable_refused`, `faithfulness` and `judge_agreement`, the last per file.
  - Also `latency_ms.search_p50` and `search_p95`, `counts.questions` and `counts.answerable`, and `created_at`.
- **`DEFAULT_MODE`** is the line `DEFAULT_MODE = "hybrid_rerank"  # decision 0010, …` in `backend/loreos/retrieval.py`.
- **The glossary:** `.claude/harness.json` `glossary`. Each term is an object with `avoid: [...]`, and `_why` is a note, not a term. The words to avoid are "BM25", "lexical BM25", "tenant", "organization", "org", "benchmark" and "test set". `org` also appears in URLs (`creativecommons.org`, `web.archive.org`), which the README's license section must carry.
- **check-wiring** (the harness library's `scripts/check-wiring.mjs`):
  - it requires a `check:<topic>` script for each `scripts/check-*.mjs`;
  - the `check:*` scripts must appear in package.json in the same order as their `npm run check:*` steps in the CI file text;
  - it never reads the `check:all` command, and `check:all` is not a CI step.

  `check:compose` is last in both, in its own CI job. So `check:readme` goes after `check:frontend` and before `check:compose` in package.json, its CI step goes at the end of the `checks` job, and `check:all` gets it by hand.
- **`evaluation.run._ingest(name, corpus)`** finds the oldest workspace with that name, or creates a memberless one, then ingests file by file and stops at the first file not processed. It has no per-file function. The loader therefore writes its own short loop over `ingest.ingest`, keyed by the workspace id: the one-file-at-a-time pattern, without the lookup by name or the stop on the first failure.
- **The other loader pieces:**
  - `run.load_corpus`, `fetch.corpus_problems` (a missing file or a wrong hash) and `dataset.read_manifest`;
  - `smoke.preflight(reranker=False)`, which checks the database, the migration head, the grants and the key, but not which models are listed;
  - `ingest.ingest`, which returns a processed duplicate without embedding;
  - `workspaces.EVAL_PREFIX` owns the `eval-` prefix.
- **The pins `demo.py` touches:**
  - **The workspace read.** `loreos_app` has grants on `documents` and `chunks` only (0002), so the loader reads one `loreos.workspaces` row, and its owners in `memberships`, through `system_session()`. That puts `demo.py` in `test_isolation.py`'s `SYSTEM_SESSION_FILES`, with a spec row naming the read.
  - **The environment reads.** Its `npm_config_*` loop and its `npm_config_dry_run` read go into `test_auth.py`'s `ENV_READS_ALLOWED`.
  - **The flag name.** `--workspace` is npm's own option, so the flag is `--workspace-id`.
- **The UI shows the signed-in email in the header** at the `sm` breakpoint (640 px) and wider (`Shell.tsx`).
- **Protected paths:** `.github/workflows/ci.yml` asks on edit; `README.md`, `package.json` and `AGENTS.md` do not.

## Tasks

### Task 1.1: the table generator and `check:readme`

- Files owned:
  - `scripts/readme-table.mjs` and `scripts/check-readme.mjs` (both new);
  - `package.json` (`readme:table`, `check:readme` after `check:frontend`, and `check:readme` in `check:all`);
  - `.github/workflows/ci.yml` (one step, at the end of the `checks` job);
  - `README.md` (the markers, the filled block, and the tagline, so `check:readme` is green when this task ends).
- Change, in `readme-table.mjs`, which exports pure functions that each throw an `Error` with the reason:
  - **`findGroup(results)`:**
    - it keeps files with `destination === "results"`;
    - it groups them by the exact tuple of `schema`, `git_sha`, `corpus_hash`, `questions_hash`, `calibration_hash` and `settings` (deep-equal through sorted-key JSON);
    - a group is complete when it holds exactly one file per mode; two files of one mode in a tuple refuse, naming both;
    - it returns the complete group with the newest `created_at`, or refuses when there is none.
  - **`defaultMode(retrievalSource)`** reads `DEFAULT_MODE = "<mode>"`, or refuses.
  - **`buildBlock(group, defaultMode)`:**
    - ratios use `toFixed(3)` and milliseconds use `Math.round`; `null` is "n/a", never 0;
    - the caption names the commit, `counts.questions` (and answerable), a link to `eval/corpus.json` without a count, the models, the chunk settings, and the judge agreement with Claude's grades, as one value when all three files agree, or one per mode when they do not;
    - the default row is marked;
    - each result file is linked.
  - **`replaceBlock(readme, block)`** refuses when a marker is missing.
  - **`glossaryProblems(readme, glossary)`:** case-insensitive and whole-word, after removing fenced code blocks, inline code spans, Markdown link targets and bare URLs.
  - **`linkProblems(readme, root)`:** each relative link target must exist.
- Change, in `check-readme.mjs`, which replays fixture cases, then checks the real README:
  - **A golden row:** distinct values per metric (recall 0.111, MRR 0.222, and so on) give a literal expected line, so a mutated `buildBlock` fails it.
  - **The grouping cases:**
    - an edited cell is reported as a difference;
    - mixed SHAs make no complete group, so it refuses;
    - a missing mode refuses;
    - a duplicate mode in the newest tuple refuses, naming both files;
    - a newer single-mode file at another SHA, beside an older complete group, still picks the older group;
    - a `scratch` destination is ignored.
  - **The rendering cases:**
    - a `null` metric renders as "n/a";
    - an unreadable `DEFAULT_MODE` refuses.
  - **The glossary cases:** "Organization" fails, `https://creativecommons.org/...` passes, "forget" passes, and `BM25` inside a code span passes.
  - **The link case:** a missing link target fails, and is named.
- Acceptance check:
  - `npm run check:readme` passes;
  - `node <library>/scripts/check-wiring.mjs` passes;
  - `grep -c "npm run check:readme" package.json` shows it inside `check:all`.
- Red first:
  - with the markers in and the block empty, the real-README check fails, showing the expected block;
  - with the tagline still saying "organization", it fails on the glossary.
- Redproof: in `buildBlock`, read `recall_at_5` for the MRR@10 cell. The golden fixture must go red.
- `check:all` turns green again at the end of this task.

### Task 1.2: `paid:demo-load`

- Files owned:
  - `backend/loreos/demo.py` and `backend/tests/test_demo.py` (both new);
  - `package.json` (`paid:demo-load`);
  - `backend/tests/test_isolation.py` (`"demo.py"` in `SYSTEM_SESSION_FILES`);
  - `backend/tests/test_auth.py` (`("demo.py", "for key in os.environ:")` and `("demo.py", "npm_config_dry_run")` in `ENV_READS_ALLOWED`);
  - `scripts/check-spend.mjs` (a case: `npm run paid:demo-load -- --workspace-id x --dry-run` asks).
- Change:
  - **`cli(argv)`** takes `--workspace-id <uuid>` and `--dry-run`.
    - `npm_config_dry_run=true` means a dry run, as in the evaluation.
    - Only a swallowed `workspace-id` is refused, with the separator form.
    - The usage text says that npm's own `--workspace` is a different option.
  - **The preflight**, each step stopping with its fix:
    - `smoke.preflight(reranker=False)`, with a `RuntimeError` turned into an exit;
    - `settings.embedding_model()` is in the API's model list, read for free;
    - the manifest, and `fetch.corpus_problems`, which covers a missing file and a wrong hash;
    - one `system_session()` read: the workspace exists, its name does not start with `workspaces.EVAL_PREFIX`, and it has at least one owner;
    - the plan: the files and tokens to embed, leaving out files already processed in that workspace.
  - **Then**, unless it is a dry run, a loop over the corpus files, one `workspace_session` and one `ingest.ingest` each. It prints each file's status and exits 1 when any file is not processed. A `ponytail:` note says why it does not reuse `run._ingest`.
- Acceptance check: `uv --directory backend run python -m pytest tests/test_demo.py tests/test_isolation.py tests/test_auth.py` passes, and `npm run check:spend` passes. `test_demo.py` covers:
  - a first run that embeds each file's chunks, and a second run that embeds nothing and adds no document;
  - each of these stops before `llm.embed` with its exit code and message, on an empty workspace: an unknown id, an `eval-*` workspace, a workspace with no owner, a missing corpus file, a wrong hash, and an unlisted embedding model;
  - `--dry-run` and `npm_config_dry_run=true` embed nothing;
  - `npm_config_workspace_id` is refused.
- Red first: the named assertions, after the commit (before it, `demo.py` is missing).
- Redproof: drop the `EVAL_PREFIX` refusal. The `eval-*` case must go red on its exit code and message.

### Task 1.3: the README, KNOWN-GAPS and the number rule

- Files owned:
  - `README.md` (the sections around the block);
  - `docs/KNOWN-GAPS.md`;
  - `docs/decisions/0011-readme-numbers.md` (new) and `AGENTS.md` (the README-number line, pointing at it);
  - `eval/README.md` (a link to the README's results, if needed).
- Change:
  - the spec's sections, in glossary terms, with no quality, latency or cost number in the prose;
  - decision 0011 records how the README-number rule is read: quality, latency and cost numbers come only from result files, while configuration facts come from the code;
  - KNOWN-GAPS is reread. The spend-guard row's trigger names `loreos.demo` as handled, and stale rows are corrected.
- Acceptance check: `npm run check:readme` stays green (glossary and links), plus the review.
- Red first: none automated beyond `check:readme`. Prose is a review item, and the spec says so.

### Phase 2: live (main session)

1. **Claim green** on the pushed tip.
2. **The demo load.**
   - The operator creates a workspace named "Demo" in the UI and gives its id from the address bar (`/w/<id>`).
   - Then `npm run paid:demo-load -- --workspace-id <id> --dry-run`, the paid run, and the run again, each asking. Ledger rows by hand.
3. **The recording.** The operator logs in themselves, and approves the questions and their count in chat.
   - **The viewport** is under 640 px wide, so the header hides the email.
   - **The capture:** the agent records `docs/assets/demo.gif` through the browser extension, with one cited answer and its passage open.
   - **Before staging**, every frame is checked for an email, a key or a workspace id the operator did not approve. If any appears, the frame is cropped or the GIF is recorded again.
   - **The README** embeds the GIF.
4. **Step 9:** the independent whole-branch review, the fix wave, the PR and CI. Merge on the operator's yes.

## What this plan does NOT cover

- **A table for the chunk sweep.** The README links decision 0009 and its files. Trigger: the README needs the sweep's numbers inline.
- **A check that the README's curl paths exist in the app.** That stays a review item. Trigger: the API's paths change.

## Plan review findings and their changes

| Finding (reviews/plan.md, first review) | Change |
|---|---|
| Major: wrong check-wiring facts | Facts restated: `check:readme` goes after `check:frontend` in package.json, its CI step at the end of the `checks` job, and into `check:all` by hand, with a grep as acceptance |
| Major: 1.1 could not go green, and 1.3's red-first was not real | 1.1 owns the markers, the filled block and the tagline, and ends green. 1.3's red-first is stated as a review item |
| Major: missing owned files in 1.2 | 1.2 owns the `test_isolation.py` and `test_auth.py` entries. The spec names the cross-workspace read |
| Major: `_ingest`'s real signature | The facts state it. The loader has its own loop keyed by id, with a `ponytail:` note |
| Major: glossary matching undefined | Case-insensitive and whole-word, after removing code and URLs, with four fixture cases |
| Major: the recording would show the email | A viewport under 640 px, and a frame check before staging |
| Major: group selection undefined | Grouping by the exact tuple, exactly one file per mode, a duplicate refuses, the newest by `created_at`, with two fixture cases |
| Minor: number format and null | `toFixed(3)` and `Math.round`, and "n/a" for null, with a fixture |
| Minor: judge agreement per file | One value when the files agree, else one per mode |
| Minor: corpus file count | A link to `eval/corpus.json`, with no count |
| Minor: the redproof could not catch a `buildBlock` mutation | A golden fixture with distinct values |
| Minor: the link check had no home | It moves into 1.1, with a fixture |
| Minor: fail before spend for the embedding model | The preflight checks that the model is listed, and turns a `RuntimeError` into an exit |
| Minor: operator-owned not checked; the prefix's owner | It requires an owner, and uses `workspaces.EVAL_PREFIX` |
| Minor: `npm_config_dry_run` | It is honoured as a dry run; only `workspace-id` is refused |
| Minor: the redproof needed an empty workspace | The refusal cases run on empty workspaces and assert the exit code and message |
| Minor: the number rule narrowed without a decision | Decision 0011, and the AGENTS.md line, in 1.3 |
| Nit: overlapping owned files | Stated as sequential |
| Nit: the spend-guard row's trigger | 1.3 updates the row, and 1.2 adds a `check-spend` case |
| Nit: missing file against wrong hash | Both are tested |
| Nit: `--workspace` is npm's | Renamed `--workspace-id` |
