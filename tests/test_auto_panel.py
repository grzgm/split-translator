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
        panel.from_selection.connect(lambda: self.requests.append(("from selection",)))
        return panel

    def test_a_batch_starts_at_the_first_paragraph_and_covers_the_default_count(self):
        panel = self._panel()
        self.assertEqual(panel.start(), 0)
        self.assertEqual(panel.start_box.value(), 1)  # shown counted from 1
        self.assertEqual(panel.count(), DEFAULT_COUNT)

    def test_the_count_never_exceeds_the_edition(self):
        self.assertEqual(self._panel(30).count(), 30)

    def test_generate_and_remove_announce_the_batch(self):
        panel = self._panel()
        panel.start_box.setValue(11)
        panel.count_box.setValue(40)
        panel.generate_button.click()
        panel.remove_button.click()
        self.assertEqual(self.requests, [("generate", 10, 40), ("remove", 10, 40)])

    def test_from_selection_is_announced(self):
        panel = self._panel()
        panel.from_selection_button.click()
        self.assertEqual(self.requests, [("from selection",)])

    def test_set_start_takes_a_position_and_clamps_it(self):
        panel = self._panel(50)
        panel.set_start(7)
        self.assertEqual((panel.start(), panel.start_box.value()), (7, 8))
        panel.set_start(80)
        self.assertEqual(panel.start(), 49)
        panel.set_start(-3)
        self.assertEqual(panel.start(), 0)
        self.assertEqual(self.requests, [])

    def test_busy_disables_generate_and_remove_until_done(self):
        panel = self._panel()
        panel.set_busy(True)
        self.assertFalse(panel.generate_button.isEnabled())
        self.assertFalse(panel.remove_button.isEnabled())
        self.assertTrue(panel.start_box.isEnabled())
        panel.set_busy(False)
        self.assertTrue(panel.generate_button.isEnabled())
        self.assertTrue(panel.remove_button.isEnabled())

    def test_an_edition_with_no_paragraphs_disables_everything(self):
        panel = self._panel(0)
        for widget in (
            panel.start_box,
            panel.count_box,
            panel.from_selection_button,
            panel.generate_button,
            panel.remove_button,
        ):
            self.assertFalse(widget.isEnabled())


if __name__ == "__main__":
    unittest.main()
