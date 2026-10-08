# Spec: P2 evaluation harness and baseline

Phase P2 of [the v1 brief](../v1/brief.md). Drafted before P1 started, then re-read against what P1 built and revised. The section "Revised against P1" lists every change from the draft and its reason.

## Summary

One command scores retrieval and answers against a hand-written evaluation set and writes a result file under `eval/results/`. P2 ends with the committed vector-only baseline.
Labels name a file and a heading or page, not a chunk, so they survive P3's chunk-size changes.
Kill switch: none. Offline tooling, plus one parser fix that changes heading text in citations (behaviour 11).

## Interfaces

| Interface | Kind | Owner file | Contract |
|---|---|---|---|
| Corpus manifest | file format | `eval/corpus.json` | `{sources: [{name, home, license, attribution, files}], files: [{file, url, sha256}]}`. `file` is the path under `eval/corpus/`, and the document's filename in the evaluation workspace. A source's `files` is the path prefix it covers, and every file falls under exactly one source. Handbook URLs pin one commit; PDF URLs are Wayback `id_` snapshots, because NIST replaces bytes behind the same URL. |
| Corpus | directory | `eval/corpus/` (git-ignored) | Written by `eval:fetch`; never committed. Holds `outline.txt`: every file's heading paths or pages, spelled as labels must spell them, with the chunk count of each. |
| Evaluation set | file format | `eval/questions.jsonl` | One object per line: `{id, question, answerable, sources: [...], note?}`. A Markdown source is `{file, heading_path: [...]}` with a non-empty path; a PDF source is `{file, page}`, the 1-based physical page. Unanswerable rows have `sources: []`. |
| Judge calibration | file format | `eval/judge_calibration.jsonl` | 30 rows `{id, question, answer, passages: [{n, source, text}], human: "faithful" \| "unfaithful"}`. `passages` are the cited passages with their original `[n]` numbers, the same input the judge gets in a run. |
| `npm run eval:fetch` | root script | `package.json` to `python -m loreos.evaluation.fetch` | Downloads each manifest file that is missing or differs, verifies its sha256, writes `outline.txt`. Free. |
| `npm run eval:calibration-draft -- <result file>` | root script | `package.json` to `python -m loreos.evaluation.calibration` | Writes `eval/judge_calibration.jsonl` from 30 non-refused answers of a result file, spread evenly by id, with `human: null` and no judge grade shown. Refuses to overwrite. Free. |
| `npm run paid:eval -- [--mode vector] [--limit n] [--dry-run]` | root script | `package.json` to `python -m loreos.evaluation` | `--dry-run` runs only the preflight: it spends nothing, but the guard asks as for every paid form. `--limit n` runs the first n questions and skips the calibration pass, so it stays a cheap check. P3 adds modes. |
| `JUDGE_MODEL` | env | `backend/loreos/settings.py`, `.env.example` | Default `gpt-6.1-sol`. Read by the evaluation only. |
| `llm.judge(question, answer, passages) -> Verdict` | function | `backend/loreos/llm.py` | Structured output `{rationale, grade}` with the rationale first; `reasoning_effort="low"`; no temperature or seed. |
| `llm.USAGE` | counter | `backend/loreos/llm.py` | Input and output tokens per kind (`embedding`, `answer`, `judge`), from each response's `usage`. A response without `usage` adds nothing, and the run notes it. |
| `is_relevant(hit, source) -> bool` | function | `backend/loreos/evaluation/labels.py` | Same file, and the labeled heading path is a list prefix of the hit's, or the same page. |
| Metrics | functions | `backend/loreos/evaluation/metrics.py` | Pure; per-question rows in, numbers out; `None` when the denominator is 0. |
| Evaluation workspace key | function | `backend/loreos/evaluation/run.py` | Workspace named `eval-<12 hex>`, a sha256 over the corpus hash, the source text of `parsing.py`, `chunking.py` and `ingest.py` (line endings normalised), `CHUNK_TOKENS`, `CHUNK_OVERLAP`, the embedding model and `OPENAI_BASE_URL`. A changed input never reuses stale chunks. |
| Result file | file format | `eval/results/<YYYYMMDDTHHMMSSZ>-<mode>-<sha8>.json` | `{schema: 1, git_sha, created_at, mode, settings: {embedding_model, answer_model, judge_model, chunk_tokens, chunk_overlap, k, search_k}, corpus_hash, questions_hash, calibration_hash, destination: "results" \| "scratch", workspace: {name, reused}, counts, metrics: {recall_at_5, mrr_at_10, citation_accuracy, unanswerable_refused, answerable_refused, faithfulness, judge_agreement}, judge_confusion, latency_ms: {search_p50, search_p95}, usage: {embedding_tokens, answer_input_tokens, answer_output_tokens, judge_input_tokens, judge_output_tokens}, notes: [...], questions: [...]}` |

