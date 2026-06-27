"""Loads a book file (PDF or EPUB) into normalised HTML with stable block ids.

Pure logic, no Qt. EPUB is unzipped and its spine HTML concatenated; PDF is
converted with pymupdf. A single pass then assigns id="b0", "b1", ... to each
block-level element in document order, so saved anchors stay valid across
sessions (same file in, same ids out)."""

from dataclasses import dataclass
from html.parser import HTMLParser

BLOCK_TAGS = frozenset(
    {"p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li", "blockquote"}
)


@dataclass
class BookDocument:
    """A book rendered to HTML with anchorable block ids in document order."""

    html: str
    block_ids: list[str]
    title: str


class _BlockIdAssigner(HTMLParser):
    """Re-emits HTML, adding data-stid="bN" to every block element in order.

    A private data-stid marker (not id) is used so it cannot collide with the
    book's own id attributes; every block is marked whether or not it already
    has an id. convert_charrefs is off and refs are re-emitted verbatim so the
    output is a faithful, deterministic copy of the input."""

    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.parts: list[str] = []
        self.ids: list[str] = []
        self._counter = 0

    def handle_starttag(self, tag, attrs):
        if tag in BLOCK_TAGS:
            new_id = f"b{self._counter}"
            self._counter += 1
            self.ids.append(new_id)
            attrs = attrs + [("data-stid", new_id)]
        self.parts.append(self._format_starttag(tag, attrs))

    def handle_startendtag(self, tag, attrs):
        # Self-closing tags (e.g. <br/>, <img/>) are never block anchors here.
        self.parts.append(self._format_starttag(tag, attrs, self_closing=True))

    def handle_endtag(self, tag):
        self.parts.append(f"</{tag}>")

    def handle_data(self, data):
        self.parts.append(data)

    def handle_entityref(self, name):
        self.parts.append(f"&{name};")

    def handle_charref(self, name):
        self.parts.append(f"&#{name};")

    def handle_comment(self, data):
        self.parts.append(f"<!--{data}-->")

    def _format_starttag(self, tag, attrs, self_closing=False):
        rendered = "".join(
            f' {name}="{value}"' if value is not None else f" {name}"
            for name, value in attrs
        )
        close = "/" if self_closing else ""
        return f"<{tag}{rendered}{close}>"


def assign_block_ids(body_html: str) -> tuple[str, list[str]]:
    """Add data-stid="bN" to each block element in order; return (html, ids)."""
    assigner = _BlockIdAssigner()
    assigner.feed(body_html)
    assigner.close()
    return "".join(assigner.parts), assigner.ids
