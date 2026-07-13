"""The match-locating JS, executed in a real page against nested book markup.

Search marks a block by counting term occurrences in document order until the
running count reaches Chromium's activeMatch. That only lines up with Chromium
if each match is counted exactly once. Real book markup nests block elements
(``<div class="chapter">`` around the paragraphs, ``<blockquote>`` around a
``<p>``, a ``<li>`` holding a ``<p>``), and ``assign_block_ids`` tags every block
element, nested or not. An ancestor's ``textContent`` already contains its
children's text, so a walk over every ``[data-stid]`` counts each nested match
twice: once in the paragraph and once in every wrapper above it. The count then
runs ahead of Chromium's, the target index is reached early, and the mark lands
on the wrapper, which starts higher up the page than the paragraph that matched.
That is the "highlights the previous paragraph" bug.

These tests run the real JS in a real page (the counting logic cannot be checked
against a stub) and pin that only leaf blocks are counted."""

import json
import os
import pathlib
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QTimer, QUrl
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication

from split_translator.book_loader import assign_block_ids
from split_translator.book_view import _MATCH_BLOCK_JS, _MATCH_SENTENCE_JS

app = QApplication.instance() or QApplication([])


class _Page:
    """A real web page holding book-shaped HTML, so the JS can be executed.

    The HTML is tagged by the loader's own ``assign_block_ids``, so the fixture
    nests exactly the way a loaded book does. It is loaded from a file URL rather
    than setHtml, like the app does (see book_render)."""

    def __init__(self, body: str):
        self._tmp = tempfile.TemporaryDirectory()
        self.html, self.ids = assign_block_ids(body)
        path = pathlib.Path(self._tmp.name) / "book.html"
        path.write_text(
            "<!DOCTYPE html><html><head><meta charset='utf-8'></head>"
            f"<body>{self.html}</body></html>",
            encoding="utf-8",
        )
        self.view = QWebEngineView()
        self._load(QUrl.fromLocalFile(str(path)))

    def _load(self, url: QUrl) -> None:
        loop = QEventLoop()
        self.view.loadFinished.connect(lambda ok: loop.quit())
        self.view.load(url)
        QTimer.singleShot(10000, loop.quit)
        loop.exec()

    def run_js(self, js: str):
        """Run JS in the page and return its result (runJavaScript is async)."""
        result = []
        loop = QEventLoop()

        def done(value):
            result.append(value)
            loop.quit()

        self.view.page().runJavaScript(js, done)
        QTimer.singleShot(10000, loop.quit)
        loop.exec()
        return result[0] if result else None

    def block_for_match(self, term: str, index: int) -> str:
        js = _MATCH_BLOCK_JS % {"term": json.dumps(term), "index": int(index)}
        return self.run_js(js) or ""

    def sentence_for_match(self, term: str, index: int) -> str:
        js = _MATCH_SENTENCE_JS % {"term": json.dumps(term), "index": int(index)}
        payload = self.run_js(js) or "{}"
        return json.loads(payload).get("sentence", "")

    def close(self) -> None:
        self.view.deleteLater()
        self._tmp.cleanup()


# A chapter div wrapping the paragraphs, which is how real EPUB markup is shaped.
# Both "shed" matches sit in the SAME paragraph, the case that surfaced the bug.
NESTED_BODY = """
<div class="chapter">
  <p>Nothing to find in the opening line.</p>
  <p>The shed was locked, so the shed stayed shut.</p>
  <p>They shed no tears at all.</p>
</div>
"""


