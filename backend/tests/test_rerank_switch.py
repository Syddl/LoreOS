"""The RERANK kill switch and where the reranker model loads, with DEFAULT_MODE set to hybrid_rerank.

Proves: RERANK=off answers through vector search (decision 0010: hybrid alone measured worse than vector), says so
in the ask response, and never loads or runs the reranker or keyword search; with
RERANK=on the api loads the model at startup and refuses to start, naming RERANK=off, when it cannot; the worker
starts without loading it; a RERANK value other than on or off stops the api and the worker.
Does NOT exercise: the real model (tests/test_rerank.py), or a real download failure (the load is faked to fail).
"""

import logging

import pytest

from conftest import W, app_client, sql, word_vector
from loreos import llm, rerank, retrieval, worker
from loreos.retrieval import vector_literal
from loreos.workspaces import DEFAULT_WORKSPACE_ID

MODEL_ERROR = "the reranker model could not load (faked); or set RERANK=off to serve without the reranker"


@pytest.fixture
def rerank_default(monkeypatch):
    monkeypatch.setattr(retrieval, "DEFAULT_MODE", "hybrid_rerank")


@pytest.fixture
def no_model(monkeypatch):
    """rerank.model raises as a failed load does; the list records each attempt."""
    attempts = []

    def fail():
        attempts.append("model")
        raise RuntimeError(MODEL_ERROR)

    monkeypatch.setattr(rerank, "model", fail)
    return attempts


@pytest.fixture
def serve(monkeypatch):
    calls = []

    async def served():
        calls.append("served")

    monkeypatch.setattr(worker, "serve", served)
    return calls


def test_rerank_off_answers_through_vector_search_and_says_so(owner, fake_embed, fake_draft, rerank_default, no_model, monkeypatch):
    monkeypatch.setenv("RERANK", "off")
    monkeypatch.setattr(rerank, "rerank", lambda query, hits: pytest.fail("reranked with RERANK=off"))

    async def no_keyword(*args):
        pytest.fail("keyword search ran with RERANK=off")

    monkeypatch.setattr(retrieval, "keyword_search", no_keyword)
    doc = sql(
        "insert into loreos.documents (workspace_id, filename, kind, sha256, content, status) "
        "values (:w, 'releases.md', 'md', 'x', 'x', 'processed') returning id",
        w=DEFAULT_WORKSPACE_ID,
    )[0][0]
    sql(
        "insert into loreos.chunks (workspace_id, document_id, ordinal, text, token_count, embedding) "
        "values (:w, :d, 0, 'We ship on Tuesdays.', 1, cast(:e as vector))",
        w=DEFAULT_WORKSPACE_ID,
        d=doc,
        e=vector_literal(word_vector("We ship on Tuesdays.")),
    )
    fake_draft.reply = llm.Draft(found=True, text="On Tuesdays [1].")
    body = owner.client.post(f"{W}/ask", json={"question": "When do we ship?"}).json()
    assert (body["found"], body["retrieval_mode"]) == (True, "vector")
    assert no_model == []


def test_the_api_loads_the_model_at_startup_when_it_serves_with_it(db, rerank_default, monkeypatch):
    loads = []
    monkeypatch.setattr(rerank, "model", lambda: loads.append("model"))
    with app_client():
        assert loads == ["model"]


def test_a_model_that_cannot_load_stops_the_api_naming_rerank_off(db, rerank_default, no_model, caplog):
    with caplog.at_level(logging.ERROR), pytest.raises(RuntimeError, match="RERANK=off"):
        with app_client():
            pass
    assert no_model == ["model"]
    assert any(r.levelno == logging.ERROR and "RERANK=off" in r.getMessage() for r in caplog.records)


def test_rerank_off_starts_the_api_without_the_model(db, rerank_default, no_model, monkeypatch):
    monkeypatch.setenv("RERANK", "off")
    with app_client():
        pass
    assert no_model == []


def test_the_worker_starts_without_loading_the_model(db, rerank_default, no_model, serve):
    assert worker.main() == 0
    assert serve == ["served"] and no_model == []


def test_a_rerank_value_other_than_on_or_off_stops_the_api_and_the_worker(db, serve, monkeypatch, capsys):
    monkeypatch.setenv("RERANK", "maybe")
    with pytest.raises(RuntimeError, match="RERANK must be on or off"):
        with app_client():
            pass
    assert worker.main() == 1
    assert serve == [] and "RERANK must be on or off" in capsys.readouterr().err
