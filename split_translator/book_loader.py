"""Loads a book file (PDF or EPUB) into normalised HTML with stable paragraph ids.

Pure logic, no Qt. EPUB is unzipped and its spine HTML concatenated; PDF is
converted with pymupdf. Every block-level element is then counted in document
order, and each paragraph (a block with visible text of its own) is marked
data-stid="bN" with its count, so saved anchors stay valid across sessions (same
file in, same ids out). Blank spacer blocks are marked data-st-spacer for the
Normalise stylesheet instead."""

import posixpath
import re
import zipfile
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree

import pymupdf

BLOCK_TAGS = frozenset(
    {"p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li", "blockquote"}
)


@dataclass
class BookDocument:
    """A book rendered to HTML with anchorable paragraph ids in document order.

    ``block_ids`` lists paragraphs only: blocks with visible text of their own.
    ``block_texts`` runs parallel to it, each paragraph's visible own text.

    ``images`` maps an EPUB-root-relative resource path (the same path the HTML
    now references) to its bytes, so the renderer can lay the images out beside
    the HTML and they resolve over file://. Empty for PDFs (pymupdf inlines
    images) and image-less books."""

    html: str
    block_ids: list[str]
    title: str
    images: dict[str, bytes] = field(default_factory=dict)
    block_texts: list[str] = field(default_factory=list)


# Elements with no content and no end tag, so they never go on the stack of
# open elements.
_VOID_TAGS = frozenset(
    {
        "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
        "meta", "param", "source", "track", "wbr",
    }
)

# An image anywhere inside a block makes it more than a spacer. <image> is the
# SVG element an EPUB cover is usually drawn with.
_IMAGE_TAGS = frozenset({"img", "svg", "image"})

# Characters that take no room on the page: zero-width spaces and joiners, the
# byte order mark and the soft hyphen.
_ZERO_WIDTH_RE = re.compile("[​‌‍⁠﻿­]")
_WHITESPACE_RE = re.compile(r"\s+")


def _visible_text(raw: str) -> str:
    """Text as a reader sees it: zero-width characters removed, whitespace
    (the non-breaking space included) collapsed to single spaces, and trimmed.
    Empty when nothing would show."""
    return _WHITESPACE_RE.sub(" ", _ZERO_WIDTH_RE.sub("", raw)).strip()


