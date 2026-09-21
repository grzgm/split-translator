"""Editor-only book view: a BookView that reports paragraph clicks and can
highlight blocks (the current selection, saved anchors, and a jumped-to anchor).

The read-only reading panel keeps using plain BookView, so it carries none of
this overhead. Click reporting uses the same QWebChannel + bridge pattern as
the dictionary capture buttons."""

import json

from PySide6.QtCore import QFile, QIODevice, Signal
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEngineProfile

from .anchor_click_bridge import AnchorClickBridge
from .book_loader import BookDocument
from .book_view import BookView
from .normalise_spec import NormaliseSpec

#: The class a manual group's paragraphs get: a yellow background.
MANUAL_MARK = "st-anchored"
#: The classes automatic groups' paragraphs get, alternating from one group to
#: the next so neighbours can be told apart: a light or a deeper purple
#: background.
AUTOMATIC_MARKS = ("st-auto-a", "st-auto-b")


def _qwebchannel_js() -> str:
    """Read Qt's bundled qwebchannel.js client from the resource system."""
    f = QFile(":/qtwebchannel/qwebchannel.js")
    if not f.open(QIODevice.OpenModeFlag.ReadOnly):
        return ""
    try:
        return bytes(f.readAll().data()).decode("utf-8")
    finally:
        f.close()


# Injected at load. Connects to the channel, grabs the bridge, attaches one
# delegated click listener that reports the clicked block's data-stid, and
# defines the helpers that set the selection, the jump outline and the group
# marks, plus their styles. __CHANNEL_JS__ is replaced with the bundled
# qwebchannel.js client (str.replace, not format, because that client text is
# full of braces).
_ANCHOR_JS = """
(function() {
    __CHANNEL_JS__

    function injectStyle() {
        if (document.getElementById('st-anchor-style')) return;
        var style = document.createElement('style');
        style.id = 'st-anchor-style';
        style.textContent =
            '.st-selected { outline: 2px solid #1a73e8; background: #e8f0fe; }' +
            '.st-anchored { background: #fff3cd; }' +
            '.st-auto-a { background: #f1e4fa; }' +
            '.st-auto-b { background: #dfc8f0; }' +
            '.st-jump { outline: 2px dashed #1a73e8; }';
        (document.head || document.documentElement).appendChild(style);
    }

    function clearClass(name) {
        var els = document.querySelectorAll('.' + name);
        for (var i = 0; i < els.length; i++) els[i].classList.remove(name);
    }

    function addClass(id, name) {
        if (!id) return;
        var el = document.querySelector('[data-stid=' + JSON.stringify(id) + ']');
        if (el) el.classList.add(name);
    }

    window.stSetSelected = function(id) {
        clearClass('st-selected');
        addClass(id, 'st-selected');
    };
    window.stSetJump = function(id) {
        clearClass('st-jump');
        addClass(id, 'st-jump');
    };
    var GROUP_MARKS = ['st-anchored', 'st-auto-a', 'st-auto-b'];
    window.stSetMarks = function(marksJson) {
        for (var c = 0; c < GROUP_MARKS.length; c++) clearClass(GROUP_MARKS[c]);
        var marks = JSON.parse(marksJson);
        for (var k = 0; k < GROUP_MARKS.length; k++) {
            var ids = marks[GROUP_MARKS[k]] || [];
            for (var i = 0; i < ids.length; i++) addClass(ids[i], GROUP_MARKS[k]);
        }
    };

    function attachClicks() {
        document.addEventListener('click', function(ev) {
            var el = ev.target;
            while (el && el !== document) {
                if (el.hasAttribute && el.hasAttribute('data-stid')) {
                    if (window.anchorBridge) {
                        window.anchorBridge.clicked(el.getAttribute('data-stid'));
                    }
                    return;
                }
                el = el.parentNode;
            }
        });
    }

    function start() {
        injectStyle();
        attachClicks();
        new QWebChannel(qt.webChannelTransport, function(channel) {
            window.anchorBridge = channel.objects.anchorBridge;
        });
    }

    start();
})();
"""


class AnchorBookView(BookView):
    """A BookView that reports clicks and can highlight blocks for the editor."""

    block_clicked = Signal(str)

    def __init__(
        self,
        document: BookDocument,
        profile: QWebEngineProfile,
        parent=None,
        initial_scroll: tuple[str, float] | None = None,
        normalise: bool = False,
        spec: NormaliseSpec | None = None,
    ):
        super().__init__(
            document,
            profile,
            parent,
            initial_scroll=initial_scroll,
            normalise=normalise,
            spec=spec,
        )
        self._bridge = AnchorClickBridge(self)
        self._bridge.block_clicked.connect(self.block_clicked)

        self._channel = QWebChannel(self)
        self._channel.registerObject("anchorBridge", self._bridge)
        self.page().setWebChannel(self._channel)

        # The group marks are often requested before the page has finished
        # loading (the editor highlights saved anchors at construction, while
        # the async load is still in flight). window.stSetMarks is only defined
        # by the injected _ANCHOR_JS below, so an early set_marks is a no-op.
        # Remember the marks and re-apply them once the page (and the helpers)
        # load.
        self._marks: dict[str, list[str]] = {}

        # setHtml (run in BookView.__init__) is async; inject once it has loaded.
        self.page().loadFinished.connect(self._on_load_finished)

    def _on_load_finished(self, ok: bool) -> None:
        if not ok:
            return
        js = _ANCHOR_JS.replace("__CHANNEL_JS__", _qwebchannel_js())
        self.page().runJavaScript(js)
        # Now that stSetMarks exists, re-apply any marks requested before the
        # load so the groups show on first open, not only after the next
        # set_marks call.
        if self._marks:
            self.set_marks(self._marks)

    def set_selected(self, block_id: str) -> None:
        self.page().runJavaScript(f"window.stSetSelected({json.dumps(block_id)})")

    def set_jump(self, block_id: str) -> None:
        self.page().runJavaScript(f"window.stSetJump({json.dumps(block_id)})")

    def remember_marks(self, marks: dict[str, list[str]]) -> None:
        """Record the group marks without touching the page, so they can be
        re-applied once the page (and stSetMarks) have loaded."""
        self._marks = {name: list(ids) for name, ids in marks.items()}

    def set_marks(self, marks: dict[str, list[str]]) -> None:
        """Mark the anchor groups: each key is a class (MANUAL_MARK or one of
        AUTOMATIC_MARKS) and its value the paragraph ids to give it. Every
        earlier group mark is cleared, in the same script call."""
        self.remember_marks(marks)
        self.page().runJavaScript(
            f"window.stSetMarks({json.dumps(json.dumps(self._marks))})"
        )
