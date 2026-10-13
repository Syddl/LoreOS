# Plan: p3-hybrid-search

Implements [spec.md](spec.md), as revised against P1, P2 and P4.

**Sizing.** P3 is a multi-task feature with a data migration and a spend surface, so all fourteen lifecycle steps run, and step 9 is by an independent reviewer.

**Implementation.** The main session implements the tasks itself, red first, with a `redproof` per task (LIFECYCLE step 6, "the main session for small work"). The reasons:
- each task is under about 150 lines;
- three of them touch protected paths (the migration, `uv.lock`, `ci.yml`), whose edit asks cannot be answered from a subagent.

A reviewer subagent reviews each phase (step 7).

## Facts read before planning

- **retrieval.py** has `search(session, workspace_id, query, k)`: an exact cosine scan with `limit k`. It returns nothing, and buys no embedding, when the workspace has no chunks (`HAS_CHUNKS`). `Hit` carries `score`.
- **answering.py**: `answer()` calls `search(..., TOP_K)`, then `answer_from_hits(question, hits)`. `Answer` has four fields, and the ask route maps every one into the JSON (`routes/documents.py`, `ask`), with `text` renamed `answer`.
- **chunking.py**: `chunk(sections, max_tokens=CHUNK_TOKENS, overlap_tokens=CHUNK_OVERLAP)`. The defaults bind when Python defines the function, so assigning `chunking.CHUNK_TOKENS` later changes nothing in `ingest.run_stages`, which calls `chunking.chunk(sections)`.
- **evaluation.** These parts read `chunking.CHUNK_TOKENS` and `CHUNK_OVERLAP` when they run:
  - `run.workspace_name` (the key), which also hashes the source of `parsing.py`, `chunking.py` and `ingest.py`;
  - `preflight._print_plan`;
  - the result's `settings`.

  The rest of it:
  - `run.MODES = ("vector",)`;
  - `run._ask` times `retrieval.search(..., SEARCH_K)` as `search_ms`, then answers from the first `TOP_K` hits;
  - `__main__.cli` runs the preflight once, then `run.evaluate(mode, ...)`;
  - `NPM_SWALLOWED` covers `limit` and `mode`.
- **Settings.** `tests/test_config.py` pins two things: the exact set of `_env("...")` names, which must equal `.env.example`'s keys, and each default. `tests/test_schema.py::test_every_key_settings_reads_is_pinned_for_the_tests` needs every key in conftest's `PINNED_ENV`. `startup_problems()` reads `DATABASE_URL` and `OPENAI_API_KEY`. The api's lifespan refuses to start on any of them, then runs `verify_rls`.
- **Migrations**: `0001_initial`, then `0002_platform` (the file is `0002_platform_shell.py`). `chunks.heading_path` is `text[] not null default '{}'`. conftest drops and recreates the per-checkout test database every session and migrates from empty, so a new migration always runs in the tests.
- **Licenses.** `check_licenses.py` passes any MPL-2.0 package (decision 0007). `test_licenses.py` already lists `tqdm`.
- **fastembed 0.9.0.**
  - `TextCrossEncoder(model_name, cache_dir=None, threads=None, lazy_load=False)`, and `rerank(query, documents, batch_size)` yields scores.
  - The cache defaults to `FASTEMBED_CACHE_PATH`, or else `<tmp>/fastembed_cache`.
  - It truncates each pair at 512 tokens.
  - Importing it takes about a second, so `rerank.py` imports it inside `model()`.
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
| 2 | Modes wired through search, ask, startup and the evaluation | phase 1 | `npm run check:all` PASS, then claim-green on the pushed tip |
| 3 | Measurement (paid, main session only) | phase 2 pushed and green | Six committed result files, decisions 0009 and 0010, `DEFAULT_MODE` set |
| 4 | Whole-branch review, fixes, PR | phase 3 | claim-green PASS on the pushed tip, and CI green |

## Parallel windows

All the tasks run in the main session, one at a time, in this order: 1.1, 1.2, 1.3, 2.1, 2.2, 3.x. File ownership still holds: no two tasks of one phase own the same file.

| Window | Tasks | Shared files (must be none) |
|---|---|---|
| A | 1.1, 1.2, 1.3 | none (`retrieval.py` belongs to 1.1 alone) |
| B | 2.1, then 2.2 | none: 2.1 owns `retrieval.py`, `answering.py`, `settings.py` and `main.py`; 2.2 owns `evaluation/` and `chunking.py` |

## Handoff contracts

