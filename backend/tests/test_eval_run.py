"""The evaluation run against testdb, with fake embeddings, drafts and verdicts over a tiny corpus in tmp_path."""

import asyncio
import collections
import hashlib
import json
import re
import subprocess
import uuid
from types import SimpleNamespace

import httpx2  # the SDK's own HTTP module, to build the request its errors carry
import openai
import pytest

from conftest import sql
from loreos import answering, chunking, llm, settings
from loreos.evaluation import dataset, run
from pdf import make_pdf

SHA = "0123456789abcdef0123456789abcdef01234567"
MD = "handbook/guide.md"
PDF = "nist/report.pdf"
GUIDE = "# Guide\n\n" + "".join(f"## Topic {i}\n\nThe code word for topic {i} is word{i}.\n\n" for i in range(1, 13))
CORPUS = {MD: GUIDE.encode(), PDF: make_pdf(["Page one sets the alpha rule.", "Page two sets the beta rule."])}
CHUNKS = 12 + 2  # one per Markdown topic, one per PDF page
REQUEST = httpx2.Request("POST", "https://api.openai.com/v1/chat/completions")
RESULT_KEYS = [
    "schema", "git_sha", "created_at", "mode", "settings", "corpus_hash", "questions_hash", "calibration_hash",
    "destination", "workspace", "counts", "metrics", "judge_confusion", "latency_ms", "usage", "notes", "questions",
]


def manifest(files):
    return {
        "sources": [
            {"name": "Guide", "home": "https://example.com", "license": "CC BY-SA 4.0", "attribution": "Example", "files": "handbook/"},
            {"name": "NIST", "home": "https://example.gov", "license": "Public domain", "attribution": "NIST", "files": "nist/"},
        ],
        "files": [{"file": f, "url": f"https://example.com/{f}", "sha256": hashlib.sha256(d).hexdigest()} for f, d in files.items()],
    }


def questions(n, unanswerable=15):
    """n questions: the first `unanswerable` have no sources, then they alternate Markdown and PDF labels."""
    rows = []
    for i in range(1, n + 1):
        qid = f"q{i:03}"
        if i <= unanswerable:
            rows.append({"id": qid, "question": f"What does the café on floor {i} serve?", "answerable": False, "sources": []})
        elif i % 2:
            topic = i % 12 + 1
            rows.append({"id": qid, "question": f"What is the code word for topic {topic}?", "answerable": True,
                         "sources": [{"file": MD, "heading_path": ["Guide", f"Topic {topic}"]}]})
        else:
            rows.append({"id": qid, "question": "Which rule does page one set?", "answerable": True,
                         "sources": [{"file": PDF, "page": 1}]})
    return rows


def calibration():
    """30 graded rows: 20 faithful, then 10 unfaithful."""
    return [
        {"id": f"c{i:02}", "question": f"Calibration question {i}?", "answer": f"Calibration answer {i} [1].",
         "passages": [{"n": 1, "source": f"{MD} > Guide > Topic 1", "text": f"Passage {i}."}],
         "human": "faithful" if i <= 20 else "unfaithful"}
        for i in range(1, 31)
    ]


def write_jsonl(path, rows):
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def write_corpus(files):
    for name, data in files.items():
        path = dataset.CORPUS_DIR / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    dataset.MANIFEST.write_text(json.dumps(manifest(files)), encoding="utf-8")


def evaluate(limit=None, preflight_notes=()):
    return asyncio.run(run.evaluate("vector", limit, SHA, list(preflight_notes)))


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def only_scratch_file():
    [path] = dataset.SCRATCH_DIR.glob("*.json")
    return path


def wrap(monkeypatch, name, before):
    """Replace llm.<name> with a call to before(*args), then the current fake; before may raise."""
    inner = getattr(llm, name)

    async def wrapped(*args):
        before(*args)
        return await inner(*args)

    monkeypatch.setattr(llm, name, wrapped)


def raise_on(question, error):
    def before(asked, *rest):
        if asked == question:
            raise error

    return before


