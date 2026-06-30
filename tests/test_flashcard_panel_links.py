import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from split_translator.flashcard_panel import FlashcardPanel
from split_translator.flashcards import Card, FlashcardStore, Link

app = QApplication.instance() or QApplication([])


class LinkSectionTests(unittest.TestCase):
    def _panel(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        store = FlashcardStore(Path(tmp.name) / "f.json")
        store.cards = [
            Card(headword="big", id="big"),
            Card(headword="large", id="large"),
            Card(headword="small", id="small"),
        ]
        store.links = [Link("big", "large", "synonym"),
                       Link("big", "small", "antonym")]
        panel = FlashcardPanel(store)
        panel._refresh_saved_list()
        return panel, store

    def test_loading_a_card_populates_staged_links(self):
        panel, store = self._panel()
        panel.load_card(store.cards[0])  # big
        self.assertEqual(len(panel._staged_links), 2)

    def test_link_rows_show_partner_headwords(self):
        panel, store = self._panel()
        panel.load_card(store.cards[0])  # big
        labels = panel._link_row_labels()
        self.assertIn("large", labels)
        self.assertIn("small", labels)

    def test_reset_clears_staged_links(self):
        panel, store = self._panel()
        panel.load_card(store.cards[0])
        panel._reset_editor()
        self.assertEqual(panel._staged_links, [])
