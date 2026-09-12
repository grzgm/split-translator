import json
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWebEngineCore import QWebEngineProfile
from PySide6.QtWidgets import QApplication

from split_translator.dictionary_panel import (
    DictionaryPanel,
    _parse_base_form,
)
from split_translator.layout import LAYOUT_DEFAULT, LAYOUT_WIDE
from split_translator.flashcard_editor_base import SenseRow

app = QApplication.instance() or QApplication([])

# What a Cambridge entry that points at no base form answers with.
NO_POINTER = json.dumps({"base": None})


class PosCodeTests(unittest.TestCase):
    def test_codes_are_at_most_three_letters(self):
        for code in SenseRow.POS_OPTIONS:
            self.assertLessEqual(len(code), 3, code)

    def test_codes_are_distinct(self):
        self.assertEqual(
            len(SenseRow.POS_OPTIONS), len(set(SenseRow.POS_OPTIONS))
        )

    def test_captured_codes_are_offered_by_the_editor(self):
        # The capture buttons write these codes straight into the sense combo,
        # so every mapped code has to be one the combo offers.
        for label, code in DictionaryPanel._POS_MAP.items():
            self.assertIn(code, SenseRow.POS_OPTIONS, label)


class CorrectionTests(unittest.TestCase):
    def _panel(self):
        return DictionaryPanel(QWebEngineProfile.defaultProfile())

    def _collect(self, panel):
        corrections, searches, unavailable = [], [], []
        panel.correction_applied.connect(
            lambda w, c: corrections.append((w, c))
        )
        panel.word_searched.connect(lambda w: searches.append(w))
        panel.correction_unavailable.connect(lambda w: unavailable.append(w))
        return corrections, searches, unavailable

    def test_correction_emits_wrong_and_corrected(self):
        # _handle_correction takes the JSON string the injected JS returns
        # ({"word": <correction>}); runJavaScript drops a bare object, so the
        # correction is carried as a JSON string (see the module conventions).
        panel = self._panel()
        corrections, searches, unavailable = self._collect(panel)
        panel.search_input.setText("recieve")
        panel._handle_correction(json.dumps({"word": "receive"}))
        self.assertEqual(corrections, [("recieve", "receive")])
        self.assertEqual(searches, ["receive"])
        self.assertEqual(unavailable, [])
        self.assertEqual(panel.search_input.text(), "receive")

    def test_unavailable_when_correction_equals_current_word(self):
        # The page's correction is the word already in the box, so there is
        # nothing to correct: no re-search, report it as unavailable.
        panel = self._panel()
        corrections, searches, unavailable = self._collect(panel)
        panel.search_input.setText("receive")
        panel._handle_correction(json.dumps({"word": "receive"}))
        self.assertEqual(corrections, [])
        self.assertEqual(searches, [])
        self.assertEqual(unavailable, ["receive"])

    def test_unavailable_when_no_correction_on_page(self):
        # An empty word (the "Showing results for" block was absent, e.g. the
        # meaning page hit an anti-bot wall) reports unavailable and re-searches
        # nothing.
        panel = self._panel()
        corrections, searches, unavailable = self._collect(panel)
        panel.search_input.setText("recieve")
        panel._handle_correction(json.dumps({"word": ""}))
        self.assertEqual(corrections, [])
        self.assertEqual(searches, [])
        self.assertEqual(unavailable, ["recieve"])

    def test_unavailable_when_result_is_none_or_malformed(self):
        # runJavaScript can hand back None (nothing returned) or non-JSON; both
        # are treated as no correction.
        panel = self._panel()
        corrections, searches, unavailable = self._collect(panel)
        panel.search_input.setText("recieve")
        panel._handle_correction(None)
        panel._handle_correction("not json")
        self.assertEqual(corrections, [])
        self.assertEqual(searches, [])
        self.assertEqual(unavailable, ["recieve", "recieve"])


