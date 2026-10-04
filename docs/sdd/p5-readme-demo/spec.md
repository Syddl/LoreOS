# Spec: P5 README and demo

Phase P5 of [the v1 brief](../v1/brief.md). Draft written before P1 started: when P5 starts, re-read it against what P1 to P4 built, then plan.

## Summary

The README explains what LoreOS does, how to run it, how retrieval works and how it scores. Its comparison table is generated from committed result files, and a check fails when the README's table differs from what the generator produces.
A demo workspace loads the evaluation corpus, and a recording shows a cited answer.
Kill switch: none. Docs and a loader script.

## Interfaces

| Interface | Kind | Owner file | Contract |
|---|---|---|---|
| `npm run readme:table` | root script | `scripts/readme-table.mjs` | Reads `eval/results/*.json`, takes the newest group of `vector`, `hybrid` and `hybrid_rerank` files sharing SHA, corpus hash, question hash and settings, and rewrites the README between `<!-- results:start -->` and `<!-- results:end -->`. No dependencies. |
| `check:readme` | check | `scripts/check-readme.mjs` | Builds the same table in memory and fails, showing the difference, when the README's block differs. |
| `npm run paid:demo-load -- --workspace <id>` | root script | `python -m loreos.demo` | Ingests the fetched evaluation corpus into that workspace through the normal upload path. |
| README | doc | `README.md` | Sections below. |
| Recording | asset | `docs/assets/` | A GIF or short video of the UI answering a demo question with a citation open. |

README sections: what LoreOS is; quickstart with `docker compose up`; configuration (`DATABASE_URL` on a session pooler, `OPENAI_API_KEY`, model settings, `RERANK`, ports, running behind a TLS proxy); how retrieval works (chunking, vector search, keyword search, RRF, the reranker, citations and refusal); results (the generated table, the evaluation method, links to the result files and decision records); API with curl examples using a secret key; license.

## Behaviour

1. The table has one row per mode (vector only; + keyword search with RRF; + reranker) and columns Recall@5, MRR@10, citation accuracy, unanswerable refused, answerable wrongly refused, faithfulness and search p95 latency. Its caption names the commit, question count, corpus, models, chunk settings and judge agreement, every value read from the result files.
2. The generator exits non-zero with the reason when no complete group exists or the group mixes SHAs, corpus, questions or settings. It never fills a cell by hand or by default.
3. `check:readme` runs in `check:all` and CI. The AGENTS.md rule on README numbers now has a check behind it for the table; numbers in prose stay a review item.
4. Each claim in "how retrieval works" that a change helped links the result files that show it.
5. `paid:demo-load` is idempotent: running it twice adds nothing, because uploads dedupe by content.
6. The tagline and status line are rewritten for a working v1. The current tagline says "organization", a word the glossary replaces with "workspace". `docs/KNOWN-GAPS.md` is brought up to date.

## Acceptance checks

| # | Behaviour | Check | Expected | Does NOT exercise |
|---|---|---|---|---|
| 1-3 | Generated table | `npm run check:readme` | Passes on the committed README; a fixture README with one number edited fails and shows the cell | Numbers in prose |
| 2 | Refusal to mix | `scripts/check-readme.mjs` fixtures | A group mixing two SHAs or missing a mode fails with the reason | |
| 5 | Demo load | `npm run paid:demo-load` twice (asks) | Second run adds no document and makes no embedding call; ledger row by hand | |
| 6 | Wording | Review | Glossary terms only | |

## Kill switch

None.

## Not changing

- No hosted public demo. Anyone could spend the owner's OpenAI budget through it, and the brief does not ask for one; the recording stands in.
- No new result files: P5 publishes P3's.
- Product code, except bugs the demo exposes, which go through their own fix.

## Risks

- A README drafted before the final results would tempt hand-written numbers; the table block stays empty until `readme:table` fills it.
- Committing a result file must stay possible while edit tools are denied on `eval/results/`: the run writes the file and the operator stages it by path.
