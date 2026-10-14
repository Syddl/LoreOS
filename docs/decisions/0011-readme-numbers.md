---
id: 0011
title: The README's quality, latency and cost numbers come only from result files
date: 2026-10-14
status: accepted
superseded_by:
---

# The README's quality, latency and cost numbers come only from result files

## Decision

AGENTS.md says: "Never put a number in the README that a committed evaluation result file under `eval/results/` did not produce." It is read this way:

- **Numbers about quality, latency or cost** come only from committed result files. That covers Recall@5, MRR@10, citation accuracy, refusals, faithfulness, judge agreement, search time, and money per run or per question.
  - They live in the README's results block, which `npm run readme:table` generates from the files.
  - `npm run check:readme` fails when the block differs from what the files give.
  - The README's prose carries none of them. It points at the table instead.
- **Configuration facts** come from the code and the configuration, and the README may state them: ports, the upload cap, the embedding dimensions, the chunk size and overlap, and the pooler's port.
- **The caption's counts**, such as the number of questions, come from the result files too, as the generator writes them.

The AGENTS.md line now names this decision.

## Why

The operator chose this on 2026-10-14.

Read literally, the rule would forbid the README from saying which port the api listens on, or that Supabase's transaction pooler is refused. The rule's purpose is that no one types a measured number by hand, so a claim about how well LoreOS works always traces to a committed run. Configuration facts are not measurements, and the code they come from is their source.

## Kill switch

None. It is a policy. `check:readme` enforces the table half. The prose half stays a review item, since no check can tell a typed measurement from a configuration fact.

## Reopen only if

- A README claim about quality, latency or cost turns up in prose, with no result file behind it. Then the check widens, or the rule tightens back to its literal reading.