| From | To | Handoff |
|---|---|---|
| 1.1 | 2.1 | `retrieval.keyword_search(session, workspace_id, query, n) -> list[Hit]`, where `score` is `ts_rank_cd` |
| 1.2 | 2.1 | `fusion.rrf(rankings: list[list[uuid]], k=60) -> list[uuid]` |
| 1.3 | 2.1, 2.2 | `rerank.RERANK_MODEL`; `rerank.model()` is cached and raises `RuntimeError` with the corrective action; `rerank.rerank(query, hits) -> list[Hit]` is sync, and `score` is the cross-encoder score |
| 2.1 | 2.2 | `retrieval.MODES`, `retrieval.DEFAULT_MODE` (`"vector"` until decision 0010), `search(..., mode="vector")`, `answer_from_hits(question, hits, mode)`, `settings.rerank_on()` |
| 2.2 | 3 | `npm run paid:eval -- --mode M --chunk-tokens N --chunk-overlap N`, and `--mode all` |

## Tasks

### Task 1.1: `tsv` column and keyword search

- Files owned:
  - `backend/alembic/versions/0003_keyword_search.py` (new);
  - `backend/loreos/retrieval.py` (`keyword_search` and its SQL only);
  - `backend/tests/test_keyword_search.py` (new);
  - `backend/tests/test_schema.py` (append).
- Depends on: none.
- Change:
  - **The migration** creates `loreos.heading_text(text[]) returns text language sql immutable`, returning `array_to_string($1, ' ')`. It then adds `tsv tsvector generated always as (to_tsvector('english', loreos.heading_text(heading_path) || ' ' || text)) stored` and `create index chunks_tsv on loreos.chunks using gin (tsv)`. `downgrade` raises, as in 0001 and 0002.
  - **`keyword_search`** builds the query in SQL as `replace(plainto_tsquery('english', :q)::text, ' & ', ' | ')::tsquery`.
    - `plainto_tsquery` drops punctuation and stems once. Its text output quotes every lexeme, and that output parses back as it was. A lexeme holds no space, so only the operators change. Phrase operators (`<->`), which a hyphenated word produces, stay.
    - When `numnode` of the query is 0, the question is stop words only, and the function returns `[]`.
    - Otherwise it filters `c.workspace_id = :w and c.tsv @@ query`, orders by `ts_rank_cd(c.tsv, query) desc, c.id`, and limits to `:n`. It joins `documents` for `filename`, like `NEAREST`.
- Acceptance check: `uv --directory backend run python -m pytest tests/test_keyword_search.py tests/test_schema.py` passes. These cases:
  - an exact term (`SKU-4471`) found by keyword search;
  - a stop-word question returns `[]`;
  - questions holding `&`, `|`, `!`, `:`, `'` and `(` return hits without an error;
  - another workspace's chunk is never returned when the search runs under `workspace_session`;
  - the rank prefers the chunk with more matched lexemes;
  - in `test_schema.py`, `tsv` holds a heading word and a text word after a plain insert, and `chunks_tsv` exists in `pg_indexes`.
- Red first: the tests import `keyword_search`, which does not exist, so collection fails. With the module but no migration, the SQL errors on the missing `tsv` column.
- Redproof: replace the `' | '` join with `' & '`. The many-word question case must go red.
- Skills to load: harness:authoring-a-check.
- Predicted size: 4 files, about 150 lines.

### Task 1.2: RRF

- Files owned: `backend/loreos/fusion.py` (new), `backend/tests/test_fusion.py` (new).
- Depends on: none.
- Change: `rrf(rankings, k=60)` returns ids ordered by the summed 1 / (k + rank), with rank counted from 1. A tie breaks on the best single rank, then on the id. It is pure.
- Acceptance check: `uv --directory backend run python -m pytest tests/test_fusion.py` passes, with:
  - a hand-computed three-list case;
  - an id that appears in only one list;
  - an exact tie, broken by best rank and then by id;
  - empty input gives `[]`.
- Red first: an import error.
- Redproof: drop the best-rank tiebreak. The tie case must go red.
- Predicted size: 2 files, about 60 lines.

### Task 1.3: the reranker and fastembed

- Files owned:
  - `backend/pyproject.toml` and `backend/uv.lock`, changed only through `uv add fastembed==0.9.0`;
  - `backend/loreos/rerank.py` (new);
  - `backend/tests/test_rerank.py` (new);
  - `.github/workflows/ci.yml`: one `actions/cache` step for `~/.cache/fastembed`, with `FASTEMBED_CACHE_PATH` set at job level.
