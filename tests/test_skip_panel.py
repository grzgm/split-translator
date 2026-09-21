import unittest

from PySide6.QtWidgets import QApplication

from split_translator.normalise_spec import ORIGINAL_SIDE, TRANSLATION_SIDE
from split_translator.skip_panel import AT_END, AT_START, SkipPanel

app = QApplication.instance() or QApplication([])


class SkipPanelTests(unittest.TestCase):
    def _panel(self, original_count=10, translation_count=5):
        panel = SkipPanel(original_count, translation_count)
        self.changed = []
        self.requested = []
        panel.changed.connect(lambda side, which: self.changed.append((side, which)))
        panel.from_selection.connect(
            lambda side, which: self.requested.append((side, which))
        )
        return panel

    def test_nothing_is_skipped_at_first(self):
        panel = self._panel()
        self.assertEqual(panel.skip(ORIGINAL_SIDE), (0, 0))
        self.assertEqual(panel.skip(TRANSLATION_SIDE), (0, 0))

    def test_at_least_one_paragraph_always_stays_kept(self):
        panel = self._panel(original_count=10)
        self.assertEqual(panel.box(ORIGINAL_SIDE, AT_START).maximum(), 9)
        panel.box(ORIGINAL_SIDE, AT_START).setValue(4)
        self.assertEqual(panel.box(ORIGINAL_SIDE, AT_END).maximum(), 5)
        panel.box(ORIGINAL_SIDE, AT_END).setValue(5)
        self.assertEqual(panel.box(ORIGINAL_SIDE, AT_START).maximum(), 4)

    def test_an_edit_announces_the_side_and_the_field(self):
        panel = self._panel()
        panel.box(TRANSLATION_SIDE, AT_END).setValue(2)
        self.assertEqual(self.changed, [(TRANSLATION_SIDE, AT_END)])
        self.assertEqual(panel.skip(TRANSLATION_SIDE), (0, 2))

    def test_seeding_announces_nothing_and_clamps(self):
        panel = self._panel(original_count=10)
        panel.set_skip(ORIGINAL_SIDE, 20, 20)
        self.assertEqual(panel.skip(ORIGINAL_SIDE), (9, 0))
        panel.set_skip(ORIGINAL_SIDE, 3, 4)
        self.assertEqual(panel.skip(ORIGINAL_SIDE), (3, 4))
        self.assertEqual(panel.box(ORIGINAL_SIDE, AT_END).maximum(), 6)
        self.assertEqual(self.changed, [])

    def test_from_selection_asks_the_owner(self):
        panel = self._panel()
        panel.button(ORIGINAL_SIDE, AT_END).click()
        self.assertEqual(self.requested, [(ORIGINAL_SIDE, AT_END)])

    def test_an_edition_with_no_paragraphs_cannot_skip(self):
        panel = self._panel(translation_count=0)
        self.assertFalse(panel.box(TRANSLATION_SIDE, AT_START).isEnabled())
        self.assertFalse(panel.button(TRANSLATION_SIDE, AT_END).isEnabled())
        self.assertTrue(panel.box(ORIGINAL_SIDE, AT_START).isEnabled())
