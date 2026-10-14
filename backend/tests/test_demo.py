"""paid:demo-load (loreos.demo) against testdb, with fake embeddings and a fake model list over a tiny corpus.

Proves: the first run embeds every corpus file into the workspace and the second embeds and adds nothing; every
preflight refusal (an unknown, evaluation or ownerless workspace, a missing or changed corpus file, an unlisted
embedding model, a malformed id) stops before the first embedding with its exit and its fix; a dry run, by flag or
by npm's npm_config_dry_run, embeds nothing; a --workspace-id npm swallowed is refused with the separator form.
Does NOT exercise: real OpenAI (the live demo load is a ledger row), or the UI showing the loaded documents.
"""

import os
import uuid
from types import SimpleNamespace

import pytest

from conftest import make_user, sql
from loreos import demo, llm, settings, smoke
from loreos.evaluation import dataset
from loreos.workspaces import DEFAULT_WORKSPACE_ID
from test_eval_run import CORPUS, MD, write_corpus


class Models:
    """llm.client(): a model list holding the listed ids."""

    def __init__(self, listed):
        self.listed, self.models = listed, self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def list(self):
        return SimpleNamespace(data=[SimpleNamespace(id=model) for model in self.listed])


@pytest.fixture
def corpus(tmp_path, monkeypatch, clean, fake_embed):
    """The dataset paths under tmp_path with the corpus written, smoke's checks passing, and the embedding model listed."""
    for name, relative in [("MANIFEST", "corpus.json"), ("CORPUS_DIR", "corpus")]:
        monkeypatch.setattr(dataset, name, tmp_path / relative)
    write_corpus(CORPUS)

    async def ok(reranker=True):
        assert reranker is False  # the loader never answers, so it never needs the model

    monkeypatch.setattr(smoke, "preflight", ok)
    monkeypatch.setattr(llm, "client", lambda: Models([settings.embedding_model()]))
    for name in [name for name in os.environ if name.lower().startswith("npm_config_")]:
        monkeypatch.delenv(name)
    return fake_embed


@pytest.fixture
def owned(corpus):
    """The default workspace, with an owner."""
    make_user("owner@example.com", "owner")
    return str(DEFAULT_WORKSPACE_ID)


def documents(workspace_id):
    return sql("select filename, status from loreos.documents where workspace_id = :w order by filename", w=workspace_id)


def test_the_first_run_embeds_every_file_and_the_second_nothing(owned, corpus, capsys):
    assert demo.cli(["--workspace-id", owned]) == 0
    assert documents(owned) == [(name, "processed") for name in sorted(CORPUS)]
    first = len(corpus)
    assert first > 0
    assert "plan: 2 files to embed" in capsys.readouterr().out
    assert demo.cli(["--workspace-id", owned]) == 0
    assert len(corpus) == first and len(documents(owned)) == 2
    assert "plan: 0 files to embed, 0 tokens" in capsys.readouterr().out


@pytest.mark.parametrize("argv", [["--dry-run"], []])
def test_a_dry_run_embeds_nothing(owned, corpus, monkeypatch, argv):
    if not argv:
        monkeypatch.setenv("npm_config_dry_run", "true")  # npm run paid:demo-load --dry-run, without the separator
    assert demo.cli(["--workspace-id", owned, *argv]) == 0
    assert corpus == [] and documents(owned) == []


def stops(workspace_id, fragment):
    with pytest.raises(SystemExit) as stopped:
        demo.cli(["--workspace-id", str(workspace_id)])
    assert fragment in str(stopped.value), str(stopped.value)


def test_an_unknown_workspace_stops_before_any_embedding(corpus):
    stops(uuid.uuid4(), "no workspace has the id")
    assert corpus == []


def test_an_evaluation_workspace_stops_even_with_an_owner(corpus):
    eval_id = sql("insert into loreos.workspaces (name) values ('eval-0123456789ab') returning id")[0][0]
    make_user("owner@example.com", "owner", workspace_id=eval_id)
    stops(eval_id, "is an evaluation workspace")
    assert corpus == [] and documents(eval_id) == []


def test_a_workspace_without_an_owner_stops(corpus):
    lonely = sql("insert into loreos.workspaces (name) values ('Lonely') returning id")[0][0]
    make_user("member@example.com", "member", workspace_id=lonely)
    stops(lonely, "has no owner")
    assert corpus == []


def test_a_missing_corpus_file_stops(owned, corpus):
    (dataset.CORPUS_DIR / MD).unlink()
    stops(owned, "run npm run eval:fetch")
    assert corpus == []


def test_a_changed_corpus_file_stops(owned, corpus):
    (dataset.CORPUS_DIR / MD).write_bytes(b"# Guide\n\nEdited.\n")
    stops(owned, "run npm run eval:fetch")
    assert corpus == []


def test_an_unlisted_embedding_model_stops(owned, corpus, monkeypatch):
    monkeypatch.setattr(llm, "client", lambda: Models(["some-other-model"]))
    stops(owned, f"EMBEDDING_MODEL={settings.embedding_model()}")
    assert corpus == []


@pytest.mark.parametrize("argv", [["--workspace-id", "not-a-uuid"], []])
def test_a_malformed_or_missing_id_exits_2_before_the_preflight(corpus, monkeypatch, argv, capsys):
    monkeypatch.setattr(smoke, "preflight", lambda **kw: pytest.fail("the preflight ran"))
    assert demo.cli(argv) == 2
    assert "--workspace-id" in capsys.readouterr().err


def test_a_workspace_id_npm_swallowed_is_refused_with_the_separator_form(corpus, monkeypatch, capsys):
    monkeypatch.setenv("npm_config_workspace_id", "x")
    assert demo.cli([]) == 2
    assert "npm run paid:demo-load -- --workspace-id <id>" in capsys.readouterr().err
