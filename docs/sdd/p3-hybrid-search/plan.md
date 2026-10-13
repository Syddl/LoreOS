# Plan: p3-hybrid-search

Implements [spec.md](spec.md), as revised against P1, P2 and P4. Step 5's first review returned "fix then re-review" ([reviews/plan.md](reviews/plan.md)). This revision answers every finding, and the table at the end maps each one to its change.

**Sizing.** P3 is a multi-task feature with a data migration and a spend surface. So all fourteen lifecycle steps run, and step 9 is by an independent reviewer.

**Implementation.** The main session implements the tasks itself, red first (LIFECYCLE step 6, "the main session for small work"). The reasons:
- each task is under about 200 lines;
- five of them touch protected paths, whose edit asks cannot be answered from a subagent: the migration, `uv.lock`, `ci.yml`, `.env.example` and the `Dockerfile`.

Each task's `redproof` runs after the task's commit, because redproof refuses a dirty tree and an untracked target. A reviewer subagent reviews each phase (step 7).

## Facts read before planning

- **retrieval.py** has `search(session, workspace_id, query, k)`: an exact cosine scan with `limit k`. It returns nothing, and buys no embedding, when the workspace has no chunks (`HAS_CHUNKS`). `Hit` carries `score`.
- **The import graph.** `ingest.py` imports `vector_literal` from `retrieval`. Both `routes/documents.py` and `evaluation/run.py` load `answering` first, which loads `retrieval`. So a module-level `retrieval` → `rerank` → `ingest` import is a cycle.
- **answering.py**: `answer()` calls `search(..., TOP_K)`, then `answer_from_hits(question, hits)`. `Answer` has four fields, and the ask route maps every one into the JSON (`routes/documents.py`, `ask`), with `text` renamed `answer`. `test_answering.py` and `evaluation/run.py` call `answer_from_hits` with two arguments; `run.py` also builds `Answer(...)` with four.
- **chunking.py**: `chunk(sections, max_tokens=CHUNK_TOKENS, overlap_tokens=CHUNK_OVERLAP)`. The defaults bind when Python defines the function, so assigning `chunking.CHUNK_TOKENS` later changes nothing in `ingest.run_stages`, which calls `chunking.chunk(sections)`. `test_chunking.py::test_defaults` pins 500 and 50.
- **evaluation.**
  - These read `chunking.CHUNK_TOKENS` and `CHUNK_OVERLAP` when they run: `run.workspace_name` (the key, which also hashes the source of `parsing.py`, `chunking.py` and `ingest.py`), `preflight._print_plan`, and the result's `settings`.
  - `run.MODES = ("vector",)`. `run._ask` times `retrieval.search(..., SEARCH_K)` as `search_ms`, then answers from the first `TOP_K` hits. `__main__.cli` runs the preflight once, then `run.evaluate(mode, ...)`. `NPM_SWALLOWED` covers `limit` and `mode`.
  - **The clean-tree rule.** `run.tree_clean()` runs `git status --porcelain --untracked-files=normal`, so any untracked file counts as dirty, and `eval/results/` is not git-ignored. The preflight refuses a dirty tree for a full run, and `_scratch_reasons` sends a result to scratch when the tree is dirty at the write. Every existing destination test stubs `tree_clean`.
  - **Tests that pin `vector` as the only mode**: `test_eval_run.py::test_only_the_vector_mode_runs`, `test_eval_cli.py`'s bad-argument case `["--mode", "hybrid"]`, the spy `fake_preflight(limit)` in `test_eval_cli.py`, and `check()` in `test_eval_preflight.py`, which calls `preflight(limit)`. `test_eval_run.py` asserts the result's `settings` dict exactly.
