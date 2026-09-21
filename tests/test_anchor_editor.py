import unittest

from PySide6.QtWebEngineCore import QWebEngineProfile
from PySide6.QtWidgets import QApplication

from split_translator.anchor_click_bridge import AnchorClickBridge
from split_translator.anchor_book_view import AUTOMATIC_MARKS, MANUAL_MARK
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

from split_translator.anchor_editor import AnchorEditor
from split_translator.anchor_store import AnchorStore
from split_translator.book_sync import SectionMap


def _sections(original_doc, translation_doc):
    return SectionMap(
        original_doc.block_ids, [], translation_doc.block_ids, [], []
    )


class AnchorEditorTests(unittest.TestCase):
    def _editor(self):
        tmp = tempfile.TemporaryDirectory()
        store = AnchorStore(Path(tmp.name) / "anchors.json")
        self.changed = 0

        def on_changed():
            self.changed += 1

        original_doc = _doc("b")
        translation_doc = _doc("b")
        section_map = _sections(original_doc, translation_doc)
        editor = AnchorEditor(
            original_doc,
            translation_doc,
            store,
            section_map,
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
        self.assertTrue(callable(view.set_marks))
        self.assertTrue(callable(view.set_jump))

    def test_block_clicked_signal_relays_bridge(self):
        view = AnchorBookView(_doc(), QWebEngineProfile())
        received = []
        view.block_clicked.connect(received.append)
        # The bridge is the source of truth; emitting from it relays to the view.
        view._bridge.clicked("b3")
        self.assertEqual(received, ["b3"])

    def test_marks_are_reapplied_after_load(self):
        # set_marks can run before the page has loaded (the editor highlights
        # at construction, while setHtml is still async). The helper script is
        # only defined once the page loads, so the view must remember the marks
        # and re-apply them in the load handler, or the groups never show until
        # the next set_marks call.
        view = AnchorBookView(_doc(), QWebEngineProfile.defaultProfile())
        calls = []
        view.set_marks = lambda marks: calls.append(marks)
        view.remember_marks({MANUAL_MARK: ["b0", "b1"]})
        view._on_load_finished(True)
        self.assertEqual(calls, [{MANUAL_MARK: ["b0", "b1"]}])

    def test_no_reapply_when_load_fails(self):
        view = AnchorBookView(_doc(), QWebEngineProfile.defaultProfile())
        calls = []
        view.set_marks = lambda marks: calls.append(marks)
        view.remember_marks({MANUAL_MARK: ["b0"]})
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
        section_map = _sections(original_doc, translation_doc)
        editor = AnchorEditor(
            original_doc,
            translation_doc,
            store,
            section_map,
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
        section_map = _sections(doc, doc)
        editor = AnchorEditor(
            doc, doc, store, section_map, QWebEngineProfile(), lambda: None
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

    def test_the_views_are_given_their_section_starts(self):
        editor, _ = self._editor()
        self.assertEqual(
            editor.original_view._section_starts, ["top", "b0", "end"]
        )

    def test_set_section_map_pushes_the_new_starts(self):
        from split_translator.anchor_groups import build_groups

        editor, _ = self._editor()
        ids = ["b0", "b1"]
        groups = build_groups([("b1", "b1")], ids, ids)
        new_map = SectionMap(ids, [], ids, [], groups)
        editor.set_section_map(new_map)
        self.assertIs(editor.section_map, new_map)
        self.assertEqual(
            editor.translation_view._section_starts, ["top", "b0", "b1", "end"]
        )

    def test_a_position_without_a_section_is_not_mirrored(self):
        editor, _ = self._editor()
        calls = []
        editor.translation_view.scroll_to_section = (
            lambda k, s: calls.append((k, s))
        )
        editor._sync_from(editor.original_view, "b0", 0.5)
        self.assertEqual(calls, [])

    def test_sync_from_with_no_translation_paragraphs_does_not_raise(self):
        # A scanned or image-only translation has no paragraphs at all, so
        # there is nothing to map a scroll on the original onto.
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        store = AnchorStore(Path(tmp.name) / "anchors.json")
        self.addCleanup(store.shutdown)
        original_doc = _doc("b")
        translation_doc = BookDocument(html="", block_ids=[], title="T")
        section_map = _sections(original_doc, translation_doc)
        editor = AnchorEditor(
            original_doc,
            translation_doc,
            store,
            section_map,
            QWebEngineProfile(),
            lambda: None,
        )
        editor.sync_enabled = True
        calls = []
        editor.translation_view.scroll_to_section = (
            lambda k, s: calls.append((k, s))
        )
        editor._sync_from(editor.original_view, "b0", 0.5, 1, 0.5)  # must not raise
        self.assertEqual(calls, [])

    def test_follower_echo_does_not_reverse_drive_the_source(self):
        # The jitter bug: a genuine scroll on one side mirrors to the other, and
        # the mirrored scroll echoes back a scrollPositionChanged. That echo must
        # NOT map back and scroll the side the user is driving, or both views snap
        # at once. The side being scrolled (the gesture owner) stays put.
        editor, _ = self._editor()
        editor.sync_enabled = True

        original_calls = []
        translation_calls = []
        editor.original_view.scroll_to_section = (
            lambda k, s: original_calls.append((k, s))
        )
        editor.translation_view.scroll_to_section = (
            lambda k, s: translation_calls.append((k, s))
        )

        # Genuine user scroll on the original: it becomes the gesture owner and
        # mirrors to the translation.
        editor._sync_from(editor.original_view, "b0", 0.0, 1, 0.0)
        self.assertEqual(len(translation_calls), 1)  # mirrored to follower
        self.assertEqual(original_calls, [])  # owner not scrolled

        # The mirror's echo: the translation reports a scroll it did not initiate.
        # It is the follower, not the owner, so it must be ignored: the original
        # (owner) must not be scrolled back.
        editor._sync_from(editor.translation_view, "b0", 0.0, 1, 0.0)
        self.assertEqual(original_calls, [])  # owner still never reverse-driven

    def test_follower_echo_is_ignored_when_the_translation_drives(self):
        # The same guard the other way round: the user drives the translation,
        # and the original's echo of the mirror must not scroll it back.
        editor, _ = self._editor()
        editor.sync_enabled = True

        original_calls = []
        translation_calls = []
        editor.original_view.scroll_to_section = (
            lambda k, s: original_calls.append((k, s))
        )
        editor.translation_view.scroll_to_section = (
            lambda k, s: translation_calls.append((k, s))
        )

        editor._sync_from(editor.translation_view, "b0", 0.0, 1, 0.0)
        self.assertEqual(len(original_calls), 1)  # mirrored to the original

        editor._sync_from(editor.original_view, "b0", 0.0, 1, 0.0)
        self.assertEqual(translation_calls, [])  # the driver is not scrolled back

    def test_touching_the_other_view_transfers_ownership(self):
        # "Last view the user touched" owns the gesture. After the in-flight
        # window expires, a genuine scroll on the other side becomes the new owner
        # and mirrors, so sync still works in both directions over time.
        editor, _ = self._editor()
        editor.sync_enabled = True

        original_calls = []
        translation_calls = []
        editor.original_view.scroll_to_section = (
            lambda k, s: original_calls.append((k, s))
        )
        editor.translation_view.scroll_to_section = (
            lambda k, s: translation_calls.append((k, s))
        )

        editor._sync_from(editor.original_view, "b0", 0.0, 1, 0.0)
        self.assertEqual(len(translation_calls), 1)

        # Simulate the in-flight window having elapsed (the user paused, then
        # grabbed the translation): close the window the timer would close.
        editor._gesture.settle()

        # Now a genuine scroll on the translation must mirror to the original.
        editor._sync_from(editor.translation_view, "b1", 0.0, 1, 0.0)
        self.assertEqual(len(original_calls), 1)  # new owner mirrors to original


class AnchorEditorGroupTests(unittest.TestCase):
    """Anchors sharing a paragraph form groups: the editor grows them, refuses
    an anchor that would overlap or cross another group, and draws each group
    over its whole extent."""

    def _editor(self, anchors=(), automatic=()):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        store = AnchorStore(Path(tmp.name) / "anchors.json")
        self.addCleanup(store.shutdown)
        store.anchors = list(anchors)
        store.auto_anchors = list(automatic)
        ids = [f"b{i}" for i in range(8)]
        html = "".join(f"<p data-stid='{x}'>p</p>" for x in ids)
        doc = BookDocument(html=html, block_ids=ids, title="T")
        self.changed = 0

        def on_changed():
            self.changed += 1

        editor = AnchorEditor(
            doc, doc, store, _sections(doc, doc), QWebEngineProfile(), on_changed
        )
        return editor, store

    def _select(self, editor, original_id, translation_id):
        editor._on_original_clicked(original_id)
        editor._on_translation_clicked(translation_id)

    def test_the_status_line_starts_empty(self):
        editor, _ = self._editor()
        self.assertEqual(editor.status_label.text(), "")

    def test_an_anchor_on_an_anchored_paragraph_grows_its_group(self):
        editor, store = self._editor([("b1", "b1")])
        self._select(editor, "b1", "b2")
        editor._on_add_clicked()
        self.assertEqual(store.anchors, [("b1", "b1"), ("b1", "b2")])
        self.assertEqual(editor.status_label.text(), "")
        self.assertEqual(self.changed, 1)

    def test_a_crossing_anchor_is_refused_and_names_the_anchor_it_crosses(self):
        editor, store = self._editor([("b1", "b5")])
        self._select(editor, "b3", "b2")
        editor._on_add_clicked()
        self.assertEqual(store.anchors, [("b1", "b5")])
        self.assertEqual(
            editor.status_label.text(),
            "Not added: b3 = b2 would overlap or cross the anchor b1 = b5",
        )
        self.assertEqual(self.changed, 0)
        # The selection stays, so either side can be moved and tried again.
        self.assertEqual(editor._selected_original, "b3")
        self.assertEqual(editor._selected_translation, "b2")

    def test_an_existing_anchor_is_not_added_twice(self):
        editor, store = self._editor([("b1", "b1")])
        self._select(editor, "b1", "b1")
        editor._on_add_clicked()
        self.assertEqual(store.anchors, [("b1", "b1")])
        self.assertEqual(editor.status_label.text(), "b1 = b1 is already an anchor")
        self.assertEqual(self.changed, 0)

    def test_a_successful_add_clears_an_earlier_refusal(self):
        editor, _ = self._editor([("b1", "b5")])
        self._select(editor, "b3", "b2")
        editor._on_add_clicked()
        self._select(editor, "b6", "b6")
        editor._on_add_clicked()
        self.assertEqual(editor.status_label.text(), "")

    def test_remove_selected_removes_only_that_anchor(self):
        editor, store = self._editor([("b1", "b1"), ("b1", "b2")])
        editor.refresh()
        editor.anchor_list.setCurrentRow(1)
        editor._remove_selected()
        self.assertEqual(store.anchors, [("b1", "b1")])

    def test_anchors_ignored_on_load_are_labelled_as_conflicts(self):
        editor, _ = self._editor([("b1", "b5"), ("b3", "b2")])
        editor.refresh()
        labels = [
            editor.anchor_list.item(i).text()
            for i in range(editor.anchor_list.count())
        ]
        self.assertEqual(labels, ["b1  =  b5", "b3  =  b2  (conflicts)"])

    def _marks(self, editor):
        seen = {}
        editor.original_view.set_marks = lambda marks: seen.update(orig=marks)
        editor.translation_view.set_marks = lambda marks: seen.update(trans=marks)
        editor._refresh_highlights()
        return seen

    def test_highlights_cover_every_paragraph_of_a_group(self):
        editor, _ = self._editor([("b1", "b1"), ("b1", "b3")])
        seen = self._marks(editor)
        self.assertEqual(seen["orig"][MANUAL_MARK], ["b1"])
        self.assertEqual(seen["trans"][MANUAL_MARK], ["b1", "b2", "b3"])

    def test_highlights_leave_out_anchors_ignored_on_load(self):
        editor, _ = self._editor([("b1", "b5"), ("b3", "b2")])
        seen = self._marks(editor)
        self.assertEqual(seen["orig"][MANUAL_MARK], ["b1"])
        self.assertEqual(seen["trans"][MANUAL_MARK], ["b5"])

    def test_automatic_groups_alternate_between_two_shades(self):
        editor, _ = self._editor(
            automatic=[("b1", "b1"), ("b2", "b2"), ("b2", "b3"), ("b5", "b6")]
        )
        seen = self._marks(editor)
        self.assertEqual(
            seen["orig"],
            {MANUAL_MARK: [], AUTOMATIC_MARKS[0]: ["b1", "b5"], AUTOMATIC_MARKS[1]: ["b2"]},
        )
        self.assertEqual(
            seen["trans"],
            {
                MANUAL_MARK: [],
                AUTOMATIC_MARKS[0]: ["b1", "b6"],
                AUTOMATIC_MARKS[1]: ["b2", "b3"],
            },
        )

    def test_an_automatic_group_touching_a_manual_one_is_not_drawn(self):
        editor, _ = self._editor([("b3", "b3")], automatic=[("b3", "b4"), ("b5", "b5")])
        seen = self._marks(editor)
        self.assertEqual(
            seen["orig"],
            {MANUAL_MARK: ["b3"], AUTOMATIC_MARKS[0]: ["b5"], AUTOMATIC_MARKS[1]: []},
        )

    def test_a_manual_anchor_replaces_the_automatic_anchors_it_touches(self):
        editor, store = self._editor(automatic=[("b1", "b1"), ("b2", "b2"), ("b3", "b3")])
        self._select(editor, "b2", "b2")
        editor._on_add_clicked()
        self.assertEqual(store.anchors, [("b2", "b2")])
        self.assertEqual(store.auto_anchors, [("b1", "b1"), ("b3", "b3")])
        self.assertEqual(
            editor.status_label.text(), "Added b2 = b2; automatic anchors removed: 1"
        )

    def test_a_manual_anchor_clear_of_automatic_ones_leaves_them(self):
        editor, store = self._editor(automatic=[("b1", "b1")])
        self._select(editor, "b4", "b4")
        editor._on_add_clicked()
        self.assertEqual(store.auto_anchors, [("b1", "b1")])
        self.assertEqual(editor.status_label.text(), "")

    def _labels(self, editor):
        return [editor.anchor_list.item(i).text() for i in range(editor.anchor_list.count())]

    def test_the_list_shows_manual_anchors_only_by_default(self):
        editor, _ = self._editor([("b3", "b3")], automatic=[("b1", "b1")])
        self.assertFalse(editor.show_automatic_checkbox.isChecked())
        self.assertEqual(self._labels(editor), ["b3  =  b3"])

    def test_show_automatic_adds_them_labelled(self):
        editor, _ = self._editor([("b3", "b3")], automatic=[("b1", "b1"), ("b5", "b5")])
        editor.show_automatic_checkbox.setChecked(True)
        self.assertEqual(
            self._labels(editor),
            ["b1  =  b1  (automatic)", "b3  =  b3", "b5  =  b5  (automatic)"],
        )

    def test_an_ignored_automatic_anchor_is_labelled_and_follows_the_manual_one(self):
        editor, _ = self._editor([("b3", "b3")], automatic=[("b3", "b4")])
        editor.show_automatic_checkbox.setChecked(True)
        self.assertEqual(
            self._labels(editor),
            ["b3  =  b3", "b3  =  b4  (automatic)  (conflicts)"],
        )

    def test_an_automatic_anchor_outside_the_kept_range_is_labelled(self):
        editor, store = self._editor(automatic=[("b1", "b1"), ("b4", "b4")])
        store.set_skip(ORIGINAL_SIDE, "b2", None)
        editor.show_automatic_checkbox.setChecked(True)
        self.assertEqual(
            self._labels(editor),
            ["b1  =  b1  (automatic)  (skipped)", "b4  =  b4  (automatic)"],
        )

    def test_remove_selected_removes_an_automatic_anchor(self):
        editor, store = self._editor([("b3", "b3")], automatic=[("b3", "b3"), ("b5", "b5")])
        editor.show_automatic_checkbox.setChecked(True)
        labels = self._labels(editor)
        editor.anchor_list.setCurrentRow(labels.index("b3  =  b3  (automatic)  (conflicts)"))
        editor._remove_selected()
        self.assertEqual(store.anchors, [("b3", "b3")])
        self.assertEqual(store.auto_anchors, [("b5", "b5")])


from split_translator.skip_panel import AT_END, AT_START
from split_translator.normalise_spec import ORIGINAL_SIDE, TRANSLATION_SIDE


class AnchorEditorSkipTests(unittest.TestCase):
    """The Skip tab: counts of paragraphs each edition leaves out at its start
    and end, stored as the first and last kept ids."""

    def _editor(self, skip=None, anchors=()):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "anchors.json"
        store = AnchorStore(self.path)
        self.addCleanup(store.shutdown)
        store.anchors = list(anchors)
        for side, (first, last) in (skip or {}).items():
            store.set_skip(side, first, last)
        ids = [f"b{i}" for i in range(8)]
        html = "".join(f"<p data-stid='{x}'>p</p>" for x in ids)
        doc = BookDocument(html=html, block_ids=ids, title="T")
        self.changed = 0

        def on_changed():
            self.changed += 1

        editor = AnchorEditor(
            doc, doc, store, _sections(doc, doc), QWebEngineProfile(), on_changed
        )
        self.jumps = {ORIGINAL_SIDE: [], TRANSLATION_SIDE: []}
        for side, view in (
            (ORIGINAL_SIDE, editor.original_view),
            (TRANSLATION_SIDE, editor.translation_view),
        ):
            view.scroll_to = lambda bid, frac, s=side: self.jumps[s].append(
                ("scroll", bid)
            )
            view.set_jump = lambda bid, s=side: self.jumps[s].append(("jump", bid))
        return editor, store

    def test_the_fields_are_seeded_from_the_store(self):
        editor, _ = self._editor(
            {ORIGINAL_SIDE: ("b2", None), TRANSLATION_SIDE: ("b1", "b5")}
        )
        self.assertEqual(editor.skip_panel.skip(ORIGINAL_SIDE), (2, 0))
        self.assertEqual(editor.skip_panel.skip(TRANSLATION_SIDE), (1, 2))

    def test_a_start_change_stores_the_first_kept_paragraph_and_shows_it(self):
        editor, store = self._editor()
        editor.skip_panel.box(ORIGINAL_SIDE, AT_START).setValue(3)
        self.assertEqual(store.get_skip(ORIGINAL_SIDE), ("b3", None))
        self.assertEqual(self.changed, 1)
        self.assertEqual(
            self.jumps[ORIGINAL_SIDE], [("scroll", "b3"), ("jump", "b3")]
        )
        self.assertEqual(self.jumps[TRANSLATION_SIDE], [])
        self.assertFalse(self.path.exists())  # written on the debounce

    def test_an_end_change_stores_the_last_kept_paragraph(self):
        editor, store = self._editor()
        editor.skip_panel.box(TRANSLATION_SIDE, AT_END).setValue(2)
        self.assertEqual(store.get_skip(TRANSLATION_SIDE), (None, "b5"))
        self.assertEqual(
            self.jumps[TRANSLATION_SIDE], [("scroll", "b5"), ("jump", "b5")]
        )

    def test_skipping_nothing_again_clears_the_side(self):
        editor, store = self._editor()
        editor.skip_panel.box(ORIGINAL_SIDE, AT_START).setValue(3)
        editor.skip_panel.box(ORIGINAL_SIDE, AT_START).setValue(0)
        self.assertEqual(store.get_skip(ORIGINAL_SIDE), (None, None))

    def test_the_debounce_writes_the_skip(self):
        editor, _ = self._editor()
        editor.skip_panel.box(ORIGINAL_SIDE, AT_START).setValue(3)
        editor._save_skip()
        editor.anchor_store.shutdown()
        reloaded = AnchorStore(self.path)
        self.addCleanup(reloaded.shutdown)
        self.assertEqual(reloaded.get_skip(ORIGINAL_SIDE), ("b3", None))

    def test_closing_keeps_a_pending_change(self):
        editor, _ = self._editor()
        editor.skip_panel.box(ORIGINAL_SIDE, AT_START).setValue(3)
        editor.close()
        editor.anchor_store.shutdown()
        reloaded = AnchorStore(self.path)
        self.addCleanup(reloaded.shutdown)
        self.assertEqual(reloaded.get_skip(ORIGINAL_SIDE), ("b3", None))
        self.assertFalse(editor._skip_save_timer.isActive())

    def test_from_selection_skips_what_comes_before_the_selected_paragraph(self):
        editor, store = self._editor()
        editor._on_original_clicked("b4")
        editor._skip_from_selection(ORIGINAL_SIDE, AT_START)
        self.assertEqual(editor.skip_panel.skip(ORIGINAL_SIDE), (4, 0))
        self.assertEqual(store.get_skip(ORIGINAL_SIDE), ("b4", None))

    def test_from_selection_skips_what_comes_after_the_selected_paragraph(self):
        editor, store = self._editor()
        editor._on_translation_clicked("b5")
        editor._skip_from_selection(TRANSLATION_SIDE, AT_END)
        self.assertEqual(editor.skip_panel.skip(TRANSLATION_SIDE), (0, 2))
        self.assertEqual(store.get_skip(TRANSLATION_SIDE), (None, "b5"))

    def test_from_selection_without_a_selection_says_so(self):
        editor, store = self._editor()
        editor._skip_from_selection(ORIGINAL_SIDE, AT_START)
        self.assertEqual(
            editor.status_label.text(), "Select a paragraph in the original first"
        )
        self.assertEqual(store.get_skip(ORIGINAL_SIDE), (None, None))

    def test_from_selection_after_the_end_skip_is_refused(self):
        editor, store = self._editor()
        editor.skip_panel.box(ORIGINAL_SIDE, AT_END).setValue(5)
        editor._on_original_clicked("b6")
        editor._skip_from_selection(ORIGINAL_SIDE, AT_START)
        self.assertEqual(editor.skip_panel.skip(ORIGINAL_SIDE), (0, 5))
        self.assertEqual(store.get_skip(ORIGINAL_SIDE), (None, "b2"))
        self.assertEqual(
            editor.status_label.text(),
            "The selected paragraph is after the last kept paragraph",
        )

    def test_from_selection_before_the_start_skip_is_refused(self):
        editor, store = self._editor()
        editor.skip_panel.box(ORIGINAL_SIDE, AT_START).setValue(4)
        editor._on_original_clicked("b1")
        editor._skip_from_selection(ORIGINAL_SIDE, AT_END)
        self.assertEqual(editor.skip_panel.skip(ORIGINAL_SIDE), (4, 0))
        self.assertEqual(store.get_skip(ORIGINAL_SIDE), ("b4", None))
        self.assertEqual(
            editor.status_label.text(),
            "The selected paragraph is before the first kept paragraph",
        )

    def test_from_selection_on_the_boundary_itself_is_allowed(self):
        editor, store = self._editor()
        editor.skip_panel.box(ORIGINAL_SIDE, AT_END).setValue(5)
        editor._on_original_clicked("b2")
        editor._skip_from_selection(ORIGINAL_SIDE, AT_START)
        self.assertEqual(editor.skip_panel.skip(ORIGINAL_SIDE), (2, 5))
        self.assertEqual(store.get_skip(ORIGINAL_SIDE), ("b2", "b2"))
        self.assertEqual(editor.status_label.text(), "")

    def test_anchors_outside_the_kept_range_are_labelled(self):
        editor, _ = self._editor(
            {ORIGINAL_SIDE: ("b1", None)}, anchors=[("b0", "b0"), ("b3", "b3")]
        )
        editor.refresh()
        labels = [
            editor.anchor_list.item(i).text()
            for i in range(editor.anchor_list.count())
        ]
        self.assertEqual(labels, ["b0  =  b0  (skipped)", "b3  =  b3"])


from split_translator.anchor_store import EDITOR_SURFACE, READER_SURFACE


class AnchorEditorScrollMemoryTests(unittest.TestCase):
    def _editor_with_store(self, store):
        original_doc = _doc("b")
        translation_doc = _doc("b")
        section_map = _sections(original_doc, translation_doc)
        editor = AnchorEditor(
            original_doc,
            translation_doc,
            store,
            section_map,
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

    def test_a_saved_position_on_a_lost_block_reopens_at_a_paragraph(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "anchors.json"
        seed = AnchorStore(path)
        # The documents' paragraphs are b0 and b1; b5 no longer exists.
        seed.set_scroll(EDITOR_SURFACE, ("b5", 0.3), ("b0", 0.7))
        seed.shutdown()

        store = AnchorStore(path)
        self.addCleanup(store.shutdown)
        editor = self._editor_with_store(store)
        self.assertEqual(editor.original_view._initial_scroll, ("b1", 0.0))
        self.assertEqual(editor.translation_view._initial_scroll, ("b0", 0.7))


from split_translator.normalise_spec import (
    ORIGINAL_SIDE,
    TRANSLATION_SIDE,
    NormaliseSpec,
)


class AnchorEditorNormalisePanelTests(unittest.TestCase):
    """The normalisation panel beside the anchor list: applied live to both
    views, persisted on a debounce, and announced to the owner."""

    def _editor(self, store=None):
        if store is None:
            tmp = tempfile.TemporaryDirectory()
            self.addCleanup(tmp.cleanup)
            store = AnchorStore(Path(tmp.name) / "anchors.json")
            self.addCleanup(store.shutdown)
        self.announced = []
        original_doc = _doc("b")
        translation_doc = _doc("b")
        editor = AnchorEditor(
            original_doc,
            translation_doc,
            store,
            _sections(original_doc, translation_doc),
            QWebEngineProfile(),
            lambda: None,
            on_spec_changed=lambda side, spec: self.announced.append((side, spec)),
        )
        return editor, store

    def test_the_bottom_is_a_splitter_holding_the_list_and_the_tabs(self):
        editor, _ = self._editor()
        self.assertEqual(editor.bottom_splitter.count(), 2)
        self.assertIs(editor.bottom_splitter.widget(0), editor.anchor_list)
        self.assertIs(editor.bottom_splitter.widget(1), editor.side_tabs)
        self.assertEqual(
            [editor.side_tabs.tabText(i) for i in range(editor.side_tabs.count())],
            ["Skip", "Spacing"],
        )
        self.assertIs(editor.side_tabs.widget(1), editor.normalise_panel)

    def test_the_splitter_starts_even(self):
        # The Skip tab (the tabs' default) is wide enough that its minimum
        # width beats the requested 50/50 split while the widget has never
        # been given a real size, as in a headless construction; shown at a
        # realistic width the split is even, matching what setSizes asked for.
        editor, _ = self._editor()
        editor.resize(1400, 800)
        editor.show()
        self.addCleanup(editor.hide)
        QApplication.processEvents()
        left, right = editor.bottom_splitter.sizes()
        self.assertEqual(left, right)

    def test_seeds_the_panel_from_the_store(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        store = AnchorStore(Path(tmp.name) / "anchors.json")
        self.addCleanup(store.shutdown)
        store.set_normalise_specs(NormaliseSpec(font=0.9), NormaliseSpec())
        editor, _ = self._editor(store=store)
        self.assertAlmostEqual(editor.normalise_panel.spec(ORIGINAL_SIDE).font, 0.9)

    def test_seeds_the_views_from_the_store(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        store = AnchorStore(Path(tmp.name) / "anchors.json")
        self.addCleanup(store.shutdown)
        store.set_normalise_specs(NormaliseSpec(), NormaliseSpec(gap=0.7))
        editor, _ = self._editor(store=store)
        self.assertAlmostEqual(editor.translation_view._normalise_spec.gap, 0.7)

    def test_an_edit_reaches_that_side_s_view_only(self):
        editor, _ = self._editor()
        seen = {"orig": [], "trans": []}
        editor.original_view.set_normalise_spec = lambda s: seen["orig"].append(s)
        editor.translation_view.set_normalise_spec = lambda s: seen["trans"].append(s)
        editor.normalise_panel.box(ORIGINAL_SIDE, "font").setValue(0.9)
        self.assertEqual(len(seen["orig"]), 1)
        self.assertEqual(seen["trans"], [])
        self.assertAlmostEqual(seen["orig"][0].font, 0.9)

    def test_an_edit_is_announced_to_the_owner(self):
        editor, _ = self._editor()
        editor.normalise_panel.box(TRANSLATION_SIDE, "gap").setValue(0.8)
        self.assertEqual(len(self.announced), 1)
        side, spec = self.announced[0]
        self.assertEqual(side, TRANSLATION_SIDE)
        self.assertAlmostEqual(spec.gap, 0.8)

    def test_an_edit_does_not_persist_immediately(self):
        # Debounced: a held-down arrow must not spawn one write worker per step.
        editor, store = self._editor()
        editor.normalise_panel.box(ORIGINAL_SIDE, "font").setValue(0.9)
        self.assertTrue(store.get_normalise_specs()[0].is_default)

    def test_the_debounce_persists_when_it_fires(self):
        editor, store = self._editor()
        editor.normalise_panel.box(ORIGINAL_SIDE, "font").setValue(0.9)
        editor._save_specs()  # what the timer calls
        self.assertAlmostEqual(store.get_normalise_specs()[0].font, 0.9)

    def test_closing_flushes_a_pending_save(self):
        # BookPanel.close_doc closes the editor before shutting the store down,
        # so the last edit before closing must not be lost with the timer.
        editor, store = self._editor()
        editor.normalise_panel.box(ORIGINAL_SIDE, "font").setValue(0.9)
        editor.close()
        self.assertAlmostEqual(store.get_normalise_specs()[0].font, 0.9)

    def test_the_panel_greys_while_normalisation_is_off(self):
        editor, _ = self._editor()
        editor.normalise_checkbox.setChecked(False)
        self.assertFalse(editor.normalise_panel.isEnabled())
        editor.normalise_checkbox.setChecked(True)
        self.assertTrue(editor.normalise_panel.isEnabled())

    def test_the_panel_starts_greyed_when_the_stored_flag_is_off(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        store = AnchorStore(Path(tmp.name) / "anchors.json")
        self.addCleanup(store.shutdown)
        store.set_normalise(EDITOR_SURFACE, False)
        editor, _ = self._editor(store=store)
        self.assertFalse(editor.normalise_panel.isEnabled())

    def test_reset_reaches_both_views_and_the_owner(self):
        editor, _ = self._editor()
        editor.normalise_panel.set_specs(
            NormaliseSpec(font=0.9), NormaliseSpec(gap=0.8)
        )
        self.announced.clear()
        editor.normalise_panel.reset()
        self.assertEqual(
            [side for side, _ in self.announced], [ORIGINAL_SIDE, TRANSLATION_SIDE]
        )
        self.assertTrue(editor.original_view._normalise_spec.is_default)
        self.assertTrue(editor.translation_view._normalise_spec.is_default)