class _BlockClassifier(HTMLParser):
    """First pass: for each block element, in the order the id counter meets
    them, the text it owns and whether anything visible sits anywhere inside.

    A block owns the text whose nearest enclosing block it is; inline elements
    are transparent. Whether a block is empty is only known at its end tag,
    which is why this runs as a pass of its own before any HTML is written."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.own_text: list[list[str]] = []
        self.has_content: list[bool] = []
        self._stack: list[tuple[str, int | None]] = []
        self._open_blocks: list[int] = []

    def handle_starttag(self, tag, attrs):
        if tag in _IMAGE_TAGS:
            self._mark_content()
        if tag == "br":
            self._add_text(" ")
        if tag in _VOID_TAGS:
            return
        index = None
        if tag in BLOCK_TAGS:
            index = len(self.own_text)
            self.own_text.append([])
            self.has_content.append(False)
            self._open_blocks.append(index)
        self._stack.append((tag, index))

    def handle_startendtag(self, tag, attrs):
        # A self-closed <img/>, <image/> or <br/>. A self-closed block tag gets
        # no id, as it never has.
        if tag in _IMAGE_TAGS:
            self._mark_content()
        if tag == "br":
            self._add_text(" ")

    def handle_endtag(self, tag):
        # Close back to the nearest open element of this name, so markup that
        # leaves an inner element unclosed still ends its blocks.
        for position in range(len(self._stack) - 1, -1, -1):
            if self._stack[position][0] != tag:
                continue
            for _tag, index in reversed(self._stack[position:]):
                if (
                    index is not None
                    and self._open_blocks
                    and self._open_blocks[-1] == index
                ):
                    self._open_blocks.pop()
            del self._stack[position:]
            return

    def handle_data(self, data):
        # Script and style text never shows on the page.
        if self._stack and self._stack[-1][0] in ("script", "style"):
            return
        self._add_text(data)
        if _visible_text(data):
            self._mark_content()

    def _add_text(self, text):
        if self._open_blocks:
            self.own_text[self._open_blocks[-1]].append(text)

    def _mark_content(self):
        for index in self._open_blocks:
            self.has_content[index] = True


class _BlockIdAssigner(HTMLParser):
    """Second pass: re-emits the HTML, marking each block the classifier sorted.

    A paragraph gets data-stid="bN"; a spacer gets data-st-spacer; any other
    block (a wrapper holding paragraphs, an image-only block) gets neither. The
    counter advances for every block, so a paragraph's id does not depend on
    which of its neighbours are spacers.

    A private data-stid marker (not id) is used so it cannot collide with the
    book's own id attributes. convert_charrefs is off and refs are re-emitted
    verbatim so the output is a faithful, deterministic copy of the input."""

    def __init__(self, paragraphs: list[bool], spacers: list[bool]):
        super().__init__(convert_charrefs=False)
        self.parts: list[str] = []
        self.ids: list[str] = []
        # The block index of each id, to look its text up afterwards.
        self.indices: list[int] = []
        self._counter = 0
        self._paragraphs = paragraphs
        self._spacers = spacers

    def handle_starttag(self, tag, attrs):
        if tag in BLOCK_TAGS:
            index = self._counter
            self._counter += 1
            if self._paragraphs[index]:
                new_id = f"b{index}"
                self.ids.append(new_id)
                self.indices.append(index)
                attrs = attrs + [("data-stid", new_id)]
            elif self._spacers[index]:
                attrs = attrs + [("data-st-spacer", None)]
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


def assign_block_ids(body_html: str) -> tuple[str, list[str], list[str]]:
    """Mark the block elements of a book body.

    Each paragraph (a block with visible text of its own) gets data-stid="bN",
    where N counts every block element in document order; each spacer (a block
    with no visible text and no image anywhere inside) gets data-st-spacer.
    Return the marked HTML, the paragraph ids in document order, and each
    paragraph's visible own text."""
    classifier = _BlockClassifier()
    classifier.feed(body_html)
    classifier.close()
    texts = [_visible_text("".join(parts)) for parts in classifier.own_text]
    paragraphs = [bool(text) for text in texts]
    spacers = [not content for content in classifier.has_content]
    assigner = _BlockIdAssigner(paragraphs, spacers)
    assigner.feed(body_html)
    assigner.close()
    return (
        "".join(assigner.parts),
        assigner.ids,
        [texts[index] for index in assigner.indices],
    )


_CONTAINER_PATH = "META-INF/container.xml"
_OPF_NS = {"opf": "http://www.idpf.org/2007/opf"}
_DC_NS = {"dc": "http://purl.org/dc/elements/1.1/"}
_CONTAINER_NS = {"c": "urn:oasis:names:tc:opendocument:xmlns:container"}


def _extract_body(xhtml: str) -> str:
    """Return the inner HTML of the <body> element, or the whole string if none."""
    match = re.search(r"<body[^>]*>(.*)</body>", xhtml, re.IGNORECASE | re.DOTALL)
    return match.group(1) if match else xhtml


# Matches a resource reference attribute: src=, href= or xlink:href= (the EPUB
# cover is often an SVG <image xlink:href=...>), single or double quoted.
_RESOURCE_REF_RE = re.compile(
    r'(src|href|xlink:href)\s*=\s*(["\'])(.*?)\2', re.IGNORECASE
)

# Only image refs are rewritten and extracted. Stylesheet/script hrefs are left
# alone (the reader does not use the book's CSS or scripts).
_IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp", ".bmp")


def _resolve_epub_ref(doc_dir: str, ref: str) -> str | None:
    """Resolve a chapter-relative ref to an EPUB-root-relative path, or None for
    refs that must not be rewritten (absolute URLs, data URIs, in-page anchors,
    root-absolute paths)."""
    if not ref or ref.startswith(("http:", "https:", "data:", "#", "/")):
        return None
    if doc_dir in ("", "."):
        return posixpath.normpath(ref)
    return posixpath.normpath(posixpath.join(doc_dir, ref))