- **Settings.** `tests/test_config.py` pins two things: the exact set of `_env("...")` names, which must equal `.env.example`'s keys, and each default. `tests/test_schema.py::test_every_key_settings_reads_is_pinned_for_the_tests` needs every key in conftest's `PINNED_ENV`. `startup_problems()` reads `DATABASE_URL` and `OPENAI_API_KEY`. The api's lifespan and `worker.main()` both refuse to start on any problem, then run `verify_rls`.
- **The environment-read pin.** `test_auth.py::test_no_module_but_settings_reads_the_environment_unless_allowlisted` fails on any `environ`, `getenv` or `_env(` read outside `settings.py` that is not on its allowlist.
- **Migrations**: `0001_initial`, then `0002_platform` (the file is `0002_platform_shell.py`). `chunks.heading_path` is `text[] not null default '{}'`. conftest drops and recreates the per-checkout test database every session and migrates from empty, so a new migration always runs in the tests.
- **`verify_rls`** checks the role, the table grants, the `SET` option and the policy. The api, the worker and `smoke.preflight` all run it, and the evaluation's preflight calls `smoke.preflight`. It checks no function privileges.
- **`smoke.main`** ingests, which is paid, and then answers through `answering.answer`.
- **Licenses.** `check_licenses.py` passes any MPL-2.0 package (decision 0007). `test_licenses.py` already lists `tqdm`.
- **fastembed 0.9.0**, probed in a scratch environment:
  - `TextCrossEncoder(model_name, cache_dir=None, threads=None, lazy_load=False)`, and `rerank(query, documents, batch_size)` yields scores;
  - the cache is `fastembed.common.utils.define_cache_dir()`: `FASTEMBED_CACHE_PATH`, or else `<tmp>/fastembed_cache`;
  - each pair is truncated at 512 tokens;
  - importing it takes about a second, so `rerank.py` imports it inside `model()`.
- **The guard.**
  - Its interpreter spend pattern asks on any python or uv command that names `loreos` and a paid module word, such as `evaluation`.
  - A test file name like `tests/test_eval_modes.py` does not match, because `_` is a word character.
  - `uv --directory backend run python -m pytest tests/...` never names `loreos`.
- **CI** runs `uv sync --locked`, then each check. It keeps no cache for fastembed.
- **Probed on testdb (pg17), 2026-10-14:**
  - **The generated column.** `array_to_string` has `provolatile = 's'`, and a generated column using it fails with "generation expression is not immutable".
  - **The OR query.** `replace(plainto_tsquery('english', q)::text, ' & ', ' | ')::tsquery`:
    - "What is the e-mail policy for SKU-4471?" gives `'e-mail' | 'e' | 'mail' | 'polici' | 'sku' | '-4471'`;
    - "the and of" gives an empty query, with `numnode` 0 and a NOTICE;
    - "a & b | !c :d 'e' (f) O'Brien\x" gives quoted lexemes only.

## Phases

| Phase | Goal | Depends on | Check at the end |
|---|---|---|---|
| 1 | Keyword search, fusion and the reranker, each alone | none | `npm run check:all` PASS |
| 2 | Modes wired through search, ask, startup, smoke and the evaluation | phase 1 | `npm run check:all` PASS, then claim-green on the pushed tip |
| 3 | Measurement (paid, main session only) | phase 2 pushed and green | Six committed result files, decisions 0009 and 0010, `DEFAULT_MODE` set |
| 4 | Whole-branch review, fixes, PR | phase 3 | claim-green PASS on the pushed tip, and CI green |

## Parallel windows

All the tasks run in the main session, one at a time, in this order: 1.1, 1.2, 1.3, 2.1, 2.2, then phase 3. Two files pass between tasks, always in order:
- `retrieval.py` goes from 1.1 to 2.1;
- `run.py` goes from 2.1 (its two call sites) to 2.2.

| Window | Tasks | Shared files (must be none) |
|---|---|---|
| A | 1.1, 1.2, 1.3 | none (`retrieval.py` belongs to 1.1 alone) |
| B | 2.1, then 2.2 | `evaluation/run.py`, handed from 2.1 to 2.2 (sequential, never at once) |

## Handoff contracts

