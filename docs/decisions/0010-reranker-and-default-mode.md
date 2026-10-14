---
id: 0010
title: The api answers with hybrid search and the MiniLM reranker, by measurement
date: 2026-10-14
status: accepted
superseded_by:
---

# The api answers with hybrid search and the MiniLM reranker, by measurement

## Decision

`DEFAULT_MODE = "hybrid_rerank"` in `backend/loreos/retrieval.py`. It fuses vector search and keyword search with RRF (k = 60, the top 50 from each). It then rescores the top 30 with a local cross-encoder and answers from the top 5.

**The reranker model** is `Xenova/ms-marco-MiniLM-L-6-v2`:
- the license is Apache-2.0, which allows MIT distribution;
- the download is 0.08 GB;
- it runs on the CPU through onnxruntime in fastembed 0.9.0, without PyTorch;
- fastembed cuts each (question, passage) pair at 512 tokens. With 500-token chunks (decision 0009), the cut drops at most the tail of a long chunk.

**The image** bakes the model. The api loads it at startup and refuses to start, naming the fixes, when it cannot. The worker never loads it.

**The kill switch:** `RERANK=off` serves `vector` without a deploy, and every answer's `retrieval_mode` says which mode served it. The spec had it serve `hybrid`, but `hybrid` measured worse than `vector`. See "Kill switch" below.

## The measurement

There were three paid evaluations from one commit (`c221b3a`). All used chunks of 500/50 and the same corpus, questions and calibration hashes. All read one stored workspace (`eval-093199cc80a6`), so the stored chunks were identical.

| Mode | Result file | Recall@5 | MRR@10 | Citation accuracy | Answerable refused | Faithfulness | Search p50 / p95 |
|---|---|---|---|---|---|---|---|
| vector | `eval/results/20261014T103002Z-vector-c221b3a3.json` | 0.909 | 0.825 | 0.709 | 0.076 | 0.918 | 1306 / 2112 ms |
| hybrid | `eval/results/20261014T104308Z-hybrid-c221b3a3.json` | 0.864 | 0.682 | 0.644 | 0.061 | 0.855 | 1599 / 2151 ms |
| hybrid_rerank | `eval/results/20261014T123854Z-hybrid_rerank-c221b3a3.json` | 0.924 | 0.855 | 0.759 | 0.061 | 0.968 | 3655 / 6079 ms |

The rule is P3 spec behaviour 9:
- the best Recall@5 wins;
- MRR@10 breaks a tie;
- a slower mode must beat a faster one on one of the two metrics without losing on the other.

`hybrid_rerank` beats `vector` on both: 0.924 against 0.909, and 0.855 against 0.825. `hybrid` loses to `vector` on both.

**Search time** covers the question's embedding (an OpenAI round trip, about 1.3 s at p50), the queries and the rerank. It was measured on the dev machine against hosted Supabase. At p50, `hybrid_rerank` takes about 2.3 s more than `vector`. The rerank itself, CPU inference on 30 passages, accounts for about 2.1 s of that (`hybrid_rerank` minus `hybrid`).

## Why

**The reranker recovers what fusion loses, and more.**
- **Per question:** against `vector`, the first relevant chunk ranks higher on 12 answerable questions and lower on 11. On balance that lifts MRR@10 by 0.030 and Recall@5 by one question.
- **Two questions vector never retrieved:** it finds q053 (rank 3) and q061 (rank 1). Both were among the four answerable questions P2's baseline wrongly refused.
- **Citation accuracy and faithfulness** rise too, to 0.759 and 0.968. Those come from one sample of the answer model each, so the README reports them, but they do not decide.

**Hybrid alone hurts on this corpus.**
- **The count:** against `vector`, it ranks the first relevant chunk lower on 20 answerable questions and higher on 7.
- **The usual cause** is a sibling section of the same document. Its heading path holds the question's words ("Reverse AMA > Process for initiating…", "Sick Time > …"), so keyword search ranks it high, and equal-weight RRF lifts it over vector search's first hit.
- **Hugo shortcodes** are not the cause. Shortcode chunks fill about the same share of the top 5 in every mode.
- **So `hybrid`** stays measurable through `--mode hybrid`, but it serves nothing: it is neither the default nor the fallback.

## The cost, and what it does not show

- **Latency.** About 2.3 s more per question than `vector` at p50 on the dev machine, and p95 above 6 s. It was measured one question at a time. Reranks run in their own pool of 2 threads, so concurrent questions queue behind each other while logins do not (KNOWN-GAPS).
- **Memory and image size.** The image grows from 93 MB to 240 MB (onnxruntime, numpy, tokenizers, the model). The api's resident memory with the model loaded was not measured.
- **The keyword index under RLS.** At 922 chunks the planner seq-scans, so whether `chunks_tsv` is used under `loreos_app`'s policy is unproven at scale (KNOWN-GAPS).
- **The size of the gain.** It is small and measured on 66 answerable questions: one question of Recall@5, 0.030 of MRR@10. A larger or different corpus may show more or less.
- **Tuning.** None was done: RRF k, the depths (50 and 30), the keyword ranking (heading words weigh as much as body words), and the reranker model are all as the spec set them. The plan's trigger for tuning, `hybrid` losing to `vector`, has fired. It is left to a later phase with its own measurement, because the default mode already wins without it.
- **An earlier run.** It died with the host at question 51 of the `hybrid_rerank` mode (`docs/sdd/p3-hybrid-search/STATUS.md`). The file above is from its retry at the same commit.

## Kill switch

`RERANK=off` serves `vector`, the best mode measured without the reranker. It is also the fastest: P2's baseline, 1.3 s at p50.

The spec said `off` serves `hybrid`. That assumed fusion alone would at least match vector search. Measured, it loses to vector on both metrics, so a switch to `hybrid` would leave answers worse than before P3. `serving_mode()` returns `vector`, and `tests/test_rerank_switch.py` pins that `off` runs neither the reranker nor keyword search. The operator can veto this, and with it the default above, before P3 merges.

## Reopen only if

- The latency or the memory is wrong for a deployment's host. Then measure on that host before choosing.
- A corpus change, an embedding-model change or keyword-search tuning gives new comparison rows.
- fastembed or the model's hub revision changes. The result files record the model name, not the weights' revision.
