"""rerank: the real fastembed cross-encoder, loaded from its cache (the first run downloads 0.08 GB, free).

Proves: the real model orders a relevant passage above an irrelevant one, scoring the heading path with the text;
a model that cannot load raises with the corrective action, RERANK=off included; model() loads once per process.
Does NOT exercise: ranking quality on the corpus (the evaluation's hybrid_rerank run), latency on the deploy host.
"""

import uuid

import pytest

from loreos import rerank
from loreos.retrieval import Hit


def hit(text, heading_path=()):
    return Hit(uuid.uuid4(), uuid.uuid4(), "handbook.md", list(heading_path), None, text, 0.0)


@pytest.fixture(autouse=True)
def fresh_model():
    """model() is cached per process; a faked failure must not leak into, or be hidden by, another test."""
    rerank.model.cache_clear()
    yield
    rerank.model.cache_clear()


def test_the_real_model_ranks_the_relevant_passage_first():
    cafeteria = hit("The cafeteria opens at noon on weekdays.")
    deploys = hit("Deploys happen on Tuesdays after the release review.")
    ranked = rerank.rerank("When do deploys happen?", [cafeteria, deploys])
    assert ranked == [deploys, cafeteria]
    assert ranked[0].score > ranked[1].score


def test_the_heading_path_is_scored_with_the_text():
    # The text alone says nothing about holidays; only its heading does.
    under_heading = hit("Ask your manager first.", ["Leave", "Public holidays"])
    unrelated = hit("Ask your manager first.", ["Expenses", "Travel"])
    ranked = rerank.rerank("How do I take a public holiday off?", [unrelated, under_heading])
    assert ranked[0] is under_heading


def test_no_hits_loads_nothing(monkeypatch):
    monkeypatch.setattr(rerank, "model", lambda: pytest.fail("model() loaded for no hits"))
    assert rerank.rerank("anything", []) == []


def test_a_model_that_cannot_load_names_the_fixes(monkeypatch):
    def refuse(name):
        raise OSError("connection refused")

    monkeypatch.setattr("fastembed.rerank.cross_encoder.TextCrossEncoder", refuse)
    with pytest.raises(RuntimeError) as raised:
        rerank.model()
    message = str(raised.value)
    assert rerank.RERANK_MODEL in message and "connection refused" in message
    assert "network" in message and "deleting" in message and "RERANK=off" in message


@pytest.mark.parametrize(
    "target, error",
    [
        ("fastembed.common.utils.define_cache_dir", PermissionError("cache directory is read-only")),
        ("fastembed.rerank.cross_encoder.TextCrossEncoder", ImportError("DLL load failed while importing onnxruntime")),
    ],
)
def test_any_load_failure_becomes_the_message_with_the_fixes(monkeypatch, target, error):
    """The api, smoke and the evaluation catch RuntimeError: anything else would stop them with a bare traceback."""

    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(target, fail)
    with pytest.raises(RuntimeError, match="RERANK=off") as raised:
        rerank.model()
    assert str(error) in str(raised.value)


def test_the_model_loads_once_per_process():
    assert rerank.model() is rerank.model()
