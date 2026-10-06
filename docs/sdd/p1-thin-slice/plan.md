# Plan: p1-thin-slice

Implements [spec.md](spec.md). Sizing: all fourteen lifecycle steps (a spend surface and the first schema), with an independent reviewer at step 9. Revised after the plan review in [reviews/plan.md](reviews/plan.md).

## Facts read before planning

- Supabase runs PostgreSQL 17.11 with pgvector 0.8.2 in the `extensions` schema. The role's `search_path` is `"$user", public, extensions`, so the unqualified `vector` type and `<=>` resolve. The test database is `pgvector/pgvector:pg17`.
- Python 3.14 resolves wheels-only on Windows and Linux for every P1 to P3 dependency (fastembed and onnxruntime included), so `backend/.python-version` pins 3.14.
- The Supabase database already holds an empty `public.documents` (a LangChain template) and `match_documents()`, and default privileges grant `anon` full access to every table `postgres` creates in `public`. Operator decision: LoreOS lives in its own schema `loreos`, including `alembic_version`. The old table stays untouched.
- certifi (MPL-2.0) comes in through tiktoken's `requests`. The OpenAI SDK 3.x uses httpx2 and truststore, and so does Starlette's TestClient, so no `httpx` dev dependency is needed. Operator decision: allow certifi by name only. P3's fastembed brings tqdm (MPL-2.0 AND MIT), so P3 decides that one.
- `DATABASE_URL` in `.env` is set and uses the session pooler (port 5432) with no query string. `OPENAI_API_KEY` is empty, which blocks only `paid:smoke`.
- On this machine, Application Control blocks the venv's console-script shims (`pytest.exe`), so every script runs `python -m <tool>`.

## Design choices inside the spec

- SQL is written as `text()` in the module that owns it, with tables schema-qualified (`loreos.chunks`). Each table name is spelled out where it is used, like the table names themselves. A `search_path` would hide a wrong reference behind the unrelated `public.documents`. Vectors are bound as `'[...]'` strings with `cast(:q as vector)`, so the `pgvector` package is not needed.
- The engine uses `NullPool` (`ponytail:` marked). It opens one connection per `workspace_session`, so no pooled asyncpg connection outlives the event loop it was made on. The OpenAI client follows the same rule: it is built per call inside `async with`, never cached.
- `.env` is read by a few lines in `settings.py` from the repo root with `os.environ.setdefault`, so a variable the process already has wins. The test conftest assigns the test values before any read.
- `ingest` runs inside the caller's `workspace_session` transaction; `process(session, workspace_id, document_id)` is the rerunnable half P4's worker calls. It deletes the document's chunks first, then parses and embeds. The store stage inserts chunks and marks the document processed inside a savepoint, so a failed insert rolls back while the transaction stays usable. Any failure leaves the document `failed` with zero chunks. Error text is truncated, and `sk-` keys and the configured key value are scrubbed.
- Added during implementation, after a security review of the routes commit: `TrustedHostMiddleware` for 127.0.0.1 and localhost (DNS rebinding), and a 403 for any non-GET request with a foreign or opaque `Origin` (CSRF: a multipart upload is a simple request any page can send). `tests/test_local_only.py` covers both. P4's login and deployment hosts replace them.
- `search` returns no hits, without embedding the question, when the workspace has no chunks. `answer_from_hits(q, [])` returns `no_chunks` without calling `draft_answer`, so P2's split calls keep the rule.
- `check:backend` and `check:licenses` run through thin `scripts/check-backend.mjs` and `scripts/check-licenses.mjs` wrappers. They then match `checks.glob`, and the wiring check covers their CI steps. `.claude/harness.json` only gains spend patterns and the `evidence` entry.
- Spend fixtures for the live config go into a project-owned `scripts/check-spend.mjs` (`check:spend`). `scripts/check-hooks.mjs` is a library template that `init --update-guard` overwrites.
- The paid HTTP routes count as spend too: a regex asks before a `curl`, `Invoke-RestMethod` or `Invoke-WebRequest` that posts to `/api/ask` or `/api/documents`.

## Phases

| Phase | Goal | Depends on | Check at the end |
|---|---|---|---|
| 1 | Backend skeleton, settings, schema, test database | none | `npm run check:backend` green with `tests/test_schema.py`; red with the command to start `testdb` when the container is stopped |
| 2 | Pure parts: parsing, chunking, OpenAI wrapper, license check, spend guard, decision record | phase 1 | `npm run check:backend`, `npm run check:licenses`, `npm run check:spend` green |
| 3 | Ingest, search, answering and the HTTP routes | phase 2 | `npm run check:backend` green with the documents, ingest, retrieval, answering and ask tests |
| 4 | Smoke command, CI, wiring, docs | phase 3 | `npm run check:all` green locally, wiring check green, CI green on the PR, then `npm run paid:smoke` (operator approves, needs `OPENAI_API_KEY`) |

