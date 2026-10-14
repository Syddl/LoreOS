# Spec: P3 keyword search with RRF, then a reranker

Phase P3 of [the v1 brief](../v1/brief.md). The draft was written before P1 started. On 2026-10-14 it was revised against the code that P1, P2 and P4 merged; the section "Revised against P1, P2 and P4" lists each change.

## Summary

P3 settles the default chunk size and overlap by measurement. It then adds keyword search (Postgres full-text search), merged with vector search by reciprocal rank fusion (RRF), and a local cross-encoder reranker run through fastembed on the CPU.
Every step leaves a committed result file, and the mode the server uses by default is the one the results support.
Kill switch: `RERANK=off` skips the reranker and serves the fused order. It covers the operational risks: CPU, memory and the model download on a small host.

## Interfaces

| Interface | Kind | Owner file | Contract |
|---|---|---|---|
| `chunks.tsv` | column, migration `0003` | `backend/alembic/versions/` | A `tsvector`, generated and stored, built with the `english` configuration from the heading path and the chunk text, with a GIN index. `array_to_string` is only stable, so the heading path goes through an immutable SQL function in `loreos`. Adding the column fills it on existing rows. |
| `keyword_search(session, workspace_id, query, n) -> list[Hit]` | function | `backend/loreos/retrieval.py` | The chunks holding any lexeme of the question, ranked by `ts_rank_cd`, at most `n`. |
| `rrf(rankings, k=RRF_K) -> list[tuple[uuid, float]]` | function | `backend/loreos/fusion.py` | Pure, with `RRF_K = 60`. A chunk's score is the sum of 1 / (k + rank) over the rankings it appears in, summed exactly. Ties break by the best single rank, then by chunk id, so the order is deterministic. It returns each id with its score, best first. |
| `rerank(query, hits) -> list[Hit]` | function | `backend/loreos/rerank.py` | Synchronous. It uses fastembed's `TextCrossEncoder`, with the model named in `RERANK_MODEL` in this file. `model()` loads it once per process. |
| `search(session, workspace_id, query, k, mode)` | function | `backend/loreos/retrieval.py` | `mode` is `vector`, `hybrid` or `hybrid_rerank`, and the function runs exactly that mode. `DEFAULT_MODE` lives in this file. |
| `serving_mode() -> str` | function | `backend/loreos/retrieval.py` | Returns `DEFAULT_MODE`, or `hybrid` when the default is `hybrid_rerank` and `RERANK=off`. |
| `RERANK` | env | `backend/loreos/settings.py` | `on`, the default, or `off`. Any other value is a startup problem that names the fix. |
| `Answer.retrieval_mode` | field | `backend/loreos/answering.py` | The mode that served the answer. `POST /api/ask` returns it through the route's existing field mapping. |
| `--mode vector\|hybrid\|hybrid_rerank\|all`, `--chunk-tokens N`, `--chunk-overlap N` | CLI flags | `python -m loreos.evaluation` | `all` runs the three modes from one SHA and writes three result files. The chunk flags set the chunker's budget for the run, so they feed the evaluation workspace key and the result's `settings`. npm swallows each one when it is given before `--`, so they join `NPM_SWALLOWED`. |
| `fastembed` | dependency | `backend/pyproject.toml`, `uv.lock` | Version 0.9.0 at the revision, with onnxruntime 1.31.0. Both resolve for Python 3.14 on Windows and on manylinux. |
| Image | build | `Dockerfile` | Bakes the model under `FASTEMBED_CACHE_PATH` only when `DEFAULT_MODE` is `hybrid_rerank`, as it does for tiktoken's encoding, so a container never downloads it at runtime. |
| Decision records | docs | `docs/decisions/` | 0009 records the chunk size and overlap. 0010 records the reranker model and the default mode. Each one cites its result files by name. |

## Behaviour

1. Keyword search returns the chunks in the workspace that hold any lexeme of the question, ranked by `ts_rank_cd`.
   - The terms are ORed, not ANDed. `websearch_to_tsquery` alone ANDs every word of a full question and matches almost nothing.
   - The lexemes are the ones `plainto_tsquery('english', question)` produces, with its ANDs turned into ORs. They are stemmed once, and no character of the question is parsed as query syntax.
   - A question made only of stop words returns no hits.
   - It is called keyword search everywhere, since Postgres ranking uses no corpus-wide statistics.
