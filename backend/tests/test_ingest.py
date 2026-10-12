import asyncio
import time

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from conftest import sql, word_vector
from loreos import fetch_url, ingest, llm, parsing
from loreos.db import engine, workspace_session
from loreos.workspaces import DEFAULT_WORKSPACE_ID

GUIDE = b"# Guide\n\n## Setup\n\nInstall it with one command.\n\n## Use\n\nRun it daily.\n"
PAGE = b"<html><body><h1>Guide</h1><h2>Setup</h2><p>Install it.</p><h2>Use</h2><p>Run it daily.</p></body></html>"
URL = "https://example.com/guide"
LOCK_ROW = text("select 1 from loreos.documents where id = :d for update nowait")


def run(coro_fn):
    async def go():
        async with workspace_session(DEFAULT_WORKSPACE_ID) as session:
            return await coro_fn(session)

    return asyncio.run(go())


def upload(name="guide.md", data=GUIDE):
    return run(lambda s: ingest.ingest(s, DEFAULT_WORKSPACE_ID, name, data))


def enqueue(name="guide.md", data=GUIDE):
    return run(lambda s: ingest.enqueue(s, DEFAULT_WORKSPACE_ID, name, data))


def enqueue_url(url=URL):
    return run(lambda s: ingest.enqueue_url(s, DEFAULT_WORKSPACE_ID, url))


def stored_chunks(document_id):
    return sql("select ordinal, text, heading_path from loreos.chunks where document_id = :d order by ordinal", d=document_id)


def queue_state(document_id):
    return sql("select status, attempts, error, next_attempt_at, locked_until from loreos.documents where id = :d", d=document_id)


def whole_row(document_id):
    return sql("select * from loreos.documents where id = :d", d=document_id)


def sqlstate(error: DBAPIError) -> str:
    return error.orig.sqlstate


def stage_error_in_a_committed_session(document_id):
    """run_stages' StageError, caught inside the session so the session commits whatever it wrote."""

    async def go(session):
        with pytest.raises(ingest.StageError) as caught:
            await ingest.run_stages(session, DEFAULT_WORKSPACE_ID, document_id)
        return caught.value

    return run(go)


def test_enqueue_stores_a_pending_document_and_embeds_nothing(clean, fake_embed):
    doc = enqueue()
    assert (doc.filename, doc.kind, doc.status, doc.attempts, doc.chunk_count) == ("guide.md", "md", "pending", 0, 0)
    assert sql("select content from loreos.documents where id = :d", d=doc.id) == [(GUIDE,)]
    assert fake_embed == []


def test_enqueue_checks_the_type_before_storing(clean):
    with pytest.raises(parsing.UnsupportedType):
        enqueue("slides.pptx", b"PK\x03\x04")
    assert sql("select count(*) from loreos.documents") == [(0,)]


def test_enqueue_returns_a_duplicate_that_has_not_failed_unchanged(clean, fake_embed):
    processed = upload()
    pending = enqueue("other.md", b"Other text.")
    calls = len(fake_embed)
    assert enqueue("renamed.md") == processed
    assert enqueue("other-again.md", b"Other text.") == pending
    assert len(fake_embed) == calls


def test_enqueue_requeues_a_failed_duplicate_with_attempts_reset(clean, fake_embed):
    failed = upload("empty.md", b"  \n")
    assert (failed.status, failed.attempts) == ("failed", 1)
    sql("update loreos.documents set next_attempt_at = now(), locked_until = now() where id = :d", d=failed.id)
    assert enqueue("empty.md", b"  \n").id == failed.id
    assert queue_state(failed.id) == [("pending", 0, None, None, None)]


def test_the_same_url_twice_is_one_row_queued_again(clean):
    first = enqueue_url("HTTPS://Example.COM:443/guide#intro")
    assert (first.filename, first.kind, first.status) == (URL, "url", "pending")
    assert sql("select source_url, content, sha256 from loreos.documents where id = :d", d=first.id) == [
        (URL, None, ingest.sha256(URL.encode()))
    ]
    sql(
        "update loreos.documents set status = 'processed', attempts = 2, error = 'old', next_attempt_at = now(), "
        "locked_until = now() where id = :d",
        d=first.id,
    )
    assert enqueue_url(URL).id == first.id
    assert queue_state(first.id) == [("pending", 0, None, None, None)]
    assert sql("select count(*) from loreos.documents") == [(1,)]


def test_a_url_that_is_not_http_is_refused_and_stores_nothing(clean):
    with pytest.raises(fetch_url.Refused):
        enqueue_url("ftp://example.com/guide.txt")
    assert sql("select count(*) from loreos.documents") == [(0,)]


