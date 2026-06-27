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
# defines the three highlight helpers plus their styles. __CHANNEL_JS__ is
# replaced with the bundled qwebchannel.js client (str.replace, not format,
# because that client text is full of braces).
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
    window.stSetAnchored = function(idsJson) {
        clearClass('st-anchored');
        var ids = JSON.parse(idsJson);
        for (var i = 0; i < ids.length; i++) addClass(ids[i], 'st-anchored');
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

    def __init__(self, document: BookDocument, profile: QWebEngineProfile, parent=None):
        super().__init__(document, profile, parent)
        self._bridge = AnchorClickBridge(self)
        self._bridge.block_clicked.connect(self.block_clicked)

        self._channel = QWebChannel(self)
        self._channel.registerObject("anchorBridge", self._bridge)
        self.page().setWebChannel(self._channel)

        # setHtml (run in BookView.__init__) is async; inject once it has loaded.
        self.page().loadFinished.connect(self._on_load_finished)

    def _on_load_finished(self, ok: bool) -> None:
        if not ok:
            return
        js = _ANCHOR_JS.replace("__CHANNEL_JS__", _qwebchannel_js())
        self.page().runJavaScript(js)

    def set_selected(self, block_id: str) -> None:
        self.page().runJavaScript(f"window.stSetSelected({json.dumps(block_id)})")

    def set_jump(self, block_id: str) -> None:
        self.page().runJavaScript(f"window.stSetJump({json.dumps(block_id)})")

    def set_anchored(self, block_ids: list[str]) -> None:
        self.page().runJavaScript(
            f"window.stSetAnchored({json.dumps(json.dumps(block_ids))})"
        )
