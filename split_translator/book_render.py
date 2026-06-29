"""Render a loaded book to a file the web view can load by URL.

QWebEnginePage.setHtml (and setContent) load their argument as an internal
``data:`` URL, which Qt caps at ~2 MB *after* percent-encoding. A full novel's
HTML exceeds that, so setHtml silently fails: loadFinished fires with ok=False
and the view stays blank. Loading the same HTML from a ``file://`` URL has no
such limit, so each book is written to a private temp file and loaded from
there. The file also gives relative resources (EPUB cover/images) a real base
directory to resolve against.

The temp file is owned by ``RenderedBook`` and removed when it is released, so
nothing is left on disk and no machine path is ever persisted (anchors and
config store block ids, not paths)."""

import tempfile
import weakref
from pathlib import Path

from PySide6.QtCore import QUrl

from .book_loader import BookDocument

# A minimal, valid HTML wrapper. The loader concatenates body fragments, so the
# document has no <html>/<head> of its own; wrapping it declares UTF-8 (the
# fragments are decoded as UTF-8) and gives the browser a well-formed page.
_DOCUMENT_TEMPLATE = (
    "<!DOCTYPE html>\n"
    '<html><head><meta charset="utf-8"></head><body>\n'
    "{body}\n"
    "</body></html>\n"
)


def document_html(document: BookDocument) -> str:
    """Wrap a book's body fragment in a complete HTML document."""
    return _DOCUMENT_TEMPLATE.format(body=document.html)


def _remove_dir(path: Path) -> None:
    """Delete the temp file and its directory. Never raises: a leftover file in
    the OS temp dir is harmless and is reclaimed by the system."""
    try:
        for child in path.iterdir():
            child.unlink()
    except OSError:
        pass
    try:
        path.rmdir()
    except OSError:
        pass


class RenderedBook:
    """Owns one temp HTML file for a book and exposes it as a file:// URL.

    Cleanup is deterministic and does not depend on Qt: a ``weakref.finalize``
    deletes the temp directory when this object is garbage-collected (i.e. when
    the owning view is gone), and ``release()`` deletes it eagerly. Both are
    idempotent and the finalizer is disarmed once either has run."""

    def __init__(self, document: BookDocument):
        # A private per-book directory keeps the file isolated and lets a later
        # images change drop sibling resources beside it without name clashes.
        self._dir = Path(
            tempfile.mkdtemp(prefix="split-translator-book-")
        )
        self._path = self._dir / "book.html"
        self._path.write_text(document_html(document), encoding="utf-8")
        # Finalizer bound to the directory path only (no reference back to self),
        # so it does not keep this object alive and runs at GC even if release()
        # is never called.
        self._finalizer = weakref.finalize(self, _remove_dir, self._dir)

    @property
    def path(self) -> Path:
        return self._path

    def url(self) -> QUrl:
        """The file:// URL the web view loads."""
        return QUrl.fromLocalFile(str(self._path))

    def release(self) -> None:
        """Delete the temp file and its directory now. Safe to call repeatedly;
        also disarms the GC finalizer so it does not run again."""
        self._finalizer()