2. Chunk size is measured first, in `vector` mode, at three settings: 250/25, 500/50 and 1000/100 tokens. All three runs use one SHA and differ only in their flags.
   - The best Recall@5 wins, and MRR@10 breaks a tie. When both tie, the smaller chunk wins, since it sends fewer tokens to the answer model.
   - The winner becomes `CHUNK_TOKENS` and `CHUNK_OVERLAP` in `chunking.py`, recorded in decision 0009 with the three result files.
3. `hybrid` fuses the top 50 vector hits and the top 50 keyword hits with RRF (k = 60) and returns the top `k`. Each hit's `score` is its RRF score.
4. `hybrid_rerank` rescores the top 30 fused candidates with the cross-encoder and returns the top `k` by that score.
   - Each candidate is scored on the question paired with the same text the chunk was embedded from: the heading path, a blank line, then the chunk text.
   - Inference runs in a worker thread, so the api's event loop keeps serving other requests.
5. The reranker model meets four conditions:
   - fastembed supports it;
   - it runs on the CPU through onnxruntime, without PyTorch;
   - it is small enough for the dev machine's disk;
   - its license allows MIT distribution, so a non-commercial model is excluded.

   The model is `Xenova/ms-marco-MiniLM-L-6-v2` (Apache-2.0, 0.08 GB). fastembed cuts each (question, passage) pair at 512 tokens, so the reranker reads only the start of a long chunk. Decision 0010 records the model, its size, its license, the cut and the measured latency.
6. The api loads the model at startup only when the default mode needs it, that is when `DEFAULT_MODE` is `hybrid_rerank` and `RERANK=on`.
   - When the model cannot load, the api refuses to start and gives the corrective action:
     - the first download needs network access;
     - a corrupt cache is fixed by deleting the cache directory it names;
     - `RERANK=off` serves without the reranker.
   - The worker never searches, so it never loads the model.
   - With `RERANK=off`, answers are served by `hybrid`, and `retrieval_mode` says `hybrid`.
7. The evaluation keeps every result file's mode label true:
   - With `RERANK=off`, it refuses `--mode hybrid_rerank` and `--mode all` before the preflight, so a file is never labelled with a mode it did not run.
   - For those two modes, the preflight loads the model. The load is free, and it runs before any paid call, so a missing network stops the run before it spends.
8. Every result file records search latency p50 and p95. The timing covers what one search does in that mode: the question's embedding, the queries, and the rerank. So the reranker's cost shows beside its gain.
9. After decision 0009, one `--mode all` run from a single SHA writes the three rows the README compares. `DEFAULT_MODE` is chosen from those rows and recorded in decision 0010:
   - It is the mode with the best Recall@5, with MRR@10 breaking a tie.
   - A slower mode must beat a faster one on one of the two metrics without losing on the other. Otherwise the faster mode wins.
   - The operator can veto the choice before it merges.

## Acceptance checks

