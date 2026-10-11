# Brief: LoreOS v1

## What

A self-hostable document Q&A engine. A user uploads documents (PDF, Markdown, TXT, DOCX) or a single URL into a workspace, asks a question, and gets an answer that cites the passage it came from, or "I couldn't find this in your documents" when the documents don't say. The same engine is reachable through a web UI, an HTTP API with API keys, and an embeddable widget.

## Why now

Onyx, RAGFlow, AnythingLLM and Dify already serve organizations, and several repos named KnowledgeOS already ship this feature list. LoreOS is a learning build and reference implementation: its value is retrieval that is measured and explained, with every search change scored against a hand-written question set.

## Done means

- `docker compose up`, with `DATABASE_URL` and `OPENAI_API_KEY` set, starts the api and worker, and the UI loads in a browser.
- An uploaded file or URL reaches a "processed" state; a failed ingestion is retried, then marked failed with its error visible.
- A question returns an answer whose citations open the source passage (heading path, or page for PDFs).
- An unanswerable question returns "I couldn't find this in your documents."
- One command runs the evaluation and writes a result file with Recall@5, MRR, citation accuracy, refusal rates (unanswerable refused, answerable wrongly refused) and judge faithfulness.
- The README comparison table (vector only, + keyword with RRF, + reranker) comes only from committed result files.
- A test proves workspace A's credentials retrieve zero chunks from workspace B, enforced by Postgres row-level security.
- The widget works from a listed domain with a publishable key, is refused from an unlisted one, and returns 429 past its rate limit.

## Out of scope

- Website crawler, roles beyond owner/member, caching: later, each only when a need is shown.
- Separate services, Redis: no.
- Supabase Auth, Storage or SDK: the database is reached only through `DATABASE_URL`.
- Calling the keyword search BM25.

## Constraints

- The thesis comes first; LoreOS is side work.
- OpenAI calls cost money: evaluation runs on demand, never on every push.
- The dev machine has about 23 GB free on C:; no PyTorch install.
- Dependencies must allow MIT distribution: no AGPL (for example PyMuPDF).
- No AI attribution in commits, PRs or docs.

## Open questions

- Login method for the UI: email and password, decided in P4 ([decision 0006](../../decisions/0006-login-email-and-password.md)).
- Parsing libraries per file type (decided in P1, license checked).
- Default chunk size and overlap (measured in P3).

## Decisions confirmed by grilling

1. Headline: measured retrieval and the comparison table. Rejected: a breadth-first feature list, which existing clones already have.
2. Timing: thesis first; after P2, P3 and P4 can run in parallel sessions. Rejected: full-time now, with 27 thesis issues open.
3. Demo documents: a subset of the GitLab handbook plus a few public PDFs. The handbook's text is CC BY-SA 4.0, not MIT (MIT covers GitLab's software); the PDFs are US government works. [Decision 0003](../../decisions/0003-evaluation-corpus-and-judge.md) holds the details. Rejected: invented documents, which give no real exact-term questions.
4. v1 includes: PDF, Markdown, TXT, DOCX and single-URL import; our own chunker; vector plus keyword search merged with RRF; a local reranker; cited answers and "couldn't find this"; workspaces with RLS and an isolation test; a worker with retries; API keys; the UI; the widget in P6 with publishable keys, allowed domains and a rate limit in Postgres.
5. Crawler, extra roles and caching come later; separate services and Redis are out. Rejected: everything in v1, about a year of solo work.
6. Stack: backend in Python with FastAPI, uv, SQLAlchemy and Alembic; frontend and widget in strict TypeScript with React, Vite, Tailwind and shadcn, served by FastAPI. Rejected: Next.js (heavier, one more server process) and a TypeScript backend (weaker AI and evaluation libraries).
7. Data and models: Supabase Postgres with pgvector through `DATABASE_URL` and the session pooler; our own login in P4; OpenAI for embeddings and answers, with base URL and model names in settings; the reranker local through fastembed. Rejected: Supabase Auth/Storage/SDK (self-hosting would need the full Supabase stack), an LLM as reranker (slow, costs per query); OpenAI has no rerank API.
8. Chunking: our own, split by heading or PDF page, packed to a token budget with a small overlap, each chunk keeping its heading path or page. Rejected: LangChain splitters (pull in langchain-core; chunking is the part we need to explain and tune).
9. Keyword search: Postgres full-text search, called "keyword search". Rejected: calling it BM25, since Postgres ranking uses no corpus-wide statistics.
10. Evaluation: 60-100 questions (drafted by Claude at the operator's request, [decision 0004](../../decisions/0004-evaluation-set-drafted-by-claude.md); first chosen as hand-written), about 15 unanswerable, sources labeled by file and heading; retrieval and answer metrics as in "Done means"; the judge checked against 30 hand grades; runs on demand with results committed. Rejected: 500 LLM-generated questions (synthetic) and CI on every push (costs money, fork PRs get no secrets).
11. Build order: P1 thin slice (upload to cited answer), P2 evaluation harness and baseline, P3 keyword search with RRF then reranker, P4 platform shell (workspaces, worker, API keys, login, UI), P5 README and demo, P6 widget.
12. Repo: `Documents/code/loreos`, GitHub account Syddl, MIT, public after P1.
13. Name: LoreOS. Rejected: KnowledgeOS, already used by several repos with the same feature list.
