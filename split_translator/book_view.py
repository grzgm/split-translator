"""A single book edition rendered in a web view, with scroll position exposed as
content coordinates (a block id plus a fraction toward the next block)."""

import json

from PySide6.QtCore import Signal
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
from PySide6.QtWebEngineWidgets import QWebEngineView

from .book_loader import BookDocument
from .book_render import RenderedBook

# Reports the block at the viewport CENTRE and how far the centre has scrolled
# through it (0.0 at its top, approaching 1.0 at the next block). The centre, not
# the top edge, is the reading position: aligning what the reader is looking at
# (mid-screen) keeps the two editions matched even though their paragraphs differ
# in length, whereas aligning the top edge only ever lines up the top line.
# Returns a JSON string: runJavaScript delivers a bare JS object as an empty
# string, so the payload must be stringified and parsed back in Python.
_SCROLL_STATE_JS = """
(function() {
    var blocks = Array.prototype.slice.call(
        document.querySelectorAll('[data-stid]'));
    if (!blocks.length) return JSON.stringify({id: "", fraction: 0});
    var anchorY = window.scrollY + window.innerHeight / 2;
    var current = blocks[0];
    for (var i = 0; i < blocks.length; i++) {
        if (blocks[i].offsetTop <= anchorY) current = blocks[i];
        else break;
    }
    var idx = blocks.indexOf(current);
    var top = current.offsetTop;
    var nextTop = (idx + 1 < blocks.length)
        ? blocks[idx + 1].offsetTop
        : document.body.scrollHeight;
    var span = nextTop - top;
    var fraction = span > 0 ? (anchorY - top) / span : 0;
    if (fraction < 0) fraction = 0;
    if (fraction > 1) fraction = 1;
    return JSON.stringify({
        id: current.getAttribute("data-stid"), fraction: fraction
    });
})();
"""

# Scrolls so the given block-and-fraction point sits at the viewport CENTRE, the
# inverse of _SCROLL_STATE_JS: the point that was mid-screen in the source is put
# mid-screen here. Subtracting half the viewport height converts the point's
# document position into a scrollY.
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
    var point = top + %(fraction)s * (nextTop - top);
    window.scrollTo(0, point - window.innerHeight / 2);
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

# Injected once per load: adds the search-block overlay style. The reader marks
# the section holding the current find match (and its anchor-equivalent in the
# other edition) by toggling this class. The class name is distinct from the
# anchor editor's classes so the two never clash if a view ever carries both.
_SEARCH_STYLE_JS = """
(function() {
    if (document.getElementById('st-search-style')) return;
    var style = document.createElement('style');
    style.id = 'st-search-style';
    style.textContent =
        '.st-search-block { background: #fff3a8; outline: 2px solid #e0b400; }';
    (document.head || document.documentElement).appendChild(style);
})();
"""

# Toggles the search-block class. Self-contained (no dependency on a pre-injected
# helper), so a mark or clear issued before the style injection still works; it
# just lacks the colour until the style lands on load. %(id)s is a JSON-quoted
# block id, or '""' to only clear.
_MARK_BLOCK_JS = """
(function(id) {
    var els = document.querySelectorAll('.st-search-block');
    for (var i = 0; i < els.length; i++) {
        els[i].classList.remove('st-search-block');
    }
    if (!id) return;
    var el = document.querySelector('[data-stid=' + JSON.stringify(id) + ']');
    if (el) el.classList.add('st-search-block');
})(%(id)s);
"""

# Finds the block holding the Nth find match (1-based, the find result's
# activeMatch). findText does not update window.getSelection (Chromium highlights
# via the find controller, not the DOM selection), so the match block is located
# by counting term occurrences across blocks in document order and returning the
# block whose running count first reaches the target index. This is independent
# of the live scroll position: on a wrap-around the findText callback fires while
# the scroll is still at the old place, so a scrollY-based guess would pick the
# wrong block (and miss the first occurrence entirely). %(term)s is a JSON-quoted
# search string; %(index)s is the 1-based match index.
_MATCH_BLOCK_JS = """
(function(term, index) {
    if (!term || index < 1) return "";
    term = term.toLowerCase();
    var blocks = Array.prototype.slice.call(
        document.querySelectorAll('[data-stid]'));
    var seen = 0;
    for (var i = 0; i < blocks.length; i++) {
        var b = blocks[i];
        var text = (b.textContent || "").toLowerCase();
        if (!text) continue;
        var from = 0;
        var hit = text.indexOf(term, from);
        while (hit !== -1) {
            seen++;
            if (seen === index) return b.getAttribute("data-stid");
            from = hit + term.length;
            hit = text.indexOf(term, from);
        }
    }
    return "";
})(%(term)s, %(index)s);
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
        # Inject the search-block overlay helpers once the page loads, so a book
        # search can mark the section holding the current match. Connect before
        # loading so the signal is not missed.
        self.loadFinished.connect(self._inject_search_mark)
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

    def _inject_search_mark(self, ok: bool) -> None:
        # Add the overlay style on every successful load (idempotent: the style
        # element is added once). The mark/clear JS is self-contained, so it does
        # not depend on this having run.
        if not ok:
            return
        self.page().runJavaScript(_SEARCH_STYLE_JS)

    def mark_search_block(self, block_id: str) -> None:
        """Highlight the block holding the current search match (clears any prior
        mark first). An empty id just clears."""
        self.page().runJavaScript(_MARK_BLOCK_JS % {"id": json.dumps(block_id)})

    def clear_search_mark(self) -> None:
        """Remove the search-block highlight."""
        self.page().runJavaScript(_MARK_BLOCK_JS % {"id": '""'})

    def matched_block_id(self, term: str, index: int, callback) -> None:
        """Find the block holding the `index`-th (1-based) match for `term` and
        pass its id (or "") to callback(str). `index` is the find result's
        activeMatch; see _MATCH_BLOCK_JS for why the block is located by
        occurrence count rather than the live scroll (findText leaves no DOM
        selection to read, and its callback can fire before the scroll settles)."""
        js = _MATCH_BLOCK_JS % {"term": json.dumps(term), "index": int(index)}
        self.page().runJavaScript(js, lambda value: callback(value or ""))

    def find(self, term: str, forward: bool, callback) -> None:
        """Run a native find; report (active_match, total) to callback(int, int).
        active_match is the 1-based index of the highlighted match (0 when there
        is none), so the caller can number it absolutely and locate its block."""
        flags = QWebEnginePage.FindFlag(0)
        if not forward:
            flags |= QWebEnginePage.FindFlag.FindBackward

        def _on_result(result):
            callback(result.activeMatch(), result.numberOfMatches())

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
