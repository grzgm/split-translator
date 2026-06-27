import unittest

from PySide6.QtWidgets import QApplication
from PySide6.QtWebEngineCore import QWebEngineProfile

from split_translator.book_loader import BookDocument
from split_translator.book_view import BookView
from split_translator.anchor_click_bridge import AnchorClickBridge

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

class AnchorClickBridgeTests(unittest.TestCase):
    def test_clicked_emits_block_clicked(self):
        bridge = AnchorClickBridge()
        received = []
        bridge.block_clicked.connect(received.append)
        bridge.clicked("b7")
        self.assertEqual(received, ["b7"])


from split_translator.anchor_book_view import AnchorBookView


class AnchorBookViewTests(unittest.TestCase):
    def test_constructs_and_exposes_highlight_methods(self):
        view = AnchorBookView(_doc(), QWebEngineProfile())
        self.assertTrue(hasattr(view, "block_clicked"))
        self.assertTrue(callable(view.set_selected))
        self.assertTrue(callable(view.set_anchored))
        self.assertTrue(callable(view.set_jump))

    def test_block_clicked_signal_relays_bridge(self):
        view = AnchorBookView(_doc(), QWebEngineProfile())
        received = []
        view.block_clicked.connect(received.append)
        # The bridge is the source of truth; emitting from it relays to the view.
        view._bridge.clicked("b3")
        self.assertEqual(received, ["b3"])


class AnchorEditorSelectionTests(unittest.TestCase):
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

    def test_add_button_disabled_until_both_sides_selected(self):
        editor, _ = self._editor()
        self.assertFalse(editor.add_button.isEnabled())
        editor._on_original_clicked("b0")
        self.assertFalse(editor.add_button.isEnabled())  # only one side
        editor._on_translation_clicked("b1")
        self.assertTrue(editor.add_button.isEnabled())  # both sides

    def test_add_binds_current_selections_and_clears(self):
        editor, store = self._editor()
        editor._on_original_clicked("b0")
        editor._on_translation_clicked("b1")
        editor._on_add_clicked()
        self.assertEqual(store.anchors, [("b0", "b1")])
        # Selections clear and the button disables again.
        self.assertIsNone(editor._selected_original)
        self.assertIsNone(editor._selected_translation)
        self.assertFalse(editor.add_button.isEnabled())
        self.assertGreaterEqual(self.changed, 1)

    def test_add_is_noop_without_both_selections(self):
        editor, store = self._editor()
        editor._on_original_clicked("b0")  # only original
        editor._on_add_clicked()
        self.assertEqual(store.anchors, [])

    def test_reselecting_replaces_that_sides_selection(self):
        editor, _ = self._editor()
        editor._on_original_clicked("b0")
        editor._on_original_clicked("b2")
        self.assertEqual(editor._selected_original, "b2")

    def test_refresh_stores_both_ids_per_item(self):
        editor, store = self._editor()
        store.anchors = [("b0", "b1")]
        editor.refresh()
        item = editor.anchor_list.item(0)
        self.assertEqual(item.data(256), "b0")  # Qt.UserRole
        self.assertEqual(item.data(257), "b1")  # Qt.UserRole + 1

    def test_remove_selected_drops_pair(self):
        editor, store = self._editor()
        store.anchors = [("b0", "b1")]
        editor.refresh()
        editor.anchor_list.setCurrentRow(0)
        editor._remove_selected()
        self.assertEqual(store.anchors, [])