| # | Behaviour | Check | Expected | Does NOT exercise |
|---|---|---|---|---|
| 1 | Keyword search | `npm run check:backend`, `tests/test_keyword_search.py` | Expected: <ul><li>keyword search finds an exact product term that the fake vector order misses;</li><li>a question of stop words only returns no hits;</li><li>a question holding `&`, `\|`, `!`, `:` or `'` neither errors nor fails to match;</li><li>it never returns another workspace's chunk, under `loreos_app`.</li></ul> | Ranking quality (that is the evaluation's job) |
| 1 | Generated column | `tests/test_schema.py` | `tsv` is filled on insert, from the heading path and the text, and the GIN index exists. | Rows that existed before the upgrade (next row) |
| 1 | Existing rows | `npm run db:migrate` on Supabase, then `select count(*) from loreos.chunks where tsv is null` (free) | 0, since Postgres computes a stored generated column for every existing row when the column is added. Ledger row by hand. | |
| 3 | Fusion | `tests/test_fusion.py` | A hand-computed RRF order, with stable ties. | |
| 3, 4 | Modes | `tests/test_retrieval.py` | `hybrid` returns a chunk that only keyword search found. `hybrid_rerank` reorders by a fake scorer and keeps the top `k`. A workspace without chunks buys no embedding in any mode. | |
| 4, 5 | Reranker | `tests/test_rerank.py` | The real model scores a relevant pair above an irrelevant one. The first run downloads the model, which is free. | Latency on the deploy host |
| 6 | Kill switch and startup | `tests/test_rerank_switch.py` | `RERANK=off` serves `hybrid`, and the ask response says so. With `on` and a broken cache, the api refuses to start with the message. The worker starts without loading the model. A bad `RERANK` value is a startup problem. | |
| 6 | Ask response | `tests/test_ask_api.py` | `retrieval_mode` is in the response. | |
| 7 | Honest labels | `tests/test_eval_cli.py`, `tests/test_eval_run.py` | `--mode all` and `--mode hybrid_rerank` with `RERANK=off` stop before the preflight. A chunk flag before `--` is refused with the separator form. The chunk flags change the workspace key and the result's `settings`. | |
| 5 | Licenses | `npm run check:licenses` | fastembed's tree passes; tqdm passes under decision 0007. | |
| 2 | Chunk measurement | three `npm run paid:eval -- --mode vector --chunk-tokens ... --chunk-overlap ...` runs (each asks) | Three committed result files, one SHA, and decision 0009. Ledger rows by hand. | Chunk size for the hybrid modes |
| 9 | Comparison | `npm run paid:eval -- --mode all` (asks) | Three committed result files sharing the SHA, the corpus hash and the question hash, and decision 0010. | |
| 6 | Image | `npm run check:compose` (its own CI job), when the model is baked | The api is healthy with the model loaded from the image and no network for the model. | |

## Spend

Each run asks first, and each gets a priced estimate from its `--dry-run` plan before it is approved. The cap is the operator's $5 (decision 0005); $0.28 had been spent when P3 started.

| Run | Estimate |
|---|---|
| Chunk sweep: three `vector` runs | about $0.10, $0.13 and $0.20 for 250, 500 and 1000 tokens. Most of that is answer input, and P2's 500-token run cost $0.126. |
| `--mode all` at the chosen size | three times that size's run: about $0.30 to $0.60 |
| Corpus embedding | about $0.004 per new workspace (195,274 tokens) |

That is about $0.85 to $1.05 in all, or $1.25 with one rerun.

## Kill switch

`RERANK=off`, which defaults to `on`. The reranker adds CPU, memory and a model download to every host. When that is wrong for a host, `off` restores the fused order without a deploy. `DEFAULT_MODE` is `hybrid_rerank` only if the committed results show a gain under behaviour 9. Otherwise it is `hybrid` or `vector`, and the reranker stays measurable but unused, so the api never loads it.

## Not changing

- The answer step, the refusal wording and the citation rules from P1.
- No similarity threshold for refusals. Add one only if P2 or P3 results show unanswerable questions answered, and measure it like any other change. P2's baseline refused all 15 unanswerable questions.
- Workspaces, the worker, auth and the UI. `retrieval_mode` reaches the client through the ask route's existing mapping, and the UI does not show it.

## Risks

- **Reranker latency.** On the dev machine, the chosen model scored 30 passages of about 500 tokens in 2.3 to 2.7 s. The question's embedding already takes about 1.3 s at p50 (P2's baseline). Behaviour 9 weighs that latency, and `RERANK=off` drops it.
- **Memory.** The model and an onnxruntime session add a few hundred MB to the api process.
- **Chunk size is chosen in vector mode only.** The best size for the hybrid modes may differ. The README says which mode measured it.
- **The 512-token cut.** If decision 0009 picks 1000-token chunks, the reranker reads about the first half of each one. fastembed sets the cut from the model's tokenizer config and has no option to change it. Decision 0010 states the cut beside the gain.
- **Stemming.** `english` text search stems English only, so a non-English corpus gets weak keyword search.
- **RRF k = 60** is the usual constant. It is not tuned here.
- **The generated column must be immutable.** `to_tsvector(regconfig, text)` is immutable, but `array_to_string` is only stable, hence the wrapper function. The migration grants `loreos_app` execute on it, and `db:verify-rls` checks that grant. Without it, the first chunk insert would fail after its embedding was paid for.
- **Evaluation workspaces.** The sweep adds three `eval-*` workspaces of about 10 MB each, which meets the KNOWN-GAPS trigger for pruning them. After the runs, read the database size, which is free. Prune only with the operator's yes, since pruning deletes data.
- **CI and the image.** `test_rerank.py` downloads 0.08 GB on every CI run unless the cache is kept. fastembed brings onnxruntime, numpy, tokenizers, huggingface-hub and pillow into the image, and the model too when it is baked.
- **Hugo shortcodes stay in chunk text.** That meets their KNOWN-GAPS trigger if shortcode tokens show up among keyword search's false hits. Check the hybrid run's misses for them.

