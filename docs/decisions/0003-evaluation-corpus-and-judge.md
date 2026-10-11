---
id: 0003
title: Evaluation corpus, its license, and the faithfulness judge
date: 2026-10-08
status: accepted
superseded_by:
---

# Evaluation corpus, its license, and the faithfulness judge

## Decision

**Corpus.** `eval/corpus.json` pins 48 files: 44 GitLab handbook pages and 4 US government PDFs.
- The handbook pages are from `gitlab.com/gitlab-com/content-sites/handbook` at commit `8d0947598af36ea1a8d534028f103f8277976716`. They cover values, communication, time off, expenses and travel, onboarding and laptops, and security policies.
- The PDFs are NIST CSF 2.0, NIST AI RMF 1.0, NIST SP 800-88r2 and OSHA 3885. They are fetched from Wayback Machine `id_` snapshots, because NIST serves new bytes behind the same URL and a pinned sha256 would break.
- Every file carries its sha256. `npm run eval:fetch` downloads and verifies the files, and they are never committed.

**License.**
- **The handbook**: its text is CC BY-SA 4.0. The repo's root MIT license covers only GitLab's software. Calibration rows and result files quote handbook passages, so those files under `eval/` are licensed CC BY-SA 4.0, with the attribution in `eval/README.md` and `eval/corpus.json`. LoreOS's code stays MIT. AGENTS.md's copyleft rule governs dependencies, and the corpus is test data, not a dependency.
- **The PDFs**: US government works, with no share-alike. NIST and OSHA ask for credit, which `eval/corpus.json` gives.

**Judge.** `JUDGE_MODEL` defaults to `gpt-6-luna` ([decision 0005](0005-cheaper-judge-and-a-spend-cap.md); first chosen as `gpt-6.1-sol`), at `reasoning_effort="low"`, with no temperature or seed.
- It grades faithful or unfaithful against the cited passages only, writing its rationale before the grade.
- A verdict failure (a refusal, no parsed verdict, or a length or content-filter stop) is recorded on its row.
- Any `openai.APIError` stops the run, after writing what was done to scratch.

**The dry run asks.** `npm run paid:eval -- --dry-run` spends nothing, but the guard asks before it runs, as it does for every paid form (P1 removed every exemption).

**Markdown headings drop `{#id}` anchors and HTML tags** for every upload, so citations and labels show the heading as a reader sees it.

## Why

- **The handbook**: the brief chose it for real exact-term questions; invented documents give none. The operator kept it once its license was known, and accepted CC BY-SA on the evaluation data that quotes it, rather than committing no passages or switching corpora.
- **The PDFs** are distractors on different topics, and they test PDF page labels. The candidates over 80 pages, the scanned or garbled ones, and the ones under unclear licenses were rejected (the research is summarised in `docs/sdd/p2-evaluation/plan.md`).
- **The judge model**: OpenAI's guidance is to grade with a strong model. `gpt-6.1-sol` is near the flagship at a fifth of its price: about $1.60 a run for about 130 grading calls. A judge that is also the answer model favours its own answers. `gpt-6-luna` costs about $0.08 a run but is unproven as a grader; the calibration run measures any judge, so an operator can try it through `JUDGE_MODEL`.
- **The dry run**: P1's reviews showed that an exempt spelling can be redirected through package.json, `.npmrc`, `npm_config_*` or PYTHONPATH. Approving a free preflight costs a click.
- **The headings**: the handbook writes Hugo heading anchors and Font Awesome icons in headings. Without the cleanup, labels would have to copy `{#travel-mode}`, and citations would show it.

## Kill switch

None. The corpus and the judge are evaluation inputs that serve nothing. `JUDGE_MODEL` changes the judge. Reverting the parser commit restores the old heading text.

## Reopen only if

- GitLab changes the handbook's content license.
- A judge model scores clearly better agreement on the calibration rows at a lower cost.
- The corpus needs to be committed, for example for an offline evaluation.
- A user's Markdown relies on `{#...}` text at the end of a heading as literal content.
