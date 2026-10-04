# Spec: P2 evaluation harness and baseline

Phase P2 of [the v1 brief](../v1/brief.md). Draft written before P1 started: when P2 starts, re-read it against what P1 built, then plan.

## Summary

One command scores retrieval and answers against a hand-written evaluation set and writes a result file under `eval/results/`. P2 ends with the committed vector-only baseline.
Labels name a file and a heading or page, not a chunk, so they survive P3's chunk-size changes.
Kill switch: none. Offline tooling that changes no served behaviour.

## Interfaces

| Interface | Kind | Owner file | Contract |
|---|---|---|---|
| Corpus manifest | file format | `eval/corpus.json` | `{handbook: {repo, commit, paths: [...]}, pdfs: [{file, url, sha256}]}`. A corpus file is named by its path under `eval/corpus/`. |
| Corpus | directory | `eval/corpus/` (git-ignored) | Written by `eval:fetch`; never committed, so the corpus licenses never mix with the repo's. |
| Evaluation set | file format | `eval/questions.jsonl` | One object per line: `{id, question, answerable, sources: [{file, heading_path?: [...], page?: n}], note?}`. Unanswerable rows have `sources: []`. |
| Judge calibration | file format | `eval/judge_calibration.jsonl` | 30 rows `{id, question, passages: [...], answer, human: "faithful" \| "unfaithful"}`, graded by hand. |
| `npm run eval:fetch` | root script | `package.json` | Downloads the handbook files at the pinned commit and the PDFs; verifies each sha256. Free. |
| `npm run paid:eval -- --mode vector [--limit n] [--dry-run]` | root script | `package.json` to `python -m loreos.evaluation` | `--dry-run` runs the preflight only (free, exempt from the spend ask). `--limit` writes to `docs/sdd/p2-evaluation/scratch/`, never to `eval/results/`. P3 adds modes. |
| `JUDGE_MODEL` | env | `backend/loreos/settings.py` | Read by the evaluation only; default in `settings.py`. |
| `is_relevant(hit, source) -> bool` | function | `backend/loreos/evaluation/labels.py` | Same file, and the labeled heading path is a prefix of the hit's, or the same page. |
| Metrics | functions | `backend/loreos/evaluation/metrics.py` | Pure; per-question rows in, numbers out; `None` when the denominator is 0. |
| Evaluation workspace key | function | `backend/loreos/evaluation/run.py` | Workspace named `eval-<hash>` over corpus hash, chunker version, chunk tokens, overlap, embedding model and embedding input format: a changed input never reuses stale chunks. |
| Result file | file format | `eval/results/<UTC timestamp>-<mode>-<short sha>.json` | `{schema: 1, git_sha, created_at, mode, settings: {embedding_model, answer_model, judge_model, chunk_tokens, chunk_overlap, k}, corpus_hash, questions_hash, counts, metrics: {recall_at_5, mrr_at_10, citation_accuracy, unanswerable_refused, answerable_refused, faithfulness, judge_agreement}, latency_ms: {search_p50, search_p95}, usage: {embedding_tokens, answer_tokens, judge_tokens}, questions: [...]}` |

## Behaviour

1. `eval:fetch` writes the handbook files at the pinned commit and the PDFs to `eval/corpus/`, and fails naming the file when a sha256 does not match. It makes no OpenAI call.
2. The evaluation set holds 60 to 100 questions written by a person, about 15 unanswerable. Every answerable question labels at least one source, at the most specific heading that answers it.
3. `check:backend` validates the evaluation set: schema, unique ids, unanswerable count between 10 and 20, sources present exactly on answerable rows.
4. The preflight runs before any paid call and stops on the first failure: corpus present with matching hashes; every label resolves to a heading or page in the corpus; DATABASE_URL reachable; migrations at head; OPENAI_API_KEY set; git tree clean unless `--limit` is given. It prints the planned call counts and token estimate.
5. A result file under `eval/results/` is written only from a clean tree, so its `git_sha` names the code that produced it. Edit tools are denied there; only the run writes it.
6. The corpus is ingested through `ingest()` into the workspace named by the key. A workspace that already holds every corpus file `processed` is reused with no embedding spend.
7. For each question the run calls `search` for the top 10, then `answer_from_hits` with the top 5: the same code path as `POST /api/ask`.
8. Metric definitions:
   - Recall@5: over answerable questions, the mean of (labeled sources matched by any of the top 5 hits) / (labeled sources).
   - MRR@10: over answerable questions, the mean of 1 / rank of the first relevant hit in the top 10, and 0 when there is none.
   - Citation accuracy: over answerable questions answered with at least one citation, cited chunks that match a labeled source / all cited chunks.
   - Unanswerable refused: refused unanswerable questions / unanswerable questions.
   - Answerable wrongly refused: refused answerable questions / answerable questions.
   - Faithfulness: the share of non-refused answers the judge grades faithful (every claim supported by the cited passages).
   - Judge agreement: the share of the 30 calibration rows where the judge's grade equals the human grade, computed in the same run.
   A metric whose denominator is 0 is `null`, never 0.
9. Per-question rows record retrieved chunk ids with rank, score and relevance, the answer, its citations, the refusal reason and the judge grade with its one-line rationale.
10. P2 ends with one committed result file: mode `vector`, full evaluation set, judge agreement present.

## Acceptance checks

| # | Behaviour | Check | Expected | Does NOT exercise |
|---|---|---|---|---|
| 1 | Fetch verifies | `tests/test_eval_fetch.py` with a local HTTP fixture | A wrong sha256 fails naming the file | The real GitHub and PDF hosts |
| 3 | Set validation | `npm run check:backend`, `tests/test_eval_set.py` | The committed `eval/questions.jsonl` passes; fixtures with a duplicate id or a sourced unanswerable row fail | Whether the questions are good |
| 4 | Preflight | `tests/test_eval_preflight.py` against a tiny fixture corpus | Unresolvable label and dirty tree each stop before any fake LLM call | |
| 4 | Dry run is free | `npm run paid:eval -- --dry-run` | Exits 0, prints the estimate, no ask prompt | |
| 6 | Workspace reuse | `tests/test_eval_run.py` with fakes | Second run makes zero embed calls; changed chunk tokens produce a new workspace | |
| 8 | Metrics | `tests/test_eval_metrics.py` | Hand-computed values for each metric; `None` for zero denominators | |
| 8 | Relevance | `tests/test_eval_labels.py` | Prefix match on heading path; page match; other file never matches | |
| 10 | Baseline | `npm run paid:eval -- --mode vector` (asks first) | A result file in `eval/results/`, committed; verification row by hand naming it | Any mode but vector (P3) |

## Kill switch

None. Nothing served changes.

## Not changing

- Retrieval and answering code: P2 only calls them.
- The README: P5 builds the table from result files.
- No evaluation in CI or on push: runs are on demand, through `paid:eval` only.

## Risks

- Writing 60 to 100 good questions takes the operator several hours; that time competes with the thesis. A first pass of 60 is enough to start P3.
- The calibration rows need real answers, so the first full run cannot report judge agreement: run 1 goes to scratch, the operator grades 30 of its answers into `eval/judge_calibration.jsonl`, then run 2 is the baseline. Two paid runs.
- A label at a broad heading credits every chunk under it and inflates recall. The validator warns when a labeled section is longer than a few chunks.
- The handbook moves; the pinned commit keeps labels valid. Its content license is checked when the manifest is written. The corpus is fetched, not committed, so the repo's MIT license is unaffected.
- The judge is an LLM: its agreement number is reported beside faithfulness so the reader can discount it.
