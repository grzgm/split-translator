"""The headword read, executed in a real page against Cambridge markup.

The flashcard's Headword comes from the dictionary rather than the search box,
so the page has to be asked which entry it is showing. For a plain word that is
the title with the headword nested inside it:

    <div class="di-title">
      <span class="headword ... dhw"><span class="hw dhw">dog</span></span>

For a phrasal verb the title is an <h2> holding the whole phrase, and the only
span.hw.dhw on the page is the bare verb in the note beside it:

    <div class="di-title"><h2 class="headword ... dhw"><b>come off</b></h2></div>
    <span class="anc-info-head">phrasal verb with <span class="hw dhw">come</span></span>

Reading span.hw.dhw therefore headed a card for "came off" (which Cambridge
answers at its "come off" entry) with "come". The title is read instead, and a
trailing object placeholder is dropped, since the entry is titled "look after
someone/something" while the phrase is "look after".

The fixtures carry the class names and nesting the live pages were measured to
use. The JS cannot be checked without a page, so these run it in one."""

import json
import os
import pathlib
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QTimer, QUrl
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication

from split_translator.dictionary_panel import _BLOCK_PRON_JS, DictionaryPanel

app = QApplication.instance() or QApplication([])

GRAB_JS = DictionaryPanel._GRAB_JS.replace("__BLOCK_PRON_JS__", _BLOCK_PRON_JS)


def _plain_entry(word: str) -> str:
    """A one-word entry: dog, surmised, glasses."""
    return (
        "<div class='pr entry-body__el'><div class='pos-header dpos-h'>"
        "<div class='di-title'>"
        f"<span class='headword hdb tw-bw dhw dpos-h_hw '><span class='hw dhw'>{word}</span></span>"
        "</div></div></div>"
    )


def _phrasal_entry(title: str, verb: str) -> str:
    """A phrasal verb's entry: the title holds the phrase, and the only
    span.hw.dhw is the bare verb in the "phrasal verb with" note."""
    return (
        "<div class='pv-block'>"
        f"<div class='di-title'><h2 class='headword tw-bw dhw dpos-h_hw '><b>{title}</b></h2></div>"
        "<div class='pos-header dpos-h'><span class='di-info'>"
        "<span class='anc-info-head danc-info-head'>phrasal verb with "
        f"<span class='hw dhw'>{verb}</span></span>"
        "<span class='pos dpos'>verb</span>"
        "</span></div></div>"
    )


class _Page:
    """A real page holding entry-shaped HTML, loaded from a file URL."""

    def __init__(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.view = QWebEngineView()

    def _run(self, js: str):
        result = []
        loop = QEventLoop()
        self.view.page().runJavaScript(
            js, lambda value: (result.append(value), loop.quit())
        )
        QTimer.singleShot(10000, loop.quit)
        loop.exec()
        return result[0] if result else None

    def load(self, body: str) -> None:
        path = pathlib.Path(self._tmp.name) / "entry.html"
        path.write_text(
            "<!DOCTYPE html><html><head><meta charset='utf-8'></head>"
            f"<body>{body}</body></html>",
            encoding="utf-8",
        )
        loop = QEventLoop()
        self.view.loadFinished.connect(lambda ok: loop.quit())
        self.view.load(QUrl.fromLocalFile(str(path)))
        QTimer.singleShot(10000, loop.quit)
        loop.exec()

    def headword(self, body: str):
        self.load(body)
        payload = self._run(GRAB_JS)
        return json.loads(payload).get("headword") if payload else None

    def first_hw_dhw(self, body: str):
        """What the read used to return, so a fixture cannot pass by accident."""
        self.load(body)
        return self._run(
            "(function() { var e = document.querySelector('.hw.dhw');"
            " return e ? e.textContent.trim() : null; })();"
        )


class HeadwordJsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = _Page()

    def test_a_plain_word_is_its_own_title(self):
        self.assertEqual(self.page.headword(_plain_entry("dog")), "dog")

    def test_an_inflected_form_served_as_its_own_entry_is_kept(self):
        # "surmised" has an entry of its own; following it to "surmise" is the
        # base-form read's job, not this one's.
        self.assertEqual(self.page.headword(_plain_entry("surmised")), "surmised")

    def test_a_phrasal_verb_reads_the_whole_phrase(self):
        body = _phrasal_entry("come off", "come")
        self.assertEqual(self.page.headword(body), "come off")

    def test_the_phrasal_verb_fixture_would_have_read_the_bare_verb(self):
        # The control: the fixture reproduces the bug, so the test above is
        # pinning the fix and not the markup.
        body = _phrasal_entry("come off", "come")
        self.assertEqual(self.page.first_hw_dhw(body), "come")

    def test_a_trailing_object_placeholder_is_dropped(self):
        for title, expected in (
            ("look after someone/something", "look after"),
            ("put up with something/someone", "put up with"),
            ("count on someone", "count on"),
            ("look forward to something", "look forward to"),
            ("take care of sb/sth", "take care of"),
        ):
            with self.subTest(title=title):
                body = _phrasal_entry(title, title.split()[0])
                self.assertEqual(self.page.headword(body), expected)

    def test_a_placeholder_inside_the_phrase_is_left_alone(self):
        # Cambridge's own wording for where the object goes.
        body = _phrasal_entry("break something up", "break")
        self.assertEqual(self.page.headword(body), "break something up")

    def test_a_one_word_entry_is_never_stripped_away(self):
        # "something" is an entry in its own right, not a placeholder here.
        self.assertEqual(self.page.headword(_plain_entry("something")), "something")

    def test_a_page_with_no_title_falls_back_to_the_headword_span(self):
        body = "<div class='pr entry-body__el'><span class='hw dhw'>dog</span></div>"
        self.assertEqual(self.page.headword(body), "dog")

    def test_a_page_with_no_headword_at_all_reports_none(self):
        self.assertIsNone(self.page.headword("<p>nothing here</p>"))


if __name__ == "__main__":
    unittest.main()