@pytest.fixture
def ev(tmp_path, monkeypatch, clean, fake_embed, fake_draft, fake_judge):
    """The dataset paths under tmp_path with the corpus, 60 questions and 30 graded calibration rows; git clean at SHA."""
    for name, relative in [("QUESTIONS", "questions.jsonl"), ("CALIBRATION", "judge_calibration.jsonl"), ("MANIFEST", "corpus.json"),
                           ("CORPUS_DIR", "corpus"), ("RESULTS_DIR", "results"), ("SCRATCH_DIR", "scratch")]:
        monkeypatch.setattr(dataset, name, tmp_path / relative)
    monkeypatch.setattr(run, "git_sha", lambda: SHA)
    monkeypatch.setattr(run, "tree_clean", lambda: True)
    monkeypatch.setattr(llm, "USAGE", collections.Counter())
    write_corpus(CORPUS)
    write_jsonl(dataset.QUESTIONS, questions(60))
    write_jsonl(dataset.CALIBRATION, calibration())
    fake_draft.reply = llm.Draft(found=True, text="A [2] and B [4].")
    return SimpleNamespace(embed=fake_embed, draft=fake_draft, judge=fake_judge)


def test_a_full_run_writes_every_field_to_the_results_dir(ev):
    path = evaluate()
    assert path.parent == dataset.RESULTS_DIR and not dataset.SCRATCH_DIR.exists()
    assert re.fullmatch(rf"\d{{8}}T\d{{6}}Z-vector-{SHA[:8]}\.json", path.name)
    raw = path.read_bytes()
    assert raw.startswith(b'{\n  "schema": 1,\n') and raw.endswith(b"}\n") and b"\r" not in raw
    assert "café".encode() in raw  # UTF-8, not \u escapes
    result = json.loads(raw)
    assert list(result) == RESULT_KEYS
    assert run.result_problems(result) == []
    assert (result["schema"], result["git_sha"], result["mode"], result["destination"]) == (1, SHA, "vector", "results")
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", result["created_at"])
    assert path.name.startswith(result["created_at"].replace("-", "").replace(":", ""))
    assert result["settings"] == {
        "embedding_model": settings.embedding_model(), "answer_model": settings.answer_model(), "judge_model": settings.judge_model(),
        "chunk_tokens": chunking.CHUNK_TOKENS, "chunk_overlap": chunking.CHUNK_OVERLAP, "k": 5, "search_k": 10,
        "openai_base_url_host": "0.0.0.0",
    }
    the_manifest = dataset.read_manifest(dataset.MANIFEST)
    assert result["corpus_hash"] == dataset.corpus_hash(the_manifest)
    assert result["questions_hash"] == dataset.text_hash(dataset.QUESTIONS)
    assert result["calibration_hash"] == dataset.text_hash(dataset.CALIBRATION)
    assert result["workspace"] == {"name": run.workspace_name(the_manifest), "reused": False}
    assert result["notes"] == []
    assert result["counts"] == {"questions": 60, "answerable": 45, "unanswerable": 15, "refused": 0, "judged": 60,
                                "judge_errors": 0, "calibration_rows": 30, "calibration_judge_errors": 0}
    assert None not in result["metrics"].values() and None not in result["latency_ms"].values()
    assert (result["metrics"]["faithfulness"], result["metrics"]["judge_agreement"]) == (1.0, 20 / 30)
    assert result["judge_confusion"] == {"human_faithful": {"judge_faithful": 20, "judge_unfaithful": 0},
                                         "human_unfaithful": {"judge_faithful": 10, "judge_unfaithful": 0}}
    assert result["usage"] == {"embedding_tokens": 0, "answer_input_tokens": 0, "answer_output_tokens": 0,
                               "judge_input_tokens": 0, "judge_output_tokens": 0}
    # The calibration rows reach the judge after the 60 answers, each with its own question, answer and passages.
    assert ev.judge.calls[60:] == [(c["question"], c["answer"], c["passages"]) for c in calibration()]

    assert [row["id"] for row in result["questions"]] == [q["id"] for q in questions(60)]
    row = next(r for r in result["questions"] if r["question"] == "What is the code word for topic 6?")
    assert list(row) == ["id", "question", "answerable", "sources", "search_ms", "hits", "answer", "judge"]
    assert isinstance(row["search_ms"], float) and row["search_ms"] >= 0
    hits = row["hits"]
    assert [h["rank"] for h in hits] == list(range(1, 11))
    assert list(hits[0]) == ["rank", "chunk_id", "file", "heading_path", "page", "score", "relevant"]
    assert all(uuid.UUID(h["chunk_id"]) for h in hits)
    assert (hits[0]["file"], hits[0]["heading_path"], hits[0]["page"], hits[0]["relevant"]) == (MD, ["Guide", "Topic 6"], None, [0])
    assert all(h["relevant"] == [] for h in hits[1:])
    answer = row["answer"]
    assert list(answer) == ["found", "text", "reason", "citations"]
    assert (answer["found"], answer["text"], answer["reason"]) == (True, "A [2] and B [4].", None)
    assert [c["n"] for c in answer["citations"]] == [2, 4]
    cited = answer["citations"][0]
    assert list(cited) == ["n", "chunk_id", "file", "heading_path", "page", "source", "text", "relevant"]
    assert cited["chunk_id"] == hits[1]["chunk_id"] and cited["relevant"] == []
    assert cited["source"] == f"{MD} > {' > '.join(hits[1]['heading_path'])}" and cited["text"].startswith("The code word")
    assert row["judge"] == {"grade": "faithful", "rationale": "Every claim is supported.", "error": None}

    page_row = next(r for r in result["questions"] if r["sources"] == [{"file": PDF, "page": 1}])
    page_hit = next(h for h in page_row["hits"] if h["file"] == PDF and h["page"] == 1)
    assert page_hit["heading_path"] == [] and page_hit["relevant"] == [0]


