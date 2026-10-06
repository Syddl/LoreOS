"""Split sections into chunks within a token budget; a chunk never spans two sections."""

import functools
import re
from dataclasses import dataclass

import tiktoken

from loreos.parsing import Section

CHUNK_TOKENS = 500  # measured in P3
CHUNK_OVERLAP = 50


@dataclass
class Chunk:
    ordinal: int
    text: str
    heading_path: list[str]
    page: int | None
    token_count: int


@functools.cache
def _encoding() -> tiktoken.Encoding:
    return tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str) -> int:
    return len(_encoding().encode(text))


def chunk(sections: list[Section], max_tokens: int = CHUNK_TOKENS, overlap_tokens: int = CHUNK_OVERLAP) -> list[Chunk]:
    chunks: list[Chunk] = []
    for section in sections:
        for text in _split(section.text, max_tokens, overlap_tokens):
            chunks.append(Chunk(len(chunks), text, section.heading_path, section.page, count_tokens(text)))
    return chunks


def _split(text: str, max_tokens: int, overlap_tokens: int) -> list[str]:
    if count_tokens(text) <= max_tokens:
        return [text]
    out: list[str] = []
    current = ""
    for sep, piece in _pieces(text, max_tokens - overlap_tokens):
        candidate = current + sep + piece if current else piece
        if current and count_tokens(candidate) > max_tokens:
            out.append(current)
            room = max_tokens - count_tokens(sep + piece)
            tail = _tail(current, min(overlap_tokens, room))
            candidate = tail + sep + piece if tail else piece
            if count_tokens(candidate) > max_tokens:  # re-tokenising across the join can add a token
                candidate = piece
        current = candidate
    out.append(current)
    return out


def _tail(text: str, tokens: int) -> str:
    """The last `tokens` tokens of text, without a broken character at the start."""
    if tokens <= 0:
        return ""
    return _encoding().decode(_encoding().encode(text)[-tokens:]).lstrip("�")


def _pieces(text: str, limit: int) -> list[tuple[str, str]]:
    """(separator, piece) pairs, each piece within limit: paragraphs, then sentences, then token windows."""
    out: list[tuple[str, str]] = []
    for paragraph in re.split(r"\n\s*\n", text):
        paragraph = paragraph.strip()
        sep = "\n\n"
        for sentence in [paragraph] if count_tokens(paragraph) <= limit else re.split(r"(?<=[.!?])\s+", paragraph):
            ids = _encoding().encode(sentence)
            for start in range(0, len(ids), limit):
                out.append((sep, _encoding().decode(ids[start : start + limit])))
                sep = ""
            sep = " "
    return [(sep, piece) for sep, piece in out if piece.strip()]
