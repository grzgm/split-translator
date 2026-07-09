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
from split_translator.book_sync import BookSync


class AnchorEditorTests(unittest.TestCase):
    def _editor(self):
        tmp = tempfile.TemporaryDirectory()
        store = AnchorStore(Path(tmp.name) / "anchors.json")
        self.changed = 0

        def on_changed():
            self.changed += 1

        original_doc = _doc("b")
        translation_doc = _doc("b")
        book_sync = BookSync(
            len(original_doc.block_ids), len(translation_doc.block_ids)
        )
        editor = AnchorEditor(
            original_doc,
            translation_doc,
            store,
            book_sync,
            QWebEngineProfile(),
            on_changed,
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

    def test_each_find_bar_has_a_search_button(self):
        # One Search button per edition (alongside Prev / Next), so a search can
        # be run by button as well as by pressing Enter.
        from PySide6.QtWidgets import QPushButton

        editor, _ = self._editor()
        search_buttons = [
            b
            for b in editor.findChildren(QPushButton)
            if b.text() == "Search"
        ]
        self.assertEqual(len(search_buttons), 2)

    def test_normalise_checkbox_defaults_on(self):
        editor, _ = self._editor()
        self.assertTrue(editor.normalise_checkbox.isChecked())
        self.assertTrue(editor._normalise)

    def test_toggle_normalise_sets_both_views_and_persists(self):
        editor, store = self._editor()
        seen = {"orig": [], "trans": []}
        editor.original_view.set_normalise = lambda v: seen["orig"].append(v)
        editor.translation_view.set_normalise = lambda v: seen["trans"].append(v)
        editor.normalise_checkbox.setChecked(False)
        self.assertFalse(editor._normalise)
        self.assertEqual(seen["orig"], [False])
        self.assertEqual(seen["trans"], [False])
        from split_translator.anchor_store import EDITOR_SURFACE

        self.assertFalse(store.get_normalise(EDITOR_SURFACE))

    def test_editor_normalise_is_independent_of_reader(self):
        # Toggling the editor's flag off must not change the reader-surface flag.
        editor, store = self._editor()
        from split_translator.anchor_store import EDITOR_SURFACE, READER_SURFACE

        editor.normalise_checkbox.setChecked(False)
        self.assertFalse(store.get_normalise(EDITOR_SURFACE))
        self.assertTrue(store.get_normalise(READER_SURFACE))  # untouched default


class AnchorClickBridgeTests(unittest.TestCase):
    def test_clicked_emits_block_clicked(self):
        bridge = AnchorClickBridge()
        received = []
        bridge.block_clicked.connect(received.append)
        bridge.clicked("b7")
        self.assertEqual(received, ["b7"])


from split_translator.anchor_editor import _EditorSearch


class _FakeView:
    """Stands in for an AnchorBookView: records finds and jump highlights, and
    replays a scripted (active, count) for each find so the helper's counter and
    stepping logic can be driven without a live page."""

    def __init__(self, script):
        # script: list of (active, count) tuples, consumed one per find() call.
        self._script = list(script)
        self.find_calls = []  # (term, forward)
        self.jump_calls = []  # block ids passed to set_jump
        self.block_for_index = {}  # active index -> block id for matched_block_id

    def find(self, term, forward, callback):
        self.find_calls.append((term, forward))
        active, count = self._script.pop(0) if self._script else (0, 0)
        callback(active, count)

    def matched_block_id(self, term, index, callback):
        callback(self.block_for_index.get(index, ""))

    def set_jump(self, block_id):
        self.jump_calls.append(block_id)


class EditorSearchTests(unittest.TestCase):
    def _search(self, view):
        self.labels = []
        return _EditorSearch(view, self.labels.append)

    def test_search_finds_forward_and_shows_the_counter(self):
        view = _FakeView([(3, 12)])
        view.block_for_index = {3: "b5"}
        search = self._search(view)
        search.search("word")
        self.assertEqual(view.find_calls, [("word", True)])
        self.assertEqual(self.labels[-1], "3 / 12")
        self.assertEqual(view.jump_calls[-1], "b5")  # match block highlighted

    def test_empty_term_clears_the_jump_and_label(self):
        view = _FakeView([(3, 12)])
        view.block_for_index = {3: "b5"}
        search = self._search(view)
        search.search("word")
        view.jump_calls.clear()
        search.search("   ")  # blank
        self.assertEqual(view.find_calls, [("word", True)])  # no new find
        self.assertEqual(view.jump_calls, [""])  # jump cleared
        self.assertEqual(self.labels[-1], "")

    def test_no_matches_reports_and_clears_jump(self):
        view = _FakeView([(0, 0)])
        search = self._search(view)
        search.search("zzz")
        self.assertEqual(self.labels[-1], "No matches")
        self.assertEqual(view.jump_calls[-1], "")

    def test_next_and_prev_step_the_active_term(self):
        view = _FakeView([(1, 3), (2, 3), (1, 3)])
        search = self._search(view)
        search.search("a")  # find #1, forward
        search.next()  # find #2, forward
        search.prev()  # find #3, backward
        self.assertEqual(
            view.find_calls,
            [("a", True), ("a", True), ("a", False)],
        )

    def test_step_without_a_term_does_nothing(self):
        view = _FakeView([])
        search = self._search(view)
        search.next()  # nothing searched yet
        search.prev()
        self.assertEqual(view.find_calls, [])


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

    def test_anchored_ids_reapplied_after_load(self):
        # set_anchored can run before the page has loaded (the editor highlights
        # at construction, while setHtml is still async). The highlight JS is
        # only defined once the page loads, so the view must remember the ids and
        # re-apply them in the load handler, or the anchors never light up until
        # the next set_anchored call.
        view = AnchorBookView(_doc(), QWebEngineProfile.defaultProfile())
        calls = []
        view.set_anchored = lambda ids: calls.append(list(ids))
        view.remember_anchored(["b0", "b1"])  # what the editor asks to highlight
        calls.clear()
        view._on_load_finished(True)
        self.assertEqual(calls, [["b0", "b1"]])

    def test_no_reapply_when_load_fails(self):
        view = AnchorBookView(_doc(), QWebEngineProfile.defaultProfile())
        calls = []
        view.set_anchored = lambda ids: calls.append(list(ids))
        view.remember_anchored(["b0"])
        calls.clear()
        view._on_load_finished(False)  # a failed load re-applies nothing
        self.assertEqual(calls, [])


class AnchorEditorSelectionTests(unittest.TestCase):
    def _editor(self):
        tmp = tempfile.TemporaryDirectory()
        store = AnchorStore(Path(tmp.name) / "anchors.json")
        self.changed = 0

        def on_changed():
            self.changed += 1

        original_doc = _doc("b")
        translation_doc = _doc("b")
        book_sync = BookSync(
            len(original_doc.block_ids), len(translation_doc.block_ids)
        )
        editor = AnchorEditor(
            original_doc,
            translation_doc,
            store,
            book_sync,
            QWebEngineProfile(),
            on_changed,
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

    def test_list_is_ordered_lowest_first_by_block_index(self):
        # Build an editor over a document large enough to expose the b7 vs b100
        # case (lexical sort would wrongly put b100 before b7).
        tmp = tempfile.TemporaryDirectory()
        store = AnchorStore(Path(tmp.name) / "anchors.json")
        ids = [f"b{i}" for i in range(120)]
        html = "".join(f"<p data-stid='{x}'>p</p>" for x in ids)
        doc = BookDocument(html=html, block_ids=ids, title="T")
        book_sync = BookSync(len(ids), len(ids))
        editor = AnchorEditor(
            doc, doc, store, book_sync, QWebEngineProfile(), lambda: None
        )
        self.addCleanup(tmp.cleanup)
        self.addCleanup(store.shutdown)

        store.anchors = [("b100", "b100"), ("b7", "b7"), ("b0", "b0")]
        editor.refresh()
        shown = [
            editor.anchor_list.item(i).data(256)
            for i in range(editor.anchor_list.count())
        ]
        self.assertEqual(shown, ["b0", "b7", "b100"])
        # The stored order is left untouched (display-only sort).
        self.assertEqual(
            [p[0] for p in store.anchors], ["b100", "b7", "b0"]
        )

    def test_sync_defaults_on(self):
        editor, _ = self._editor()
        self.assertTrue(editor.sync_enabled)
        self.assertTrue(editor.sync_checkbox.isChecked())

    def test_sync_from_disabled_is_a_noop(self):
        editor, _ = self._editor()
        editor.sync_enabled = False
        # Must not raise and must not move the other view (no mapping applied).
        editor._sync_from(editor.original_view, "b0", 0.0)

    def test_sync_from_unknown_block_does_not_raise(self):
        editor, _ = self._editor()
        editor.sync_enabled = True
        # A block id absent from the document is guarded by try/except ValueError.
        editor._sync_from(editor.original_view, "nonexistent", 0.0)

    def test_follower_echo_does_not_reverse_drive_the_source(self):
        # The jitter bug: a genuine scroll on one side mirrors to the other, and
        # the mirrored scroll echoes back a scrollPositionChanged. That echo must
        # NOT map back and scroll the side the user is driving, or both views snap
        # at once. The side being scrolled (the gesture owner) stays put.
        editor, _ = self._editor()
        editor.sync_enabled = True

        original_calls = []
        translation_calls = []
        editor.original_view.scroll_to = (
            lambda bid, frac: original_calls.append((bid, frac))
        )
        editor.translation_view.scroll_to = (
            lambda bid, frac: translation_calls.append((bid, frac))
        )

        # Genuine user scroll on the original: it becomes the gesture owner and
        # mirrors to the translation.
        editor._sync_from(editor.original_view, "b0", 0.0)
        self.assertEqual(len(translation_calls), 1)  # mirrored to follower
        self.assertEqual(original_calls, [])  # owner not scrolled

        # The mirror's echo: the translation reports a scroll it did not initiate.
        # It is the follower, not the owner, so it must be ignored: the original
        # (owner) must not be scrolled back.
        editor._sync_from(editor.translation_view, "b0", 0.0)
        self.assertEqual(original_calls, [])  # owner still never reverse-driven

    def test_touching_the_other_view_transfers_ownership(self):
        # "Last view the user touched" owns the gesture. After the in-flight
        # window expires, a genuine scroll on the other side becomes the new owner
        # and mirrors, so sync still works in both directions over time.
        editor, _ = self._editor()
        editor.sync_enabled = True

        original_calls = []
        translation_calls = []
        editor.original_view.scroll_to = (
            lambda bid, frac: original_calls.append((bid, frac))
        )
        editor.translation_view.scroll_to = (
            lambda bid, frac: translation_calls.append((bid, frac))
        )

        editor._sync_from(editor.original_view, "b0", 0.0)
        self.assertEqual(len(translation_calls), 1)

        # Simulate the in-flight window having elapsed (the user paused, then
        # grabbed the translation): clear the guard the timer would clear.
        editor._end_sync_gesture()

        # Now a genuine scroll on the translation must mirror to the original.
        editor._sync_from(editor.translation_view, "b1", 0.0)
        self.assertEqual(len(original_calls), 1)  # new owner mirrors to original


from split_translator.anchor_store import EDITOR_SURFACE, READER_SURFACE


class AnchorEditorScrollMemoryTests(unittest.TestCase):
    def _editor_with_store(self, store):
        original_doc = _doc("b")
        translation_doc = _doc("b")
        book_sync = BookSync(
            len(original_doc.block_ids), len(translation_doc.block_ids)
        )
        editor = AnchorEditor(
            original_doc,
            translation_doc,
            store,
            book_sync,
            QWebEngineProfile(),
            lambda: None,
        )
        return editor

    def test_sync_from_caches_scroll_even_with_sync_off(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        store = AnchorStore(Path(tmp.name) / "anchors.json")
        self.addCleanup(store.shutdown)
        editor = self._editor_with_store(store)
        editor.sync_enabled = False
        editor._sync_from(editor.original_view, "b0", 0.3)
        editor._sync_from(editor.translation_view, "b1", 0.4)
        self.assertEqual(editor._original_scroll, ("b0", 0.3))
        self.assertEqual(editor._translation_scroll, ("b1", 0.4))

    def test_close_persists_to_editor_surface_only(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "anchors.json"
        store = AnchorStore(path)
        editor = self._editor_with_store(store)
        editor.sync_enabled = False
        editor._sync_from(editor.original_view, "b0", 0.3)
        editor._sync_from(editor.translation_view, "b1", 0.4)
        editor.close()  # fires closeEvent -> set_scroll(EDITOR_SURFACE, ...)
        store.shutdown()

        reloaded = AnchorStore(path)
        self.addCleanup(reloaded.shutdown)
        self.assertEqual(
            reloaded.get_scroll(EDITOR_SURFACE), (("b0", 0.3), ("b1", 0.4))
        )
        # The reader surface is left untouched by the editor.
        self.assertEqual(reloaded.get_scroll(READER_SURFACE), (None, None))

    def test_editor_seeds_views_from_editor_surface(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "anchors.json"
        seed = AnchorStore(path)
        # Reader and editor stored at different spots; the editor must use its own.
        seed.set_scroll(READER_SURFACE, ("b1", 0.9), ("b1", 0.9))
        seed.set_scroll(EDITOR_SURFACE, ("b0", 0.2), ("b1", 0.7))
        seed.shutdown()

        store = AnchorStore(path)
        self.addCleanup(store.shutdown)
        editor = self._editor_with_store(store)
        self.assertEqual(editor.original_view._initial_scroll, ("b0", 0.2))
        self.assertEqual(editor.translation_view._initial_scroll, ("b1", 0.7))
