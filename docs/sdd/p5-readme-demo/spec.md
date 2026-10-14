# Spec: P5 README and demo

Phase P5 of [the v1 brief](../v1/brief.md). The draft was written before P1 started. On 2026-10-14 it was revised against what P1 to P4 and P3 built; the section "Revised against P1 to P4" lists each change.

## Summary

The README explains:
- what LoreOS does;
- how to run it;
- how retrieval works;
- how it scores.

Its comparison table is generated from the committed result files of decision 0010, and a check fails when the README's table differs from what the generator produces.

A loader puts the evaluation corpus into a workspace the operator owns, and a recording shows the real UI giving a cited answer from it.

Kill switch: none. Docs, a check and a loader script.

## Interfaces

| Interface | Kind | Owner file | Contract |
|---|---|---|---|
| `npm run readme:table` | root script | `scripts/readme-table.mjs` | Reads `eval/results/*.json` and takes the newest complete group: one `vector`, one `hybrid` and one `hybrid_rerank` file sharing `git_sha`, `corpus_hash`, `questions_hash`, `calibration_hash` and `settings`, each with `destination` `results`. It rewrites `README.md` between `<!-- results:start -->` and `<!-- results:end -->`. No dependencies. |
| `check:readme` | check | `scripts/check-readme.mjs` | Builds the same block in memory and fails, showing the difference, when the README's block differs. It also fails on any glossary word listed under `avoid` in `.claude/harness.json`. Wired into `check:all` and CI before the end anchor. |
| `npm run paid:demo-load -- --workspace-id <id> [--dry-run]` | root script | `python -m loreos.demo` | A free preflight, then the paid part: each fetched corpus file through `ingest.ingest` into that workspace, inline, one file at a time. The flag is not `--workspace`, which is npm's own option. |
| The demo's cross-workspace read | `system_session()` | `backend/loreos/demo.py` | One read, as the connecting role: the `loreos.workspaces` row with that id, and whether it has an owner in `loreos.memberships`. `loreos_app` has no grant on either table. The ingest itself runs in `workspace_session`. |
| Decision 0011 | doc | `docs/decisions/0011-readme-numbers.md`, `AGENTS.md` | How the README-number rule is read: quality, latency and cost numbers come only from result files, while configuration facts come from the code. |
| README | doc | `README.md` | Sections below. |
| Recording | asset | `docs/assets/demo.gif` | The real UI on the operator's machine answering a question about the demo workspace, with a citation open. |

**README sections:**
- what LoreOS is;
- quickstart with `docker compose up`;
- configuration: `DATABASE_URL` on a session pooler, `OPENAI_API_KEY`, the model settings, `RERANK`, `ALLOWED_HOSTS`, and running behind a TLS proxy;
- how retrieval works: chunking, vector search, keyword search, RRF, the reranker, citations and refusal;
- results: the generated table, the evaluation method, links to the result files and the decision records;
- the API, with curl examples using a secret key;
- the demo;
- the license, the corpus's license included.

## Behaviour

1. **The table** has one row per mode:
   - vector only;
   - + keyword search with RRF;
   - + reranker.

   Its columns are Recall@5, MRR@10, citation accuracy, unanswerable refused, answerable wrongly refused, faithfulness, and search p50 and p95. The caption names the commit, the question count, the corpus files, the models, the chunk settings and the judge agreement, which is with Claude's grades (decision 0008). Every value comes from the result files.

   The row that matches `DEFAULT_MODE` in `backend/loreos/retrieval.py` is marked as the default, so the README cannot drift from the code.
2. **The generator refuses rather than guesses.** It exits non-zero with the reason in three cases:
   - no complete group exists;
   - a candidate group mixes SHAs, hashes or settings;
   - `DEFAULT_MODE` cannot be read.

   It never fills a cell by hand or by default. A missing metric prints as the file has it (`null` becomes "n/a"), never as 0.
3. **`check:readme` runs in `check:all` and in CI.** The AGENTS.md rule on README numbers now has a check behind it for the table.
   - **The rule** is read as numbers about quality, latency or cost, which only result files produce. Configuration facts, such as ports and caps, come from the code. Decision 0011 records this reading.
   - **Prose** carries no quality, latency or cost number, and points at the table instead. Prose stays a review item.
