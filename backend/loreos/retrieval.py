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
# Any of the question's lexemes, not all: plainto_tsquery stems the question once, drops its punctuation and ANDs the
# lexemes; its text form quotes each lexeme and parses back unchanged, and a lexeme holds no space, so turning ' & '
# into ' | ' changes only the operators. Stop words alone give an empty query (numnode 0), which matches nothing.
KEYWORD = text(
    """
    with q as (select replace(plainto_tsquery('english', :q)::text, ' & ', ' | ')::tsquery as query)
    select c.id, c.document_id, d.filename, c.heading_path, c.page, c.text, ts_rank_cd(c.tsv, q.query) as score
    from q, loreos.chunks c
    join loreos.documents d on d.id = c.document_id and d.workspace_id = c.workspace_id
    where numnode(q.query) > 0 and c.workspace_id = :w and c.tsv @@ q.query
    order by score desc, c.id
    limit :n
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


async def keyword_search(session: AsyncConnection, workspace_id: uuid.UUID, query: str, n: int) -> list[Hit]:
    """Up to n chunks holding any lexeme of the query, by ts_rank_cd, best first. Free: no embedding."""
    rows = await session.execute(KEYWORD, {"q": query, "w": workspace_id, "n": n})
    return [Hit(*row) for row in rows]
