---
id: 0005
title: The judge defaults to gpt-6-luna, under a $5 cap for closing P1 and P2
date: 2026-10-11
status: accepted
superseded_by:
---

# The judge defaults to gpt-6-luna, under a $5 cap for closing P1 and P2

## Decision

`JUDGE_MODEL` defaults to `gpt-6-luna`, at `reasoning_effort="low"` as before. This amends [decision 0003](0003-evaluation-corpus-and-judge.md), which chose `gpt-6.1-sol`. `ANSWER_MODEL` stays `gpt-5.4-mini`.

The operator capped OpenAI spend at $5 for closing P1 and P2: `paid:smoke`, evaluation run 1 and the baseline run.

## Why

The operator asked for the cheaper model. Aggregators list `gpt-6-luna` at $0.10 / $0.50 per 1M input / output tokens, against $2 / $10 for `gpt-6.1-sol`.
- Upper estimate per full run: about $0.10 for the judge and about $0.40 for the answers. P1 and P2 together come to about $1.
- With `gpt-6.1-sol` the same work came to about $3 to $5, at the cap.

The answer model stays as it is. A judge that is also the answer model favours its own answers (0003), and changing the answer model is outside P2 (its spec). `gpt-6-luna` as the answer model, with `gpt-6.1-sol` judging, costs about $1.70 a run, more than this choice.

`gpt-6-luna` is unproven as a grader. The 30 hand grades measure it: the baseline records `judge_agreement`, as it would for any judge.

## Kill switch

`JUDGE_MODEL=gpt-6.1-sol` in `.env` restores the old judge without a code change. Every result file records the judge it used.

## Reopen only if

- The baseline's `judge_agreement` is too low for its faithfulness number to be trusted. Then rerun the baseline with `JUDGE_MODEL=gpt-6.1-sol` (about $2.30, inside the cap) and make that the default again.
- OpenAI deprecates `gpt-6-luna`, or a cheaper judge scores better agreement.
