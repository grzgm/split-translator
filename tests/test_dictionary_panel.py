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


if __name__ == "__main__":
    unittest.main()