4. **Retrieval claims link their evidence.** Each claim in "how retrieval works" that a measurement supports links the decision and the result files that show it: decision 0009 for the chunk size, which was measured in `vector` mode, and decision 0010 for the default mode.
5. **`paid:demo-load` is idempotent.** Uploads dedupe by content within a workspace, so a second run adds no document and makes no embedding call. The free preflight checks these before the first paid call, and prints how many files and tokens it will embed. `--dry-run`, or `npm_config_dry_run=true`, stops there.
   - the database, the migration head, the grants and the key (smoke's preflight, which loads no reranker);
   - that the embedding model is in the API's model list;
   - the corpus files and their hashes;
   - that the workspace exists, is not an `eval-*` workspace (`workspaces.EVAL_PREFIX`), and has an owner.

   A file that is not processed is reported, and the run exits 1 after the last file.
6. **The wording is fixed.**
   - The tagline and the status line are rewritten for a working v1. The current tagline says "organization", which the glossary replaces with "workspace".
   - `docs/KNOWN-GAPS.md` is reread, and stale rows are corrected.

## Acceptance checks

| # | Behaviour | Check | Expected | Does NOT exercise |
|---|---|---|---|---|
| 1-3 | Generated table | `npm run check:readme` | Passes on the committed README. Its inline fixture cases, replayed the way `check-spend.mjs` replays its own, show that a README with one number edited fails and names the cell. | Numbers in prose |
| 2 | Refusal to mix | the same fixtures | A group that mixes two SHAs, or lacks a mode, fails with the reason. An unreadable `DEFAULT_MODE` fails. | |
| 3 | Glossary | the same fixtures | A README saying a word the glossary avoids fails and names it. | Synonyms not listed |
| 5 | Demo loader | `tests/test_demo.py`, with the fakes | A second run embeds nothing. An `eval-*` or unknown workspace, or a missing corpus file, stops before any embedding. `--dry-run` embeds nothing. | Real OpenAI |
| 5 | Demo load, live | `npm run paid:demo-load` twice (each asks) | The first embeds about 195k tokens, about $0.004. The second adds no document. Ledger rows by hand. | |
| 4, 6 | Wording and links | review | Glossary terms only, and links resolve | |
| | Recording | by hand, the operator logged in | `docs/assets/demo.gif` shows a cited answer with its passage open. It is recorded under 640 px wide, so the header hides the email, and every frame is checked for personal data before staging. The ledger names the question asked. | |

## Spend

- **The demo load:** the corpus embedding, about 195k tokens, about $0.004. The second run is free.
- **The recording:** each question is one embedding plus one answer, about $0.002. It is asked through the browser, which the guard cannot see, so the operator approves the number of questions in chat first.
- **The total** is under $0.02, against $1.17 spent of the $5 cap (decision 0005).

## Kill switch

None.

## Not changing

- **No hosted public demo.** Anyone could spend the owner's OpenAI budget through it, and the brief does not ask for one; the recording stands in.
- **No new result files.** P5 publishes P3's.
- **No product code**, except bugs the demo exposes, which go through their own fix.

## Risks

- **Hand-written numbers.** A README drafted before the generator exists would tempt them, so the table block stays empty until `readme:table` fills it.
- **The recording needs a browser session.** The operator logs in, since the agent never types their password, and then the agent drives. If the browser extension is not connected, the fallback is a screenshot sequence the operator takes.
- **The demo workspace holds CC BY-SA 4.0 text** (decision 0003). The README's license section says so.

## Revised against P1 to P4

| Draft said | Now | Why |
|---|---|---|
| `paid:demo-load` "through the normal upload path" | Inline `ingest.ingest`, as the evaluation does, after a free preflight with `--dry-run` | The upload route only queues; `paid:worker` embeds. Inline keeps it to one paid command and one approval, and still dedupes by content. |
| The group shares SHA, corpus hash, question hash and settings | It also shares `calibration_hash`, and every file's `destination` is `results` | Faithfulness and judge agreement depend on the calibration rows. Only committed results may reach the README. |
| Columns end at p95 latency | p50 and p95 | Decision 0010 weighs the reranker's median cost. |
| No marker for the serving mode | The row matching `retrieval.DEFAULT_MODE` is marked | One owner per fact: the code declares the default, and the README reads it. |
| `check:readme` covers the table | It also covers the glossary | AGENTS.md and the glossary forbid "BM25", "tenant", "organization", "benchmark" and "test set", and the current tagline breaks that rule. |
| A recording of "a demo question" | The real UI, logged in by the operator, with the questions approved in chat | The agent never enters the operator's password, and the guard cannot see a question asked through the browser. |
| README configuration: ports | `ALLOWED_HOSTS` and the TLS proxy (`FORWARDED_ALLOW_IPS`) | P4 replaced hard-coded hosts with `ALLOWED_HOSTS`. KNOWN-GAPS records what a proxy needs. |
