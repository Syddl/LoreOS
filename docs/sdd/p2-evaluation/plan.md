# Plan: p2-evaluation

Implements [spec.md](spec.md). Sizing: all fourteen lifecycle steps, since `paid:eval` is a spend surface, with an independent reviewer at step 9.

## Facts read before planning

- P1's `search(session, workspace_id, query, k)` and `answer_from_hits(question, hits)` are the calls the evaluation makes. `answering.TOP_K` is 5. `Hit` carries `chunk_id, document_id, filename, heading_path, page, text, score`, and `Citation` carries `n` plus the same fields.
- `ingest(session, workspace_id, filename, data)` deduplicates by sha256 within a workspace and returns a stored document early unless it `failed`. A failure is recorded on the document and the transaction still commits. So a rerun over a processed workspace makes no embed call.
- `llm.embed` and `llm.draft_answer` discard `response.usage`. `llm._source(hit)` formats `file > heading path, page n`. `llm.py` is documented as the only module that calls OpenAI, and the judge goes there too.
- `smoke.preflight()` checks that the key is set, that the migration is at head, and that listing models is accepted. Tests patch `smoke.preflight` and `smoke.main`.
- `chunking.chunk(sections, max_tokens=CHUNK_TOKENS, ...)` binds its defaults at definition time. The workspace key reads `chunking.CHUNK_TOKENS` at call time.
- `.gitignore` already ignores `docs/sdd/*/scratch/`. `protected_paths.deny` already holds `eval/results/**`. `scripts/check-spend.mjs` already pins `paid:eval` and `python -m loreos.evaluation` (with `--dry-run` too) as ask.
- `tests/test_config.py` pins the exact set of env keys that `settings.py` reads against `.env.example`.
- Research (main session, three read-only agents):
  - Handbook: `gitlab.com/gitlab-com/content-sites/handbook`, commit `8d0947598af36ea1a8d534028f103f8277976716`. Its content is CC BY-SA 4.0. 44 pages, about 129k tokens, all hashed.
  - Raw URLs `https://gitlab.com/gitlab-com/content-sites/handbook/-/raw/<sha>/content/<path>` return 200. A missing file returns 404 with an HTML body.
  - Ten headings in the chosen pages carry `{#id}`, three of them with no space before it; three carry `<i>` tags.
  - PDFs: NIST CSF 2.0 (32 pages), NIST AI RMF 1.0 (48), NIST SP 800-88r2 (48) and OSHA 3885 (40). All are US government works and extract cleanly with pypdf, with no empty page.
    - NIST serves new bytes behind the same URL, so the manifest uses Wayback `id_` snapshots. Each snapshot was verified byte-identical, and urllib's default User-Agent works there and on GitLab.
    - Labels use physical pages. The printed folio is offset by 4 to 9 pages.
  - OpenAI: `gpt-6.1-sol` costs $2 / $10 per 1M input / output tokens. `reasoning_effort` `low` is supported, and `none` is rejected. Chat usage is `usage.prompt_tokens` / `usage.completion_tokens`, the latter including reasoning; `usage` can be `None`. Embeddings usage is `usage.prompt_tokens`. `seed` is deprecated.
- Operator decisions:
  - Keep the handbook and license the quoting files under `eval/` CC BY-SA 4.0.
  - `JUDGE_MODEL` defaults to `gpt-6.1-sol`.
  - Strip `{#id}` and HTML from Markdown headings.

## Design choices inside the spec

- **Module layout** under `backend/loreos/evaluation/`:
  - `__init__.py` is empty, so importing `fetch` or `calibration` runs no paid code.
  - `dataset.py`: the paths and the file validators.
  - `labels.py`: relevance and the outline.
  - `metrics.py`: pure numbers.
  - `fetch.py`: `eval:fetch`.
  - `run.py`: the workspace, the per-question loop and the result file.
  - `preflight.py`: the checks and the estimate.
  - `calibration.py`: the draft.
  - `__main__.py`: the `paid:eval` CLI.
