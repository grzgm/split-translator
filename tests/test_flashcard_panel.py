import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

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

    def test_pronunciation_fills_empty_fields_without_asking(self):
        panel, _ = self._panel()
        asked = []
        panel._confirm_overwrite_fields = lambda: asked.append(True) or True
        panel.set_pronunciation("/aa/", "/bb/", None, None, "uk", "us")
        self.assertEqual(panel.ipa_uk_input.text(), "/aa/")
        self.assertEqual(panel.spelling_uk_input.text(), "uk")
        self.assertEqual(asked, [])  # no conflict, so no prompt

    def test_pronunciation_keeps_values_when_overwrite_declined(self):
        panel, _ = self._panel()
        panel.ipa_uk_input.setText("/old/")
        panel.spelling_us_input.setText("kept")
        panel._confirm_overwrite_fields = lambda: False
        # ipa_us is empty, so it fills even though the user declined the others.
        panel.set_pronunciation("/new/", "/usnew/", None, None, "uk", "newus")
        self.assertEqual(panel.ipa_uk_input.text(), "/old/")
        self.assertEqual(panel.spelling_us_input.text(), "kept")
        self.assertEqual(panel.ipa_us_input.text(), "/usnew/")
        self.assertEqual(panel.spelling_uk_input.text(), "uk")

    def test_pronunciation_overwrites_when_confirmed(self):
        panel, _ = self._panel()
        panel.ipa_uk_input.setText("/old/")
        panel._confirm_overwrite_fields = lambda: True
        panel.set_pronunciation("/new/", None, None, None)
        self.assertEqual(panel.ipa_uk_input.text(), "/new/")

    def test_pronunciation_same_value_is_not_a_conflict(self):
        panel, _ = self._panel()
        panel.ipa_uk_input.setText("/same/")
        asked = []
        panel._confirm_overwrite_fields = lambda: asked.append(True) or True
        panel.set_pronunciation("/same/", None, None, None)
        self.assertEqual(asked, [])  # identical value, no prompt


if __name__ == "__main__":
    unittest.main()
