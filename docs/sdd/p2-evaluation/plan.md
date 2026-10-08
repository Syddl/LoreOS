# Plan: p2-evaluation

Implements [spec.md](spec.md). Sizing: all fourteen lifecycle steps, since `paid:eval` is a spend surface, with an independent reviewer at step 9. Revised after the plan review in [reviews/plan.md](reviews/plan.md).

## Facts read before planning

- P1's `search(session, workspace_id, query, k)` and `answer_from_hits(question, hits)` are the calls the evaluation makes. `answering.TOP_K` is 5.
  - `Hit` carries `chunk_id, document_id, filename, heading_path, page, text, score`.
  - `Citation` carries `n, chunk_id, document_id, filename, heading_path, page, text`, with no score.
- `ingest(session, workspace_id, filename, data)` deduplicates by sha256 within a workspace and returns a stored document early unless it `failed`. A failure is recorded on the document and the transaction still commits. So a rerun over a processed workspace embeds no chunk. `search` still embeds each question.
- `llm.embed` and `llm.draft_answer` discard `response.usage`. `llm._source(hit)` formats `file > heading path, page n`. `llm.py` is documented as the only module that calls OpenAI, and the judge goes there too.
- `smoke.preflight()` checks that the key is set, that the migration is at head, and that listing models is accepted. Tests patch `smoke.preflight` and `smoke.main`. `smoke.py`'s entry point calls `sys.stdout.reconfigure(errors="replace")`.
- `chunking.chunk(sections, max_tokens=CHUNK_TOKENS, ...)` binds its defaults at definition time. The workspace key reads `chunking.CHUNK_TOKENS` at call time.
- Already in place:
  - `.gitignore` ignores `docs/sdd/*/scratch/`.
  - `protected_paths.deny` holds `eval/results/**`, and `protected_paths.ask` holds `.env.*`, which covers `.env.example`.
  - `scripts/check-spend.mjs` pins `paid:eval` and `python -m loreos.evaluation` as ask, with `--dry-run` too.
- `tests/test_config.py` pins the exact set of env keys that `settings.py` reads against `.env.example`.
- The harness `redproof.mjs` refuses a target file git does not track, and a tree with other uncommitted changes.
- Research (main session, three read-only agents):
  - Handbook: `gitlab.com/gitlab-com/content-sites/handbook`, commit `8d0947598af36ea1a8d534028f103f8277976716`. Its content is CC BY-SA 4.0. 44 pages, about 129k tokens, all hashed.
  - Raw URLs `https://gitlab.com/gitlab-com/content-sites/handbook/-/raw/<sha>/content/<path>` return 200. A missing file returns 404 with an HTML body.
  - Ten headings in the chosen pages carry `{#id}`, three of them with no space before it; three carry `<i>` tags.
  - PDFs: NIST CSF 2.0 (32 pages), NIST AI RMF 1.0 (48), NIST SP 800-88r2 (48) and OSHA 3885 (40). All are US government works and extract cleanly with pypdf, with no empty page.
    - NIST serves new bytes behind the same URL, so the manifest uses Wayback `id_` snapshots. Each snapshot was verified byte-identical, and urllib's default User-Agent works there and on GitLab.
    - Labels use physical pages. The printed folio is offset by 4 to 9 pages.
  - OpenAI: `gpt-6.1-sol` costs $2 / $10 per 1M input / output tokens. `reasoning_effort` `low` is supported, and `none` is rejected.
    - Chat usage is `usage.prompt_tokens` / `usage.completion_tokens`; the latter includes reasoning tokens, and `usage` can be `None`.
    - Embeddings usage is `usage.prompt_tokens`. `seed` is deprecated.
    - `parse()` raises `LengthFinishReasonError` / `ContentFilterFinishReasonError`. API failures are subclasses of `openai.APIError`.
- Operator decisions:
  - Keep the handbook and license the quoting files under `eval/` CC BY-SA 4.0.
  - `JUDGE_MODEL` defaults to `gpt-6.1-sol`.
  - Strip `{#id}` and HTML from Markdown headings.

## Design choices inside the spec

