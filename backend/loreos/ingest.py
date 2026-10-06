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

from loreos import chunking, llm, parsing
from loreos.chunking import Chunk
from loreos.retrieval import vector_literal

log = logging.getLogger("loreos.ingest")

MAX_ERROR_CHARS = 1000
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


async def ingest(session: AsyncConnection, workspace_id: uuid.UUID, filename: str, data: bytes) -> Document:
    """Store and process an upload. The same bytes again return the stored document; a failed one is retried."""
    kind = parsing.kind_of(filename, data)
    existing = await find_by_sha(session, workspace_id, sha256(data))
    if existing and existing.status != "failed":
        return existing
    document_id = existing.id if existing else await session.scalar(
        text(
            "insert into loreos.documents (workspace_id, filename, kind, sha256, content) "
            "values (:w, :f, :k, :s, :c) returning id"
        ),
        {"w": workspace_id, "f": filename, "k": kind, "s": sha256(data), "c": data},
    )
    await process(session, workspace_id, document_id)
    return await get_document(session, workspace_id, document_id)


async def process(session: AsyncConnection, workspace_id: uuid.UUID, document_id: uuid.UUID) -> None:
    """Replace the document's chunks from its stored content. A rerun gives the same chunks (P4's worker relies on it).

    Any failure leaves the document failed with zero chunks and `error` naming the stage.
    """
    ids = {"w": workspace_id, "d": document_id}
    filename, content = (
        await session.execute(text("select filename, content from loreos.documents where id = :d and workspace_id = :w"), ids)
    ).one()
    await session.execute(
        text("update loreos.documents set status = 'processing', attempts = attempts + 1, error = null where id = :d and workspace_id = :w"),
        ids,
    )
    await session.execute(text("delete from loreos.chunks where document_id = :d and workspace_id = :w"), ids)
    stage = "parse"
    try:
        chunks = chunking.chunk(parsing.parse(filename, content))
        stage = "embed"
        vectors = await llm.embed([embedding_input(c) for c in chunks])
        stage = "store"
        async with session.begin_nested():  # a failed insert rolls back to here and leaves the transaction usable
            await session.execute(INSERT_CHUNK, [_chunk_row(ids, c, v) for c, v in zip(chunks, vectors, strict=True)])
            await session.execute(
                text("update loreos.documents set status = 'processed', processed_at = clock_timestamp() where id = :d and workspace_id = :w"),
                ids,
            )
    except Exception as e:  # every failure is recorded on the document; the stage classifies it
        error = _scrub(f"{stage}: {type(e).__name__}: {e}")
        await session.execute(text("update loreos.documents set status = 'failed', error = :e where id = :d and workspace_id = :w"), {**ids, "e": error})
        log.warning("ingest failed document=%s stage=%s error=%s", document_id, stage, error)
        return
    log.info("ingest processed document=%s chunks=%d", document_id, len(chunks))


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


def _scrub(message: str) -> str:
    """Never store a key: drop sk- keys and the configured key value, and cap the length."""
    message = re.sub(r"sk-[A-Za-z0-9_\-*]{6,}", "sk-***", message)
    if key := os.environ.get("OPENAI_API_KEY", "").strip():
        message = message.replace(key, "***")
    return message[:MAX_ERROR_CHARS]
