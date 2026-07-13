"""The flashcard dock title carries a "*" while the card has unsaved edits.

Same convention as a text editor marking a modified file. The chain has three
links, and each is tested here:

  EditorState.altered flips -> FlashcardPanel.altered_changed(bool) ->
  TranslationTool.on_flashcard_altered_changed sets the dock title

The panel deliberately knows nothing about the dock (only the main window wires
panels to anything), so the middle link is a signal and the last one is a main
window method. As in test_flashcard_dock_toggle, that method is driven against a
real dock and panel through a carrier, rather than building the whole
(WebEngine-heavy) main window."""

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDockWidget, QMainWindow

from split_translator.flashcard_editor_state import EditorState
from split_translator.flashcard_panel import FlashcardPanel
from split_translator.flashcards import Card, FlashcardStore
from split_translator.main_window import TranslationTool

app = QApplication.instance() or QApplication([])


class EditorStateAlteredCallbackTests(unittest.TestCase):
    """The state announces an altered flip through a plain callback (it holds no
    Qt). It must fire on the transition only, so a listener is not woken on every
    keystroke of a card that is already known to be altered."""

    def _state(self):
        state = EditorState()
        seen = []
        state.on_altered_changed = seen.append
        return state, seen

    def test_marking_altered_announces_once(self):
        state, seen = self._state()
        state.mark_altered()
        self.assertEqual(seen, [True])

    def test_repeated_marks_do_not_re_announce(self):
        # Every keystroke calls mark_altered. Only the first is a change.
        state, seen = self._state()
        for _ in range(5):
            state.mark_altered()
        self.assertEqual(seen, [True])
        self.assertTrue(state.altered)

    def test_saving_or_clearing_announces_the_clean_baseline(self):
        state, seen = self._state()
        state.mark_altered()
        state.to_editing("id-1", None)  # what Save does
        self.assertEqual(seen, [True, False])
        self.assertFalse(state.altered)

    def test_to_new_announces_the_clean_baseline(self):
        state, seen = self._state()
        state.mark_altered()
        state.to_new()  # what Clear does
        self.assertEqual(seen, [True, False])

    def test_clean_to_clean_is_not_announced(self):
        # A clear on an already-clean card changes nothing.
        state, seen = self._state()
        state.to_new()
        self.assertEqual(seen, [])

    def test_state_without_a_listener_still_works(self):
        # The callback is optional; the print panel never sets one.
        state = EditorState()
        state.mark_altered()
        self.assertTrue(state.altered)


class PanelAlteredSignalTests(unittest.TestCase):
    """The panel re-emits the state's flip as a Qt signal, and a programmatic
    fill (auto-grab, load, clear) must not raise it: that is the whole point of
    the altered flag, and the title would otherwise star a card the user has not
    touched."""

    def _panel(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        store = FlashcardStore(Path(tmp.name) / "cards.json")
        panel = FlashcardPanel(store)
        self.addCleanup(panel.deleteLater)
        seen = []
        panel.altered_changed.connect(seen.append)
        return panel, store, seen

    def test_typing_emits_altered(self):
        panel, _, seen = self._panel()
        panel.headword_input.setText("shed")
        self.assertEqual(seen, [True])

    def test_further_typing_does_not_re_emit(self):
        panel, _, seen = self._panel()
        panel.headword_input.setText("shed")
        panel.own_notation_input.setText("a note")
        self.assertEqual(seen, [True])

    def test_saving_emits_unaltered(self):
        panel, _, seen = self._panel()
        panel.headword_input.setText("shed")
        panel.save_card()
        self.assertEqual(seen, [True, False])
        self.assertFalse(panel.state.altered)

    def test_clearing_emits_unaltered(self):
        panel, _, seen = self._panel()
        panel.headword_input.setText("shed")
        panel.ctrl_held = lambda: True  # skip the discard prompt
        panel.clear_editor()
        self.assertEqual(seen, [True, False])

    def test_loading_a_card_leaves_it_unaltered(self):
        # Loading fills every field programmatically. None of that is a user
        # edit, so no card is starred just for being opened.
        panel, store, seen = self._panel()
        store.cards = [Card(headword="address", id="id-addr")]
        panel._refresh_saved_list()
        panel._on_saved_clicked(panel.saved_list.item(0))
        self.assertEqual(seen, [])
        self.assertFalse(panel.state.altered)

    def test_passive_autofill_does_not_alter(self):
        # A Cambridge page load fills IPA, spelling and audio behind the user's
        # back. Starring the card for that would be a lie.
        panel, _, seen = self._panel()
        panel.autofill_pronunciation(
            "ipa-uk", "ipa-us", None, None, word="shed"
        )
        self.assertEqual(seen, [])
        self.assertFalse(panel.state.altered)


class DockTitleTests(unittest.TestCase):
    """The main window turns the panel's signal into the dock title."""

    def _carrier(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        store = FlashcardStore(Path(tmp.name) / "cards.json")
        panel = FlashcardPanel(store)

        window = QMainWindow()
        self.addCleanup(window.close)
        dock = QDockWidget(TranslationTool._FLASHCARD_TITLE, window)
        dock.setWidget(panel)
        window.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)

        carrier = SimpleNamespace(flashcard_panel=panel, flashcard_dock=dock)
        # The real connection the main window makes in connect_signals, so a
        # keystroke below drives the whole chain rather than the handler alone.
        panel.altered_changed.connect(
            lambda altered: TranslationTool.on_flashcard_altered_changed(
                carrier, altered
            )
        )
        return carrier, dock, panel

    def test_title_starts_unstarred(self):
        _, dock, _ = self._carrier()
        self.assertEqual(dock.windowTitle(), "Flashcard")

    def test_typing_stars_the_title(self):
        _, dock, panel = self._carrier()
        panel.headword_input.setText("shed")
        self.assertEqual(dock.windowTitle(), "Flashcard *")

    def test_saving_unstars_the_title(self):
        _, dock, panel = self._carrier()
        panel.headword_input.setText("shed")
        panel.save_card()
        self.assertEqual(dock.windowTitle(), "Flashcard")

    def test_clearing_unstars_the_title(self):
        _, dock, panel = self._carrier()
        panel.headword_input.setText("shed")
        panel.ctrl_held = lambda: True  # skip the discard prompt
        panel.clear_editor()
        self.assertEqual(dock.windowTitle(), "Flashcard")

    def test_editing_a_saved_card_stars_the_title_again(self):
        carrier, dock, panel = self._carrier()
        panel.headword_input.setText("shed")
        panel.save_card()
        panel.own_notation_input.setText("a note")
        self.assertEqual(dock.windowTitle(), "Flashcard *")


if __name__ == "__main__":
    unittest.main()