- **Paths live in `dataset.py` only**: `EVAL_DIR`, `QUESTIONS`, `CALIBRATION`, `MANIFEST`, `CORPUS_DIR`, `RESULTS_DIR`, `SCRATCH_DIR`. Every reader writes `dataset.CORPUS_DIR` at call time, never `from dataset import CORPUS_DIR`, so tests can monkeypatch them.
- **A file's kind comes from `parsing.kind_of(file, b"")`**, so validation and ingest agree on Markdown versus PDF. A `.txt` source cannot be labeled (no headings, no pages), and the validator says so.
- **The run is sequential.** About 100 questions at a few seconds each is well under the time a person waits, and sequential calls keep the search latency numbers clean.
- **Fakes in tests**: `fake_embed` and `fake_draft` (P1), plus a `fake_judge` fixture in `conftest.py`. The git checks go through `run.git_sha()` and `run.tree_clean()`, and tests patch them. `smoke.preflight` is patched to a no-op where a test is not about it.
- **Implementers write files and do not commit.** Several tasks run at once in one checkout, and one shared index would let one task's commit sweep up another's staged files. The main session reads each task's diff and report, then commits that task alone with explicit paths. STATUS.md records this under "Steps run differently".

## Phases

| Phase | Goal | Depends on | Check at the end |
|---|---|---|---|
| 1 | Pure parts: validators, labels, metrics, fetch, judge and usage, heading cleanup | none | `uv --directory backend run python -m pytest tests/test_eval_set.py tests/test_eval_labels.py tests/test_eval_metrics.py tests/test_eval_fetch.py tests/test_llm_judge.py tests/test_parsing.py tests/test_config.py` green; then `npm run check:backend` green |
| 2 | The run: workspace key and reuse, per-question loop, judge passes, result file and destination | phase 1 | `tests/test_eval_run.py` green; `npm run check:backend` green |
| 3 | Preflight, CLI, calibration draft, scripts, data and docs | phase 2 | `npm run check:all` green; `npm run eval:fetch` downloads and verifies the real corpus (free); `npm run paid:eval -- --dry-run` approved at the ask, exits 0 with an estimate |
| 4 | Baseline (operator) | phase 3, the evaluation set, `OPENAI_API_KEY` | Run 1 to scratch, then `eval:calibration-draft` and grading, then run 2 to `eval/results/`, committed |

## Parallel windows

| Window | Tasks | Shared files (must be none) |
|---|---|---|
| A | 1.1, 1.2, 1.3, 1.4, 1.5, 1.6 | none: `conftest.py` belongs to 1.5 alone |
| B | 2.1 | none |
| C | 3.1, 3.2, and 3.3 by the main session | none: `package.json` and `fetch.py`'s `main` belong to 3.1; data and docs to 3.3 |

## Handoff contracts

| From | To | Handoff |
|---|---|---|
| 1.1 | 2.1, 3.1, 3.2 | `dataset.{EVAL_DIR, QUESTIONS, CALIBRATION, MANIFEST, CORPUS_DIR, RESULTS_DIR, SCRATCH_DIR}`; `read_jsonl(path) -> list[dict]` (raises `DatasetError` naming path and line); `question_problems(rows) -> list[str]`; `calibration_problems(rows) -> list[str]`; `read_manifest(path) -> dict`; `manifest_problems(manifest) -> list[str]` (each file: a relative path with forward slashes and no `..`, an http(s) url and a 64-hex sha256, unique by file, and covered by exactly one `sources[].files` prefix); `text_hash(path) -> str` (sha256 after CRLF to LF); `corpus_hash(manifest) -> str` (sha256 over sorted `file\tsha256\n` lines) |
| 1.2 | 2.1, 3.1 | `is_relevant(hit, source) -> bool` (hit: any object with `filename`, `heading_path`, `page`); `matched_sources(hit, sources) -> list[int]`; `OutlineEntry(file, heading_path, page, chunks)`; `outline(corpus: dict[str, bytes]) -> list[OutlineEntry]`; `label_problems(questions, entries) -> list[str]` (names the closest heading); `broad_labels(questions, entries, max_chunks=3) -> list[str]`; `render_outline(entries) -> str` |
| 1.3 | 2.1 | `summarize(rows, calibration) -> {"metrics", "judge_confusion", "latency_ms", "counts"}` over the row shape below; `percentile(values, q) -> float \| None` (nearest rank) |
| 1.4 | 3.1 | `fetch(manifest, corpus_dir) -> list[str]` (problems; downloads with `urllib.request`); `main() -> int` |
| 1.5 | 2.1, 3.1 | `llm.USAGE` (`collections.Counter`, keys `embedding_input`, `answer_input`, `answer_output`, `judge_input`, `judge_output`, `responses_without_usage`); `llm.Verdict(rationale: str, grade: Literal["faithful","unfaithful"])`; `async llm.judge(question, answer, passages: list[dict{n, source, text}]) -> Verdict`; `llm.source_label(hit_or_citation) -> str` (renamed from `_source`); `settings.judge_model()`, `settings.DEFAULT_JUDGE_MODEL = "gpt-6.1-sol"`; conftest `fake_judge` (`.reply`, `.calls`) |
| 2.1 | 3.1, 3.2 | `run.workspace_name(manifest) -> str`; `async run.workspace_status(name, corpus) -> (workspace_id \| None, reused: bool)`; `run.git_sha() -> str`; `run.tree_clean() -> bool`; `run.load_corpus(manifest) -> dict[str, bytes]`; `async run.evaluate(mode, limit, *, clean_at_preflight: bool) -> Path` (the paid part, after the preflight); the result file shape in the spec, with rows as below |