class HeadwordSearchTests(unittest.TestCase):
    """A flashcard-selection lookup runs the search but records no history and
    does not arm the passive Cambridge auto-grab (which would overwrite the
    just-loaded card)."""

    def _panel(self):
        return DictionaryPanel(QWebEngineProfile.defaultProfile())

    def test_search_headword_does_not_emit_word_searched(self):
        panel = self._panel()
        searches = []
        panel.word_searched.connect(searches.append)
        panel.search_headword("address")
        # The box is filled so a following normal search would work, but no
        # word_searched fires (so the main window adds no history entry).
        self.assertEqual(panel.search_input.text(), "address")
        self.assertEqual(searches, [])

    def test_search_headword_does_not_arm_the_grab(self):
        panel = self._panel()
        panel.search_headword("address")
        self.assertFalse(panel._grab_gate.is_armed)

    def test_normal_search_still_emits_and_arms(self):
        panel = self._panel()
        searches = []
        panel.word_searched.connect(searches.append)
        panel.search_input.setText("address")
        panel.search()
        self.assertEqual(searches, ["address"])
        self.assertTrue(panel._grab_gate.is_armed)

    def _search_button(self, panel):
        # The Search button is a local in init_ui, not stored on the panel; find
        # it by its label so the test drives its real clicked() wiring.
        from PySide6.QtWidgets import QPushButton

        for button in panel.findChildren(QPushButton):
            if button.text() == "Search":
                return button
        self.fail("Search button not found")

    def test_search_button_click_emits_word_searched(self):
        # Regression: QPushButton.clicked emits a `checked` bool. If the button is
        # bound straight to search(), that bool lands on emit_searched=False and
        # the lookup silently records no history and drives no book search. The
        # button must emit word_searched exactly like pressing Enter.
        panel = self._panel()
        searches = []
        panel.word_searched.connect(searches.append)
        panel.search_input.setText("address")
        self._search_button(panel).click()
        self.assertEqual(searches, ["address"])

    def test_return_pressed_emits_word_searched(self):
        panel = self._panel()
        searches = []
        panel.word_searched.connect(searches.append)
        panel.search_input.setText("address")
        panel.search_input.returnPressed.emit()
        self.assertEqual(searches, ["address"])


class AudioPlaybackTests(unittest.TestCase):
    def _panel(self):
        return DictionaryPanel(QWebEngineProfile.defaultProfile())

    def _stub_player(self, panel):
        # Record the URLs handed to the media player without playing anything.
        played = []

        class FakePlayer:
            def setAudioOutput(self, _out):
                pass

            def stop(self):
                pass

            def setSource(self, url):
                played.append(url.toString())

            def play(self):
                pass

        panel._player = FakePlayer()
        panel._audio_output = object()  # already built, so no real one is made
        return played

    def test_plays_the_nth_url_one_based(self):
        panel = self._panel()
        played = self._stub_player(panel)
        urls = ["https://x/uk1.mp3", "https://x/us1.mp3", "https://x/uk2.mp3"]
        panel._play_audio_url(json.dumps(urls), 2)
        # setSource is called twice per play: once with "" to clear, then the URL.
        self.assertEqual(played, ["", "https://x/us1.mp3"])

    def test_first_url_is_audio_num_one(self):
        panel = self._panel()
        played = self._stub_player(panel)
        urls = ["https://x/uk1.mp3", "https://x/us1.mp3"]
        panel._play_audio_url(json.dumps(urls), 1)
        self.assertEqual(played, ["", "https://x/uk1.mp3"])

    def test_out_of_range_index_plays_nothing(self):
        panel = self._panel()
        played = self._stub_player(panel)
        urls = ["https://x/uk1.mp3"]
        panel._play_audio_url(json.dumps(urls), 5)  # only one clip on the page
        self.assertEqual(played, [])

    def test_null_url_entry_plays_nothing(self):
        panel = self._panel()
        played = self._stub_player(panel)
        urls = [None]  # an <audio> with no resolvable source
        panel._play_audio_url(json.dumps(urls), 1)
        self.assertEqual(played, [])

    def test_malformed_payload_plays_nothing(self):
        panel = self._panel()
        played = self._stub_player(panel)
        panel._play_audio_url("not json", 1)
        self.assertEqual(played, [])

    def test_empty_payload_plays_nothing(self):
        panel = self._panel()
        played = self._stub_player(panel)
        panel._play_audio_url("", 1)
        self.assertEqual(played, [])


class _LoadReport:
    """Stands in for QWebEngineLoadingInfo, which only Qt constructs. Headers
    are given as name to value and handed over in Qt's own shape: a QByteArray
    name mapped to a list of QByteArray values."""

    def __init__(self, status, url, headers=None):
        from PySide6.QtCore import QByteArray, QUrl

        self._status = status
        self._url = QUrl(url)
        self._headers = {
            QByteArray(name.encode()): [QByteArray(value.encode())]
            for name, value in (headers or {}).items()
        }

    def status(self):
        return self._status

    def url(self):
        return self._url

    def responseHeaders(self):
        return self._headers


