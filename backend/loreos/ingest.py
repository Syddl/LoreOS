"""Upload to stored chunks: parse, chunk, embed, store. Owns the document status transitions."""

import hashlib
import logging
import os
import re
import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from loreos import chunking, fetch_url, llm, parsing
from loreos.chunking import Chunk
from loreos.retrieval import vector_literal

log = logging.getLogger("loreos.ingest")

MAX_ERROR_CHARS = 1000
# The longest a request waits on the worker's row lock before giving up; it lasts the caller's whole transaction.
LOCK_TIMEOUT = text("set local lock_timeout = '2s'")
# Back to the queue as if new. The worker may hold the row lock for minutes, hence the lock_timeout on URL re-queues.
REQUEUE = text(
    "update loreos.documents set status = 'pending', attempts = 0, error = null, next_attempt_at = null, "
    "locked_until = null where id = :d and workspace_id = :w"
)
SELECT_DOCUMENTS = """
    select d.id, d.filename, d.kind, d.status, d.error, d.attempts,
           (select count(*) from loreos.chunks c where c.document_id = d.id) as chunk_count,
           d.created_at, d.processed_at
    from loreos.documents d
    where d.workspace_id = :w
"""
INSERT_CHUNK = text(
    """
    insert into loreos.chunks (workspace_id, document_id, ordinal, text, heading_path, page, token_count, embedding)
    values (:w, :d, :ordinal, :text, :heading_path, :page, :token_count, cast(:embedding as vector))
    """
)


@dataclass
class Document:
    id: uuid.UUID
    filename: str
    kind: str
    status: str
    error: str | None
    attempts: int
    chunk_count: int
    created_at: datetime
    processed_at: datetime | None


class StageError(Exception):
    """A processing failure; `stage` is fetch, parse, embed or store, and the failure itself is in __cause__."""

    def __init__(self, stage: str) -> None:
        super().__init__(stage)
        self.stage = stage


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


async def list_documents(session: AsyncConnection, workspace_id: uuid.UUID) -> list[Document]:
    rows = await session.execute(text(SELECT_DOCUMENTS + " order by d.created_at desc"), {"w": workspace_id})
    return [Document(*row) for row in rows]


async def get_document(session: AsyncConnection, workspace_id: uuid.UUID, document_id: uuid.UUID) -> Document | None:
    row = (await session.execute(text(SELECT_DOCUMENTS + " and d.id = :id"), {"w": workspace_id, "id": document_id})).first()
    return Document(*row) if row else None


async def find_by_sha(session: AsyncConnection, workspace_id: uuid.UUID, digest: str) -> Document | None:
    row = (await session.execute(text(SELECT_DOCUMENTS + " and d.sha256 = :s"), {"w": workspace_id, "s": digest})).first()
    return Document(*row) if row else None


async def enqueue(session: AsyncConnection, workspace_id: uuid.UUID, filename: str, data: bytes) -> Document:
    """Store an upload as pending. The same bytes again return the stored document; a failed one is queued again."""
    kind = parsing.kind_of(filename, data)
    existing = await find_by_sha(session, workspace_id, sha256(data))
    if existing and existing.status != "failed":
        return existing
    if existing:
        await session.execute(REQUEUE, {"w": workspace_id, "d": existing.id})
        return await get_document(session, workspace_id, existing.id)
    document_id = await session.scalar(
        text(
            "insert into loreos.documents (workspace_id, filename, kind, sha256, content) "
            "values (:w, :f, :k, :s, :c) returning id"
        ),
        {"w": workspace_id, "f": filename, "k": kind, "s": sha256(data), "c": data},
    )
    return await get_document(session, workspace_id, document_id)


async def enqueue_url(session: AsyncConnection, workspace_id: uuid.UUID, url: str) -> Document:
    """Queue a page by its normalised URL; the same URL again is queued again, so it is fetched again.

    Raises fetch_url.Refused for a URL that is not http(s). Re-queueing a row the worker holds raises the
    lock timeout (sqlstate 55P03) after 2 s instead of waiting for the worker to finish.
    """
    url = fetch_url.normalise(url)
    existing = await find_by_sha(session, workspace_id, sha256(url.encode()))
    if existing:
        await session.execute(LOCK_TIMEOUT)
        await session.execute(REQUEUE, {"w": workspace_id, "d": existing.id})
        return await get_document(session, workspace_id, existing.id)
    document_id = await session.scalar(
        text(
            "insert into loreos.documents (workspace_id, filename, kind, sha256, source_url) "
            "values (:w, :u, 'url', :s, :u) returning id"
        ),
        {"w": workspace_id, "u": url, "s": sha256(url.encode())},
    )
    return await get_document(session, workspace_id, document_id)


