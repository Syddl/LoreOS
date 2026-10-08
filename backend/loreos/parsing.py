"""Turn an uploaded file into sections that keep their heading path or page."""

import io
import re
from dataclasses import dataclass
from pathlib import PurePath

from pypdf import PdfReader

KINDS = {".md": "md", ".markdown": "md", ".txt": "txt", ".pdf": "pdf"}

FRONT_MATTER = re.compile(r"\A---\n.*?\n(?:---|\.\.\.)(?:\n|\Z)", re.S)
FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
HEADING = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+(.*?))?(?:[ \t]+#+)?[ \t]*$")
HTML_TAG = re.compile(r"<[^<>]+>")  # stops at the next "<", so a line of "<" is scanned once, not quadratically


@dataclass
class Section:
    heading_path: list[str]
    page: int | None
    text: str


class UnsupportedType(ValueError):
    pass


class ParseError(ValueError):
    pass


def kind_of(filename: str, data: bytes) -> str:
    """'md', 'txt' or 'pdf', by extension or by a PDF header."""
    if data.startswith(b"%PDF-"):
        return "pdf"
    kind = KINDS.get(PurePath(filename).suffix.lower())
    if not kind:
        raise UnsupportedType(f"unsupported file type: {filename!r}; upload a .md, .markdown, .txt or .pdf file")
    return kind


def parse(filename: str, data: bytes) -> list[Section]:
    kind = kind_of(filename, data)
    if kind == "pdf":
        return _pdf(data)
    text = _decode(data)
    sections = _markdown(text) if kind == "md" else [Section([], None, text.strip())]
    sections = [s for s in sections if s.text]
    if not sections:
        raise ParseError("no text found in the file; check that it is not empty")
    return sections


def _decode(data: bytes) -> str:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as e:
        raise ParseError(f"the file is not UTF-8 text (byte {e.start}); save it as UTF-8 and upload it again") from e
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _markdown(text: str) -> list[Section]:
    """ATX headings outside fenced code start a section; the heading line itself goes into the path."""
    sections: list[Section] = []
    stack: list[tuple[int, str]] = []
    lines: list[str] = []
    fence = None

    def flush() -> None:
        sections.append(Section([title for _, title in stack], None, "\n".join(lines).strip()))
        lines.clear()

    for line in FRONT_MATTER.sub("", text, count=1).split("\n"):
        if fence:
            if line.strip().startswith(fence) and not line.strip().lstrip(fence[0]):
                fence = None
        elif m := FENCE.match(line):
            fence = m[1]
        elif m := HEADING.match(line):
            flush()
            level = len(m[1])
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, _heading_title(m[2] or "")))
            continue
        lines.append(line)
    flush()
    return sections


def _heading_title(text: str) -> str:
    """The heading as a reader sees it: no HTML tags, no trailing {#id} attribute block."""
    text = HTML_TAG.sub("", text).rstrip()
    # String search, not a regex: a pattern for the trailing block rescans from every "{#", quadratic on a hostile line.
    if text.endswith("}") and (i := text.rfind("{#")) != -1 and "}" not in text[i + 2 : -1]:
        text = text[:i]
    return text.strip()


def _pdf(data: bytes) -> list[Section]:
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted and not reader.decrypt(""):
            raise ParseError("the PDF is password-protected; upload an unprotected copy")
        texts = [page.extract_text() or "" for page in reader.pages]
    except ParseError:
        raise
    except Exception as e:  # pypdf raises many types on a damaged file
        raise ParseError(f"cannot read the PDF ({type(e).__name__}: {e}); check that it opens in a PDF viewer") from e
    sections = [Section([], number, text.strip()) for number, text in enumerate(texts, 1) if text.strip()]
    if not sections:
        raise ParseError("no extractable text (scanned PDF?)")
    return sections
