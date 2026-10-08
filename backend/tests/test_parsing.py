import time

import pytest

from loreos.parsing import ParseError, Section, UnsupportedType, kind_of, parse
from pdf import make_pdf

MARKDOWN = """---
title: Handbook
tags: [a, b]
---
Intro before any heading.

# Engineering

Engineering overview.

## On-call ##

Pages go to the primary.

```bash
# not a heading
echo hi
```

### Escalation

Call the secondary.

## Releases

Ship on Tuesdays.

#hashtag is not a heading either.

# Sales

Sales text.
"""


def test_markdown_sections_keep_heading_paths():
    sections = parse("handbook.md", MARKDOWN.encode())
    assert [(s.heading_path, s.text.splitlines()[0]) for s in sections] == [
        ([], "Intro before any heading."),
        (["Engineering"], "Engineering overview."),
        (["Engineering", "On-call"], "Pages go to the primary."),
        (["Engineering", "On-call", "Escalation"], "Call the secondary."),
        (["Engineering", "Releases"], "Ship on Tuesdays."),
        (["Sales"], "Sales text."),
    ]
    assert all(s.page is None for s in sections)


def test_markdown_drops_front_matter_and_keeps_fenced_hashes():
    sections = parse("handbook.markdown", MARKDOWN.encode())
    text = "\n".join(s.text for s in sections)
    assert "title: Handbook" not in text
    assert "# not a heading" in sections[2].text
    assert "#hashtag is not a heading either." in sections[4].text


def test_markdown_crlf_and_bom():
    sections = parse("a.md", "﻿# One\r\n\r\nbody\r\n".encode())
    assert sections == [Section(["One"], None, "body")]


@pytest.mark.parametrize(
    ("line", "title"),
    [
        ("## Title {#id}", "Title"),
        ("## Collaboration{#collab}", "Collaboration"),
        ("## 🤝 Collaboration{#collaboration}", "🤝 Collaboration"),
        ("#### Traveling with 1Password{#travel-mode}", "Traveling with 1Password"),
        ('## <i class="fas"></i>Compliance', "Compliance"),
        ('## <i class="fas fa-tasks fa-fw color-orange font-awesome"></i>Compliance', "Compliance"),
        ("## Use {braces} here", "Use {braces} here"),
        ("## Ends in {braces}", "Ends in {braces}"),
        ("## {#only-an-anchor}", ""),
        ('## <i class="x"></i>Title', "Title"),
        ("## </b>Title", "Title"),
        ("## x < 5 and y > 3", "x < 5 and y > 3"),
        ("## Values <= 10 and >= 5", "Values <= 10 and >= 5"),
    ],
)
def test_heading_text_drops_anchor_and_html_tags(line, title):
    assert parse("a.md", f"{line}\n\nbody\n".encode()) == [Section([title], None, "body")]


@pytest.mark.parametrize(
    ("line", "title"),
    [
        ("## foo ##   ", "foo"),
        ("## foo\t#", "foo"),
        ("## foo#", "foo#"),
        ("## foo ## bar", "foo ## bar"),
        ("## foo # #", "foo #"),
        ("### ###", ""),
        ("#\t", ""),
    ],
)
def test_closing_hashes_follow_commonmark(line, title):
    assert parse("a.md", f"{line}\n\nbody\n".encode()) == [Section([title], None, "body")]


def test_cleaned_headings_nest_into_a_clean_path():
    text = '## Teams {#teams}\n\n### <i class="fas fa-tasks"></i>Compliance\n\nbody\n'
    assert parse("a.md", text.encode()) == [Section(["Teams", "Compliance"], None, "body")]


@pytest.mark.parametrize(
    "title",
    [" " * 200_000 + "x", "{#" * 100_000, "<" * 200_000, "<a" * 100_000, "a" + " " * 200_000 + "b"],
    ids=["spaces", "anchor-openers", "tag-openers", "tag-name-openers", "interior-spaces"],
)
def test_hostile_heading_parses_in_linear_time(title):
    start = time.perf_counter()
    parse("a.md", f"## {title}\n\nbody\n".encode())
    assert time.perf_counter() - start < 1


def test_txt_is_one_section():
    assert parse("notes.txt", b"line one\n\nline two\n") == [Section([], None, "line one\n\nline two")]


def test_pdf_pages_numbered_from_one_and_empty_pages_skipped():
    sections = parse("report.pdf", make_pdf(["First page text", "", "Third page text"]))
    assert [(s.page, s.text, s.heading_path) for s in sections] == [
        (1, "First page text", []),
        (3, "Third page text", []),
    ]


def test_pdf_detected_by_header_under_any_name():
    assert kind_of("download.bin", make_pdf(["x"])) == "pdf"
    assert parse("download.bin", make_pdf(["Hello"]))[0].page == 1


def test_textless_pdf_fails_with_its_message():
    with pytest.raises(ParseError, match=r"no extractable text \(scanned PDF\?\)"):
        parse("scan.pdf", make_pdf(["", ""]))


def test_damaged_pdf_is_a_parse_error():
    with pytest.raises(ParseError, match="cannot read the PDF"):
        parse("broken.pdf", b"%PDF-1.4\nnot really a pdf")


def test_kinds_and_unsupported_types():
    assert [kind_of(n, b"x") for n in ("a.md", "a.MARKDOWN", "a.txt", "a.pdf")] == ["md", "md", "txt", "pdf"]
    with pytest.raises(UnsupportedType, match=r"\.md, \.markdown, \.txt or \.pdf"):
        kind_of("contract.docx", b"PK\x03\x04")


def test_non_utf8_and_empty_text_are_parse_errors():
    with pytest.raises(ParseError, match="UTF-8"):
        parse("latin.txt", "café".encode("latin-1"))
    with pytest.raises(ParseError, match="no text"):
        parse("empty.md", b"---\na: b\n---\n# Only a heading\n")