## Behaviour

1. `eval:fetch` downloads each manifest file to `eval/corpus/<file>`. A file already present with the right sha256 is not downloaded again. A non-200 response or a sha256 mismatch fails naming the file, and leaves no file at that path. It then writes `outline.txt`. It makes no OpenAI call.
2. The evaluation set holds 60 to 100 questions written by a person, about 15 unanswerable. Every answerable question labels at least one source, at the most specific heading that answers it.
3. `check:backend` validates the committed `eval/questions.jsonl`, and `eval/judge_calibration.jsonl` when present. For the set: the schema, unique ids, an unanswerable count between 10 and 20, sources on exactly the answerable rows, and each source in the shape its file type needs. For the calibration file: 30 rows, unique ids, every row graded. Until the operator commits the set, its test skips and names the missing file. The preflight refuses to run without it.
4. The preflight runs before any paid call and stops on the first failure, in this order:
   - the evaluation set and the calibration file are valid;
   - the corpus is present with matching hashes, and no two files have identical bytes (ingest would merge them into one document);
   - every label resolves to a heading path or page in the parsed corpus, and an error names the closest heading;
   - DATABASE_URL is reachable and the migrations are at head;
   - OPENAI_API_KEY is set and accepted, through the same check as `paid:smoke` (listing models is free);
   - when listing models works, the embedding, answer and judge models are each in the list;
   - the git tree is clean, with no tracked change and no untracked file, unless `--limit` is given.

   It prints the planned call counts and token estimate: corpus embedding tokens are counted exactly, and are 0 when the workspace is reused. It warns about each label whose section spans more than 3 chunks.
5. A result file goes to `eval/results/` only when every one of these holds:
   - the run had no `--limit` and covered 60 to 100 questions;
   - the judge graded every calibration row, so judge agreement is not null;
   - faithfulness is not null;
   - the tree was clean at the preflight and is still clean before the write;
   - HEAD is the commit the preflight recorded.

   Any other run writes to `docs/sdd/p2-evaluation/scratch/`, which git ignores, and records each reason in `notes`. The file's `destination` field says which. So a committed result's `git_sha` names the code that produced it. Edit tools are denied in `eval/results/` (`protected_paths` in `.claude/harness.json`); only the run writes there. `check:backend` fails on a committed result whose `destination` is not `results` or whose judge agreement is null. That catches a scratch file copied in by a shell.
6. The corpus is ingested through `ingest()` into the workspace named by the key, one transaction per file. A workspace that already holds every corpus file `processed` is reused with no embedding spend. Any file not `processed` after ingest stops the run, naming the file and its stored error.
7. For each question, in file order, the run calls `search` for the top 10 (`search_k`), then `answer_from_hits` with the top 5 (`answering.TOP_K`). This is the same code path as `POST /api/ask`. The search call is timed. The run sorts judge failures into two classes:
   - **Verdict failures**: a refusal, no parsed verdict, or a length or content-filter stop. The error is recorded on that row and in `notes`, and the answer leaves the faithfulness denominator.
   - **API failures**: any `openai.APIError`, such as a bad key, an unknown model, an unsupported parameter, an exhausted quota, or the network. These mean the judge itself is broken, so the run stops.

   An answer that fails without an API error is recorded as refused, with reason `answer_error` and the error on the row and in `notes`. That covers no parsed answer and a length or content-filter stop: the user would get no answer either. An `openai.APIError` while answering stops the run, as it does for the judge. Any stop, a Ctrl-C included, first writes what was done to scratch with the error in `notes`, since that output was already paid for.