## Parallel windows

The main session implements, one task after another. The tasks are small and share a design held in this plan; STATUS.md records that. Phase 2's tasks share no file, so a later session could dispatch them as one window.

| Window | Tasks | Shared files (must be none) |
|---|---|---|
| A | 2.1, 2.2, 2.3, 2.4, 2.6 | none |
| B | 2.5 | none in its window; it edits `package.json` after 2.4 |

## Handoff contracts

| From | To | Handoff |
|---|---|---|
| 1.1 | all | `loreos.settings` (`database_url()`, `openai_api_key()`, `openai_base_url()`, `embedding_model()`, `answer_model()`); `loreos.db.workspace_session(workspace_id)` yielding an `AsyncConnection` in one transaction; schema `loreos`; `tests/conftest.py` with `sql()`, fixtures `db` (session, migrated), `clean` (empties documents) and `fake_embed` (word-hash vectors, never zero; records its inputs) |
| 2.1 | 3.1 | `parsing.kind_of(filename, data) -> 'md'\|'txt'\|'pdf'`, `parse(filename, data) -> list[Section]`, `UnsupportedType`, `ParseError`; `tests/pdf.py` `make_pdf(pages) -> bytes` |
| 2.2 | 3.1 | `chunking.chunk(sections, max_tokens=CHUNK_TOKENS, overlap_tokens=CHUNK_OVERLAP) -> list[Chunk]` |
| 2.3 | 3.1 | `llm.client()`, `async llm.embed(texts)`, `async llm.draft_answer(question, hits) -> Draft`; tests patch `loreos.llm.embed` / `loreos.llm.draft_answer` |
| 3.1 | 4.1 | `ingest.ingest`, `ingest.find_by_sha`, `retrieval.search`, `answering.answer` |

## Tasks

### Task 1.1: Backend skeleton and schema

- Files owned: `backend/pyproject.toml`, `backend/uv.lock`, `backend/.python-version`, `backend/alembic.ini`, `backend/alembic/env.py`, `backend/alembic/versions/0001_initial.py`, `backend/loreos/{__init__,settings,db,workspaces,embeddings}.py`, `backend/tests/conftest.py`, `backend/tests/test_schema.py`, `docker-compose.yml`, `package.json` (`db:migrate`, `dev:api`)
- Depends on: none
- Change: a uv project with FastAPI, SQLAlchemy async, Alembic, asyncpg, openai, tiktoken and pypdf (dev: pytest). `env.py` creates schema `loreos` and keeps `alembic_version` there. The first migration creates `vector` if it is missing, the three tables and the default workspace. The conftest sets the test env, migrates `testdb`, and stops the run with the start command when `testdb` is unreachable.
- Acceptance check: `uv --directory backend run python -m pytest` (wired as `check:backend` in 2.4). `test_schema.py` proves the `(document_id, workspace_id)` foreign key rejects a chunk whose workspace differs from its document's, and that the default workspace exists. With `testdb` stopped, the run exits 1 and prints `docker compose --profile test up -d testdb`.
- Red first: with `testdb` stopped, exit 1 and the start command (seen). Before the migration, `test_schema.py` fails on `relation "loreos.chunks" does not exist`.
- Skills to load: none
- Predicted size: 14 files, about 300 lines, 60 minutes

### Task 2.1: Parsing

- Files owned: `backend/loreos/parsing.py`, `backend/tests/test_parsing.py`, `backend/tests/pdf.py`
- Depends on: 1.1
- Change: type detection by `.md`, `.markdown`, `.txt` or `.pdf`, or by a `%PDF-` header under any name. Markdown: front matter dropped, ATX headings outside fences, heading paths, text before the first heading under an empty path. TXT: one section. PDF: per page through pypdf, empty pages skipped, and a textless PDF fails with "no extractable text (scanned PDF?)".
- Acceptance check: `test_parsing.py` (rows 5 to 7): front matter dropped; `#` in a fence is not a heading; nested paths with a sibling popping the stack; preamble under `[]`; `.markdown` and a header-only PDF named `x.bin` detected; TXT gives one section; PDF pages numbered from 1 with the empty middle page skipped; a textless PDF fails with its message; `.docx` raises `UnsupportedType`.
- Red first: against a stub `parse` that returns `[Section([], None, text)]`, the heading-path and page assertions fail.
- Skills to load: none
- Predicted size: 3 files, about 200 lines, 40 minutes

