import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
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


class TickLinkingTests(unittest.TestCase):
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

    def _item(self, panel, card_id):
        for i in range(panel.saved_list.count()):
            it = panel.saved_list.item(i)
            if it.data(Qt.ItemDataRole.UserRole) == card_id:
                return it
        raise AssertionError(f"no row for {card_id}")

    def _set_category(self, panel, key):
        for i in range(panel.link_category_combo.count()):
            if panel.link_category_combo.itemData(i) == key:
                panel.link_category_combo.setCurrentIndex(i)
                return
        raise AssertionError(f"no category {key}")

    def test_loading_card_ticks_its_links_in_current_category(self):
        panel, store = self._panel()
        store.links = [Link("big", "large", "synonym")]
        self._set_category(panel, "synonym")
        panel.load_card(store.cards[0])  # big
        self.assertEqual(
            self._item(panel, "large").checkState(), Qt.CheckState.Checked
        )
        self.assertEqual(
            self._item(panel, "small").checkState(), Qt.CheckState.Unchecked
        )

    def test_switching_category_returns_the_ticks(self):
        panel, store = self._panel()
        store.links = [Link("big", "large", "synonym"),
                       Link("big", "small", "antonym")]
        panel.load_card(store.cards[0])  # big
        self._set_category(panel, "synonym")
        self.assertEqual(
            self._item(panel, "large").checkState(), Qt.CheckState.Checked)
        self.assertEqual(
            self._item(panel, "small").checkState(), Qt.CheckState.Unchecked)
        self._set_category(panel, "antonym")
        self.assertEqual(
            self._item(panel, "large").checkState(), Qt.CheckState.Unchecked)
        self.assertEqual(
            self._item(panel, "small").checkState(), Qt.CheckState.Checked)

    def test_ticking_stages_a_link_and_marks_dirty(self):
        panel, store = self._panel()
        panel.load_card(store.cards[0])  # big
        self._set_category(panel, "synonym")
        self._item(panel, "large").setCheckState(Qt.CheckState.Checked)
        partners = {panel._partner_id(l): l.type for l in panel._staged_links}
        self.assertEqual(partners.get("large"), "synonym")
        self.assertTrue(panel._dirty)

    def test_unticking_removes_the_staged_link(self):
        panel, store = self._panel()
        store.links = [Link("big", "large", "synonym")]
        panel.load_card(store.cards[0])  # big
        self._set_category(panel, "synonym")
        self._item(panel, "large").setCheckState(Qt.CheckState.Unchecked)
        self.assertEqual(panel._staged_links, [])
        self.assertTrue(panel._dirty)

    def test_tick_then_save_persists_symmetrically(self):
        panel, store = self._panel()
        panel.load_card(store.cards[0])  # big
        self._set_category(panel, "synonym")
        self._item(panel, "large").setCheckState(Qt.CheckState.Checked)
        panel.save_card()
        store.shutdown()
        self.assertEqual(len(store.links_for("big")), 1)
        self.assertEqual(len(store.links_for("large")), 1)

    def test_untick_then_save_unlinks(self):
        panel, store = self._panel()
        store.links = [Link("big", "large", "synonym")]
        panel.load_card(store.cards[0])  # big
        self._set_category(panel, "synonym")
        self._item(panel, "large").setCheckState(Qt.CheckState.Unchecked)
        panel.save_card()
        store.shutdown()
        self.assertEqual(store.links_for("big"), [])

    def test_toggling_checkbox_does_not_load_that_card(self):
        panel, store = self._panel()
        panel.load_card(store.cards[0])  # big loaded
        self._set_category(panel, "synonym")
        self._item(panel, "large").setCheckState(Qt.CheckState.Checked)
        # The loaded card is unchanged: ticking large did not load it.
        self.assertEqual(panel._loaded_card_id, "big")

    def test_clicking_row_text_loads(self):
        panel, store = self._panel()
        panel._on_saved_clicked(self._item(panel, "large"))
        self.assertEqual(panel._loaded_card_id, "large")

    def test_ticking_while_creating_new_card_persists_on_first_save(self):
        panel, store = self._panel()
        # brand-new card, never saved
        panel.headword_input.setText("huge")
        self._set_category(panel, "synonym")
        self._item(panel, "big").setCheckState(Qt.CheckState.Checked)
        panel.save_card()
        store.shutdown()
        new_card = next(c for c in store.cards if c.headword == "huge")
        self.assertEqual(len(store.links_for(new_card.id)), 1)
        self.assertEqual(len(store.links_for("big")), 1)

    def test_programmatic_retick_does_not_mark_dirty(self):
        panel, store = self._panel()
        store.links = [Link("big", "large", "synonym")]
        panel.load_card(store.cards[0])  # ticks large via _retick, must stay clean
        self.assertFalse(panel._dirty)
        self._set_category(panel, "antonym")  # re-ticks, still not a user edit
        self.assertFalse(panel._dirty)

    def test_loaded_cards_own_row_is_not_checkable(self):
        panel, store = self._panel()
        panel.load_card(store.cards[0])  # big
        own = self._item(panel, "big")
        self.assertFalse(bool(own.flags() & Qt.ItemFlag.ItemIsUserCheckable))

    def test_removed_api_is_gone(self):
        panel, _ = self._panel()
        for attr in (
            "link_button", "link_type_combo", "_on_link_selected",
            "_checked_card_ids", "_uncheck_all_saved",
            "_update_link_button_enabled", "_refresh_links_section",
            "_build_link_row", "_link_row_labels", "links_container",
        ):
            self.assertFalse(hasattr(panel, attr), f"{attr} should be removed")


if __name__ == "__main__":
    unittest.main()
