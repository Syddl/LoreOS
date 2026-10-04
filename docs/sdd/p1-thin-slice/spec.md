# Spec: P1 thin slice

Phase P1 of [the v1 brief](../v1/brief.md): upload to cited answer. Interfaces and acceptance checks; no line-number anchors. Next step after this spec: `plan.md`.

## Summary

A local API takes a Markdown, TXT or PDF upload, splits it into chunks that keep their heading path or page, embeds them with OpenAI into Postgres with pgvector, and answers a question with cited passages or with "I couldn't find this in your documents."
It serves one workspace on 127.0.0.1 with no login; ingestion runs inside the upload request.
Kill switch: none. P1 creates the system, so there is no earlier behaviour to restore.

## Interfaces

| Interface | Kind | Owner file | Contract |
|---|---|---|---|
| `DATABASE_URL` | env | `backend/loreos/settings.py` | Postgres URL; on Supabase the session pooler (port 5432). `postgresql://` is rewritten to the asyncpg driver. Unset: error "DATABASE_URL is not set; add the session pooler connection string to .env". |
| `OPENAI_API_KEY`, `OPENAI_BASE_URL` | env | `backend/loreos/settings.py` | Read when the first OpenAI client is built, never at import. Unset key: error naming the key. |
| `EMBEDDING_MODEL`, `ANSWER_MODEL` | env | `backend/loreos/settings.py` | Defaults live in `settings.py` and are copied into `.env.example`. The embedding model must return `EMBEDDING_DIM` (1536) dimensions. |
| `EMBEDDING_DIM` | constant | `backend/loreos/embeddings.py` | 1536; the one owner, read by the migration that creates `chunks.embedding`. |
| Schema | Alembic migration | `backend/alembic/versions/` | Tables below. Creates `vector` if missing (a no-op on Supabase, needed on the test database). |
| `parse(filename, data) -> list[Section]` | function | `backend/loreos/parsing.py` | `Section(heading_path: list[str], page: int \| None, text: str)`. Raises `UnsupportedType` or `ParseError` with a message a person can act on. |
| `chunk(sections, max_tokens, overlap_tokens) -> list[Chunk]` | function | `backend/loreos/chunking.py` | `Chunk(ordinal, text, heading_path, page, token_count)`. Tokens counted with tiktoken `cl100k_base`. Defaults `CHUNK_TOKENS = 500`, `CHUNK_OVERLAP = 50` in this file (measured in P3). |
| `embed(texts) -> list[list[float]]` | function | `backend/loreos/llm.py` | The only place embeddings are requested; batches the inputs. |
| `draft_answer(question, hits) -> Draft` | function | `backend/loreos/llm.py` | `Draft(found: bool, text: str)` through structured output. The only place answers are requested. |
| `workspace_session(workspace_id)` | async context manager | `backend/loreos/db.py` | The only way code reads or writes workspace data: one transaction, every query filtered by `workspace_id`. P4 adds the role switch and the RLS setting inside it, so callers do not change. |
| `ingest(session, workspace_id, filename, data) -> Document` | function | `backend/loreos/ingest.py` | Parse, chunk, embed, store; owns the status transitions. Replaces a document's chunks in one transaction, so a rerun is idempotent (P4's worker relies on this). |
| `search(session, workspace_id, query, k) -> list[Hit]` | function | `backend/loreos/retrieval.py` | `Hit(chunk_id, document_id, filename, heading_path, page, text, score)`; cosine similarity, exact scan. P3 adds a `mode` argument. |
| `answer_from_hits(question, hits) -> Answer` and `answer(session, workspace_id, question) -> Answer` | functions | `backend/loreos/answering.py` | `Answer(found, text, citations, reason)`. `answer` is `search` then `answer_from_hits`; P2 calls the two halves separately. |
| `REFUSAL` | constant | `backend/loreos/answering.py` | `I couldn't find this in your documents.` |
| `DEFAULT_WORKSPACE_ID` | constant | `backend/loreos/workspaces.py` | The workspace the first migration creates. P4 removes its use from routes. |
| `POST /api/documents` | route | `backend/loreos/main.py` | multipart `file`. 201 with the document; 200 with the existing document on a duplicate; 413 over 20 MB; 415 for other types. |
| `GET /api/documents`, `GET /api/documents/{id}` | route | `backend/loreos/main.py` | `{id, filename, kind, status, error, attempts, chunk_count, created_at, processed_at}` |
| `POST /api/ask` | route | `backend/loreos/main.py` | `{question}` to `{found, answer, reason, citations: [{n, chunk_id, document_id, filename, heading_path, page, text}]}` |
| Root scripts | package.json | `package.json` | `db:migrate`, `dev:api`, `check:backend`, `check:licenses`, `paid:smoke` |
| Test database | compose service | `docker-compose.yml` | `testdb` under profile `test`: pgvector image on the same Postgres major version as Supabase, bound to 127.0.0.1. P4 adds the app services to this file. |

