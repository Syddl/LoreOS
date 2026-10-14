"""The paid part of `npm run paid:eval`: ingest the corpus, answer and judge every question, write the result file.

Called only after the preflight (`preflight.py`), which records the commit this run must still be at when it writes.
Every `dataset.<NAME>` is read at call time, so a test can point the paths at a temporary directory.
"""

import hashlib
import inspect
import json
import os
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path
from urllib.parse import urlsplit

import openai
from sqlalchemy import text

from loreos import answering, chunking, fusion, ingest, llm, parsing, rerank, retrieval, settings
from loreos.db import RETRIES, engine, workspace_session
from loreos.evaluation import dataset, labels, metrics

SCHEMA = 1
SEARCH_K = 10
MODES = retrieval.MODES
KEYED_SOURCES = (parsing, chunking, ingest)  # the code that shapes stored chunks and their embedding input
# The embedding request and the stored vector text, captured at import so a test's fake never changes the key.
KEYED_FUNCTIONS = (llm.embed, retrieval.vector_literal)
KEYED_LIBRARIES = ("pypdf", "tiktoken")  # PDF text extraction and token counts shape the chunks too


def workspace_name(manifest: dict) -> str:
    """`eval-` and 12 hex of a sha256 over every input that shapes the stored chunks, so a change never reuses stale ones."""
    inputs = [
        dataset.corpus_hash(manifest),
        *[Path(module.__file__).read_bytes().replace(b"\r\n", b"\n").decode() for module in KEYED_SOURCES],
        *[inspect.getsource(function).replace("\r\n", "\n") for function in KEYED_FUNCTIONS],
        *[f"{name}=={metadata.version(name)}" for name in KEYED_LIBRARIES],
        chunking.CHUNK_TOKENS,
        chunking.CHUNK_OVERLAP,
        settings.embedding_model(),
        settings.openai_base_url() or "",
    ]
    return "eval-" + hashlib.sha256(json.dumps(inputs).encode()).hexdigest()[:12]


async def workspace_status(name: str, corpus: dict[str, bytes]) -> tuple[uuid.UUID | None, bool]:
    """The oldest workspace with this name (None when there is none), and whether it holds every corpus file processed."""
    async with engine().connect() as conn:
        workspace_id = await conn.scalar(
            text("select id from loreos.workspaces where name = :n order by created_at, id limit 1"), {"n": name}
        )
    if workspace_id is None:
        return None, False
    async with workspace_session(workspace_id) as session:
        processed = set(
            await session.scalars(
                text("select sha256 from loreos.documents where workspace_id = :w and status = 'processed'"), {"w": workspace_id}
            )
        )
    return workspace_id, all(ingest.sha256(data) in processed for data in corpus.values())


def load_corpus(manifest: dict) -> dict[str, bytes]:
    """Each manifest file's bytes from dataset.CORPUS_DIR; the preflight has already checked their hashes."""
    return {item["file"]: (dataset.CORPUS_DIR / item["file"]).read_bytes() for item in manifest["files"]}


def git_sha() -> str:
    return _git("rev-parse", "HEAD").strip()


def tree_clean() -> bool:
    """No tracked change and no untracked file but a result: an untracked *.json directly in RESULTS_DIR does not count.

    A result is not code, and --mode all, or a chunk sweep at one commit, writes several before any is committed;
    each still records the commit it ran at. Ignored files do not count either.
    """
    exempt = _results_prefix()
    # every untracked file listed, whatever status.showUntrackedFiles says; porcelain paths are from the repo root
    for line in _git("status", "--porcelain", "--untracked-files=all").splitlines():
        path = line[3:]
        if exempt and line.startswith("?? ") and path.startswith(exempt) and path.endswith(".json") and "/" not in path[len(exempt):]:
            continue
        return False
    return True


def _results_prefix() -> str | None:
    """RESULTS_DIR as git prints it under ROOT ('eval/results/'); None, so nothing is exempt, when it lies outside."""
    try:
        return dataset.RESULTS_DIR.relative_to(dataset.ROOT).as_posix() + "/"
    except ValueError:
        return None


