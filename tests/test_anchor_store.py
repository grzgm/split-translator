import json
import tempfile
import unittest
from pathlib import Path

from split_translator.anchor_store import (
    EDITOR_SURFACE,
    READER_SURFACE,
    AnchorStore,
    anchor_path_for,
)


class AnchorStoreTests(unittest.TestCase):
    def _store(self):
        tmp = tempfile.TemporaryDirectory()
        store = AnchorStore(Path(tmp.name) / "anchors.json")
        self.addCleanup(tmp.cleanup)
        self.addCleanup(store.shutdown)
        return store

    def test_add_then_reload_round_trips(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "anchors.json"
        store = AnchorStore(path)
        store.add("b3", "b5")
        store.shutdown()  # flush
        reloaded = AnchorStore(path)
        self.addCleanup(reloaded.shutdown)
        self.assertEqual(reloaded.anchors, [("b3", "b5")])

    def test_remove_drops_pair_by_original_id(self):
        store = self._store()
        store.add("b1", "b2")
        store.add("b3", "b4")
        store.remove("b1")
        self.assertEqual(store.anchors, [("b3", "b4")])

    def test_resolve_converts_ids_to_indices(self):
        store = self._store()
        store.add("b1", "b2")
        pairs = store.resolve(["b0", "b1"], ["b0", "b1", "b2"])
        # b1 is index 1 in original; b2 is index 2 in translation.
        self.assertEqual(pairs, [(1, 2)])

    def test_resolve_drops_anchor_with_missing_id(self):
        store = self._store()
        store.add("b9", "b2")  # b9 not in the original id list below
        pairs = store.resolve(["b0", "b1"], ["b0", "b1", "b2"])
        self.assertEqual(pairs, [])

    def test_load_malformed_starts_empty(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "anchors.json"
        path.write_text("{ not json", encoding="utf-8")
        store = AnchorStore(path)
        self.addCleanup(store.shutdown)
        self.assertEqual(store.anchors, [])

    def test_path_is_stable_for_a_book_pair(self):
        root = Path("/tmp")
        a = anchor_path_for("/books/orig.epub", "/books/trans.pdf", root)
        b = anchor_path_for("/books/orig.epub", "/books/trans.pdf", root)
        self.assertEqual(a, b)
        self.assertEqual(a.parent, root)

    def test_scroll_defaults_to_none_for_both_sides(self):
        store = self._store()
        self.assertEqual(store.get_scroll(READER_SURFACE), (None, None))
        self.assertEqual(store.get_scroll(EDITOR_SURFACE), (None, None))

    def test_set_scroll_then_reload_round_trips(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "anchors.json"
        store = AnchorStore(path)
        store.set_scroll(READER_SURFACE, ("b3", 0.25), ("b7", 0.5))
        store.shutdown()  # flush
        reloaded = AnchorStore(path)
        self.addCleanup(reloaded.shutdown)
        self.assertEqual(reloaded.get_scroll(READER_SURFACE), (("b3", 0.25), ("b7", 0.5)))

    def test_reader_and_editor_scroll_are_independent(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "anchors.json"
        store = AnchorStore(path)
        store.set_scroll(READER_SURFACE, ("b3", 0.25), ("b7", 0.5))
        store.set_scroll(EDITOR_SURFACE, ("b10", 0.1), ("b20", 0.2))
        store.shutdown()
        reloaded = AnchorStore(path)
        self.addCleanup(reloaded.shutdown)
        self.assertEqual(
            reloaded.get_scroll(READER_SURFACE), (("b3", 0.25), ("b7", 0.5))
        )
        self.assertEqual(
            reloaded.get_scroll(EDITOR_SURFACE), (("b10", 0.1), ("b20", 0.2))
        )

    def test_set_scroll_keeps_existing_anchors(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "anchors.json"
        store = AnchorStore(path)
        store.add("b1", "b2")
        store.set_scroll(READER_SURFACE, ("b1", 0.0), ("b2", 0.0))
        store.shutdown()
        reloaded = AnchorStore(path)
        self.addCleanup(reloaded.shutdown)
        self.assertEqual(reloaded.anchors, [("b1", "b2")])
        self.assertEqual(reloaded.get_scroll(READER_SURFACE)[0], ("b1", 0.0))

    def test_set_scroll_with_none_clears_that_side(self):
        store = self._store()
        store.set_scroll(READER_SURFACE, ("b3", 0.25), None)
        self.assertEqual(store.get_scroll(READER_SURFACE), (("b3", 0.25), None))

    def test_load_old_file_without_scroll_starts_none(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "anchors.json"
        # A file written before scroll positions existed (anchors only).
        path.write_text(
            '{"version": 1, "anchors": [{"original": "b1", "translation": "b2"}]}',
            encoding="utf-8",
        )
        store = AnchorStore(path)
        self.addCleanup(store.shutdown)
        self.assertEqual(store.anchors, [("b1", "b2")])
        self.assertEqual(store.get_scroll(READER_SURFACE), (None, None))
        self.assertEqual(store.get_scroll(EDITOR_SURFACE), (None, None))

    def test_writes_book_basenames_for_information(self):
        # The two book file names are written near the top so the hash-named
        # file can be identified at a glance. Only the basename, never a path.
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "anchors.json"
        store = AnchorStore(
            path, "/books/library/Dune.epub", "/books/library/Diuna.epub"
        )
        store.add("b1", "b2")
        store.shutdown()  # flush
        raw = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(raw["original_file"], "Dune.epub")
        self.assertEqual(raw["translation_file"], "Diuna.epub")
        # The full path must never leak into the file.
        self.assertNotIn("/books/library", path.read_text(encoding="utf-8"))

    def test_omits_filename_fields_when_paths_unknown(self):
        # A store built without paths (e.g. in a test) writes no filename keys.
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "anchors.json"
        store = AnchorStore(path)
        store.add("b1", "b2")
        store.shutdown()
        raw = json.loads(path.read_text(encoding="utf-8"))
        self.assertNotIn("original_file", raw)
        self.assertNotIn("translation_file", raw)

    def test_filename_fields_are_ignored_on_load(self):
        # The fields are informational; loading a file that has them must work
        # and must not disturb anchors or scroll.
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "anchors.json"
        path.write_text(
            '{"version": 1, "original_file": "A.epub", '
            '"translation_file": "B.epub", '
            '"anchors": [{"original": "b1", "translation": "b2"}]}',
            encoding="utf-8",
        )
        store = AnchorStore(path)
        self.addCleanup(store.shutdown)
        self.assertEqual(store.anchors, [("b1", "b2")])

    def test_flat_scroll_shape_loads_as_reader(self):
        # A file written by the first scroll-memory version stored the position
        # flat under "scroll" (no surface key). It must load as the reader's.
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "anchors.json"
        path.write_text(
            '{"version": 1, "anchors": [], "scroll": '
            '{"original": {"id": "b3", "fraction": 0.25}, '
            '"translation": {"id": "b7", "fraction": 0.5}}}',
            encoding="utf-8",
        )
        store = AnchorStore(path)
        self.addCleanup(store.shutdown)
        self.assertEqual(
            store.get_scroll(READER_SURFACE), (("b3", 0.25), ("b7", 0.5))
        )
        self.assertEqual(store.get_scroll(EDITOR_SURFACE), (None, None))
