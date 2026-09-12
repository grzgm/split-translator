"""The window-level half of the wide layout: the View menu entry moves both
panels together and remembers the choice for the workspace.

Tested against a stub window, the way tests/test_main_window_workspace.py does,
so the methods can be exercised without building the WebEngine-heavy window.
"""

import json
import tempfile
import unittest
from pathlib import Path

from split_translator.config import Config
from split_translator.layout import LAYOUT_DEFAULT, LAYOUT_WIDE
from split_translator.main_window import TranslationTool


class _StubPanel:
    def __init__(self):
        self.layout = None

    def set_layout(self, layout):
        self.layout = layout


class _StubSplitter:
    def __init__(self):
        self.sizes = None

    def setSizes(self, sizes):
        self.sizes = sizes


class _StubWindow:
    def __init__(self, config):
        self.config = config
        self.dictionary_panel = _StubPanel()
        self.book_panel = _StubPanel()
        self.content_splitter = _StubSplitter()

    def apply_layout(self, layout):
        # The real one: the toggle is meant to go through it, so the stub
        # stands in for the window's widgets, not for its behaviour.
        TranslationTool.apply_layout(self, layout)


def _config(d, layout=LAYOUT_DEFAULT):
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


class ApplyLayoutTests(unittest.TestCase):
    def test_both_panels_are_moved_together(self):
        with tempfile.TemporaryDirectory() as d:
            window = _StubWindow(_config(d))
            TranslationTool.apply_layout(window, LAYOUT_WIDE)
            self.assertEqual(window.dictionary_panel.layout, LAYOUT_WIDE)
            self.assertEqual(window.book_panel.layout, LAYOUT_WIDE)

    def test_the_wide_layout_gives_the_books_the_greater_share(self):
        with tempfile.TemporaryDirectory() as d:
            window = _StubWindow(_config(d))
            TranslationTool.apply_layout(window, LAYOUT_WIDE)
            dictionary, books = window.content_splitter.sizes
            self.assertGreater(books, dictionary)

    def test_the_default_layout_gives_the_dictionary_the_greater_share(self):
        with tempfile.TemporaryDirectory() as d:
            window = _StubWindow(_config(d))
            TranslationTool.apply_layout(window, LAYOUT_DEFAULT)
            dictionary, books = window.content_splitter.sizes
            self.assertGreater(dictionary, books)

    def test_an_unreadable_layout_applies_the_default_view(self):
        with tempfile.TemporaryDirectory() as d:
            window = _StubWindow(_config(d))
            TranslationTool.apply_layout(window, "sideways")
            self.assertEqual(window.dictionary_panel.layout, LAYOUT_DEFAULT)


class ToggleWideLayoutTests(unittest.TestCase):
    def test_ticking_it_switches_and_records_the_choice(self):
        with tempfile.TemporaryDirectory() as d:
            _write_config(d)
            window = _StubWindow(_config(d))
            TranslationTool.toggle_wide_layout(window, True)
            self.assertEqual(window.book_panel.layout, LAYOUT_WIDE)
            raw = json.loads(
                (Path(d) / "config.json").read_text(encoding="utf-8")
            )
            self.assertEqual(raw["layout"], "wide")

    def test_unticking_it_returns_to_the_default_view(self):
        with tempfile.TemporaryDirectory() as d:
            _write_config(d)
            window = _StubWindow(_config(d, LAYOUT_WIDE))
            TranslationTool.toggle_wide_layout(window, False)
            self.assertEqual(window.book_panel.layout, LAYOUT_DEFAULT)
            raw = json.loads(
                (Path(d) / "config.json").read_text(encoding="utf-8")
            )
            self.assertEqual(raw["layout"], "default")
