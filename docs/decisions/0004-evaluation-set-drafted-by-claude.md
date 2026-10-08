---
id: 0004
title: The evaluation set is drafted by Claude
date: 2026-10-08
status: accepted
superseded_by:
---

# The evaluation set is drafted by Claude

## Decision

Claude drafts `eval/questions.jsonl`, at the operator's request: about 80 questions over the pinned corpus, about 15 of them unanswerable. This amends brief decision 10, which had chosen hand-written questions.

How the set is made:
- Five agents each draft one area of the corpus under one brief.
- Each question is phrased as a reader would ask it, not copied from its passage. Each carries the expected answer in `note`.
- Each label is copied byte for byte from `eval/corpus/outline.txt`. A PDF label is the physical page whose extracted text holds the answer.
- Each unanswerable question was searched for across the whole corpus.
- The main session merges the drafts, assigns ids, and checks every label against the fetched corpus (a test in `check:backend` when the corpus is present). It reviews every answer against its section before committing.

What stays human: the 30 judge-calibration grades in `eval/judge_calibration.jsonl`. They are what measure the LLM judge, so an LLM cannot write them.

## Why

The operator cannot spend the hours that 60 to 100 hand-written questions take, and P3 needs a baseline to measure against.

The brief rejected 500 LLM-generated questions, for the bias generated questions carry. A model tends to phrase a question in its passage's own words, and that inflates retrieval scores. This set reduces the bias rather than removing it:
- the rule against copying the passage's wording;
- a mix of exact-fact, procedural and conceptual questions;
- an expected answer on every row, so a person can audit it.

The numbers it produces are still a baseline for comparing P3's changes on one fixed set. They are not a claim about real users' questions.

## Kill switch

None. The set is evaluation input and serves nothing. A hand-written set can replace it at any time; the next result file then records a new `questions_hash`.

## Reopen only if

- The operator writes or rewrites questions by hand. When that happens, the provenance line in `eval/README.md` changes with them.
- Retrieval scores look implausibly high and a check shows heavy word overlap between questions and passages.