def _spy_grabs(panel):
    """Record the passive grabs instead of reading a page."""
    calls = []
    panel.grab_grammar = lambda: calls.append("grammar")
    panel.grab_pronunciation = lambda: calls.append("pronunciation")
    return calls


def _load_page(panel, url, ok=True, challenge=False, started_at=None):
    """One Cambridge English load as Qt reports it, started and then finished.
    Every Cambridge response comes through Cloudflare; a check is a failed load
    (HTTP 403) that Cloudflare also marks with cf-mitigated. A redirected load
    starts at one address and ends at another."""
    from PySide6.QtWebEngineCore import QWebEngineLoadingInfo

    status = QWebEngineLoadingInfo.LoadStatus
    panel._on_english_loading(
        _LoadReport(status.LoadStartedStatus, started_at or url)
    )
    headers = {"Server": "cloudflare"}
    if challenge:
        headers["CF-Mitigated"] = "challenge"
    end = status.LoadSucceededStatus if ok else status.LoadFailedStatus
    panel._on_english_loading(_LoadReport(end, url, headers))


class AppSearchGrabGateTests(unittest.TestCase):
    """The passive auto-grab (grammar + pronunciation) must fire only for the
    Cambridge English load started by the app's own search bar, not for a load
    the user causes by searching or clicking inside the page. A Cloudflare
    check standing in front of that page does not use the grab up: it passes to
    the page that replaces the check."""

    RUN = "https://dictionary.cambridge.org/dictionary/english/run"
    WALK = "https://dictionary.cambridge.org/dictionary/english/walk"

    def _panel(self):
        panel = DictionaryPanel(QWebEngineProfile.defaultProfile())
        # Every page in these tests is an entry in its own right, so it points
        # at no base form (the pointer pages are BaseFormFollowTests).
        panel._read_base_form = lambda callback: callback(NO_POINTER)
        return panel

    def test_grab_runs_for_the_app_search_load(self):
        panel = self._panel()
        calls = _spy_grabs(panel)
        panel.search_input.setText("run")
        panel.search()  # arms the grab
        _load_page(panel, self.RUN)
        self.assertEqual(calls, ["grammar", "pronunciation"])

    def test_second_load_after_a_search_does_not_grab(self):
        panel = self._panel()
        calls = _spy_grabs(panel)
        panel.search_input.setText("run")
        panel.search()
        _load_page(panel, self.RUN)  # app search load, grabs
        calls.clear()
        _load_page(panel, self.WALK)  # manual in-page navigation, must not grab
        self.assertEqual(calls, [])

    def test_load_without_a_preceding_search_does_not_grab(self):
        panel = self._panel()
        calls = _spy_grabs(panel)
        _load_page(panel, self.RUN)  # user typed in Cambridge's own box
        self.assertEqual(calls, [])

    def test_failed_app_search_load_spends_the_grab(self):
        # A failed load (no connection) still spends the grab, so it does not
        # leak onto the next, manual load.
        panel = self._panel()
        calls = _spy_grabs(panel)
        panel.search_input.setText("run")
        panel.search()
        _load_page(panel, self.RUN, ok=False)  # app search load failed, no grab
        self.assertEqual(calls, [])
        _load_page(panel, self.RUN)  # next load is manual, must not grab
        self.assertEqual(calls, [])

    def test_a_bot_check_passes_the_grab_to_the_page_behind_it(self):
        # The report: held on Cambridge's check, the card was never filled,
        # because the check was the load that used the grab up.
        panel = self._panel()
        calls = _spy_grabs(panel)
        panel.search_input.setText("run")
        panel.search()
        _load_page(panel, self.RUN, ok=False, challenge=True)  # "Just a moment..."
        self.assertEqual(calls, [])
        # Passed: the answer goes back to the same address, with a token.
        _load_page(panel, self.RUN, started_at=self.RUN + "?__cf_chl_f_tk=abc")
        self.assertEqual(calls, ["grammar", "pronunciation"])

    def test_back_from_a_bot_check_does_not_grab(self):
        panel = self._panel()
        calls = _spy_grabs(panel)
        panel.search_input.setText("run")
        panel.search()
        _load_page(panel, self.RUN, ok=False, challenge=True)
        _load_page(panel, self.WALK)  # the previous word's page
        self.assertEqual(calls, [])

    def test_a_card_selected_during_a_bot_check_is_not_grabbed(self):
        # Even a card for the very word the check holds the grab for: its page
        # loads at the same address, and must not overwrite the loaded card.
        panel = self._panel()
        calls = _spy_grabs(panel)
        panel.search_input.setText("run")
        panel.search()
        _load_page(panel, self.RUN, ok=False, challenge=True)
        panel.search_headword("run")
        _load_page(panel, self.RUN)
        self.assertEqual(calls, [])

    def test_direct_grab_calls_are_unaffected(self):
        # New-from-word and the toggle path call the grabbers directly; those
        # never go through the gate.
        panel = self._panel()
        pron, gram = [], []
        panel.pronunciation_grabbed.connect(lambda d: pron.append(d))
        panel.grammar_grabbed.connect(lambda d: gram.append(d))
        # No search armed the flag, yet a direct call still emits.
        panel._on_pronunciation("")
        panel._on_grammar("")
        self.assertEqual(len(pron), 1)
        self.assertEqual(len(gram), 1)


