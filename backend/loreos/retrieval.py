"""Vector search over one workspace's chunks: an exact cosine scan. P3 adds a mode argument."""

import uuid
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from loreos import llm

HAS_CHUNKS = text("select exists (select 1 from loreos.chunks where workspace_id = :w)")
NEAREST = text(
    """
    select c.id, c.document_id, d.filename, c.heading_path, c.page, c.text,
           1 - (c.embedding <=> cast(:q as vector)) as score
    from loreos.chunks c
    join loreos.documents d on d.id = c.document_id and d.workspace_id = c.workspace_id
    where c.workspace_id = :w
    order by c.embedding <=> cast(:q as vector)
    limit :k
    """
)


@dataclass
class Hit:
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    filename: str
    heading_path: list[str]
    page: int | None
    text: str
    score: float


def vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(map(str, vector)) + "]"


async def search(session: AsyncConnection, workspace_id: uuid.UUID, query: str, k: int) -> list[Hit]:
    """The k chunks closest to the query, best first. No chunks: no hits, and no embedding is bought."""
    if not await session.scalar(HAS_CHUNKS, {"w": workspace_id}):
        return []
    [vector] = await llm.embed([query])
    rows = await session.execute(NEAREST, {"q": vector_literal(vector), "w": workspace_id, "k": k})
    return [Hit(*row) for row in rows]