| From | To | Handoff |
|---|---|---|
| 1.1 | 2.1 | `retrieval.keyword_search(session, workspace_id, query, n) -> list[Hit]`, where `score` is `ts_rank_cd` |
| 1.2 | 2.1, 2.2 | `fusion.RRF_K = 60`, and `fusion.rrf(rankings: list[list[uuid]], k=RRF_K) -> list[tuple[uuid, float]]`, best first, with each id's RRF score |
| 1.3 | 2.1, 2.2 | `rerank.RERANK_MODEL`. `rerank.model()` is cached and raises `RuntimeError` with the corrective action. `rerank.rerank(query, hits) -> list[Hit]` is sync, and `score` is the cross-encoder score. `rerank.py` imports nothing from `loreos` at module level: `Hit` only under `TYPE_CHECKING`, and `ingest` inside `rerank()`. Either import at module level closes a cycle through `retrieval`. |
| 2.1 | 2.2 | `retrieval.MODES`, `retrieval.DEFAULT_MODE` (`"vector"` until decision 0010), `search(..., mode="vector")`, `answer_from_hits(question, hits, mode)`, `settings.rerank_on()` |
| 2.2 | 3 | `npm run paid:eval -- --mode M --chunk-tokens N --chunk-overlap N`, and `--mode all`. An untracked `eval/results/*.json` no longer dirties the tree. |

## Tasks

### Task 1.1: `tsv` column and keyword search

- Files owned:
  - `backend/alembic/versions/0003_keyword_search.py` (new);
  - `backend/loreos/retrieval.py` (`keyword_search` and its SQL only);
  - `backend/loreos/verify_rls.py`;
  - `backend/tests/test_keyword_search.py` (new);
  - `backend/tests/test_schema.py` and `test_isolation.py` (one case each, appended).
- Depends on: none.
- Change:
  - **The migration:**
    - creates `loreos.heading_text(text[]) returns text language sql immutable`, returning `pg_catalog.array_to_string($1, ' ')`;
    - grants `execute` on it to `loreos_app`;
    - adds `tsv tsvector generated always as (to_tsvector('english', loreos.heading_text(heading_path) || ' ' || text)) stored`;
    - runs `create index chunks_tsv on loreos.chunks using gin (tsv)`;
    - `downgrade` raises, as in 0001 and 0002.
  - **`verify_rls`** gains one named check: `loreos_app` can execute `loreos.heading_text(text[])`, read through `to_regprocedure`, with a missing function treated as a failure that names `npm run db:migrate`.
  - **`keyword_search`** builds the query in SQL as `replace(plainto_tsquery('english', :q)::text, ' & ', ' | ')::tsquery`.
    - `plainto_tsquery` drops punctuation and stems once. Its text output quotes every lexeme, and that output parses back as it was. A lexeme holds no space, so only the operators change.
    - When `numnode` of the query is 0, the question is stop words only, and the function returns `[]`.
    - Otherwise it filters `c.workspace_id = :w and c.tsv @@ query`, orders by `ts_rank_cd(c.tsv, query) desc, c.id`, and limits to `:n`. It joins `documents` for `filename`, like `NEAREST`.
- Acceptance check: `uv --directory backend run python -m pytest tests/test_keyword_search.py tests/test_schema.py tests/test_isolation.py` passes. These cases:
  - an exact term (`SKU-4471`) found by keyword search;
  - a stop-word question returns `[]`;
  - questions holding `&`, `|`, `!`, `:`, `'` and `(` return hits without an error;
  - another workspace's chunk is never returned when the search runs under `workspace_session`;
  - the rank prefers the chunk with more matched lexemes;
  - in `test_schema.py`, `tsv` holds a heading word and a text word after a plain insert, and `chunks_tsv` exists in `pg_indexes`;
  - in `test_isolation.py`, a new `NEGATIVES` entry revokes execute on `loreos.heading_text(text[])` from `loreos_app` and `public` on the admin connection, rolled back like the others. Its expected set is the new check's name alone, so `test_the_negatives_cover_every_check` covers it.
- Red first: the tests import `keyword_search`, which does not exist, so collection fails. With the module but no migration, the SQL errors on the missing `tsv` column.
- Redproof: replace the `' | '` join with `' & '`. The many-word question case must go red.
- Skills to load: harness:authoring-a-check.
- Predicted size: 6 files, about 180 lines.

