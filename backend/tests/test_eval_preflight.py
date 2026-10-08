"""The paid:eval preflight over a tiny corpus in tmp_path: each check stops in spec order, before any paid call.

llm.embed, llm.draft_answer and llm.judge are replaced by traps that fail the test if called, in every case.
"""

import asyncio
import hashlib
import json
import re
from types import SimpleNamespace

import httpx2  # the SDK's own HTTP module, to build the request its errors carry
import openai
import pytest

from loreos import chunking, llm, settings, smoke
from loreos.evaluation import dataset, preflight, run
from pdf import make_pdf

SHA = "0123456789abcdef0123456789abcdef01234567"
MD = "handbook/guide.md"
PDF = "nist/report.pdf"
GUIDE = "# Guide\n\n" + "".join(f"## Topic {i}\n\nThe code word for topic {i} is word{i}.\n\n" for i in range(1, 5))
CORPUS = {MD: GUIDE.encode(), PDF: make_pdf(["Page one sets the alpha rule.", "Page two sets the beta rule."])}
REQUEST = httpx2.Request("GET", "https://api.openai.com/v1/models")


def entry(file: str, data: bytes) -> dict:
    return {"file": file, "url": f"https://example.com/{file}", "sha256": hashlib.sha256(data).hexdigest()}


def manifest(files: dict) -> dict:
    return {
        "sources": [
            {"name": "Guide", "home": "https://example.com", "license": "CC BY-SA 4.0", "attribution": "Example", "files": "handbook/"},
            {"name": "NIST", "home": "https://example.gov", "license": "Public domain", "attribution": "NIST", "files": "nist/"},
        ],
        "files": [entry(f, d) for f, d in files.items()],
    }


def questions() -> list[dict]:
    """3 answerable rows (the third a broad label over 4 chunks), then 10 unanswerable ones."""
    return [
        {"id": "a1", "question": "What is the code word for topic 1?", "answerable": True,
         "sources": [{"file": MD, "heading_path": ["Guide", "Topic 1"]}]},
        {"id": "a2", "question": "Which rule does page two set?", "answerable": True, "sources": [{"file": PDF, "page": 2}]},
        {"id": "a3", "question": "What are all the code words?", "answerable": True, "sources": [{"file": MD, "heading_path": ["Guide"]}]},
    ] + [
        {"id": f"u{i:02}", "question": f"What does the café on floor {i} serve?", "answerable": False, "sources": []}
        for i in range(1, 11)
    ]


def calibration() -> list[dict]:
    return [
        {"id": f"c{i:02}", "question": f"Calibration question {i}?", "answer": f"Calibration answer {i} [1].",
         "passages": [{"n": 1, "source": f"{MD} > Guide > Topic 1", "text": f"Passage {i}."}], "human": "faithful"}
        for i in range(1, 31)
    ]


def write_jsonl(path, rows):
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


class FakeClient:
    """llm.client(): an async context manager whose models.list() returns the state's ids, or raises its error."""

    def __init__(self, state):
        self.state = state
        self.models = self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def list(self):
        self.state.calls.append("models")
        if self.state.models_error:
            raise self.state.models_error
        return SimpleNamespace(data=[SimpleNamespace(id=model) for model in self.state.models])


def trap(state, name):
    async def paid_call(*args):
        state.paid.append(name)
        raise AssertionError(f"llm.{name} was called during the preflight")

    return paid_call


@pytest.fixture
def pf(tmp_path, monkeypatch):
    """The dataset paths under tmp_path, filled from this state by check(); the external checks are recorded in .calls."""
    for name, relative in [("QUESTIONS", "questions.jsonl"), ("CALIBRATION", "judge_calibration.jsonl"),
                           ("MANIFEST", "corpus.json"), ("CORPUS_DIR", "corpus")]:
        monkeypatch.setattr(dataset, name, tmp_path / relative)
    state = SimpleNamespace(
        questions=questions(), calibration=calibration(), files=dict(CORPUS), manifest=manifest(CORPUS),
        models=[settings.embedding_model(), settings.answer_model(), settings.judge_model(), "other-model"],
        models_error=None, smoke_error=None, clean=True, calls=[], paid=[],
    )

    async def smoke_preflight():
        state.calls.append("smoke")
        if state.smoke_error:
            raise state.smoke_error

    def tree_clean():
        state.calls.append("tree")
        return state.clean

    monkeypatch.setattr(smoke, "preflight", smoke_preflight)
    monkeypatch.setattr(llm, "client", lambda: FakeClient(state))
    monkeypatch.setattr(run, "tree_clean", tree_clean)
    monkeypatch.setattr(run, "git_sha", lambda: SHA)
    for name in ("embed", "draft_answer", "judge"):
        monkeypatch.setattr(llm, name, trap(state, name))
    yield state
    assert state.paid == []