Row shape (one per question; 1.3 reads it, 2.1 writes it, 3.2 reads it):

```
{id, question, answerable, sources, search_ms,
 hits: [{rank, chunk_id, file, heading_path, page, score, relevant: [source index, ...]}],
 answer: {found, text, reason, citations: [{n, chunk_id, file, heading_path, page, source, text, relevant: [source index, ...]}]},
 judge: null | {grade: "faithful" | "unfaithful" | null, rationale, error}}
```

Here `judge` is `null` for a refused answer. Calibration pairs for `summarize` are `[{id, human, judge: grade | None}]`.

## Tasks

### Task 1.1: Evaluation set and calibration validators

- Files owned: `backend/loreos/evaluation/__init__.py`, `backend/loreos/evaluation/dataset.py`, `backend/tests/test_eval_set.py`
- Depends on: none
- Change:
  - Adds the paths, `read_jsonl`, `question_problems`, `calibration_problems`, `read_manifest`, `manifest_problems`, `text_hash` and `corpus_hash` per the contract.
  - `question_problems` covers: required keys and types; unique ids; unanswerable count 10 to 20; sources on exactly the answerable rows; a Markdown source with a non-empty `heading_path` of strings and no `page`; a PDF source with an int `page >= 1` and no `heading_path`; a `.txt` or unknown file refused.
  - A test validates the committed `eval/questions.jsonl` when it exists, and skips naming the file when it does not.
- Acceptance check: `uv --directory backend run python -m pytest tests/test_eval_set.py` green. It has one failing fixture per rule in spec behaviour 3, plus a valid fixture of 10 unanswerable and 2 answerable rows that passes.
- Red first: the test file fails on import before `dataset.py` exists. Each rule's fixture is shown failing with its rule removed (a `redproof` mutation of the rule).
- Skills to load: none
- Predicted size: 2 files, about 150 lines, 30 minutes

### Task 1.2: Relevance and the corpus outline

- Files owned: `backend/loreos/evaluation/labels.py`, `backend/tests/test_eval_labels.py`
- Depends on: none (reads `parsing` and `chunking`)
- Change:
  - Adds `is_relevant`, `matched_sources`, `OutlineEntry`, `outline`, `label_problems`, `broad_labels` and `render_outline` per the contract.
  - `outline` parses each file and chunks each section alone, so it counts chunks per section.
  - A label heading path resolves when it is a list prefix of some section's path, and its chunk count is the sum over those sections.
  - `label_problems` names the closest heading path with `difflib.get_close_matches`.