def _git(*args: str) -> str:
    command = "git " + " ".join(args)
    try:
        done = subprocess.run(["git", *args], cwd=dataset.ROOT, capture_output=True, encoding="utf-8", errors="replace")
    except OSError as e:
        raise RuntimeError(f"{command} could not run in {dataset.ROOT} ({e}); install git and put it on PATH") from e
    if done.returncode:
        raise RuntimeError(f"{command} failed in {dataset.ROOT} ({done.stderr.strip()}); run the evaluation from a git checkout with a commit")
    return done.stdout


async def evaluate(mode: str, limit: int | None, preflight_sha: str, preflight_notes: list[str]) -> Path:
    """Run the evaluation and write its result file; return the file's path. The preflight's notes open `notes`.

    The result goes to eval/results/ only when every destination rule holds (spec behaviour 5), else to scratch with
    each reason in `notes`. Any stop, Ctrl-C included, first writes the completed rows to scratch, then re-raises.
    """
    if mode not in MODES:
        raise ValueError(f"mode {mode!r} is not supported; use one of: {', '.join(MODES)}")
    manifest = dataset.read_manifest(dataset.MANIFEST)
    questions = dataset.read_jsonl(dataset.QUESTIONS)[:limit]
    calibration = dataset.read_jsonl(dataset.CALIBRATION) if limit is None and dataset.CALIBRATION.is_file() else None
    questions_hash = dataset.text_hash(dataset.QUESTIONS)
    calibration_hash = dataset.text_hash(dataset.CALIBRATION) if calibration is not None else None
    corpus = load_corpus(manifest)
    workspace = {"name": workspace_name(manifest), "reused": None}
    rows: list[dict] = []
    pairs: list[dict] = []
    opening = [f"preflight: {note}" for note in preflight_notes]
    notes: list[str] = []
    llm.USAGE.clear()
    RETRIES.clear()

    def build() -> dict:
        summary = metrics.summarize(rows, pairs)
        missing = llm.USAGE["responses_without_usage"]
        usage_notes = [f"usage: {missing} OpenAI responses reported no token usage; the usage block leaves their tokens out"]
        resets = RETRIES["connect_reset"]
        db_notes = [f"db: {resets} connection attempts were reset while connecting, and retried"]
        return {
            "schema": SCHEMA,
            "git_sha": preflight_sha,
            "created_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "mode": mode,
            "settings": {
                "embedding_model": settings.embedding_model(),
                "answer_model": settings.answer_model(),
                "judge_model": settings.judge_model(),
                "chunk_tokens": chunking.CHUNK_TOKENS,
                "chunk_overlap": chunking.CHUNK_OVERLAP,
                "k": answering.TOP_K,
                "search_k": SEARCH_K,
                "rrf_k": fusion.RRF_K,
                "rerank_model": rerank.RERANK_MODEL,
                # The host alone (never the URL, which may carry credentials): it tells an OpenAI run from another server's.
                "openai_base_url_host": urlsplit(base).hostname if (base := settings.openai_base_url()) else None,
            },
            "corpus_hash": dataset.corpus_hash(manifest),
            "questions_hash": questions_hash,
            "calibration_hash": calibration_hash,
            "destination": "scratch",
            "workspace": dict(workspace),
            "counts": summary["counts"],
            "metrics": summary["metrics"],
            "judge_confusion": summary["judge_confusion"],
            "latency_ms": summary["latency_ms"],
            "usage": {
                "embedding_tokens": llm.USAGE["embedding_input"],
                "answer_input_tokens": llm.USAGE["answer_input"],
                "answer_output_tokens": llm.USAGE["answer_output"],
                "judge_input_tokens": llm.USAGE["judge_input"],
                "judge_output_tokens": llm.USAGE["judge_output"],
            },
            "notes": opening + (usage_notes if missing else []) + (db_notes if resets else []) + notes,  # the preflight's first, a stop's last
            "questions": rows,
        }

    try:
        print(f"workspace {workspace['name']}: ingesting {len(corpus)} files", flush=True)
        workspace_id, workspace["reused"] = await _ingest(workspace["name"], corpus)
        # ponytail: one question at a time keeps the search timings clean, and 100 questions take minutes;
        # run them concurrently if the set grows to thousands.
        for i, question in enumerate(questions, 1):
            row, row_notes = await _ask(workspace_id, question, mode)
            rows.append(row)  # only a complete row, so a partial result's numbers match its rows
            notes.extend(row_notes)
            outcome = (row["judge"]["grade"] or "no verdict") if row["judge"] else f"refused ({row['answer']['reason']})"
            print(f"[{i}/{len(questions)}] {row['id']}: {outcome}", flush=True)  # a paid run is never silent for minutes
        if limit is not None:
            notes.append(f"calibration: skipped, since --limit {limit} was given")
        elif calibration is None:
            notes.append(f"calibration: {dataset.CALIBRATION.name} is missing, so judge agreement is null; "
                         "write it with npm run eval:calibration-draft and grade it")
        else:
            for i, row in enumerate(calibration, 1):
                try:
                    grade = (await llm.judge(row["question"], row["answer"], row["passages"])).grade
                except llm.VerdictError as e:
                    grade = None
                    notes.append(f"calibration {row['id']}: the judge gave no verdict ({e}); left out of judge agreement")
                pairs.append({"id": row["id"], "human": row["human"], "judge": grade})
                print(f"[calibration {i}/{len(calibration)}] {row['id']}: judge {grade or 'no verdict'}, human {row['human']}", flush=True)
        result = build()
        reasons = _scratch_reasons(result, limit, preflight_sha)
        result["notes"] += [f"scratch: {reason}" for reason in reasons]
        if not reasons:
            result["destination"] = "results"
        return _write(result, dataset.SCRATCH_DIR if reasons else dataset.RESULTS_DIR)
    except BaseException as e:  # Ctrl-C and cancellation too: what was done is already paid for
        notes.append(f"stopped: {type(e).__name__}: {e}")
        path = _write(build(), dataset.SCRATCH_DIR)
        print(f"stopped; the partial result is in {path}", file=sys.stderr)
        raise