### Task 1.2: RRF

- Files owned: `backend/loreos/fusion.py` (new), `backend/tests/test_fusion.py` (new).
- Depends on: none.
- Change: `RRF_K = 60`, and `rrf(rankings, k=RRF_K)` returns `(id, score)` pairs, best first.
  - The score is the sum of `Fraction(1, k + rank)`, with rank counted from 1. Exact arithmetic makes ties exact.
  - A tie breaks on the best single rank, then on the id.
  - The score is returned as a float. The function is pure.
- Acceptance check: `uv --directory backend run python -m pytest tests/test_fusion.py` passes, with:
  - a hand-computed three-list case at k = 60;
  - an id that appears in only one list;
  - a tie broken by best rank: at k = 0, A at ranks (2, 6) and B at (3, 3) both score 2/3, and A wins on rank 2;
  - an exact tie on both broken by id;
  - empty input gives `[]`.
- Red first: an import error.
- Redproof: drop the best-rank tiebreak. The tie case must go red.
- Predicted size: 2 files, about 60 lines.

### Task 1.3: the reranker and fastembed

- Files owned:
  - `backend/pyproject.toml` and `backend/uv.lock`, changed only through `uv add fastembed==0.9.0`;
  - `backend/loreos/rerank.py` (new);
  - `backend/tests/test_rerank.py` (new);
  - `.github/workflows/ci.yml`: a job-level `FASTEMBED_CACHE_PATH: ${{ github.workspace }}/.fastembed-cache` and one `actions/cache` step for that same path, keyed on the model name;
  - `.gitignore` (`.fastembed-cache/`).
- Depends on: none.
- Change:
  - `RERANK_MODEL = "Xenova/ms-marco-MiniLM-L-6-v2"`.
  - `model()` is `functools.cache`d. It imports fastembed inside, builds `TextCrossEncoder(RERANK_MODEL)`, and wraps any failure in `RuntimeError`. The message names:
    - the cache path, from `fastembed.common.utils.define_cache_dir()`, so loreos reads no environment variable;
    - deleting that cache;
    - network access for the first download;
    - "or set RERANK=off".
  - `rerank.py` imports nothing from `loreos` at module level: `Hit` only under `TYPE_CHECKING`.
  - `rerank(query, hits)` imports `ingest` inside, and scores each hit on `ingest.embedding_input`'s form: the heading path, a blank line, the text. It sets `score` and returns the hits sorted by score, descending, with ties kept in input order.
- Acceptance check:
  - `uv --directory backend run python -m pytest tests/test_rerank.py` passes. An autouse fixture calls `rerank.model.cache_clear()` before and after each test. Two cases:
    - the real model ranks "Deploys happen on Tuesdays" above "The cafeteria opens at noon" for "When do deploys happen?";
    - a `model()` failure, faked by monkeypatching the constructor, raises with "RERANK=off" in the message.
  - `npm run check:licenses` passes, and `test_auth.py`'s environment-read pin passes.
- Red first: an import error.
- Redproof: reverse the sort. The ranking case must go red.
- Predicted size: 6 files, about 90 lines, plus the lock.

### Task 2.1: modes in search, ask, startup and smoke

- Files owned:
  - `backend/loreos/retrieval.py`, `answering.py`, `settings.py` and `smoke.py` (the preflight only);
  - `backend/loreos/main.py` (the lifespan only);
  - `backend/loreos/evaluation/run.py` (the two call sites only);
  - `.env.example`;
  - `backend/tests/conftest.py` (`PINNED_ENV` only);
  - `backend/tests/test_retrieval.py`, `test_answering.py`, `test_ask_api.py`, `test_config.py` and `test_smoke.py`;
  - `backend/tests/test_rerank_switch.py` (new).
