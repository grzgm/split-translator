"""A single book edition rendered in a web view, with scroll positions exposed as
a paragraph position (a paragraph id plus a fraction toward the next paragraph)
and a section position (a section index plus a share of its height)."""

import json

from PySide6.QtCore import Signal
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
from PySide6.QtWebEngineWidgets import QWebEngineView

from .book_loader import BookDocument
from .book_render import RenderedBook
from .normalise_spec import NormaliseSpec

# Shared by the section scripts. A section start is a paragraph element or one
# of two markers: 'top' for the document top and 'end' for the document end.
# Positions are read live from the layout, so a resize or a Normalise change
# needs nothing extra. getBoundingClientRect plus scrollY is the element's
# document position even inside a positioned wrapper, where offsetTop is not.
_SECTION_GEOMETRY_JS = """
    function __stTop(mark) {
        if (mark === 'top') return 0;
        if (mark === 'end') return document.documentElement.scrollHeight;
        return mark.getBoundingClientRect().top + window.scrollY;
    }
    function __stHeight(marks, k) {
        var next = k + 1 < marks.length
            ? __stTop(marks[k + 1])
            : document.documentElement.scrollHeight;
        return Math.max(0, next - __stTop(marks[k]));
    }
"""

# Stores the section starts, in document order, for the two scripts below. The
# ids are looked up once here, through one pass over the paragraphs, rather
# than once per scroll. %(starts)s is a JSON list of paragraph ids and markers.
_SET_SECTIONS_JS = """
(function(starts) {
    var byId = {};
    var blocks = document.querySelectorAll('[data-stid]');
    for (var i = 0; i < blocks.length; i++) {
        byId[blocks[i].getAttribute('data-stid')] = blocks[i];
    }
    var marks = [];
    for (var j = 0; j < starts.length; j++) {
        var start = starts[j];
        marks.push(start === 'top' || start === 'end'
            ? start : (byId[start] || 'end'));
    }
    window.__stSections = marks;
})(%(starts)s);
"""

# Reports the viewport CENTRE twice. The paragraph position is the paragraph the
# centre is in and how far the centre has passed through the span to the next
# paragraph (0.0 at its top); saved reading positions use it. The section
# position is the section the centre is in (the last start at or above it, so
# a section with no height is passed over) and the share of that section's
# height the centre has passed; sync hands it to the other edition unchanged.
# The section is -1 until the section starts have been set.
# The centre, not the top edge, is the reading position: aligning what the
# reader is looking at keeps the editions matched even though their paragraphs
# differ in length. Returns a JSON string: runJavaScript delivers a bare JS
# object as an empty string.
_SCROLL_STATE_JS = """
(function() {
    __SECTION_GEOMETRY__
    var anchorY = window.scrollY + window.innerHeight / 2;
    var section = -1;
    var share = 0;
    var marks = window.__stSections;
    if (marks && marks.length) {
        var lo = 0;
        var hi = marks.length - 1;
        while (lo < hi) {
            var mid = Math.ceil((lo + hi) / 2);
            if (__stTop(marks[mid]) <= anchorY) lo = mid;
            else hi = mid - 1;
        }
        section = lo;
        var height = __stHeight(marks, lo);
        share = height > 0 ? (anchorY - __stTop(marks[lo])) / height : 0;
        if (share < 0) share = 0;
        if (share > 1) share = 1;
    }
    var blocks = Array.prototype.slice.call(
        document.querySelectorAll('[data-stid]'));
    if (!blocks.length) {
        return JSON.stringify(
            {id: "", fraction: 0, section: section, share: share});
    }
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
        id: current.getAttribute("data-stid"), fraction: fraction,
        section: section, share: share
    });
})();
""".replace("__SECTION_GEOMETRY__", _SECTION_GEOMETRY_JS)