- Depends on: none.
- Change:
  - `RERANK_MODEL = "Xenova/ms-marco-MiniLM-L-6-v2"`.
  - `model()` is `functools.cache`d. It imports fastembed inside, builds `TextCrossEncoder(RERANK_MODEL)`, and wraps any failure in `RuntimeError`. The message names three ways out: the cache path (from `FASTEMBED_CACHE_PATH`, or the temp default), deleting that cache, and network access for the first download. It closes with "or set RERANK=off".
  - `rerank(query, hits)` scores each hit on `ingest.embedding_input`'s form (the heading path, a blank line, the text), sets `score`, and returns the hits sorted by score, descending, with ties kept in input order.
- Acceptance check:
  - `uv --directory backend run python -m pytest tests/test_rerank.py` passes. The real model ranks "Deploys happen on Tuesdays" above "The cafeteria opens at noon" for "When do deploys happen?". A `model()` failure, faked by monkeypatching the constructor, raises with "RERANK=off" in the message.
  - `npm run check:licenses` passes.
- Red first: an import error.
- Redproof: reverse the sort. The ranking case must go red.
- Skills to load: none.
- Predicted size: 5 files, about 80 lines, plus the lock.

### Task 2.1: modes in search, ask and startup

- Files owned:
  - `backend/loreos/retrieval.py`;
  - `backend/loreos/answering.py`;
  - `backend/loreos/settings.py`;
  - `backend/loreos/main.py` (the lifespan only);
  - `.env.example`;
  - `backend/tests/conftest.py` (`PINNED_ENV` only);
  - `backend/tests/test_retrieval.py`, `test_ask_api.py` and `test_config.py` (appended);
  - `backend/tests/test_rerank_switch.py` (new).
- Depends on: 1.1, 1.2, 1.3.
- Change:
  - **`retrieval`:**
    - `MODES = ("vector", "hybrid", "hybrid_rerank")`, and `DEFAULT_MODE = "vector"`.
    - `search(session, workspace_id, query, k, mode="vector")`, where `vector` is the old body with `limit k`.
    - `hybrid` fuses vector top 50 and `keyword_search(..., 50)` with `rrf`, and keeps the top `k`, with `score` set to the RRF score.
    - `hybrid_rerank` takes the fused top 30, runs `await asyncio.to_thread(rerank.rerank, query, hits)`, and keeps the top `k`.
    - The `HAS_CHUNKS` short-circuit still comes first in every mode.
    - `serving_mode()` returns `hybrid` when `DEFAULT_MODE == "hybrid_rerank"` and RERANK is off, else `DEFAULT_MODE`.
  - **`settings.rerank_on()`** reads `RERANK`: empty or `on` is True, `off` is False, and anything else raises `RuntimeError` naming the two values. `startup_problems()` reads it too.
  - **`answering`:**
    - `Answer.retrieval_mode: str`;
    - `answer()` resolves `mode = retrieval.serving_mode()` and passes it to `search` and to `answer_from_hits(question, hits, mode)`;
    - `_refuse` carries the mode.
  - **`main.lifespan`** loads `rerank.model()` after the existing checks, only when `serving_mode() == "hybrid_rerank"`, and refuses to start with the model error.
  - **`.env.example`** gets `RERANK=on`, with a comment; `PINNED_ENV` gets `RERANK: "on"`.
- Acceptance check: `npm run check:backend` passes, with:
  - in `test_retrieval.py`, `hybrid` returns a chunk only keyword search finds, and `hybrid_rerank` with a monkeypatched `rerank.rerank` returns its order cut to `k`. No embedding is bought on an empty workspace in any mode, and the existing tests pass unchanged;
  - in `test_ask_api.py`, `retrieval_mode == "vector"` is in the JSON;
  - in `test_rerank_switch.py`, with `DEFAULT_MODE` monkeypatched to `hybrid_rerank`:
    - `RERANK=off` answers with `retrieval_mode == "hybrid"` and never calls `rerank.model`;
    - `on` with `rerank.model` raising makes the lifespan raise with "RERANK=off" in the message;
    - `RERANK=maybe` is a startup problem;
  - in `test_config.py`, the key set gains `RERANK`, and the default is `on`.
- Red first: the new tests fail on the missing `mode` argument and the missing field. `test_config` fails on the key set until `.env.example` changes.
- Redproof: in `serving_mode`, return `DEFAULT_MODE` unconditionally. The `RERANK=off` case must go red.
- Predicted size: 10 files, about 200 lines.

### Task 2.2: the evaluation runs every mode and any chunk size

- Files owned:
  - `backend/loreos/chunking.py` (call-time defaults only);
  - `backend/loreos/evaluation/__main__.py`, `run.py` and `preflight.py`;
  - `backend/tests/test_chunking.py` (appended), `test_eval_cli.py` (appended), `test_eval_modes.py` (new).
