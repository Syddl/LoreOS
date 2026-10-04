# LoreOS

Read docs/sdd/v1/brief.md before any change: it holds the confirmed decisions and what v1 leaves out.

- Backend: Python, FastAPI, uv. Frontend and widget: TypeScript (strict), React, Vite.
- The database is any Postgres with pgvector, reached only through `DATABASE_URL`. No Supabase SDK, Auth or Storage.
- Call it "keyword search", never BM25.
- Never put a number in the README that a committed evaluation result file did not produce.
- No dependency under AGPL or another copyleft license.
- OpenAI calls cost money: run the evaluation on demand, never in a loop or on every push.
- No AI attribution anywhere: no Co-Authored-By trailers, no "Generated with" footers.
