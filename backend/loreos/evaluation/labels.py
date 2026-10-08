"""Whether a hit answers a labeled source, and the corpus outline that labels are written from.

A label names a file and a heading path (Markdown) or a physical page (PDF), never a chunk, so it
survives a change of chunk size. A hit is anything with `filename`, `heading_path` and `page`.
"""

import difflib
import itertools
from dataclasses import dataclass

from loreos import chunking, parsing

OUTLINE_HEADER = """\
Every section of the evaluation corpus, with the number of chunks it makes.
A line below becomes a label:
- Markdown: {"file": "<file>", "heading_path": [...]}, one heading per element, for the path on the line
  or any prefix of it. Copy each heading exactly: a label matches only a byte-for-byte equal heading.
- PDF: {"file": "<file>", "page": n}, n being the physical page (the nth page of the file, not the printed folio).
Label the most specific heading that answers. Text before the first heading of a Markdown file cannot be labeled.
"""


@dataclass
class OutlineEntry:
    file: str
    heading_path: list[str]
    page: int | None
    chunks: int


def is_relevant(hit, source: dict) -> bool:
    """Same file, and the label's heading path is a list prefix of the hit's, or the same page."""
    return _covers(source, hit.filename, hit.heading_path, hit.page)


def matched_sources(hit, sources: list[dict]) -> list[int]:
    return [i for i, source in enumerate(sources) if is_relevant(hit, source)]


def outline(corpus: dict[str, bytes]) -> list[OutlineEntry]:
    """One entry per parsed section, files in sorted order, each section chunked alone as ingest would."""
    return [
        OutlineEntry(file, section.heading_path, section.page, len(chunking.chunk([section])))
        for file in sorted(corpus)
        for section in parsing.parse(file, corpus[file])
    ]


def label_problems(questions: list[dict], entries: list[OutlineEntry]) -> list[str]:
    """Each label that names no corpus file or covers no section, with the closest heading when one is near."""
    files = {e.file for e in entries}
    problems = []
    for qid, source in _labels(questions):
        prefix = f"{qid}: {source['file']}: "
        if source["file"] not in files:
            problems.append(prefix + "the file is not in the corpus; copy its name from outline.txt")
        elif not _covered(source, entries):
            problems.append(prefix + f"{_describe(source)} matches no section in outline.txt{_closest(source, entries)}")
    return problems


def broad_labels(questions: list[dict], entries: list[OutlineEntry], max_chunks: int = 3) -> list[str]:
    warnings = []
    for qid, source in _labels(questions):
        chunks = sum(e.chunks for e in _covered(source, entries))
        if chunks > max_chunks:
            where = f"{qid}: {source['file']}: {_describe(source)}"
            warnings.append(f"{where} spans {chunks} chunks; label a narrower heading if one answers")
    return warnings


def render_outline(entries: list[OutlineEntry]) -> str:
    lines = [OUTLINE_HEADER.rstrip("\n")]
    for file, group in itertools.groupby(entries, key=lambda e: e.file):
        lines += ["", f"## {file}"]
        lines += [f"{_place(e)}  (chunks: {e.chunks})" for e in group]
    return "\n".join(lines) + "\n"


def _covers(source: dict, file: str, heading_path: list[str], page: int | None) -> bool:
    if file != source["file"]:
        return False
    # An empty path is a prefix of every path; the validator forbids it, and it matches nothing here.
    if path := source.get("heading_path"):
        return heading_path[: len(path)] == path
    return source.get("page") is not None and page == source["page"]


def _covered(source: dict, entries: list[OutlineEntry]) -> list[OutlineEntry]:
    return [e for e in entries if _covers(source, e.file, e.heading_path, e.page)]


def _labels(questions: list[dict]) -> list[tuple[str, dict]]:
    return [(q["id"], source) for q in questions if q["answerable"] for source in q["sources"]]


def _describe(source: dict) -> str:
    if "page" in source:
        return f"page {source['page']}"
    joined = " > ".join(source["heading_path"])
    return f'heading "{joined}"'


def _closest(source: dict, entries: list[OutlineEntry]) -> str:
    if "page" in source:
        return ""
    paths = {" > ".join(e.heading_path) for e in entries if e.file == source["file"] and e.heading_path}
    match = difflib.get_close_matches(" > ".join(source["heading_path"]), paths, n=1)
    return f'; closest: "{match[0]}"' if match else ""


def _place(entry: OutlineEntry) -> str:
    if entry.page is not None:
        return f"page {entry.page}"
    return " > ".join(entry.heading_path) or "(before the first heading)"
