import tempfile
import unittest

from split_translator.book_loader import (
    BookDocument,
    _resolve_epub_ref,
    _rewrite_image_refs,
    assign_block_ids,
    load_book,
)
from tests.fixtures.make_fixtures import (
    make_epub,
    make_epub_with_images,
    make_pdf,
)


class AssignBlockIdsTests(unittest.TestCase):
    def test_assigns_sequential_ids_to_block_elements(self):
        html = "<h1>Title</h1><p>One</p><p>Two</p>"
        out, ids = assign_block_ids(html)
        self.assertEqual(ids, ["b0", "b1", "b2"])
        self.assertIn('data-stid="b0"', out)
        self.assertIn('data-stid="b1"', out)
        self.assertIn('data-stid="b2"', out)

    def test_ignores_inline_elements(self):
        html = "<p>Hello <span>world</span> <b>bold</b></p>"
        out, ids = assign_block_ids(html)
        # Only the <p> is a block; span and b are inline and get no marker.
        self.assertEqual(ids, ["b0"])

    def test_marks_blocks_that_already_have_an_id(self):
        # A real EPUB id must not stop us marking the block, and must not be
        # mistaken for one of our anchors.
        html = '<p id="ch1">Existing id here.</p><p>Plain.</p>'
        out, ids = assign_block_ids(html)
        self.assertEqual(ids, ["b0", "b1"])
        # The author id survives; our marker is added alongside it.
        self.assertIn('id="ch1"', out)
        self.assertIn('data-stid="b0"', out)

    def test_preserves_entities_verbatim(self):
        html = "<p>Tom &amp; Jerry &lt;3</p>"
        out, _ = assign_block_ids(html)
        self.assertIn("&amp;", out)
        self.assertIn("&lt;", out)

    def test_is_deterministic_across_two_runs(self):
        html = "<div>a</div><div>b</div>"
        out1, ids1 = assign_block_ids(html)
        out2, ids2 = assign_block_ids(html)
        self.assertEqual(out1, out2)
        self.assertEqual(ids1, ids2)

    def test_document_is_a_dataclass_with_expected_fields(self):
        doc = BookDocument(
            html='<p data-stid="b0">x</p>', block_ids=["b0"], title="T"
        )
        self.assertEqual(doc.html, '<p data-stid="b0">x</p>')
        self.assertEqual(doc.block_ids, ["b0"])
        self.assertEqual(doc.title, "T")


class FixtureBuilderTests(unittest.TestCase):
    def test_make_epub_creates_a_readable_zip(self):
        import zipfile

        with tempfile.TemporaryDirectory() as d:
            path = make_epub(d)
            self.assertTrue(zipfile.is_zipfile(path))

    def test_make_pdf_creates_a_pdf(self):
        import pymupdf

        with tempfile.TemporaryDirectory() as d:
            path = make_pdf(d)
            doc = pymupdf.open(path)
            self.assertEqual(doc.page_count, 1)
            doc.close()


class EpubLoadTests(unittest.TestCase):
    def test_loads_both_chapters_in_spine_order(self):
        with tempfile.TemporaryDirectory() as d:
            path = make_epub(d)
            doc = load_book(path)
            # Both chapter bodies are present, chapter one before chapter two.
            self.assertIn("Chapter One", doc.html)
            self.assertIn("Chapter Two", doc.html)
            self.assertLess(
                doc.html.index("Chapter One"), doc.html.index("Chapter Two")
            )

    def test_blocks_get_sequential_ids(self):
        with tempfile.TemporaryDirectory() as d:
            doc = load_book(make_epub(d))
            # 2 h1 + 2 p = 4 block ids, in order.
            self.assertEqual(doc.block_ids, ["b0", "b1", "b2", "b3"])

    def test_title_comes_from_opf(self):
        with tempfile.TemporaryDirectory() as d:
            doc = load_book(make_epub(d))
            self.assertEqual(doc.title, "Test Book")


class ResolveEpubRefTests(unittest.TestCase):
    def test_resolves_relative_ref_against_chapter_dir(self):
        self.assertEqual(
            _resolve_epub_ref("OEBPS/Text", "../Images/x.png"),
            "OEBPS/Images/x.png",
        )

    def test_resolves_plain_ref_at_root(self):
        self.assertEqual(_resolve_epub_ref(".", "cover.jpeg"), "cover.jpeg")

    def test_leaves_absolute_and_special_refs_alone(self):
        for ref in (
            "https://example.com/x.png",
            "http://example.com/x.png",
            "data:image/png;base64,AAAA",
            "#anchor",
            "/abs/x.png",
            "",
        ):
            self.assertIsNone(_resolve_epub_ref("OEBPS/Text", ref))