## Revised against P1, P2 and P4

| Draft said | Now | Why |
|---|---|---|
| The api and the worker load the model at startup | The api only, and only when `DEFAULT_MODE` needs it | The worker never searches (P4's STATUS). The ask route has no mode parameter, so a default of `hybrid` never calls the reranker. |
| `search(..., mode=DEFAULT_MODE)` falls back when `RERANK=off` | `search` runs the mode it is given; `serving_mode()` applies the fallback for the api | The evaluation must never run a mode other than its label (behaviour 7), so the fallback lives only on the serving path. |
| `rerank` loaded and called inline | It runs in a worker thread | The api is async, and seconds of inference on the event loop would stall every other request. |
| The model left open | `Xenova/ms-marco-MiniLM-L-6-v2` | fastembed 0.9.0 lists 8 cross-encoders. `jina-reranker-v2-base-multilingual` is CC-BY-NC, and the BGE models are 0.6 to 2.3 GB. `jina-reranker-v1-turbo-en` advertises 8k tokens, but fastembed cuts it at 512 like the others. It was also slower: 3.1 s against 2.3 to 2.7 s for 30 passages, measured on the dev machine on 2026-10-14. |
| A generated column "from the heading path and chunk text" | It goes through an immutable SQL wrapper for the heading path | A generated column refuses a stable function. |
| `websearch_to_tsquery` with ORed terms | `plainto_tsquery`'s output with `&` turned into `\|` | Building the query by hand from the question's words would stem them twice and parse `&`, `\|` and `!` as operators. `plainto_tsquery` ignores punctuation, and its output quotes every lexeme. |
| The chunk flags "feed the evaluation workspace key" | They set the chunker's budget for the run, and `chunk()` reads its defaults when called | `chunk()` binds `CHUNK_TOKENS` as a default argument when Python defines it, so `ingest.run_stages` would ignore any flag. The key, the preflight's plan and the result's `settings` already read the module values. |
| No npm handling for the new flags | `--chunk-tokens` and `--chunk-overlap` join `NPM_SWALLOWED` | npm takes a flag given before `--` as its own config, and P2 refuses that for `--mode` and `--limit`. |
| "Result files record search latency per mode" as new work | It is already there: `search_ms`, p50 and p95, per file | P2 records it. P3's work is that the timing wraps the whole search in every mode. |
| P3 and P4 share files, and the second to merge rebases | P4 merged first, at `43b2281` | The migration is `0003`, on top of `0002_platform`. `settings.py`, `.env.example`, `tests/test_config.py` and `uv.lock` change here alone. |
| The image is left to whichever phase merges second | The `Dockerfile` bakes the model only when `DEFAULT_MODE` is `hybrid_rerank` | P4 left this line to P3 (P4 spec, Revised). |
| No spend estimate | The Spend section | Decision 0005 caps OpenAI at $5, and each run asks with a priced estimate. |
| P2 behaviour 5: any untracked file dirties the tree | An untracked `eval/results/*.json` does not | `--mode all` writes three files from one process, and the sweep runs three times at one SHA. Under P2's rule the second file would see the first as a dirty tree and go to scratch after paying. An uncommitted result is not code, so the SHA still names the code that produced it. A tracked change, or any other untracked file, still counts (plan review, blocker). |
