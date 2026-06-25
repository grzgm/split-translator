import os
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from split_translator.history import HistoryPanel

app = QApplication.instance() or QApplication([])


class HistoryRemoveWordTests(unittest.TestCase):
    def _panel(self):
        tmp = tempfile.TemporaryDirectory()
        panel = HistoryPanel(Path(tmp.name) / "history.json")
        # Wait for any in-flight save thread before the temp dir is removed, so
        # the worker is never destroyed mid-write.
        self.addCleanup(tmp.cleanup)
        self.addCleanup(panel.shutdown)
        return panel

    def test_remove_word_drops_entry(self):
        panel = self._panel()
        panel.add_to_history("recieve")
        panel.add_to_history("dog")
        panel.remove_word("recieve")
        words = [e["word"] for e in panel.history]
        self.assertEqual(words, ["dog"])

    def test_remove_word_removes_all_matches(self):
        panel = self._panel()
        # Two entries for the same word on different days.
        old = (datetime.now() - timedelta(days=3)).isoformat()
        panel.history = [
            {"word": "recieve", "date": old},
            {"word": "recieve", "date": datetime.now().isoformat()},
            {"word": "cat", "date": datetime.now().isoformat()},
        ]
        panel.remove_word("recieve")
        self.assertEqual([e["word"] for e in panel.history], ["cat"])

    def test_remove_word_missing_is_noop(self):
        panel = self._panel()
        panel.add_to_history("dog")
        before = list(panel.history)
        panel.remove_word("nothere")
        self.assertEqual(panel.history, before)

    def test_correction_flow_leaves_only_corrected(self):
        # Simulate the main-window wiring: remove wrong, then add corrected.
        panel = self._panel()
        panel.add_to_history("recieve")  # the misspelled lookup
        panel.remove_word("recieve")  # correction_applied handler
        panel.add_to_history("receive")  # the corrected re-search
        self.assertEqual([e["word"] for e in panel.history], ["receive"])


if __name__ == "__main__":
    unittest.main()
