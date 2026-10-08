import uuid

from loreos.evaluation.labels import (
    OutlineEntry,
    broad_labels,
    is_relevant,
    label_problems,
    matched_sources,
    outline,
    render_outline,
)
from loreos.retrieval import Hit
from pdf import make_pdf

HANDBOOK = """Intro before any heading.

# Leave

Leave overview.

## Sick

Sick leave text.

### Notes

Bring a note.

## Vacation

Vacation text.

## Sick

A second section under the same path.

# Benefits

## Dental

Dental text.
"""

TRAVEL = "# Travel\n\n" + "\n\n".join(["Book trains before flights and keep every receipt. " * 30] * 4)

CORPUS = {
    "travel.md": TRAVEL.encode(),
    "handbook.md": HANDBOOK.encode(),
    "manual.pdf": make_pdf(["Page one text", "", "Page three text"]),
}


def hit(filename: str, heading_path: list[str], page: int | None = None) -> Hit:
    return Hit(uuid.uuid4(), uuid.uuid4(), filename, heading_path, page, "text", 0.5)


def question(qid: str, *sources: dict) -> dict:
    return {"id": qid, "question": "?", "answerable": True, "sources": list(sources)}


def test_heading_label_matches_its_section_and_those_below_it():
    label = {"file": "handbook.md", "heading_path": ["Leave", "Sick"]}
    assert is_relevant(hit("handbook.md", ["Leave", "Sick"]), label)
    assert is_relevant(hit("handbook.md", ["Leave", "Sick", "Notes"]), label)
    assert not is_relevant(hit("handbook.md", ["Leave"]), label)


def test_sibling_heading_does_not_match():
    label = {"file": "handbook.md", "heading_path": ["Leave", "Sick"]}
    assert not is_relevant(hit("handbook.md", ["Leave", "Vacation"]), label)


def test_page_label_matches_the_same_page_only():
    label = {"file": "manual.pdf", "page": 3}
    assert is_relevant(hit("manual.pdf", [], 3), label)
    assert not is_relevant(hit("manual.pdf", [], 1), label)


def test_another_file_never_matches():
    assert not is_relevant(hit("other.md", ["Leave", "Sick"]), {"file": "handbook.md", "heading_path": ["Leave", "Sick"]})
    assert not is_relevant(hit("other.pdf", [], 3), {"file": "manual.pdf", "page": 3})


def test_empty_label_path_matches_nothing():
    label = {"file": "handbook.md", "heading_path": []}
    assert not is_relevant(hit("handbook.md", []), label)
    assert not is_relevant(hit("handbook.md", ["Leave"]), label)


def test_matched_sources_returns_the_indices_of_matching_sources():
    sources = [
        {"file": "other.md", "heading_path": ["Leave"]},
        {"file": "handbook.md", "heading_path": ["Leave"]},
        {"file": "handbook.md", "heading_path": ["Leave", "Vacation"]},
        {"file": "handbook.md", "heading_path": ["Leave", "Sick"]},
    ]
    assert matched_sources(hit("handbook.md", ["Leave", "Sick", "Notes"]), sources) == [1, 3]
    assert matched_sources(hit("manual.pdf", [], 1), sources) == []


def test_outline_has_one_entry_per_section_with_its_own_chunk_count():
    assert outline(CORPUS) == [
        OutlineEntry("handbook.md", [], None, 1),
        OutlineEntry("handbook.md", ["Leave"], None, 1),
        OutlineEntry("handbook.md", ["Leave", "Sick"], None, 1),
        OutlineEntry("handbook.md", ["Leave", "Sick", "Notes"], None, 1),
        OutlineEntry("handbook.md", ["Leave", "Vacation"], None, 1),
        OutlineEntry("handbook.md", ["Leave", "Sick"], None, 1),
        OutlineEntry("handbook.md", ["Benefits", "Dental"], None, 1),
        OutlineEntry("manual.pdf", [], 1, 1),
        OutlineEntry("manual.pdf", [], 3, 1),
        OutlineEntry("travel.md", ["Travel"], None, 4),
    ]


def test_render_outline_lists_paths_and_pages_with_chunk_counts():
    text = render_outline(outline(CORPUS))
    header, body = text.split("\n## ", 1)
    assert '{"file": "<file>", "heading_path": [...]}' in header
    assert '{"file": "<file>", "page": n}' in header
    assert ("## " + body).splitlines() == [
        "## handbook.md",
        "(before the first heading)  (chunks: 1)",
        "Leave  (chunks: 1)",
        "Leave > Sick  (chunks: 1)",
        "Leave > Sick > Notes  (chunks: 1)",
        "Leave > Vacation  (chunks: 1)",
        "Leave > Sick  (chunks: 1)",
        "Benefits > Dental  (chunks: 1)",
        "",
        "## manual.pdf",
        "page 1  (chunks: 1)",
        "page 3  (chunks: 1)",
        "",
        "## travel.md",
        "Travel  (chunks: 4)",
    ]


def test_labels_that_resolve_have_no_problems():
    questions = [
        question("q1", {"file": "handbook.md", "heading_path": ["Leave", "Sick"]}),
        question("q2", {"file": "handbook.md", "heading_path": ["Benefits"]}, {"file": "manual.pdf", "page": 3}),
        {"id": "q3", "question": "?", "answerable": False, "sources": []},
    ]
    assert label_problems(questions, outline(CORPUS)) == []


def test_unknown_heading_names_its_closest_match():
    questions = [question("q1", {"file": "handbook.md", "heading_path": ["Leave", "Sik"]})]
    [problem] = label_problems(questions, outline(CORPUS))
    assert problem.startswith("q1: handbook.md: ")
    assert '"Leave > Sik"' in problem
    assert 'closest: "Leave > Sick"' in problem


def test_unresolved_labels_and_unknown_files_are_problems():
    questions = [
        question("q1", {"file": "missing.md", "heading_path": ["Leave"]}),
        question("q2", {"file": "manual.pdf", "page": 2}, {"file": "travel.md", "heading_path": ["Leave"]}),
    ]
    problems = label_problems(questions, outline(CORPUS))
    assert len(problems) == 3
    assert problems[0].startswith("q1: missing.md: ")
    assert "not in the corpus" in problems[0]
    assert problems[1].startswith("q2: manual.pdf: ") and "page 2" in problems[1]
    assert problems[2].startswith("q2: travel.md: ") and '"Leave"' in problems[2]
    assert "closest" not in problems[2]


def test_broad_labels_are_warned_with_their_chunk_count():
    questions = [
        question("q1", {"file": "handbook.md", "heading_path": ["Leave"]}),
        question("q2", {"file": "handbook.md", "heading_path": ["Leave", "Sick"]}, {"file": "manual.pdf", "page": 3}),
        question("q3", {"file": "travel.md", "heading_path": ["Travel"]}),
    ]
    warnings = broad_labels(questions, outline(CORPUS))
    assert len(warnings) == 2
    assert warnings[0].startswith("q1: handbook.md: ") and '"Leave"' in warnings[0] and "5 chunks" in warnings[0]
    assert warnings[1].startswith("q3: travel.md: ") and '"Travel"' in warnings[1] and "4 chunks" in warnings[1]
    assert broad_labels(questions, outline(CORPUS), max_chunks=5) == []
