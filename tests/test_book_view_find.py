"""Finding in a book view: where a search starts, and what happens when the
page cannot answer one yet.

Chromium starts a new search at the selection and pays no attention to where
the page is scrolled, so one search carries on from the one before it. Nothing
in that is tied to the reader, so over a session of lookups it drifts ahead of
them and a word is found pages into a part of the book they have not read. A
new term is therefore searched from the paragraph on screen, while Prev and
Next still step on from the current match.

findText fails two ways and says so neither time. Sent before the document has
loaded it never calls back at all, so the match counter and the paragraph marks
keep standing at the search before it. Sent to a view that is off screen it
reports 0 matches however many the page holds, so the word reads as missing
from the book. Both looked in the reader like a search that reached the
dictionaries and not the books, and both cleared on searching the same word
again, which is the only thing the second search did differently.

These tests run the real findText against a real page, because a stub cannot
show either failure. The control is the find on a loaded, visible view: it has
to report the matches, or the other tests prove nothing (findText reports 0
matches in conditions of its own that have nothing to do with the view)."""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWebEngineCore import QWebEngineProfile
from PySide6.QtWidgets import QApplication

from split_translator.book_loader import BookDocument
from split_translator.book_view import BookView

app = QApplication.instance() or QApplication([])

# One profile for the module, held in a global: an inline QWebEngineProfile()
# can be garbage-collected out from under its pages, and the callbacks then
# never fire (see the profile notes in web.py).
PROFILE = QWebEngineProfile()

TERM = "needle"


def _doc():
    """Two paragraphs holding the term, so a find has something to count."""
    return BookDocument(
        html=(
            "<p data-stid='b0'>A needle in the first paragraph.</p>"
            "<p data-stid='b1'>Another needle, in the second.</p>"
        ),
        block_ids=["b0", "b1"],
        title="T",
    )


#: Paragraph count of the tall fixture, and the two paragraphs holding the term.
TALL_BLOCKS = 80
EARLY = 5
LATE = 60
#: Where the reader is: between the two, so the two possible starting points
#: (the top of the book and the paragraph on screen) give different matches.
READING_AT = 40


def _tall_doc():
    """A page long enough to scroll, with the term early and late in it."""
    paragraphs = []
    ids = []
    for i in range(TALL_BLOCKS):
        bid = f"b{i}"
        ids.append(bid)
        word = TERM if i in (EARLY, LATE) else "hay"
        paragraphs.append(
            f"<p data-stid='{bid}'>Paragraph {i} holds some {word} "
            "and enough words after it to take up a line or two of the "
            "page, so that scrolling has somewhere to go.</p>"
        )
    return BookDocument(html="".join(paragraphs), block_ids=ids, title="T")


def _spin(until, timeout_ms: int = 10000) -> None:
    """Run the event loop until until() is true, or the timeout runs out."""
    loop = QEventLoop()
    timer = QTimer()
    timer.setInterval(20)
    timer.timeout.connect(lambda: until() and loop.quit())
    timer.start()
    QTimer.singleShot(timeout_ms, loop.quit)
    loop.exec()
    timer.stop()


class HeldFindTests(unittest.TestCase):
    def setUp(self):
        self.view = BookView(_doc(), PROFILE)
        self.view.resize(600, 400)
        self.answers = []

    def tearDown(self):
        self.view.release_rendered()
        self.view.deleteLater()

    def _find(self):
        self.view.find(TERM, True, lambda a, c: self.answers.append((a, c)))

    def _wait_for_load(self):
        _spin(lambda: self.view._loaded)
        self.assertTrue(self.view._loaded, "the page never loaded")

    def test_a_loaded_visible_view_answers_the_find(self):
        # The control. Without this, a 0 from the tests below says nothing.
        self.view.show()
        self._wait_for_load()
        self._find()
        _spin(lambda: self.answers)
        self.assertEqual(self.answers, [(1, 2)])

    def test_a_find_before_the_page_loads_is_answered_once_it_has(self):
        self.view.show()
        self._find()
        self.assertEqual(self.answers, [])  # held, not sent
        self.assertIsNotNone(self.view._pending_find)
        _spin(lambda: self.answers)
        self.assertEqual(self.answers, [(1, 2)])

    def test_a_find_on_a_view_off_screen_waits_until_it_is_shown(self):
        self._wait_for_load()
        self._find()
        _spin(lambda: self.answers, timeout_ms=300)
        self.assertEqual(self.answers, [])  # a sent find would report (0, 0)
        self.view.show()
        _spin(lambda: self.answers)
        self.assertEqual(self.answers, [(1, 2)])

    def test_a_failed_load_does_not_make_the_view_searchable(self):
        # A load that failed leaves a blank page, so a held find waits for a
        # load that works rather than being spent on nothing.
        self.view.show()
        self._find()
        self.view._note_loaded(False)
        self.assertFalse(self.view._loaded)
        self.assertIsNotNone(self.view._pending_find)
        _spin(lambda: self.answers)
        self.assertEqual(self.answers, [(1, 2)])

    def test_only_the_newest_held_find_is_sent(self):
        # By the time the page can answer, an older term has left the search
        # box, so answering it would mark a paragraph for a word nobody is
        # looking at.
        self.view.show()
        self.view.find("first", True, lambda a, c: self.answers.append(("first", a, c)))
        self.view.find(TERM, True, lambda a, c: self.answers.append((TERM, a, c)))
        _spin(lambda: self.answers)
        self.assertEqual(self.answers, [(TERM, 1, 2)])

    def test_clearing_the_mark_drops_a_held_find(self):
        # Clearing the search (a blank term in the panel) clears the marks in
        # both editions. A find held from before must not land afterwards and
        # mark a paragraph for the term that was just cleared.
        self.view.show()
        self._find()
        self.assertIsNotNone(self.view._pending_find)
        self.view.clear_search_mark()
        self.assertIsNone(self.view._pending_find)
        _spin(lambda: self.answers, timeout_ms=400)
        self.assertEqual(self.answers, [])


