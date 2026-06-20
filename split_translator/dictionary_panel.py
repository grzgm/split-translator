"""Dictionary lookup panel: search bar plus a grid of web views for each source."""

import json
from urllib.parse import quote

from PySide6.QtCore import QFile, QIODevice, Qt, QUrl, Signal
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .capture_bridge import CaptureBridge


def _qwebchannel_js() -> str:
    """Read Qt's bundled qwebchannel.js client from the resource system."""
    f = QFile(":/qtwebchannel/qwebchannel.js")
    if not f.open(QIODevice.OpenModeFlag.ReadOnly):
        return ""
    try:
        return bytes(f.readAll().data()).decode("utf-8")
    finally:
        f.close()


class CaptureWebView(QWebEngineView):
    """A web view whose right-click menu keeps the browser defaults and adds the
    two flashcard capture actions below them."""

    # field ("polish"/"english"), selected text
    capture_selection = Signal(str, str)

    def contextMenuEvent(self, event):
        text = self.page().selectedText().strip()
        page_url = self.url().toString()
        # Start from the standard menu (Copy, Back, Reload, ...) so nothing is lost.
        menu = self.createStandardContextMenu()
        menu.addSeparator()
        to_polish = menu.addAction("Add selection to Polish")
        to_english = menu.addAction("Add selection to English")
        to_polish.setEnabled(bool(text))
        to_english.setEnabled(bool(text))
        menu.addSeparator()
        copy_url = menu.addAction("Copy page URL")
        copy_url.setEnabled(bool(page_url))
        chosen = menu.exec(event.globalPos())
        if chosen == to_polish:
            self.capture_selection.emit("polish", text)
        elif chosen == to_english:
            self.capture_selection.emit("english", text)
        elif chosen == copy_url:
            QApplication.clipboard().setText(page_url)


