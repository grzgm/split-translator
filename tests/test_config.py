import json
import tempfile
import unittest
from pathlib import Path

from split_translator.config import load_config, save_layout
from split_translator.layout import LAYOUT_DEFAULT, LAYOUT_WIDE


class ConfigTests(unittest.TestCase):
    def _write(self, d, data):
        path = Path(d) / "config.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def test_loads_without_page_anchors(self):
        with tempfile.TemporaryDirectory() as d:
            path = self._write(
                d,
                {
                    "original_path": "/books/a.epub",
                    "translation_path": "/books/b.epub",
                },
            )
            config = load_config(path)
            self.assertEqual(config.original_path, "/books/a.epub")
            self.assertEqual(config.page_anchors, [])

    def test_still_reads_page_anchors_when_present(self):
        with tempfile.TemporaryDirectory() as d:
            path = self._write(
                d,
                {
                    "original_path": "/books/a.epub",
                    "translation_path": "/books/b.epub",
                    "page_anchors": [[0, 0], [10, 8]],
                },
            )
            config = load_config(path)
            self.assertEqual(config.page_anchors, [(0, 0), (10, 8)])

    def test_exposes_the_folder_it_was_loaded_from(self):
        # Every store reads its file from here, which is what makes one config
        # file per workspace enough to isolate a workspace's data.
        with tempfile.TemporaryDirectory() as d:
            path = self._write(
                d,
                {
                    "original_path": "/books/a.epub",
                    "translation_path": "/books/b.epub",
                },
            )
            self.assertEqual(load_config(path).dir, Path(d))

    def test_reads_the_workspace_name(self):
        with tempfile.TemporaryDirectory() as d:
            path = self._write(
                d,
                {
                    "name": "Pan Tadeusz",
                    "original_path": "/books/a.epub",
                    "translation_path": "/books/b.epub",
                },
            )
            self.assertEqual(load_config(path).name, "Pan Tadeusz")

    def test_falls_back_to_the_folder_name_when_unnamed(self):
        with tempfile.TemporaryDirectory() as d:
            path = self._write(
                d,
                {
                    "original_path": "/books/a.epub",
                    "translation_path": "/books/b.epub",
                },
            )
            self.assertEqual(load_config(path).name, Path(d).name)

    def test_layout_defaults_to_the_default_view(self):
        with tempfile.TemporaryDirectory() as d:
            path = self._write(
                d,
                {
                    "original_path": "/books/a.epub",
                    "translation_path": "/books/b.epub",
                },
            )
            self.assertEqual(load_config(path).layout, LAYOUT_DEFAULT)

    def test_reads_a_stored_layout(self):
        with tempfile.TemporaryDirectory() as d:
            path = self._write(
                d,
                {
                    "original_path": "/books/a.epub",
                    "translation_path": "/books/b.epub",
                    "layout": "wide",
                },
            )
            self.assertEqual(load_config(path).layout, LAYOUT_WIDE)

    def test_an_unreadable_layout_loads_as_the_default_view(self):
        # Hand-edited, or written by a newer version: the app opens in the view
        # it knows rather than failing, the way every other stored setting
        # loads.
        with tempfile.TemporaryDirectory() as d:
            path = self._write(
                d,
                {
                    "original_path": "/books/a.epub",
                    "translation_path": "/books/b.epub",
                    "layout": "sideways",
                },
            )
            self.assertEqual(load_config(path).layout, LAYOUT_DEFAULT)


class SaveLayoutTests(unittest.TestCase):
    def _write(self, d, data):
        path = Path(d) / "config.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def test_records_the_layout_without_touching_the_books(self):
        with tempfile.TemporaryDirectory() as d:
            self._write(
                d,
                {
                    "name": "Lalka",
                    "original_path": "/books/a.epub",
                    "translation_path": "/books/b.epub",
                },
            )
            save_layout(Path(d), LAYOUT_WIDE)
            raw = json.loads(
                (Path(d) / "config.json").read_text(encoding="utf-8")
            )
            self.assertEqual(raw["layout"], "wide")
            self.assertEqual(raw["name"], "Lalka")
            self.assertEqual(raw["original_path"], "/books/a.epub")

    def test_writes_nothing_when_there_is_no_config_to_update(self):
        with tempfile.TemporaryDirectory() as d:
            save_layout(Path(d), LAYOUT_WIDE)
            self.assertFalse((Path(d) / "config.json").exists())
