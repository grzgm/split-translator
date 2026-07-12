import json
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from PySide6.QtWebEngineCore import QWebEngineProfile

from split_translator.dictionary_panel import DictionaryPanel
from split_translator.flashcard_editor_base import SenseRow

app = QApplication.instance() or QApplication([])


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
        self.assertFalse(panel._app_search_pending)

    def test_normal_search_still_emits_and_arms(self):
        panel = self._panel()
        searches = []
        panel.word_searched.connect(searches.append)
        panel.search_input.setText("address")
        panel.search()
        self.assertEqual(searches, ["address"])
        self.assertTrue(panel._app_search_pending)

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


class AppSearchGrabGateTests(unittest.TestCase):
    """The passive auto-grab (grammar + pronunciation) must fire only for the
    Cambridge English load started by the app's own search bar, not for a load
    the user causes by searching or clicking inside the page."""

    def _panel(self):
        return DictionaryPanel(QWebEngineProfile.defaultProfile())

    def _spy_grabs(self, panel):
        calls = []
        panel.grab_grammar = lambda: calls.append("grammar")
        panel.grab_pronunciation = lambda: calls.append("pronunciation")
        return calls

    def test_grab_runs_for_the_app_search_load(self):
        panel = self._panel()
        calls = self._spy_grabs(panel)
        panel.search_input.setText("run")
        panel.search()  # arms the app-search flag
        panel._on_english_loaded(True)
        self.assertEqual(calls, ["grammar", "pronunciation"])

    def test_second_load_after_a_search_does_not_grab(self):
        panel = self._panel()
        calls = self._spy_grabs(panel)
        panel.search_input.setText("run")
        panel.search()
        panel._on_english_loaded(True)  # app search load, grabs
        calls.clear()
        panel._on_english_loaded(True)  # manual in-page navigation, must not grab
        self.assertEqual(calls, [])

    def test_load_without_a_preceding_search_does_not_grab(self):
        panel = self._panel()
        calls = self._spy_grabs(panel)
        panel._on_english_loaded(True)  # user typed in Cambridge's own box
        self.assertEqual(calls, [])

    def test_failed_app_search_load_consumes_the_flag(self):
        # A failed load (ok=False) still consumes the armed flag, so it does not
        # leak onto the next, manual load.
        panel = self._panel()
        calls = self._spy_grabs(panel)
        panel.search_input.setText("run")
        panel.search()
        panel._on_english_loaded(False)  # app search load failed, no grab
        self.assertEqual(calls, [])
        panel._on_english_loaded(True)  # next load is manual, must not grab
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


class AudioCaptureBridgeTests(unittest.TestCase):
    def test_bridge_captureAudio_emits_region_url_and_ipa(self):
        from split_translator.capture_bridge import CaptureBridge

        bridge = CaptureBridge()
        got = []
        bridge.audio_capture_requested.connect(
            lambda region, url, ipa: got.append((region, url, ipa))
        )
        bridge.captureAudio("uk", "https://example/uk.mp3", "/uk/")
        self.assertEqual(got, [("uk", "https://example/uk.mp3", "/uk/")])

    def test_panel_relays_audio_capture(self):
        panel = DictionaryPanel(QWebEngineProfile.defaultProfile())
        got = []
        panel.audio_capture_requested.connect(
            lambda region, url, ipa: got.append((region, url, ipa))
        )
        # The page button would call captureAudio on the bridge; simulate it.
        panel.capture_bridge.captureAudio("us", "https://example/us.mp3", "/us/")
        self.assertEqual(got, [("us", "https://example/us.mp3", "/us/")])


if __name__ == "__main__":
    unittest.main()