class DictionaryPanel(QWidget):
    """Search controls and the web views that show dictionary/translation results.

    Emits ``word_searched`` whenever a lookup runs so the owner can record history and
    drive the PDF search.
    """

    word_searched = Signal(str)
    pronunciation_grabbed = Signal(object)
    selection_capture_requested = Signal(str, str)  # field ("polish"/"english"), text
    # text, field ("polish"/"english"), target ("current"/"new"), pos ("" if unknown)
    sense_capture_requested = Signal(str, str, str, str)

    def __init__(self, profile: QWebEngineProfile, parent=None):
        super().__init__(parent)
        self.profile = profile
        self.capture_bridge = CaptureBridge(self)
        self.capture_bridge.capture_requested.connect(
            self.sense_capture_requested
        )
        self.init_ui()
        self._setup_capture_buttons()

    def _make_view(self) -> QWebEngineView:
        """Create a web view backed by the shared persistent profile."""
        view = CaptureWebView()
        view.setPage(QWebEnginePage(self.profile, view))
        view.capture_selection.connect(self._on_capture_selection)
        return view

    def _on_capture_selection(self, field: str, text: str):
        if text:
            self.selection_capture_requested.emit(field, text)

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Search bar.
        search_layout = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Enter word to translate...")
        self.search_input.returnPressed.connect(self.search)
        search_button = QPushButton("Search")
        search_button.clicked.connect(self.search)
        correction_button = QPushButton("Get Correction")
        correction_button.clicked.connect(self.get_correction)
        search_layout.addWidget(self.search_input)
        search_layout.addWidget(search_button)
        search_layout.addWidget(correction_button)
        layout.addLayout(search_layout)

        # Web views.
        main_splitter = QSplitter(Qt.Orientation.Horizontal)
        left_splitter = QSplitter(Qt.Orientation.Vertical)

        self.cambridge_en_view = self._make_view()
        self.cambridge_pl_view = self._make_view()

        left_splitter.addWidget(self.cambridge_en_view)
        left_splitter.addWidget(self.cambridge_pl_view)
        left_splitter.setSizes([1, 1])

        right_splitter = QSplitter(Qt.Orientation.Vertical)

        self.google_tabs = QTabWidget()
        self.google_meaning_view = self._make_view()
        self.google_translate_view = self._make_view()
        self.google_tabs.addTab(self.google_meaning_view, "Meaning")
        self.google_tabs.addTab(self.google_translate_view, "Po polsku")

        self.babla_view = self._make_view()

        right_splitter.addWidget(self.google_tabs)
        right_splitter.addWidget(self.babla_view)
        right_splitter.setSizes([400, 400])

        main_splitter.addWidget(left_splitter)
        main_splitter.addWidget(right_splitter)
        main_splitter.setSizes([500, 500])
        layout.addWidget(main_splitter)

    def _all_views(self) -> list:
        return [
            self.cambridge_en_view,
            self.cambridge_pl_view,
            self.google_meaning_view,
            self.google_translate_view,
            self.babla_view,
        ]

    def focused_selection(self) -> str:
        for view in self._all_views():
            proxy = view.focusProxy()
            if view.hasFocus() or (proxy is not None and proxy.hasFocus()):
                text = view.page().selectedText().strip()
                if text:
                    return text
        for view in self._all_views():
            text = view.page().selectedText().strip()
            if text:
                return text
        return ""

    _GRAB_JS = r"""
    (function() {
        function grab(region) {
            var block = document.querySelector('span.' + region + '.dpron-i');
            if (!block) { return { ipa: null, audio: null }; }
            var ipaEl = block.querySelector('.ipa');
            var srcEl = block.querySelector('source[type="audio/mpeg"]')
                || block.querySelector('source[src$=".mp3"]');
            var audio = srcEl ? srcEl.getAttribute('src') : null;
            if (audio && audio.indexOf('http') !== 0) {
                audio = 'https://dictionary.cambridge.org' + audio;
            }
            return { ipa: ipaEl ? ipaEl.textContent.trim() : null, audio: audio };
        }
        var uk = grab('uk');
        var us = grab('us');
        // Return a JSON string, not a bare object: Qt's runJavaScript bridge
        // drops a plain object here (it arrives as an empty string), whereas a
        // string round-trips reliably. The Python callback parses it back.
        return JSON.stringify({
            ipa_uk: uk.ipa, ipa_us: us.ipa,
            audio_uk_url: uk.audio, audio_us_url: us.audio
        });
    })();
    """

    def grab_pronunciation(self):
        self.cambridge_en_view.page().runJavaScript(
            self._GRAB_JS, self._on_pronunciation
        )

    def _on_pronunciation(self, result):
        try:
            data = json.loads(result) if result else {}
        except (json.JSONDecodeError, TypeError):
            data = {}
        self.pronunciation_grabbed.emit(data)

    # --- inject capture buttons into the Cambridge views ----------------

    # POS labels Cambridge uses, mapped to the editor's short dropdown codes.
    _POS_MAP = {
        "noun": "n",
        "verb": "v",
        "adjective": "adj",
        "adverb": "adv",
        "preposition": "prep",
        "conjunction": "conj",
        "pronoun": "pron",
        "phrase": "phrase",
        "idiom": "phrase",
    }

    # Injected on the Cambridge views: builds two small buttons next to each
    # definition and translation and routes clicks through the QWebChannel
    # bridge. __PAIRS__ is a JSON array of {selector, field} objects, so one
    # view can carry both English-definition and Polish-translation buttons
    # (the English-Polish page shows both). Placeholders __CHANNEL_JS__ (Qt's
    # qwebchannel.js client), __PAIRS__ and __POS_MAP__ are substituted with
    # str.replace, not str.format, because the embedded qwebchannel.js is full
    # of braces that would break formatting.
    _CAPTURE_JS_TEMPLATE = r"""
    (function() {
        __CHANNEL_JS__

        var pairs = __PAIRS__;

        function posCodeFor(el) {
            var posMap = __POS_MAP__;
            var block = el.closest('.pr.entry-body__el')
                || el.closest('.entry-body__el') || el.closest('.di-body')
                || document;
            var posEl = (el.closest('.def-block') || block).querySelector('.pos.dpos')
                || block.querySelector('.pos.dpos');
            if (!posEl) { return ""; }
            var word = posEl.textContent.trim().toLowerCase();
            return posMap[word] || "";
        }

        function makeButton(label, title, onClick) {
            var b = document.createElement('button');
            b.textContent = label;
            b.title = title;
            b.className = 'st-capture-btn';
            b.style.cssText = 'margin-left:4px;padding:0 5px;font-size:11px;'
                + 'line-height:16px;border:1px solid #0a84ff;border-radius:3px;'
                + 'background:#0a84ff;color:#fff;cursor:pointer;vertical-align:middle;';
            b.addEventListener('click', function(ev) {
                ev.preventDefault();
                ev.stopPropagation();
                onClick();
            });
            return b;
        }

        function injectPair(selector, field) {
            var items = document.querySelectorAll(selector);
            items.forEach(function(item) {
                if (item.dataset.stCapture === '1') { return; }
                item.dataset.stCapture = '1';
                var text = item.textContent.trim();
                if (!text) { return; }
                var pos = posCodeFor(item);
                var holder = document.createElement('span');
                holder.className = 'st-capture-holder';
                holder.style.cssText = 'white-space:nowrap;display:inline-block;';
                holder.appendChild(makeButton('+cur', 'Add to current sense', function() {
                    window.captureBridge.capture(text, field, 'current', pos);
                }));
                holder.appendChild(makeButton('+new', 'Add to new sense', function() {
                    window.captureBridge.capture(text, field, 'new', pos);
                }));
                item.appendChild(holder);
            });
        }

        function inject() {
            if (!window.captureBridge) { return; }
            pairs.forEach(function(p) { injectPair(p.selector, p.field); });
        }

        function start() {
            new QWebChannel(qt.webChannelTransport, function(channel) {
                window.captureBridge = channel.objects.captureBridge;
                inject();
            });
        }

        if (window.captureBridge) { inject(); } else { start(); }

        // Cambridge renders content progressively; re-inject for late nodes.
        var observer = new MutationObserver(inject);
        if (document.body) {
            observer.observe(document.body, { childList: true, subtree: true });
        }
        setTimeout(function() { observer.disconnect(); }, 8000);
    })();
    """

    # Which (CSS selector, target field) pairs get capture buttons per view.
    # The English page shows only definitions; the English-Polish page shows
    # both Polish translations and the English definitions, so both get buttons.
    _EN_CAPTURE_PAIRS = [{"selector": ".def.ddef_d", "field": "english"}]
    _PL_CAPTURE_PAIRS = [
        {"selector": ".trans.dtrans.dtrans-se", "field": "polish"},
        {"selector": ".def.ddef_d", "field": "english"},
    ]

    def _setup_capture_buttons(self):
        channel = QWebChannel(self)
        channel.registerObject("captureBridge", self.capture_bridge)
        # Both Cambridge views share the one bridge object.
        self.cambridge_en_view.page().setWebChannel(channel)
        self.cambridge_pl_view.page().setWebChannel(channel)
        self._capture_channel = channel

        self.cambridge_en_view.loadFinished.connect(
            lambda ok: self._inject_capture(
                self.cambridge_en_view, self._EN_CAPTURE_PAIRS, ok
            )
        )
        self.cambridge_pl_view.loadFinished.connect(
            lambda ok: self._inject_capture(
                self.cambridge_pl_view, self._PL_CAPTURE_PAIRS, ok
            )
        )

    def _inject_capture(self, view, pairs, ok):
        if not ok:
            return
        js = (
            self._CAPTURE_JS_TEMPLATE
            .replace("__CHANNEL_JS__", _qwebchannel_js())
            .replace("__POS_MAP__", json.dumps(self._POS_MAP))
            .replace("__PAIRS__", json.dumps(pairs))
        )
        view.page().runJavaScript(js)

    def set_focus(self):
        self.search_input.setFocus()

    def focus_search(self):
        self.search_input.setFocus()
        self.search_input.selectAll()

    def search_word(self, word: str):
        """Populate the search box with a word and run the lookup."""
        self.search_input.setText(word)
        self.search()

    def search(self):
        word = self.search_input.text().strip()
        if not word:
            return

        encoded_word = quote(word)

        cambridge_en_url = (
            f"https://dictionary.cambridge.org/dictionary/english/{encoded_word}"
        )
        self.cambridge_en_view.setUrl(QUrl(cambridge_en_url))

        cambridge_pl_url = (
            "https://dictionary.cambridge.org/pl/dictionary/"
            f"english-polish/{encoded_word}"
        )
        self.cambridge_pl_view.setUrl(QUrl(cambridge_pl_url))

        # Two Google searches.
        google_meaning_url = f"https://www.google.pl/search?q={encoded_word}+meaning"
        self.google_meaning_view.setUrl(QUrl(google_meaning_url))

        google_translate_url = (
            f"https://www.google.pl/search?q={encoded_word}+po+polsku"
        )
        self.google_translate_view.setUrl(QUrl(google_translate_url))

        babla_url = f"https://www.google.pl/search?q={encoded_word}+po+polsku"
        self.babla_view.setUrl(QUrl(babla_url))

        self.word_searched.emit(word)

    def get_correction(self):
        """Read Google's 'Did you mean' spelling correction and re-search with it."""
        js_code = r"""
        (function() {
            const link = document.querySelector('a[href*="spell=1"]');
            if (!link) return null;

            const fullText = link.textContent.trim().replace(/\s+/g, ' ');

            // Remove the trailing "meaning" added by the app.
            return fullText.replace(/\s+meaning$/i, '');
        })();
        """
        self.google_meaning_view.page().runJavaScript(js_code, self._handle_correction)

    def _handle_correction(self, result):
        if result:
            corrected = result.replace(" meaning", "").strip()
            self.search_word(corrected)

    def play_cambridge_audio(self, audio_num: int = 1):
        js_code = f"audio{audio_num}.load(); audio{audio_num}.play();"
        self.cambridge_en_view.page().runJavaScript(js_code)
