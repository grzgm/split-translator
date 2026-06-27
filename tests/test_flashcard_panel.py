import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLineEdit

from split_translator.flashcard_panel import FlashcardPanel
from split_translator.flashcards import FlashcardStore

app = QApplication.instance() or QApplication([])


class FlashcardPanelTests(unittest.TestCase):
    def _panel(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        store = FlashcardStore(Path(tmp.name) / "cards.json")
        return FlashcardPanel(store), store

    def test_starts_with_one_active_sense(self):
        panel, _ = self._panel()
        self.assertEqual(len(panel._rows()), 1)
        self.assertIs(panel.active_row, panel._rows()[0])

    def test_capture_routes_to_active_row(self):
        panel, _ = self._panel()
        panel.set_polish_selection("adres")
        panel.set_english_selection("the details of where someone lives")
        row = panel.active_row
        self.assertEqual(row.polish_input.text(), "adres")
        self.assertEqual(
            row.english_input.text(), "the details of where someone lives"
        )

    def test_add_sense_makes_new_row_active(self):
        panel, _ = self._panel()
        panel.add_sense()
        self.assertEqual(len(panel._rows()), 2)
        self.assertIs(panel.active_row, panel._rows()[1])

    def test_example_capture_appends_to_active_row(self):
        panel, _ = self._panel()
        panel.add_example_selection("She lives at that address.")
        panel.add_example_selection("Send it to my address.")
        row = panel.active_row
        self.assertEqual(
            row.examples(),
            ["She lives at that address.", "Send it to my address."],
        )

    def test_example_capture_skips_blank(self):
        panel, _ = self._panel()
        panel.add_example_selection("   ")
        self.assertEqual(panel.active_row.examples(), [])

    # Real keyboard focus cannot be asserted under the offscreen platform
    # (focusWidget() is always None), so these check that setFocus is invoked on
    # the right field instead, which is what drives the focus on a live display.
    def test_add_example_with_focus_calls_setfocus(self):
        panel, _ = self._panel()
        focused = []
        orig = QLineEdit.setFocus
        try:
            QLineEdit.setFocus = lambda self, *a: focused.append(self)
            panel.active_row.add_example(focus=True)
        finally:
            QLineEdit.setFocus = orig
        field = panel.active_row._example_rows()[-1].example_input
        self.assertIn(field, focused)

    def test_example_capture_does_not_focus(self):
        panel, _ = self._panel()
        focused = []
        orig = QLineEdit.setFocus
        try:
            QLineEdit.setFocus = lambda self, *a: focused.append(self)
            panel.active_row.add_example_text("She lives at that address.")
        finally:
            QLineEdit.setFocus = orig
        self.assertEqual(focused, [])

    def test_build_card_carries_examples(self):
        panel, _ = self._panel()
        panel.headword_input.setText("address")
        panel.set_english_selection("the details of a place")
        panel.add_example_selection("She lives at that address.")
        card = panel.build_card()
        self.assertEqual(len(card.senses), 1)
        self.assertEqual(
            card.senses[0].examples, ["She lives at that address."]
        )

    def test_sense_kept_when_only_examples(self):
        panel, _ = self._panel()
        panel.headword_input.setText("address")
        panel.add_example_selection("She lives at that address.")
        card = panel.build_card()
        self.assertEqual(len(card.senses), 1)
        self.assertEqual(card.senses[0].polish, "")
        self.assertEqual(
            card.senses[0].examples, ["She lives at that address."]
        )

    def test_build_card_requires_headword(self):
        panel, _ = self._panel()
        self.assertIsNone(panel.build_card())

    def test_build_card_drops_empty_senses(self):
        panel, _ = self._panel()
        panel.headword_input.setText("address")
        panel.active_row.pos_combo.setCurrentText("n")
        panel.set_polish_selection("adres")
        panel.add_sense()  # second, left empty
        card = panel.build_card()
        self.assertEqual(card.headword, "address")
        self.assertEqual(len(card.senses), 1)
        self.assertEqual(card.senses[0].pos, "n")
        self.assertEqual(card.senses[0].polish, "adres")

    def test_save_persists_and_clears(self):
        panel, store = self._panel()
        panel.headword_input.setText("address")
        panel.set_polish_selection("adres")
        panel.save_card()
        store.shutdown()
        self.assertEqual(len(store.cards), 1)
        self.assertEqual(panel.headword_input.text(), "")

    def test_build_card_carries_star(self):
        panel, _ = self._panel()
        panel.headword_input.setText("address")
        self.assertFalse(panel.build_card().starred)
        panel.set_starred(True)
        self.assertTrue(panel.build_card().starred)

    def test_save_resets_star(self):
        panel, store = self._panel()
        panel.headword_input.setText("address")
        panel.set_starred(True)
        panel.save_card()
        store.shutdown()
        self.assertTrue(store.cards[0].starred)
        self.assertFalse(panel.is_starred())

    def test_grab_fills_everything_when_editor_empty(self):
        panel, _ = self._panel()
        panel.set_pronunciation("/aa/", "/bb/", "a.mp3", None, "uk", "us", word="run")
        self.assertEqual(panel.headword_input.text(), "run")
        self.assertEqual(panel.ipa_uk_input.text(), "/aa/")
        self.assertEqual(panel.ipa_us_input.text(), "/bb/")
        self.assertEqual(panel.spelling_uk_input.text(), "uk")
        self.assertEqual(panel.spelling_us_input.text(), "us")
        self.assertEqual(panel._audio_uk_url, "a.mp3")

    def test_grab_fills_nothing_when_any_field_has_value(self):
        panel, _ = self._panel()
        panel.ipa_uk_input.setText("/mine/")  # one field already filled
        panel.set_pronunciation("/aa/", "/bb/", "a.mp3", None, "uk", "us", word="run")
        # Nothing is touched, not even the empty fields.
        self.assertEqual(panel.headword_input.text(), "")
        self.assertEqual(panel.ipa_uk_input.text(), "/mine/")
        self.assertEqual(panel.ipa_us_input.text(), "")
        self.assertEqual(panel.spelling_uk_input.text(), "")
        self.assertIsNone(panel._audio_uk_url)

    def test_grab_blocked_by_headword_value(self):
        panel, _ = self._panel()
        panel.headword_input.setText("kept")
        panel.set_pronunciation("/aa/", None, None, None, word="run")
        self.assertEqual(panel.headword_input.text(), "kept")
        self.assertEqual(panel.ipa_uk_input.text(), "")

    def test_grab_blocked_by_existing_audio(self):
        panel, _ = self._panel()
        panel._audio_uk_url = "old.mp3"
        panel.set_pronunciation("/aa/", None, None, None, word="run")
        self.assertEqual(panel.headword_input.text(), "")
        self.assertEqual(panel.ipa_uk_input.text(), "")

    def test_new_card_clears_without_setting_headword(self):
        panel, _ = self._panel()
        # Empty editor: no discard prompt, returns True, clears.
        self.assertTrue(panel.new_card("run"))
        self.assertEqual(panel.headword_input.text(), "")

    def test_new_card_returns_false_when_discard_declined(self):
        panel, _ = self._panel()
        panel.headword_input.setText("keep")
        panel._confirm_discard = lambda: False
        self.assertFalse(panel.new_card("run"))
        self.assertEqual(panel.headword_input.text(), "keep")

    def test_new_card_force_skips_confirmation(self):
        panel, _ = self._panel()
        panel.headword_input.setText("keep")
        asked = []
        panel._confirm_discard = lambda: asked.append(True) or False
        self.assertTrue(panel.new_card("run", force=True))
        self.assertEqual(asked, [])  # never prompted
        self.assertEqual(panel.headword_input.text(), "")  # cleared

    def test_clear_editor_ctrl_skips_confirmation(self):
        panel, _ = self._panel()
        panel.headword_input.setText("keep")
        asked = []
        panel._confirm_discard = lambda: asked.append(True) or False
        panel.ctrl_held = lambda: True
        panel.clear_editor()
        self.assertEqual(asked, [])  # never prompted
        self.assertEqual(panel.headword_input.text(), "")  # cleared

    def test_clear_editor_without_ctrl_confirms(self):
        panel, _ = self._panel()
        panel.headword_input.setText("keep")
        panel.ctrl_held = lambda: False
        panel._confirm_discard = lambda: False  # decline
        panel.clear_editor()
        self.assertEqual(panel.headword_input.text(), "keep")  # not cleared

    # --- empty-field marking --------------------------------------------
    # A blank fillable field carries a "border" style; a filled one does not.

    @staticmethod
    def _marked(field):
        return "border" in field.styleSheet()

    def _card_fields(self, panel):
        return (
            panel.headword_input,
            panel.spelling_uk_input,
            panel.spelling_us_input,
            panel.ipa_uk_input,
            panel.ipa_us_input,
            panel.own_notation_input,
        )

    def test_empty_card_fields_are_marked(self):
        panel, _ = self._panel()
        self.assertTrue(all(self._marked(f) for f in self._card_fields(panel)))

    def test_empty_sense_fields_are_marked(self):
        panel, _ = self._panel()
        row = panel.active_row
        self.assertTrue(self._marked(row.pos_combo))
        self.assertTrue(self._marked(row.polish_input))
        self.assertTrue(self._marked(row.english_input))

    def test_setting_pos_clears_its_marker(self):
        panel, _ = self._panel()
        row = panel.active_row
        row.pos_combo.setCurrentText("n")
        self.assertFalse(self._marked(row.pos_combo))
        row.pos_combo.setCurrentText("")
        self.assertTrue(self._marked(row.pos_combo))

    def test_blank_example_is_marked_and_clears_when_typed(self):
        panel, _ = self._panel()
        row = panel.active_row
        row.add_example()  # blank "+ example" row
        field = row._example_rows()[-1].example_input
        self.assertTrue(self._marked(field))
        field.setText("She lives here.")
        self.assertFalse(self._marked(field))

    def test_captured_example_is_not_marked(self):
        panel, _ = self._panel()
        row = panel.active_row
        row.add_example_text("She lives here.")
        field = row._example_rows()[-1].example_input
        self.assertFalse(self._marked(field))

    def test_filling_a_field_clears_its_marker(self):
        panel, _ = self._panel()
        panel.headword_input.setText("dog")
        self.assertFalse(self._marked(panel.headword_input))
        panel.active_row.polish_input.setText("pies")
        self.assertFalse(self._marked(panel.active_row.polish_input))

    def test_clearing_a_field_re_marks_it(self):
        panel, _ = self._panel()
        panel.headword_input.setText("dog")
        panel.headword_input.clear()
        self.assertTrue(self._marked(panel.headword_input))

    def test_grab_clears_markers_on_filled_fields(self):
        panel, _ = self._panel()
        panel.set_pronunciation("/wn/", "/wun/", "u.mp3", None, word="one")
        self.assertFalse(self._marked(panel.headword_input))
        self.assertFalse(self._marked(panel.ipa_uk_input))
        # No spelling came through, so those stay marked.
        self.assertTrue(self._marked(panel.spelling_uk_input))

    def test_reset_re_marks_card_and_new_sense(self):
        panel, _ = self._panel()
        panel.headword_input.setText("dog")
        panel.active_row.polish_input.setText("pies")
        panel._reset_editor()
        self.assertTrue(all(self._marked(f) for f in self._card_fields(panel)))
        new_row = panel.active_row
        self.assertTrue(self._marked(new_row.polish_input))
        self.assertTrue(self._marked(new_row.english_input))


if __name__ == "__main__":
    unittest.main()
