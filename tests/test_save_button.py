"""The Save button is live exactly when saving would write a card.

Both modes need a headword. Editing needs an edit on top of it, because
re-saving an untouched card would write the same card back. New mode has no
such baseline, and the Cambridge auto-fill deliberately leaves the card
unaltered, so an auto-filled card must stay saveable without the user typing
anything."""

import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from split_translator.flashcard_panel import FlashcardPanel
from split_translator.flashcards import Card, FlashcardStore

app = QApplication.instance() or QApplication([])


class SaveButtonTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.store = FlashcardStore(Path(tmp.name) / "cards.json")
        self.panel = FlashcardPanel(self.store)

    def _load_saved_card(self):
        self.store.cards = [Card(headword="address", id="id-addr")]
        self.panel._refresh_saved_list()
        self.panel._on_saved_clicked(self.panel.saved_list.item(0))

    # --- new mode -------------------------------------------------------

    def test_an_empty_new_card_cannot_be_saved(self):
        self.assertTrue(self.panel.state.is_new)
        self.assertFalse(self.panel.save_button.isEnabled())

    def test_a_headword_makes_a_new_card_saveable(self):
        self.panel.headword_input.setText("run")
        self.assertTrue(self.panel.save_button.isEnabled())

    def test_clearing_the_headword_disables_save_again(self):
        self.panel.headword_input.setText("run")
        self.panel.headword_input.setText("")
        self.assertFalse(self.panel.save_button.isEnabled())

    def test_a_blank_headword_does_not_count(self):
        self.panel.headword_input.setText("   ")
        self.assertFalse(self.panel.save_button.isEnabled())

    def test_an_auto_filled_card_is_saveable_without_a_user_edit(self):
        # The passive Cambridge grab never marks the card altered, so an
        # altered-only rule would leave this card unsaveable.
        self.panel.autofill_headword("run")
        self.assertFalse(self.panel.state.altered)
        self.assertTrue(self.panel.save_button.isEnabled())

    def test_a_card_with_only_a_sense_cannot_be_saved(self):
        # No headword means build_card refuses, whatever else is filled in.
        self.panel._rows()[0].set_first_example("a sentence")
        self.assertTrue(self.panel.state.altered)
        self.assertFalse(self.panel.save_button.isEnabled())

    # --- editing mode ---------------------------------------------------

    def test_a_freshly_loaded_card_cannot_be_saved(self):
        self._load_saved_card()
        self.assertTrue(self.panel.state.is_editing)
        self.assertFalse(self.panel.save_button.isEnabled())

    def test_editing_a_field_makes_a_loaded_card_saveable(self):
        self._load_saved_card()
        self.panel.own_notation_input.setText("a note")
        self.assertTrue(self.panel.save_button.isEnabled())

    def test_editing_a_sense_makes_a_loaded_card_saveable(self):
        self._load_saved_card()
        self.panel._rows()[0].set_first_example("a sentence")
        self.assertTrue(self.panel.save_button.isEnabled())

    def test_saving_a_loaded_card_disables_save_again(self):
        self._load_saved_card()
        self.panel.headword_input.setText("address2")
        self.panel.save_card()
        # The saved card is the new baseline, so there is nothing left to save.
        self.assertFalse(self.panel.state.altered)
        self.assertFalse(self.panel.save_button.isEnabled())

    def test_a_loaded_card_stripped_of_its_headword_cannot_be_saved(self):
        self._load_saved_card()
        self.panel.headword_input.setText("")
        self.assertTrue(self.panel.state.altered)
        self.assertFalse(self.panel.save_button.isEnabled())

    def test_clearing_the_editor_disables_save(self):
        self.panel.headword_input.setText("run")
        self.panel.ctrl_held = lambda: True  # skip the discard prompt
        self.panel.clear_editor()
        self.assertFalse(self.panel.save_button.isEnabled())

    # --- the tooltip says why -------------------------------------------

    def test_the_tooltip_explains_a_missing_headword(self):
        self.assertIn("headword", self.panel.save_button.toolTip())

    def test_the_tooltip_explains_an_unchanged_card(self):
        self._load_saved_card()
        self.assertIn("No changes", self.panel.save_button.toolTip())

    def test_the_tooltip_names_the_shortcut_when_enabled(self):
        self.panel.headword_input.setText("run")
        self.assertIn("Ctrl+S", self.panel.save_button.toolTip())

    # --- the shortcut still reaches a refused save ----------------------

    def test_ctrl_s_still_reports_why_an_empty_card_is_refused(self):
        # The shortcut calls save_card directly, so disabling the button must
        # not swallow the explanation.
        rejected = []
        self.panel.save_rejected.connect(rejected.append)
        self.panel.save_card()
        self.assertTrue(rejected)


if __name__ == "__main__":
    unittest.main()