def test_the_answer_gets_the_first_5_of_the_10_hits(ev):
    [row] = load(evaluate(limit=1))["questions"]
    assert len(row["hits"]) == 10
    assert [str(h.chunk_id) for h in ev.draft.hits[0]] == [h["chunk_id"] for h in row["hits"][:5]]


def test_the_judge_gets_only_the_cited_passages_under_their_numbers(ev):
    evaluate(limit=1)
    hits = ev.draft.hits[0]
    [(question, answer, passages)] = ev.judge.calls
    assert (question, answer) == (questions(1)[0]["question"], "A [2] and B [4].")
    assert passages == [{"n": n, "source": llm.source_label(hits[n - 1]), "text": hits[n - 1].text} for n in (2, 4)]


def test_usage_counts_this_run_only(ev, monkeypatch):
    llm.USAGE.update(embedding_input=7, judge_input=999)  # stale counts from earlier work in the process
    wrap(monkeypatch, "embed", lambda texts: llm.USAGE.update(embedding_input=len(texts)))
    wrap(monkeypatch, "draft_answer", lambda *args: llm.USAGE.update(answer_input=100, answer_output=10))
    wrap(monkeypatch, "judge", lambda *args: llm.USAGE.update(judge_input=50, judge_output=5, responses_without_usage=1))
    result = load(evaluate(limit=3))
    assert len(ev.embed) == CHUNKS + 3
    assert result["usage"] == {"embedding_tokens": CHUNKS + 3, "answer_input_tokens": 300, "answer_output_tokens": 30,
                               "judge_input_tokens": 150, "judge_output_tokens": 15}
    assert any(note.startswith("usage: 3 OpenAI responses") for note in result["notes"]), result["notes"]