async def _ingest(name: str, corpus: dict[str, bytes]) -> tuple[uuid.UUID, bool]:
    """Find or create the workspace, then ingest each file in its own transaction; a file not processed stops the run."""
    workspace_id, reused = await workspace_status(name, corpus)
    if workspace_id is None:
        async with engine().begin() as conn:
            workspace_id = await conn.scalar(text("insert into loreos.workspaces (name) values (:n) returning id"), {"n": name})
    for file, data in corpus.items():
        async with workspace_session(workspace_id) as session:
            document = await ingest.ingest(session, workspace_id, file, data)
        if document.status != "processed":
            raise RuntimeError(f"{file}: {document.status} after ingest ({document.error}); fix or replace the file, then run again")
    return workspace_id, reused


async def _ask(workspace_id: uuid.UUID, question: dict, mode: str) -> tuple[dict, list[str]]:
    """One question as POST /api/ask answers it (search, then the first TOP_K hits), then judged; the row and its notes.
    search_ms times the whole search in this mode: the question's embedding, the queries and any rerank."""
    qid, asked = question["id"], question["question"]
    notes = []
    async with workspace_session(workspace_id) as session:
        start = time.perf_counter()
        hits = await retrieval.search(session, workspace_id, asked, SEARCH_K, mode)
        search_ms = round((time.perf_counter() - start) * 1000, 1)
    error = None
    try:
        answer = await answering.answer_from_hits(asked, hits[: answering.TOP_K], mode)
    except openai.APIError:
        raise  # the model or the key is broken, so every later answer would fail too
    except Exception as e:  # no parsed answer, or a length or content-filter stop: the user would get no answer either
        if isinstance(e.__cause__, openai.APIError):
            raise  # draft_answer wraps a rejected request (BadRequestError) for its message; it is still an API failure
        error = f"{type(e).__name__}: {e}"
        answer = answering.Answer(False, answering.REFUSAL, [], "answer_error", mode)
        notes.append(f"{qid}: the answer failed ({error}); recorded as refused with reason answer_error")
    judge = None
    if answer.found:
        passages = [dict(n=c.n, source=llm.source_label(c), text=c.text) for c in answer.citations]
        try:
            verdict = await llm.judge(asked, answer.text, passages)
            judge = {"grade": verdict.grade, "rationale": verdict.rationale, "error": None}
        except llm.VerdictError as e:
            judge = {"grade": None, "rationale": None, "error": str(e)}
            notes.append(f"{qid}: the judge gave no verdict ({e}); left out of faithfulness")
    return _row(question, hits, search_ms, answer, error, judge), notes


