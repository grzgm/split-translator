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
from split_translator.normalise_spec import (
    ORIGINAL_SIDE,
    TRANSLATION_SIDE,
    NormaliseSpec,
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

    def test_remove_drops_exactly_that_pair(self):
        # b1 is matched to two translation paragraphs; removing one keeps the
        # other.
        store = self._store()
        store.add("b1", "b2")
        store.add("b1", "b3")
        store.add("b4", "b5")
        store.remove("b1", "b3")
        self.assertEqual(store.anchors, [("b1", "b2"), ("b4", "b5")])

    def test_add_skips_an_exact_duplicate(self):
        store = self._store()
        store.add("b1", "b2")
        store.add("b1", "b2")
        self.assertEqual(store.anchors, [("b1", "b2")])

    def test_exact_duplicates_are_dropped_on_load(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "anchors.json"
        path.write_text(
            json.dumps(
                {
                    "anchors": [
                        {"original": "b1", "translation": "b2"},
                        {"original": "b3", "translation": "b4"},
                        {"original": "b1", "translation": "b2"},
                    ]
                }
            ),
            encoding="utf-8",
        )
        store = AnchorStore(path)
        self.addCleanup(store.shutdown)
        self.assertEqual(store.anchors, [("b1", "b2"), ("b3", "b4")])

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

    # --- paragraph-normalisation flag (per surface, default ON) ----------

    def test_normalise_defaults_to_on_for_both_surfaces(self):
        store = self._store()
        self.assertTrue(store.get_normalise(READER_SURFACE))
        self.assertTrue(store.get_normalise(EDITOR_SURFACE))

    def test_set_normalise_then_reload_round_trips(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "anchors.json"
        store = AnchorStore(path)
        store.set_normalise(READER_SURFACE, False)
        store.shutdown()
        reloaded = AnchorStore(path)
        self.addCleanup(reloaded.shutdown)
        self.assertFalse(reloaded.get_normalise(READER_SURFACE))

    def test_reader_and_editor_normalise_are_independent(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "anchors.json"
        store = AnchorStore(path)
        store.set_normalise(READER_SURFACE, False)
        store.set_normalise(EDITOR_SURFACE, True)
        store.shutdown()
        reloaded = AnchorStore(path)
        self.addCleanup(reloaded.shutdown)
        self.assertFalse(reloaded.get_normalise(READER_SURFACE))
        self.assertTrue(reloaded.get_normalise(EDITOR_SURFACE))

    def test_set_normalise_keeps_existing_anchors(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "anchors.json"
        store = AnchorStore(path)
        store.add("b3", "b5")
        store.set_normalise(READER_SURFACE, False)
        store.shutdown()
        reloaded = AnchorStore(path)
        self.addCleanup(reloaded.shutdown)
        self.assertEqual(reloaded.anchors, [("b3", "b5")])
        self.assertFalse(reloaded.get_normalise(READER_SURFACE))

    def test_old_file_without_normalise_defaults_on(self):
        # A file written before this feature has no "normalise" block; both
        # surfaces must then report the default (ON).
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "anchors.json"
        path.write_text('{"version": 1, "anchors": []}', encoding="utf-8")
        store = AnchorStore(path)
        self.addCleanup(store.shutdown)
        self.assertTrue(store.get_normalise(READER_SURFACE))
        self.assertTrue(store.get_normalise(EDITOR_SURFACE))

    def test_get_normalise_honours_an_explicit_default(self):
        # A caller may pass default=False; an unset surface then reports False.
        store = self._store()
        self.assertFalse(store.get_normalise(READER_SURFACE, default=False))


class NormaliseScaleTests(unittest.TestCase):
    """The two editions' normalisation multipliers, stored per book pair and
    shared by the reader and the editor."""

    def _path(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return Path(tmp.name) / "anchors.json"

    def _store(self, path):
        store = AnchorStore(path)
        self.addCleanup(store.shutdown)
        return store

    def test_defaults_when_nothing_is_stored(self):
        store = self._store(self._path())
        original, translation = store.get_normalise_specs()
        self.assertTrue(original.is_default)
        self.assertTrue(translation.is_default)

    def test_round_trips_through_the_file(self):
        path = self._path()
        store = self._store(path)
        store.set_normalise_specs(
            NormaliseSpec(font=0.9, gap=0.8), NormaliseSpec(line_height=1.2)
        )
        store.shutdown()
        reloaded = self._store(path)
        original, translation = reloaded.get_normalise_specs()
        self.assertEqual(original, NormaliseSpec(font=0.9, gap=0.8))
        self.assertEqual(translation, NormaliseSpec(line_height=1.2))

    def test_a_default_side_is_not_written(self):
        # Keeps the file clean, and means a reset removes the key rather than
        # leaving a block of ones behind.
        path = self._path()
        store = self._store(path)
        store.set_normalise_specs(NormaliseSpec(font=0.9), NormaliseSpec())
        store.shutdown()
        raw = json.loads(path.read_text())
        self.assertEqual(list(raw["normalise_scale"]), [ORIGINAL_SIDE])

    def test_resetting_both_sides_drops_the_key(self):
        path = self._path()
        store = self._store(path)
        store.set_normalise_specs(NormaliseSpec(font=0.9), NormaliseSpec())
        store.set_normalise_specs(NormaliseSpec(), NormaliseSpec())
        store.shutdown()
        raw = json.loads(path.read_text())
        self.assertNotIn("normalise_scale", raw)

    def test_a_malformed_block_gives_defaults(self):
        path = self._path()
        path.write_text(json.dumps({"normalise_scale": "nonsense"}))
        original, translation = self._store(path).get_normalise_specs()
        self.assertTrue(original.is_default)
        self.assertTrue(translation.is_default)

    def test_a_malformed_side_gives_that_side_the_default(self):
        path = self._path()
        path.write_text(
            json.dumps(
                {
                    "normalise_scale": {
                        ORIGINAL_SIDE: {"font": "wide"},
                        TRANSLATION_SIDE: {"gap": 0.7},
                    }
                }
            )
        )
        original, translation = self._store(path).get_normalise_specs()
        self.assertTrue(original.is_default)
        self.assertEqual(translation.gap, 0.7)

    def test_an_out_of_range_stored_value_is_clamped(self):
        path = self._path()
        path.write_text(
            json.dumps({"normalise_scale": {ORIGINAL_SIDE: {"font": 40}}})
        )
        original, _ = self._store(path).get_normalise_specs()
        self.assertEqual(original.font, 2.0)

    def test_a_file_written_before_this_feature_still_loads(self):
        # No normalise_scale key: the anchors, scroll and normalise flag must
        # all survive and the specs come back default.
        path = self._path()
        path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "anchors": [{"original": "a1", "translation": "b1"}],
                    "normalise": {READER_SURFACE: False},
                }
            )
        )
        store = self._store(path)
        self.assertEqual(store.anchors, [("a1", "b1")])
        self.assertFalse(store.get_normalise(READER_SURFACE))
        self.assertTrue(store.get_normalise_specs()[0].is_default)

    def test_saving_specs_keeps_the_anchors(self):
        path = self._path()
        store = self._store(path)
        store.add("a1", "b1")
        store.set_normalise_specs(NormaliseSpec(font=0.9), NormaliseSpec())
        store.shutdown()
        self.assertEqual(self._store(path).anchors, [("a1", "b1")])
