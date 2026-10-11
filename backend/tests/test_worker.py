"""The worker: claim, classification, retries with backoff, the lease, fenced writes, release on stop, startup checks.

Every case runs on fake_embed or a raising embed, so nothing here reaches OpenAI.
"""

import asyncio
import logging
from types import SimpleNamespace

import httpx2  # the SDK's own HTTP module, to build the request and response its errors carry
import openai
import pytest
from sqlalchemy import exc as sa_exc
from sqlalchemy import text

from conftest import drain, sql, word_vector
from loreos import fetch_url, ingest, llm, parsing, verify_rls, worker
from loreos.db import engine, workspace_session
from loreos.embeddings import EMBEDDING_DIM
from loreos.workspaces import DEFAULT_WORKSPACE_ID
from pdf import make_pdf

GUIDE = b"# Guide\n\n## Setup\n\nInstall it with one command.\n\n## Use\n\nRun it daily.\n"
REQUEST = httpx2.Request("POST", "https://api.openai.com/v1/embeddings")
URL = "https://example.com/guide"
LEASE_ERROR = "lease: transient: the worker stopped before finishing (lease expired)"
PROBE = text("select current_setting('idle_in_transaction_session_timeout'), current_user, current_setting('app.workspace_id')")


class Killed(BaseException):
    """A crash the worker cannot handle, as when its process is killed."""


class PgError(Exception):
    """Stands in for the driver error SQLAlchemy wraps; only its sqlstate is read."""

    def __init__(self, sqlstate: str) -> None:
        super().__init__(sqlstate)
        self.sqlstate = sqlstate


@pytest.fixture(autouse=True)
def worker_log(caplog):
    caplog.set_level(logging.INFO, logger="loreos.worker")
    return caplog


def enqueue(name="guide.md", data=GUIDE, workspace_id=DEFAULT_WORKSPACE_ID):
    async def go():
        async with workspace_session(workspace_id) as session:
            return await ingest.enqueue(session, workspace_id, name, data)

    return asyncio.run(go())


def processed_then_queued_again():
    """A processed document with its two chunks, back to pending as a re-queue leaves it."""
    doc = enqueue()
    assert drain() == ["processed"]
    sql("update loreos.documents set status = 'pending' where id = :d", d=doc.id)
    return doc.id


def state(document_id):
    return sql("select status, attempts, error from loreos.documents where id = :d", d=document_id)[0]


def lease_and_retry(document_id):
    return sql("select locked_until, next_attempt_at from loreos.documents where id = :d", d=document_id)[0]


def seconds_until_due(document_id) -> float:
    return sql("select extract(epoch from next_attempt_at - now())::float from loreos.documents where id = :d", d=document_id)[0][0]


def chunks(document_id):
    return sql("select ordinal, text, heading_path from loreos.chunks where document_id = :d order by ordinal", d=document_id)


def make_due(document_id):
    sql("update loreos.documents set next_attempt_at = now() where id = :d", d=document_id)


def expire_lease(document_id):
    sql("update loreos.documents set locked_until = now() - interval '1 second' where id = :d", d=document_id)


def embed_raises(monkeypatch, error: BaseException):
    async def embed(texts):
        raise error

    monkeypatch.setattr(llm, "embed", embed)


def status_error(cls, status: int, code: str | None = None):
    return cls("refused", response=httpx2.Response(status, request=REQUEST), body={"code": code} if code else None)


def db_error(cls=sa_exc.ProgrammingError, sqlstate: str = "", invalidated: bool = False):
    return cls("select 1", {}, PgError(sqlstate), connection_invalidated=invalidated)


def logged(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.name == "loreos.worker"]


def test_a_queued_document_is_claimed_processed_and_logged(clean, fake_embed, worker_log):
    doc = enqueue()
    assert drain() == ["processed"]
    assert state(doc.id) == ("processed", 0, None)
    assert lease_and_retry(doc.id) == (None, None)
    assert len(chunks(doc.id)) == 2
    assert logged(worker_log) == [f"worker claimed document={doc.id}", f"worker processed document={doc.id} chunks=2"]
    assert drain() == []