- Depends on: 2.1.
- Change:
  - **`chunk(sections, max_tokens=None, overlap_tokens=None)`** reads the module constants when it is called.
  - **The CLI:**
    - `--mode` choices are `run.MODES + ("all",)`;
    - `--chunk-tokens N` and `--chunk-overlap N` must both be integers, with tokens at least 50 and overlap from 0 to less than tokens. They are assigned to `chunking.CHUNK_TOKENS` and `CHUNK_OVERLAP` before the preflight;
    - both join `NPM_SWALLOWED`;
    - with `settings.rerank_on()` False, `hybrid_rerank` and `all` exit 2 before the preflight, with the fix;
    - `all` runs the preflight once, then `run.evaluate` for each mode in `run.MODES`, printing each result's path and metrics.
  - **`run`:**
    - `MODES = retrieval.MODES`;
    - `_ask` passes `mode` to `retrieval.search` and to `answer_from_hits`;
    - the row gains nothing new: the file's `mode` already labels it.
  - **`preflight.preflight(limit, modes)`:**
    - for a mode list holding `hybrid_rerank`, it calls `rerank.model()` before `_print_plan` and turns a failure into `SystemExit`;
    - `_print_plan` multiplies the answer and judge calls and tokens by `len(modes)`.
- Acceptance check: `npm run check:backend` passes, with:
  - `test_chunking.py`: assigning `chunking.CHUNK_TOKENS = 100` changes what `chunk()` returns;
  - `test_eval_cli.py`:
    - `--chunk-tokens 250 --chunk-overlap 25` reaches `chunking` before the preflight, and the module values are restored by the fixture;
    - an overlap of at least the token count exits 2;
    - `npm_config_chunk_tokens` is refused with the separator form;
    - `--mode all` calls `evaluate` three times after one preflight;
  - `test_eval_modes.py`:
    - with `RERANK=off`, `--mode all` and `--mode hybrid_rerank` exit 2 without calling the preflight;
    - `run.workspace_name` differs between 250 and 500 tokens;
    - a run in `hybrid` mode, with the fakes, writes a result whose `mode` is `hybrid`;
    - `preflight` with `hybrid_rerank` and a failing `rerank.model` stops before `_print_plan`.
- Red first: the new flags are unknown to argparse (exit 2), and `MODES` has only `vector`.
- Redproof: drop the `rerank_on()` refusal. The `RERANK=off` cases must go red.
- Predicted size: 7 files, about 180 lines.

### Phase 3: measurement (main session, paid, each run asks)

1. **Push and claim green on the phase 2 tip.** `claim-green --feature p3-hybrid-search`, then commit and push the ledger row.
2. **Migrate Supabase.** Run `npm run db:migrate` and `npm run db:verify-rls`, then `select count(*) from loreos.chunks where tsv is null`. All three are free. Each gets a ledger row by hand.
3. **Dry-run the sweep.** `npm run paid:eval -- --mode vector --chunk-tokens 250 --chunk-overlap 25 --dry-run` asks, and is free. It is repeated for 500/50 and 1000/100. Each plan is priced from the spec's Spend section before the paid runs are asked.
4. **The sweep: three runs at one SHA**, run detached with their output in `docs/sdd/p3-hybrid-search/scratch/`. Each asks:

   | Run | Chunk tokens | Overlap |
   |---|---|---|
   | 1 | 250 | 25 |
   | 2 | 500 | 50 |
   | 3 | 1000 | 100 |

   One ledger row per run, with its cost from the `usage` block.
5. **Decision 0009.** It sets `CHUNK_TOKENS` and `CHUNK_OVERLAP` by spec behaviour 2, and is committed with the three result files.
6. **`--mode all`**: first `--dry-run`, then the paid run, each asking, at the SHA from step 5.
7. **Decision 0010** names:
   - the model, its size, its license and the 512-token cut;
   - the three rows and their latency;
   - `DEFAULT_MODE` by spec behaviour 9.

   If `DEFAULT_MODE` is `hybrid_rerank`, two more changes follow:
   - the `Dockerfile` gets `ENV FASTEMBED_CACHE_PATH=/app/fastembed` and a build line `python -c "from loreos import rerank; rerank.model()"`, placed before `USER`;
   - `npm run check:compose` passes, run in its own CI job.
8. **The database size.** `select pg_size_pretty(pg_database_size(current_database()))` is free, and its result goes in STATUS. Pruning old `eval-*` workspaces waits for the operator's yes.

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
