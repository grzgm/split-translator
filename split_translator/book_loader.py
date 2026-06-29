"""Loads a book file (PDF or EPUB) into normalised HTML with stable block ids.

Pure logic, no Qt. EPUB is unzipped and its spine HTML concatenated; PDF is
converted with pymupdf. A single pass then assigns data-stid="b0", "b1", ... to each
block-level element in document order, so saved anchors stay valid across
sessions (same file in, same ids out)."""

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
    """A book rendered to HTML with anchorable block ids in document order.

    ``images`` maps an EPUB-root-relative resource path (the same path the HTML
    now references) to its bytes, so the renderer can lay the images out beside
    the HTML and they resolve over file://. Empty for PDFs (pymupdf inlines
    images) and image-less books."""

    html: str
    block_ids: list[str]
    title: str
    images: dict[str, bytes] = field(default_factory=dict)


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
    html, ids = assign_block_ids(body)
    return BookDocument(html=html, block_ids=ids, title=title, images=images)