def test_a_transient_failure_retries_after_30_s_then_2_min_then_fails(clean, fake_embed, monkeypatch, worker_log):
    doc = processed_then_queued_again()
    kept = chunks(doc)
    embed_raises(monkeypatch, openai.APITimeoutError(request=REQUEST))
    for attempts, delay in ((1, 30), (2, 120)):
        assert drain() == ["transient"]
        assert state(doc)[:2] == ("pending", attempts)
        assert delay - 5 < seconds_until_due(doc) <= delay
        assert chunks(doc) == kept  # a retry keeps the last good chunks until it replaces them
        make_due(doc)
    assert drain() == ["transient"]
    status, attempts, error = state(doc)
    assert (status, attempts) == ("failed", 3)
    assert error.startswith("embed: transient: APITimeoutError: ")
    assert chunks(doc) == []
    assert lease_and_retry(doc) == (None, None)
    assert f"worker failed document={doc} stage=embed class=transient" in logged(worker_log)


def test_a_permanent_failure_fails_at_once_and_spends_nothing(clean, fake_embed):
    doc = enqueue("scan.pdf", make_pdf(["", ""]))
    assert drain() == ["permanent"]
    assert state(doc.id) == ("failed", 1, "parse: permanent: ParseError: no extractable text (scanned PDF?)")
    assert chunks(doc.id) == []
    assert fake_embed == []


@pytest.mark.parametrize(
    "error",
    [status_error(openai.AuthenticationError, 401), status_error(openai.RateLimitError, 429, "insufficient_quota")],
    ids=["authentication", "insufficient_quota"],
)
def test_a_systemic_failure_leaves_the_document_pending_and_uncounted(clean, monkeypatch, error):
    doc = enqueue()
    embed_raises(monkeypatch, error)
    assert asyncio.run(worker.run_once()) == "systemic"
    status, attempts, stored = state(doc.id)
    assert (status, attempts) == ("pending", 0)
    assert stored.startswith(f"embed: systemic: {type(error).__name__}: ")
    assert worker.SYSTEMIC_PAUSE_S - 5 < seconds_until_due(doc.id) <= worker.SYSTEMIC_PAUSE_S


class Stop(BaseException):
    pass


def test_the_loop_pauses_after_a_systemic_failure_polls_while_idle_and_rides_out_a_database_error(monkeypatch, worker_log):
    results = iter(["systemic", None, "processed", db_error(sa_exc.OperationalError, "08006")])
    sleeps = []

    async def run_once():
        result = next(results)
        if isinstance(result, Exception):
            raise result
        return result

    async def sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) == 3:
            raise Stop

    monkeypatch.setattr(worker, "run_once", run_once)
    monkeypatch.setattr(asyncio, "sleep", sleep)
    with pytest.raises(Stop):
        asyncio.run(worker.serve())
    assert sleeps == [worker.SYSTEMIC_PAUSE_S, worker.POLL_S, worker.POLL_S]
    assert (worker.SYSTEMIC_PAUSE_S, worker.POLL_S) == (300, 2)
    lines = logged(worker_log)
    assert "worker paused class=systemic seconds=300" in lines
    assert any(line.startswith("worker database error: OperationalError") for line in lines)


CLASSES = [
    (parsing.UnsupportedType("slides.pptx"), "permanent"),
    (parsing.ParseError("the DOCX unpacks to over 100 MB"), "permanent"),
    (fetch_url.Refused("ftp"), "permanent"),
    (fetch_url.TooLarge("big"), "permanent"),
    (fetch_url.UnsupportedContent("image/png"), "permanent"),
    (fetch_url.HTTPStatus(404, URL), "permanent"),
    (status_error(openai.BadRequestError, 400, "invalid_value"), "permanent"),
    (status_error(openai.AuthenticationError, 401), "systemic"),
    (status_error(openai.PermissionDeniedError, 403), "systemic"),
    (status_error(openai.NotFoundError, 404), "systemic"),
    (status_error(openai.RateLimitError, 429, "insufficient_quota"), "systemic"),
    (status_error(openai.BadRequestError, 400, "model_not_found"), "systemic"),
    (llm.EmbeddingDimensionError("3 dimensions"), "systemic"),
    (db_error(sqlstate="42501"), "systemic"),
    (db_error(sqlstate="42P01"), "systemic"),
    (db_error(sqlstate="3F000"), "systemic"),
    (status_error(openai.RateLimitError, 429, "rate_limit_exceeded"), "transient"),
    (status_error(openai.InternalServerError, 500), "transient"),
    (openai.APITimeoutError(request=REQUEST), "transient"),
    (openai.APIConnectionError(request=REQUEST), "transient"),
    (fetch_url.HTTPStatus(503, URL), "transient"),
    (TimeoutError(), "transient"),
    (httpx2.ConnectError("refused"), "transient"),
    (OSError("reset"), "transient"),
    (db_error(sa_exc.OperationalError, "08006"), "transient"),
    (db_error(sa_exc.InterfaceError), "transient"),
    (db_error(sa_exc.DBAPIError, "22000", invalidated=True), "transient"),
    (RuntimeError("something new"), "transient"),
]


