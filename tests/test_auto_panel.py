"""The Automatic anchors tab: a batch is the selection plus a count.

There is no start to type. The owner reports the paragraph selected in the
original and the panel shows it, so a batch is always the passage being looked
at. With nothing selected there is no batch, and Generate and Remove are
disabled rather than acting on a number left over from an earlier batch."""

import unittest

from PySide6.QtWidgets import QApplication

from split_translator.auto_panel import DEFAULT_COUNT, AutoAnchorPanel

app = QApplication.instance() or QApplication([])


class AutoAnchorPanelTests(unittest.TestCase):
    def _panel(self, count=500):
        panel = AutoAnchorPanel(count)
        self.requests = []
        panel.generate.connect(lambda s, c: self.requests.append(("generate", s, c)))
        panel.remove.connect(lambda s, c: self.requests.append(("remove", s, c)))
        return panel

    def test_it_opens_with_nothing_selected_and_the_default_count(self):
        panel = self._panel()
        self.assertIsNone(panel.start())
        self.assertEqual(panel.count(), DEFAULT_COUNT)
        self.assertEqual(
            panel.start_label.text(), "Select a paragraph in the original"
        )

    def test_the_buttons_are_disabled_until_a_paragraph_is_selected(self):
        panel = self._panel()
        self.assertFalse(panel.generate_button.isEnabled())
        self.assertFalse(panel.remove_button.isEnabled())
        panel.set_selected(4)
        self.assertTrue(panel.generate_button.isEnabled())
        self.assertTrue(panel.remove_button.isEnabled())

    def test_clearing_the_selection_disables_them_again(self):
        panel = self._panel()
        panel.set_selected(4)
        panel.set_selected(None)
        self.assertIsNone(panel.start())
        self.assertFalse(panel.generate_button.isEnabled())
        self.assertFalse(panel.remove_button.isEnabled())
        self.assertEqual(
            panel.start_label.text(), "Select a paragraph in the original"
        )

    def test_the_selected_paragraph_is_shown_counted_from_1(self):
        panel = self._panel()
        panel.set_selected(0)
        self.assertEqual(panel.start_label.text(), "Paragraph 1")
        panel.set_selected(41)
        self.assertEqual(panel.start_label.text(), "Paragraph 42")

    def test_the_count_never_exceeds_the_edition(self):
        self.assertEqual(self._panel(30).count(), 30)

    def test_generate_and_remove_announce_the_batch(self):
        panel = self._panel()
        panel.set_selected(10)
        panel.count_box.setValue(40)
        panel.generate_button.click()
        panel.remove_button.click()
        self.assertEqual(self.requests, [("generate", 10, 40), ("remove", 10, 40)])

    def test_a_position_outside_the_edition_counts_as_no_selection(self):
        # A stale paragraph id must not leave the buttons live.
        panel = self._panel(50)
        panel.set_selected(50)
        self.assertIsNone(panel.start())
        self.assertFalse(panel.generate_button.isEnabled())
        panel.set_selected(-1)
        self.assertIsNone(panel.start())

    def test_nothing_is_announced_without_a_selection(self):
        panel = self._panel()
        panel.generate_button.click()  # disabled, but click it anyway
        panel.remove_button.click()
        self.assertEqual(self.requests, [])

    def test_setting_the_selection_announces_nothing(self):
        panel = self._panel(50)
        panel.set_selected(7)
        self.assertEqual(self.requests, [])

    def test_busy_disables_generate_and_remove_until_done(self):
        panel = self._panel()
        panel.set_selected(0)
        panel.set_busy(True)
        self.assertFalse(panel.generate_button.isEnabled())
        self.assertFalse(panel.remove_button.isEnabled())
        self.assertTrue(panel.count_box.isEnabled())
        panel.set_busy(False)
        self.assertTrue(panel.generate_button.isEnabled())
        self.assertTrue(panel.remove_button.isEnabled())

    def test_a_batch_that_finishes_with_no_selection_leaves_the_buttons_off(self):
        # The selection was cleared while the batch ran, so there is nothing to
        # generate for any more.
        panel = self._panel()
        panel.set_selected(0)
        panel.set_busy(True)
        panel.set_selected(None)
        panel.set_busy(False)
        self.assertFalse(panel.generate_button.isEnabled())

    def test_an_edition_with_no_paragraphs_disables_everything(self):
        panel = self._panel(0)
        panel.set_selected(0)  # there is no paragraph 0 to select
        for widget in (
            panel.count_box,
            panel.generate_button,
            panel.remove_button,
        ):
            self.assertFalse(widget.isEnabled())


if __name__ == "__main__":
    unittest.main()
