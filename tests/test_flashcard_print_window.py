import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from split_translator.flashcard_print_window import FlashcardPrintWindow
from split_translator.flashcards import Card, FlashcardStore

app = QApplication.instance() or QApplication([])


class FlashcardPrintWindowTests(unittest.TestCase):
    def _window(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        store = FlashcardStore(Path(tmp.name) / "f.json")
        self.addCleanup(store.shutdown)
        store.cards = [Card(headword="alpha", id="a"), Card(headword="bravo", id="b")]
        win = FlashcardPrintWindow(store)
        win.panel._refresh_saved_list()
        return win, store

    def test_has_panel_and_view(self):
        win, _ = self._window()
        self.assertIsNotNone(win.panel)
        self.assertIsNotNone(win.print_view)

    def test_is_not_a_dock(self):
        # A plain top-level QWidget window, not a QDockWidget.
        from PySide6.QtWidgets import QDockWidget
        win, _ = self._window()
        self.assertNotIsInstance(win, QDockWidget)

    def test_selecting_a_card_sets_it_on_the_view(self):
        win, _ = self._window()
        item = None
        for i in range(win.panel.saved_list.count()):
            it = win.panel.saved_list.item(i)
            if it.data(Qt.ItemDataRole.UserRole) == "a":
                item = it
        item.setCheckState(Qt.CheckState.Checked)
        self.assertEqual([c.id for c in win.print_view._cards], ["a"])


if __name__ == "__main__":
    unittest.main()
