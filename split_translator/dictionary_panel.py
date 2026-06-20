"""Dictionary lookup panel: search bar plus a grid of web views for each source."""

import json
from urllib.parse import quote

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLineEdit,
    QMenu,
    QPushButton,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)


class DictionaryPanel(QWidget):
    """Search controls and the web views that show dictionary/translation results.

    Emits ``word_searched`` whenever a lookup runs so the owner can record history and
    drive the PDF search.
    """

    word_searched = Signal(str)
    pronunciation_grabbed = Signal(object)
    selection_capture_requested = Signal(str, str)  # field ("polish"/"english"), text

    def __init__(self, profile: QWebEngineProfile, parent=None):
        super().__init__(parent)
        self.profile = profile
        self.init_ui()
        self._setup_context_menus()

    def _make_view(self) -> QWebEngineView:
        """Create a web view backed by the shared persistent profile."""
        view = QWebEngineView()
        view.setPage(QWebEnginePage(self.profile, view))
        return view

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

    def _setup_context_menus(self):
        for view in self._all_views():
            view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            view.customContextMenuRequested.connect(
                lambda pos, v=view: self._show_capture_menu(v, pos)
            )

    def _show_capture_menu(self, view, pos):
        text = view.page().selectedText().strip()
        menu = QMenu(view)
        to_polish = menu.addAction("Add selection to Polish")
        to_english = menu.addAction("Add selection to English")
        to_polish.setEnabled(bool(text))
        to_english.setEnabled(bool(text))
        action = menu.exec(view.mapToGlobal(pos))
        if action == to_polish:
            self.selection_capture_requested.emit("polish", text)
        elif action == to_english:
            self.selection_capture_requested.emit("english", text)

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