- **Module layout** under `backend/loreos/evaluation/`:
  - `__init__.py` is empty, so importing `fetch` or `calibration` runs no paid code.
  - `dataset.py`: the paths, the constants and the file validators.
  - `labels.py`: relevance and the outline.
  - `metrics.py`: pure numbers.
  - `fetch.py`: `eval:fetch` and the corpus hash check.
  - `run.py`: the workspace, the per-question loop and the result file.
  - `preflight.py`: the checks and the estimate.
  - `calibration.py`: the draft.
  - `__main__.py`: the `paid:eval` CLI.
- **Each fact has one owner.**
  - Paths: `dataset.{EVAL_DIR, QUESTIONS, CALIBRATION, MANIFEST, CORPUS_DIR, RESULTS_DIR, SCRATCH_DIR}`.
  - Counts: `dataset.CALIBRATION_ROWS = 30`, `MIN_QUESTIONS = 60`, `MAX_QUESTIONS = 100`, `UNANSWERABLE_RANGE = (10, 20)`.
  - Corpus file check: `fetch.corpus_problems`, over raw bytes with `ingest.sha256`. Both fetch's skip and the preflight use it.

  Every reader reads `dataset.<NAME>` at call time, for paths and counts alike, never `from dataset import <NAME>`. Tests monkeypatch them, and a copied name would send a test's output into the real `eval/results/`.
- **A file's kind comes from `parsing.kind_of(file, b"")`**, so validation and ingest agree on Markdown versus PDF. A `.txt` source cannot be labeled (no headings, no pages), and the validator says so.
- **The run is sequential.** About 100 questions at a few seconds each is well under the time a person waits, and sequential calls keep the search latency numbers clean.
- **The judge prompt.** System message:

  > You grade whether an answer is faithful to the numbered passages it cites. Split the answer into its factual claims. A claim is supported only if the passages state it or directly imply it; paraphrase counts, but outside knowledge does not, even when the claim is true. Markers like [2] point to the passage with that number. Grade "faithful" only if every claim is supported; one unsupported or contradicted claim makes it "unfaithful". Do not penalise hedges or statements that something is not covered. Write a one-sentence rationale naming the first unsupported claim, or confirming that all claims are supported, before the grade.

  The user message is `Question: <q>`, then `Passages:` with each passage as `[n] <source>\n<text>`, then `Answer: <a>`. The schema is `Verdict(rationale: str, grade: Literal["faithful", "unfaithful"])`, with the rationale first so it is generated before the grade.
