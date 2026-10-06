---
id: 0002
title: Parsing and driver libraries, the loreos schema
date: 2026-10-06
status: accepted
superseded_by:
---

# Parsing and driver libraries, the loreos schema

## Decision

The libraries for each v1 file type, and the database driver:

| Need | Library | License | Phase |
|---|---|---|---|
| PDF text | pypdf | BSD-3-Clause | P1 |
| Markdown sections | our own splitter in `backend/loreos/parsing.py` | MIT (ours) | P1 |
| TXT | the standard library | PSF | P1 |
| DOCX | python-docx | MIT | P4 |
| Single-URL import | httpx (or the OpenAI SDK's httpx2) to fetch, beautifulsoup4 to extract | BSD-3-Clause, MIT | P4 |
| Postgres driver | asyncpg | Apache-2.0 | P1 |
| Token counting | tiktoken (`cl100k_base`) | MIT | P1 |

`check:licenses` fails on any installed backend package that declares a strong or weak copyleft license, or none. The one exception is certifi under MPL-2.0. tiktoken needs it through requests, and an unmodified MPL file does not change LoreOS's MIT license. Nothing else is exempt. P3's fastembed brings in tqdm (MPL-2.0 AND MIT), and P3 decides that one on its own.

All LoreOS tables, including `alembic_version`, live in the Postgres schema `loreos`, never `public`.

## Why

- psycopg is LGPL-3.0; asyncpg is Apache-2.0 and async-native. Its prepared statements need the Supabase session pooler (port 5432), and `settings.database_url()` refuses port 6543 with that reason.
- PyMuPDF is AGPL. pypdf is pure Python and reads the text layer. OCR is out of scope.
- A Markdown library would give a token stream we would still have to walk for heading paths. The splitter is about thirty lines and is the part P3 tunes.
- On the project's Supabase database, default privileges grant `anon` full access to every table `postgres` creates in `public`, and the Data API exposes `public`. Until P4's RLS, a table there would let anyone holding the anon key read and change uploaded documents. A separate schema gets no such grants and is not exposed. It also avoids an unrelated empty `public.documents` that already exists there.

## Kill switch

None. Each choice is a dependency or a schema name. Changing one means a new decision and, for the schema, a migration.

## Reopen only if

A v1 file type needs a feature pypdf or python-docx cannot provide (OCR, reading order in multi-column PDFs). Or the deployment moves to a Postgres whose pooler cannot run prepared statements. Or certifi leaves the dependency tree, in which case the exception goes too.