# Scrolls so a section position sits at the viewport centre, the inverse of
# the section half of _SCROLL_STATE_JS. Does nothing until the section starts
# are set, or for a section the page does not have.
_SCROLL_TO_SECTION_JS = """
(function(section, share) {
    __SECTION_GEOMETRY__
    var marks = window.__stSections;
    if (!marks || section < 0 || section >= marks.length) return;
    var point = __stTop(marks[section]) + share * __stHeight(marks, section);
    window.scrollTo(0, point - window.innerHeight / 2);
})(%(section)s, %(share)s);
""".replace("__SECTION_GEOMETRY__", _SECTION_GEOMETRY_JS)

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
# the paragraph holding the current find match (and its counterpart paragraphs in
# the other edition) by toggling this class. The class name is distinct from the
# anchor editor's classes so the two never clash if a view ever carries both.
#: How the paragraph holding the current search match is marked, in the reader
#: and in the anchor editor's find bars alike (see anchor_book_view).
SEARCH_MARK_STYLE = "background: #fff3a8; outline: 2px solid #e0b400;"

_SEARCH_STYLE_JS = """
(function() {
    if (document.getElementById('st-search-style')) return;
    var style = document.createElement('style');
    style.id = 'st-search-style';
    style.textContent =
        '.st-search-block { __SEARCH_MARK_STYLE__ }';
    (document.head || document.documentElement).appendChild(style);
})();
""".replace("__SEARCH_MARK_STYLE__", SEARCH_MARK_STYLE)

# The paragraph-spacing normalisation rules live in normalise_spec, which builds
# them from one edition's multipliers; see that module for why the app levels
# spacing at all. Blank spacer blocks need no work in the page: the loader marks
# them data-st-spacer and the stylesheet collapses them (see book_loader).

# Injected on every load, on every toggle, and on every spec change. Adds the
# normalisation style element once (idempotent), sets its text to %(css)s (the
# JSON-quoted rule text) and its enabled state from %(enabled)s (a JS boolean),
# so a later toggle or spec change just rewrites the element's text and/or
# flips its `disabled` flag: no reload or re-render, the scroll position is kept.
_NORMALISE_STYLE_JS = """
(function(css, enabled) {
    var style = document.getElementById('st-normalise-style');
    if (!style) {
        style = document.createElement('style');
        style.id = 'st-normalise-style';
        (document.head || document.documentElement).appendChild(style);
    }
    // Reassigned on every call, not only on create: a normalisation spec change
    // comes through this same injection, and would otherwise keep the first
    // stylesheet forever.
    style.textContent = css;
    style.disabled = !enabled;
})(%(css)s, %(enabled)s);
"""

# Toggles the search-block class: clears every mark, then marks each given
# paragraph. Self-contained (no dependency on a pre-injected helper), so a mark
# or clear issued before the style injection still works; it just lacks the
# colour until the style lands on load. %(ids)s is a JSON list of paragraph
# ids, empty to only clear.
_MARK_BLOCKS_JS = """
(function(ids) {
    var els = document.querySelectorAll('.st-search-block');
    for (var i = 0; i < els.length; i++) {
        els[i].classList.remove('st-search-block');
    }
    for (var j = 0; j < ids.length; j++) {
        var el = document.querySelector(
            '[data-stid=' + JSON.stringify(ids[j]) + ']');
        if (el) el.classList.add('st-search-block');
    }
})(%(ids)s);
"""