- Acceptance check: `uv --directory backend run python -m pytest tests/test_eval_labels.py` green. It covers:
  - a heading path matches by prefix, and a sibling with the same first element does not;
  - a page matches;
  - another file never matches, even with the same path;
  - `matched_sources` returns indices;
  - an unknown heading names its closest match;
  - a broad label is warned about;
  - the outline renders paths and pages.
- Red first: import failure, then a `redproof` mutation turning the prefix test into "any shared element" fails the sibling case.
- Skills to load: none
- Predicted size: 2 files, about 120 lines, 30 minutes

### Task 1.3: Metrics

- Files owned: `backend/loreos/evaluation/metrics.py`, `backend/tests/test_eval_metrics.py`
- Depends on: none
- Change: `summarize` and `percentile`, exactly as spec behaviour 8 defines them, over the row shape above. Citation accuracy is pooled. Faithfulness counts only graded answers. `counts` holds questions, answerable, unanswerable, refused, judged and judge errors, plus the calibration rows and their judge errors.
- Acceptance check: `uv --directory backend run python -m pytest tests/test_eval_metrics.py` green. One hand-computed fixture of about six rows checks every metric to the exact value; zero denominators give `None` for each metric; p50 and p95 by nearest rank on a known list; and `percentile([])` is `None`.
- Red first: import failure; a `redproof` mutation averaging citation accuracy per question instead of pooling it fails the fixture.
- Skills to load: none
- Predicted size: 2 files, about 130 lines, 30 minutes

### Task 1.4: Fetch

- Files owned: `backend/loreos/evaluation/fetch.py`, `backend/tests/test_eval_fetch.py`, `.gitignore`
- Depends on: none (reads `dataset` paths through the module at call time; until 1.1 lands, the test passes `corpus_dir` explicitly)
- Change:
  - `fetch(manifest, corpus_dir)` skips a present file whose sha256 matches, and downloads every other one with `urllib.request` (timeout 60 s).
  - A non-200 status or a sha256 mismatch is a problem naming the file and the reason, and leaves no file at that path. Bytes go to a `.part` file that is renamed only after the hash matches.
  - A `file` path is refused if it leaves `corpus_dir`.
  - `main()` reads `dataset.MANIFEST`, prints a summary and returns 1 when there is any problem. Writing the outline is added in 3.1.
  - `.gitignore` gains `eval/corpus/`.
- Acceptance check: `uv --directory backend run python -m pytest tests/test_eval_fetch.py` green against a `http.server` on 127.0.0.1 in a thread. It covers:
  - a good file is written;
  - a wrong sha256 fails naming the file and leaves nothing;
  - a 404 fails naming the file;
  - a second fetch makes no request;
  - a `../` path is refused.
- Red first: import failure; a `redproof` mutation that writes before verifying fails "leaves nothing".
- Skills to load: none
- Predicted size: 3 files, about 120 lines, 30 minutes

### Task 1.5: Judge, usage counter and JUDGE_MODEL

- Files owned: `backend/loreos/llm.py`, `backend/loreos/settings.py`, `.env.example`, `backend/tests/test_config.py`, `backend/tests/test_llm_judge.py`, `backend/tests/conftest.py`
- Depends on: none
- Change:
  - `USAGE` counter: `embed` adds `usage.prompt_tokens`, and `draft_answer` and `judge` add `prompt_tokens` and `completion_tokens`. A response with `usage` of `None` adds `responses_without_usage`.
  - `Verdict` and `judge()` follow the contract. The system prompt is the one in the task brief (from the OpenAI research). The user message holds the question, then each passage as `[n] <source>\n<text>`, then the answer. The call uses `reasoning_effort="low"`; a `None` parse raises like `draft_answer`.
  - `_source` is renamed to `source_label`.
  - `settings.judge_model()` with the `gpt-6.1-sol` default; `.env.example` gains `JUDGE_MODEL`; `test_config.py` pins it.
  - The conftest gains `fake_judge`.
- Acceptance check: `uv --directory backend run python -m pytest tests/test_llm_judge.py tests/test_config.py tests/test_answering.py tests/test_no_openai.py` green. With a fake client (`llm.client` patched to return an object whose `chat.completions.parse` and `embeddings.create` record their kwargs):
  - only the passages given are sent, with their numbers;
  - the model is `settings.judge_model()`, with `reasoning_effort` `low` and no `temperature` or `seed`;
  - `USAGE` gains the right counts for embed, draft and judge;
  - `usage=None` counts `responses_without_usage`;
  - a refusal raises.
