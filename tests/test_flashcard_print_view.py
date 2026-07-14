import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from split_translator.flashcard_print_view import PrintView
from split_translator.flashcards import Card

app = QApplication.instance() or QApplication([])


class PrintViewTests(unittest.TestCase):
    def test_constructs_with_controls(self):
        view = PrintView()
        self.assertIsNotNone(view.borders_checkbox)
        self.assertFalse(view.show_borders())

    def test_set_cards_does_not_raise(self):
        view = PrintView()
        view.set_cards([Card(headword="alpha", id="a")])

    def test_borders_js_toggles_class(self):
        view = PrintView()
        self.assertIn("add", view._borders_js(True))
        self.assertIn("remove", view._borders_js(False))
        self.assertIn("show-borders", view._borders_js(True))

    def test_overflow_js_marks_tiles(self):
        view = PrintView()
        self.assertIn("is-overflow", view._OVERFLOW_JS)
        self.assertIn("scrollHeight", view._OVERFLOW_JS)

    def test_fit_examples_js_measures_and_regroups(self):
        # Only the browser knows how tall a wrapped sentence renders, so the fit
        # is measured in-page: fill until the tile overflows, then sort the
        # survivors back into sense order.
        view = PrintView()
        js = view._FIT_EXAMPLES_JS
        self.assertIn("scrollHeight", js)
        self.assertIn("example-list", js)
        self.assertIn("dataset.sense", js)
        self.assertIn("sort", js)

    def test_cut_lines_checkbox_defaults_on(self):
        view = PrintView()
        self.assertIsNotNone(view.cut_lines_checkbox)
        self.assertTrue(view.print_cut_lines())

    def test_cut_lines_js_toggles_body_class(self):
        view = PrintView()
        self.assertIn("add", view._cut_lines_js(True))
        self.assertIn("remove", view._cut_lines_js(False))
        self.assertIn("print-cut-lines", view._cut_lines_js(True))

    def test_back_offset_spinbox_defaults_to_3mm(self):
        view = PrintView()
        self.assertIsNotNone(view.back_offset_spin)
        self.assertEqual(view.back_offset(), 3.0)

    def test_horizontal_back_offset_spinbox_defaults_to_zero(self):
        view = PrintView()
        self.assertIsNotNone(view.back_offset_x_spin)
        self.assertEqual(view.back_offset_x(), 0.0)

    def test_set_cards_uses_both_back_offsets(self):
        # The rendered HTML must reflect the chosen back offsets, so changing a
        # spinbox actually moves the back sheet.
        view = PrintView()
        view.back_offset_spin.setValue(5.0)
        view.back_offset_x_spin.setValue(2.0)
        html = view._render()
        self.assertIn("translate(2mm, -5mm)", html)


if __name__ == "__main__":
    unittest.main()
