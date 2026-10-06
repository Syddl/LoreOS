from loreos.chunking import CHUNK_OVERLAP, CHUNK_TOKENS, chunk, count_tokens
from loreos.parsing import Section

# 12 distinct paragraphs of 4 distinct sentences, about 80 tokens each, so a shared tail means real overlap.
PARAGRAPHS = [
    " ".join(f"Runbook step {p}.{s} says the on-call engineer acknowledges the page, ticket {p}-{s}." for s in range(4))
    for p in range(12)
]
LONG = "\n\n".join(PARAGRAPHS)
RUN_ON = "word " * 400  # one sentence with no break, forcing token windows


def test_defaults():
    assert (CHUNK_TOKENS, CHUNK_OVERLAP) == (500, 50)


def test_section_within_budget_is_one_chunk_with_its_text():
    [only] = chunk([Section(["A", "B"], None, "Short text.")])
    assert (only.ordinal, only.text, only.heading_path, only.page) == (0, "Short text.", ["A", "B"], None)
    assert only.token_count == count_tokens("Short text.")


def test_long_section_splits_within_budget_with_overlap():
    chunks = chunk([Section(["Runbook"], None, LONG)], max_tokens=120, overlap_tokens=20)
    assert len(chunks) > 3
    assert all(c.token_count == count_tokens(c.text) <= 120 for c in chunks)
    assert all(c.heading_path == ["Runbook"] for c in chunks)
    for before, after in zip(chunks, chunks[1:]):
        assert before.text[-15:] in after.text[:150], "each later chunk starts with the end of the one before"


def test_split_prefers_paragraph_breaks():
    chunks = chunk([Section([], None, LONG)], max_tokens=120, overlap_tokens=0)
    assert all(set(c.text.split("\n\n")) <= set(PARAGRAPHS) for c in chunks), "whole paragraphs only"
    assert "\n\n".join(c.text for c in chunks) == LONG


def test_run_on_text_falls_back_to_token_windows():
    chunks = chunk([Section([], 7, RUN_ON)], max_tokens=60, overlap_tokens=10)
    assert len(chunks) > 5
    assert all(c.token_count <= 60 and c.page == 7 for c in chunks)


def test_chunks_never_span_sections_and_ordinals_run_in_order():
    sections = [Section(["A"], None, LONG), Section(["B"], None, "B text."), Section([], 2, LONG)]
    chunks = chunk(sections, max_tokens=120, overlap_tokens=20)
    assert [c.ordinal for c in chunks] == list(range(len(chunks)))
    b = next(c for c in chunks if c.heading_path == ["B"])
    assert b.text == "B text.", "the first chunk of a section carries no tail from the section before"
    first_of_page = next(c for c in chunks if c.page == 2)
    assert first_of_page.text.startswith("Runbook step 0.0 ")
    assert all(c.token_count <= 120 for c in chunks)
