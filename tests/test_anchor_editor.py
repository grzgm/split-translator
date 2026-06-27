import unittest

from PySide6.QtWidgets import QApplication
from PySide6.QtWebEngineCore import QWebEngineProfile

from split_translator.book_loader import BookDocument
from split_translator.book_view import BookView

app = QApplication.instance() or QApplication([])


def _doc(prefix="b"):
    return BookDocument(
        html=(
            f"<p data-stid='{prefix}0'>One</p>"
            f"<p data-stid='{prefix}1'>Two</p>"
        ),
        block_ids=[f"{prefix}0", f"{prefix}1"],
        title="T",
    )


class TopmostBlockIdTests(unittest.TestCase):
    def test_method_is_callable(self):
        view = BookView(_doc(), QWebEngineProfile())
        self.assertTrue(callable(view.topmost_block_id))
