---
status: open
feature: p3-hybrid-search
---

# Status: p3-hybrid-search

The single carrier of state between sessions. Update it before a session ends; the session-start hook injects the open lines. Status is one of open, blocked, done.

## Open tasks

- Steps 1 and 2, PRD and grilling: covered by [the v1 brief](../v1/brief.md), decisions 4, 7, 8, 9 and 11, which the operator confirmed before P1.
- Step 3, spec revised against P1, P2 and P4: done (2026-10-14). The changes are in `spec.md`, section "Revised against P1, P2 and P4".
  - **Free probes behind it:**
    - fastembed 0.9.0 and onnxruntime 1.31.0 resolve for Python 3.14 on Windows and on manylinux.
    - fastembed lists 8 cross-encoders, with their licenses.
    - Two models were timed on 30 passages on the dev machine: `ms-marco-MiniLM-L-6-v2` took 2.3 to 2.7 s, and `jina-reranker-v1-turbo-en` took 3.1 s.
    - fastembed cuts both at 512 tokens.
  - **Engineering calls, for the operator to veto:**
    - the reranker model, `Xenova/ms-marco-MiniLM-L-6-v2`;
    - the default-mode rule in behaviour 9: a slower mode must win on Recall@5 or MRR@10 without losing on the other;
    - the tie rule for chunk size: when both metrics tie, the smaller chunk wins.
- Step 4, plan: done (2026-10-14), `plan.md`. It has two build phases (window A: 1.1 to 1.3; window B: 2.1, then 2.2), the paid measurement in phase 3, then review. The main session implements the tasks.
- Step 5, plan review by execution, recorded in [reviews/plan.md](reviews/plan.md):
  - **First review** of `c9f6cae`: "fix then re-review", with 1 blocker, 2 majors, 12 minors and 6 nits. `check:all` was green, with 712 backend tests. The blocker: an untracked result dirtied the tree, so `--mode all` could commit only one of its three files.
  - **Revision** `840abe1` answers each finding, mapped in the plan's last section.
  - **Re-review** of `840abe1`: **merge**. Its 5 minors and 5 nits are folded in. Step 5 is done.