- Red first: `ImportError` on `llm.judge`, and `test_config` fails on the missing `JUDGE_MODEL`.
- Skills to load: none
- Predicted size: 6 files, about 140 lines, 40 minutes

### Task 1.6: Heading cleanup

- Files owned: `backend/loreos/parsing.py`, `backend/tests/test_parsing.py`
- Depends on: none
- Change: Markdown heading text drops a trailing `{#...}` block (with or without a space before it) and every HTML tag, then is stripped. A heading that becomes empty stays empty, as an empty heading does now.
- Acceptance check: `uv --directory backend run python -m pytest tests/test_parsing.py` green, with new cases for:
  - `## Title {#id}`;
  - `## Collaboration{#collab}`;
  - `## <i class="fas"></i>Compliance`;
  - `## Use {braces} here` (unchanged);
  - a nested path that mixes them.
- Red first: the new cases fail on the current parser.
- Skills to load: none
- Predicted size: 2 files, about 30 lines, 15 minutes

### Task 2.1: The run

- Files owned: `backend/loreos/evaluation/run.py`, `backend/tests/test_eval_run.py`
- Depends on: 1.1, 1.2, 1.3, 1.5
- Change:
  - **Workspace and git helpers**: `workspace_name`, `workspace_status`, `load_corpus`, `git_sha` and `tree_clean` per the contract.
  - **`evaluate(mode, limit, clean_at_preflight)`**:
    - finds or creates the workspace by name, then ingests each corpus file in its own `workspace_session`;
    - stops naming any file not `processed`, with its stored error;
    - runs the questions (search with k=10, timed; `answer_from_hits` with the first 5);
    - judges each non-refused answer, recording an error on the row and in `notes`;
    - judges the calibration rows unless `limit` is set;
    - calls `metrics.summarize` and builds the result.
  - **Destination**: `eval/results/` when there is no limit, 30 graded calibration rows exist, the tree was clean at the preflight and `tree_clean()` still holds; otherwise scratch, with the reason in `notes`.
  - **Writing**: the file is written atomically, and the function returns its path.
  - **Failure**: any exception after the first paid call writes the partial result to scratch, with the error in `notes`, then re-raises.
- Acceptance check: `uv --directory backend run python -m pytest tests/test_eval_run.py` green against testdb with `fake_embed`, `fake_draft`, `fake_judge` and a tiny fixture corpus (one Markdown, one PDF from `tests/pdf.py`):
  - a full run writes to a monkeypatched results dir with every metric present;
  - a second run makes zero embed calls and reports `reused: true`;
  - a changed `chunking.CHUNK_TOKENS` gives a new workspace name;
  - `answer_from_hits` receives the first 5 of 10 hits;
  - `limit`, a missing calibration and a tree dirtied mid-run each go to scratch with the reason;
  - a judge error is recorded and leaves the denominator;
  - an exception mid-loop leaves a partial scratch file and re-raises.
- Red first: import failure; then a `redproof` mutation that passes all 10 hits to `answer_from_hits` fails the same-code-path test.
- Skills to load: none
- Predicted size: 2 files, about 330 lines, 90 minutes

### Task 3.1: Preflight, CLI, outline and scripts

