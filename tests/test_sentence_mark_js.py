"""The sentence-marking script, executed in a real page.

A sentence is a range of text inside a paragraph, not an element, so it cannot
be marked by toggling a class the way the paragraph is. Wrapping the range in a
span is not an option either: real book markup puts inline elements inside
paragraphs, and surroundContents throws InvalidStateError when a range
partially selects one. The script therefore registers the range with the CSS
Custom Highlight API, which marks the text and leaves the document alone, so
the paragraph mark stays underneath it and the search's own text-run counting
sees nothing change.

These tests run the real script in a real page, because none of that can be
checked against a stub, and they check the colour actually reaches the screen
by counting pixels of it."""

import json
import os
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWebEngineCore import QWebEngineProfile

from PySide6.QtWidgets import QApplication

from split_translator.book_loader import BookDocument
from split_translator.book_view import _SENTENCE_BOUNDS_JS, BookView
from split_translator.sentence_sync import split

app = QApplication.instance() or QApplication([])

# Held for the module: an inline profile can be collected out from under its
# pages, and the callbacks then never fire (see web.py).
PROFILE = QWebEngineProfile()

#: The sentence colour as the style sets it, for counting pixels. Between the
#: paragraph's #fff3a8 and the find colour below, nearer the paragraph's.
MARK_COLOUR = QColor(255, 220, 138)  # SENTENCE_MARK_STYLE, #ffdc8a

#: The colour the engine paints a find match in. A highlight's background
#: paints over it and would hide the word that was searched for, so the
#: sentence is marked either side of the word rather than across it.
FIND_COLOUR = QColor(255, 150, 50)


def _doc():
    """Three sentences, the middle one running through an inline element, which
    is the case a wrapping span cannot handle."""
    return BookDocument(
        html=(
            "<p data-stid='b0'>First sentence here. "
            "The <i>middle</i> sentence runs on. Third sentence closes it.</p>"
            "<p data-stid='b1'>One sentence only.</p>"
        ),
        block_ids=["b0", "b1"],
        title="T",
    )


