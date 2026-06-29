"""A single book edition rendered in a web view, with scroll position exposed as
content coordinates (a block id plus a fraction toward the next block)."""

import json

from PySide6.QtCore import Signal
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
from PySide6.QtWebEngineWidgets import QWebEngineView

from .book_loader import BookDocument
from .book_render import RenderedBook

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

_TOPMOST_ID_JS = """
(function() {
    var blocks = Array.prototype.slice.call(
        document.querySelectorAll('[data-stid]'));
    if (!blocks.length) return "";
    var y = window.scrollY;
    var current = blocks[0];
    for (var i = 0; i < blocks.length; i++) {
        if (blocks[i].offsetTop <= y) current = blocks[i];
        else break;
    }
    return current.getAttribute("data-stid");
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
        initial_scroll: tuple[str, float] | None = None,
    ):
        super().__init__(parent)
        self._document = document
        self._suppress_scroll = False
        self._initial_scroll = initial_scroll
        # A pending (block_id, fraction) to re-apply once the layout settles. A
        # hidden tab lays out against a provisional height, so a scroll computed
        # then bakes a wrong pixel offset; this is re-run on the next reflow.
        self._pending_reapply: tuple[str, float] | None = None
        # The book HTML is loaded from a temp file, not setHtml: a full novel's
        # HTML is larger than setHtml's ~2 MB data-URL cap and would silently
        # fail to render (loadFinished ok=False, blank view). See book_render.
        # RenderedBook deletes its temp file when garbage-collected (a weakref
        # finalizer), so holding it on the view is enough; release_rendered()
        # lets the panel delete it eagerly on close.
        self._rendered = RenderedBook(document)
        self.setPage(QWebEnginePage(profile, self))
        # Restore the saved scroll position once the page has laid out: offsets
        # are only correct after load, so scrolling before loadFinished would
        # land at the top. Connect before loading so the signal is not missed.
        if initial_scroll is not None:
            self.loadFinished.connect(self._restore_initial_scroll)
        self.page().load(self._rendered.url())
        self.page().scrollPositionChanged.connect(self.request_scroll_state)
        # When a tab is shown, its content reflows to the now-correct width and
        # the page height settles; re-apply any pending scroll against that
        # settled layout (offsetTop/scrollHeight are wrong until then).
        self.page().contentsSizeChanged.connect(self._on_contents_size_changed)

    def _restore_initial_scroll(self, ok: bool) -> None:
        # Wait for a successful load before restoring: a failed (ok=False) load
        # leaves the handler connected so a later good load still restores.
        if not ok:
            return
        self.loadFinished.disconnect(self._restore_initial_scroll)
        if self._initial_scroll is None:
            return
        block_id, fraction = self._initial_scroll
        self.scroll_to(block_id, fraction)
        # Re-announce the restored position. The scroll_to above suppresses the
        # echoed scrollPositionChanged, so without this the only position a
        # listener (the panel's scroll cache) ever sees from load is the top of
        # the document, which would then be persisted on close, wiping the saved
        # spot. Emitting here keeps that cache at the genuine restored position.
        self.scrolled.emit(block_id, fraction)

    def request_scroll_state(self) -> None:
        """Read the current scroll position and emit `scrolled`."""
        if self._suppress_scroll:
            return
        # A scroll this view did not suppress is a genuine user scroll, so any
        # pending re-apply is stale: drop it rather than yank the user back on
        # the next reflow.
        self._pending_reapply = None
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

    def reapply_scroll(self, block_id: str, fraction: float) -> None:
        """Re-scroll to a cached position once this view is shown. Scrolls now
        as a best effort and re-runs on the next reflow, so the final offset is
        computed against the settled (visible) layout, not a stale hidden one."""
        self._pending_reapply = (block_id, fraction)
        self.scroll_to(block_id, fraction)

    def _on_contents_size_changed(self, _size) -> None:
        # Fires whenever the page height changes, including the reflow when a
        # hidden tab is shown. Re-run the pending scroll against the now-settled
        # layout. Cleared on the matching scrollPositionChanged, not here, so a
        # multi-step settle keeps re-applying until the height stops changing.
        if self._pending_reapply is None:
            return
        # Only scroll while this view is the visible tab. A reflow can fire on a
        # hidden tab (a window resize, or the tab being hidden again mid-settle);
        # scrolling then would bake a wrong offset against the provisional hidden
        # layout, the very fault this fix exists to avoid. The pending position
        # stays armed, so the next time the tab is shown it is re-applied.
        if not self.isVisible():
            return
        block_id, fraction = self._pending_reapply
        self.scroll_to(block_id, fraction)

    def find(self, term: str, forward: bool, callback) -> None:
        """Run a native find; report the match count to callback(int)."""
        flags = QWebEnginePage.FindFlag(0)
        if not forward:
            flags |= QWebEnginePage.FindFlag.FindBackward

        def _on_result(result):
            callback(result.numberOfMatches())

        self.page().findText(term, flags, _on_result)

    def topmost_block_id(self, callback) -> None:
        """Read the topmost visible block id and pass it to callback(str)."""
        self.page().runJavaScript(
            _TOPMOST_ID_JS, lambda value: callback(value or "")
        )

    def release_rendered(self) -> None:
        """Delete the backing temp file now (called on panel close). Cleanup
        also happens at garbage collection, so this is an eager convenience."""
        self._rendered.release()
