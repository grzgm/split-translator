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


import tempfile
from pathlib import Path

from split_translator.anchor_store import AnchorStore
from split_translator.anchor_editor import AnchorEditor


class AnchorEditorTests(unittest.TestCase):
    def _editor(self):
        tmp = tempfile.TemporaryDirectory()
        store = AnchorStore(Path(tmp.name) / "anchors.json")
        self.changed = 0

        def on_changed():
            self.changed += 1

        editor = AnchorEditor(
            _doc("b"), _doc("b"), store, QWebEngineProfile(), on_changed
        )
        self.addCleanup(tmp.cleanup)
        self.addCleanup(store.shutdown)
        return editor, store

    def test_constructs_with_two_views_and_a_button(self):
        editor, _ = self._editor()
        self.assertTrue(hasattr(editor, "original_view"))
        self.assertTrue(hasattr(editor, "translation_view"))
        self.assertTrue(callable(editor.refresh))

    def test_refresh_lists_current_anchors(self):
        editor, store = self._editor()
        store.anchors = [("b0", "b1")]
        editor.refresh()
        self.assertEqual(editor.anchor_list.count(), 1)

    def test_capture_pair_adds_to_store_and_notifies(self):
        editor, store = self._editor()
        # Capture directly with known ids (bypassing async JS read in the test).
        editor._capture_pair("b0", "b1")
        self.assertEqual(store.anchors, [("b0", "b1")])
        self.assertEqual(editor.anchor_list.count(), 1)
        self.assertGreaterEqual(self.changed, 1)

    def test_remove_selected_drops_pair(self):
        editor, store = self._editor()
        editor._capture_pair("b0", "b1")
        editor.anchor_list.setCurrentRow(0)
        editor._remove_selected()
        self.assertEqual(store.anchors, [])