def _rewrite_image_refs(
    body: str, doc_dir: str, available: set[str]
) -> tuple[str, set[str]]:
    """Rewrite a chapter body's image refs from chapter-relative to
    EPUB-root-relative, collecting the resources actually referenced.

    The book is read as one document concatenated at the EPUB root, so a ref
    like ``../Images/x.jpeg`` from a chapter in ``OEBPS/Text/`` is rewritten to
    ``OEBPS/Images/x.jpeg`` (its path from the root). Only image refs that
    resolve to a file present in the archive are rewritten; anything else is
    left untouched. Returns the rewritten body and the set of root-relative
    image paths it uses."""
    used: set[str] = set()

    def repl(match: re.Match) -> str:
        attr, quote, ref = match.group(1), match.group(2), match.group(3)
        if not ref.lower().endswith(_IMAGE_SUFFIXES):
            return match.group(0)
        target = _resolve_epub_ref(doc_dir, ref)
        if target is None or target not in available:
            return match.group(0)
        used.add(target)
        return f"{attr}={quote}{target}{quote}"

    return _RESOURCE_REF_RE.sub(repl, body), used


def _load_epub(path: str) -> tuple[str, str, dict[str, bytes]]:
    with zipfile.ZipFile(path) as z:
        container = ElementTree.fromstring(z.read(_CONTAINER_PATH))
        rootfile = container.find(".//c:rootfile", _CONTAINER_NS)
        opf_path = rootfile.get("full-path")
        opf_dir = posixpath.dirname(opf_path)

        opf = ElementTree.fromstring(z.read(opf_path))
        title_el = opf.find(".//dc:title", _DC_NS)
        title = title_el.text if title_el is not None and title_el.text else Path(path).stem

        # Map manifest id -> href.
        manifest = {}
        for item in opf.findall(".//opf:manifest/opf:item", _OPF_NS):
            manifest[item.get("id")] = item.get("href")

        # The archive's file list, so a rewrite only targets refs that resolve
        # to a real resource.
        available = set(z.namelist())

        bodies = []
        used_images: set[str] = set()
        for itemref in opf.findall(".//opf:spine/opf:itemref", _OPF_NS):
            href = manifest.get(itemref.get("idref"))
            if not href:
                continue
            full = href if not opf_dir or opf_dir == "." else f"{opf_dir}/{href}"
            doc_dir = posixpath.dirname(full)
            xhtml = z.read(full).decode("utf-8", errors="replace")
            body = _extract_body(xhtml)
            # Make each chapter's image paths relative to the EPUB root so they
            # resolve from one document concatenated at the temp-dir root.
            body, used = _rewrite_image_refs(body, doc_dir, available)
            used_images |= used
            bodies.append(body)

        images = {name: z.read(name) for name in sorted(used_images)}

    return "".join(bodies), title, images


def _load_pdf(path: str) -> tuple[str, str, dict[str, bytes]]:
    doc = pymupdf.open(path)
    try:
        bodies = []
        for page in doc:
            xhtml = page.get_text("xhtml")
            bodies.append(_extract_body(xhtml))
        title = doc.metadata.get("title") or Path(path).stem
    finally:
        doc.close()
    # pymupdf inlines page images as data: URIs, so there are no external image
    # resources to extract.
    return "".join(bodies), title, {}


def load_book(path: str) -> BookDocument:
    """Load a book file to normalised HTML with block ids. Raises ValueError on
    an unsupported or unreadable file."""
    suffix = Path(path).suffix.lower()
    if suffix == ".epub":
        body, title, images = _load_epub(path)
    elif suffix == ".pdf":
        body, title, images = _load_pdf(path)
    else:
        raise ValueError(f"Unsupported book format: {path}")
    html, ids, texts = assign_block_ids(body)
    return BookDocument(
        html=html, block_ids=ids, title=title, images=images, block_texts=texts
    )
