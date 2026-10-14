# Evaluation

LoreOS scores its retrieval and its answers against a written evaluation set. This folder holds the inputs and the committed results. The README's results table is generated from `results/` by `npm run readme:table`.

| Path | What | Written by |
|---|---|---|
| `corpus.json` | The 48 corpus files: URL, sha256 and source attribution | by hand, [decision 0003](../docs/decisions/0003-evaluation-corpus-and-judge.md) |
| `corpus/` | The downloaded files and `outline.txt` (git-ignored) | `npm run eval:fetch` |
| `questions.jsonl` | The evaluation set: 60 to 100 questions, about 15 unanswerable | drafted by Claude, each label and answer checked ([decision 0004](../docs/decisions/0004-evaluation-set-drafted-by-claude.md)) |
| `judge_calibration.jsonl` | 30 answers graded faithful or unfaithful, to measure the judge | `npm run eval:calibration-draft`, then graded by Claude at the operator's request ([decision 0008](../docs/decisions/0008-calibration-graded-by-claude.md); a reason for each row in `docs/sdd/p2-evaluation/calibration-grades.md`). So judge agreement means agreement with Claude's grades, not a person's |
| `results/` | One JSON file per committed run | `npm run paid:eval` only, never by hand |

## 1. Fetch the corpus (free)

```sh
npm run eval:fetch
```

This downloads every file in `corpus.json` into `corpus/`, checks each sha256, and writes `corpus/outline.txt`. The outline lists every heading path (Markdown) and page (PDF), spelled exactly as the parser sees them, with its chunk count. Rerunning it downloads only what is missing or changed.

## 2. The evaluation set

Claude drafted the committed set at the operator's request (decision 0004). Each row's `note` gives the expected answer, so a person can audit any row. To add or replace questions, follow the same format. One JSON object per line in `questions.jsonl`:

```json
{"id": "q001", "question": "<a question the corpus answers>", "answerable": true, "sources": [{"file": "handbook/finance/expenses.md", "heading_path": ["<H2 heading>", "<H3 heading>"]}]}
{"id": "q002", "question": "<a question about a PDF>", "answerable": true, "sources": [{"file": "pdf/nist-csf-2.0.pdf", "page": 31}]}
{"id": "q003", "question": "<a plausible question the corpus does not answer>", "answerable": false, "sources": []}
```

- **Ids** are unique strings. `note` is an optional free-text field.
- **Markdown labels** copy a heading path from `outline.txt`. Label the most specific heading that answers the question: a label credits every chunk under it, so a broad one inflates recall. The preflight warns when a label spans more than 3 chunks.
- **PDF labels** use the physical page: the `page n` line in the outline, or the viewer's "n of N". Never use the printed page number, which is 4 to 9 pages off in these PDFs.
- **Several sources**: list each one when an answer needs more than one section.
- **Unanswerable questions**, between 10 and 20 of them, should sound answerable from these documents but are not. They test the "I couldn't find this in your documents" refusal.
- `npm run check:backend` validates the file's shape. The preflight also checks that every label resolves, and names the closest heading when one does not.

## 3. Run (paid; the guard asks every time)

| Step | Command | Writes to |
|---|---|---|
| Preflight only (free) | `npm run paid:eval -- --dry-run` | nothing; prints the estimate |
| A cheap check | `npm run paid:eval -- --limit 5` | `docs/sdd/p2-evaluation/scratch/` |
| Run 1 (full) | `npm run paid:eval` | scratch: there are no graded calibration rows yet |
| Draft the calibration | `npm run eval:calibration-draft -- docs/sdd/p2-evaluation/scratch/<run 1 file>.json` | `judge_calibration.jsonl`, with `human: null` |
| Grade it | Set each row's `human` to `"faithful"` or `"unfaithful"`, judging only from its passages | |
| Run 2 (the baseline) | `npm run paid:eval` | `results/`, from a clean tree; commit it |

A run writes to `results/` only when all of these hold:
- the run covered the full set of 60 to 100 questions;
- the judge graded all 30 calibration rows;
- the judge gave a verdict on every answer that was not refused;
- the tree was clean, with `questions.jsonl` and the graded `judge_calibration.jsonl` committed;
- HEAD did not move during the run.

Otherwise it writes to scratch, and the file's `notes` say why.

A full run, and a dry run without `--limit`, need a clean tree. So commit `questions.jsonl`, and later the graded `judge_calibration.jsonl`, before running.

Merge the branch that carries a result with a merge commit, not a squash or rebase. A squash or rebase drops the commit the result's `git_sha` names. Faithful means every claim in the answer is supported by the passages it cites; outside knowledge does not count, even when it is true.

## License of the files in this folder

LoreOS's code is MIT. The corpus files are never committed. Two files here quote corpus passages: `judge_calibration.jsonl` and the files under `results/`. They are licensed as follows:

- **Text from the GitLab Handbook** is CC BY-SA 4.0 (https://creativecommons.org/licenses/by-sa/4.0/). It comes from the GitLab Handbook by GitLab Inc., `gitlab.com/gitlab-com/content-sites/handbook`, at the commit pinned in `corpus.json`. Those passages, and these two files as adaptations containing them, are shared under CC BY-SA 4.0. The passages were modified: they are excerpts cut into chunks, and heading anchors (`{#id}`) and HTML tags were removed from their headings.
- **Text from NIST CSWP 29, NIST AI 100-1 and NIST SP 800-88r2** is a US government work, republished courtesy of the National Institute of Standards and Technology.
- **Text from OSHA 3885** (Recommended Practices for Safety and Health Programs) is a US government work, from the U.S. Department of Labor, Occupational Safety and Health Administration.