### Task 2.2: Chunking

- Files owned: `backend/loreos/chunking.py`, `backend/tests/test_chunking.py`
- Depends on: 1.1
- Change: per section, one chunk when it fits. Otherwise the text splits at paragraphs, then sentences, then token windows, each piece within `max_tokens - overlap_tokens`. Pieces pack greedily on the real token count, and every later chunk starts with the previous chunk's last tokens.
- Acceptance check: `test_chunking.py` (row 8): no chunk crosses a section; every `token_count <= max_tokens` and equals the real count; a section that fits is one chunk equal to its text; a split section's later chunks start with the tail of the one before; the first chunk of the next section carries no tail; a split falls on a paragraph break when one fits; ordinals run 0..n-1.
- Red first: against a stub chunker that never splits, the budget assertion fails.
- Skills to load: none
- Predicted size: 2 files, about 150 lines, 40 minutes

### Task 2.3: OpenAI wrapper

- Files owned: `backend/loreos/llm.py`, `backend/tests/test_no_openai.py`
- Depends on: 1.1
- Change: `client()` builds an `AsyncOpenAI` from `settings` on each call. `embed` batches its inputs and checks the vector length against `EMBEDDING_DIM`. `draft_answer` asks for structured output `{found, text}` over numbered passages, and its error says when the server does not support structured output.
- Acceptance check: `test_no_openai.py` (row 15): the client built under the test env points at the local unroutable base URL, and one embeddings call with `max_retries=0` raises `APIConnectionError` in under a second.
- Red first: with `OPENAI_BASE_URL` left out of the conftest, the base-URL assertion fails (and without the fake key, `client()` raises the missing-key error).
- Skills to load: none
- Predicted size: 2 files, about 110 lines, 30 minutes

### Task 2.4: License check and backend wiring

- Files owned: `backend/check_licenses.py`, `backend/tests/test_licenses.py`, `scripts/check-backend.mjs`, `scripts/check-licenses.mjs`, `package.json` (`check:backend`, `check:licenses`)
- Depends on: 1.1
- Change: the check reads every installed distribution's `License-Expression`, then its `License` field and license classifiers. It fails on GPL, AGPL, LGPL, SSPL, EUPL, MPL, EPL, CDDL, OSL, CECILL or CC-BY-SA, and on a package that declares no license. The only exception is `certifi` with MPL-2.0. The two `.mjs` wrappers run the uv commands and pass the exit code through.
- Acceptance check: `npm run check:licenses` exits 0 (row 19). `test_licenses.py` shows an `AGPL-3.0` fixture entry fails, an MPL-2.0 entry not named certifi fails, a package with no license fails, and certifi passes.
- Red first: against a stub that allows everything, the AGPL assertion fails.
- Skills to load: none
- Predicted size: 5 files, about 100 lines, 25 minutes

### Task 2.5: Spend guard for paid modules and routes

- Files owned: `.claude/harness.json` (`spend.patterns`, `evidence`), `scripts/check-spend.mjs`, `package.json` (`check:spend`, after 2.4), `docs/KNOWN-GAPS.md`
- Depends on: none
- Change: spend regexes for `-m loreos.(smoke|evaluation|demo)` and for a `curl` that posts (`-F`, `-d`, `--data*`, `--json`, `-X POST`) to `/api/ask` or `/api/documents`, plus `Invoke-RestMethod`/`Invoke-WebRequest` with `-Method Post`. `check-spend.mjs` replays payloads through `.claude/hooks/guard.mjs` against the live config. Asks: `uv run python -m loreos.smoke`, `python -m loreos.evaluation`, a curl upload, an Invoke-RestMethod ask. No decision: `uv --directory backend run python -m pytest`, `npm run check:backend`, `curl http://127.0.0.1:8000/api/documents`, `grep -rn loreos.smoke`. The `evidence` entry names the `loreos.documents` columns and the api log. The KNOWN-GAPS spend row goes, and the product-code row narrows to the frontend (P4).
- Acceptance check: `npm run check:spend` green (row 17).
- Red first: before the patterns are added, the `python -m loreos.smoke -> ask` and curl-upload fixtures fail.
- Skills to load: none
- Predicted size: 4 files, about 60 lines, 20 minutes

### Task 2.6: Library decision record