- Depends on: 1.1, 1.2, 1.3.
- Change:
  - **`retrieval`:**
    - `MODES = ("vector", "hybrid", "hybrid_rerank")`, and `DEFAULT_MODE = "vector"`.
    - `search(session, workspace_id, query, k, mode="vector")`, where `vector` is the old body with `limit k`.
    - `hybrid` fuses vector top `FUSE_DEPTH = 50` and `keyword_search(..., FUSE_DEPTH)` with `rrf`, and keeps the top `k`, with `score` set to the RRF score.
    - `hybrid_rerank` takes the fused top `RERANK_DEPTH = 30`, runs `await asyncio.to_thread(rerank.rerank, query, hits)`, and keeps the top `k`.
    - The `HAS_CHUNKS` short-circuit still comes first in every mode.
    - `serving_mode()` returns `hybrid` when `DEFAULT_MODE == "hybrid_rerank"` and RERANK is off, else `DEFAULT_MODE`.
  - **`settings.rerank_on()`** reads `RERANK`: empty or `on` is True, `off` is False, and anything else raises `RuntimeError` naming the two values.
    - `startup_problems()` reads it too, so a bad value stops the api and the worker alike. A typo in `.env` should fail loudly everywhere.
  - **`answering`:**
    - `Answer.retrieval_mode: str` is required;
    - `answer()` resolves `mode = retrieval.serving_mode()` and passes it to `search` and to `answer_from_hits(question, hits, mode)`;
    - `_refuse` carries the mode.
  - **`run.py`:** `_ask` passes `"vector"`, the only mode until 2.2, to `answer_from_hits` and to the `Answer` built on an answer error.
  - **`main.lifespan`** loads `rerank.model()` after the existing checks, only when `serving_mode() == "hybrid_rerank"`, and refuses to start with the model error.
  - **`smoke.preflight`** calls `rerank.model()` under the same condition, before any paid call, and turns a failure into `SystemExit`.
  - **`.env.example`** gets `RERANK=on`, with a comment; `PINNED_ENV` gets `RERANK: "on"`.
- Acceptance check: `npm run check:backend` passes, with:
  - in `test_retrieval.py`:
    - `hybrid` returns a chunk only keyword search finds;
    - `hybrid_rerank` with a monkeypatched `rerank.rerank` returns its order cut to `k`;
    - no embedding is bought on an empty workspace in any mode;
    - the existing tests pass unchanged;
  - in `test_answering.py`, the existing calls get the mode, and a refusal carries it;
  - in `test_ask_api.py`, the JSON's `retrieval_mode` equals `retrieval.serving_mode()`, so the case survives the phase 3 flip;
  - in `test_rerank_switch.py`, with `DEFAULT_MODE` monkeypatched to `hybrid_rerank`:
    - `RERANK=off` answers with `retrieval_mode == "hybrid"` and never calls `rerank.model`;
    - `on` with `rerank.model` raising makes the lifespan raise with "RERANK=off" in the message;
    - `worker.main()`'s startup checks pass without calling `rerank.model` (it is set to raise);
    - `RERANK=maybe` is a startup problem;
  - in `test_smoke.py`, the preflight stops before any paid call when `rerank.model` raises and the serving mode is `hybrid_rerank`;
  - in `test_config.py`, the key set gains `RERANK`, and the default is `on`.
- Red first: the new tests fail on the missing `mode` argument and the missing field. `test_config` fails on the key set until `.env.example` changes.
- Redproof: in `serving_mode`, return `DEFAULT_MODE` unconditionally. The `RERANK=off` case must go red.
- Predicted size: 15 files, about 220 lines.

### Task 2.2: the evaluation runs every mode and any chunk size

- Files owned:
  - `backend/loreos/chunking.py` (call-time defaults only);
  - `backend/loreos/evaluation/__main__.py`, `run.py` and `preflight.py`;
  - `backend/tests/test_chunking.py`, `test_eval_cli.py`, `test_eval_run.py` and `test_eval_preflight.py`;
  - `backend/tests/test_eval_modes.py` (new).
