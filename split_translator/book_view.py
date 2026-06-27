"""A single book edition rendered in a web view, with scroll position exposed as
content coordinates (a block id plus a fraction toward the next block)."""

import json

from PySide6.QtCore import QUrl, Signal
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
from PySide6.QtWebEngineWidgets import QWebEngineView

from .book_loader import BookDocument

# Reports the topmost visible block id and how far the viewport top has scrolled
# from it toward the next block (0.0 at its top, approaching 1.0 at the next).
# Returns a JSON string: runJavaScript delivers a bare JS object as an empty
# string, so the payload must be stringified and parsed back in Python.
_SCROLL_STATE_JS = """
(function() {
    var blocks = Array.prototype.slice.call(
        document.querySelectorAll('[data-stid]'));
    if (!blocks.length) return JSON.stringify({id: "", fraction: 0});
    var y = window.scrollY;
    var current = blocks[0];
    for (var i = 0; i < blocks.length; i++) {
        if (blocks[i].offsetTop <= y) current = blocks[i];
        else break;
    }
    var idx = blocks.indexOf(current);
    var top = current.offsetTop;
    var nextTop = (idx + 1 < blocks.length)
        ? blocks[idx + 1].offsetTop
        : document.body.scrollHeight;
    var span = nextTop - top;
    var fraction = span > 0 ? (y - top) / span : 0;
    if (fraction < 0) fraction = 0;
    if (fraction > 1) fraction = 1;
    return JSON.stringify({
        id: current.getAttribute("data-stid"), fraction: fraction
    });
})();
"""

_SCROLL_TO_JS = """
(function() {
    var el = document.querySelector('[data-stid=' + %(id)s + ']');
    if (!el) return;
    var blocks = Array.prototype.slice.call(
        document.querySelectorAll('[data-stid]'));
    var idx = blocks.indexOf(el);
    var top = el.offsetTop;
    var nextTop = (idx + 1 < blocks.length)
        ? blocks[idx + 1].offsetTop
        : document.body.scrollHeight;
    var target = top + %(fraction)s * (nextTop - top);
    window.scrollTo(0, target);
})();
"""


class BookView(QWebEngineView):
    """Renders one edition's HTML; exposes scroll position as (block_id, fraction)."""

    scrolled = Signal(str, float)

    def __init__(
        self,
        document: BookDocument,
        profile: QWebEngineProfile,
        parent=None,
    ):
        super().__init__(parent)
        self._document = document
        self._suppress_scroll = False
        self.setPage(QWebEnginePage(profile, self))
        self.setHtml(document.html, QUrl("about:blank"))

    def request_scroll_state(self) -> None:
        """Read the current scroll position and emit `scrolled`."""
        if self._suppress_scroll:
            return
        self.page().runJavaScript(_SCROLL_STATE_JS, self._on_scroll_state)

    def _on_scroll_state(self, payload) -> None:
        if not payload:
            return
        data = json.loads(payload)
        block_id = data.get("id", "")
        if block_id:
            self.scrolled.emit(block_id, float(data.get("fraction", 0.0)))

    def scroll_to(self, block_id: str, fraction: float) -> None:
        """Scroll so the viewport top sits `fraction` from `block_id` toward the
        next block. Suppresses the echoed scroll event briefly."""
        self._suppress_scroll = True
        js = _SCROLL_TO_JS % {
            "id": json.dumps(block_id),
            "fraction": float(fraction),
        }
        self.page().runJavaScript(js, lambda _=None: self._release_suppress())

    def _release_suppress(self) -> None:
        self._suppress_scroll = False

    def find(self, term: str, forward: bool, callback) -> None:
        """Run a native find; report the match count to callback(int)."""
        flags = QWebEnginePage.FindFlag(0)
        if not forward:
            flags |= QWebEnginePage.FindFlag.FindBackward

        def _on_result(result):
            callback(result.numberOfMatches())

        self.page().findText(term, flags, _on_result)