# The text a search match can be counted in, split into *runs*. A run is a
# stretch of text belonging to one tagged block: it starts where that block's
# text starts and ends where a nested block interrupts it. Every character of
# the page belongs to exactly one run, the run of its nearest tagged ancestor;
# text with no tagged ancestor at all forms a run with an empty id, which
# marks nothing.
#
# That one-character-one-run property is the whole point, because the running
# count has to track Chromium's activeMatch. Book markup nests block elements (a
# chapter <div> around the paragraphs, a <blockquote> or <li> around a <p>) and
# the loader tags every block with text of its own, nested or not (see
# book_loader.assign_block_ids), so a tagged block's textContent can already
# contain its children's. Two earlier rules each broke the property in one
# direction:
#
#   - Walking every [data-stid] and reading textContent counted a nested match
#     once per ancestor as well as in its own paragraph. The count overtook
#     Chromium's, reached the target index early, and returned a wrapper whose
#     highlight starts higher up the page than the paragraph that matched.
#   - Counting only the leaf blocks fixed that and opened the mirror hole. A
#     block can hold text of its own *and* a nested block (Children of Dune ends
#     a paragraph div with a nested div carrying the song that follows it), and
#     that own text sits in no leaf. Chromium still found it, so the match was
#     highlighted with nothing marked, and every later match was pulled one
#     place forward onto the wrong paragraph.
#
# Text nodes are visited in document order and consecutive nodes with the same
# owning block join, so a leaf block still yields exactly its textContent and
# nothing about the common case changes. SCRIPT and STYLE text is skipped:
# Chromium's find does not match it, and counting it would put the count out of
# step again.
#
# Anchors are unaffected: every block with text of its own keeps its id, and an
# id's number never depends on its untagged neighbours. This narrows what is
# *counted for search*, not what exists.
# Folds typographic quotes and apostrophes to their ASCII forms, so a term typed
# on a keyboard matches a book that was typeset with curly ones. Chromium's own
# find-in-page does this, which is why a search for "brother's body" highlights
# the phrase in a book that actually contains "brother\\u2019s body". Counting the
# same match here with a plain indexOf found nothing, so the section mark was
# cleared while the phrase stayed highlighted.
#
# Every mapping is one character to one character, so offsets into the folded
# text still address the original string. _MATCH_SENTENCE_JS depends on that: it
# locates the match in the folded text but slices the raw text, which keeps the
# book's real typography in the extracted sentence.
_FOLD_JS = """
    function __fold(s) {
        return s.replace(/[\\u2018\\u2019\\u201A\\u201B\\u02BC\\u2032]/g, "'")
                .replace(/[\\u201C\\u201D\\u201E\\u201F\\u2033]/g, '"');
    }
"""

_TEXT_RUNS_JS = """
    var runs = [];
    var walker = document.createTreeWalker(
        document.body, NodeFilter.SHOW_TEXT, null);
    for (var node = walker.nextNode(); node; node = walker.nextNode()) {
        var parent = node.parentNode;
        if (!parent) continue;
        var tag = parent.nodeName;
        if (tag === 'SCRIPT' || tag === 'STYLE') continue;
        // The nearest tagged ancestor owns this text. Untagged inline elements
        // (a <span>, an <i>) are walked straight through, which is what keeps a
        // leaf block's runs identical to its textContent.
        var owner = parent;
        while (owner && (!owner.getAttribute
                         || owner.getAttribute('data-stid') === null)) {
            owner = owner.parentNode;
        }
        var id = owner ? owner.getAttribute('data-stid') : "";
        var last = runs.length ? runs[runs.length - 1] : null;
        if (last && last.id === id) {
            last.text += node.nodeValue;
        } else {
            runs.push({id: id, text: node.nodeValue});
        }
    }
"""

# Finds the block holding the Nth find match (1-based, the find result's
# activeMatch). findText does not update window.getSelection (Chromium highlights
# via the find controller, not the DOM selection), so the match block is located
# by counting term occurrences across the text runs in document order and
# returning the owner of the run whose running count first reaches the target
# index. This is
# independent of the live scroll position: on a wrap-around the findText callback
# fires while the scroll is still at the old place, so a scrollY-based guess would
# pick the wrong block (and miss the first occurrence entirely). %(term)s is a
# JSON-quoted search string; %(index)s is the 1-based match index.
_MATCH_BLOCK_JS = """
(function(term, index) {
    if (!term || index < 1) return "";
    __FOLD__
    term = __fold(term.toLowerCase());
    __TEXT_RUNS__
    var seen = 0;
    for (var i = 0; i < runs.length; i++) {
        var text = __fold(runs[i].text.toLowerCase());
        if (!text) continue;
        var from = 0;
        var hit = text.indexOf(term, from);
        while (hit !== -1) {
            seen++;
            if (seen === index) return runs[i].id;
            from = hit + term.length;
            hit = text.indexOf(term, from);
        }
    }
    return "";
})(%(term)s, %(index)s);
""".replace("__TEXT_RUNS__", _TEXT_RUNS_JS).replace("__FOLD__", _FOLD_JS)