Schema:

- `workspaces(id uuid pk, name text not null, created_at)`
- `documents(id uuid pk, workspace_id fk, filename text, kind text check (kind in ('md','txt','pdf')), sha256 text, content bytea, status text check (status in ('pending','processing','processed','failed')), error text null, attempts int default 0, created_at, processed_at null)`, `unique (workspace_id, sha256)`, `unique (id, workspace_id)`
- `chunks(id uuid pk, workspace_id, document_id, ordinal int, text text, heading_path text[] not null default '{}', page int null, token_count int, embedding vector(1536) not null)`, `unique (document_id, ordinal)`, foreign key `(document_id, workspace_id)` to `documents (id, workspace_id)` on delete cascade, so a chunk's workspace always equals its document's (P4's RLS policy reads that one column).
- No vector index: an exact scan keeps Recall@5 a measure of the retrieval method, not of an approximate index. Marked `ponytail:` in the migration; add HNSW when a workspace passes about 50k chunks, with iterative scan for the workspace filter.

## Behaviour

1. An upload of `.md`, `.markdown`, `.txt` or `.pdf` (a PDF also by its `%PDF-` header) up to 20 MB stores the file in `documents.content` and processes it inside the request; the response is 201 with status `processed` and `chunk_count > 0`.
2. Any other type gets 415 naming the accepted types; over 20 MB gets 413. Nothing is stored and nothing is spent.
3. The same bytes uploaded again to the same workspace return 200 with the existing document, with no new chunks and no OpenAI call. When the existing document is `failed`, it is processed again and `attempts` goes up by one.
4. A parse or embedding failure leaves the document `failed` with `error` holding the stage (`parse`, `embed`, `store`), the error class and its message, never a secret. The response is 201 with that status. No partial chunks remain.
5. Markdown: YAML front matter is removed; ATX headings (`#` to `######`) outside fenced code blocks start a section; a section's heading path is its ancestors plus its own heading; text before the first heading has an empty path.
6. TXT: one section with an empty heading path.
7. PDF: one section per page, numbered from 1, text from pypdf. A page with no extractable text yields no chunk; a PDF with no text at all fails with "no extractable text (scanned PDF?)". OCR is out of scope.
8. Chunking: a chunk never spans two sections. A section within `max_tokens` is one chunk. A longer one splits at paragraph breaks, then sentence ends, then at the token limit; each later chunk of that section starts with up to `overlap_tokens` from the end of the one before. No chunk exceeds `max_tokens`.
9. The embedding input is the heading path joined with ` > `, a blank line, then the chunk text. The stored `text` is the chunk text alone.
10. Ask embeds the question, takes the 5 chunks in the workspace with the highest cosine similarity, and asks the answer model to answer only from them, citing passages as `[n]` markers, or to report that they do not answer the question.
11. Citations come from the `[n]` markers in the answer text. Each `n` from 1 to 5 becomes a citation carrying that chunk's passage, filename, heading path and page; a marker outside that range is removed from the text.
12. When the model reports not found, or no valid marker remains, the response has `found: false`, `answer` exactly `REFUSAL`, no citations, and `reason` `model_not_found` or `no_valid_citation`. The reason is in the response and in the log line.
13. A blank question gets 422. A workspace with no chunks returns the refusal with reason `no_chunks` and makes no OpenAI call.
14. `npm run dev:api` binds 127.0.0.1 only. P1 has no login and every upload and question spends OpenAI money.
15. No check calls OpenAI: the test environment sets a fake key and points `OPENAI_BASE_URL` at an unroutable local address, and tests replace `embed` and `draft_answer` with deterministic fakes.
16. `npm run paid:smoke` runs a preflight before any paid call (DATABASE_URL connects, migrations at head, OPENAI_API_KEY set), then in a throwaway workspace uploads a fixture Markdown file, asks one answerable and one unanswerable question, prints the answers and citations, and deletes the workspace.
17. The spend guard also asks before a direct run of a paid entry module (`python -m loreos.smoke`, later `loreos.evaluation` and `loreos.demo`), not only `npm run paid:*`; that row leaves `docs/KNOWN-GAPS.md`.
18. `check:backend` runs pytest against the `testdb` container and fails with the command to start it when it is not running; it never skips the database tests. `check:all` and CI run it, CI with a pgvector service container.
19. `check:licenses` fails when an installed backend package declares a strong or weak copyleft license (GPL, AGPL, LGPL, SSPL, EUPL and the like). MPL-2.0 is allowed for `certifi` only, which the OpenAI SDK needs through httpx; see Risks. `check:all` and CI run it.
20. A decision record under `docs/decisions/` names the parsing and driver libraries for every v1 file type with their licenses: pypdf (BSD-3) for PDF, our own Markdown splitter, python-docx (MIT) and beautifulsoup4 (MIT) with httpx (BSD-3) for P4's DOCX and URL import, asyncpg (Apache-2.0) as the driver because psycopg is LGPL-3.0, tiktoken (MIT). This closes the brief's open question on parsing libraries.
21. `.env.example` is tracked and lists `DATABASE_URL`, `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `EMBEDDING_MODEL`, `ANSWER_MODEL`. The `evidence` entry in `.claude/harness.json` names the `documents` table (`status`, `error`, `attempts`) and the api log as the record of a failed ingestion.

## Acceptance checks

| # | Behaviour | Check | Expected | Does NOT exercise |
|---|---|---|---|---|
| 1 | Upload processed | `npm run check:backend`, `tests/test_documents_api.py` | Markdown, TXT and PDF fixtures reach `processed` with chunks stored | Real embeddings |
| 2 | 413, 415 | same file | Status codes; no row written | |
| 3 | Duplicate upload | same file | 200, same id, chunk count unchanged, fake embedder not called; a failed duplicate is reprocessed | |
| 4 | Failure recorded | same file, fake embedder that raises | `failed`, `error` starts with `embed:`, zero chunks | Real OpenAI error shapes |
| 5-7 | Parsers | `tests/test_parsing.py` | Front matter dropped; `#` inside a code fence is not a heading; nested heading paths; PDF pages numbered from 1; textless PDF fails with its message | Multi-column PDF reading order |
| 8 | Chunk boundaries | `tests/test_chunking.py` | No chunk crosses a section; all within budget; overlap present on split sections only | Whether 500/50 is a good default (P3) |
| 9 | Embedding input | `tests/test_ingest.py` | Fake embedder receives the heading path line; stored text has none | |
| 10-12 | Citations and refusal | `tests/test_answering.py` with a fake `draft_answer` | Markers map to the right chunks; out-of-range markers dropped; no valid marker gives `REFUSAL` and `no_valid_citation`; not found gives `model_not_found` | Answer quality (P2) |
| 13 | Empty cases | `tests/test_ask_api.py` | 422 for blank; `no_chunks` with no fake call | |
| 15 | No OpenAI from checks | `tests/test_no_openai.py` | A real client built under the test environment fails to connect within a second | A test that bypasses `llm.py` |
| 17 | Spend guard | `npm run check:hooks` with new fixtures | `python -m loreos.smoke` asks; `pytest` does not | Spend through other spellings the guard cannot see |
| 18 | Wiring | `npm run check:all`; CI run on the PR | Both run `check:backend` and `check:licenses` green | |
| 19 | Licenses | `npm run check:licenses` | Passes; a fixture metadata entry with `AGPL-3.0` fails it | Frontend packages (P4 adds them) |
| 16 | Real slice end to end | `npm run paid:smoke` (asks first; a few cents) | Answerable question cited, unanswerable refused; verification row added by hand | Retrieval quality at scale (P2) |

## Kill switch

None. P1 creates the system; there is no earlier behaviour to fall back to.

## Not changing

- No login, users, API keys, worker, Docker image or UI: P4.
- No DOCX or URL import: P4, with the worker and the URL fetch guard. P1 only records their libraries.
- No keyword search or reranker: P3.
- No README numbers: P5 generates them from result files.
- Files under `.claude/` other than the spend patterns, fixtures and `evidence` entry named above.

## Risks

- Python 3.14 is installed; asyncpg, tiktoken and P3's onnxruntime may lack wheels for it. P1 pins in `backend/.python-version` the newest version all P1 to P3 dependencies ship wheels for, and uv installs it.
- asyncpg uses prepared statements: fine on the session pooler, broken on the transaction pooler (port 6543). The settings error names the port when it sees 6543. `paid:smoke` and `db:migrate` exercise the real pooler.
- tiktoken downloads its encoding file on first use. CI needs network; P4's image bakes the file in.
- The license rule in AGENTS.md says "no copyleft". certifi (MPL-2.0, weak copyleft) is unavoidable with the OpenAI SDK, so the check allows it by name. The operator confirms or rejects that exception before the plan.
- Uploaded files live in `documents.content`. On a Supabase free plan the 500 MB database limit counts them; the eval corpus is small, so this matters only for heavy use.
- The GitLab handbook uses Hugo shortcodes (`{{< ... >}}`) that stay in the chunk text; P2 decides whether the corpus fetch strips them.
- Setext headings (underlined with `===`) are not recognised; the handbook uses ATX headings.
- Structured output may be missing on servers behind a non-OpenAI `OPENAI_BASE_URL`; the error says so.
- The test database's Postgres major version must match Supabase's; the plan reads it with `select version()`.