- Files owned: `backend/loreos/evaluation/preflight.py`, `backend/loreos/evaluation/__main__.py`, `backend/loreos/evaluation/fetch.py` (`main` only), `backend/tests/test_eval_preflight.py`, `backend/tests/test_eval_cli.py`, `package.json`
- Depends on: 2.1
- Change:
  - **`preflight(limit)`** runs spec behaviour 4 in order. It prints the plan:
    - questions, answerable and unanswerable counts;
    - embed calls and exact corpus tokens (0 when reused), using `chunking.count_tokens` over `ingest.embedding_input` of every chunk;
    - answer calls and judge calls (up to answers + 30);
    - a token estimate;
    - each broad-label warning.

    It returns whether the tree was clean.
  - **`__main__.cli(argv)`**: argparse with `--mode {vector}`, `--limit N` and `--dry-run`.
    - It refuses unknown arguments with exit 2.
    - `npm_config_dry_run=true` with no arguments is a dry run.
    - `npm_config_limit` or `npm_config_mode` set exits 2 and prints the `--` form.
    - It runs the preflight, then `run.evaluate`, and prints the result path and the metrics.
  - **`fetch.main`** also writes `dataset.CORPUS_DIR / "outline.txt"` when every file is good.
  - **`package.json`** gains `eval:fetch`, `eval:calibration-draft` and `paid:eval`, before the `check:*` group.
- Acceptance check: `uv --directory backend run python -m pytest tests/test_eval_preflight.py tests/test_eval_cli.py tests/test_eval_fetch.py` green; `npm run check:all` green.
  - Preflight: each failure stops before a fake LLM call (a fake that raises if called), and the closest heading is named.
  - CLI: the npm flag cases from spec behaviour 12; `--help` and `--dry-run` never reach `run.evaluate`.
- Red first: import failure; then a `redproof` mutation that skips the tree check fails the dirty-tree case.
- Skills to load: none
- Predicted size: 6 files, about 220 lines, 60 minutes

### Task 3.2: Calibration draft

- Files owned: `backend/loreos/evaluation/calibration.py`, `backend/tests/test_eval_calibration.py`
- Depends on: 2.1 (row shape)
- Change:
  - `draft(result) -> list[dict]` picks 30 non-refused rows spread evenly in id order (all of them when there are fewer, with a printed warning) and maps each to `{id, question, answer, passages, human: null}`. The passages come from the citations, as `{n, source, text}`.
  - `main(argv)` writes `dataset.CALIBRATION` and refuses when it exists. The judge's grade is never copied.
- Acceptance check: `uv --directory backend run python -m pytest tests/test_eval_calibration.py` green:
  - 40 eligible rows give 30 spread across them;
  - refused rows are never picked;
  - no judge field is in the output;
  - an existing file is not overwritten;
  - the passages match the shape `llm.judge` takes.
- Red first: import failure.
- Skills to load: none
- Predicted size: 2 files, about 80 lines, 20 minutes

### Task 3.3: Data, docs and decision (main session)

- Files owned:
  - `eval/corpus.json`, `eval/README.md`
  - `docs/decisions/0003-evaluation-corpus-and-judge.md`, `docs/sdd/v1/brief.md` (decision 3 license fact), `docs/KNOWN-GAPS.md`
  - `docs/sdd/p2-evaluation/STATUS.md`
- Depends on: 1.1 (`manifest_problems` validates `eval/corpus.json`)
- Change:
  - `eval/corpus.json` gets the 44 handbook files at the pinned commit and the PDFs from research, with `sources` attribution.
  - `eval/README.md` explains how to write questions and labels from `outline.txt` and the two-run calibration procedure, and holds the CC BY-SA 4.0 notice for the quoting files.
  - Decision 0003 records the corpus, the license handling, the judge default, the dry run asking, and the heading cleanup.
  - KNOWN-GAPS gains rows for:
    - stale `eval-*` workspaces kept in the database;
    - shortcode noise;
    - the previous-generation answer model.
  - The brief's "(MIT)" gets corrected.
- Acceptance check: `npm run eval:fetch` exits 0 and writes all files and `outline.txt` (free, real hosts); `manifest_problems` is empty.
- Red first: none (data); the fetch is the check.
- Skills to load: none
- Predicted size: 6 files, 45 minutes

## What this plan does NOT cover

- The evaluation set itself: 60 to 100 questions written by the operator (brief decision 10 rejects generated ones). The trigger is the operator committing `eval/questions.jsonl`.
- The two paid runs and the committed baseline (phase 4). The trigger is the set plus `OPENAI_API_KEY`, with the operator's approval at each ask.
- Pruning old `eval-*` workspaces: a KNOWN-GAPS row. The trigger is database size mattering on Supabase.
- Modes other than `vector`: P3.
