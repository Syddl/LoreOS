# Plan: p5-readme-demo

Implements [spec.md](spec.md), as revised against P1 to P4.

**Sizing.** P5 adds a spend surface (`paid:demo-load`), so all fourteen lifecycle steps run, each kept small, and step 9 is by an independent reviewer. The main session implements, red first, and runs each redproof after its task's commit.

## Facts read before planning

- **The result files** are in `eval/results/`: P2's baseline, P3's chunk sweep at `22688aeb`, and the comparison at `c221b3a3`. The comparison has one file per mode, and the three share SHA, corpus, questions and calibration hashes, `settings` and `destination: results`. No other complete three-mode group exists.
  - The `settings` keys: `embedding_model`, `answer_model`, `judge_model`, `chunk_tokens`, `chunk_overlap`, `k`, `search_k`, `rrf_k`, `fuse_depth`, `rerank_depth`, `rerank_model` and `openai_base_url_host`.
  - The metrics keys: `recall_at_5`, `mrr_at_10`, `citation_accuracy`, `unanswerable_refused`, `answerable_refused`, `faithfulness` and `judge_agreement`.
  - `latency_ms` holds `search_p50` and `search_p95`; `counts` holds `questions` and `answerable`.
- **`DEFAULT_MODE`** is the line `DEFAULT_MODE = "hybrid_rerank"  # decision 0010, …` in `backend/loreos/retrieval.py`.
- **The glossary:** `.claude/harness.json` `glossary`. Each term is an object with `avoid: [...]`, and the object's `_why` key is a note, not a term.
- **The checks:**
  - **The glob:** `checks.glob` is `scripts/check-*.mjs`, so a new `scripts/check-readme.mjs` needs a `check:readme` script, a CI step in package.json order before `check:all`, and a place in `check:all`. `check-wiring.mjs` verifies all three.
  - **Fixtures:** the existing checks replay their fixture cases inline (`check-spend.mjs`).
- **The loader's pieces:**
  - `evaluation.run._ingest` already ingests a corpus dict inline, file by file, into a workspace. `run.load_corpus`, `fetch.corpus_problems`, `dataset.read_manifest` and `smoke.preflight(reranker=False)` cover the preflight.
  - The guard already asks on `paid:` scripts, and on interpreter commands naming `loreos` and `demo` (`check-spend.mjs` has a `loreos.demo` case).
  - `ingest.ingest` returns a processed duplicate as stored, without embedding.
- **The protected paths:** `.github/workflows/ci.yml` asks on edit; `README.md` and `package.json` do not.

## Tasks

### Task 1.1: the table generator and `check:readme`

- Files owned: `scripts/readme-table.mjs` (new), `scripts/check-readme.mjs` (new), `package.json` (`readme:table`, `check:readme`, and `check:all`), `.github/workflows/ci.yml` (one step), `README.md` (the two markers only).
- Change:
  - **`readme-table.mjs`** exports `findGroup(results)`, `defaultMode(retrievalSource)`, `buildBlock(group, mode)` and `replaceBlock(readme, block)`, each throwing an `Error` with the reason. Run directly, it rewrites the README's block.
  - **`check-readme.mjs`** replays fixture cases against those functions:
    - an edited cell is a difference named in the output;
    - mixed SHAs refuse;
    - a missing mode refuses;
    - a `destination` of `scratch` is excluded;
    - an unreadable `DEFAULT_MODE` refuses;
    - a glossary word fails.

    Then it checks the real README's block and the glossary.
- Acceptance check: `npm run check:readme` passes, and `node <library>/scripts/check-wiring.mjs` passes.
- Red first: with the markers in place and the block empty, `check:readme` fails, showing the expected block.
- Redproof: change `buildBlock`'s MRR@10 cell to read `recall_at_5`. The fixture case and the real-README check must both go red.

### Task 1.2: `paid:demo-load`

- Files owned: `backend/loreos/demo.py` (new), `backend/tests/test_demo.py` (new), `package.json` (`paid:demo-load`).
- Change:
  - **`cli(argv)`** takes `--workspace <uuid>` and `--dry-run`, and refuses `npm_config_*` swallowing as the evaluation does.
  - **The preflight** runs, in order:
    - `smoke.preflight(reranker=False)`;
    - the manifest and the corpus hashes;
    - the workspace exists and its name does not start with `eval-`, read through `system_session`, since the loader has no member;
    - a plan that prints the files and the tokens it will embed, leaving out files already processed there.
  - **Then**, unless it is a dry run, it calls `evaluation.run._ingest`'s per-file loop, once per file, and prints each file's status.
- Acceptance check: `uv --directory backend run python -m pytest tests/test_demo.py` passes, with:
  - a first run that embeds each file once, and a second run that embeds nothing;
  - an unknown workspace, an `eval-*` workspace, and a corpus file with a wrong hash each stop before `llm.embed`;
  - `--dry-run`, which calls no embedding.
- Red first: an import error, and then the named assertions after the commit.
- Redproof: drop the `eval-` refusal. That case must go red.

### Task 1.3: the README and KNOWN-GAPS

- Files owned: `README.md`, `docs/KNOWN-GAPS.md`, `eval/README.md` (a link to the README's results, if needed).
- Change: the spec's sections, in glossary terms, with no quality, latency or cost number in the prose. `npm run readme:table` fills the block. KNOWN-GAPS is reread, and stale rows are corrected.
- Acceptance check: `npm run check:readme` passes. Every relative link in `README.md` points at a file that exists, which the check verifies too.
- Red first: the check fails before the generator fills the block.

### Phase 2: live (main session)

1. **Claim green** on the pushed tip.
2. **The demo load.** The operator creates a workspace named "Demo" in the UI and gives its id. Then `npm run paid:demo-load -- --workspace <id> --dry-run`, the paid run, and the run again, each asking.
3. **The recording.** The operator logs in. The agent records `docs/assets/demo.gif` through the browser extension, asking one or two questions that the operator approved in chat, with a citation open. The README embeds the recording.
4. **Step 9:** the independent whole-branch review, the fix wave, the PR and CI. Merge on the operator's yes.

## What this plan does NOT cover

- **A table for the chunk sweep.** The README links decision 0009 and its files. Trigger: the README needs the sweep's numbers inline.
- **A check that the README's curl paths exist in the app.** That stays a review item. Trigger: the API's paths change.