def test_a_second_run_reuses_the_workspace_and_embeds_no_chunk(ev):
    the_manifest = dataset.read_manifest(dataset.MANIFEST)
    name, corpus = run.workspace_name(the_manifest), run.load_corpus(the_manifest)
    assert corpus == CORPUS
    assert asyncio.run(run.workspace_status(name, corpus)) == (None, False)
    first = load(evaluate(limit=2))
    assert first["workspace"] == {"name": name, "reused": False} and len(ev.embed) == CHUNKS + 2
    ev.embed.clear()
    second = load(evaluate(limit=2))
    assert second["workspace"] == {"name": name, "reused": True}
    assert ev.embed == [q["question"] for q in questions(2)]  # the questions only, no chunk text
    assert sql("select count(*) from loreos.workspaces where name = :n", n=name) == [(1,)]
    workspace_id, reused = asyncio.run(run.workspace_status(name, corpus))
    assert reused is True
    sql("delete from loreos.documents where workspace_id = :w and filename = :f", w=workspace_id, f=PDF)
    assert asyncio.run(run.workspace_status(name, corpus)) == (workspace_id, False)


@pytest.mark.parametrize(
    "change",
    [
        lambda mp, m: mp.setattr(chunking, "CHUNK_TOKENS", chunking.CHUNK_TOKENS + 1),
        lambda mp, m: mp.setattr(chunking, "CHUNK_OVERLAP", chunking.CHUNK_OVERLAP + 1),
        lambda mp, m: mp.setenv("OPENAI_BASE_URL", "http://127.0.0.1:9/v1"),
        lambda mp, m: mp.delenv("OPENAI_BASE_URL"),
        lambda mp, m: mp.setenv("EMBEDDING_MODEL", "text-embedding-3-large"),
        lambda mp, m: m["files"][0].update(sha256="0" * 64),
        lambda mp, m: mp.setattr(run, "KEYED_SOURCES", run.KEYED_SOURCES[:-1]),
        lambda mp, m: mp.setattr(run, "KEYED_FUNCTIONS", run.KEYED_FUNCTIONS[:-1]),
        lambda mp, m: mp.setattr(run, "KEYED_LIBRARIES", run.KEYED_LIBRARIES[:-1]),
    ],
    ids=["chunk-tokens", "chunk-overlap", "base-url", "no-base-url", "embedding-model", "corpus", "source", "function", "library"],
)
def test_the_workspace_name_changes_with_each_input_that_shapes_the_chunks(monkeypatch, change):
    the_manifest = manifest(CORPUS)
    name = run.workspace_name(the_manifest)
    assert re.fullmatch(r"eval-[0-9a-f]{12}", name) and run.workspace_name(the_manifest) == name
    change(monkeypatch, the_manifest)
    assert run.workspace_name(the_manifest) != name


def test_a_corpus_file_that_fails_ingest_stops_the_run_before_any_answer(ev):
    write_corpus({**CORPUS, "nist/blank.pdf": make_pdf([""])})
    with pytest.raises(RuntimeError, match=r"nist/blank\.pdf: failed after ingest \(parse: ParseError: no extractable text"):
        evaluate()
    assert ev.draft.calls == [] and ev.judge.calls == []
    partial = load(only_scratch_file())
    assert partial["questions"] == [] and partial["notes"][-1].startswith("stopped: RuntimeError: nist/blank.pdf")


def dirty_the_tree_mid_run(ev, monkeypatch):
    tree = SimpleNamespace(clean=True)
    monkeypatch.setattr(run, "tree_clean", lambda: tree.clean)
    wrap(monkeypatch, "draft_answer", lambda *args: setattr(tree, "clean", False))


def move_head_mid_run(ev, monkeypatch):
    head = SimpleNamespace(sha=SHA)
    monkeypatch.setattr(run, "git_sha", lambda: head.sha)
    wrap(monkeypatch, "draft_answer", lambda *args: setattr(head, "sha", "f" * 40))


def assert_scratch(path, reason):
    result = load(path)
    assert path.parent == dataset.SCRATCH_DIR and not dataset.RESULTS_DIR.exists()
    assert result["destination"] == "scratch" and run.result_problems(result)
    assert any(note.startswith(reason) for note in result["notes"]), result["notes"]


@pytest.mark.parametrize("n", [59, 101])
def test_a_set_outside_60_to_100_questions_goes_to_scratch(ev, n):
    write_jsonl(dataset.QUESTIONS, questions(n))
    assert_scratch(evaluate(), f"scratch: the run covered {n} questions; a committed result covers 60 to 100")


