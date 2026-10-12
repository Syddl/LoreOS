---
id: 0008
title: The judge-calibration grades are by Claude, at the operator's request
date: 2026-10-12
status: accepted
superseded_by:
---

# The judge-calibration grades are by Claude, at the operator's request

## Decision

Claude graded the 30 rows of `eval/judge_calibration.jsonl`, at the operator's request. This amends [decision 0004](0004-evaluation-set-drafted-by-claude.md), which kept these grades human.

How the grades were made:
- Each row was graded blind, from its passages alone, before any judge verdict was read. Run 1's verdicts were never opened.
- The rule was the judge's own: faithful means every claim in the answer is supported by the passages it cites, and outside knowledge does not count, even when true.
- The result is 29 faithful and 1 unfaithful (q066: its rule of thumb about raising your voice appears in none of its cited passages).
- [docs/sdd/p2-evaluation/calibration-grades.md](../sdd/p2-evaluation/calibration-grades.md) gives the reason for each grade, so anyone can audit or overturn one.

What changes in meaning:
- `judge_agreement` in a result file now measures how often the judge (`gpt-6-luna`) agrees with Claude, a model from another vendor, applying the same rule. It does not measure agreement with a person.
- Anything that reports the number, the README included, says "agreement with Claude's grades", never "human".

## Why

The operator chose not to spend the time to grade 30 answers, and P3 needs the baseline to measure against.

Two models from different vendors agreeing on one strict rule is weaker evidence than a person's agreement. It still catches a judge that grades carelessly or leniently.

## Kill switch

None. The grades are evaluation input. A person can regrade any row, or all of them, at any time. The next result then records a new `calibration_hash`.

## Reopen only if

- The operator grades the rows by hand. When that happens, the provenance line in `eval/README.md` changes back.
- The judge's agreement with these grades is low enough that it is unclear which side is wrong. A person then breaks the tie on the rows that disagree.