- Depends on: 2.1.
- Change:
  - **`chunk(sections, max_tokens=None, overlap_tokens=None)`** reads the module constants when it is called.
  - **The CLI:**
    - `--mode` choices are `run.MODES + ("all",)`;
    - `--chunk-tokens N` and `--chunk-overlap N` must both be integers, with tokens at least 50 and overlap from 0 to less than tokens. They are assigned to `chunking.CHUNK_TOKENS` and `CHUNK_OVERLAP` before the preflight;
    - both join `NPM_SWALLOWED`;
    - when `settings.rerank_on()` is False, `hybrid_rerank` and `all` exit 2 before the preflight, with the fix. A `RuntimeError` from a bad `RERANK` value also exits 2 with its message;
    - `all` runs the preflight once, then `run.evaluate` for each mode in `run.MODES`, printing each result's path and metrics.
  - **`run`:**
    - `MODES = retrieval.MODES`;
    - `_ask` passes the run's `mode` to `retrieval.search` and to `answer_from_hits`;
    - the result's `settings` gains `rerank_model` (`rerank.RERANK_MODEL`) and `rrf_k` (`fusion.RRF_K`) in every mode.
  - **`run.tree_clean()`** lists every untracked file (`--untracked-files=all`) and ignores only untracked `*.json` directly in `dataset.RESULTS_DIR`. A tracked change, or any other untracked file, still makes the tree dirty.
    - The prefix is `RESULTS_DIR` relative to `dataset.ROOT`, both read when called. When `RESULTS_DIR` is outside `ROOT`, nothing is exempt. That keeps `test_the_git_helpers_read_the_repo_root`, which patches only `ROOT`, from raising.
    - This narrows P2 behaviour 5: an uncommitted result is not code, and without the exception `--mode all` and the sweep could never commit more than one file per SHA.
    - The spec records the change.
  - **`preflight.preflight(limit, modes)`:**
    - for a mode list holding `hybrid_rerank`, it calls `rerank.model()` before `_print_plan` and turns a failure into `SystemExit`;
    - `_print_plan` multiplies the question embed calls, the answer and judge calls, and the tokens by `len(modes)`.
- Acceptance check: `npm run check:backend` passes, with:
  - `test_chunking.py`: assigning `chunking.CHUNK_TOKENS = 100` changes what `chunk()` returns. `test_defaults` stays as it is;
  - `test_eval_cli.py`:
    - the spy and `stopping_preflight` take `(limit, modes)`;
    - the bad-argument case becomes `["--mode", "bogus"]`;
    - `--chunk-tokens 250 --chunk-overlap 25` reaches `chunking` before the preflight, and a fixture restores the module values;
    - an overlap of at least the token count exits 2;
    - `npm_config_chunk_tokens` is refused with the separator form;
    - `--mode all` calls `evaluate` three times after one preflight;
  - `test_eval_run.py`:
    - `test_only_the_vector_mode_runs` becomes "an unknown mode is refused", with `"bogus"`;
    - the exact `settings` dict gains the two keys;
    - `tree_clean` on a temporary git repository:
      - an untracked `eval/results/x.json` is clean;
      - an untracked `eval/results/x.txt`, `eval/results/sub/x.json` or `backend/x.py` is dirty;
      - a modified tracked file is dirty;
      - the commit is made with `-c user.name=t -c user.email=t@example.com -c commit.gpgsign=false`, since CI runners have no git identity;
  - `test_eval_preflight.py`: `check()` passes the modes, and a `hybrid_rerank` preflight with a failing `rerank.model` stops before `_print_plan`;
  - `test_eval_modes.py`:
    - with `RERANK=off`, `--mode all` and `--mode hybrid_rerank` exit 2 without calling the preflight;
    - with `RERANK=maybe`, the CLI exits 2 with the settings message and no traceback;
    - `--chunk-tokens 250` reaches the result's `settings.chunk_tokens` and the stored chunks' sizes, with the fakes;
    - a `hybrid` run writes a result whose `mode` is `hybrid`;
    - a `hybrid_rerank` run with `rerank.rerank` replaced by a 50 ms sleep records every `search_ms` at 50 or more;
    - `--mode all`, with the real `run.evaluate`, `_scratch_reasons` and `tree_clean` and the fakes, writes three files to `RESULTS_DIR`. The layout:
      - `repo = tmp_path / "repo"` after `git init`, with one commit;
      - `dataset.ROOT = repo` and `RESULTS_DIR = repo / "eval" / "results"`;
      - the inputs and `SCRATCH_DIR` sit outside `repo`;
      - the setup is borrowed from `test_eval_run.py`'s `ev` fixture, moved to conftest or copied, with the real `tree_clean` restored over its stub;
      - `git_sha` is stubbed to the fake preflight's SHA.