def _row(question: dict, hits: list[retrieval.Hit], search_ms: float, answer: answering.Answer, error: str | None, judge: dict | None) -> dict:
    sources = question["sources"]
    answered = {
        "found": answer.found,
        "text": answer.text,
        "reason": answer.reason,
        "citations": [
            {"n": c.n, "chunk_id": str(c.chunk_id), "file": c.filename, "heading_path": c.heading_path, "page": c.page,
             "source": llm.source_label(c), "text": c.text, "relevant": labels.matched_sources(c, sources)}
            for c in answer.citations
        ],
    }
    if error:
        answered["error"] = error
    return {
        "id": question["id"],
        "question": question["question"],
        "answerable": question["answerable"],
        "sources": sources,
        "search_ms": search_ms,
        "hits": [
            {"rank": rank, "chunk_id": str(h.chunk_id), "file": h.filename, "heading_path": h.heading_path, "page": h.page,
             "score": h.score, "relevant": labels.matched_sources(h, sources)}
            for rank, h in enumerate(hits, 1)
        ],
        "answer": answered,
        "judge": judge,
    }


def _scratch_reasons(result: dict, limit: int | None, preflight_sha: str) -> list[str]:
    """Each destination rule (spec behaviour 5) the run breaks, with its fix; none sends the result to eval/results/."""
    counts, numbers = result["counts"], result["metrics"]
    graded = counts["calibration_rows"] - counts["calibration_judge_errors"]
    reasons = []
    if limit is not None:
        reasons.append(f"--limit {limit} was given; a committed result runs the whole set")
    if not dataset.MIN_QUESTIONS <= counts["questions"] <= dataset.MAX_QUESTIONS:
        reasons.append(f"the run covered {counts['questions']} questions; a committed result covers "
                       f"{dataset.MIN_QUESTIONS} to {dataset.MAX_QUESTIONS}")
    if counts["calibration_rows"] != dataset.CALIBRATION_ROWS or counts["calibration_judge_errors"]:
        reasons.append(f"the judge graded {graded} of {counts['calibration_rows']} calibration rows; "
                       f"a committed result needs all {dataset.CALIBRATION_ROWS} graded")
    if numbers["judge_agreement"] is None:
        reasons.append("judge agreement is null; grade eval/judge_calibration.jsonl and run again")
    if counts["judge_errors"]:
        answered = counts["judged"] + counts["judge_errors"]
        reasons.append(f"the judge gave no verdict on {counts['judge_errors']} of {answered} answers, so faithfulness "
                       "covers only part of them; see the verdict errors in notes and run again")
    if numbers["faithfulness"] is None:
        reasons.append("faithfulness is null, since the judge graded no answer; check the verdict errors in notes")
    if not tree_clean():
        reasons.append("the git tree is not clean at the write; commit or remove the changes, then run again")
    if (head := git_sha()) != preflight_sha:
        reasons.append(f"HEAD moved from {preflight_sha[:8]} to {head[:8]} during the run; run again at one commit")
    return reasons


def _write(result: dict, directory: Path) -> Path:
    """A temporary file beside the target, then a rename, so no reader ever sees half a result."""
    directory.mkdir(parents=True, exist_ok=True)
    stamp = result["created_at"].replace("-", "").replace(":", "")
    path = directory / f"{stamp}-{result['mode']}-{result['git_sha'][:8]}.json"
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="\n", dir=directory, suffix=".part", delete=False) as f:
        f.write(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    os.replace(f.name, path)
    return path


def result_problems(result: dict) -> list[str]:
    """Why a file in eval/results/ is not one a run wrote there; check:backend fails on any."""
    problems = []
    if result.get("schema") != SCHEMA:
        problems.append(f"schema is {result.get('schema')!r}, not {SCHEMA}; remove the file and run npm run paid:eval")
    if result.get("destination") != "results":
        problems.append(f"destination is {result.get('destination')!r}; only a run that met every rule writes to "
                        "eval/results/, so remove the file and run npm run paid:eval")
    if (result.get("metrics") or {}).get("judge_agreement") is None:
        problems.append("judge agreement is null; a committed result needs the graded calibration, so remove the file")
    return problems
