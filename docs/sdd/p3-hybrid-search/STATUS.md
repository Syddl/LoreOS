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
  - **Step 6 next:** `--mode all` at the commit that records this, run id `compare-all`, log `scratch/compare-all.log`. Estimate: three runs like `sweep-500` without its corpus embedding, about $0.13 each, so about $0.38. The dry run gives the upper bound.
  - **For P5** (step 10): the README states that the chunk size was measured in `vector` mode, citing decision 0009.

## Next step

Phase 3 step 6: `npm run paid:eval -- --mode all`, dry run first. Then decision 0010.

## Blockers

None. Building the code costs nothing. The four paid runs (the chunk sweep, then `--mode all`) each ask, with a priced estimate, under the $5 cap of decision 0005.

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

## Port ledger

| Branch | Status | Reference |
|---|---|---|
| main | required | |