# Extracts the sentence containing the Nth find match (1-based activeMatch).
# Locates the match the same way as _MATCH_BLOCK_JS (findText leaves no DOM
# selection to read, so occurrences are counted across the text runs in document
# order until the running count reaches the target index), then within that run
# expands from the match offset to the surrounding sentence boundaries. A boundary
# is a '.', '!' or '?' followed by whitespace; if none is found on a side the run
# edge is used. Runs matter twice over here: a block's textContent runs its own
# text straight into any nested block's, so expanding to a sentence inside it
# would splice text across a paragraph break. Returns a JSON string (a bare object
# arrives empty from runJavaScript). %(term)s is a JSON-quoted search string;
# %(index)s is the 1-based match index.
_MATCH_SENTENCE_JS = """
(function(term, index) {
    if (!term || index < 1) return JSON.stringify({sentence: ""});
    __FOLD__
    var needle = __fold(term.toLowerCase());
    __TEXT_RUNS__
    var seen = 0;
    for (var i = 0; i < runs.length; i++) {
        var raw = runs[i].text;
        // Folded for locating the match; raw is what gets sliced, so the
        // extracted sentence keeps the book's own quotes and apostrophes.
        var text = __fold(raw.toLowerCase());
        if (!text) continue;
        var from = 0;
        var hit = text.indexOf(needle, from);
        while (hit !== -1) {
            seen++;
            if (seen === index) {
                var start = 0;
                for (var s = hit - 1; s > 0; s--) {
                    var c = raw.charAt(s - 1);
                    if ((c === '.' || c === '!' || c === '?')
                            && /\\s/.test(raw.charAt(s))) {
                        start = s + 1;
                        break;
                    }
                }
                var end = raw.length;
                for (var e = hit + needle.length; e < raw.length; e++) {
                    var d = raw.charAt(e);
                    if ((d === '.' || d === '!' || d === '?')) {
                        var after = raw.charAt(e + 1);
                        if (after === '' || /\\s/.test(after)) {
                            end = e + 1;
                            break;
                        }
                    }
                }
                var sentence = raw.substring(start, end).trim();
                return JSON.stringify({sentence: sentence});
            }
            from = hit + needle.length;
            hit = text.indexOf(needle, from);
        }
    }
    return JSON.stringify({sentence: ""});
})(%(term)s, %(index)s);
""".replace("__TEXT_RUNS__", _TEXT_RUNS_JS).replace("__FOLD__", _FOLD_JS)