- Red first:
  - the new flags are unknown to argparse (exit 2), and `MODES` has only `vector`;
  - the `tree_clean` case fails on today's rule, which counts the untracked `x.json` as dirty.
- Redproof: drop the `RESULTS_DIR` exception in `tree_clean`. The temp-repo case and the `--mode all` case, which then writes one file to `RESULTS_DIR` and two to scratch, must go red.
- Predicted size: 10 files, about 280 lines.

### Phase 3: measurement (main session, paid, each run asks)

1. **Push and claim green on the phase 2 tip.** `claim-green --feature p3-hybrid-search`, then commit and push the ledger row.
2. **Migrate Supabase.** Run `npm run db:migrate` and `npm run db:verify-rls`, then `select count(*) from loreos.chunks where tsv is null`. All three are free. Their output is kept in `scratch/`, and the ledger rows wait for step 5.
3. **Dry-run the sweep.** `npm run paid:eval -- --mode vector --chunk-tokens 250 --chunk-overlap 25 --dry-run` asks, and is free. It is repeated for 500/50 and 1000/100. Each plan is priced from the spec's Spend section before the paid runs are asked.
4. **The sweep: three runs at one SHA**, run detached with their output in `docs/sdd/p3-hybrid-search/scratch/`. Each asks:

   | Run | Chunk tokens | Overlap |
   |---|---|---|
   | 1 | 250 | 25 |
   | 2 | 500 | 50 |
   | 3 | 1000 | 100 |

   Nothing is committed and STATUS is not touched until the third run has written its file.
5. **Decision 0009 and the sweep's commit.**
   - First check that the three result files carry one `git_sha`, since nothing else forces one SHA now that results are exempt from the clean-tree rule.
   - Decision 0009 sets `CHUNK_TOKENS` and `CHUNK_OVERLAP` by spec behaviour 2. `test_chunking.py::test_defaults` follows the new values.
   - One commit carries the three result files, the decision, the constants, the test, and the ledger rows for steps 2 to 4, each run with its cost from its `usage` block.
   - Then `npm run check:all` passes and the commit is pushed.
6. **`--mode all`**: first `--dry-run`, then the paid run, each asking, at the SHA from step 5.
7. **Decision 0010** names:
   - the model, its size, its license and the 512-token cut;
   - the three rows and their latency;
   - `DEFAULT_MODE` by spec behaviour 9.

   If `DEFAULT_MODE` is `hybrid_rerank`, three more changes follow:
   - the `Dockerfile` gets `ENV FASTEMBED_CACHE_PATH=/app/fastembed` and a build line `python -c "from loreos import rerank; rerank.model()"`, placed before `USER`;
   - `scripts/compose-check.yml` sets `HF_HUB_OFFLINE=1` for the api, so a failed bake cannot pass by downloading at startup;
   - `npm run check:compose` passes, run in its own CI job.

   Whatever the default becomes, `npm run check:all` runs after the change. A default other than `vector` makes the ask tests and `test_smoke.py`'s real preflight serve through that mode, and with `RERANK=on` pinned, `hybrid_rerank` loads the real model. Any test that assumes vector serving is fixed red first, or conftest pins `retrieval.DEFAULT_MODE` with a note, before the push.
8. **The hybrid run's misses.** Read them for Hugo shortcode tokens among keyword search's false hits, which is the KNOWN-GAPS trigger. A shortcode found among them becomes a finding in STATUS.
9. **The database size.** `select pg_size_pretty(pg_database_size(current_database()))` is free, and its result goes in STATUS. Pruning old `eval-*` workspaces waits for the operator's yes.
10. **The README line** stating which mode measured the chunk size is P5's: P5 writes the README, and this note in STATUS hands it over by name.

