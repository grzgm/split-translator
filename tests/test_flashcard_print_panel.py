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

    def test_rows_render_a_checkbox_after_refresh(self):
        # A QListWidgetItem only draws a checkbox indicator when it carries a
        # value in the CheckStateRole data role. Setting only the
        # ItemIsUserCheckable flag is not enough: without the role, no box is
        # painted (which is why the checkboxes were invisible). Assert every
        # freshly built row carries the role, so the box actually renders. This
        # must hold WITHOUT the test setting the check state itself.
        panel, _ = self._panel()
        for card_id in ("a", "b", "c"):
            item = self._item(panel, card_id)
            self.assertTrue(
                bool(item.flags() & Qt.ItemFlag.ItemIsUserCheckable),
                f"{card_id} row must be checkable",
            )
            self.assertIsNotNone(
                item.data(Qt.ItemDataRole.CheckStateRole),
                f"{card_id} row must carry a CheckStateRole so a box is drawn",
            )
            self.assertEqual(item.checkState(), Qt.CheckState.Unchecked)

    def test_loaded_cards_row_also_renders_a_checkbox(self):
        # The card currently loaded for editing keeps its dot/bold/tint but must
        # still be checkable AND carry the check-state role, so it too can be
        # ticked for printing (its box must render like the others).
        panel, store = self._panel()
        panel.load_card(store.cards[0])  # "a" becomes the loaded row
        item = self._item(panel, "a")
        self.assertTrue(bool(item.flags() & Qt.ItemFlag.ItemIsUserCheckable))
        self.assertIsNotNone(item.data(Qt.ItemDataRole.CheckStateRole))

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

    def test_selection_survives_loading_a_card(self):
        # Loading a card rebuilds the saved list from scratch. The print
        # selection must survive that rebuild rather than being wiped.
        panel, store = self._panel()
        self._item(panel, "b").setCheckState(Qt.CheckState.Checked)
        self._item(panel, "c").setCheckState(Qt.CheckState.Checked)
        panel.load_card(store.cards[0])  # clicking a card's name loads it
        self.assertEqual(set(panel.selected_ids()), {"b", "c"})
        # The rebuilt rows show the ticks too.
        self.assertEqual(
            self._item(panel, "b").checkState(), Qt.CheckState.Checked
        )
        self.assertEqual(
            self._item(panel, "c").checkState(), Qt.CheckState.Checked
        )

    def test_selection_survives_a_plain_refresh(self):
        panel, _ = self._panel()
        self._item(panel, "a").setCheckState(Qt.CheckState.Checked)
        panel._refresh_saved_list()
        self.assertEqual(panel.selected_ids(), ["a"])

    def _shift_click_checkbox(self, panel, row, shift):
        # Drive the real viewport event filter: a MouseButtonPress carrying the
        # Shift modifier records the anchor/shift state, then the check-state
        # toggle runs through the normal itemChanged path.
        from PySide6.QtCore import QEvent, QPointF
        from PySide6.QtGui import QMouseEvent

        lst = panel.saved_list
        item = lst.item(row)
        mods = (
            Qt.KeyboardModifier.ShiftModifier
            if shift
            else Qt.KeyboardModifier.NoModifier
        )
        rect = lst.visualItemRect(item)
        pos = QPointF(rect.left() + 8, rect.center().y())
        press = QMouseEvent(
            QEvent.Type.MouseButtonPress,
            pos,
            lst.viewport().mapToGlobal(pos.toPoint()),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            mods,
        )
        panel.eventFilter(lst.viewport(), press)
        # Toggle the box the way a click would, then let the handler run.
        new_state = (
            Qt.CheckState.Unchecked
            if item.checkState() == Qt.CheckState.Checked
            else Qt.CheckState.Checked
        )
        item.setCheckState(new_state)

    def test_shift_click_checks_the_range(self):
        # Plain-click a row (sets the anchor), then shift-click a lower row: every
        # card's checkbox in between is ticked too.
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        store = FlashcardStore(Path(tmp.name) / "f.json")
        self.addCleanup(store.shutdown)
        store.cards = [Card(headword=f"c{i}", id=str(i)) for i in range(5)]
        panel = FlashcardPrintPanel(store)
        panel._refresh_saved_list()

        self._shift_click_checkbox(panel, 1, shift=False)  # anchor at row 1
        self._shift_click_checkbox(panel, 3, shift=True)   # range 1..3
        self.assertEqual(panel.selected_ids(), ["1", "2", "3"])

    def test_shift_click_range_works_upwards(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        store = FlashcardStore(Path(tmp.name) / "f.json")
        self.addCleanup(store.shutdown)
        store.cards = [Card(headword=f"c{i}", id=str(i)) for i in range(5)]
        panel = FlashcardPrintPanel(store)
        panel._refresh_saved_list()

        self._shift_click_checkbox(panel, 4, shift=False)  # anchor at row 4
        self._shift_click_checkbox(panel, 2, shift=True)   # range 2..4
        self.assertEqual(panel.selected_ids(), ["2", "3", "4"])

    def test_plain_click_without_anchor_does_not_range(self):
        panel, _ = self._panel()
        # A shift-click with no prior plain click just toggles the one row.
        self._shift_click_checkbox(panel, 1, shift=True)
        self.assertEqual(panel.selected_ids(), ["b"])

    def test_unselect_all_clears_the_selection(self):
        panel, _ = self._panel()
        self._item(panel, "a").setCheckState(Qt.CheckState.Checked)
        self._item(panel, "c").setCheckState(Qt.CheckState.Checked)
        panel.clear_selection()
        self.assertEqual(panel.selected_ids(), [])
        self.assertEqual(
            self._item(panel, "a").checkState(), Qt.CheckState.Unchecked
        )
        self.assertEqual(
            self._item(panel, "c").checkState(), Qt.CheckState.Unchecked
        )

    def test_unselect_all_emits_selection_changed(self):
        panel, _ = self._panel()
        self._item(panel, "a").setCheckState(Qt.CheckState.Checked)
        seen = []
        panel.selection_changed.connect(lambda: seen.append(True))
        panel.clear_selection()
        self.assertTrue(seen)

    def test_unselect_all_is_a_noop_when_nothing_selected(self):
        panel, _ = self._panel()
        seen = []
        panel.selection_changed.connect(lambda: seen.append(True))
        panel.clear_selection()
        self.assertEqual(seen, [])

    def test_has_an_unselect_all_button(self):
        panel, _ = self._panel()
        self.assertIsNotNone(panel.unselect_all_button)

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