- Step 6, implementation, done by the main session:

  | Task | Commit | What it adds | Proof (redproof PASS for each) |
  |---|---|---|---|
  | 1.1 | `be4261f` | migration `0003_keyword_search` (`tsv`, `loreos.heading_text`, GIN index, execute grant), `keyword_search`, and a `verify_rls` check for the grant | `' \| '` to `' & '` reddens 5 keyword cases; dropping the check reddens its negative |
  | 1.2 | `6501c7a` | `fusion.rrf`, with exact `Fraction` sums | dropping the best-rank tiebreak reddens the tie case |
  | 1.3 | `5584229` | fastembed 0.9.0, `rerank.py` (`Xenova/ms-marco-MiniLM-L-6-v2`), the CI model cache | a reversed sort reddens the real-model case |
  | 2.1 | `17f2847` | modes in `search`, `serving_mode()`, `RERANK`, `Answer.retrieval_mode`, model load at api startup and in `smoke.preflight` | 4 redproofs: the switch, the startup load, the fusion, the smoke load |
  | 2.2 | `d6d20d9` | `--mode all`, `--chunk-tokens` and `--chunk-overlap`, `chunk()` reading its budget when called, the clean-tree exemption for untracked results, the plan per mode | 4 redproofs: the exemption (twice), the RERANK=off refusal, the call-time budget |

  - **Window A closed:** `check:all` PASS at `5584229` (739 backend tests).
  - **Deviations from the plan:**
    - **The license check.** 1.3 also changed `backend/check_licenses.py` and `tests/test_licenses.py`. `py-rust-stemmers` (fastembed's) ships an MIT `licenses/LICENSE` but fills no license field. A package that declares nothing is now judged by the text of the license files it ships, so the copyleft scan reads the real text, and a package with neither still fails.
    - **New dependencies.** fastembed brings `httpx` and `httpcore` through huggingface-hub, beside P4's `httpx2`. They are unavoidable with fastembed, and all pass `check:licenses`.
    - **Where the 2.2 cases live.** The CLI cases are in `test_eval_cli.py`, and the run cases in `test_eval_run.py`, which already has the `ev` fixture they need. That replaces the planned `test_eval_modes.py`.
    - **Step 7 (task review)** runs once for phases 1 and 2 together, before any paid run, rather than once per phase. That keeps the tree free while the reviewer runs the suite.

- Step 7, task review of phases 1 and 2 ([reviews/tasks.md](reviews/tasks.md)): **merge**, with 5 minors and 4 nits. The reviewer ran `check:all` green (786 backend tests).
- **Fix wave** `95b09fa`, red first. Each new case failed before its fix, the NUL one included:
  - **The license fallback** now accepts a license file only when it names a permissive license (or a copyleft one, which fails).
  - **`rerank.model()`** turns every load failure into the message with the fixes, the fastembed imports and the cache directory included.
  - **Keyword search runs before the embedding**, and NUL is replaced.
  - **`--chunk-tokens`** is capped at 8000.
  - **A test proves the rerank runs off the event loop.**
  - **The vector order breaks ties on the chunk id.**
  - **The result's `settings`** gain `fuse_depth` and `rerank_depth`.
  - **The latency case** sleeps 0.3 s.
  - **Spec row 7** names the right files.
  - **The redproofs** for the thread, the tiebreak and the license fallback all pass.
  - **The index plan** under RLS moves to phase 3 step 2, against real data on Supabase.

- **Phase 3, operator's yes on 2026-10-14** ("Migrate, then run"). Each paid command still asks at the guard.
  - **Step 2 done.** `npm run db:migrate` took Supabase (PG 17.11) to `0003_keyword_search`, and `db:verify-rls` printed `ok`, the `heading_text` check included. The free reads, in `scratch/supabase-0003.log`:
    - 0 of 922 chunks have a null `tsv`;
    - the database is 32 MB;
    - the keyword query runs as `loreos_app` with the RLS filter, in 17 ms. At 922 chunks the planner seq-scans, so index use under RLS is unproven at scale.
  - **Step 3 done.** All three dry runs passed at `7b236d2` (`scratch/dry-{250,500,1000}.log`), with every preflight step and new workspaces to build. Priced from their plans:

    | Run | Workspace | Corpus embedding | Upper bound | Likely (P2's actuals were about 42% of the bound) |
    |---|---|---|---|---|
    | 250/25 | `eval-f09e96cf6f39` | 201,229 tokens | $0.20 | about $0.09 |
    | 500/50 | `eval-093199cc80a6` | 195,274 tokens | $0.29 | about $0.13 |
    | 1000/100 | `eval-2f5e71f82f9c` | 189,103 tokens | $0.47 | about $0.20 |

    The sweep's upper bound is $0.96. Spent before P3: $0.28, under the $5 cap.
  - **Step 4, the sweep.** Three paid runs at the commit that records this table, launched one at a time, detached, each approved at the guard:
    - run ids `sweep-250`, `sweep-500` and `sweep-1000`;
    - logs in `scratch/sweep-<tokens>.log`;
    - output in `eval/results/`, or `docs/sdd/p2-evaluation/scratch/` when a destination rule fails.

    STATUS is not touched again until the third run has written its file.

  - **Step 4 done.** All three runs went to `eval/results/` at `22688aeb`, sharing the corpus, question and calibration hashes; the ledger has one row each. The sweep cost $0.383, so the spend to date is $0.663 of $5.
  - **Step 5 done.** [Decision 0009](../../decisions/0009-chunk-size-500-overlap-50.md) keeps 500/50, which ties 1000/100 on Recall@5 at 0.909 and wins on MRR@10, with 0.825 against 0.766.
    - `chunking.py` is not edited, not even its comment. Its source keys the evaluation workspace, so the `--mode all` run reuses `eval-093199cc80a6` and pays no corpus embedding.
    - `test_defaults` still pins 500/50.
  - **Step 6 done**, with one environment failure and its retry, all at `c221b3a` on workspace `eval-093199cc80a6` (reused, so no corpus embedding). The dry run's upper bound was $0.85.
    - **`compare-all`** wrote the `vector` and `hybrid` files to `eval/results/`, then died at `hybrid_rerank` question 51 of 81.
      - **Triage:** environment. The host shut down uncleanly: the System log has Kernel-Power 41 and EventLog 6008, the run's log was last written at 10:52:59 UTC, and the host was back at 12:04 UTC, then took three Windows Update restarts.
      - **The output:** it was a hard kill, so no partial result was written. That part's spend, about $0.09, is estimated, since no usage was recorded.
      - **Notes:** `scratch/compare-retry-note.txt`.
    - **`compare-rerank-retry`** reran `--mode hybrid_rerank` alone at the same commit, so the two finished modes were not billed again. Its file went to `eval/results/`.
    - **The three rows:**

      | Mode | Recall@5 | MRR@10 | Citation accuracy | Faithfulness | Search p50 / p95 | Cost |
      |---|---|---|---|---|---|---|
      | vector | 0.909 | 0.825 | 0.709 | 0.918 | 1306 / 2112 ms | $0.1251 |
      | hybrid | 0.864 | 0.682 | 0.644 | 0.855 | 1599 / 2151 ms | $0.1545 |
      | hybrid_rerank | 0.924 | 0.855 | 0.759 | 0.968 | 3655 / 6079 ms | $0.1383 |

    - **The spend for P3's runs is about $0.89**, so the total to date is about $1.17 of $5. No paid run remains in P3.
  - **Step 8, the hybrid run's misses.**
    - **Hybrid against vector:** hybrid ranks the first relevant chunk lower than vector on 20 answerable questions, and higher on 7 (`scratch/vector-vs-hybrid.txt`). The usual cause is a sibling section of the same document, whose heading path shares the question's words. Keyword search ranks it high, and equal-weight RRF lifts it over vector's first hit.
    - **Shortcodes:** 88 of 920 chunks hold a Hugo shortcode. Shortcode chunks fill about the same share of the top 5 in each mode: 36, 42 and 34 of 405 top-5 hits, of which 29, 37 and 27 are not relevant (`scratch/shortcodes.txt`). The KNOWN-GAPS trigger is met only marginally, by 8 extra hits in hybrid, so the row stays as it is.
    - **The reranked mode against vector:** it is better on 12 questions and worse on 11 (`scratch/vector-vs-rerank.txt`). It finds q053 (rank 3) and q061 (rank 1), which vector never retrieved.
  - **Step 7 done**, at `7b278eb`. [Decision 0010](../../decisions/0010-reranker-and-default-mode.md) sets `DEFAULT_MODE = "hybrid_rerank"`: by behaviour 9, it beats `vector` on Recall@5 (0.924 against 0.909) and on MRR@10 (0.855 against 0.825), for about 2.3 s more search time at p50.
    - **A spec change, for the operator to veto: `RERANK=off` now serves `vector`, not `hybrid`.** `hybrid` measured worse than `vector` on both metrics, so the switch as specced would leave answers worse than before P3. Red first: the switch test expected `vector`, failed, then passed; redproof PASS.
    - **The image** bakes the model under `FASTEMBED_CACHE_PATH=/app/fastembed`, and grows from 93 MB to 324 MB.
      - **The compose check** starts the api with `HF_HUB_OFFLINE=1`, and `check-compose.mjs` asserts it.
      - **Run locally**, `npm run check:compose` passes.
      - **The redproof:** an image with an empty cache directory builds, but the api fails at startup. PASS.
      - **A first redproof was red for the wrong reason** (the build failed at `chown`), so it was redone with a mutation that keeps the build valid.
    - **One test assumed vector serving**: `test_preflight_never_loads_the_reranker_when_the_api_would_not_use_it`. It now sets the default and the switch itself, across three cases. Every other test passes with real `hybrid_rerank` serving.
    - **KNOWN-GAPS gains three rows:**
      - the reranker's CPU per question, with no concurrency cap;
      - the GIN index under RLS, unproven at scale;
      - heading words in keyword ranking.
  - **Step 9 (database size):** 93 MB, up from 32 MB. There are four `eval-*` workspaces. Only `eval-093199cc80a6` (500/50) is in use. Three are no longer read, and pruning them waits for the operator's yes, because it deletes data:
    - `eval-f642a16b4e50` (P2's, 920 chunks);
    - `eval-f09e96cf6f39` (250/25, 1239 chunks);
    - `eval-2f5e71f82f9c` (1000/100, 796 chunks).
  - **For P5** (step 10), the README:
    - states that the chunk size was measured in `vector` mode, citing decision 0009;
    - takes the three-row comparison from the `c221b3a` files, as decision 0010 lists them;
    - says that judge agreement is with Claude's grades (decision 0008).

- **Phase 4.**
  - **Step 9, whole-branch review** ([reviews/branch.md](reviews/branch.md)): **merge**, with 3 minors and 4 nits.
    - The reviewer ran `check:all` twice at `47eeb97`, both green (796 backend tests).
    - It checked every number in decisions 0009 and 0010 against the result files, the costs recomputed from `usage` included.
  - **Step 10, fix wave**, red first:
    - **`smoke.preflight(reranker=False)`.** The evaluation's preflight passes it, so `--mode vector` or `--mode hybrid` never needs the model.
    - **Reranks run in their own 2-thread pool**, `retrieval.RERANK_POOL`, so logins (argon2 on asyncio's default pool) never queue behind them. The thread test asserts the pool's thread name.
    - **The Dockerfile bakes and chowns the model in one layer**, before the rest of the source. The image went from 324 MB to 240 MB, and `check:compose` passes again (`scratch/check-compose-2.log`).
    - **The nits:**
      - the latency wording (2.3 s over `vector`, 2.1 s for the rerank alone);
      - the plan's two lines about the fallback;
      - the CI comment;
      - the KNOWN-GAPS rows on the reranker and the `eval-*` workspaces.

## Next step

Phase 4: claim-green on the fix wave's pushed tip, the PR, and CI. Merge only on the operator's yes.

## Blockers

None. Every paid run in P3 is done. The operator decides three things:
1. **The default and the fallback** (decision 0010): `hybrid_rerank`, and `RERANK=off` serving `vector`.
2. **Pruning the three unused `eval-*` workspaces**, which deletes data.
3. **Whether to re-sweep chunk size in `hybrid_rerank` mode**, about $0.40. Decision 0009's reopen condition is half met now that the default is not `vector`. The default is to skip it: the 512-token reranker cut favours 500-token chunks anyway.

## Verification ledger

| date | branch | sha | suite | result | duration | not covered |
|---|---|---|---|---|---|---|
| 2026-10-14T08:34:23.891Z | p3-hybrid-search | 19d2c00e | `npm run check:all` | PASS | 334.7 s | real OpenAI and Supabase (phase 3's paid runs and db:migrate); check:compose (its own CI job); CI on Linux |
| 2026-10-14T09:00:06.746Z | p3-hybrid-search | 945c93f4 | `npm run check:all` | PASS | 336.3 s | real OpenAI and Supabase (phase 3's paid runs and db:migrate); check:compose (its own CI job); CI on Linux |
| 2026-10-14 (by hand, live) | p3-hybrid-search | 7b236d2 | `npm run db:migrate` and `npm run db:verify-rls` on Supabase, then read-only queries; `scratch/db-migrate.log`, `scratch/verify-rls.log`, `scratch/supabase-0003.log` | PASS | | Migration `0003_keyword_search` on PG 17.11. `verify-rls` printed `ok`, the `heading_text` grant included. 0 of 922 chunks have a null `tsv`. The keyword query applies RLS as `loreos_app`, in 17 ms. Not covered: index use under RLS at scale (922 chunks seq-scan) |
| 2026-10-14 (by hand, live) | p3-hybrid-search | 7b236d2 | `npm run paid:eval -- --mode vector --chunk-tokens {250,500,1000} --chunk-overlap {25,50,100} --dry-run`, each approved at the ask; `scratch/dry-*.log` | PASS | | Every preflight step passed, with 3 new workspaces to build. Upper bounds $0.20, $0.29 and $0.47. No paid call |
| 2026-10-14 (by hand, live) | p3-hybrid-search | 22688ae | `sweep-250`, approved at the ask; `scratch/sweep-250.log` | PASS (to `eval/results/`) | | `20261014T092118Z-vector-22688aeb.json`: Recall@5 0.894, MRR@10 0.795, faithfulness 0.935, judge agreement 1.0. Cost $0.1058 (likely $0.09, upper $0.20) |
| 2026-10-14 (by hand, live) | p3-hybrid-search | 22688ae | `sweep-500`, approved at the ask; `scratch/sweep-500.log` | PASS (to `eval/results/`) | | `20261014T094653Z-vector-22688aeb.json`: Recall@5 0.909, MRR@10 0.825 (the same as P2's baseline), faithfulness 0.871. Cost $0.1310 (likely $0.13, upper $0.29) |
| 2026-10-14 (by hand, live) | p3-hybrid-search | 22688ae | `sweep-1000`, approved at the ask; `scratch/sweep-1000.log` | PASS (to `eval/results/`) | | `20261014T101001Z-vector-22688aeb.json`: Recall@5 0.909, MRR@10 0.766, faithfulness 0.889. Cost $0.1462 (likely $0.20, upper $0.47). The sweep's total is $0.383. Not covered: chunk size in the hybrid modes; the answer model's variance (one run each) |
| 2026-10-14 (by hand, live) | p3-hybrid-search | c221b3a | `npm run paid:eval -- --mode all --dry-run`, approved at the ask; `scratch/dry-all.log` | PASS | | The workspace was reused (0 corpus tokens). 243 answer and 333 judge calls, with an upper bound of about $0.85. No paid call |
| 2026-10-14 (by hand, live) | p3-hybrid-search | c221b3a | `compare-all` (`--mode all`), approved at the ask; `scratch/compare-all.log` | PARTIAL: 2 of 3 modes to `eval/results/`; FAIL (environment) on the third | | `20261014T103002Z-vector-c221b3a3.json`: Recall@5 0.909, MRR@10 0.825, $0.1251. `20261014T104308Z-hybrid-c221b3a3.json`: Recall@5 0.864, MRR@10 0.682, $0.1545. `hybrid_rerank` died at question 51 of 81 in an unclean host shutdown (Kernel-Power 41), with no partial file, about $0.09 lost |
| 2026-10-14 (by hand, live) | p3-hybrid-search | c221b3a | `compare-rerank-retry` (`--mode hybrid_rerank`), approved at the ask; `scratch/compare-rerank-retry.log` | PASS (to `eval/results/`) | | `20261014T123854Z-hybrid_rerank-c221b3a3.json`: Recall@5 0.924, MRR@10 0.855, faithfulness 0.968, search p50 3655 ms. Cost $0.1383. Not covered: latency on a deploy host; concurrent questions |
| 2026-10-14 (by hand) | p3-hybrid-search | 7b278eb | `npm run check:compose` locally (its own CI job), after a retry: the first build hit a Docker Hub TLS timeout; `scratch/check-compose.log` | PASS | | The api is healthy with `HF_HUB_OFFLINE=1`, and the image is 324 MB. Redproof (an empty `/app/fastembed`, so no model) PASS: the api fails at startup. Not covered: CI's run of the same job |
| 2026-10-14T13:03:31.008Z | p3-hybrid-search | 7b278eb6 | `npm run check:all` | PASS | 345.3 s | check:compose (its own CI job; run locally and redproved by hand); real OpenAI and Supabase (the paid runs are ledger rows); CI on Linux |

## Port ledger

| Branch | Status | Reference |
|---|---|---|
| main | required | |