### Phase 4: review and PR

1. **Whole-branch review** by an independent reviewer subagent. It runs `npm run check:all` twice, since the suite reads the environment.
2. **A fix wave** for its findings, each fix red first.
3. **claim-green** on the pushed tip, with the PR body built from `templates/sdd/pr-body.md`, and CI green.
4. **Merge only on the operator's yes.**
5. **STATUS closed.**

## What this plan does NOT cover

- **Tuning RRF k or the candidate depths (50 and 30).** Trigger: the comparison shows `hybrid` losing to `vector`.
- **A chunk size measured per mode.** Trigger: decision 0010's default differs from `vector`, and the operator wants the size re-checked in that mode.
- **Showing `retrieval_mode` in the UI.** Trigger: a user asks why two answers differ.
- **A longer reranker input than fastembed's 512 tokens.** Trigger: decision 0009 picks 1000 tokens and the rerank gain is small.
- **Pruning `eval-*` workspaces.** Trigger: the database nears its plan's size limit, or the operator asks.
- **The ask route's transaction**, which stays open through the embedding, the draft and now the rerank. That is P1's pattern. Trigger: connection pressure on Supabase.

## Plan review findings and their changes

| Finding (reviews/plan.md, first review) | Change |
|---|---|
| Blocker: an untracked result dirties the tree, so `--mode all` and the sweep cannot commit more than one file | 2.2 narrows `tree_clean` to ignore untracked `eval/results/*.json`, with a temp-repo check and a three-file `--mode all` check. Phase 3 commits and writes ledger rows only after the third run. The spec records the change to P2 behaviour 5. |
| Major: existing tests go red in files no task owns | 2.1 owns `test_answering.py` and `run.py`'s two call sites. 2.2 owns `test_eval_run.py` and `test_eval_preflight.py`, with each needed edit named. |
| Major: import cycle `retrieval` → `rerank` → `ingest` → `retrieval` | 1.3 imports `ingest` inside `rerank()`. Recorded in Facts and in the handoff. |
| Minor: the cache path read from the environment | 1.3 uses `define_cache_dir()`. |
| Minor: `functools.cache` makes test order matter | 1.3 adds an autouse `cache_clear` fixture. |
| Minor: the RRF tie fixture | 1.2 uses `Fraction` and names the k = 0 fixture. |
| Minor: no check that the worker never loads the model | 2.1 adds the worker case and states that a bad `RERANK` stops the worker too. |
| Minor: no check that latency covers the rerank | 2.2 adds the 50 ms sleep case. |
| Minor: `settings` lacks the model and k | 2.2 adds `rerank_model` and `rrf_k`. |
| Minor: `~` in the CI cache path | 1.3 uses `${{ github.workspace }}/.fastembed-cache`, keyed on the model. |
| Minor: `check:compose` passes when the bake fails | Phase 3 step 7 sets `HF_HUB_OFFLINE=1` for the api. |
| Minor: `test_defaults` goes red at decision 0009 | Phase 3 step 5 updates it and runs `check:all` before `--mode all`. |
| Minor: smoke would load the model after paying | 2.1 has `smoke.preflight` load it when the serving mode needs it, with a test. |
| Minor: the function grant and the unqualified `array_to_string` | 1.1 grants execute to `loreos_app`, uses `pg_catalog.array_to_string`, and adds a `verify_rls` check. |
| Minor: the README line and the shortcode check have no step | Phase 3 steps 8 and 10. |
| Nit: the multiplier leaves out question embeds | 2.2 multiplies them too. |
| Nit: the protected-path count | Five, listed. |
| Nit: the phrase-operator sentence contradicts the probe | Deleted. |
| Nit: the `workspace_name` case repeats an existing test | Replaced by the `settings.chunk_tokens` and chunk-size case. |
| Nit: redproof needs a clean tree | Stated: each redproof runs after the task's commit. |
| Nit: `RERANK=maybe` gives a traceback in the CLI | 2.2 exits 2 with the message. |
