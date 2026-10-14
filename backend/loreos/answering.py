"""Cited answers: search, draft, then keep only the [n] markers that point at a passage."""

import logging
import re
import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncConnection

from loreos import llm, retrieval
from loreos.retrieval import Hit

REFUSAL = "I couldn't find this in your documents."
TOP_K = 5
MARKER = re.compile(r"\s*\[(\d+)\]")

log = logging.getLogger("loreos.answering")


@dataclass
class Citation:
    n: int
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    filename: str
    heading_path: list[str]
    page: int | None
    text: str


@dataclass
class Answer:
    found: bool
    text: str
    citations: list[Citation]
    reason: str | None
    retrieval_mode: str  # the mode that found the hits; with RERANK=off it says hybrid where hybrid_rerank was the default


async def answer(session: AsyncConnection, workspace_id: uuid.UUID, question: str) -> Answer:
    mode = retrieval.serving_mode()
    return await answer_from_hits(question, await retrieval.search(session, workspace_id, question, TOP_K, mode), mode)


async def answer_from_hits(question: str, hits: list[Hit], mode: str) -> Answer:
    if not hits:
        return _refuse("no_chunks", mode)
    draft = await llm.draft_answer(question, hits)
    if not draft.found:
        return _refuse("model_not_found", mode)
    cited: set[int] = set()

    def keep(marker: re.Match) -> str:
        n = int(marker[1])
        if 1 <= n <= len(hits):
            cited.add(n)
            return marker[0]
        return ""

    answer_text = MARKER.sub(keep, draft.text).strip()
    if not cited:
        return _refuse("no_valid_citation", mode)
    citations = [
        Citation(n, h.chunk_id, h.document_id, h.filename, h.heading_path, h.page, h.text)
        for n in sorted(cited)
        for h in [hits[n - 1]]
    ]
    log.info("ask found=true reason=none citations=%d mode=%s", len(citations), mode)
    return Answer(True, answer_text, citations, None, mode)


def _refuse(reason: str, mode: str) -> Answer:
    log.info("ask found=false reason=%s mode=%s", reason, mode)
    return Answer(False, REFUSAL, [], reason, mode)