def check(state, limit=None) -> tuple[str, list[str]]:
    """Write the state's files (a None list writes nothing), then run the preflight."""
    for file, data in state.files.items():
        path = dataset.CORPUS_DIR / file
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    dataset.MANIFEST.write_text(json.dumps(state.manifest), encoding="utf-8")
    if state.questions is not None:
        write_jsonl(dataset.QUESTIONS, state.questions)
    if state.calibration is not None:
        write_jsonl(dataset.CALIBRATION, state.calibration)
    return asyncio.run(preflight.preflight(limit))


def refused(state, limit=None) -> str:
    with pytest.raises(SystemExit) as caught:
        check(state, limit)
    return str(caught.value)


# In spec order: (step, how to break it, a fragment of its refusal, the external checks made before it stops).
BREAKS = [
    ("set", lambda s, mp: s.questions.append(dict(s.questions[0])), "a1: the id is used by 2 rows", []),
    ("calibration", lambda s, mp: s.calibration[0].update(human=None), "c01: not graded yet", []),
    ("corpus", lambda s, mp: s.files.update({MD: b"# Guide\n\nEdited.\n"}), f"{MD}: sha256 is", []),
    ("labels", lambda s, mp: s.questions[0]["sources"][0].update(heading_path=["Guide", "Topic 1x"]),
     f'a1: {MD}: heading "Guide > Topic 1x" matches no section in outline.txt; closest: "Guide > Topic 1"', []),
    ("database", lambda s, mp: setattr(s, "smoke_error", SystemExit("preflight: the database is at migration a; run npm run db:migrate")),
     "run npm run db:migrate", ["smoke"]),
    ("models", lambda s, mp: mp.setenv("JUDGE_MODEL", "gpt-unlisted"), "JUDGE_MODEL=gpt-unlisted", ["smoke", "models"]),
    ("tree", lambda s, mp: setattr(s, "clean", False), "the git tree is not clean", ["smoke", "models", "tree"]),
]


@pytest.mark.parametrize("first", range(len(BREAKS)), ids=[step for step, *_ in BREAKS])
def test_each_check_refuses_and_the_earliest_failure_wins(pf, monkeypatch, first):
    for _, breaks, _, _ in BREAKS[first:]:  # this step and every later one are broken at once
        breaks(pf, monkeypatch)
    _, _, fragment, calls = BREAKS[first]
    message = refused(pf)
    assert message.startswith("preflight: ") and fragment in message, message
    assert pf.calls == calls


def test_a_missing_set_is_refused_naming_it(pf):
    pf.questions = None
    message = refused(pf)
    assert dataset.QUESTIONS.as_posix() in message and "eval/README.md" in message
    assert pf.calls == []


def test_a_set_that_is_not_json_is_refused_naming_the_line(pf):
    pf.questions = None
    dataset.QUESTIONS.write_text('{"id": "a1"}\n{not json\n', encoding="utf-8")
    assert f"{dataset.QUESTIONS}:2: not valid JSON" in refused(pf)


def test_every_problem_in_the_set_is_listed(pf):
    pf.questions[0]["answerable"] = "yes"
    pf.questions[1]["sources"] = [{"file": PDF}]
    message = refused(pf)
    assert "a1: answerable must be true or false" in message and "a2 source 1 (nist/report.pdf): a PDF source needs page" in message


def test_a_manifest_problem_is_refused(pf):
    pf.manifest["files"][0]["sha256"] = "XYZ"
    assert f"{MD}: sha256 must be 64 lowercase hex characters" in refused(pf)


def test_a_missing_corpus_file_is_refused_with_the_fetch_command(pf):
    del pf.files[PDF]
    assert f"{PDF}: missing from" in (message := refused(pf)) and "npm run eval:fetch" in message


def test_two_corpus_files_with_the_same_bytes_are_refused_naming_both(pf):
    pf.files["handbook/copy.md"] = CORPUS[MD]
    pf.manifest["files"].append(entry("handbook/copy.md", CORPUS[MD]))
    message = refused(pf)
    assert MD in message and "handbook/copy.md" in message and "one document" in message
    assert pf.calls == []


