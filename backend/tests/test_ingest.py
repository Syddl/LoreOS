import asyncio

import pytest

from conftest import sql, word_vector
from loreos import ingest, llm
from loreos.db import workspace_session
from loreos.workspaces import DEFAULT_WORKSPACE_ID

GUIDE = b"# Guide\n\n## Setup\n\nInstall it with one command.\n\n## Use\n\nRun it daily.\n"


def run(coro_fn):
    async def go():
        async with workspace_session(DEFAULT_WORKSPACE_ID) as session:
            return await coro_fn(session)

    return asyncio.run(go())


def upload(name="guide.md", data=GUIDE):
    return run(lambda s: ingest.ingest(s, DEFAULT_WORKSPACE_ID, name, data))


def stored_chunks(document_id):
    return sql("select ordinal, text, heading_path from loreos.chunks where document_id = :d order by ordinal", d=document_id)


def test_embedding_input_carries_the_heading_path_and_stored_text_does_not(clean, fake_embed):
    doc = upload()
    assert doc.status == "processed" and doc.chunk_count == 2
    assert fake_embed == ["Guide > Setup\n\nInstall it with one command.", "Guide > Use\n\nRun it daily."]
    assert stored_chunks(doc.id) == [
        (0, "Install it with one command.", ["Guide", "Setup"]),
        (1, "Run it daily.", ["Guide", "Use"]),
    ]


def test_processing_again_replaces_the_chunks(clean, fake_embed):
    doc = upload()
    before = stored_chunks(doc.id)
    run(lambda s: ingest.process(s, DEFAULT_WORKSPACE_ID, doc.id))
    assert stored_chunks(doc.id) == before
    assert sql("select attempts, status from loreos.documents where id = :d", d=doc.id) == [(2, "processed")]


def test_a_store_failure_after_a_partial_insert_leaves_no_chunks(clean, monkeypatch):
    async def second_vector_has_the_wrong_size(texts):
        return [word_vector(t) if i == 0 else [1.0, 2.0, 3.0] for i, t in enumerate(texts)]

    monkeypatch.setattr(llm, "embed", second_vector_has_the_wrong_size)
    doc = upload()
    assert doc.status == "failed" and doc.chunk_count == 0
    assert doc.error.startswith("store: ")
    assert stored_chunks(doc.id) == []


@pytest.mark.parametrize("leak", ["Incorrect API key provided: sk-proj-abcdef123456XYZ", "bad key sk-test-not-a-real-key"])
def test_keys_never_reach_the_stored_error(clean, monkeypatch, leak):
    async def embed_fails(texts):
        raise RuntimeError(leak)

    monkeypatch.setattr(llm, "embed", embed_fails)
    doc = upload()
    assert doc.status == "failed" and doc.error.startswith("embed: RuntimeError: ")
    assert "abcdef123456" not in doc.error and "not-a-real-key" not in doc.error
