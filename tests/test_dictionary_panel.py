import json
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from PySide6.QtWebEngineCore import QWebEngineProfile

from split_translator.dictionary_panel import DictionaryPanel

app = QApplication.instance() or QApplication([])


class CorrectionTests(unittest.TestCase):
    def _panel(self):
        return DictionaryPanel(QWebEngineProfile.defaultProfile())

    def _collect(self, panel):
        corrections, searches = [], []
        panel.correction_applied.connect(
            lambda w, c: corrections.append((w, c))
        )
        panel.word_searched.connect(lambda w: searches.append(w))
        return corrections, searches

    def test_correction_emits_wrong_and_corrected(self):
        panel = self._panel()
        corrections, searches = self._collect(panel)
        panel.search_input.setText("recieve")
        panel._handle_correction("receive meaning")
        self.assertEqual(corrections, [("recieve", "receive")])
        self.assertEqual(searches, ["receive"])
        self.assertEqual(panel.search_input.text(), "receive")

    def test_no_emit_when_correction_equals_current_word(self):
        panel = self._panel()
        corrections, searches = self._collect(panel)
        panel.search_input.setText("receive")
        panel._handle_correction("receive meaning")
        self.assertEqual(corrections, [])  # nothing to correct
        self.assertEqual(searches, ["receive"])

    def test_no_action_when_no_correction_found(self):
        panel = self._panel()
        corrections, searches = self._collect(panel)
        panel.search_input.setText("recieve")
        panel._handle_correction(None)
        self.assertEqual(corrections, [])
        self.assertEqual(searches, [])


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
