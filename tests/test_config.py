import json
import tempfile
import unittest
from pathlib import Path

from split_translator.config import load_config


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
