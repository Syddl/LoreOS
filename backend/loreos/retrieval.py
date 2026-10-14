"""Search over one workspace's chunks, in one of three modes.

vector: an exact cosine scan. hybrid: the vector and keyword rankings fused by RRF. hybrid_rerank: the fused top
candidates rescored by the local cross-encoder.
"""

import asyncio
import uuid
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from loreos import fusion, llm, rerank, settings

MODES = ("vector", "hybrid", "hybrid_rerank")
DEFAULT_MODE = "vector"  # decision 0010 sets it from the committed comparison
FUSE_DEPTH = 50  # hits taken from each ranking before fusion
RERANK_DEPTH = 30  # fused candidates the cross-encoder rescores

HAS_CHUNKS = text("select exists (select 1 from loreos.chunks where workspace_id = :w)")
NEAREST = text(
    """
    select c.id, c.document_id, d.filename, c.heading_path, c.page, c.text,
           1 - (c.embedding <=> cast(:q as vector)) as score
    from loreos.chunks c
    join loreos.documents d on d.id = c.document_id and d.workspace_id = c.workspace_id
    where c.workspace_id = :w
    order by c.embedding <=> cast(:q as vector), c.id
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


def serving_mode() -> str:
    """The mode the api answers with: DEFAULT_MODE, or hybrid when that is hybrid_rerank and RERANK=off."""
    if DEFAULT_MODE == "hybrid_rerank" and not settings.rerank_on():
        return "hybrid"
    return DEFAULT_MODE


async def search(session: AsyncConnection, workspace_id: uuid.UUID, query: str, k: int, mode: str = "vector") -> list[Hit]:
    """The k best chunks for the query in exactly this mode, best first; `score` is the mode's own score (cosine
    similarity, RRF score, or cross-encoder score). No chunks: no hits, and no embedding is bought."""
    if mode not in MODES:
        raise ValueError(f"mode {mode!r} is not one of {', '.join(MODES)}")
    if not await session.scalar(HAS_CHUNKS, {"w": workspace_id}):
        return []
    if mode == "vector":
        [vector] = await llm.embed([query])
        return await _nearest(session, workspace_id, vector, k)
    # Keyword search first: it is free, and a question Postgres refuses then fails before the embedding is bought.
    keyword = await keyword_search(session, workspace_id, query, FUSE_DEPTH)
    [vector] = await llm.embed([query])
    nearest = await _nearest(session, workspace_id, vector, FUSE_DEPTH)
    by_id = {hit.chunk_id: hit for hit in [*keyword, *nearest]}
    fused = []
    for chunk_id, score in fusion.rrf([[hit.chunk_id for hit in nearest], [hit.chunk_id for hit in keyword]]):
        by_id[chunk_id].score = score
        fused.append(by_id[chunk_id])
    if mode == "hybrid":
        return fused[:k]
    # Seconds of CPU: in a thread, so the event loop keeps serving other requests meanwhile.
    return (await asyncio.to_thread(rerank.rerank, query, fused[:RERANK_DEPTH]))[:k]


async def _nearest(session: AsyncConnection, workspace_id: uuid.UUID, vector: list[float], n: int) -> list[Hit]:
    rows = await session.execute(NEAREST, {"q": vector_literal(vector), "w": workspace_id, "k": n})
    return [Hit(*row) for row in rows]


async def keyword_search(session: AsyncConnection, workspace_id: uuid.UUID, query: str, n: int) -> list[Hit]:
    """Up to n chunks holding any lexeme of the query, by ts_rank_cd, best first. Free: no embedding."""
    # Postgres text refuses NUL (22021); as a separator it changes no lexeme.
    rows = await session.execute(KEYWORD, {"q": query.replace("\x00", " "), "w": workspace_id, "n": n})
    return [Hit(*row) for row in rows]
