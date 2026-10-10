"""Finding in a book view that cannot answer yet.

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


if __name__ == "__main__":
    unittest.main()
