import unittest

from PySide6.QtWidgets import QApplication
from PySide6.QtWebEngineCore import QWebEngineProfile

from split_translator.book_loader import BookDocument
from split_translator.book_view import BookView

app = QApplication.instance() or QApplication([])


def _doc():
    return BookDocument(
        html=(
            "<h1 data-stid='b0'>Title</h1>"
            "<p data-stid='b1'>Body text here.</p>"
        ),
        block_ids=["b0", "b1"],
        title="T",
    )


class BookViewConstructionTests(unittest.TestCase):
    def test_constructs_with_document_and_profile(self):
        profile = QWebEngineProfile()
        view = BookView(_doc(), profile)
        self.assertTrue(hasattr(view, "scrolled"))
        self.assertTrue(callable(view.scroll_to))
        self.assertTrue(callable(view.request_scroll_state))
        self.assertTrue(callable(view.find))


import tempfile

from split_translator.config import Config
from split_translator.book_panel import BookPanel
from tests.fixtures.make_fixtures import make_epub


def _config(d):
    epub = make_epub(d)
    return Config(
        pdf_original_path=epub,
        pdf_translation_path=epub,
        page_anchors=[],
    )


class BookPanelContractTests(unittest.TestCase):
    def test_constructs_and_exposes_the_main_window_contract(self):
        with tempfile.TemporaryDirectory() as d:
            profile = QWebEngineProfile()
            panel = BookPanel(_config(d), profile)
            for name in ("search", "go_to_next", "go_to_previous", "close_doc"):
                self.assertTrue(callable(getattr(panel, name)), name)

    def test_sync_checkbox_defaults_on(self):
        with tempfile.TemporaryDirectory() as d:
            profile = QWebEngineProfile()
            panel = BookPanel(_config(d), profile)
            self.assertTrue(panel.sync_checkbox.isChecked())

    def test_search_with_blank_term_is_a_noop(self):
        with tempfile.TemporaryDirectory() as d:
            profile = QWebEngineProfile()
            panel = BookPanel(_config(d), profile)
            panel.search("   ")  # must not raise
