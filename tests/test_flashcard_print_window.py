import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from split_translator.flashcard_print_window import FlashcardPrintWindow
from split_translator.flashcards import Card, FlashcardStore, Sense

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


class TogglePrintedResolutionTests(unittest.TestCase):
    def _window(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        store = FlashcardStore(Path(tmp.name) / "cards.json")
        self.addCleanup(store.shutdown)
        store.cards = [
            Card(headword="a", id="a"),
            Card(headword="b", id="b", printed=True),
        ]
        window = FlashcardPrintWindow(store)
        self.addCleanup(window.deleteLater)
        return window, store

    def test_mixed_selection_sets_all(self):
        window, store = self._window()
        window.panel._selected_ids = {"a", "b"}
        window._on_toggle_printed()
        self.assertTrue(store.cards[0].printed)
        self.assertTrue(store.cards[1].printed)

    def test_all_printed_selection_clears_all(self):
        window, store = self._window()
        store.cards[0].printed = True
        window.panel._selected_ids = {"a", "b"}
        window._on_toggle_printed()
        self.assertFalse(store.cards[0].printed)
        self.assertFalse(store.cards[1].printed)

    def test_empty_selection_does_nothing(self):
        window, store = self._window()
        window.panel._selected_ids = set()
        window._on_toggle_printed()
        self.assertTrue(store.cards[1].printed)  # unchanged

    def test_loaded_card_toggle_resyncs_on_external_flag(self):
        window, store = self._window()
        window.panel.load_card(store.cards[0])  # id "a", not printed, unaltered
        self.assertFalse(window.panel.is_printed())
        window.panel._selected_ids = {"a"}
        window._on_toggle_printed()  # flags "a" printed
        self.assertTrue(window.panel.is_printed())
        self.assertFalse(window.panel.state.altered)

    def test_cards_printed_flags_those_cards(self):
        window, store = self._window()  # "a" unprinted, "b" printed
        window.print_view.cards_printed.emit(["a"])
        self.assertTrue(store.cards[0].printed)


class SidebarWiringTests(unittest.TestCase):
    def _window(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        store = FlashcardStore(Path(tmp.name) / "f.json")
        self.addCleanup(store.shutdown)
        store.cards = [
            Card(
                headword="cat", id="c",
                senses=[Sense(pos="v", examples=["a1", "a2"])],
            )
        ]
        win = FlashcardPrintWindow(store)
        self.addCleanup(win.deleteLater)
        win.panel._refresh_saved_list()
        return win, store

    def test_loading_a_card_shows_it_in_the_sidebar(self):
        win, store = self._window()
        win.panel.load_card(store.cards[0])
        self.assertEqual(win.sidebar.card_id(), "c")

    def test_clearing_the_editor_empties_the_sidebar(self):
        win, store = self._window()
        win.panel.load_card(store.cards[0])
        win.panel.clear_editor()
        self.assertIsNone(win.sidebar.card_id())

    def test_a_choice_reaches_the_preview(self):
        win, store = self._window()
        win.panel.load_card(store.cards[0])
        win.sidebar._boxes[(0, 1)].setChecked(False)
        self.assertEqual(win.print_view._choices, {"c": {(0, 0)}})

    def test_editing_a_card_drops_its_hand_picked_set(self):
        win, store = self._window()
        win.choices.set_manual(store.cards[0], [(0, 0)])
        edited = Card(
            headword="cat", id="c",
            senses=[Sense(pos="v", examples=["a1 reworded", "a2"])],
        )
        store.update_card(edited)
        self.assertEqual(win.choices.mode_of("c"), "auto")
        self.assertEqual(win.print_view._choices, {})

    def test_editing_a_card_drops_its_stale_measurement_too(self):
        # drop_stale only reports ids that had a hand-picked set, so give the
        # card one, exactly the case _on_cards_changed actually wires up: a
        # manual card whose examples change loses both its choice and the
        # measurement that would otherwise pre-tick it wrong on next load.
        win, store = self._window()
        win.sidebar.set_auto_fit({"c": [(0, 0)]})
        win.choices.set_manual(store.cards[0], [(0, 0)])
        edited = Card(
            headword="cat", id="c",
            senses=[Sense(pos="v", examples=["a1 reworded", "a2"])],
        )
        store.update_card(edited)
        self.assertNotIn("c", win.sidebar._measured)

    def test_a_tile_click_loads_that_card(self):
        win, _store = self._window()
        win.print_view.card_clicked.emit("c")
        self.assertEqual(win.panel.state.loaded_card_id, "c")
        self.assertEqual(win.sidebar.card_id(), "c")

    def test_a_click_on_an_unknown_card_is_ignored(self):
        win, _store = self._window()
        win.print_view.card_clicked.emit("nobody")  # must not raise
        self.assertIsNone(win.panel.state.loaded_card_id)

    def test_loading_a_card_marks_it_in_the_preview(self):
        # The saved list, the editor, the sidebar and the sheets must all point
        # at one card, or it is unclear which card is being worked on.
        win, store = self._window()
        win.panel.load_card(store.cards[0])
        self.assertEqual(win.print_view._selected_card_id, "c")

    def test_clearing_the_editor_clears_the_preview_mark(self):
        win, store = self._window()
        win.panel.load_card(store.cards[0])
        win.panel.clear_editor()
        self.assertIsNone(win.print_view._selected_card_id)

    def test_nothing_is_marked_before_a_card_is_loaded(self):
        win, _store = self._window()
        self.assertIsNone(win.print_view._selected_card_id)

    def test_the_view_starts_in_step_with_the_sidebar(self):
        # The anti-drift push in __init__ exists so these two never disagree
        # about what the view is showing before anything has been touched.
        win, _store = self._window()
        self.assertEqual(win.print_view.show_borders(), win.sidebar.show_borders())
        self.assertEqual(
            win.print_view.print_cut_lines(), win.sidebar.print_cut_lines()
        )
        self.assertEqual(
            win.print_view.blank_headwords(), win.sidebar.blank_headwords()
        )
        self.assertEqual(win.print_view.back_offset(), win.sidebar.back_offset())
        self.assertEqual(
            win.print_view.back_offset_x(), win.sidebar.back_offset_x()
        )

    def test_blanking_headwords_on_the_sidebar_reaches_the_view(self):
        win, _store = self._window()
        win.sidebar.blank_headwords_checkbox.setChecked(False)
        self.assertFalse(win.print_view.blank_headwords())

    def test_changing_the_back_offset_on_the_sidebar_reaches_the_view(self):
        win, _store = self._window()
        win.sidebar.back_offset_spin.setValue(7.5)
        self.assertEqual(win.print_view.back_offset(), 7.5)


if __name__ == "__main__":
    unittest.main()
