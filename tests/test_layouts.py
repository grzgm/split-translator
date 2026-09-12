"""Choosing a view from the View menu.

The window is built for one view and never rearranged, so choosing the other one
records the choice and closes the window; the workspace session in app.py then
builds a fresh window for the same workspace. Tested against a stub window, the
way tests/test_main_window_workspace.py does, so the methods can be exercised
without building the WebEngine-heavy window.
"""

import json
import tempfile
import unittest
from pathlib import Path

from split_translator import main_window
from split_translator.config import Config
from split_translator.layout import LAYOUT_BOOK, LAYOUT_NORMAL
from split_translator.main_window import TranslationTool


class _StubWindow:
    def __init__(self, config):
        self.config = config
        self.next_workspace = None
        self.closed = False

    def close(self):
        self.closed = True


def _config(d, layout=LAYOUT_NORMAL):
    return Config(
        name="Lalka",
        dir=Path(d),
        original_path="/books/a.epub",
        translation_path="/books/b.epub",
        page_anchors=[],
        layout=layout,
    )


def _write_config(d):
    (Path(d) / "config.json").write_text(
        json.dumps(
            {
                "name": "Lalka",
                "original_path": "/books/a.epub",
                "translation_path": "/books/b.epub",
            }
        ),
        encoding="utf-8",
    )


def _stored_layout(d):
    raw = json.loads((Path(d) / "config.json").read_text(encoding="utf-8"))
    return raw.get("layout")


class ChooseLayoutTests(unittest.TestCase):
    def test_choosing_the_book_view_records_it_and_closes_the_window(self):
        with tempfile.TemporaryDirectory() as d:
            _write_config(d)
            window = _StubWindow(_config(d))
            TranslationTool.choose_layout(window, LAYOUT_BOOK)
            self.assertEqual(_stored_layout(d), "book")
            self.assertTrue(window.closed)

    def test_it_reopens_the_same_workspace(self):
        # The session opens whatever next_workspace names, so this is what makes
        # the rebuild land back on the workspace that was open.
        with tempfile.TemporaryDirectory() as d:
            _write_config(d)
            window = _StubWindow(_config(d))
            TranslationTool.choose_layout(window, LAYOUT_BOOK)
            self.assertEqual(window.next_workspace, Path(d).name)

    def test_choosing_the_normal_view_records_it_and_closes_the_window(self):
        with tempfile.TemporaryDirectory() as d:
            _write_config(d)
            window = _StubWindow(_config(d, LAYOUT_BOOK))
            TranslationTool.choose_layout(window, LAYOUT_NORMAL)
            self.assertEqual(_stored_layout(d), "normal")
            self.assertTrue(window.closed)

    def test_choosing_the_view_already_open_changes_nothing(self):
        # The menu marks the open view, and its entry stays clickable. Clicking
        # it must not throw the window away and rebuild it for no reason.
        with tempfile.TemporaryDirectory() as d:
            _write_config(d)
            window = _StubWindow(_config(d))
            TranslationTool.choose_layout(window, LAYOUT_NORMAL)
            self.assertIsNone(_stored_layout(d))
            self.assertFalse(window.closed)
            self.assertIsNone(window.next_workspace)

    def test_an_unreadable_stored_layout_counts_as_the_normal_view(self):
        with tempfile.TemporaryDirectory() as d:
            _write_config(d)
            window = _StubWindow(_config(d, "sideways"))
            TranslationTool.choose_layout(window, LAYOUT_NORMAL)
            self.assertFalse(window.closed)


class SplitterShareTests(unittest.TestCase):
    def test_the_normal_view_gives_the_dictionary_the_greater_share(self):
        dictionary, books = main_window._SPLITTER_SIZES[LAYOUT_NORMAL]
        self.assertGreater(dictionary, books)

    def test_the_book_view_gives_the_books_the_greater_share(self):
        # Two editions are on screen there, so each ends up about as wide as the
        # dictionary column.
        dictionary, books = main_window._SPLITTER_SIZES[LAYOUT_BOOK]
        self.assertGreater(books, dictionary)