class BaseFormTests(unittest.TestCase):
    """What counts as a base form worth following. The answer is read off a web
    page, so what it names is checked before anything is loaded from it."""

    SURMISE = "https://dictionary.cambridge.org/dictionary/english/surmise"

    def test_a_linked_pointer_is_a_base_form(self):
        base = _parse_base_form(
            json.dumps({"base": {"word": "surmise", "url": self.SURMISE}})
        )
        self.assertEqual(base, {"word": "surmise", "url": self.SURMISE})

    def test_a_page_that_points_nowhere_has_no_base_form(self):
        # An entry in its own right: "surmise" itself, "running", "better".
        self.assertIsNone(_parse_base_form(NO_POINTER))

    def test_a_link_away_from_cambridge_is_refused(self):
        for url in (
            "https://example.com/dictionary/english/surmise",
            "http://dictionary.cambridge.org/dictionary/english/surmise",
            "",
        ):
            self.assertIsNone(
                _parse_base_form(
                    json.dumps({"base": {"word": "surmise", "url": url}})
                ),
                url,
            )

    def test_a_pointer_naming_no_word_is_refused(self):
        self.assertIsNone(
            _parse_base_form(
                json.dumps({"base": {"word": " ", "url": self.SURMISE}})
            )
        )

    def test_an_empty_or_malformed_answer_is_no_base_form(self):
        # runJavaScript hands back None when the page returned nothing.
        self.assertIsNone(_parse_base_form(None))
        self.assertIsNone(_parse_base_form(""))
        self.assertIsNone(_parse_base_form("not json"))


