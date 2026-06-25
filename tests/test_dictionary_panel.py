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


if __name__ == "__main__":
    unittest.main()