class NestedBlockMatchTests(unittest.TestCase):
    """A match must be attributed to the paragraph holding it, never to a
    wrapper that merely contains that paragraph."""

    def setUp(self):
        self.page = _Page(NESTED_BODY)
        self.addCleanup(self.page.close)
        # b0 is the chapter div; b1..b3 are the paragraphs inside it.
        self.assertEqual(self.page.ids, ["b0", "b1", "b2", "b3"])

    def test_wrapper_div_is_never_marked(self):
        # The regression itself. Every match lives in a paragraph, so no match
        # may resolve to the containing div: that is the mark landing "one
        # paragraph up" from where the match really is.
        for index in (1, 2, 3):
            self.assertNotEqual(
                self.page.block_for_match("shed", index),
                "b0",
                f"match {index} was attributed to the wrapping div",
            )

    def test_each_match_maps_to_its_own_paragraph(self):
        # Matches 1 and 2 are both in b2 (two in one paragraph, the reported
        # case); match 3 is in b3.
        self.assertEqual(self.page.block_for_match("shed", 1), "b2")
        self.assertEqual(self.page.block_for_match("shed", 2), "b2")
        self.assertEqual(self.page.block_for_match("shed", 3), "b3")

    def test_index_past_the_last_match_marks_nothing(self):
        # Counting each match once means the total is 3. A 4th index must come
        # back empty rather than wrapping onto some block.
        self.assertEqual(self.page.block_for_match("shed", 4), "")

    def test_sentence_comes_from_the_paragraph_not_the_wrapper(self):
        # _MATCH_SENTENCE_JS counts occurrences the same way, so it drifts the
        # same way. Reading the wrapper's textContent would splice the
        # paragraphs together and the sentence would start in the wrong one.
        self.assertEqual(
            self.page.sentence_for_match("shed", 1),
            "The shed was locked, so the shed stayed shut.",
        )
        self.assertEqual(
            self.page.sentence_for_match("shed", 3),
            "They shed no tears at all.",
        )


DEEP_BODY = """
<div class="chapter">
  <p>Opening line with nothing.</p>
  <blockquote>
    <p>A quoted shed, nested two deep.</p>
  </blockquote>
  <ul>
    <li><p>A shed inside a list item.</p></li>
  </ul>
</div>
"""


class DeeplyNestedMatchTests(unittest.TestCase):
    """Blocks nest more than one level deep (blockquote > p, li > p). The
    innermost block owns the match; every wrapper above it must be skipped."""

    def setUp(self):
        self.page = _Page(DEEP_BODY)
        self.addCleanup(self.page.close)

    def test_innermost_block_owns_the_match(self):
        # Whatever the ids are, the marked block must be the one whose own text
        # is the paragraph, and it must hold no further tagged block.
        for index in (1, 2):
            block_id = self.page.block_for_match("shed", index)
            self.assertTrue(block_id, f"match {index} was not located")
            nested = self.page.run_js(
                "document.querySelector('[data-stid=' + "
                f"{json.dumps(json.dumps(block_id))}"
                " + ']').querySelectorAll('[data-stid]').length"
            )
            self.assertEqual(
                nested, 0, f"match {index} was attributed to a wrapper block"
            )

    def test_the_two_matches_are_in_different_blocks(self):
        # A drifting count collapses both onto the same ancestor.
        first = self.page.block_for_match("shed", 1)
        second = self.page.block_for_match("shed", 2)
        self.assertNotEqual(first, second)


FLAT_BODY = """
<p>She walked home alone.</p>
<p>The shed was locked, so the shed stayed shut.</p>
<p>They shed no tears.</p>
"""


class FlatBlockMatchTests(unittest.TestCase):
    """Un-nested markup already worked; it must keep working. This is what
    guards against "fixing" nesting by breaking the ordinary case."""

    def setUp(self):
        self.page = _Page(FLAT_BODY)
        self.addCleanup(self.page.close)

    def test_matches_map_to_their_paragraphs(self):
        self.assertEqual(self.page.block_for_match("shed", 1), "b1")
        self.assertEqual(self.page.block_for_match("shed", 2), "b1")
        self.assertEqual(self.page.block_for_match("shed", 3), "b2")

    def test_sentence_extraction_still_works(self):
        self.assertEqual(
            self.page.sentence_for_match("shed", 3), "They shed no tears."
        )


if __name__ == "__main__":
    unittest.main()
