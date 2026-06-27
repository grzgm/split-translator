import tempfile
import unittest
from pathlib import Path

from split_translator.anchor_store import AnchorStore, anchor_path_for


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