def test_a_url_document_is_fetched_stored_and_parsed_as_the_fetched_kind(clean, fake_embed, monkeypatch):
    fetched = []

    async def fetch(url):
        fetched.append(url)
        return fetch_url.Fetched(PAGE, "html", url)

    monkeypatch.setattr(fetch_url, "fetch", fetch)
    doc = enqueue_url()
    sql("update loreos.documents set error = 'old', next_attempt_at = now(), locked_until = now() where id = :d", d=doc.id)
    assert run(lambda s: ingest.run_stages(s, DEFAULT_WORKSPACE_ID, doc.id)) == 2
    assert fetched == [URL]
    assert stored_chunks(doc.id) == [(0, "Install it.", ["Guide", "Setup"]), (1, "Run it daily.", ["Guide", "Use"])]
    assert queue_state(doc.id) == [("processed", 0, None, None, None)]
    assert sql("select content, processed_at is not null from loreos.documents where id = :d", d=doc.id) == [(PAGE, True)]


def test_a_parse_failure_raises_stage_error_and_writes_nothing(clean, fake_embed):
    doc = upload()
    sql("update loreos.documents set content = :c where id = :d", c=b"  \n", d=doc.id)
    row, chunks, calls = whole_row(doc.id), stored_chunks(doc.id), len(fake_embed)
    error = stage_error_in_a_committed_session(doc.id)
    assert error.stage == "parse" and isinstance(error.__cause__, parsing.ParseError)
    assert whole_row(doc.id) == row and stored_chunks(doc.id) == chunks
    assert len(fake_embed) == calls


def test_run_stages_holds_the_row_lock_while_it_embeds(clean, monkeypatch):
    doc = enqueue()
    seen = []

    async def embed(texts):
        async with engine().connect() as other:
            try:
                await other.execute(LOCK_ROW, {"d": doc.id})
                seen.append("locked")
            except DBAPIError as e:
                seen.append(sqlstate(e))
        return [word_vector(t) for t in texts]

    monkeypatch.setattr(llm, "embed", embed)
    run(lambda s: ingest.run_stages(s, DEFAULT_WORKSPACE_ID, doc.id))
    assert seen == ["55P03"]


def test_requeueing_a_url_while_its_row_is_locked_times_out_in_about_two_seconds(clean):
    doc = enqueue_url()

    async def go():
        async with engine().begin() as holder:
            await holder.execute(LOCK_ROW, {"d": doc.id})
            started = time.monotonic()
            with pytest.raises(DBAPIError) as caught:
                async with workspace_session(DEFAULT_WORKSPACE_ID) as session:
                    await ingest.enqueue_url(session, DEFAULT_WORKSPACE_ID, URL)
            return sqlstate(caught.value), time.monotonic() - started

    state, elapsed = asyncio.run(asyncio.wait_for(go(), 10))
    assert state == "55P03" and 1.5 < elapsed < 5


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
    assert sql("select attempts, status from loreos.documents where id = :d", d=doc.id) == [(0, "processed")]


def test_a_failed_rerun_of_a_processed_document_leaves_no_stale_chunks(clean, fake_embed, monkeypatch):
    """Search does not filter by status, so a failed document must not keep its old chunks."""
    doc = upload()

    async def embed_fails(texts):
        raise ConnectionError("upstream timed out")

    monkeypatch.setattr(llm, "embed", embed_fails)
    run(lambda s: ingest.process(s, DEFAULT_WORKSPACE_ID, doc.id))
    assert sql("select status, attempts from loreos.documents where id = :d", d=doc.id) == [("failed", 1)]
    assert stored_chunks(doc.id) == []


def test_a_store_failure_after_a_partial_insert_leaves_no_chunks(clean, monkeypatch):
    async def second_vector_has_the_wrong_size(texts):
        return [word_vector(t) if i == 0 else [1.0, 2.0, 3.0] for i, t in enumerate(texts)]

    monkeypatch.setattr(llm, "embed", second_vector_has_the_wrong_size)
    doc = upload()
    assert doc.status == "failed" and doc.chunk_count == 0
    assert doc.error.startswith("store: ")
    assert stored_chunks(doc.id) == []


@pytest.mark.parametrize(
    "configured_key, leak",
    [
        ("sk-test-not-a-real-key", "Incorrect API key provided: sk-proj-abcdef123456XYZ"),
        ("sk-test-not-a-real-key", "bad key sk-test-not-a-real-key"),
        ("gw_live_abcdef123456", "gateway refused key gw_live_abcdef123456"),  # a compatible server's key, no sk- prefix
    ],
)
def test_keys_never_reach_the_stored_error(clean, monkeypatch, configured_key, leak):
    monkeypatch.setenv("OPENAI_API_KEY", configured_key)

    async def embed_fails(texts):
        raise RuntimeError(leak)

    monkeypatch.setattr(llm, "embed", embed_fails)
    doc = upload()
    assert doc.status == "failed" and doc.error.startswith("embed: RuntimeError: ")
    assert "abcdef123456" not in doc.error and "not-a-real-key" not in doc.error
