import os
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
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

    def test_delete_row_removes_the_row_asked_for(self):
        # The row clicked, not the first entry carrying its word. The same word
        # holds two entries once it is looked up again on a later day, and
        # deleting the older row used to take the newer one instead.
        panel = self._panel()
        old = (datetime.now() - timedelta(days=3)).isoformat()
        now = datetime.now().isoformat()
        panel.history = [
            {"word": "dog", "date": now},
            {"word": "recieve", "date": now},
            {"word": "dog", "date": old},  # the same word, from Tuesday
        ]
        panel.update_history_list()
        panel.delete_row(2)  # the older "dog"
        self.assertEqual(
            [(e["word"], e["date"]) for e in panel.history],
            [("dog", now), ("recieve", now)],
        )
        self.assertEqual(panel.history_list.count(), 2)

    def test_delete_row_keeps_the_list_and_the_history_in_step(self):
        panel = self._panel()
        panel.add_to_history("one")
        panel.add_to_history("two")
        panel.add_to_history("three")  # newest first: three, two, one
        panel.delete_row(1)
        self.assertEqual([e["word"] for e in panel.history], ["three", "one"])
        rows = [
            panel.history_list.item(i).data(Qt.ItemDataRole.UserRole)["word"]
            for i in range(panel.history_list.count())
        ]
        self.assertEqual(rows, ["three", "one"])

    def test_delete_row_out_of_range_does_nothing(self):
        panel = self._panel()
        panel.add_to_history("dog")
        panel.delete_row(5)
        panel.delete_row(-1)
        self.assertEqual([e["word"] for e in panel.history], ["dog"])

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
