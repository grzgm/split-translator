import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from split_translator.flashcard_print_panel import FlashcardPrintPanel
from split_translator.flashcards import Card, FlashcardStore

app = QApplication.instance() or QApplication([])


class FlashcardPrintPanelTests(unittest.TestCase):
    def _panel(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        store = FlashcardStore(Path(tmp.name) / "f.json")
        self.addCleanup(store.shutdown)
        store.cards = [
            Card(headword="alpha", id="a"),
            Card(headword="bravo", id="b"),
            Card(headword="charlie", id="c"),
        ]
        panel = FlashcardPrintPanel(store)
        panel._refresh_saved_list()
        return panel, store

    def _item(self, panel, card_id):
        for i in range(panel.saved_list.count()):
            it = panel.saved_list.item(i)
            if it.data(Qt.ItemDataRole.UserRole) == card_id:
                return it
        raise AssertionError(f"no row for {card_id}")

    def test_no_selection_is_empty(self):
        panel, _ = self._panel()
        self.assertEqual(panel.selected_cards(), [])

    def test_ticking_selects_that_card(self):
        panel, _ = self._panel()
        self._item(panel, "b").setCheckState(Qt.CheckState.Checked)
        self.assertEqual([c.id for c in panel.selected_cards()], ["b"])

    def test_selection_is_in_list_order(self):
        panel, _ = self._panel()
        self._item(panel, "c").setCheckState(Qt.CheckState.Checked)
        self._item(panel, "a").setCheckState(Qt.CheckState.Checked)
        self.assertEqual(panel.selected_ids(), ["a", "c"])

    def test_unticking_deselects(self):
        panel, _ = self._panel()
        self._item(panel, "a").setCheckState(Qt.CheckState.Checked)
        self._item(panel, "a").setCheckState(Qt.CheckState.Unchecked)
        self.assertEqual(panel.selected_cards(), [])

    def test_selection_changed_fires_on_tick(self):
        panel, _ = self._panel()
        seen = []
        panel.selection_changed.connect(lambda: seen.append(True))
        self._item(panel, "a").setCheckState(Qt.CheckState.Checked)
        self.assertTrue(seen)

    def test_no_link_controls(self):
        panel, _ = self._panel()
        self.assertFalse(hasattr(panel, "link_category_combo"))

    def test_editing_still_saves_to_store(self):
        panel, store = self._panel()
        panel.headword_input.setText("delta")
        panel.save_card()
        store.shutdown()
        self.assertTrue(any(c.headword == "delta" for c in store.cards))


if __name__ == "__main__":
    unittest.main()
