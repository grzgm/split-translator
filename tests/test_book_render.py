import gc
import unittest

from split_translator.book_loader import BookDocument
from split_translator.book_render import (
    RenderedBook,
    document_html,
)


def _doc(body="<p data-stid='b0'>Body.</p>", images=None):
    return BookDocument(
        html=body, block_ids=["b0"], title="T", images=images or {}
    )


class DocumentHtmlTests(unittest.TestCase):
    def test_wraps_body_in_a_full_html_document(self):
        html = document_html(_doc("<p>hi</p>"))
        self.assertIn("<!DOCTYPE html>", html)
        self.assertIn('<meta charset="utf-8">', html)
        self.assertIn("<p>hi</p>", html)
        self.assertTrue(html.rstrip().endswith("</html>"))

    def test_preserves_block_ids_in_the_body(self):
        html = document_html(_doc("<p data-stid='b0'>x</p>"))
        self.assertIn("data-stid='b0'", html)


class RenderedBookTests(unittest.TestCase):
    def test_writes_a_temp_file_with_the_document_html(self):
        rendered = RenderedBook(_doc("<p>spice</p>"))
        self.addCleanup(rendered.release)
        self.assertTrue(rendered.path.exists())
        self.assertIn("<p>spice</p>", rendered.path.read_text(encoding="utf-8"))

    def test_url_is_a_file_url_to_the_temp_file(self):
        rendered = RenderedBook(_doc())
        self.addCleanup(rendered.release)
        url = rendered.url()
        self.assertTrue(url.isLocalFile())
        self.assertEqual(url.toLocalFile(), str(rendered.path))

    def test_release_deletes_the_file_and_is_idempotent(self):
        rendered = RenderedBook(_doc())
        path = rendered.path
        self.assertTrue(path.exists())
        rendered.release()
        self.assertFalse(path.exists())
        rendered.release()  # must not raise

    def test_handles_a_book_larger_than_the_sethtml_limit(self):
        # The whole point of file-backed rendering: a body well over setHtml's
        # ~2 MB data-URL cap is written and read back intact.
        big = "<p data-stid='b0'>word word word. </p>" * 80000
        rendered = RenderedBook(_doc(big))
        self.addCleanup(rendered.release)
        text = rendered.path.read_text(encoding="utf-8")
        self.assertGreater(len(text.encode("utf-8")), 2 * 1024 * 1024)
        self.assertIn("word word word.", text)

    def test_temp_file_removed_when_garbage_collected(self):
        rendered = RenderedBook(_doc())
        path = rendered.path
        self.assertTrue(path.exists())
        del rendered
        gc.collect()
        self.assertFalse(path.exists())

    def test_writes_images_beside_the_html_at_their_relative_paths(self):
        images = {
            "cover.jpeg": b"\xff\xd8\xff-cover",
            "OEBPS/Images/pic.png": b"\x89PNG-pic",
        }
        rendered = RenderedBook(_doc(images=images))
        self.addCleanup(rendered.release)
        root = rendered.path.parent
        self.assertEqual((root / "cover.jpeg").read_bytes(), b"\xff\xd8\xff-cover")
        self.assertEqual(
            (root / "OEBPS/Images/pic.png").read_bytes(), b"\x89PNG-pic"
        )

    def test_release_removes_images_and_subdirs_too(self):
        rendered = RenderedBook(
            _doc(images={"OEBPS/Images/pic.png": b"\x89PNG"})
        )
        root = rendered.path.parent
        self.assertTrue((root / "OEBPS/Images/pic.png").exists())
        rendered.release()
        self.assertFalse(root.exists())

    def test_image_path_escaping_the_temp_dir_is_skipped(self):
        # Defensive: a crafted ".." path must not write outside the temp dir.
        rendered = RenderedBook(
            _doc(images={"../escape.png": b"nope"})
        )
        self.addCleanup(rendered.release)
        escaped = rendered.path.parent.parent / "escape.png"
        self.assertFalse(escaped.exists())


if __name__ == "__main__":
    unittest.main()