# case: (setup, limit, a fragment of the note naming the reason)
DESTINATION_CASES = {
    "control": (lambda ev, mp: None, None, None),
    "limit": (lambda ev, mp: None, 4, "scratch: --limit 4 was given"),
    "no-calibration-file": (lambda ev, mp: dataset.CALIBRATION.unlink(), None, "scratch: the judge graded 0 of 0 calibration rows"),
    "judge-always-fails": (lambda ev, mp: setattr(ev.judge, "reply", llm.VerdictError("refused")), None, "scratch: faithfulness is null"),
    "one-answer-verdict-fails": (
        lambda ev, mp: wrap(mp, "judge", raise_on(questions(4, unanswerable=1)[2]["question"], llm.VerdictError("refused"))),
        None,
        "scratch: the judge gave no verdict on 1 of 4 answers",
    ),
    "one-calibration-verdict-fails": (
        lambda ev, mp: wrap(mp, "judge", raise_on("Calibration question 7?", llm.VerdictError("refused"))),
        None,
        "scratch: the judge graded 29 of 30 calibration rows",
    ),
    "tree-dirtied-mid-run": (dirty_the_tree_mid_run, None, "scratch: the git tree is not clean"),
    "head-moved-mid-run": (move_head_mid_run, None, f"scratch: HEAD moved from {SHA[:8]} to ffffffff"),
}


@pytest.mark.parametrize("case", DESTINATION_CASES)
def test_a_run_that_breaks_a_destination_rule_goes_to_scratch_with_the_reason(ev, monkeypatch, case):
    # A 4-question set with bounds of 4 to 4 keeps each case fast; the bounds are read at call time, and the
    # full run and the 59 and 101 cases use the real ones. The control case shows the small set alone goes to results.
    monkeypatch.setattr(dataset, "MIN_QUESTIONS", 4)
    monkeypatch.setattr(dataset, "MAX_QUESTIONS", 4)
    write_jsonl(dataset.QUESTIONS, questions(4, unanswerable=1))
    setup, limit, reason = DESTINATION_CASES[case]
    setup(ev, monkeypatch)
    path = evaluate(limit)
    if reason is None:
        assert path.parent == dataset.RESULTS_DIR and load(path)["notes"] == []
    else:
        assert_scratch(path, reason)


@pytest.mark.parametrize(
    "error",
    [RuntimeError("gpt returned no structured answer"), openai.LengthFinishReasonError(completion=SimpleNamespace(usage=None))],
    ids=["no-parsed-answer", "length-stop"],
)
def test_an_answer_that_fails_without_an_api_error_is_refused_with_its_error(ev, monkeypatch, error):
    wrap(monkeypatch, "draft_answer", raise_on(questions(1)[0]["question"], error))
    result = load(evaluate(limit=2))
    failed, answered = result["questions"]
    message = f"{type(error).__name__}: {error}"
    assert failed["answer"] == {"found": False, "text": answering.REFUSAL, "reason": "answer_error", "citations": [], "error": message}
    assert failed["judge"] is None and answered["answer"]["found"] is True
    assert result["counts"]["refused"] == 1
    assert any(note.startswith(f"{failed['id']}: ") and message in note for note in result["notes"]), result["notes"]


def test_a_verdict_failure_is_recorded_on_its_row_and_the_run_goes_on(ev, monkeypatch):
    error = llm.VerdictError("gpt-6.1-sol returned no verdict (refusal: 'no')")
    wrap(monkeypatch, "judge", raise_on(questions(1)[0]["question"], error))
    result = load(evaluate(limit=2))
    failed, graded = result["questions"]
    assert failed["judge"] == {"grade": None, "rationale": None, "error": str(error)}
    assert graded["judge"]["grade"] == "faithful"
    assert (result["counts"]["judged"], result["counts"]["judge_errors"]) == (1, 1)
    assert any(note.startswith(f"{failed['id']}: ") and str(error) in note for note in result["notes"]), result["notes"]