- **Judge failure classes** (spec behaviour 7). `llm.judge` raises `llm.VerdictError` for a refusal, a `None` parse, `LengthFinishReasonError` or `ContentFilterFinishReasonError`. The run records a `VerdictError` on the row. Any `openai.APIError` stops the run.
- **Fakes in tests**: `fake_embed` and `fake_draft` (P1), plus `fake_judge` in `conftest.py`. When its `.reply` is an exception, it raises it. `.calls` records `(question, answer, passages)`, so a test can check exactly which passages the judge got. The git checks go through `run.git_sha()` and `run.tree_clean()`, and tests patch them. `smoke.preflight` is patched to a no-op where a test is not about it.
- **Each implementer works in its own git worktree** (the Agent tool's worktree isolation). It runs its red and green checks there and commits its owned paths with explicit paths, with no attribution trailer. The main session reads each commit message, then cherry-picks the task's commits onto `p2-evaluation`, re-committing with `-n` when a message carries a trailer. Then it removes the worktree.
- **The main session runs each `redproof`**, in the foreground, right after cherry-picking that task, where the target is tracked and the tree is clean. Inside a subagent, a `redproof` command naming `backend/loreos/evaluation/...` or `llm.py` next to `uv ... python` matches the spend pattern, and the guard denies it. The operator approves each one at the ask. The implementer reports its red-first run and the exact mutation to apply. Task 1.6 (`parsing.py`) matches no pattern, so its implementer runs its own proof with `--project` set to its worktree.
- **Each task's acceptance check runs only its own test files** and the existing tests it names. `npm run check:all` runs once per phase, from the main session, after the cherry-picks.
- **Entry points** (`__main__`, `fetch`, `calibration`) call `sys.stdout.reconfigure(errors="replace")` as `smoke.py` does. A heading that cp1252 cannot print must not crash a run after spend.

## Phases

| Phase | Goal | Depends on | Check at the end |
|---|---|---|---|
| 1 | Pure parts: validators, labels, metrics, fetch, judge and usage, heading cleanup | none | main session: `npm run check:all` green after the six cherry-picks |
| 2 | The run: workspace key and reuse, per-question loop, judge passes, result file and destination | phase 1 | `npm run check:all` green |
| 3 | Preflight, CLI, calibration draft, scripts, data and docs | phase 2 | Three checks:<br>- `npm run check:all` green.<br>- `npm run eval:fetch` downloads and verifies the real corpus and writes `outline.txt` (free).<br>- `npm run paid:eval -- --dry-run`, approved at the ask, exits non-zero naming the missing `eval/questions.jsonl`, with no paid call. |
| 4 | Baseline (operator) | phase 3, the evaluation set, `OPENAI_API_KEY` | In order:<br>1. `npm run paid:eval -- --dry-run` exits 0 with an estimate.<br>2. Run 1 goes to scratch.<br>3. `eval:calibration-draft`, then grading.<br>4. Run 2 goes to `eval/results/`, committed. |

## Parallel windows

| Window | Tasks | Shared files (must be none) |
|---|---|---|
| A | 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, each in its own worktree | none: `conftest.py` belongs to 1.5 alone |
| B | 2.1 | none |
| C | 3.1, 3.2, each in its own worktree; then 3.3 by the main session | none: `package.json`, `fetch.py`'s `main` and `test_eval_fetch.py` belong to 3.1 |

`.env.example` gains `JUDGE_MODEL` from the main session before window A, since editing it asks the operator. `test_config.py` stays red until task 1.5 lands, and only 1.5 runs it.

## Handoff contracts

| From | To | Handoff |
|---|---|---|
| 1.1 | 1.3, 2.1, 3.1, 3.2 | **Paths and constants**: those listed in "Each fact has one owner".<br>**Readers**:<br>- `read_jsonl(path) -> list[dict]`, which raises `DatasetError` naming the path and line.<br>- `read_manifest(path) -> dict`.<br>**Validators**:<br>- `question_problems(rows) -> list[str]`.<br>- `calibration_problems(rows) -> list[str]`.<br>- `manifest_problems(manifest) -> list[str]`. Each file needs a relative path with forward slashes and no `..`, an http(s) url and a 64-hex sha256; files are unique by `file`, and each falls under exactly one `sources[].files` prefix.<br>**Hashes**:<br>- `text_hash(path) -> str`: sha256 after CRLF to LF, for questions and calibration only.<br>- `corpus_hash(manifest) -> str`: sha256 over the sorted `file\tsha256\n` lines. |
| 1.2 | 2.1, 3.1 | - `is_relevant(hit, source) -> bool`; a hit is any object with `filename`, `heading_path` and `page`.<br>- `matched_sources(hit, sources) -> list[int]`.<br>- `OutlineEntry(file, heading_path, page, chunks)` and `outline(corpus: dict[str, bytes]) -> list[OutlineEntry]`.<br>- `label_problems(questions, entries) -> list[str]`, which names the closest heading.<br>- `broad_labels(questions, entries, max_chunks=3) -> list[str]`.<br>- `render_outline(entries) -> str`. |
| 1.3 | 2.1 | `summarize(rows, calibration) -> {"metrics", "judge_confusion", "latency_ms", "counts"}` over the row shape below. `percentile(values, q) -> float \| None`, by nearest rank. |
| 1.4 | 3.1 | - `corpus_problems(manifest, corpus_dir) -> list[str]`: each file missing or with the wrong sha256, by raw bytes.<br>- `fetch(manifest, corpus_dir) -> list[str]`: the problems found; downloads with `urllib.request`.<br>- `main() -> int`. |
| 1.5 | 2.1, 3.1 | **Usage and verdicts**:<br>- `llm.USAGE`, a `collections.Counter` with keys `embedding_input`, `answer_input`, `answer_output`, `judge_input`, `judge_output` and `responses_without_usage`.<br>- `llm.Verdict`.<br>- `llm.VerdictError(RuntimeError)`.<br>**Functions**:<br>- `async llm.judge(question, answer, passages: list[dict{n, source, text}]) -> Verdict`.<br>- `llm.source_label(hit_or_citation) -> str`, renamed from `_source`.<br>**Settings**: `settings.judge_model()` and `settings.DEFAULT_JUDGE_MODEL = "gpt-6.1-sol"`.<br>**Test fixture**: conftest `fake_judge`, with `.reply` (a `Verdict`, or an exception to raise) and `.calls` (a list of `(question, answer, passages)`). |
| 2.1 | 3.1, 3.2 | **Corpus and workspace**:<br>- `run.workspace_name(manifest) -> str`.<br>- `async run.workspace_status(name, corpus) -> (workspace_id \| None, reused: bool)`.<br>- `run.load_corpus(manifest) -> dict[str, bytes]`.<br>**Git**: `run.git_sha() -> str`, `run.tree_clean() -> bool`.<br>**The paid part**: `async run.evaluate(mode, limit, preflight_sha: str) -> Path`. It runs after the preflight, which records `git_sha()`.<br>**Result**: the result file shape in the spec, with rows as below. |

Row shape (one per question; 1.3 reads it, 2.1 writes it, 3.2 reads it):

```
{id, question, answerable, sources, search_ms,
 hits: [{rank, chunk_id, file, heading_path, page, score, relevant: [source index, ...]}],
 answer: {found, text, reason, citations: [{n, chunk_id, file, heading_path, page, source, text, relevant: [source index, ...]}]},
 judge: null | {grade: "faithful" | "unfaithful" | null, rationale, error}}
```

`judge` is `null` for a refused answer. Calibration pairs for `summarize` are `[{id, human, judge: grade | None}]`; `None` marks a verdict failure.

## Tasks

### Task 1.1: Evaluation set and calibration validators

- Files owned: `backend/loreos/evaluation/__init__.py`, `backend/loreos/evaluation/dataset.py`, `backend/tests/test_eval_set.py`
- Depends on: none
- Change:
  - Adds the paths, constants, readers, validators and hashes per the contract.
  - `question_problems` covers:
    - required keys and types, and unique ids;
    - an unanswerable count within `UNANSWERABLE_RANGE`;
    - sources on exactly the answerable rows;
    - a Markdown source with a non-empty `heading_path` of strings and no `page`;
    - a PDF source with an int `page >= 1` and no `heading_path`;
    - a `.txt` or unknown file refused.

    The total of 60 to 100 is a destination rule in 2.1, not a validation rule, so the operator can run `--limit` while still writing questions.
  - `calibration_problems` covers: exactly `CALIBRATION_ROWS` rows, unique ids, `human` in {faithful, unfaithful}, and each passage `{n: int >= 1, source: str, text: str}`.
  - The test validates the committed `eval/questions.jsonl` and `eval/judge_calibration.jsonl` when each exists, and skips naming the file when it does not. It also validates the committed `eval/corpus.json` when it exists.
- Acceptance check: `uv --directory backend run python -m pytest tests/test_eval_set.py` green. It needs one failing fixture per rule above, plus a valid fixture of 10 unanswerable and 2 answerable rows that passes.
- Red first: the test fails on import before `dataset.py` exists. After the cherry-pick, the main session's `redproof` removes the sources-on-unanswerable rule and its fixture test goes red.
- Skills to load: none
- Predicted size: 3 files, about 170 lines, 30 minutes

### Task 1.2: Relevance and the corpus outline

- Files owned: `backend/loreos/evaluation/labels.py`, `backend/tests/test_eval_labels.py`
- Depends on: none (reads `parsing` and `chunking`)
- Change:
  - Adds the functions in the contract.
  - `outline` parses each file and chunks each section alone, so it counts chunks per section.
  - A label heading path resolves when it is a list prefix of some section's path; its chunk count is the sum over those sections. A page resolves when that page has a section.
  - `label_problems` names the closest heading path with `difflib.get_close_matches` over the `" > "`-joined paths.
- Acceptance check: `uv --directory backend run python -m pytest tests/test_eval_labels.py` green. It covers:
  - prefix match, and a sibling path sharing only its first element does not match;
  - page match;
  - another file never matches, even with the same path;
  - `matched_sources` returns indices;
  - an unknown heading names its closest match;
  - a broad label is warned;
  - the outline renders paths and pages with chunk counts.
- Red first: import failure. After the cherry-pick, the main session's `redproof` turns the prefix test into "first element equal" and the sibling case goes red.
- Skills to load: none
- Predicted size: 2 files, about 130 lines, 30 minutes

### Task 1.3: Metrics

- Files owned: `backend/loreos/evaluation/metrics.py`, `backend/tests/test_eval_metrics.py`
- Depends on: none (the row shape is above)
- Change:
  - `summarize` and `percentile`, exactly as spec behaviour 8 defines them.
  - Citation accuracy is pooled.
  - Faithfulness and judge agreement count only graded answers and graded calibration rows.
  - `counts` holds `questions`, `answerable`, `unanswerable`, `refused`, `judged`, `judge_errors`, `calibration_rows` and `calibration_judge_errors`.
- Acceptance check: `uv --directory backend run python -m pytest tests/test_eval_metrics.py` green. It covers:
  - a hand-computed fixture of about six rows, every metric to the exact value;
  - zero denominators give `None` for each metric;
  - p50 and p95 by nearest rank on a known list, and `percentile([])` is `None`;
  - a calibration verdict failure leaves the agreement denominator.
- Red first: import failure. After the cherry-pick, the main session's `redproof` averages citation accuracy per question instead of pooling it, and the fixture goes red.
- Skills to load: none
- Predicted size: 2 files, about 140 lines, 30 minutes

### Task 1.4: Fetch

- Files owned: `backend/loreos/evaluation/fetch.py`, `backend/tests/test_eval_fetch.py`, `.gitignore`
- Depends on: none (the manifest is passed in; `main` reads `loreos.evaluation.dataset.MANIFEST` at call time, and the test does not call `main`)
- Change:
  - `corpus_problems` and `fetch` follow the contract. `fetch` skips a file `corpus_problems` finds good, and downloads every other one with `urllib.request` (timeout 60 s).
  - A non-200 status or a sha256 mismatch is a problem naming the file and the reason, and leaves no file at that path. Bytes go to a `.part` file, renamed only after the hash matches.
  - A `file` that would land outside `corpus_dir` is refused.
  - `main()` prints a summary and returns 1 on any problem. Writing the outline comes in 3.1.
  - `.gitignore` gains `eval/corpus/`.
- Acceptance check: `uv --directory backend run python -m pytest tests/test_eval_fetch.py` green, against an `http.server` on 127.0.0.1 in a thread. It covers:
  - a good file is written;
  - a wrong sha256 fails naming the file and leaves nothing;
  - a 404 fails naming the file;
  - a second fetch makes no request;
  - a `../` path is refused;
  - `corpus_problems` names a missing file and a changed one.
- Red first: import failure. After the cherry-pick, the main session's `redproof` writes the target before verifying, and "leaves nothing" goes red.
- Skills to load: none
- Predicted size: 3 files, about 130 lines, 30 minutes

### Task 1.5: Judge, usage counter and JUDGE_MODEL

- Files owned: `backend/loreos/llm.py`, `backend/loreos/settings.py`, `backend/tests/test_config.py`, `backend/tests/test_llm_judge.py`, `backend/tests/conftest.py`
- Depends on: none (the main session adds `JUDGE_MODEL=gpt-6.1-sol` to `.env.example` first)
- Change:
  - **Usage**: the `USAGE` counter. `embed` adds `usage.prompt_tokens`; `draft_answer` and `judge` add `prompt_tokens` and `completion_tokens`. A response whose `usage` is `None` adds `responses_without_usage`.
  - **Judge**:
    - `Verdict`, `VerdictError` and `judge()` follow the contract and the prompt in "Design choices".
    - `judge()` calls `chat.completions.parse` with `model=settings.judge_model()` and `reasoning_effort="low"`, with no temperature, seed or max tokens.
    - A refusal, a `None` parse, `LengthFinishReasonError` or `ContentFilterFinishReasonError` raises `VerdictError`. Every `openai.APIError` propagates.
  - **Renames and settings**: `_source` becomes `source_label`. `settings.judge_model()` returns `_env("JUDGE_MODEL") or DEFAULT_JUDGE_MODEL`, and `test_config.py` pins `JUDGE_MODEL` and its default.
  - **Fixture**: the conftest gains `fake_judge`.
- Acceptance check: `uv --directory backend run python -m pytest tests/test_llm_judge.py tests/test_config.py tests/test_answering.py tests/test_no_openai.py` green (no database needed). The fake client is `llm.client` patched to an async context manager whose `chat.completions.parse` and `embeddings.create` record their kwargs and return `SimpleNamespace` responses. The checks:
  - only the passages given are sent, with their numbers;
  - the model and `reasoning_effort` are right, with no `temperature` or `seed`;
  - `USAGE` gains the right counts for embed, draft and judge;
  - `usage=None` counts `responses_without_usage`;
  - a refusal raises `VerdictError`;
  - an `openai.APIError` raised by the fake propagates unchanged.
- Red first: `ImportError` on `llm.judge`, and `test_config` fails on the missing `JUDGE_MODEL`. After the cherry-pick, the main session's `redproof` numbers the passages by position (`enumerate`) instead of by their `n`, and the "with their numbers" test goes red.
- Skills to load: none
- Predicted size: 5 files, about 160 lines, 40 minutes

### Task 1.6: Heading cleanup

- Files owned: `backend/loreos/parsing.py`, `backend/tests/test_parsing.py`
- Depends on: none
- Change: Markdown heading text drops a trailing `{#...}` block (with or without a space before it) and every HTML tag, then is stripped. A heading that becomes empty stays in the path as `""`, as an empty heading does now.
- Acceptance check: `uv --directory backend run python -m pytest tests/test_parsing.py` green, with new cases for:
  - `## Title {#id}`;
  - `## Collaboration{#collab}`;
  - `## <i class="fas"></i>Compliance`;
  - `## Use {braces} here` (unchanged);
  - a nested path that mixes them.
- Red first: the new cases fail on the current parser. After its commit, the implementer runs `redproof` in its worktree (`--project` set to the worktree; `parsing.py` matches no spend pattern). It removes the anchor regex, and the new cases go red.
- Skills to load: none
- Predicted size: 2 files, about 30 lines, 15 minutes

### Task 2.1: The run

- Files owned: `backend/loreos/evaluation/run.py`, `backend/tests/test_eval_run.py`
- Depends on: 1.1, 1.2, 1.3, 1.4, 1.5
- Change:
  - **Workspace and git helpers**: `workspace_name` (a key that includes `OPENAI_BASE_URL`), `workspace_status`, `load_corpus`, `git_sha` and `tree_clean` per the contract.
  - **`evaluate(mode, limit, preflight_sha)`**:
    1. Clears `llm.USAGE`.
    2. Finds or creates the workspace by name, then ingests each corpus file in its own `workspace_session`. Any file not `processed` stops the run, naming the file and its stored error, before any answer call.
    3. Runs the questions: search with k=10, timed, then `answer_from_hits` with the first 5.
    4. Judges each non-refused answer with only its cited passages, `{n, source, text}` built from the answer's citations, under their original numbers. A `VerdictError` is recorded on the row and in `notes`.
    5. Judges the calibration rows, unless `limit` is set.
    6. Calls `metrics.summarize` and builds the result. Its `usage` block maps `llm.USAGE` keys, and a non-zero `responses_without_usage` adds a note.
  - **Destination**: decided per spec behaviour 5, every unmet condition a note. The calibration condition reads `counts.calibration_rows == dataset.CALIBRATION_ROWS` and `counts.calibration_judge_errors == 0`, not just a non-null agreement. The file is written atomically, and the function returns the path.
  - **Partial results**: a `BaseException` after the workspace step writes the partial result to scratch with the error in `notes`, then re-raises.
  - **Committed results**: a test checks each committed file under `eval/results/` for `destination == "results"` and a non-null judge agreement.
- Acceptance check: `uv --directory backend run python -m pytest tests/test_eval_run.py` green against testdb. It uses `fake_embed`, `fake_draft`, `fake_judge`, and a tiny fixture corpus of one Markdown file and one PDF from `tests/pdf.py`, with the `dataset` paths patched. It covers:
  - **A full run**: written to the patched results dir, every metric present.
  - **Usage**: a stale count seeded into `llm.USAGE` before the call is gone from the result's `usage`. Counts that a fake adds during the run appear there, and a `responses_without_usage` count added during the run produces its note.
  - **Judge input**: for an answer citing [2] and [4] of 5 hits, the passages in `fake_judge.calls` are exactly `[{n: 2, ...}, {n: 4, ...}]`, with texts from those hits.
  - **Reuse**: a second run sends no chunk text to `fake_embed` and reports `reused: true`.
  - **The workspace key**: a changed `chunking.CHUNK_TOKENS` or `OPENAI_BASE_URL` gives a new workspace name.
  - **The same code path**: `answer_from_hits` receives the first 5 of 10 hits.
  - **Ingest failure**: a failing corpus file stops the run naming the file, and `fake_draft.calls == []`.
  - **Destination**: each case in spec acceptance row 5 goes to scratch with its reason. So do a single calibration verdict failure out of 30, and more than 100 questions.
  - **Failure classes**: a `VerdictError` is recorded, and the run continues.
  - **Partial results**: an `openai.APIError` or a `KeyboardInterrupt` mid-loop leaves a partial scratch file and re-raises.
  - **Committed results**: the check passes on an empty `eval/results/` and fails on a fixture scratch file.
- Red first: import failure. After the cherry-pick, the main session runs two `redproof` mutations:
  - it passes all 10 hits to `answer_from_hits`, and the same-code-path test goes red;
  - it gives the judge every hit instead of the cited passages, and the judge-input test goes red.
- Skills to load: none
- Predicted size: 2 files, about 380 lines, 90 minutes

### Task 3.1: Preflight, CLI, outline and scripts

- Files owned: `backend/loreos/evaluation/preflight.py`, `backend/loreos/evaluation/__main__.py`, `backend/loreos/evaluation/fetch.py` (`main` only), `backend/tests/test_eval_preflight.py`, `backend/tests/test_eval_cli.py`, `backend/tests/test_eval_fetch.py`, `package.json`
- Depends on: 2.1
- Change:
  - **`preflight(limit) -> str`** runs spec behaviour 4 in order and returns `run.git_sha()`. Model names are checked with one `models.list` through `llm.client()`; an `APIStatusError` there is noted and skipped, as `paid:smoke` does. It prints the plan:
    - question counts;
    - embed calls and exact corpus tokens (0 when reused), from `chunking.count_tokens` over `ingest.embedding_input` of every chunk;
    - answer calls and judge calls (up to answers + `CALIBRATION_ROWS`);
    - a token estimate;
    - the broad-label warnings.
  - **`__main__.cli(argv)`**: argparse with `--mode {vector}`, `--limit N` (an integer of at least 1) and `--dry-run`.
    - Unknown arguments exit 2.
    - `npm_config_dry_run=true` with no arguments is a dry run.
    - `npm_config_limit` or `npm_config_mode` set exits 2 and prints the `--` form.
    - Otherwise it runs `preflight`, then `run.evaluate(mode, limit, sha)`, and prints the result path and metrics.
  - **`fetch.main`** also writes `dataset.CORPUS_DIR / "outline.txt"` when every file is good.
  - **`package.json`** gains `eval:fetch`, `eval:calibration-draft` and `paid:eval`, before the `check:*` group.
- Acceptance check: `uv --directory backend run python -m pytest tests/test_eval_preflight.py tests/test_eval_cli.py tests/test_eval_fetch.py` green.
  - **Preflight**, against a tiny fixture corpus:
    - a missing set and an invalid set or calibration file are refused;
    - an unresolved label is refused, naming its closest heading;
    - a hash mismatch and duplicate bytes are refused;
    - a dirty tree is refused;
    - a missing model name is refused;
    - each stops before a fake that raises when called;
    - `smoke.preflight` is called, and the order holds;
    - the printed corpus token count equals the token count of the texts `fake_embed` receives when the same corpus is really ingested. That case needs testdb, the only database use in window C.
  - **CLI**:
    - the npm flag cases from spec behaviour 12;
    - `--limit 0` exits 2;
    - `--help` and `--dry-run` never reach `run.evaluate`;
    - a preflight raising `SystemExit` never reaches it;
    - the preflight's sha is passed through.
  - **Fetch**: `main` writes `outline.txt`.
- Red first: import failure. After the cherry-pick, the main session's `redproof` skips the tree check, and the dirty-tree case goes red.
- Skills to load: none
- Predicted size: 7 files, about 260 lines, 70 minutes

### Task 3.2: Calibration draft

- Files owned: `backend/loreos/evaluation/calibration.py`, `backend/tests/test_eval_calibration.py`
- Depends on: 2.1 (the row shape)
- Change:
  - `draft(result) -> list[dict]` picks `CALIBRATION_ROWS` non-refused rows, spread evenly in id order. Each becomes `{id, question, answer, passages, human: null}`, with passages `{n, source, text}` from the citations. The judge's grade is never copied.
  - `main(argv)` writes `dataset.CALIBRATION`. It refuses, with exit 1, when the file exists or when fewer than `CALIBRATION_ROWS` rows are eligible.
  - A relative result path resolves against `INIT_CWD`, which npm sets to the directory the operator ran it from, else against the repo root. `uv --directory backend` makes Python's own working directory `backend/`.
- Acceptance check: `uv --directory backend run python -m pytest tests/test_eval_calibration.py` green:
  - 40 eligible rows give 30 spread across them;
  - refused rows are never picked;
  - no judge field is in the output;
  - an existing file is not overwritten;
  - 29 eligible rows exit 1;
  - a relative path resolves against `INIT_CWD`;
  - the passages match `llm.judge`'s shape.
- Red first: import failure. After the cherry-pick, the main session's `redproof` copies the judge grade into the row, and the no-judge-field test goes red.
- Skills to load: none
- Predicted size: 2 files, about 90 lines, 20 minutes

### Task 3.3: Data, docs and decision (main session)

- Files owned:
  - `eval/corpus.json`, `eval/README.md`
  - `docs/decisions/0003-evaluation-corpus-and-judge.md`, `docs/sdd/v1/brief.md` (decision 3's license fact), `docs/KNOWN-GAPS.md`
  - `docs/sdd/p2-evaluation/STATUS.md`
- Depends on: 1.1 (its test validates `eval/corpus.json`) and 3.1 (`eval:fetch` writes the outline)
- Change:
  - **`eval/corpus.json`**: the 44 handbook files at the pinned commit and the 4 PDFs, with the `sources` attribution.
  - **`eval/README.md`**: how to write questions and labels from `outline.txt` (physical pages for PDFs), the two-run calibration procedure, and the CC BY-SA 4.0 notice for the quoting files.
  - **Decision 0003** records:
    - the corpus and the license handling;
    - the judge default and its failure classes;
    - the dry run asking;
    - the heading cleanup.
  - **KNOWN-GAPS** gains rows for:
    - stale `eval-*` workspaces kept in the database;
    - shortcode noise;
    - the previous-generation answer model;
    - edit-tool-only protection of `eval/results/`, backed by the committed-result check.
  - **The brief**: its "(MIT)" is corrected.
- Acceptance check: `npm run check:backend` validates `eval/corpus.json`; `npm run eval:fetch` exits 0 and writes all 48 files and `outline.txt` (free, real hosts).
- Red first: none (data); the fetch is the check.
- Skills to load: none
- Predicted size: 6 files, 45 minutes

## What this plan does NOT cover

- The evaluation set itself: 60 to 100 questions written by the operator (brief decision 10 rejects generated ones). The trigger is the operator committing `eval/questions.jsonl`.
- The two paid runs and the committed baseline (phase 4). The trigger is the set plus `OPENAI_API_KEY`, with the operator's approval at each ask.
- Pruning old `eval-*` workspaces: a KNOWN-GAPS row. The trigger is database size mattering on Supabase.
- Modes other than `vector`: P3.