@pytest.mark.parametrize(
    "error, expected",
    CLASSES,
    ids=[f"{expected}-{type(e).__name__}-{getattr(e, 'code', None) or getattr(e, 'status', None) or ''}" for e, expected in CLASSES],
)
def test_classify(error, expected):
    assert worker.classify(error) == expected


def test_two_concurrent_claims_give_one_job(clean):
    doc = enqueue()

    async def go():
        return await asyncio.gather(worker.claim(), worker.claim())

    claims = asyncio.run(go())
    assert sorted(claim is None for claim in claims) == [False, True]
    assert state(doc.id)[:2] == ("processing", 0)


def test_a_row_being_processed_is_not_claimed_even_after_its_lease_runs_out(clean, monkeypatch):
    monkeypatch.setattr(worker, "LEASE", 0)
    doc = enqueue()
    seen = []

    async def embed(texts):
        async with engine().connect() as other:
            expired = await other.scalar(text("select locked_until <= now() from loreos.documents where id = :d"), {"d": doc.id})
        seen.append((expired, await asyncio.wait_for(worker.claim(), 5)))
        return [word_vector(t) for t in texts]

    monkeypatch.setattr(llm, "embed", embed)
    assert asyncio.run(worker.run_once()) == "processed"
    assert seen == [(True, None)]


def test_an_expired_lease_is_counted_once_then_processed(clean, fake_embed, worker_log):
    doc = enqueue()
    assert asyncio.run(worker.claim()) is not None  # a worker that stopped after its claim
    assert drain() == []  # its lease is still running
    expire_lease(doc.id)
    assert drain() == ["processed"]
    assert state(doc.id) == ("processed", 1, None)
    assert len(chunks(doc.id)) == 2
    assert logged(worker_log).count(f"worker failed document={doc.id} stage=lease class=transient") == 1


def test_a_third_expired_lease_fails_the_document_without_processing(clean, fake_embed):
    doc = processed_then_queued_again()
    calls = len(fake_embed)
    sql("update loreos.documents set status = 'processing', attempts = 2, locked_until = now() - interval '1 second' where id = :d", d=doc)
    assert drain() == ["transient"]
    assert state(doc) == ("failed", 3, LEASE_ERROR)
    assert lease_and_retry(doc) == (None, None)
    assert chunks(doc) == []
    assert len(fake_embed) == calls


def test_a_failed_reprocessing_keeps_the_previous_chunks(clean, fake_embed, monkeypatch):
    doc = processed_then_queued_again()
    before = chunks(doc)

    async def second_vector_has_the_wrong_size(texts):
        return [word_vector(t) if i == 0 else [1.0, 2.0, 3.0] for i, t in enumerate(texts)]

    monkeypatch.setattr(llm, "embed", second_vector_has_the_wrong_size)
    assert drain() == ["transient"]
    status, attempts, error = state(doc)
    assert (status, attempts) == ("pending", 1) and error.startswith("store: transient: ")
    assert chunks(doc) == before


def test_a_worker_killed_midway_is_recovered_after_its_lease_with_exactly_the_expected_chunks(clean, fake_embed, monkeypatch):
    doc = processed_then_queued_again()
    expected, fake = chunks(doc), llm.embed
    embed_raises(monkeypatch, Killed())
    with pytest.raises(Killed):
        asyncio.run(worker.run_once())
    assert state(doc)[:2] == ("processing", 0)
    monkeypatch.setattr(llm, "embed", fake)
    assert drain() == []  # the lease has not run out
    expire_lease(doc)
    assert drain() == ["processed"]
    assert state(doc) == ("processed", 1, None)
    assert chunks(doc) == expected


