"""Dictionary lookup panel: search bar plus a grid of web views for each source."""

import json
from urllib.parse import quote

from PySide6.QtCore import QFile, QIODevice, Qt, QUrl, Signal
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import (
    QWebEnginePage,
    QWebEngineProfile,
    QWebEngineScript,
)
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


# diki plays the searched word's pronunciation clip on load (its Howler.js
# bundle calls HTMLMediaElement.play() automatically, at document "interactive",
# with no user gesture), which is unwanted noise on every search. This gate,
# injected at document creation before diki's own scripts run, blocks play()
# until the user has interacted with the page. The auto-play fires during load,
# before any click, so it is suppressed; every speaker-icon click happens after
# a user gesture, so it still plays. Scoped to the diki view only.
_DIKI_AUDIO_GATE_JS = r"""
(function () {
    var interacted = false;
    var events = ['pointerdown', 'mousedown', 'click', 'keydown', 'touchstart'];
    events.forEach(function (ev) {
        window.addEventListener(ev, function () { interacted = true; }, true);
    });
    var origPlay = HTMLMediaElement.prototype.play;
    HTMLMediaElement.prototype.play = function () {
        if (!interacted) {
            try { this.pause(); } catch (e) {}
            return Promise.reject(
                new DOMException('blocked before user gesture', 'NotAllowedError')
            );
        }
        return origPlay.apply(this, arguments);
    };
})();
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
    correction_unavailable = Signal(str)  # searched word with no correction found
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
        # Armed by search() so the passive auto-grab on the next Cambridge English
        # load fires only for an app-initiated lookup. A load the user causes by
        # searching or clicking inside the page leaves this False, so it is not
        # grabbed. Consumed (cleared) by the first English loadFinished after a
        # search, whether that load succeeded or not.
        self._app_search_pending = False
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

    def _install_diki_audio_gate(self, view: QWebEngineView) -> None:
        """Suppress diki's on-load pronunciation clip while keeping the
        speaker-icon click playback working (see _DIKI_AUDIO_GATE_JS)."""
        script = QWebEngineScript()
        script.setName("diki-audio-gate")
        script.setInjectionPoint(
            QWebEngineScript.InjectionPoint.DocumentCreation
        )
        script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
        script.setRunsOnSubFrames(False)
        script.setSourceCode(_DIKI_AUDIO_GATE_JS)
        view.page().scripts().insert(script)

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Search bar.
        search_layout = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Enter word to translate...")
        # Both trigger a normal search. Wrap them so no signal argument reaches
        # search(): QPushButton.clicked emits a `checked` bool, and binding it to
        # search() positionally would land on emit_searched=False, silently
        # skipping the history add and the book search. returnPressed carries no
        # argument, but is wrapped too so the two paths call search identically.
        self.search_input.returnPressed.connect(lambda: self.search())
        search_button = QPushButton("Search")
        search_button.clicked.connect(lambda: self.search())
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
        self.diki_view = self._make_view()
        self._install_diki_audio_gate(self.diki_view)
        self.google_tabs.addTab(self.google_meaning_view, "Meaning")
        self.google_tabs.addTab(self.babla_view, "bab.la")
        self.google_tabs.addTab(self.diki_view, "diki")

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
            self.diki_view,
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

    # --- inject capture buttons into the dictionary views ----------------

    # Each site labels a sense's part of speech in its own words and its own
    # markup, so each gets a label-to-code map and a rule saying where the label
    # sits relative to the element the capture button is attached to. Every code
    # is at most three letters and must be one of ``SenseRow.POS_OPTIONS``, the
    # list the editor's dropdown offers, because a capture writes it straight
    # into that dropdown. A label that is not in the map yields no code at all;
    # see _POS_RULE_JS for why that matters.

    # Cambridge labels senses in English, in a .pos.dpos element inside the
    # entry block that contains the definition.
    _POS_MAP = {
        "noun": "n",
        "verb": "v",
        "adjective": "adj",
        "adverb": "adv",
        "preposition": "pre",
        "conjunction": "con",
        "pronoun": "pro",
        "phrase": "phr",
        "idiom": "phr",
    }

    # bab.la labels each quick-result group in its heading, as a braced suffix:
    # "shed {vb}", "quickly {adv.}". It abbreviates inconsistently (some labels
    # are spelled out, some are truncated with a trailing dot), so both spellings
    # of each are listed. The braces are stripped before the lookup.
    #
    # The same span.suffix class also carries gender ({f}, {m}), verb aspect
    # ({ipf. v.}, {pf. v.}), plural ({pl}), conjugation hints and "also:" synonym
    # lists. None of those are parts of speech and none are listed here, so they
    # resolve to no code rather than a wrong one.
    _BABLA_POS_MAP = {
        "noun": "n",
        "vb": "v",
        "verb": "v",
        "adj.": "adj",
        "adjective": "adj",
        "adv.": "adv",
        "adverb": "adv",
        "prep.": "pre",
        "preposition": "pre",
        "conj.": "con",
        "conjunction": "con",
        "pron.": "pro",
        "pronoun": "pro",
        "phrase": "phr",
        "idiom": "phr",
    }

    # diki labels each meaning group in Polish, in a span.partOfSpeech inside the
    # header above the group. "przyslowek" without the diacritic is not a spelling
    # diki uses; only the real one is listed.
    _DIKI_POS_MAP = {
        "rzeczownik": "n",
        "czasownik": "v",
        "przymiotnik": "adj",
        "przysłówek": "adv",
        "przyimek": "pre",
        "spójnik": "con",
        "zaimek": "pro",
        "idiom": "phr",
    }

    # How to find the label element, given the element a capture button is on.
    # Two shapes cover every site:
    #
    # "ancestor": the label lives inside a block that contains the sense. Walk up
    #     to the first matching container and look inside it. This is Cambridge.
    #
    # "sibling": the label lives in a heading that sits *before* the list of
    #     senses, as its sibling rather than its ancestor. Walk up to the list,
    #     then walk backwards through preceding siblings until a label turns up.
    #     This is bab.la and diki, whose headings ("shed {vb}", "rzeczownik") name
    #     the part of speech for the whole list that follows.
    #
    # A site with no rule (the Google pane) sends no part of speech.
    _CAMBRIDGE_POS_RULE = {
        "mode": "ancestor",
        # Nearest first: a definition block is more specific than the entry body
        # it sits in, so it wins when both are present.
        "containers": [".def-block", ".pr.entry-body__el", ".entry-body__el", ".di-body"],
        "label": ".pos.dpos",
    }
    _BABLA_POS_RULE = {
        "mode": "sibling",
        # Climb to the *wrapper* around the translations, not to the list itself:
        # bab.la nests ul.sense-group-results inside a div.quick-result-overview,
        # and it is that wrapper, not the list, which is the heading's sibling.
        # (The list's own previous sibling is only a language flag.)
        "list": "div.quick-result-overview",
        # Matched against each preceding sibling itself and against its contents,
        # so this is relative to the heading block (div.quick-result-option), not
        # an absolute path from the document.
        "label": "h3 span.suffix",
        # "{vb}" is the label; the braces are markup, not part of the word.
        "strip": "{}",
    }
    _DIKI_POS_RULE = {
        "mode": "sibling",
        "list": "ol.foreignToNativeMeanings",
        "label": "span.partOfSpeech",
    }

    # Injected on every capturing view: builds the small buttons next to each
    # definition, translation and example, and routes clicks through the
    # QWebChannel bridge. One script serves every site; what differs per view is
    # substituted in.
    #
    # __PAIRS__ is a JSON array of {selector, field} objects, so one view can
    # carry buttons for several fields (the English-Polish page shows both
    # definitions and translations). __POS_RULE__ and __POS_MAP__ say where that
    # site puts a sense's part of speech and what its labels are called.
    #
    # The placeholders are substituted with str.replace, not str.format, because
    # the embedded qwebchannel.js is full of braces that would break formatting.
    _CAPTURE_JS_TEMPLATE = r"""
    (function() {
        __CHANNEL_JS__
        __BLOCK_PRON_JS__

        var pairs = __PAIRS__;
        var posMap = __POS_MAP__;
        var posRule = __POS_RULE__;

        // Turn a label element's text into one of the editor's codes. An
        // unmapped label (a gender or aspect marker, a wording the site has
        // changed) gives "", which leaves the dropdown alone rather than
        // filling it with something wrong.
        function posCodeFrom(el) {
            if (!el) { return ""; }
            var word = el.textContent.trim().toLowerCase();
            var strip = posRule.strip;
            if (strip) {
                for (var i = 0; i < strip.length; i++) {
                    word = word.split(strip.charAt(i)).join('');
                }
                word = word.trim();
            }
            return posMap[word] || "";
        }

        // Read a code out of a block that may hold several label candidates.
        // bab.la's heading, for one, holds a conjugation hint ("[shed|shed]")
        // and the part of speech ("{verb}") in the same span.suffix class, in
        // that order, so taking the first match would give up before reaching
        // the real label. Take the first candidate that maps to a code.
        function posCodeIn(block) {
            if (!block) { return ""; }
            if (block.matches && block.matches(posRule.label)) {
                var own = posCodeFrom(block);
                if (own) { return own; }
            }
            var labels = block.querySelectorAll
                ? block.querySelectorAll(posRule.label) : [];
            for (var i = 0; i < labels.length; i++) {
                var code = posCodeFrom(labels[i]);
                if (code) { return code; }
            }
            return "";
        }

        // The label sits inside a block that contains the sense: climb to the
        // nearest such block and look inside it.
        function posByAncestor(el) {
            var containers = posRule.containers || [];
            for (var i = 0; i < containers.length; i++) {
                var block = el.closest(containers[i]);
                if (!block) { continue; }
                var code = posCodeIn(block);
                if (code) { return code; }
            }
            return "";
        }

        // The label sits in a heading *before* the list of senses, not around
        // it. Climb to the list, then walk backwards through earlier siblings
        // until one yields a code. Stop at the first one that does: it is the
        // heading for this list, and anything earlier belongs to a previous
        // group with a different part of speech.
        function posBySibling(el) {
            var list = el.closest(posRule.list);
            if (!list) { return ""; }
            var node = list.previousElementSibling;
            while (node) {
                var code = posCodeIn(node);
                if (code) { return code; }
                node = node.previousElementSibling;
            }
            return "";
        }

        function posCodeFor(el) {
            if (posRule.mode === 'ancestor') { return posByAncestor(el); }
            if (posRule.mode === 'sibling') { return posBySibling(el); }
            return "";
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
                // These act on the sense currently active in the editor:
                // "add" appends to its field as a comma-separated item, "set"
                // replaces the field, "+new" starts a fresh sense (replace).
                holder.appendChild(makeButton('add', 'Append to the active sense', function() {
                    window.captureBridge.capture(text, field, 'append', pos);
                }));
                // Examples always accumulate (they have no replace/append split),
                // so "set" would behave identically to "add"; omit it there.
                if (field !== 'example') {
                    holder.appendChild(makeButton('set', 'Set the active sense', function() {
                        window.captureBridge.capture(text, field, 'current', pos);
                    }));
                }
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
    # diki.pl's English-Polish page. It renders many "div.dictionaryEntity"
    # blocks: the searched word first, then cross-references (synonyms,
    # compounds, phrasal verbs). Only the first entity is the searched word's
    # own meaning list, so it is scoped with :first-of-type. Each Polish meaning
    # is the "span.hw a" anchor inside a meaning "li"; the inner anchor holds the
    # clean word without diki's parenthetical qualifier or grammar tags.
    _DIKI_CAPTURE_PAIRS = [
        {
            "selector": "div.dictionaryEntity:first-of-type "
            "ol.foreignToNativeMeanings > li span.hw a",
            "field": "polish",
        },
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

    def _capture_config(self):
        """Each capturing view, with the selectors its buttons attach to and the
        part-of-speech lookup for the site it shows.

        The Google "po polsku" pane has no part-of-speech markup at all, so it
        gets an empty rule and captures with no code, as it always has."""
        return [
            (self.cambridge_en_view, self._EN_CAPTURE_PAIRS,
             self._CAMBRIDGE_POS_RULE, self._POS_MAP),
            (self.cambridge_pl_view, self._PL_CAPTURE_PAIRS,
             self._CAMBRIDGE_POS_RULE, self._POS_MAP),
            (self.babla_view, self._BABLA_CAPTURE_PAIRS,
             self._BABLA_POS_RULE, self._BABLA_POS_MAP),
            (self.diki_view, self._DIKI_CAPTURE_PAIRS,
             self._DIKI_POS_RULE, self._DIKI_POS_MAP),
            (self.google_translate_search, self._GOOGLE_PL_CAPTURE_PAIRS,
             {}, {}),
        ]

    def _setup_capture_buttons(self):
        channel = QWebChannel(self)
        channel.registerObject("captureBridge", self.capture_bridge)
        self._capture_channel = channel

        # Every capturing view shares the one bridge object, and each is injected
        # with its own selectors and its own site's part-of-speech lookup.
        for view, pairs, rule, pos_map in self._capture_config():
            view.page().setWebChannel(channel)
            view.loadFinished.connect(
                lambda ok, v=view, p=pairs, r=rule, m=pos_map:
                    self._inject_capture(v, p, ok, r, m)
            )

        # Once the English page loads from an app search, read the headword's
        # grammar (plural-only marker) and its pronunciation. _on_english_loaded
        # grabs only for the app's own search load, not a manual in-page one; the
        # flashcard editor then decides whether to use the result.
        self.cambridge_en_view.loadFinished.connect(self._on_english_loaded)

    def _on_english_loaded(self, ok: bool):
        # Consume the armed flag on every English load, so a load that is not an
        # app search (or a failed app-search load) never leaks the grab onto the
        # next, manual load. Grab only when this load was the app's own search.
        was_app_search = self._app_search_pending
        self._app_search_pending = False
        if not (ok and was_app_search):
            return
        self.grab_grammar()
        self.grab_pronunciation()

    def _inject_capture(self, view, pairs, ok, pos_rule=None, pos_map=None):
        if not ok:
            return
        js = self._capture_js(pairs, pos_rule, pos_map)
        view.page().runJavaScript(js)

    def _capture_js(self, pairs, pos_rule=None, pos_map=None) -> str:
        """Fill the capture script for one view: its selectors, and the rule and
        label map for reading a part of speech off the site it shows."""
        if pos_rule is None:
            pos_rule = self._CAMBRIDGE_POS_RULE
        if pos_map is None:
            pos_map = self._POS_MAP
        return (
            self._CAPTURE_JS_TEMPLATE
            .replace("__CHANNEL_JS__", _qwebchannel_js())
            .replace("__BLOCK_PRON_JS__", _BLOCK_PRON_JS)
            .replace("__POS_MAP__", json.dumps(pos_map))
            .replace("__POS_RULE__", json.dumps(pos_rule))
            .replace("__PAIRS__", json.dumps(pairs))
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

    def search_headword(self, word: str):
        """Run a lookup for a word without recording history or auto-grabbing.

        Used when a flashcard is selected: the dictionary panes update to the
        card's headword, but the search must not add a history entry and must
        not let the passive Cambridge auto-grab overwrite the just-loaded card
        (which is still unaltered). word_searched is not emitted, so the main
        window drives only the book search, not the history add or the editor
        reset."""
        self.search_input.setText(word)
        self.search(emit_searched=False, arm_grab=False)

    def search(self, emit_searched: bool = True, arm_grab: bool = True):
        word = self.search_input.text().strip()
        if not word:
            return

        # Arm the passive auto-grab for the Cambridge English load this search is
        # about to start. Only this app-initiated load grabs; the user searching
        # or clicking inside the page afterwards does not. A flashcard-selection
        # search leaves it disarmed so it cannot overwrite the loaded card.
        if arm_grab:
            self._app_search_pending = True

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

        diki_url = f"https://www.diki.pl/{encoded_word}"
        self.diki_view.setUrl(QUrl(diki_url))

        google_translate_url = (
            f"https://www.google.pl/search?q={encoded_word}+po+polsku"
        )
        self.google_translate_search.setUrl(QUrl(google_translate_url))

        if emit_searched:
            self.word_searched.emit(word)

    def get_correction(self):
        """Read Google's spelling correction and re-search with it.

        Google no longer serves the old "Did you mean" `spell=1` link for these
        searches; it now shows a "Showing results for <correction>" block (in
        Polish "W tym wyniki dla <correction>") whose first link points at the
        corrected query and bolds the corrected word. The "Search only for
        <original>" link in the same block carries `nirf=`/`nfpr=` and must be
        skipped (its text is the misspelling, not the correction). We read the
        correction from that block and keep the legacy `spell=1` link as a
        fallback. Returns a JSON string {"word": <correction or "">} so an
        empty result can be told apart from a dropped bare object (runJavaScript
        turns a bare object into an empty string; see the module conventions)."""
        js_code = r"""
        (function() {
            function clean(text) {
                return (text || '').trim().replace(/\s+/g, ' ')
                    .replace(/\s+meaning$/i, '').trim();
            }

            // Legacy: classic "Did you mean" correction link.
            var legacy = document.querySelector('a[href*="spell=1"]');
            if (legacy) {
                var word = clean(legacy.textContent);
                if (word) return JSON.stringify({ word: word });
            }

            // Current markup: the correction is the block's link that points at
            // the corrected query. The "search only for <original>" link in the
            // same block carries nirf=/nfpr=, so skip those. Prefer the bolded
            // corrected term inside the link.
            var links = document.querySelectorAll('a[href*="/search?"]');
            for (var i = 0; i < links.length; i++) {
                var a = links[i];
                var href = a.getAttribute('href') || '';
                if (href.indexOf('nirf=') !== -1 || href.indexOf('nfpr=') !== -1) {
                    continue;
                }
                if (!/[?&]q=/.test(href)) continue;
                if (!/meaning$/i.test((a.textContent || '').trim())) continue;
                var bold = a.querySelector('b, i');
                var word = clean(bold ? bold.textContent : a.textContent);
                if (word) return JSON.stringify({ word: word });
            }

            return JSON.stringify({ word: '' });
        })();
        """
        self.google_meaning_view.page().runJavaScript(js_code, self._handle_correction)

    def _handle_correction(self, result):
        wrong = self.search_input.text().strip()
        corrected = ""
        if result:
            try:
                corrected = (json.loads(result).get("word") or "").strip()
            except (ValueError, TypeError):
                corrected = ""
        if not corrected or corrected == wrong:
            # No correction on the page (or the meaning view hit an anti-bot
            # wall, which returns nothing to scrape). Tell the user rather than
            # silently doing nothing.
            self.correction_unavailable.emit(wrong)
            return
        # The word that was wrong is whatever is in the box before we re-search.
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
