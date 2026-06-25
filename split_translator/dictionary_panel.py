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
        to_example = menu.addAction("Add selection to Example")
        to_polish.setEnabled(bool(text))
        to_english.setEnabled(bool(text))
        to_example.setEnabled(bool(text))
        menu.addSeparator()
        copy_url = menu.addAction("Copy page URL")
        copy_url.setEnabled(bool(page_url))
        chosen = menu.exec(event.globalPos())
        if chosen == to_polish:
            self.capture_selection.emit("polish", text)
        elif chosen == to_english:
            self.capture_selection.emit("english", text)
        elif chosen == to_example:
            self.capture_selection.emit("example", text)
        elif chosen == copy_url:
            QApplication.clipboard().setText(page_url)


class DictionaryPanel(QWidget):
    """Search controls and the web views that show dictionary/translation results.

    Emits ``word_searched`` whenever a lookup runs so the owner can record history and
    drive the PDF search.
    """

    word_searched = Signal(str)
    pronunciation_grabbed = Signal(object)
    grammar_grabbed = Signal(object)  # {"plural": bool} from the Cambridge page
    correction_applied = Signal(str, str)  # wrong word, corrected word
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

        // UK/US spelling. Cambridge lists only the differing spelling as a
        // variant (span.spellvar with a .region tag saying UK or US and a .v
        // value); the headword is the opposite region's spelling. So a US
        // variant means us=variant and uk=headword, and vice versa. If there is
        // no variant the word spells the same in both, so leave both null.
        function grabSpelling() {
            var head = document.querySelector('.hw.dhw');
            var headword = head ? head.textContent.trim() : null;
            var ukSpelling = null, usSpelling = null;
            var variants = document.querySelectorAll('.spellvar.dspellvar');
            for (var i = 0; i < variants.length; i++) {
                var regionEl = variants[i].querySelector('.region.dregion');
                var valEl = variants[i].querySelector('.v.dv');
                if (!regionEl || !valEl) { continue; }
                var region = regionEl.textContent.trim().toUpperCase();
                var value = valEl.textContent.trim();
                if (region === 'US' && !usSpelling) {
                    usSpelling = value; if (!ukSpelling) { ukSpelling = headword; }
                } else if (region === 'UK' && !ukSpelling) {
                    ukSpelling = value; if (!usSpelling) { usSpelling = headword; }
                }
            }
            return { uk: ukSpelling, us: usSpelling };
        }
        var spelling = grabSpelling();

        // Return a JSON string, not a bare object: Qt's runJavaScript bridge
        // drops a plain object here (it arrives as an empty string), whereas a
        // string round-trips reliably. The Python callback parses it back.
        return JSON.stringify({
            ipa_uk: uk.ipa, ipa_us: us.ipa,
            audio_uk_url: uk.audio, audio_us_url: us.audio,
            spelling_uk: spelling.uk, spelling_us: spelling.us
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

    # Detect whether Cambridge marks the headword as plural-only. Grammar notes
    # live in span.gram.dgram blocks rendered like "[ plural ]". The word is
    # plural-only when a whole block (brackets and spacing stripped) reads exactly
    # "plural" (as for scissors, trousers, glasses). A softer block like
    # "[ U or plural ]" (data) is deliberately not matched, even though it
    # contains the word "plural". Returns a JSON string for the same reason as
    # _GRAB_JS (a bare object arrives empty from runJavaScript).
    _GRAMMAR_JS = r"""
    (function() {
        var plural = false;
        var grams = document.querySelectorAll('.gram.dgram');
        for (var i = 0; i < grams.length; i++) {
            var text = grams[i].textContent
                .replace(/[\[\]]/g, '').replace(/\s+/g, ' ').trim().toLowerCase();
            if (text === 'plural') {
                plural = true;
                break;
            }
        }
        return JSON.stringify({ plural: plural });
    })();
    """

    def grab_grammar(self):
        self.cambridge_en_view.page().runJavaScript(
            self._GRAMMAR_JS, self._on_grammar
        )

    def _on_grammar(self, result):
        try:
            data = json.loads(result) if result else {}
        except (json.JSONDecodeError, TypeError):
            data = {}
        self.grammar_grabbed.emit(data)

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

        // How many senses the editor currently has; the editor keeps this in
        // sync by calling window.stSetSenseCount. The per-item "sense#" dropdown
        // lists exactly these existing senses.
        if (typeof window.stSenseCount !== 'number') { window.stSenseCount = 1; }

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

        function fillSelect(sel) {
            // First option is a non-action placeholder; the rest are sense numbers.
            sel.innerHTML = '';
            var ph = document.createElement('option');
            ph.value = '';
            ph.textContent = 'sense#';
            sel.appendChild(ph);
            for (var i = 1; i <= window.stSenseCount; i++) {
                var o = document.createElement('option');
                o.value = String(i);
                o.textContent = String(i);
                sel.appendChild(o);
            }
            sel.selectedIndex = 0;
        }

        function makeSenseSelect(text, field, getPos) {
            var sel = document.createElement('select');
            sel.className = 'st-capture-select';
            sel.title = 'Add to a specific sense';
            // box-sizing + explicit height force the native select down to the
            // button height (18px); without it Chromium gives selects a taller
            // fixed minimum control height regardless of padding. appearance:none
            // drops the native arrow (which also imposed the taller height), so a
            // white chevron is drawn back in as a background SVG.
            var arrow = "url(\"data:image/svg+xml,"
                + "%3Csvg xmlns='http://www.w3.org/2000/svg' width='8' height='8' "
                + "viewBox='0 0 8 8'%3E%3Cpath d='M1 2.5L4 5.5L7 2.5' "
                + "stroke='white' stroke-width='1.2' fill='none'/%3E%3C/svg%3E\")";
            sel.style.cssText = 'margin-left:4px;padding:0 14px 0 4px;font-size:11px;'
                + 'line-height:16px;height:18px;box-sizing:border-box;'
                + 'border:1px solid #0a84ff;border-radius:3px;'
                + 'background-color:#0a84ff;color:#fff;cursor:pointer;'
                + 'vertical-align:middle;appearance:none;-webkit-appearance:none;'
                + 'background-image:' + arrow + ';background-repeat:no-repeat;'
                + 'background-position:right 3px center;';
            fillSelect(sel);
            sel.addEventListener('mousedown', function(ev) { ev.stopPropagation(); });
            sel.addEventListener('change', function(ev) {
                ev.preventDefault();
                ev.stopPropagation();
                var val = sel.value;
                if (val) { window.captureBridge.capture(text, field, val, getPos()); }
                sel.selectedIndex = 0;  // reset so it can be reused
            });
            return sel;
        }

        function injectPair(selector, field) {
            var items = document.querySelectorAll(selector);
            items.forEach(function(item) {
                if (item.dataset.stCapture === '1') { return; }
                item.dataset.stCapture = '1';
                var text = item.textContent.trim();
                if (!text) { return; }
                var pos = posCodeFor(item);
                var getPos = function() { return pos; };
                var holder = document.createElement('span');
                holder.className = 'st-capture-holder';
                holder.style.cssText = 'white-space:nowrap;display:inline-block;';
                holder.appendChild(makeButton('+cur', 'Add to current sense', function() {
                    window.captureBridge.capture(text, field, 'current', pos);
                }));
                holder.appendChild(makeButton('+new', 'Add to new sense', function() {
                    window.captureBridge.capture(text, field, 'new', pos);
                }));
                holder.appendChild(makeSenseSelect(text, field, getPos));
                item.appendChild(holder);
            });
        }

        function inject() {
            if (!window.captureBridge) { return; }
            pairs.forEach(function(p) { injectPair(p.selector, p.field); });
        }

        // Called from Python when the editor's sense count changes: refresh
        // every existing dropdown so it lists the current sense numbers.
        window.stSetSenseCount = function(n) {
            window.stSenseCount = (typeof n === 'number' && n > 0) ? n : 1;
            var selects = document.querySelectorAll('select.st-capture-select');
            selects.forEach(function(sel) { fillSelect(sel); });
        };

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
    # The English page shows definitions and their usage examples; the
    # English-Polish page also shows Polish translations. Examples (.eg.deg) get
    # the same controls so each can be added to a chosen sense.
    _EN_CAPTURE_PAIRS = [
        {"selector": ".def.ddef_d", "field": "english"},
        {"selector": ".eg.deg", "field": "example"},
    ]
    _PL_CAPTURE_PAIRS = [
        {"selector": ".trans.dtrans.dtrans-se", "field": "polish"},
        {"selector": ".def.ddef_d", "field": "english"},
        {"selector": ".eg.deg", "field": "example"},
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
        # Once the English page loads, read the headword's grammar (plural-only
        # marker) and its pronunciation. The pronunciation result is emitted on
        # every load; the flashcard editor decides whether to use it.
        self.cambridge_en_view.loadFinished.connect(
            lambda ok: self._on_english_loaded() if ok else None
        )
        self.cambridge_pl_view.loadFinished.connect(
            lambda ok: self._inject_capture(
                self.cambridge_pl_view, self._PL_CAPTURE_PAIRS, ok
            )
        )

    def _on_english_loaded(self):
        self.grab_grammar()
        self.grab_pronunciation()

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
        # A fresh page resets the JS sense count to 1; re-push the real count.
        self._push_sense_count(view)

    def set_sense_count(self, count: int):
        """Tell the injected dropdowns how many senses the editor currently has."""
        self._sense_count = max(1, int(count))
        for view in (self.cambridge_en_view, self.cambridge_pl_view):
            self._push_sense_count(view)

    def _push_sense_count(self, view):
        count = getattr(self, "_sense_count", 1)
        view.page().runJavaScript(
            f"if (window.stSetSenseCount) {{ window.stSetSenseCount({count}); }}"
        )

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
        if not result:
            return
        corrected = result.replace(" meaning", "").strip()
        if not corrected:
            return
        # The word that was wrong is whatever is in the box before we re-search.
        wrong = self.search_input.text().strip()
        if wrong and wrong != corrected:
            # Let the owner drop the misspelled history entry; the re-search
            # below adds the corrected word as a normal lookup.
            self.correction_applied.emit(wrong, corrected)
        self.search_word(corrected)

    def play_cambridge_audio(self, audio_num: int = 1):
        js_code = f"audio{audio_num}.load(); audio{audio_num}.play();"
        self.cambridge_en_view.page().runJavaScript(js_code)