class SentenceMarkJsTests(unittest.TestCase):
    def setUp(self):
        self.view = BookView(_doc(), PROFILE)
        self.view.resize(600, 300)
        self.view.show()
        self._spin(lambda: self.view._loaded)
        self.assertTrue(self.view._loaded, "the page never loaded")

    def tearDown(self):
        self.view.release_rendered()
        self.view.deleteLater()

    def _spin(self, until, timeout_ms=8000):
        deadline = time.time() + timeout_ms / 1000
        while not until() and time.time() < deadline:
            loop = QEventLoop()
            QTimer.singleShot(20, loop.quit)
            loop.exec()

    def _run(self, js):
        box = []
        self.view.page().runJavaScript(js, box.append)
        self._spin(lambda: box)
        return box[0] if box else None

    def _marked(self):
        """What the page says is marked, read back from the highlight."""
        return self._run(
            "(function() {"
            " var h = CSS.highlights.get('st-search-sentence');"
            " if (!h) { return ''; }"
            " var out = []; h.forEach(function(r) { out.push(r.toString()); });"
            " return out.join('|');"
            "})();"
        )

    def _mark(self, block_id, index, count, word=None):
        self.view.mark_sentence(block_id, index, count, word)
        self._spin(lambda: True, timeout_ms=200)

    def test_it_marks_the_sentence_asked_for(self):
        self._mark("b0", 0, 3)
        self.assertEqual(self._marked(), "First sentence here.")

    def test_a_sentence_running_through_an_inline_element_is_marked_whole(self):
        # The case that rules out wrapping the range in a span.
        self._mark("b0", 1, 3)
        self.assertEqual(self._marked(), "The middle sentence runs on.")

    def test_the_last_sentence_reaches_the_end_of_the_paragraph(self):
        self._mark("b0", 2, 3)
        self.assertEqual(self._marked(), "Third sentence closes it.")

    def test_a_count_that_does_not_match_marks_nothing(self):
        # The page cut the paragraph into three; a mark worked out from nine
        # sentences is about some other text, so it is refused.
        self._mark("b0", 1, 9)
        self.assertEqual(self._marked(), "")

    def test_an_index_outside_the_paragraph_marks_nothing(self):
        self._mark("b0", 7, 3)
        self.assertEqual(self._marked(), "")

    def test_an_unknown_paragraph_marks_nothing(self):
        self._mark("nope", 0, 1)
        self.assertEqual(self._marked(), "")

    def test_marking_replaces_the_previous_mark(self):
        self._mark("b0", 0, 3)
        self._mark("b0", 2, 3)
        self.assertEqual(self._marked(), "Third sentence closes it.")

    def test_clearing_removes_it(self):
        self._mark("b0", 0, 3)
        self.view.clear_sentence_mark()
        self._spin(lambda: True, timeout_ms=200)
        self.assertEqual(self._marked(), "")

    def test_the_document_is_left_alone(self):
        before = self._run("document.body.innerHTML;")
        self._mark("b0", 1, 3)
        self.assertEqual(self._run("document.body.innerHTML;"), before)

    def test_the_paragraph_mark_stays_underneath(self):
        self.view.mark_search_blocks(["b0"])
        self._mark("b0", 1, 3)
        self.assertEqual(
            self._run(
                "document.querySelector('[data-stid=\"b0\"]')"
                ".classList.contains('st-search-block');"
            ),
            True,
        )
        self.assertEqual(self._marked(), "The middle sentence runs on.")

    def _pixels(self, colour):
        image = self.view.grab().toImage()
        wanted = (colour.red(), colour.green(), colour.blue())
        found = 0
        for y in range(0, image.height()):
            for x in range(0, image.width(), 2):
                pixel = image.pixelColor(x, y)
                if (pixel.red(), pixel.green(), pixel.blue()) == wanted:
                    found += 1
        return found

    def _mark_pixels(self):
        return self._pixels(MARK_COLOUR)

    def test_the_word_is_left_out_of_the_mark(self):
        # Two ranges, one each side of the word, so the engine's own colour on
        # it is not painted over.
        text = self._run("document.querySelector('[data-stid=\"b0\"]').textContent;")
        start = text.index("middle")
        self._mark("b0", 1, 3, (start, start + len("middle")))
        self.assertEqual(
            self._marked(), "The |" + " sentence runs on."
        )

    def test_a_word_outside_the_sentence_is_ignored(self):
        # A bad offset must not move the mark off the sentence it belongs to.
        self._mark("b0", 1, 3, (0, 5))
        self.assertEqual(self._marked(), "The middle sentence runs on.")

    def test_a_word_that_is_the_whole_sentence_leaves_it_to_the_engine(self):
        text = self._run("document.querySelector('[data-stid=\"b0\"]').textContent;")
        start = text.index("The middle")
        self._mark("b0", 1, 3, (start, start + len("The middle sentence runs on.")))
        self.assertEqual(self._marked(), "")

    def test_the_found_word_stays_visible_under_the_sentence_mark(self):
        # The reason the mark is cut in two. The engine paints the match itself
        # and a highlight's background goes over the top of it, hiding the very
        # word that was searched for; a gap leaves it showing.
        found = []
        self.view.find("middle", True, lambda a, c: found.append((a, c)))
        self._spin(lambda: found)
        self.assertEqual(found, [(1, 1)], "the find did not land")
        self._spin(lambda: self._pixels(FIND_COLOUR) > 0, timeout_ms=3000)
        word = self._pixels(FIND_COLOUR)
        self.assertGreater(word, 0, "the engine painted no find match")
        text = self._run("document.querySelector('[data-stid=\"b0\"]').textContent;")
        start = text.index("middle")
        self._mark("b0", 1, 3, (start, start + len("middle")))
        self._spin(lambda: self._mark_pixels() > 0, timeout_ms=3000)
        self.assertGreater(self._mark_pixels(), 0, "the sentence was not marked")
        self.assertEqual(self._pixels(FIND_COLOUR), word)

    def test_marking_across_the_word_would_hide_it(self):
        # The control for the test above: without the gap the word goes under
        # the mark completely, which is what made it invisible.
        found = []
        self.view.find("middle", True, lambda a, c: found.append((a, c)))
        self._spin(lambda: found)
        self._spin(lambda: self._pixels(FIND_COLOUR) > 0, timeout_ms=3000)
        self.assertGreater(self._pixels(FIND_COLOUR), 0)
        self._mark("b0", 1, 3)  # no word, so the whole sentence is painted
        self._spin(lambda: self._mark_pixels() > 0, timeout_ms=3000)
        self.assertEqual(self._pixels(FIND_COLOUR), 0)

    def test_the_colour_reaches_the_screen(self):
        # The style is injected on load and the highlight is painted by the
        # engine, neither of which the assertions above would notice.
        self.assertEqual(self._mark_pixels(), 0)
        self._mark("b0", 1, 3)
        self._spin(lambda: self._mark_pixels() > 0, timeout_ms=3000)
        self.assertGreater(self._mark_pixels(), 0)
        self.view.clear_sentence_mark()
        self._spin(lambda: self._mark_pixels() == 0, timeout_ms=3000)
        self.assertEqual(self._mark_pixels(), 0)