@pytest.mark.parametrize("stop", [asyncio.CancelledError, KeyboardInterrupt])
def test_a_stopped_worker_releases_its_claim_uncounted(clean, monkeypatch, stop):
    doc = enqueue()
    embed_raises(monkeypatch, stop())
    with pytest.raises(stop):
        asyncio.run(worker.run_once())
    assert state(doc.id) == ("pending", 0, None)
    assert lease_and_retry(doc.id) == (None, None)


def test_a_stale_worker_changes_nothing_on_a_row_claimed_since(clean, worker_log):
    doc = enqueue()
    stale = asyncio.run(worker.claim())
    expire_lease(doc.id)
    fresh = asyncio.run(worker.claim())
    row = sql("select * from loreos.documents where id = :d", d=doc.id)
    asyncio.run(worker.record_failure(stale, "embed", "permanent", RuntimeError("late")))
    asyncio.run(worker.release(stale))
    assert sql("select * from loreos.documents where id = :d", d=doc.id) == row
    assert state(doc.id)[:2] == ("processing", 1)
    assert lease_and_retry(doc.id)[0] == fresh.locked_until
    assert logged(worker_log).count(f"worker lost document={doc.id}: another claim holds it, so nothing was written") == 2


def test_processing_runs_in_the_documents_workspace_as_loreos_app_with_the_idle_timeout(clean, monkeypatch):
    workspace = sql("insert into loreos.workspaces (name) values ('other') returning id")[0][0]
    doc = enqueue(workspace_id=workspace)
    sessions, seen = [], []
    run_stages = ingest.run_stages

    async def spy(session, workspace_id, document_id):
        sessions.append(session)
        return await run_stages(session, workspace_id, document_id)

    async def embed(texts):
        seen.append(tuple((await sessions[0].execute(PROBE)).one()))
        return [word_vector(t) for t in texts]

    monkeypatch.setattr(ingest, "run_stages", spy)
    monkeypatch.setattr(llm, "embed", embed)
    assert asyncio.run(worker.run_once()) == "processed"
    assert seen == [("10min", "loreos_app", str(workspace))]


@pytest.fixture
def serve(monkeypatch):
    calls = []

    async def serve():
        calls.append("served")

    monkeypatch.setattr(worker, "serve", serve)
    return calls


def test_the_worker_starts_when_the_settings_and_grants_hold(db, serve):
    assert worker.main() == 0
    assert serve == ["served"]


def test_a_blank_key_stops_the_worker_at_startup_naming_it(db, serve, monkeypatch, capsys):
    monkeypatch.setenv("OPENAI_API_KEY", " ")
    assert worker.main() == 1
    assert "OPENAI_API_KEY is not set" in capsys.readouterr().err
    assert serve == []


def test_a_verify_rls_problem_stops_the_worker_at_startup_naming_it(db, serve, monkeypatch, capsys):
    async def problems(conn):
        return [verify_rls.CHECKS["login"]]

    monkeypatch.setattr(verify_rls, "problems", problems)
    assert worker.main() == 1
    assert verify_rls.CHECKS["login"] in capsys.readouterr().err
    assert serve == []


def test_embed_stops_after_the_first_batch_of_wrong_size_vectors(monkeypatch):
    calls = []

    async def create(**kwargs):
        calls.append(kwargs["input"])
        data = [SimpleNamespace(index=i, embedding=[0.0] * (EMBEDDING_DIM // 2)) for i, _ in enumerate(kwargs["input"])]
        return SimpleNamespace(data=data, usage=SimpleNamespace(prompt_tokens=1))

    class Client:
        embeddings = SimpleNamespace(create=create)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return None

    monkeypatch.setattr(llm, "client", Client)
    monkeypatch.setattr(llm, "EMBED_BATCH", 2)
    with pytest.raises(llm.EmbeddingDimensionError, match="EMBEDDING_MODEL"):
        asyncio.run(llm.embed(["a", "b", "c"]))
    assert calls == [["a", "b"]]