def test_a_corpus_file_that_cannot_be_parsed_is_refused_naming_it(pf):
    pf.files["nist/blank.pdf"] = make_pdf([""])
    pf.manifest["files"].append(entry("nist/blank.pdf", pf.files["nist/blank.pdf"]))
    assert "nist/blank.pdf: cannot be parsed (no extractable text" in refused(pf)


def test_a_model_list_that_cannot_be_reached_is_refused(pf):
    pf.models_error = openai.APIConnectionError(request=REQUEST)
    assert "cannot list the models" in refused(pf)
    assert pf.calls == ["smoke", "models"]


def test_every_unlisted_model_is_named_with_its_variable(pf, monkeypatch):
    monkeypatch.setenv("EMBEDDING_MODEL", "embed-unlisted")
    monkeypatch.setenv("ANSWER_MODEL", "answer-unlisted")
    message = refused(pf)
    assert "EMBEDDING_MODEL=embed-unlisted" in message and "ANSWER_MODEL=answer-unlisted" in message
    assert "JUDGE_MODEL" not in message


def test_a_server_without_a_model_list_goes_on_unverified(pf, clean, capsys):
    pf.models_error = openai.NotFoundError("not found", response=httpx2.Response(404, request=REQUEST), body=None)
    sha, notes = check(pf)
    assert sha == SHA
    assert "listing models returned 404; the model names are unverified" in capsys.readouterr().out
    assert pf.calls == ["smoke", "models", "tree"]
    # the result file records it too (the run puts the preflight's notes in its own), not only the console
    assert notes[0] == "models: listing models returned 404; the model names are unverified"


def test_a_limit_skips_the_tree_check(pf, clean, capsys):
    pf.clean = False
    assert check(pf, limit=2)[0] == SHA
    assert pf.calls == ["smoke", "models"]
    out = capsys.readouterr().out
    assert "plan: 2 of 13 questions (2 answerable, 0 unanswerable)" in out
    assert "judge calls up to 2 (2 answers, 0 calibration rows)" in out


def test_the_plan_counts_every_call_and_warns_about_broad_labels(pf, clean, monkeypatch, capsys):
    monkeypatch.setattr(llm, "EMBED_BATCH", 3)  # the Markdown file's 4 chunks take 2 calls and the PDF's 2 take 1
    sha, notes = check(pf)
    assert sha == SHA
    assert notes == [f'broad label: a3: {MD}: heading "Guide" spans 4 chunks; label a narrower heading if one answers']
    assert pf.calls == ["smoke", "models", "tree"]
    out = capsys.readouterr().out
    name = run.workspace_name(pf.manifest)
    per_call = 5 * chunking.CHUNK_TOKENS + preflight.CALL_ALLOWANCE
    plan = [line for line in out.splitlines() if line.startswith(("plan: ", "warning: "))]
    assert plan[0] == "plan: 13 of 13 questions (3 answerable, 10 unanswerable)"
    assert re.fullmatch(rf"plan: workspace {name} to build; corpus embedding \d+ tokens in 3 embed calls", plan[1])
    assert plan[2:] == [
        "plan: embed calls 16 (3 for the corpus, one per question)",
        "plan: answer calls up to 13; judge calls up to 43 (13 answers, 30 calibration rows)",
        f"plan: input tokens up to about {per_call} per answer or judge call (5 passages of up to {chunking.CHUNK_TOKENS} tokens, "
        f"plus {preflight.CALL_ALLOWANCE}), {per_call * 56} in all; output tokens are not capped",
        f'warning: a3: {MD}: heading "Guide" spans 4 chunks; label a narrower heading if one answers',
    ]


def test_without_a_calibration_file_the_judge_grades_only_the_answers(pf, clean, capsys):
    pf.calibration = None
    check(pf)
    assert "judge calls up to 13 (13 answers, 0 calibration rows)" in capsys.readouterr().out


def test_the_corpus_token_count_is_what_ingest_sends_to_the_embedder(pf, clean, fake_embed, capsys):
    assert check(pf)[0] == SHA
    assert fake_embed == []  # the preflight embedded nothing
    name = run.workspace_name(pf.manifest)
    found = re.search(rf"workspace {name} to build; corpus embedding (\d+) tokens in 2 embed calls", capsys.readouterr().out)
    asyncio.run(run._ingest(name, run.load_corpus(pf.manifest)))  # the run's own ingest, into the workspace the run would use
    assert len(fake_embed) == 6  # 4 Markdown chunks and 2 PDF pages
    assert int(found[1]) == sum(chunking.count_tokens(text) for text in fake_embed)
    check(pf)
    assert f"workspace {name} reused; corpus embedding 0 tokens in 0 embed calls" in capsys.readouterr().out