def wrapped(error: Exception, cause: Exception) -> Exception:
    """An error raised `from` cause, as llm.draft_answer wraps a BadRequestError in a RuntimeError."""
    error.__cause__ = cause
    return error


@pytest.mark.parametrize(
    "where, error",
    [
        ("draft_answer", openai.APIConnectionError(request=REQUEST)),
        ("draft_answer", wrapped(RuntimeError("gpt rejected the answer request"), openai.BadRequestError(
            "unsupported parameter", response=httpx2.Response(400, request=REQUEST), body=None))),
        ("judge", openai.APIConnectionError(request=REQUEST)),
        ("judge", KeyboardInterrupt()),
        ("draft_answer", asyncio.CancelledError()),
    ],
    ids=["api-error-answering", "wrapped-api-error-answering", "api-error-judging", "ctrl-c", "cancelled"],
)
def test_a_stop_mid_loop_writes_the_completed_rows_to_scratch_and_re_raises(ev, monkeypatch, capsys, where, error):
    wrap(monkeypatch, where, raise_on(questions(3)[2]["question"], error))
    with pytest.raises(type(error)) as caught:
        evaluate()
    assert caught.value is error
    path = only_scratch_file()
    assert str(path) in capsys.readouterr().err and not dataset.RESULTS_DIR.exists()
    partial = load(path)
    assert partial["destination"] == "scratch" and list(partial) == RESULT_KEYS
    assert [row["id"] for row in partial["questions"]] == [q["id"] for q in questions(2)]
    assert partial["counts"]["questions"] == 2
    assert partial["notes"][-1] == f"stopped: {type(error).__name__}: {error}"


def test_the_preflight_notes_and_the_api_host_reach_the_result(ev):
    result = load(evaluate(limit=1, preflight_notes=["models: listing models returned 404; the model names are unverified"]))
    assert result["notes"][0] == "preflight: models: listing models returned 404; the model names are unverified"
    assert result["settings"]["openai_base_url_host"] == "0.0.0.0"  # conftest's base URL; the host only, never the URL


def test_only_the_vector_mode_runs():
    with pytest.raises(ValueError, match="'hybrid'"):
        asyncio.run(run.evaluate("hybrid", None, SHA, []))


def test_every_committed_result_passes_the_committed_result_check():
    files = sorted(dataset.RESULTS_DIR.glob("*.json"))
    problems = [f"{f.name}: {p}" for f in files for p in run.result_problems(json.loads(f.read_text(encoding="utf-8")))]
    assert problems == [], f"{len(problems)} problems in {len(files)} committed result files"
    print(f"{len(files)} committed result files checked")


def test_the_committed_result_check_refuses_a_scratch_or_ungraded_result():
    good = {"schema": 1, "destination": "results", "metrics": {"judge_agreement": 0.9}}
    assert run.result_problems(good) == []
    [scratch] = run.result_problems({**good, "destination": "scratch"})
    assert "destination is 'scratch'" in scratch
    [ungraded] = run.result_problems({**good, "metrics": {"judge_agreement": None}})
    assert "judge agreement is null" in ungraded
    [schema] = run.result_problems({**good, "schema": 2})
    assert "schema is 2" in schema


def test_the_git_helpers_read_the_repo_root(tmp_path, monkeypatch):
    assert re.fullmatch(r"[0-9a-f]{40}", run.git_sha())
    monkeypatch.setattr(dataset, "ROOT", tmp_path)
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    assert run.tree_clean() is True
    (tmp_path / ".git" / "info" / "exclude").write_text("ignored.txt\n")
    (tmp_path / "ignored.txt").write_text("ignored files do not count")
    assert run.tree_clean() is True
    subprocess.run(["git", "config", "status.showUntrackedFiles", "no"], cwd=tmp_path, check=True)
    (tmp_path / "new.txt").write_text("untracked files do, whatever the repo's git config says")
    assert run.tree_clean() is False
    with pytest.raises(RuntimeError, match="git rev-parse HEAD failed"):
        run.git_sha()  # no commit yet