class SearchStartsAtTheReaderTests(unittest.TestCase):
    """Where a new term's search begins, measured on a page that scrolls."""

    def setUp(self):
        self.view = BookView(_tall_doc(), PROFILE)
        self.view.resize(600, 400)
        self.view.show()
        self.answers = []
        _spin(lambda: self.view._loaded)
        self.assertTrue(self.view._loaded, "the page never loaded")

    def tearDown(self):
        self.view.release_rendered()
        self.view.deleteLater()

    def _read_at(self, index: int) -> None:
        """Put the reader at a paragraph and let the scroll land."""
        self.view.scroll_to(f"b{index}", 0.0)
        _spin(lambda: False, timeout_ms=400)

    def _answer(self):
        _spin(lambda: self.answers)
        self.assertTrue(self.answers, "the find never answered")
        return self.answers[-1]

    def _paragraph_of(self, active: int) -> str:
        box = []
        self.view.matched_block_id(TERM, active, box.append)
        _spin(lambda: box)
        return box[0] if box else ""

    def test_a_new_search_starts_at_the_paragraph_on_screen(self):
        self._read_at(READING_AT)
        self.view.find_from_reading_position(
            TERM, lambda a, c: self.answers.append((a, c))
        )
        active, count = self._answer()
        self.assertEqual(count, 2)
        self.assertEqual(active, 2)  # the one after the reader, not the first
        self.assertEqual(self._paragraph_of(active), f"b{LATE}")

    def test_the_plain_find_is_the_one_that_ignores_the_reader(self):
        # The control, and what the reader used to get: with no find session of
        # its own to carry on from, a plain find starts at the top of the book
        # however far in the reader is. The same carrying-on lands on the
        # previous search's match once there has been one, which is the drift
        # this fixes.
        self._read_at(READING_AT)
        self.view.find(TERM, True, lambda a, c: self.answers.append((a, c)))
        active, _count = self._answer()
        self.assertEqual(active, 1)
        self.assertEqual(self._paragraph_of(active), f"b{EARLY}")

    def test_a_second_new_search_starts_at_the_reader_again(self):
        # Two lookups in a row: the second does not carry on from the first,
        # which is what made searches walk away from the reader.
        self._read_at(READING_AT)
        self.view.find_from_reading_position(
            TERM, lambda a, c: self.answers.append(("first", a, c))
        )
        self._answer()
        self.view.find_from_reading_position(
            TERM, lambda a, c: self.answers.append(("second", a, c))
        )
        _spin(lambda: len(self.answers) > 1)
        self.assertEqual(self.answers[-1], ("second", 2, 2))

    def test_a_search_with_nothing_left_ahead_wraps_to_the_top(self):
        # Reading past the last match, so there is none forward: the search
        # wraps rather than reporting the word missing from the book.
        self._read_at(TALL_BLOCKS - 2)
        self.view.find_from_reading_position(
            TERM, lambda a, c: self.answers.append((a, c))
        )
        active, count = self._answer()
        self.assertEqual(count, 2)
        self.assertEqual(active, 1)
        self.assertEqual(self._paragraph_of(active), f"b{EARLY}")

    def test_a_new_search_is_held_until_the_page_can_answer_it(self):
        # The holding in HeldFindTests applies to this entry point too: a word
        # typed before the books have rendered still reaches them.
        view = BookView(_tall_doc(), PROFILE)
        self.addCleanup(view.release_rendered)
        view.resize(600, 400)
        view.show()
        answers = []
        view.find_from_reading_position(TERM, lambda a, c: answers.append((a, c)))
        self.assertEqual(answers, [])
        self.assertIsNotNone(view._pending_find)
        _spin(lambda: answers)
        self.assertEqual(answers, [(1, 2)])


if __name__ == "__main__":
    unittest.main()