class RewriteImageRefsTests(unittest.TestCase):
    def test_rewrites_known_image_and_collects_it(self):
        body = '<img src="../Images/pic.png"/>'
        available = {"OEBPS/Images/pic.png"}
        out, used = _rewrite_image_refs(body, "OEBPS/Text", available)
        self.assertIn('src="OEBPS/Images/pic.png"', out)
        self.assertEqual(used, {"OEBPS/Images/pic.png"})

    def test_leaves_missing_image_ref_untouched(self):
        body = '<img src="../Images/gone.png"/>'
        out, used = _rewrite_image_refs(body, "OEBPS/Text", set())
        self.assertEqual(out, body)
        self.assertEqual(used, set())

    def test_ignores_non_image_and_remote_refs(self):
        body = (
            '<link href="../style.css"/>'
            '<img src="https://example.com/r.png"/>'
        )
        available = {"OEBPS/style.css"}
        out, used = _rewrite_image_refs(body, "OEBPS/Text", available)
        self.assertEqual(out, body)  # nothing rewritten
        self.assertEqual(used, set())

    def test_rewrites_svg_xlink_href_cover(self):
        body = '<image xlink:href="cover.jpeg"/>'
        out, used = _rewrite_image_refs(body, ".", {"cover.jpeg"})
        self.assertIn('xlink:href="cover.jpeg"', out)
        self.assertEqual(used, {"cover.jpeg"})


class EpubImageTests(unittest.TestCase):
    def test_collects_referenced_images_with_root_relative_keys(self):
        with tempfile.TemporaryDirectory() as d:
            doc = load_book(make_epub_with_images(d))
            self.assertEqual(
                set(doc.images),
                {"OEBPS/Images/pic.png", "OEBPS/Images/cover.png"},
            )
            for data in doc.images.values():
                self.assertTrue(data.startswith(b"\x89PNG"))

    def test_html_references_rewritten_root_relative_paths(self):
        with tempfile.TemporaryDirectory() as d:
            doc = load_book(make_epub_with_images(d))
            self.assertIn('src="OEBPS/Images/pic.png"', doc.html)
            self.assertIn('src="OEBPS/Images/cover.png"', doc.html)
            # The chapter-relative form of the real images is gone (only the
            # missing image, which is not rewritten, still uses ../Images).
            self.assertNotIn('src="../Images/pic.png"', doc.html)
            self.assertNotIn('src="../Images/cover.png"', doc.html)

    def test_missing_and_remote_refs_are_not_collected_or_rewritten(self):
        with tempfile.TemporaryDirectory() as d:
            doc = load_book(make_epub_with_images(d))
            self.assertNotIn("missing.png", "".join(doc.images))
            # The missing local image keeps its original ref; the remote URL too.
            self.assertIn('src="../Images/missing.png"', doc.html)
            self.assertIn("https://example.com/remote.png", doc.html)

    def test_image_less_epub_has_empty_images(self):
        with tempfile.TemporaryDirectory() as d:
            doc = load_book(make_epub(d))
            self.assertEqual(doc.images, {})


class PdfLoadTests(unittest.TestCase):
    def test_loads_pdf_text_as_html_blocks(self):
        with tempfile.TemporaryDirectory() as d:
            doc = load_book(make_pdf(d))
            self.assertIn("Chapter One", doc.html)
            self.assertIn("The first paragraph.", doc.html)
            self.assertTrue(doc.block_ids)  # at least one block id assigned

    def test_pdf_has_no_external_images(self):
        with tempfile.TemporaryDirectory() as d:
            doc = load_book(make_pdf(d))
            self.assertEqual(doc.images, {})

    def test_ids_are_stable_across_two_loads(self):
        with tempfile.TemporaryDirectory() as d:
            path = make_pdf(d)
            first = load_book(path)
            second = load_book(path)
            self.assertEqual(first.block_ids, second.block_ids)
            self.assertEqual(first.html, second.html)


class UnsupportedFormatTests(unittest.TestCase):
    def test_unknown_extension_raises_valueerror(self):
        with self.assertRaises(ValueError):
            load_book("/tmp/whatever.txt")
