import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from split_translator.flashcard_panel import FlashcardPanel
from split_translator.flashcards import Card, FlashcardStore, Link

app = QApplication.instance() or QApplication([])


class SavedFilterTests(unittest.TestCase):
    def _panel(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        store = FlashcardStore(Path(tmp.name) / "f.json")
        store.cards = [
            Card(headword="address", id="a"),
            Card(headword="receive", id="b"),
            Card(headword="recede", id="c"),
        ]
        panel = FlashcardPanel(store)
        panel._refresh_saved_list()
        return panel, store

    def _visible(self, panel):
        return [
            panel.saved_list.item(i).text()
            for i in range(panel.saved_list.count())
            if not panel.saved_list.item(i).isHidden()
        ]

    def test_filter_narrows_to_matching_rows(self):
        panel, _ = self._panel()
        panel.saved_filter.setText("rec")
        self.assertEqual(set(self._visible(panel)), {"receive", "recede"})

    def test_filter_is_case_insensitive(self):
        panel, _ = self._panel()
        panel.saved_filter.setText("ADDR")
        self.assertEqual(self._visible(panel), ["address"])

    def test_empty_filter_shows_all(self):
        panel, _ = self._panel()
        panel.saved_filter.setText("rec")
        panel.saved_filter.setText("")
        self.assertEqual(len(self._visible(panel)), 3)


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


class LinkControlsTests(unittest.TestCase):
    def _panel(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        store = FlashcardStore(Path(tmp.name) / "f.json")
        self.addCleanup(store.shutdown)
        store.cards = [
            Card(headword="big", id="big"),
            Card(headword="large", id="large"),
            Card(headword="small", id="small"),
        ]
        panel = FlashcardPanel(store)
        panel._refresh_saved_list()
        return panel, store

    def _check(self, panel, card_id):
        from PySide6.QtCore import Qt
        for i in range(panel.saved_list.count()):
            item = panel.saved_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == card_id:
                item.setCheckState(Qt.CheckState.Checked)

    def _select_type(self, panel, key):
        from PySide6.QtCore import Qt
        for i in range(panel.link_type_combo.count()):
            if panel.link_type_combo.itemData(i, Qt.ItemDataRole.UserRole) == key:
                panel.link_type_combo.setCurrentIndex(i)

    def test_link_button_disabled_without_loaded_card(self):
        panel, _ = self._panel()
        self.assertFalse(panel.link_button.isEnabled())

    def test_link_button_enabled_after_loading(self):
        panel, store = self._panel()
        panel.load_card(store.cards[0])  # big
        self.assertTrue(panel.link_button.isEnabled())

    def test_link_selected_stages_links(self):
        panel, store = self._panel()
        panel.load_card(store.cards[0])  # big
        self._check(panel, "large")
        self._check(panel, "small")
        self._select_type(panel, "synonym")
        panel._on_link_selected()
        partners = {panel._partner_id(l) for l in panel._staged_links}
        self.assertEqual(partners, {"large", "small"})
        self.assertTrue(all(l.type == "synonym" for l in panel._staged_links))

    def test_save_persists_staged_links_symmetrically(self):
        panel, store = self._panel()
        panel.load_card(store.cards[0])  # big
        self._check(panel, "large")
        self._select_type(panel, "synonym")
        panel._on_link_selected()
        panel.save_card()
        store.shutdown()
        self.assertEqual(len(store.links_for("big")), 1)
        self.assertEqual(len(store.links_for("large")), 1)  # symmetric

    def test_removing_a_link_then_saving_unlinks(self):
        panel, store = self._panel()
        store.links = [Link("big", "large", "synonym")]
        panel.load_card(store.cards[0])  # big, with one link
        self.assertEqual(len(panel._staged_links), 1)
        panel._remove_staged_link(panel._staged_links[0])
        panel.save_card()
        store.shutdown()
        self.assertEqual(store.links_for("big"), [])

    def test_relinking_same_partner_updates_type(self):
        panel, store = self._panel()
        panel.load_card(store.cards[0])  # big
        self._check(panel, "large")
        self._select_type(panel, "synonym")
        panel._on_link_selected()
        self._check(panel, "large")
        self._select_type(panel, "antonym")
        panel._on_link_selected()
        self.assertEqual(len(panel._staged_links), 1)
        self.assertEqual(panel._staged_links[0].type, "antonym")

    def test_save_emits_cards_changed_once(self):
        panel, store = self._panel()
        panel.load_card(store.cards[0])  # big
        self._check(panel, "large")
        self._select_type(panel, "synonym")
        panel._on_link_selected()
        fired = []
        store.cards_changed.connect(lambda: fired.append(True))
        panel.save_card()
        store.shutdown()
        self.assertEqual(len(fired), 1)  # one write, not two
