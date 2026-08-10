"""Clearing, loading and saving all walk the registry.

Like the wiring tests, these loop CARD_FIELDS instead of naming fields, so a
newly declared field is covered by every value path at once."""

import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from split_translator.flashcard_fields import CARD_FIELDS
from split_translator.flashcard_panel import FlashcardPanel
from split_translator.flashcards import Card, FlashcardStore

app = QApplication.instance() or QApplication([])


def _full_card():
    """A card with every registered field set to something recognisable. Built
    fresh per test so no test can leave marks on another's fixture."""
    return Card(
        headword="run",
        spelling_uk="colour",
        spelling_us="color",
        ipa_uk="/rn uk/",
        ipa_us="/rn us/",
        own_notation="my note",
        tags=["book", "verb"],
    )


class ValuePathTests(unittest.TestCase):
    def setUp(self):
        # Same fixture shape as the other panel tests: a throwaway store
        # directory removed by addCleanup.
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        store = FlashcardStore(Path(tmp.name) / "cards.json")
        self.panel = FlashcardPanel(store)

    def _widget(self, spec):
        return getattr(self.panel, spec.attr)

    def test_load_fills_every_field(self):
        card = _full_card()
        self.panel.load_card(card)
        for spec in CARD_FIELDS:
            expected = spec.from_card(getattr(card, spec.name))
            self.assertEqual(self._widget(spec).text(), expected, spec.name)

    def test_reset_clears_every_field(self):
        self.panel.load_card(_full_card())
        self.panel._reset_editor()
        for spec in CARD_FIELDS:
            self.assertEqual(self._widget(spec).text(), "", spec.name)

    def test_reset_re_marks_every_field(self):
        self.panel.load_card(_full_card())
        self.panel._reset_editor()
        for spec in CARD_FIELDS:
            self.assertEqual(
                self._widget(spec).property("emptyField"), "true", spec.name
            )

    def test_save_reads_every_field(self):
        for spec in CARD_FIELDS:
            self._widget(spec).setText("run" if spec.name == "headword" else "x")
        card = self.panel.build_card()
        for spec in CARD_FIELDS:
            expected = spec.to_card(self._widget(spec).text())
            self.assertEqual(getattr(card, spec.name), expected, spec.name)

    def test_a_card_round_trips_through_the_editor(self):
        loaded = _full_card()
        self.panel.load_card(loaded)
        card = self.panel.build_card()
        for spec in CARD_FIELDS:
            self.assertEqual(
                getattr(card, spec.name), getattr(loaded, spec.name), spec.name
            )

    def test_blank_optional_fields_save_as_none(self):
        self.panel.headword_input.setText("run")
        card = self.panel.build_card()
        for spec in CARD_FIELDS:
            if spec.name in ("headword", "tags"):
                continue
            self.assertIsNone(getattr(card, spec.name), spec.name)

    def test_a_blank_headword_still_refuses_to_build(self):
        self.panel.spelling_uk_input.setText("colour")
        self.assertIsNone(self.panel.build_card())

    def test_has_content_sees_every_field(self):
        for spec in CARD_FIELDS:
            self.panel._reset_editor()
            self.assertFalse(self.panel.has_content(), spec.name)
            self._widget(spec).setText("x")
            self.assertTrue(self.panel.has_content(), spec.name)


if __name__ == "__main__":
    unittest.main()
