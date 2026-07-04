"""Dictionary lookup panel: search bar plus a grid of web views for each source."""

import json
from urllib.parse import quote

from PySide6.QtCore import QFile, QIODevice, Qt, QUrl, Signal
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
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


# Read one Cambridge pronunciation block (span.dpron-i) into {ipa, audio}: the
# .ipa notation and the <source> mp3 URL, normalised to absolute. Defined once
# and spliced into both the one-shot grab (the "New from word" seed) and the
# injected capture script (the per-block "replace" button), so the two read a
# block the same way. Returns "" / null when the block lacks an IPA / audio.
_BLOCK_PRON_JS = r"""
        function stReadBlockPron(block) {
            if (!block) { return { ipa: '', audio: null }; }
            var ipaEl = block.querySelector('.ipa');
            var srcEl = block.querySelector('source[type="audio/mpeg"]')
                || block.querySelector('source[src$=".mp3"]')
                || block.querySelector('source');
            var audio = srcEl ? srcEl.getAttribute('src') : null;
            if (audio && audio.indexOf('http') !== 0) {
                audio = 'https://dictionary.cambridge.org' + audio;
            }
            return {
                ipa: ipaEl ? ipaEl.textContent.trim() : '',
                audio: audio
            };
        }
"""


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
    # A pronunciation clip captured from the page: region ("uk"/"us"), mp3 URL
    # and the clip's IPA notation ("" when the block has none).
    audio_capture_requested = Signal(str, str, str)

    def __init__(self, profile: QWebEngineProfile, parent=None):
        super().__init__(parent)
        self.profile = profile
        self.capture_bridge = CaptureBridge(self)
        self.capture_bridge.capture_requested.connect(
            self.sense_capture_requested
        )
        self.capture_bridge.audio_capture_requested.connect(
            self.audio_capture_requested
        )
        # Pronunciation playback goes through Qt's own media player fed the mp3
        # URL, not by calling the Cambridge page's audioN.play() globals (which
        # couples to that page's internal scripting). Lazily built on first use.
        self._player: QMediaPlayer | None = None
        self._audio_output: QAudioOutput | None = None
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
        self.babla_view = self._make_view()
        self.google_tabs.addTab(self.google_meaning_view, "Meaning")
        self.google_tabs.addTab(self.babla_view, "bab.la")

        self.google_translate_search = self._make_view()

        right_splitter.addWidget(self.google_tabs)
        right_splitter.addWidget(self.google_translate_search)
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
            self.babla_view,
            self.google_translate_search,
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
        __BLOCK_PRON_JS__
        function grab(region) {
            return stReadBlockPron(
                document.querySelector('span.' + region + '.dpron-i')
            );
        }
        var uk = grab('uk');
        var us = grab('us');

        // The page headword (span.hw.dhw). This is Cambridge's canonical
        // spelling of the entry, which differs from the raw search term when
        // the search redirects to a lemma (searching "running" lands on "run").
        // We return it so the flashcard editor fills its Headword from the
        // dictionary rather than the search box.
        var head = document.querySelector('.hw.dhw');
        var headword = head ? head.textContent.trim() : null;

        // UK/US spelling. Cambridge lists only the differing spelling as a
        // variant (span.spellvar with a .region tag saying UK or US and a .v
        // value); the headword is the opposite region's spelling. So a US
        // variant means us=variant and uk=headword, and vice versa. If there is
        // no variant the word spells the same in both, so leave both null.
        function grabSpelling() {
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
            headword: headword,
            ipa_uk: uk.ipa, ipa_us: us.ipa,
            audio_uk_url: uk.audio, audio_us_url: us.audio,
            spelling_uk: spelling.uk, spelling_us: spelling.us
        });
    })();
    """

    def grab_pronunciation(self):
        js = self._GRAB_JS.replace("__BLOCK_PRON_JS__", _BLOCK_PRON_JS)
        self.cambridge_en_view.page().runJavaScript(js, self._on_pronunciation)

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
        __BLOCK_PRON_JS__

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
                // All three act on the sense currently active in the editor:
                // "set" replaces its field, "add" appends to it as a
                // comma-separated item, "+new" starts a fresh sense (replace).
                holder.appendChild(makeButton('set', 'Set the active sense', function() {
                    window.captureBridge.capture(text, field, 'current', pos);
                }));
                holder.appendChild(makeButton('add', 'Append to the active sense', function() {
                    window.captureBridge.capture(text, field, 'append', pos);
                }));
                holder.appendChild(makeButton('+new', 'Add to new sense', function() {
                    window.captureBridge.capture(text, field, 'new', pos);
                }));
                item.appendChild(holder);
            });
        }

        // A "replace" button next to each pronunciation that overwrites the
        // current card's audio and IPA for that clip's region (uk/us) with the
        // clip's URL and notation. A card has one UK and one US slot, so the
        // action is replace (no +new). The region is read from the block's
        // class; the mp3 URL and IPA come from stReadBlockPron, the same reader
        // the "New from word" seed uses.
        function injectAudio() {
            var blocks = document.querySelectorAll('span.dpron-i');
            blocks.forEach(function(block) {
                if (block.dataset.stAudioCapture === '1') { return; }
                var region = block.classList.contains('uk') ? 'uk'
                    : block.classList.contains('us') ? 'us' : '';
                if (!region) { return; }
                var pron = stReadBlockPron(block);
                if (!pron.audio) { return; }  // nothing to capture
                var url = pron.audio;
                var ipa = pron.ipa;
                block.dataset.stAudioCapture = '1';
                block.appendChild(makeButton(
                    'replace',
                    'Replace this card\'s ' + region.toUpperCase()
                        + ' audio and IPA',
                    function() {
                        window.captureBridge.captureAudio(region, url, ipa);
                    }
                ));
            });
        }

        function inject() {
            if (!window.captureBridge) { return; }
            pairs.forEach(function(p) { injectPair(p.selector, p.field); });
            injectAudio();
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
    # bab.la's English-Polish page. Each Polish translation is a scroll-link
    # anchor inside the sense-group list; this selector matches those and
    # excludes the audio ("volume_up") anchors and the "similar translations"
    # cross-reference block, which are not scroll-links.
    _BABLA_CAPTURE_PAIRS = [
        {"selector": "ul.sense-group-results li a.scroll-link", "field": "polish"},
    ]
    # Google's "{word} po polsku" results page. The inline translation widget
    # uses Google's stable "tw-" namespace: the primary translation is the clean
    # word span inside "#tw-target-text" (its trailing ellipsis lives in a
    # separate span, so this selector already excludes it), and every dictionary
    # alternative is a Polish word span inside a bilingual-entry row (its English
    # gloss, "div.MaH2Hf", is deliberately not matched).
    _GOOGLE_PL_CAPTURE_PAIRS = [
        {"selector": "#tw-target-text span.Y2IQFc", "field": "polish"},
        {"selector": "div.tw-bilingual-entry span.SvKTZc", "field": "polish"},
    ]

    def _setup_capture_buttons(self):
        channel = QWebChannel(self)
        channel.registerObject("captureBridge", self.capture_bridge)
        # The Cambridge views, the bab.la view and the Google "po polsku" view
        # share the one bridge object.
        self.cambridge_en_view.page().setWebChannel(channel)
        self.cambridge_pl_view.page().setWebChannel(channel)
        self.babla_view.page().setWebChannel(channel)
        self.google_translate_search.page().setWebChannel(channel)
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
        self.babla_view.loadFinished.connect(
            lambda ok: self._inject_capture(
                self.babla_view, self._BABLA_CAPTURE_PAIRS, ok
            )
        )
        self.google_translate_search.loadFinished.connect(
            lambda ok: self._inject_capture(
                self.google_translate_search, self._GOOGLE_PL_CAPTURE_PAIRS, ok
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
            .replace("__BLOCK_PRON_JS__", _BLOCK_PRON_JS)
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

        babla_url = f"https://en.bab.la/dictionary/english-polish/{encoded_word}"
        self.babla_view.setUrl(QUrl(babla_url))

        google_translate_url = (
            f"https://www.google.pl/search?q={encoded_word}+po+polsku"
        )
        self.google_translate_search.setUrl(QUrl(google_translate_url))

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

    # Collects every pronunciation clip's mp3 URL on the Cambridge English page,
    # in document order, so the Nth one can be played by URL. The page renders one
    # <audio> per pronunciation, and its audioN globals (audio1, audio2, ...) line
    # up with that DOM order, so url_list[N-1] is exactly the clip the old
    # audioN.play() played (verified against the live page). Returns a JSON string
    # array; runJavaScript drops a bare array (it arrives empty), so it is
    # stringified and parsed back in Python, as with _GRAB_JS.
    _AUDIO_URLS_JS = r"""
    (function() {
        function abs(u) {
            if (u && u.indexOf('http') !== 0) {
                u = 'https://dictionary.cambridge.org' + u;
            }
            return u;
        }
        var urls = [];
        var audios = document.querySelectorAll('audio');
        for (var i = 0; i < audios.length; i++) {
            var s = audios[i].querySelector('source[type="audio/mpeg"]')
                || audios[i].querySelector('source[src$=".mp3"]')
                || audios[i].querySelector('source');
            urls.push(s ? abs(s.getAttribute('src')) : null);
        }
        return JSON.stringify(urls);
    })();
    """

    def play_cambridge_audio(self, audio_num: int = 1):
        """Play the `audio_num`-th (1-based) pronunciation clip from the Cambridge
        English page through Qt's media player. Reads the clip URLs from the page
        (rather than driving its audioN.play() globals) and plays the chosen one
        by URL, so playback no longer depends on the page's own scripting."""
        self.cambridge_en_view.page().runJavaScript(
            self._AUDIO_URLS_JS,
            lambda result: self._play_audio_url(result, audio_num),
        )

    def _play_audio_url(self, result, audio_num: int) -> None:
        try:
            urls = json.loads(result) if result else []
        except (json.JSONDecodeError, TypeError):
            urls = []
        index = audio_num - 1
        if index < 0 or index >= len(urls):
            return
        url = urls[index]
        if not url:
            return
        if self._player is None:
            self._player = QMediaPlayer(self)
            self._audio_output = QAudioOutput(self)
            self._player.setAudioOutput(self._audio_output)
        # Replaying the same URL is a no-op unless the source is cleared first
        # (setting the held URL again does nothing once the clip has finished),
        # so stop and clear before reloading, mirroring the flashcard player.
        self._player.stop()
        self._player.setSource(QUrl())
        self._player.setSource(QUrl(url))
        self._player.play()