8. Metric definitions. "Refused" means the answer's `found` is false, for any reason.
   - Recall@5: over answerable questions, the mean of (labeled sources matched by any of the top 5 hits) / (labeled sources).
   - MRR@10: over answerable questions, the mean of 1 / rank of the first hit relevant to any labeled source in the top 10, and 0 when there is none.
   - Citation accuracy: over answerable questions answered with at least one citation, the cited chunks that match a labeled source divided by all cited chunks. The ratio is pooled over those questions, not averaged per question.
   - Unanswerable refused: refused unanswerable questions / unanswerable questions.
   - Answerable wrongly refused (`answerable_refused`): refused answerable questions / answerable questions.
   - Faithfulness: of the non-refused answers (answerable or not) that the judge graded, the share graded faithful. Faithful means every claim is supported by the cited passages. The judge sees the question, the answer and only the cited passages, each under its original number.
   - Judge agreement: of the calibration rows the judge graded, the share where its grade equals the human grade, computed in the same run. `judge_confusion` holds the four human/judge counts beside it. A calibration row with a verdict failure leaves the denominator, and behaviour 5 keeps such a run out of `eval/results/`.

   A metric whose denominator is 0 is `null`, never 0. Without a calibration file, judge agreement is `null`.
9. Per-question rows record:
   - the retrieved chunk ids, with rank, file, heading path or page, score and relevance;
   - the search time;
   - the answer, and its citations with their numbers and text;
   - the refusal reason;
   - the judge's grade and its one-line rationale.
10. P2 ends with one committed result file: mode `vector`, the full evaluation set, judge agreement present.
11. Markdown heading text loses a trailing `{#id}` attribute block and any HTML tags. This holds for every upload, so citations and labels show the heading as a reader sees it (operator decision).
12. `npm run paid:eval --dry-run` without the `--` separator is a dry run: npm sets `npm_config_dry_run`, as for `paid:smoke`. A `--limit` or `--mode` given without `--` is refused with the corrected command. npm would otherwise drop the flag and start a full paid run.

## Acceptance checks

| # | Behaviour | Check | Expected | Does NOT exercise |
|---|---|---|---|---|
| 1 | Fetch verifies | `tests/test_eval_fetch.py` with a local HTTP server | A wrong sha256 and a 404 each fail naming the file and leave no file; a present matching file is not fetched again; the outline lists heading paths and pages | The real GitLab and PDF hosts |
| 3 | Set validation | `npm run check:backend`, `tests/test_eval_set.py` | The committed set passes (skipped, naming the file, until it is committed). Fixtures fail for each of: a duplicate id, a sourced unanswerable row, an unsourced answerable row, a Markdown source without a heading path, a PDF source without a page, an unanswerable count out of range, and an ungraded calibration row | Whether the questions are good |
| 4 | Preflight | `tests/test_eval_preflight.py` against a tiny fixture corpus | A label that does not resolve (with its closest heading named), a hash mismatch, duplicate bytes and a dirty tree each stop before any fake LLM call; the estimate prints exact corpus tokens | |
| 4 | Dry run spends nothing | `npm run paid:eval -- --dry-run`, approved at the guard's ask | Before the set exists: a non-zero exit naming `eval/questions.jsonl`. Once the set and the key exist: exit 0 with the estimate. Never an embedding, answer or judge call | Whether the estimate matches a real run's usage (the baseline records actual usage) |
| 5 | Destination | `tests/test_eval_run.py` with fakes | Each of these writes to scratch with the reason in `notes`: `--limit`, a missing calibration file, a judge that fails every verdict, fewer than 60 questions, a tree dirtied during the run, and HEAD moved during the run. A committed result with `destination` other than `results`, or with null judge agreement, fails `check:backend` | |
| 6 | Workspace reuse and ingest failure | `tests/test_eval_run.py` with fakes | A second run sends no chunk text to the embedder; a changed chunk size produces a new workspace; a corpus file that fails ingest stops the run naming the file and its error, before any answer call | |
| 7 | Judge failure classes | `tests/test_eval_run.py` with fakes | A verdict failure is recorded on its row; an API error stops the run and leaves a partial scratch file; so does a `KeyboardInterrupt` | |
| 4 | Spend gate | `tests/test_eval_cli.py` | A preflight that exits non-zero never reaches `run.evaluate`; the preflight's recorded commit is passed to it | |
| 7 | Same code path | `tests/test_eval_run.py` with fakes | `answer_from_hits` receives the first 5 of the 10 hits | |
| 8 | Metrics | `tests/test_eval_metrics.py` | Hand-computed values for each metric and for p50/p95; `None` for zero denominators | |
| 8 | Relevance | `tests/test_eval_labels.py` | A heading path matches by prefix; a page matches; another file never matches | |
| 8 | Judge input and usage | `tests/test_llm_judge.py` with a fake client | The judge gets only the cited passages, with their original numbers; its tokens and the answer's land in `llm.USAGE` | Real grading quality (judge agreement measures it) |
| 11 | Heading cleanup | `tests/test_parsing.py` | `## Title {#id}` and `## <i class="x"></i>Title` both give `Title` | |
| 12 | npm flags | `tests/test_eval_cli.py` | `npm_config_dry_run=true` runs only the preflight; `npm_config_limit` exits 2 naming the `--` form; unknown arguments exit 2 | |
| 10 | Baseline | `npm run paid:eval -- --mode vector` (asks first) | A result file in `eval/results/`, committed; a verification row by hand naming it | Any mode but vector (P3) |

