"""A workspace can be opened before its books are chosen.

The book side then shows a placeholder instead of the two editions, and every
method that would reach for a document, an anchor store or a view does nothing
rather than raising. The gate that decides whether a workspace can be opened at
all lives in workspace.can_open.
"""

import tempfile
import unittest
from pathlib import Path

from PySide6.QtWebEngineCore import QWebEngineProfile
from PySide6.QtWidgets import QApplication

from split_translator.book_panel import BookPanel
from split_translator.config import Config
from split_translator.workspace import Workspace, can_open

app = QApplication.instance() or QApplication([])


def _workspace(original="", translation=""):
    return Workspace(
        slug="w",
        name="W",
        dir=Path("/nowhere"),
        original_path=original,
        translation_path=translation,
    )


class CanOpenTests(unittest.TestCase):
    def test_a_workspace_with_no_books_can_be_opened(self):
        self.assertTrue(can_open(_workspace()))

    def test_a_workspace_with_both_books_present_can_be_opened(self):
        with tempfile.TemporaryDirectory() as d:
            a, b = Path(d) / "a.epub", Path(d) / "b.epub"
            a.write_text("", encoding="utf-8")
            b.write_text("", encoding="utf-8")
            self.assertTrue(can_open(_workspace(str(a), str(b))))

    def test_a_half_configured_workspace_cannot_be_opened(self):
        # One path set is a broken setup to repair in the picker, not an empty
        # workspace: opening it would load one edition and not the other.
        with tempfile.TemporaryDirectory() as d:
            a = Path(d) / "a.epub"
            a.write_text("", encoding="utf-8")
            self.assertFalse(can_open(_workspace(str(a), "")))
            self.assertFalse(can_open(_workspace("", str(a))))

    def test_a_workspace_whose_book_has_moved_cannot_be_opened(self):
        with tempfile.TemporaryDirectory() as d:
            a = Path(d) / "a.epub"
            a.write_text("", encoding="utf-8")
            gone = str(Path(d) / "gone.epub")
            self.assertFalse(can_open(_workspace(str(a), gone)))


class BooklessBookPanelTests(unittest.TestCase):
    """The panel must build, and stay inert, with no books."""

    def _panel(self, directory):
        config = Config(
            name="Empty",
            dir=Path(directory),
            original_path="",
            translation_path="",
            page_anchors=[],
        )
        return BookPanel(config, QWebEngineProfile())

    def test_it_constructs_without_books(self):
        with tempfile.TemporaryDirectory() as d:
            panel = self._panel(d)
            self.assertFalse(panel.has_books)
            self.assertIsNone(panel.original_document)
            self.assertIsNone(panel.original_view)

    def test_it_writes_no_anchor_file(self):
        # The anchor file is keyed on a hash of the two book paths, so building
        # a store with no books would leave a junk file keyed on the empty pair.
        with tempfile.TemporaryDirectory() as d:
            panel = self._panel(d)
            self.assertIsNone(panel.anchor_store)
            panel.close_doc()
            self.assertEqual(list(Path(d).glob("anchors_*.json")), [])

    def test_searching_does_nothing(self):
        # The main window calls this on every dictionary lookup, so it is the
        # most likely thing to raise in a bookless workspace.
        with tempfile.TemporaryDirectory() as d:
            panel = self._panel(d)
            panel.search("dust")
            self.assertEqual(panel.match_count, 0)

    def test_the_current_match_sentence_is_empty(self):
        with tempfile.TemporaryDirectory() as d:
            panel = self._panel(d)
            got = []
            panel.current_match_sentence(got.append)
            self.assertEqual(got, [""])

    def test_navigation_and_the_anchor_editor_do_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            panel = self._panel(d)
            panel.go_to_next()
            panel.go_to_previous()
            panel.open_anchor_editor()
            self.assertIsNone(panel.anchor_editor)

    def test_the_navigation_row_stays_at_the_top(self):
        """The placeholder must take the spare height, not the nav row.

        The nav row holds two QLabels, whose vertical policy is Preferred, so
        they grow. With books the tab widget's Expanding policy outranks that
        and soaks up the spare height; with no tabs the labels took it instead,
        leaving the buttons floating about a quarter of the way down the panel.
        """
        with tempfile.TemporaryDirectory() as d:
            panel = self._panel(d)
            panel.resize(600, 800)
            panel.show()
            QApplication.processEvents()
            top = panel.prev_button.mapTo(panel, panel.prev_button.rect().topLeft())
            self.assertLess(top.y(), 40, "navigation row is not at the top")
            # The labels must be at their natural height, not stretched.
            self.assertLess(panel.match_label.height(), 60)

    def test_the_navigation_controls_are_disabled(self):
        with tempfile.TemporaryDirectory() as d:
            panel = self._panel(d)
            self.assertFalse(panel.prev_button.isEnabled())
            self.assertFalse(panel.next_button.isEnabled())
            self.assertFalse(panel.sync_checkbox.isEnabled())
            self.assertFalse(panel.normalise_checkbox.isEnabled())
