"""DOCX to sections: Title and Heading 1 to 9 paragraphs build the heading path, and each table row becomes a line."""

import io
import re
import zipfile
from itertools import groupby

import docx
from docx.table import Table

from loreos.parsing import ParseError, Section

MAX_UNPACKED_BYTES = 100 * 1024 * 1024  # checked on the zip directory, before python-docx inflates anything
HEADING_STYLE = re.compile(r"Heading ([1-9])")


def parse(data: bytes) -> list[Section]:
    try:
        # zipfile stops each member at its declared size, so the declared sum bounds what python-docx can inflate.
        with zipfile.ZipFile(io.BytesIO(data)) as package:
            unpacked = sum(info.file_size for info in package.infolist())
        if unpacked > MAX_UNPACKED_BYTES:
            limit = MAX_UNPACKED_BYTES / 1024 / 1024
            raise ParseError(f"the DOCX unpacks to over {limit:g} MB; remove large images or split the document, then upload it again")
        sections = [s for s in _sections(docx.Document(io.BytesIO(data))) if s.text]
    except ParseError:
        raise
    except Exception as e:  # zipfile, lxml and python-docx raise many types on a damaged file
        raise ParseError(f"cannot read the DOCX ({type(e).__name__}: {e}); check that it opens in Word and is saved as .docx") from e
    if not sections:
        raise ParseError("no text found in the DOCX; check that it is not empty")
    return sections


def _sections(document) -> list[Section]:
    sections: list[Section] = []
    stack: list[tuple[int, str]] = []
    blocks: list[str] = []

    def flush() -> None:
        sections.append(Section([title for _, title in stack], None, "\n\n".join(b for b in blocks if b)))
        blocks.clear()

    for block in document.iter_inner_content():
        if isinstance(block, Table):
            blocks.append(_table(block))
            continue
        text = block.text.strip()
        level = _heading_level(block.style.name if block.style is not None else "")
        if level is None or not text:
            blocks.append(text)
            continue
        flush()
        while stack and stack[-1][0] >= level:
            stack.pop()
        stack.append((level, " ".join(text.split())))
    flush()
    return sections


def _heading_level(style: str) -> int | None:
    """0 for Title, so it sits above Heading 1; None for a body style."""
    if style == "Title":
        return 0
    m = HEADING_STYLE.fullmatch(style)
    return int(m[1]) if m else None


def _table(table: Table) -> str:
    """One line per row, cells joined with ' | '; a cell's own line breaks become spaces."""
    # python-docx repeats a horizontally merged cell once per column it spans; groupby keeps one.
    rows = [[" ".join(cell.text.split()) for cell, _ in groupby(row.cells)] for row in table.rows]
    return "\n".join(" | ".join(cells) for cells in rows if any(cells))