## Kill switch

None. The evaluation serves nothing. The heading cleanup is a parser fix with a test, and reverting its commit undoes it.

## Not changing

- Retrieval and answering code: P2 only calls them. `llm.py` gains `judge()` and the usage counter; embedding and drafting behave as before.
- `paid:smoke`: the evaluation calls its `preflight()` for the database, migration and key checks.
- The README: P5 builds the table from result files.
- No evaluation in CI or on push: runs are on demand, through `paid:eval` only.

## Revised against P1

| Draft said | Now | Why |
|---|---|---|
| `--dry-run` is exempt from the spend ask | The guard asks; the dry run still spends nothing | P1 removed every exemption: reviews showed that an exempt spelling can be redirected (package.json, `.npmrc`, `npm_config_*`, PYTHONPATH). `scripts/check-spend.mjs` already pins `npm run paid:eval -- --dry-run` as ask. |
| Manifest `{handbook: {repo, commit, paths}, pdfs: [...]}` | One flat `files` list with a sha256 per file, plus `sources` for attribution | One download-and-verify path for every file. A per-file hash makes "corpus present with matching hashes" checkable without the network. |
| "The corpus is fetched, not committed, so the repo's MIT license is unaffected" | The handbook's text is CC BY-SA 4.0 (MIT covers only GitLab's software). Files under `eval/` that quote it carry a CC BY-SA 4.0 notice with attribution in `eval/README.md`; the code stays MIT | Calibration rows and result files quote passages. Operator decision; [decision 0003](../../decisions/0003-evaluation-corpus-and-judge.md). |
| `usage: {embedding_tokens, answer_tokens, judge_tokens}` | Input and output counted separately for answers and the judge | P1's `llm.py` discarded `usage`. Output costs 5 to 10 times input, so one total cannot be priced. |
| "chunker version, embedding input format" in the workspace key | The source text of `parsing.py`, `chunking.py` and `ingest.py` | P1 has no version constant, and a hash of the source cannot be forgotten. Re-embedding the corpus costs under a cent, so the extra invalidations are cheap. |
| Preflight: "OPENAI_API_KEY set" | Set and accepted, through `paid:smoke`'s check | Style rule: a definitive rejection blocks before the first paid call. |
| Labels: `heading_path?`, `page?` | A Markdown source needs a heading path and a PDF source needs a page | An empty path is a prefix of every path in the file, so it would credit every chunk. |
| No rule for the judge-less first run | A run without 30 graded calibration rows writes to scratch | Behaviour 10 requires judge agreement in the committed baseline. |
| Labels copy headings as the parser saw them | Heading anchors and HTML are stripped (behaviour 11) | The handbook has `{#id}` anchors and `<i>` icons in headings. Operator decision. |

## Risks

- Writing 60 to 100 good questions takes the operator several hours, and that time competes with the thesis. A first pass of 60 is enough to start P3. `outline.txt` gives the exact heading spellings.
- The calibration rows need real answers, so the first full run cannot report judge agreement. Run 1 goes to scratch. `eval:calibration-draft` turns it into 30 ungraded rows, and the operator grades them. Run 2 is the baseline. That makes two paid runs, about $2 each with the default judge.
- A label at a broad heading credits every chunk under it and inflates recall. The preflight warns when a labeled section spans more than 3 chunks.
- The handbook moves; the pinned commit keeps labels valid. Hugo shortcodes (`{{% panel %}}`, `{{% details %}}`) stay in the text as noise, as they would for a user who uploads the same files.
- The judge is an LLM, and the default judge model is not the answer model, to avoid self-preference. Its agreement number and confusion counts are reported beside faithfulness so the reader can discount it.
- `gpt-5.4-mini`, the answer model, is a previous generation, and its sibling `gpt-5.4-nano` is deprecated. Changing the answer model is outside P2; the baseline records the model it used.
