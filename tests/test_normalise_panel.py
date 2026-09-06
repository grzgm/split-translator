"""The six normalisation multipliers and their reset, as a widget that knows
nothing about books, views or storage."""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from split_translator.normalise_panel import NormalisePanel
from split_translator.normalise_spec import (
    MAX_SCALE,
    MIN_SCALE,
    ORIGINAL_SIDE,
    TRANSLATION_SIDE,
    NormaliseSpec,
)

app = QApplication.instance() or QApplication([])


class NormalisePanelTests(unittest.TestCase):
    def _panel(self):
        panel = NormalisePanel()
        self.seen = []
        panel.changed.connect(lambda side, spec: self.seen.append((side, spec)))
        return panel

    def test_starts_at_the_default_on_both_sides(self):
        panel = self._panel()
        original, translation = panel.specs()
        self.assertTrue(original.is_default)
        self.assertTrue(translation.is_default)

    def test_the_boxes_are_held_to_the_allowed_range(self):
        panel = self._panel()
        box = panel.box(ORIGINAL_SIDE, "font")
        self.assertEqual(box.minimum(), MIN_SCALE)
        self.assertEqual(box.maximum(), MAX_SCALE)
        self.assertEqual(box.suffix(), "x")

    def test_seeding_does_not_announce_a_change(self):
        # Loading stored values is not a user edit, so nothing must be applied
        # or persisted off the back of it.
        panel = self._panel()
        panel.set_specs(NormaliseSpec(font=0.9), NormaliseSpec(gap=0.7))
        self.assertEqual(self.seen, [])

    def test_seeding_fills_the_boxes(self):
        panel = self._panel()
        panel.set_specs(NormaliseSpec(font=0.9), NormaliseSpec(gap=0.7))
        self.assertAlmostEqual(panel.box(ORIGINAL_SIDE, "font").value(), 0.9)
        self.assertAlmostEqual(panel.box(TRANSLATION_SIDE, "gap").value(), 0.7)

    def test_changing_a_box_announces_that_side_only(self):
        panel = self._panel()
        panel.box(TRANSLATION_SIDE, "font").setValue(0.85)
        self.assertEqual(len(self.seen), 1)
        side, spec = self.seen[0]
        self.assertEqual(side, TRANSLATION_SIDE)
        self.assertAlmostEqual(spec.font, 0.85)

    def test_changing_a_box_leaves_the_other_side_alone(self):
        panel = self._panel()
        panel.box(TRANSLATION_SIDE, "font").setValue(0.85)
        self.assertTrue(panel.spec(ORIGINAL_SIDE).is_default)

    def test_reset_is_dead_while_everything_is_default(self):
        panel = self._panel()
        self.assertFalse(panel.reset_button.isEnabled())

    def test_reset_wakes_once_something_differs(self):
        panel = self._panel()
        panel.box(ORIGINAL_SIDE, "gap").setValue(0.8)
        self.assertTrue(panel.reset_button.isEnabled())

    def test_seeding_a_non_default_spec_wakes_reset(self):
        panel = self._panel()
        panel.set_specs(NormaliseSpec(font=0.9), NormaliseSpec())
        self.assertTrue(panel.reset_button.isEnabled())

    def test_reset_restores_every_field(self):
        panel = self._panel()
        panel.set_specs(NormaliseSpec(font=0.9, gap=0.8), NormaliseSpec(line_height=1.3))
        panel.reset()
        original, translation = panel.specs()
        self.assertTrue(original.is_default)
        self.assertTrue(translation.is_default)

    def test_reset_announces_both_sides_once_each(self):
        # The owner has two views to update, so both must be told, and told once.
        panel = self._panel()
        panel.set_specs(NormaliseSpec(font=0.9), NormaliseSpec(gap=0.8))
        self.seen.clear()
        panel.reset()
        self.assertEqual([side for side, _ in self.seen], [ORIGINAL_SIDE, TRANSLATION_SIDE])
        self.assertTrue(all(spec.is_default for _, spec in self.seen))

    def test_reset_dies_again_afterwards(self):
        panel = self._panel()
        panel.set_specs(NormaliseSpec(font=0.9), NormaliseSpec())
        panel.reset()
        self.assertFalse(panel.reset_button.isEnabled())

    def test_disabling_the_panel_greys_its_boxes(self):
        # The owner greys the whole panel while normalisation is switched off,
        # because the multipliers then do nothing at all.
        panel = self._panel()
        panel.setEnabled(False)
        self.assertFalse(panel.box(ORIGINAL_SIDE, "font").isEnabled())
        self.assertFalse(panel.reset_button.isEnabled())


if __name__ == "__main__":
    unittest.main()
