"""The editor builds and wires its card fields from the registry.

These tests loop the registry rather than naming fields, so a field added to
CARD_FIELDS is covered the moment it is declared. That is the guarantee the
registry exists for: adding a field is one entry, not an edit in six places."""

import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from split_translator.flashcard_fields import CARD_FIELDS
from split_translator.flashcard_panel import FlashcardPanel
from split_translator.flashcards import FlashcardStore

app = QApplication.instance() or QApplication([])


class FieldWiringTests(unittest.TestCase):
    def setUp(self):
        # Same fixture shape as the other panel tests: a throwaway store
        # directory removed by addCleanup.
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        store = FlashcardStore(Path(tmp.name) / "cards.json")
        self.panel = FlashcardPanel(store)

    def _widget(self, spec):
        return getattr(self.panel, spec.attr)

    def test_every_declared_field_has_a_widget(self):
        for spec in CARD_FIELDS:
            self.assertTrue(hasattr(self.panel, spec.attr), spec.name)

    def test_every_field_carries_its_declared_placeholder(self):
        for spec in CARD_FIELDS:
            self.assertEqual(
                self._widget(spec).placeholderText(), spec.placeholder, spec.name
            )

    def test_every_field_carries_its_declared_tooltip(self):
        for spec in CARD_FIELDS:
            self.assertEqual(
                self._widget(spec).toolTip(), spec.tooltip, spec.name
            )

    def test_every_field_starts_marked_empty(self):
        for spec in CARD_FIELDS:
            self.assertEqual(
                self._widget(spec).property("emptyField"), "true", spec.name
            )

    def test_typing_in_any_field_clears_its_marker(self):
        for spec in CARD_FIELDS:
            widget = self._widget(spec)
            widget.setText("x")
            self.assertEqual(widget.property("emptyField"), "false", spec.name)

    def test_typing_in_any_field_marks_the_card_altered(self):
        for spec in CARD_FIELDS:
            self.panel.state.altered = False
            self._widget(spec).setText("x")
            self.assertTrue(self.panel.state.altered, spec.name)

    def test_a_programmatic_write_never_marks_the_card_altered(self):
        for spec in CARD_FIELDS:
            self.panel.state.altered = False
            with self.panel._programmatic():
                self._widget(spec).setText("x")
            self.assertFalse(self.panel.state.altered, spec.name)

    def test_printed_fields_clear_the_printed_flag(self):
        for spec in CARD_FIELDS:
            if not spec.printed:
                continue
            self.panel.set_printed(True)
            self.panel.state.printed_flag_altered = False
            self._widget(spec).setText("x")
            self.assertFalse(self.panel.is_printed(), spec.name)

    def test_unprinted_fields_leave_the_printed_flag_alone(self):
        for spec in CARD_FIELDS:
            if spec.printed:
                continue
            self.panel.set_printed(True)
            self.panel.state.printed_flag_altered = False
            self._widget(spec).setText("x")
            self.assertTrue(self.panel.is_printed(), spec.name)


if __name__ == "__main__":
    unittest.main()
