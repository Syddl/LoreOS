"""HTML to sections: page furniture is dropped, and h1 to h6 build the heading path the way Markdown headings do."""

from bs4 import BeautifulSoup, NavigableString, Tag

from loreos.parsing import ParseError, Section

DROPPED = ["script", "style", "nav", "header", "footer", "aside"]
HEADINGS = ["h1", "h2", "h3", "h4", "h5", "h6"]


def parse(data: bytes) -> list[Section]:
    soup = BeautifulSoup(data, "html.parser")
    for tag in soup.find_all(DROPPED):
        tag.decompose()
    sections: list[Section] = []
    stack: list[tuple[int, str]] = []
    strings: list[str] = []
    in_title: set[int] = set()  # the current heading's descendants, already read into its title

    def flush() -> None:
        # ponytail: strings join with a space, so a word split by inline markup (Hel<b>lo</b>) reads as two words.
        sections.append(Section([title for _, title in stack], None, _collapse(" ".join(strings))))
        strings.clear()

    for node in soup.descendants:
        if id(node) in in_title:
            continue
        if isinstance(node, Tag) and node.name in HEADINGS and (title := _collapse(node.get_text(" "))):
            flush()
            level = int(node.name[1])
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, title))
            in_title = {id(d) for d in node.descendants}
        elif type(node) is NavigableString:  # not a comment, doctype or template string
            strings.append(node)
    flush()
    sections = [s for s in sections if s.text]
    if not sections:
        raise ParseError("no text found in the page; check that the URL serves the text itself and not a page built by scripts")
    return sections


def _collapse(text: str) -> str:
    return " ".join(text.split())