class BaseFormFollowTests(unittest.TestCase):
    """Cambridge answers a search for an inflected form with an entry that only
    points at the base form: "surmised" is served as "past simple and past
    participle of surmise", at its own address. The app follows that pointer,
    so both Cambridge views show the base word and the card is filled from that
    entry rather than from the inflected one."""

    SURMISED = "https://dictionary.cambridge.org/dictionary/english/surmised"
    SURMISE = "https://dictionary.cambridge.org/dictionary/english/surmise"
    SURMISE_PL = (
        "https://dictionary.cambridge.org/pl/dictionary/english-polish/surmise"
    )
    POINTER = json.dumps({"base": {"word": "surmise", "url": SURMISE}})

    def _panel(self, answer):
        panel = DictionaryPanel(QWebEngineProfile.defaultProfile())
        # Stand in for the page: no display and no network here, so the read of
        # a live Cambridge entry is answered in its place.
        panel._read_base_form = lambda callback: callback(answer)
        return panel

    def _watch_urls(self, panel):
        """Record where the two Cambridge views are pointed, and load nothing
        anywhere (the other four views are not part of this)."""
        urls = {"en": [], "pl": []}
        for view in panel._all_views():
            view.setUrl = lambda url: None
        panel.cambridge_en_view.setUrl = lambda url: urls["en"].append(
            url.toString()
        )
        panel.cambridge_pl_view.setUrl = lambda url: urls["pl"].append(
            url.toString()
        )
        return urls

    def _search(self, panel, word):
        panel.search_input.setText(word)
        panel.search()

    def test_a_pointer_page_is_followed_in_both_cambridge_views(self):
        panel = self._panel(self.POINTER)
        urls = self._watch_urls(panel)
        calls = _spy_grabs(panel)
        self._search(panel, "surmised")
        _load_page(panel, self.SURMISED)
        # Nothing is taken off the inflected entry: the base word is loaded.
        self.assertEqual(calls, [])
        self.assertEqual(urls["en"][-1], self.SURMISE)
        self.assertEqual(urls["pl"][-1], self.SURMISE_PL)

    def test_the_base_entry_is_grabbed_once_it_arrives(self):
        panel = self._panel(self.POINTER)
        self._watch_urls(panel)
        calls = _spy_grabs(panel)
        self._search(panel, "surmised")
        _load_page(panel, self.SURMISED)  # the pointer, followed
        _load_page(panel, self.SURMISE)  # the entry the app then asked for
        self.assertEqual(calls, ["grammar", "pronunciation"])

    def test_a_search_follows_one_pointer_at_most(self):
        # A base entry that points on again is grabbed as it is, so two entries
        # pointing at each other cannot loop.
        panel = self._panel(self.POINTER)
        urls = self._watch_urls(panel)
        calls = _spy_grabs(panel)
        self._search(panel, "surmised")
        _load_page(panel, self.SURMISED)
        followed = len(urls["en"])
        _load_page(panel, self.SURMISE)
        self.assertEqual(calls, ["grammar", "pronunciation"])
        self.assertEqual(len(urls["en"]), followed)

    def test_an_entry_page_is_grabbed_and_not_followed(self):
        panel = self._panel(NO_POINTER)
        urls = self._watch_urls(panel)
        calls = _spy_grabs(panel)
        self._search(panel, "surmise")
        searched = len(urls["en"])
        _load_page(panel, self.SURMISE)
        self.assertEqual(calls, ["grammar", "pronunciation"])
        self.assertEqual(len(urls["en"]), searched)

    def test_an_answer_arriving_after_the_next_search_is_dropped(self):
        # The read is asynchronous, and by the time this page answers, another
        # search owns the views. That search has its own page coming.
        panel = self._panel(self.POINTER)
        urls = self._watch_urls(panel)
        calls = _spy_grabs(panel)
        held = []
        panel._read_base_form = held.append  # answer nothing for now
        self._search(panel, "surmised")
        _load_page(panel, self.SURMISED)
        self._search(panel, "walk")
        searched = len(urls["en"])
        held[0](self.POINTER)  # the page before last, answering late
        self.assertEqual(calls, [])
        self.assertEqual(len(urls["en"]), searched)

    def test_a_flashcard_lookup_reads_no_base_form(self):
        # Selecting a card grabs nothing, so there is nothing to follow either:
        # the card keeps the headword it was saved with.
        panel = self._panel(self.POINTER)
        urls = self._watch_urls(panel)
        calls = _spy_grabs(panel)
        reads = []
        panel._read_base_form = reads.append
        panel.search_headword("surmised")
        searched = len(urls["en"])
        _load_page(panel, self.SURMISED)
        self.assertEqual(reads, [])
        self.assertEqual(calls, [])
        self.assertEqual(len(urls["en"]), searched)