class BookView(QWebEngineView):
    """Renders one edition's HTML; reports scroll positions as a paragraph position and a section position."""

    # Paragraph id, share of the span to the next paragraph, section index
    # (-1 when unknown), share of that section's height. See _SCROLL_STATE_JS.
    scrolled = Signal(str, float, int, float)

    def __init__(
        self,
        document: BookDocument,
        profile: QWebEngineProfile,
        parent=None,
        initial_scroll: tuple[str, float] | None = None,
        normalise: bool = False,
        spec: NormaliseSpec | None = None,
    ):
        super().__init__(parent)
        self._document = document
        self._suppress_scroll = False
        self._initial_scroll = initial_scroll
        # Whether paragraph-spacing normalisation is on. Applied on every load and
        # toggled live via set_normalise; see normalise_spec.
        self._normalise = normalise
        # This edition's normalisation multipliers. Independent of the flag
        # above: the flag says whether normalisation applies at all, the spec
        # says what it does when it does. Replaced live by set_normalise_spec.
        self._normalise_spec = spec or NormaliseSpec()
        # A pending (block_id, fraction) to re-apply once the layout settles. A
        # hidden tab lays out against a provisional height, so a scroll computed
        # then bakes a wrong pixel offset; this is re-run on the next reflow.
        self._pending_reapply: tuple[str, float] | None = None
        # A pending section position to re-apply once the layout settles, the
        # section counterpart of _pending_reapply. At most one of the two is set.
        self._pending_section: tuple[int, float] | None = None
        # The section starts this page measures against, re-sent on every load
        # because a page forgets them when it reloads. Empty until set.
        self._section_starts: list[str] = []
        # The book HTML is loaded from a temp file, not setHtml: a full novel's
        # HTML is larger than setHtml's ~2 MB data-URL cap and would silently
        # fail to render (loadFinished ok=False, blank view). See book_render.
        # RenderedBook deletes its temp file when garbage-collected (a weakref
        # finalizer), so holding it on the view is enough; release_rendered()
        # lets the panel delete it eagerly on close.
        self._rendered = RenderedBook(document)
        self.setPage(QWebEnginePage(profile, self))
        # Inject the search-block overlay helpers once the page loads, so a book
        # search can mark the paragraph holding the current match. Connect before
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
        # A restored position has no section (-1), so it is recorded but never
        # mirrored.
        self.scrolled.emit(block_id, fraction, -1, 0.0)

    def request_scroll_state(self) -> None:
        """Read the current scroll position and emit `scrolled`."""
        if self._suppress_scroll:
            return
        # A scroll this view did not suppress is a genuine user scroll, so any
        # pending re-apply is stale: drop it rather than yank the user back on
        # the next reflow.
        self._pending_reapply = None
        self._pending_section = None
        self.page().runJavaScript(_SCROLL_STATE_JS, self._on_scroll_state)

    def _on_scroll_state(self, payload) -> None:
        if not payload:
            return
        data = json.loads(payload)
        block_id = data.get("id", "")
        if block_id:
            self.scrolled.emit(
                block_id,
                float(data.get("fraction", 0.0)),
                int(data.get("section", -1)),
                float(data.get("share", 0.0)),
            )

    def scroll_to(self, block_id: str, fraction: float) -> None:
        """Scroll so the point `fraction` from `block_id` toward the next block
        sits at the viewport centre. Suppresses the echoed scroll event briefly."""
        self._suppress_scroll = True
        js = _SCROLL_TO_JS % {
            "id": json.dumps(block_id),
            "fraction": float(fraction),
        }
        self.page().runJavaScript(js, lambda _=None: self._release_suppress())

    def _release_suppress(self) -> None:
        self._suppress_scroll = False

    def scroll_to_section(self, section: int, share: float) -> None:
        """Scroll so `share` of section `section`'s height sits at the viewport
        centre. Suppresses the echoed scroll event briefly, like scroll_to."""
        self._suppress_scroll = True
        js = _SCROLL_TO_SECTION_JS % {
            "section": int(section),
            "share": float(share),
        }
        self.page().runJavaScript(js, lambda _=None: self._release_suppress())

    def reapply_scroll(self, block_id: str, fraction: float) -> None:
        """Re-scroll to a cached position once this view is shown. Scrolls now
        as a best effort and re-runs on the next reflow, so the final offset is
        computed against the settled (visible) layout, not a stale hidden one."""
        self._pending_reapply = (block_id, fraction)
        self._pending_section = None
        self.scroll_to(block_id, fraction)

    def reapply_section(self, section: int, share: float) -> None:
        """Re-scroll to a section position once this view is shown: now as a
        best effort, and again on the next reflow, like reapply_scroll."""
        self._pending_section = (section, share)
        self._pending_reapply = None
        self.scroll_to_section(section, share)

    def _on_contents_size_changed(self, _size) -> None:
        # Fires whenever the page height changes, including the reflow when a
        # hidden tab is shown. Re-run the pending scroll or section position
        # against the now-settled layout. Cleared on the matching
        # scrollPositionChanged, not here, so a multi-step settle keeps
        # re-applying until the height stops changing.
        if self._pending_reapply is None and self._pending_section is None:
            return
        # Only scroll while this view is the visible tab. A reflow can fire on a
        # hidden tab (a window resize, or the tab being hidden again mid-settle);
        # scrolling then would bake a wrong offset against the provisional hidden
        # layout, the very fault this fix exists to avoid. The pending position
        # stays armed, so the next time the tab is shown it is re-applied.
        if not self.isVisible():
            return
        if self._pending_reapply is not None:
            block_id, fraction = self._pending_reapply
            self.scroll_to(block_id, fraction)
        else:
            section, share = self._pending_section
            self.scroll_to_section(section, share)

    def _inject_search_mark(self, ok: bool) -> None:
        # Add the overlay style on every successful load (idempotent: the style
        # element is added once). The mark/clear JS is self-contained, so it does
        # not depend on this having run.
        if not ok:
            return
        self.page().runJavaScript(_SEARCH_STYLE_JS)
        # Re-apply the current normalisation state on every load, so a reload (or
        # the initial load) keeps the setting rather than reverting to the book's
        # raw spacing.
        self._apply_normalise()
        # A load replaces the page, and the section starts with it.
        if self._section_starts:
            self._apply_sections()

    def _apply_normalise(self) -> None:
        # Inject (once) the normalisation style element, set its text from this
        # edition's spec and its enabled state from self._normalise. Safe to call
        # before the page has loaded: the IIFE creates the element on first run
        # and only rewrites it after.
        js = _NORMALISE_STYLE_JS % {
            "css": json.dumps(self._normalise_spec.css()),
            "enabled": "true" if self._normalise else "false",
        }
        self.page().runJavaScript(js)

    def set_normalise(self, enabled: bool) -> None:
        """Turn paragraph-spacing normalisation on or off live. Flips the injected
        style element's `disabled` flag; no reload or re-render, so the scroll
        position is kept."""
        self._normalise = bool(enabled)
        self._apply_normalise()

    def set_normalise_spec(self, spec: NormaliseSpec) -> None:
        """Give this edition new normalisation multipliers live. Rewrites the
        injected style element's text; no reload or re-render, so the scroll
        position is kept, exactly like set_normalise. Leaves the on/off flag
        alone: a spec change on a view with normalisation off is stored and
        takes effect when it is switched back on."""
        self._normalise_spec = spec
        self._apply_normalise()

    def set_sections(self, starts: list[str]) -> None:
        """Give the page the section starts it measures against (see
        book_sync.SectionMap.section_starts). Live, no reload; remembered and
        re-sent on the next load."""
        self._section_starts = list(starts)
        self._apply_sections()

    def _apply_sections(self) -> None:
        self.page().runJavaScript(
            _SET_SECTIONS_JS % {"starts": json.dumps(self._section_starts)}
        )

    def mark_search_blocks(self, block_ids: list[str]) -> None:
        """Highlight the given paragraphs (clears any prior mark first). An
        empty list just clears."""
        self.page().runJavaScript(
            _MARK_BLOCKS_JS % {"ids": json.dumps(list(block_ids))}
        )

    def clear_search_mark(self) -> None:
        """Remove the search-block highlight."""
        self.page().runJavaScript(_MARK_BLOCKS_JS % {"ids": "[]"})

    def matched_block_id(self, term: str, index: int, callback) -> None:
        """Find the block holding the `index`-th (1-based) match for `term` and
        pass its id (or "") to callback(str). `index` is the find result's
        activeMatch; see _MATCH_BLOCK_JS for why the block is located by
        occurrence count rather than the live scroll (findText leaves no DOM
        selection to read, and its callback can fire before the scroll settles)."""
        js = _MATCH_BLOCK_JS % {"term": json.dumps(term), "index": int(index)}
        self.page().runJavaScript(js, lambda value: callback(value or ""))

    def match_sentence(self, term: str, index: int, callback) -> None:
        """Extract the sentence containing the `index`-th (1-based) match for
        `term` and pass it (or "") to callback(str). `index` is the find
        result's activeMatch; the sentence is located by occurrence count like
        matched_block_id (findText leaves no DOM selection to read). The block
        text and match offset only exist in the page, so extraction runs there
        and returns a JSON string parsed back here."""
        js = _MATCH_SENTENCE_JS % {
            "term": json.dumps(term),
            "index": int(index),
        }

        def _on_result(payload):
            if not payload:
                callback("")
                return
            try:
                data = json.loads(payload)
            except (ValueError, TypeError):
                callback("")
                return
            callback(data.get("sentence", "") or "")

        self.page().runJavaScript(js, _on_result)

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
