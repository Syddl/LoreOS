---
id: 0009
title: Chunks stay at 500 tokens with a 50-token overlap, by measurement
date: 2026-10-14
status: accepted
superseded_by:
---

# Chunks stay at 500 tokens with a 50-token overlap, by measurement

## Decision

`CHUNK_TOKENS = 500` and `CHUNK_OVERLAP = 50` in `backend/loreos/chunking.py` stay as P1 set them. P3's sweep measured them against two other settings, and they won.

The sweep ran three paid evaluations in `vector` mode. All three used one commit (`22688aeb`), the same corpus (`corpus_hash` `3a387510…`), the same 81 questions and the same 30 calibration rows. Only `--chunk-tokens` and `--chunk-overlap` differed:

| Chunks | Result file | Recall@5 | MRR@10 | Answerable refused | Faithfulness | Search p50 | Cost |
|---|---|---|---|---|---|---|---|
| 250/25 | `eval/results/20261014T092118Z-vector-22688aeb.json` | 0.894 | 0.795 | 0.061 | 0.935 | 1257 ms | $0.106 |
| 500/50 | `eval/results/20261014T094653Z-vector-22688aeb.json` | 0.909 | 0.825 | 0.061 | 0.871 | 1280 ms | $0.131 |
| 1000/100 | `eval/results/20261014T101001Z-vector-22688aeb.json` | 0.909 | 0.766 | 0.045 | 0.889 | 1248 ms | $0.146 |

The rule (P3 spec, behaviour 2):
- the best Recall@5 wins;
- MRR@10 breaks a tie;
- the smaller chunk wins when both tie.

500/50 and 1000/100 tie on Recall@5 at 0.909. 500/50 then wins on MRR@10, with 0.825 against 0.766.

## Why

- **Recall@5 and MRR@10 decide**, because the answer model reads only the top 5 passages. Recall@5 says whether the evidence reaches it at all, and MRR@10 says how high the first piece ranks.
- **Faithfulness and answerable-refused are reported, not used.** They come from one sample of the answer model each, and their differences here are within one run's noise:
  - 0.871 to 0.935 faithfulness is about 4 of the 62 or so judged answers;
  - 0.045 to 0.061 answerable refused is 1 question in 66.
- **Cost:** 1000-token chunks send about 17% more answer input than 500 for no retrieval gain.
- **The 500/50 run reproduces P2's baseline exactly.** It matches `eval/results/20261012T054918Z-vector-6852dcac.json`: Recall@5 0.909 and MRR@10 0.825, through P4's re-keyed workspace, the RLS round trip and P3's code.

## What it does not show

- **The size was chosen in `vector` mode only.** The best size for `hybrid` or `hybrid_rerank` may differ, and the README must say which mode measured it.
- **The settings are coarse.** Three settings, a factor of two apart, were measured. A size between 500 and 1000, or another overlap, was not.
- **The reranker reads only the start of a long chunk.** fastembed cuts each pair at 512 tokens, so a 1000-token chunk would be read only in part. That did not decide this sweep, which ran without the reranker.

## Kill switch

None. Chunk size is a measured constant. A change is a code change, and the evaluation workspace key covers it, so the next evaluation rebuilds the stored chunks.

## Reopen only if

- Decision 0010's default mode is not `vector`, and a sweep in that mode is worth its cost (about $0.40 at today's prices).
- The corpus or the embedding model changes.