async def ingest(session: AsyncConnection, workspace_id: uuid.UUID, filename: str, data: bytes) -> Document:
    """Store and process an upload inline, for the evaluation and paid:smoke. A processed duplicate is returned as stored."""
    document = await enqueue(session, workspace_id, filename, data)
    if document.status != "pending":
        return document
    await process(session, workspace_id, document.id)
    return await get_document(session, workspace_id, document.id)


async def run_stages(session: AsyncConnection, workspace_id: uuid.UUID, document_id: uuid.UUID) -> int:
    """Lock the row, (fetch,) parse, chunk, embed, replace the chunks and mark it processed; the chunk count.

    The row lock is held until the caller's transaction ends. A failure raises StageError and records nothing.
    A rerun gives the same chunks.
    """
    ids = {"w": workspace_id, "d": document_id}
    filename, kind, content, source_url = (
        await session.execute(
            text("select filename, kind, content, source_url from loreos.documents where id = :d and workspace_id = :w for update"),
            ids,
        )
    ).one()
    stage = "fetch"
    try:
        fetched = await fetch_url.fetch(source_url) if kind == "url" else None
        stage = "parse"
        sections = parsing.parse(filename, fetched.content, kind=fetched.kind) if fetched else parsing.parse(filename, content)
        chunks = chunking.chunk(sections)
        stage = "embed"
        vectors = await llm.embed([embedding_input(c) for c in chunks])
        stage = "store"
        rows = [_chunk_row(ids, c, v) for c, v in zip(chunks, vectors, strict=True)]
        await session.execute(text("delete from loreos.chunks where document_id = :d and workspace_id = :w"), ids)
        await session.execute(INSERT_CHUNK, rows)
        await session.execute(
            text(
                "update loreos.documents set status = 'processed', processed_at = clock_timestamp(), "
                "content = coalesce(:c, content), error = null, next_attempt_at = null, locked_until = null "
                "where id = :d and workspace_id = :w"
            ),
            {**ids, "c": fetched.content if fetched else None},  # an upload's stored bytes are not sent again
        )
    except Exception as e:  # the stage classifies it; the caller records it
        raise StageError(stage) from e
    return len(chunks)


async def process(session: AsyncConnection, workspace_id: uuid.UUID, document_id: uuid.UUID) -> None:
    """run_stages inside a savepoint. Any failure leaves the document failed with zero chunks and `error` naming the stage."""
    try:
        async with session.begin_nested():  # a failed store rolls back to here and leaves the transaction usable
            count = await run_stages(session, workspace_id, document_id)
    except StageError as e:
        error = scrub(f"{e.stage}: {type(e.__cause__).__name__}: {e.__cause__}")
        await record_failed(session, workspace_id, document_id, error)
        log.warning("ingest failed document=%s stage=%s error=%s", document_id, e.stage, error)
        return
    log.info("ingest processed document=%s chunks=%d", document_id, count)


async def record_failed(session: AsyncConnection, workspace_id: uuid.UUID, document_id: uuid.UUID, error: str) -> None:
    """Mark the document failed with one more attempt, and delete its chunks: search does not filter by status."""
    ids = {"w": workspace_id, "d": document_id}
    await session.execute(
        text("update loreos.documents set status = 'failed', attempts = attempts + 1, error = :e where id = :d and workspace_id = :w"),
        {**ids, "e": scrub(error)},
    )
    await session.execute(text("delete from loreos.chunks where document_id = :d and workspace_id = :w"), ids)


def embedding_input(c: Chunk) -> str:
    """The heading path joined with ' > ', a blank line, then the chunk text."""
    return " > ".join(c.heading_path) + "\n\n" + c.text if c.heading_path else c.text


def _chunk_row(ids: dict, c: Chunk, vector: list[float]) -> dict:
    return {
        **ids,
        "ordinal": c.ordinal,
        "text": c.text,
        "heading_path": c.heading_path,
        "page": c.page,
        "token_count": c.token_count,
        "embedding": vector_literal(vector),
    }


def scrub(message: str) -> str:
    """Never store a key: drop sk- keys and the configured key value, and cap the length."""
    message = re.sub(r"sk-[A-Za-z0-9_\-*]{6,}", "sk-***", message)
    if key := os.environ.get("OPENAI_API_KEY", "").strip():
        message = message.replace(key, "***")
    return message[:MAX_ERROR_CHARS]
