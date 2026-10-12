import pytest

from loreos import parse_html
from loreos.parsing import ParseError, Section

PAGE = b"""<!doctype html>
<html><body>
<header><h1>Site name</h1></header>
<p>Lead text   before
  any heading.</p>
<main>
<h1>Guide</h1>
<p>Guide intro.</p><p>Second paragraph.</p>
<section>
  <h2><a href="#install">Install</a> <small>v2</small></h2>
  <div><p>Run the installer.</p></div>
  <h3>Windows</h3><p>Use the MSI.</p>
  <h2>Configure</h2><p>Edit the file.</p>
</section>
<h1>Support</h1>
<p>Fish &amp; chips &lt;3 caf&eacute;&nbsp;open &#8212; it&#39;s here</p>
</main>
</body></html>"""


def test_headings_nest_and_siblings_replace_each_other():
    assert parse_html.parse(PAGE) == [
        Section([], None, "Lead text before any heading."),
        Section(["Guide"], None, "Guide intro. Second paragraph."),
        Section(["Guide", "Install v2"], None, "Run the installer."),
        Section(["Guide", "Install v2", "Windows"], None, "Use the MSI."),
        Section(["Guide", "Configure"], None, "Edit the file."),
        Section(["Support"], None, "Fish & chips <3 café open — it's here"),
    ]


@pytest.mark.parametrize("tag", ["script", "style", "nav", "header", "footer", "aside"])
def test_removed_elements_leave_no_text(tag):
    page = f"<body><p>Kept.</p><{tag}><h2>Removed heading</h2>Removed text</{tag}><p>Also kept.</p></body>"
    assert parse_html.parse(page.encode()) == [Section([], None, "Kept. Also kept.")]


@pytest.mark.parametrize("data", [b"", b"<html><body>  </body></html>", b"<script>var x = 1;</script><h1>Only a heading</h1>"])
def test_no_text_is_a_parse_error(data):
    with pytest.raises(ParseError, match="no text"):
        parse_html.parse(data)
