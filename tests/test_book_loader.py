import tempfile
import unittest

from split_translator.book_loader import BookDocument, assign_block_ids
from tests.fixtures.make_fixtures import make_epub, make_pdf


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
