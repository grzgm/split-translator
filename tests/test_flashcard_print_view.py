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


if __name__ == "__main__":
    unittest.main()