class PronunciationCaptureBridgeTests(unittest.TestCase):
    """A pronunciation block's clip and its notation are captured by separate
    buttons, so they travel as separate signals all the way to the editor."""

    def test_bridge_captureAudio_emits_region_and_url(self):
        from split_translator.capture_bridge import CaptureBridge

        bridge = CaptureBridge()
        got = []
        bridge.audio_capture_requested.connect(
            lambda region, url: got.append((region, url))
        )
        bridge.captureAudio("uk", "https://example/uk.mp3")
        self.assertEqual(got, [("uk", "https://example/uk.mp3")])

    def test_bridge_captureIpa_emits_region_and_ipa(self):
        from split_translator.capture_bridge import CaptureBridge

        bridge = CaptureBridge()
        got = []
        bridge.ipa_capture_requested.connect(
            lambda region, ipa: got.append((region, ipa))
        )
        bridge.captureIpa("uk", "/uk/")
        self.assertEqual(got, [("uk", "/uk/")])

    def test_capturing_a_clip_does_not_announce_a_notation(self):
        from split_translator.capture_bridge import CaptureBridge

        bridge = CaptureBridge()
        ipa_seen = []
        bridge.ipa_capture_requested.connect(lambda *a: ipa_seen.append(a))
        bridge.captureAudio("uk", "https://example/uk.mp3")
        self.assertEqual(ipa_seen, [])

    def test_panel_relays_audio_capture(self):
        panel = DictionaryPanel(QWebEngineProfile.defaultProfile())
        got = []
        panel.audio_capture_requested.connect(
            lambda region, url: got.append((region, url))
        )
        # The page button would call captureAudio on the bridge; simulate it.
        panel.capture_bridge.captureAudio("us", "https://example/us.mp3")
        self.assertEqual(got, [("us", "https://example/us.mp3")])

    def test_panel_relays_ipa_capture(self):
        panel = DictionaryPanel(QWebEngineProfile.defaultProfile())
        got = []
        panel.ipa_capture_requested.connect(
            lambda region, ipa: got.append((region, ipa))
        )
        panel.capture_bridge.captureIpa("us", "/us/")
        self.assertEqual(got, [("us", "/us/")])


if __name__ == "__main__":
    unittest.main()


class DictionaryLayoutTests(unittest.TestCase):
    def _panel(self, layout=LAYOUT_DEFAULT):
        return DictionaryPanel(
            QWebEngineProfile.defaultProfile(), layout=layout
        )

    def _labels(self, tabs):
        return [tabs.tabText(i) for i in range(tabs.count())]

    def test_default_layout_keeps_the_four_squares(self):
        panel = self._panel()
        self.assertIsNone(panel.top_tabs)
        self.assertIsNone(panel.bottom_tabs)
        self.assertEqual(
            self._labels(panel.google_tabs), ["Meaning", "bab.la", "diki"]
        )

    def test_wide_layout_stacks_two_tabbed_squares(self):
        panel = self._panel(LAYOUT_WIDE)
        self.assertIsNone(panel.google_tabs)
        self.assertEqual(
            self._labels(panel.top_tabs),
            ["Cambridge EN", "Meaning", "bab.la", "diki"],
        )
        self.assertEqual(
            self._labels(panel.bottom_tabs), ["Cambridge PL", "po polsku"]
        )

    def test_wide_layout_opens_on_the_cambridge_tabs(self):
        panel = self._panel(LAYOUT_WIDE)
        self.assertIs(panel.top_tabs.currentWidget(), panel.cambridge_en_view)
        self.assertIs(
            panel.bottom_tabs.currentWidget(), panel.cambridge_pl_view
        )

    def test_switching_re_parents_the_very_same_views(self):
        # Nothing is rebuilt, so no page reloads and no search is re-run.
        panel = self._panel()
        before = panel._all_views()
        panel.set_layout(LAYOUT_WIDE)
        self.assertEqual(panel._all_views(), before)
        self.assertIs(panel.top_tabs.widget(0), before[0])

    def test_switching_back_restores_the_four_squares(self):
        panel = self._panel(LAYOUT_WIDE)
        panel.set_layout(LAYOUT_DEFAULT)
        self.assertIsNone(panel.top_tabs)
        self.assertEqual(
            self._labels(panel.google_tabs), ["Meaning", "bab.la", "diki"]
        )

    def test_asking_for_the_layout_it_is_already_in_rebuilds_nothing(self):
        # The window applies the stored layout on open, so this call is the
        # common case, not an odd one.
        panel = self._panel()
        tabs = panel.google_tabs
        panel.set_layout(LAYOUT_DEFAULT)
        self.assertIs(panel.google_tabs, tabs)

    def test_an_unreadable_layout_builds_the_default_view(self):
        panel = self._panel("sideways")
        self.assertIsNone(panel.top_tabs)
        self.assertIsNotNone(panel.google_tabs)

    def test_a_search_still_loads_all_six_views_in_the_wide_layout(self):
        panel = self._panel(LAYOUT_WIDE)
        panel._read_base_form = lambda callback: callback(NO_POINTER)
        urls = []
        for view in panel._all_views():
            view.setUrl = lambda url, seen=urls: seen.append(url.toString())
        panel.search_input.setText("surmise")
        panel.search()
        self.assertEqual(len(urls), 6)
        self.assertTrue(any("dictionary.cambridge.org" in url for url in urls))
