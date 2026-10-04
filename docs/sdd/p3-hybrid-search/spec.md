# Spec: P3 keyword search with RRF, then a reranker

Phase P3 of [the v1 brief](../v1/brief.md). Draft written before P1 started: when P3 starts, re-read it against what P1 and P2 built, then plan. P3 can run beside P4 once P2 is merged.

## Summary

P3 settles the default chunk size and overlap by measurement. It then adds keyword search (Postgres full-text search) merged with vector search by reciprocal rank fusion, and a local cross-encoder reranker run through fastembed on CPU.
Every step leaves a committed result file, and the mode the server uses by default is the one the results support.
Kill switch: `RERANK=off` skips the reranker and serves the fused order (operational risk: CPU, memory and the model download on a small host).

## Interfaces

| Interface | Kind | Owner file | Contract |
|---|---|---|---|
| `chunks.tsv` | column, migration | `backend/alembic/versions/` | `tsvector` generated and stored from the heading path and chunk text with the `english` configuration; GIN index. |
| `keyword_search(session, workspace_id, query, n) -> list[Hit]` | function | `backend/loreos/retrieval.py` | Matches chunks holding any of the question's lexemes, ranked by `ts_rank_cd`. |
| `rrf(rankings, k=60) -> list[id]` | function | `backend/loreos/fusion.py` | Pure. Score is the sum of 1 / (k + rank). Ties break by best single rank, then chunk id, so the order is deterministic. |
| `rerank(query, hits) -> list[Hit]` | function | `backend/loreos/rerank.py` | fastembed `TextCrossEncoder`; model name in `RERANK_MODEL` in this file; loaded once per process. |
| `search(session, workspace_id, query, k, mode=DEFAULT_MODE)` | function | `backend/loreos/retrieval.py` | `mode` is `vector`, `hybrid` or `hybrid_rerank`. `DEFAULT_MODE` lives in this file. |
| `RERANK` | env | `backend/loreos/settings.py` | `on` (default) or `off`. |
| `Answer.retrieval_mode` | field | `backend/loreos/answering.py` | The mode that served the answer; `POST /api/ask` returns it. |
| `--mode vector\|hybrid\|hybrid_rerank\|all`, `--chunk-tokens`, `--chunk-overlap` | CLI flags | `python -m loreos.evaluation` | `all` runs the three modes from one SHA and writes three result files. Chunk flags feed the evaluation workspace key. |
| Decision records | docs | `docs/decisions/` | One for chunk size and overlap, one for the reranker model and the default mode, each citing its result files by name. |

## Behaviour

1. Keyword search returns chunks in the workspace holding any lexeme of the question, ranked by `ts_rank_cd`. A question of stop words only returns no hits. It is called keyword search everywhere: Postgres ranking uses no corpus-wide statistics.
2. Terms are ORed, not ANDed: `websearch_to_tsquery` alone ANDs every word of a full question and matches almost nothing.
3. Chunk size is measured first, in `vector` mode, at three settings (about 250/25, 500/50 and 1000/100 tokens). The best Recall@5, with MRR@10 breaking ties, becomes `CHUNK_TOKENS` and `CHUNK_OVERLAP` in `chunking.py`, recorded in a decision with the three result files.
4. `hybrid` fuses the top 50 vector hits and the top 50 keyword hits with RRF (k = 60) and returns the top `k`.
5. `hybrid_rerank` rescores the top 30 fused candidates with the cross-encoder on (question, heading path and chunk text) and returns the top `k` by that score.
6. The reranker model is one fastembed supports, runs on CPU through onnxruntime (no PyTorch), is small enough for the dev machine's disk, and has a license that allows MIT distribution: a non-commercial model is excluded. The decision record names the model, its size and its license.
7. With `RERANK=on`, the api and worker load the model at startup and exit with the corrective action when they cannot (no network for the first download, corrupt cache). With `RERANK=off`, a `hybrid_rerank` request serves `hybrid` and the response's `retrieval_mode` says so.
8. The evaluation refuses to run `hybrid_rerank` or `all` while `RERANK=off`, so a result file is never labeled with a mode it did not run.
9. Result files record search latency p50 and p95 per mode, so the reranker's cost shows beside its gain.
10. After the chunk decision, one `--mode all` run from a single SHA writes the three rows the README compares. `DEFAULT_MODE` becomes the best of them, recorded in the second decision.

## Acceptance checks

| # | Behaviour | Check | Expected | Does NOT exercise |
|---|---|---|---|---|
| 1-2 | Keyword search | `npm run check:backend`, `tests/test_keyword_search.py` | An exact product term found by keyword search and missed by the fake vector order; a stop-word question returns none; another workspace's chunk never returned | Ranking quality (eval) |
| 1 | Generated column | `tests/test_migrations.py` | `tsv` filled on insert and on existing rows after upgrade | |
| 4 | Fusion | `tests/test_fusion.py` | Hand-computed RRF order, ties stable | |
| 5-6 | Reranker | `tests/test_rerank.py` | The real model scores a relevant pair above an irrelevant one (free model download on first run) | Latency on the deploy host |
| 7 | Kill switch | `tests/test_rerank_switch.py` | `RERANK=off` serves hybrid and reports it; `on` with a broken cache exits with the message | |
| 8 | Honest labels | `tests/test_eval_modes.py` | `--mode all` with `RERANK=off` stops before any paid call | |
| 3 | Chunk measurement | three `npm run paid:eval -- --mode vector --chunk-tokens ...` runs (each asks) | Three committed result files and the decision; ledger rows by hand | Chunk size for hybrid modes |
| 10 | Comparison | `npm run paid:eval -- --mode all` (asks) | Three committed result files sharing SHA, corpus hash and question hash | |

## Kill switch

`RERANK=off`, default `on`. The reranker adds CPU, memory and a model download to every host; when that is wrong for a host, `off` restores the fused order without a deploy. It defaults to `on` only if the committed results show a gain; otherwise `DEFAULT_MODE` is `hybrid` and the reranker stays measurable but unused.

## Not changing

- The answer step, refusal wording and citation rules from P1.
- No similarity threshold for refusal. Add one only if P2 or P3 results show unanswerable questions answered, and measure it like any other change.
- Workspaces, worker, auth and UI: P4 owns those files in the same window.

## Risks

- onnxruntime may lag the pinned Python version; P1 pinned it with that in mind.
- Chunk size is chosen in vector mode only; the best size for the hybrid modes may differ. The README says which mode measured it.
- `english` text search stems English only; a non-English corpus gets weak keyword search.
- RRF k = 60 is the usual constant, not tuned here.
- P3 and P4 run in parallel and both add Alembic migrations: whichever merges second rebases its revision onto the other's, or Alembic sees two heads. One owner per file: P3 owns `retrieval.py`, `fusion.py`, `rerank.py`, `answering.py` (where `retrieval_mode` joins `Answer`) and `evaluation/`; P4 owns everything else it touches. Both add a key to `settings.py`; the second to merge resolves that one line.
