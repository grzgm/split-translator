"""The plural-only rule, executed in a real page against Cambridge markup.

The notice is for a word that has no singular: scissors, trousers, police. The
page marks that beside the headword's part of speech (``.posgram``) or in the
entry's heading (``.di-info``). The same ``[ plural ]`` block also appears
lower down against a single sense (``.def-info``) or a phrase
(``.phrase-info``), where it describes that sense or phrase and not the word,
and reading every block on the page called such words plural: "lee" is a
singular noun whose entry runs on to the phrase "the lees".

The fixtures carry the class names and nesting the live pages were measured to
use, so the selector is pinned against the markup it has to read, not against
a guess at it. The JS cannot be checked without a page, so these run it in
one."""

import json
import os
import pathlib
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QTimer, QUrl
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication

from split_translator.dictionary_panel import DictionaryPanel

app = QApplication.instance() or QApplication([])


def _header(headword: str, grammar: str = "") -> str:
    """An entry heading: the headword, its part of speech, and the grammar
    block beside that part of speech, as scissors and police carry it."""
    return (
        "<div class='pos-header dpos-h'>"
        f"<div class='di-title'><span class='hw dhw'>{headword}</span></div>"
        "<span class='posgram dpos-g hdib lmr-5'>"
        "<span class='pos dpos'>noun</span>"
        f"{grammar}"
        "</span>"
        "</div>"
    )


def _gram(text: str) -> str:
    return f"<span class='gram dgram'>[ {text} ]</span>"


# scissors, trousers, jeans, police, people, clothes, outskirts, premises, lees.
PLURAL_AT_THE_PART_OF_SPEECH = _header("scissors", _gram("plural"))

# glasses and stairs: the block sits in the heading beside the headword rather
# than inside the part-of-speech span.
PLURAL_IN_THE_HEADING = (
    "<div class='pos-header dpos-h'>"
    "<div class='di-info'>"
    "<span class='hw dhw'>glasses</span>"
    f"{_gram('plural')}"
    "</div>"
    "</div>"
)

# data: a softer note that mentions the plural without being one.
SOFTER_NOTE = _header("data", _gram("U or plural"))

# lee: a singular noun, marked [ S ] on its one sense, whose entry carries the
# phrase "the lees", marked [ plural ]. glass and means are the same shape.
PLURAL_ON_A_SENSE_AND_A_PHRASE = (
    _header("lee")
    + "<div class='def-block ddef_block'><div class='ddef_h'>"
    f"<div class='def-info ddef-info'>{_gram('S')}</div>"
    "</div></div>"
    "<div class='phrase-block dphrase-block'>"
    f"<span class='phrase-info dphrase-info'>{_gram('plural')}</span>"
    "</div>"
)

NO_GRAMMAR_AT_ALL = _header("dog")


class _Page:
    """A real page holding entry-shaped HTML, loaded from a file URL."""

    def __init__(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.view = QWebEngineView()

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

    def is_plural(self, body: str) -> bool:
        self.load(body)
        result = []
        loop = QEventLoop()
        self.view.page().runJavaScript(
            DictionaryPanel._GRAMMAR_JS, lambda value: (result.append(value), loop.quit())
        )
        QTimer.singleShot(10000, loop.quit)
        loop.exec()
        return bool(json.loads(result[0]).get("plural"))


class GrammarJsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = _Page()

    def test_a_plural_only_word_is_read_from_its_part_of_speech(self):
        self.assertTrue(self.page.is_plural(PLURAL_AT_THE_PART_OF_SPEECH))

    def test_a_plural_only_word_is_read_from_the_entry_heading(self):
        self.assertTrue(self.page.is_plural(PLURAL_IN_THE_HEADING))

    def test_a_softer_note_mentioning_the_plural_is_not_one(self):
        self.assertFalse(self.page.is_plural(SOFTER_NOTE))

    def test_a_sense_and_a_phrase_marked_plural_leave_the_word_singular(self):
        self.assertFalse(self.page.is_plural(PLURAL_ON_A_SENSE_AND_A_PHRASE))

    def test_an_entry_with_no_grammar_block_is_not_plural(self):
        self.assertFalse(self.page.is_plural(NO_GRAMMAR_AT_ALL))


if __name__ == "__main__":
    unittest.main()