- Files owned: `docs/decisions/0002-parsing-and-driver-libraries.md`
- Depends on: none
- Change: names the library and license for each v1 file type plus the driver (behaviour 20), the certifi exception, and the `loreos` schema with the reason for it.
- Acceptance check: none a check could observe; `npm run check:hooks` stays green.
- Red first: n/a (docs)
- Skills to load: none
- Predicted size: 1 file, about 40 lines, 10 minutes

### Task 3.1: Ingest, search, answering, routes

- Files owned: `backend/loreos/{ingest,retrieval,answering,main}.py`, `backend/tests/{test_documents_api,test_ingest,test_retrieval,test_answering,test_ask_api,test_config}.py`
- Depends on: 2.1, 2.2, 2.3
- Change: `ingest` does find-or-insert by sha256, then parse, chunk, embed and store, with a status per stage. `search` runs an exact cosine scan joined to filenames. `answer_from_hits` maps `[n]` markers, drops markers out of range, refuses with a reason and logs one line. The routes follow the spec, with a 20 MB cap, 415 or 413 before any write, 201 for new documents and 200 for duplicates.
- Acceptance check: `npm run check:backend`.
  - `test_documents_api.py` covers rows 1 to 4: md, `.markdown`, txt and pdf reach `processed`; 413 and 415 write no row; a duplicate returns 200 with the same id and no embed call; a failed duplicate is reprocessed with `attempts` 2; an embedder that raises leaves `embed:` and zero chunks.
  - `test_ingest.py` covers rows 4 and 9: the embed input carries the heading line and the stored text does not; an ingest run twice keeps the chunk count; a store failure after a partial insert leaves `store:` and zero chunks; an `sk-` key in an error is scrubbed.
  - `test_retrieval.py` covers row 10: the matching chunk ranks first, scores descend, at most k hits come back, and another workspace's chunks are excluded.
  - `test_answering.py` covers rows 11 and 12: markers map to the right chunks; out-of-range markers are removed; no valid marker gives `REFUSAL` and `no_valid_citation`; not found gives `model_not_found`; `[]` hits give `no_chunks` without a `draft_answer` call; the log line carries the reason.
  - `test_ask_api.py` covers row 13: blank gives 422; an empty workspace gives `no_chunks` with neither fake called; a full ask returns citations.
  - `test_config.py` covers rows 14 and 21: `dev:api` binds `--host 127.0.0.1`; the `.env.example` keys equal the keys `settings.py` reads, and its model defaults equal `settings.py`'s.
- Red first: each spec row's assertion fails against the module as first stubbed (for example, `search` without `order by` fails the ranking test, and an ingest without the savepoint fails the store-failure test).
- Skills to load: none
- Predicted size: 10 files, about 550 lines, 100 minutes

### Task 4.1: Smoke, CI, wiring, docs

- Files owned: `backend/loreos/smoke.py`, `package.json` (`paid:smoke`, `check:all`), `.github/workflows/ci.yml`, `.env.example`, `.gitignore`, `docs/sdd/p1-thin-slice/STATUS.md`
- Depends on: 3.1, 2.4, 2.5
- Change: the smoke preflight checks that `DATABASE_URL` connects, the migration is at head, and the key is set and accepted by the free `models.list`. It then creates a throwaway workspace with one inline Markdown document, asks one answerable and one unanswerable question, and deletes the workspace in `finally`. The CI `backend` job uses `astral-sh/setup-uv` with a `pgvector/pgvector:pg17` service on port 54329. `check:all` appends `check:spend`, `check:backend` and `check:licenses`.
- Acceptance check: `npm run check:all` green, `node <harness>/scripts/check-wiring.mjs` green, the CI run on the PR green (row 18), then `npm run paid:smoke` (row 16, operator approval).
- Red first: the wiring check fails on `check:backend`, `check:licenses` and `check:spend` until each has a CI step.
- Skills to load: harness:spend-gated-runs (before `paid:smoke`)
- Predicted size: 6 files, about 150 lines, 40 minutes

## What this plan does NOT cover

- DOCX, URL import, worker, login, API keys, UI and the Docker image: P4.
- Keyword search, the reranker and chunk size tuning: P3. P3 also decides tqdm's MPL-2.0 when fastembed brings it in.
- A vector index: once a workspace passes about 50k chunks (`ponytail:` note in the migration).
- Connection pooling: once P4's worker and UI need throughput (`ponytail:` note in `db.py`).
- RLS: P4, inside `workspace_session`, so callers do not change.