#: Texts whose cutting is easy to get wrong in one language and not the other.
TRICKY = [
    "One. Two. Three.",
    "No terminator at all",
    "It cost 3.50 in all. Then more.",
    "Mr. Smith left. He waited.",
    "Ends with a space after the stop. ",
    "  Leading space, then a stop. And another.",
    "Three dots... then a sentence. End.",
    "A question? An answer! A statement.",
    "Quoted: 'Why?' she asked. Then nothing.",
    "",
    ".",
    "Several   spaces   inside. Still one sentence.",
]


class RulesAgreeTests(unittest.TestCase):
    """The sentence rule is written twice: sentence_sync.split in Python, which
    chooses the sentence, and __stSentenceBounds in the page, which marks it.
    They have to cut the same text into the same sentences, or a mark would
    land on the wrong line. The count travels with every mark so a
    disagreement is caught rather than painted, but it should not happen in the
    first place, and this is what would notice if one of them drifted."""

    def test_the_page_cuts_as_python_does(self):
        document = BookDocument(
            html="".join(
                f"<p data-stid='b{i}'>{piece}</p>"
                for i, piece in enumerate(TRICKY)
            ),
            block_ids=[f"b{i}" for i in range(len(TRICKY))],
            title="T",
        )
        view = BookView(document, PROFILE)
        self.addCleanup(view.release_rendered)
        view.resize(600, 400)
        view.show()
        deadline = time.time() + 8
        while not view._loaded and time.time() < deadline:
            loop = QEventLoop()
            QTimer.singleShot(20, loop.quit)
            loop.exec()
        self.assertTrue(view._loaded, "the page never loaded")

        box = []
        view.page().runJavaScript(
            _SENTENCE_BOUNDS_JS.join(
                [
                    "(function() {",
                    """
    var out = {};
    var blocks = document.querySelectorAll('[data-stid]');
    for (var i = 0; i < blocks.length; i++) {
        var text = blocks[i].textContent;
        var bounds = __stSentenceBounds(text);
        var pieces = [];
        for (var k = 0; k < bounds.length; k++) {
            pieces.push(text.slice(bounds[k][0], bounds[k][1]));
        }
        out[blocks[i].getAttribute('data-stid')] = {
            text: text, pieces: pieces
        };
    }
    return JSON.stringify(out);
})();""",
                ]
            ),
            box.append,
        )
        deadline = time.time() + 8
        while not box and time.time() < deadline:
            loop = QEventLoop()
            QTimer.singleShot(20, loop.quit)
            loop.exec()
        self.assertTrue(box, "the page never answered")
        page = json.loads(box[0])

        for i, piece in enumerate(TRICKY):
            with self.subTest(text=piece):
                # Python is given the page's own text, so the two rules are
                # compared on the same characters.
                answer = page[f"b{i}"]
                self.assertEqual(answer["pieces"], split(answer["text"]))
        # The fixture has to exercise the rule, not just agree trivially.
        self.assertGreater(
            sum(len(page[f"b{i}"]["pieces"]) for i in range(len(TRICKY))),
            len(TRICKY),
            "no paragraph was cut into more than one sentence",
        )


if __name__ == "__main__":
    unittest.main()
