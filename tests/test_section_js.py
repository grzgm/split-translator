"""The section scripts, executed in a real page with known geometry.

A section position is measured by rendered height, so it cannot be checked
against a stub: the page lays out paragraphs of fixed height and the scripts
run against it. The body has no margin, a 200px spacer before the first
paragraph and four paragraphs of 300px, so the document is 1400px tall. The
view is 600px tall, so the viewport centre is scrollY + 300."""

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
from split_translator.book_view import (
    _MARK_BLOCKS_JS,
    _SCROLL_STATE_JS,
    _SCROLL_TO_SECTION_JS,
    _SET_SECTIONS_JS,
)

app = QApplication.instance() or QApplication([])

_BODY = (
    "<div style='height:200px'></div>"
    + "".join(
        f"<p style='height:300px;margin:0'>Paragraph {n}</p>" for n in range(1, 5)
    )
)


class _Page:
    def __init__(self):
        self._tmp = tempfile.TemporaryDirectory()
        html, self.ids, _texts = assign_block_ids(_BODY)
        path = pathlib.Path(self._tmp.name) / "book.html"
        path.write_text(
            "<!DOCTYPE html><html><head><meta charset='utf-8'>"
            "<style>html, body { margin: 0; padding: 0; }</style></head>"
            f"<body>{html}</body></html>",
            encoding="utf-8",
        )
        self.view = QWebEngineView()
        self.view.resize(800, 600)
        self.view.show()
        loop = QEventLoop()
        self.view.loadFinished.connect(lambda ok: loop.quit())
        self.view.load(QUrl.fromLocalFile(str(path)))
        QTimer.singleShot(10000, loop.quit)
        loop.exec()

    def run_js(self, js: str):
        result = []
        loop = QEventLoop()

        def done(value):
            result.append(value)
            loop.quit()

        self.view.page().runJavaScript(js, done)
        QTimer.singleShot(10000, loop.quit)
        loop.exec()
        return result[0] if result else None

    def set_sections(self, starts):
        self.run_js(_SET_SECTIONS_JS % {"starts": json.dumps(starts)})

    def state(self):
        return json.loads(self.run_js(_SCROLL_STATE_JS))

    def close(self):
        self.view.close()
        self._tmp.cleanup()


class SectionScriptTests(unittest.TestCase):
    def setUp(self):
        self.page = _Page()
        self.addCleanup(self.page.close)

    def test_the_fixture_numbers_paragraphs_after_the_spacer(self):
        self.assertEqual(self.page.ids, ["b1", "b2", "b3", "b4"])

    def test_no_sections_reports_section_minus_one(self):
        state = self.page.state()
        self.assertEqual(state["section"], -1)
        self.assertEqual(state["id"], "b1")

    def test_the_centre_is_reported_as_a_section_and_a_share_of_its_height(self):
        # Sections: 0 is 0 to 200, 1 is 200 to 800, 2 is 800 to 1400, 3 is empty.
        self.page.set_sections(["top", "b1", "b3", "end"])
        self.page.run_js("window.scrollTo(0, 0);")
        state = self.page.state()
        self.assertEqual(state["section"], 1)
        self.assertAlmostEqual(state["share"], 100 / 600, places=3)

    def test_scrolling_to_a_section_puts_that_point_at_the_centre(self):
        self.page.set_sections(["top", "b1", "b3", "end"])
        self.page.run_js(_SCROLL_TO_SECTION_JS % {"section": 2, "share": 0.5})
        self.assertEqual(self.page.run_js("window.scrollY"), 800)
        state = self.page.state()
        self.assertEqual(state["section"], 2)
        self.assertAlmostEqual(state["share"], 0.5, places=3)

    def test_a_zero_height_section_is_passed_over(self):
        # Sections 1 and 2 both start at b1, so section 1 has no height.
        self.page.set_sections(["top", "b1", "b1", "b3", "end"])
        self.page.run_js("window.scrollTo(0, 0);")
        self.assertEqual(self.page.state()["section"], 2)

    def test_scrolling_to_a_missing_section_does_nothing(self):
        self.page.set_sections(["top", "b1", "end"])
        self.page.run_js("window.scrollTo(0, 400);")
        self.page.run_js(_SCROLL_TO_SECTION_JS % {"section": 9, "share": 0.5})
        self.assertEqual(self.page.run_js("window.scrollY"), 400)

    def test_marking_several_paragraphs_replaces_the_previous_mark(self):
        count = "document.querySelectorAll('.st-search-block').length"
        self.page.run_js(_MARK_BLOCKS_JS % {"ids": json.dumps(["b2", "b3"])})
        self.assertEqual(self.page.run_js(count), 2)
        self.page.run_js(_MARK_BLOCKS_JS % {"ids": json.dumps(["b4"])})
        self.assertEqual(self.page.run_js(count), 1)
        self.page.run_js(_MARK_BLOCKS_JS % {"ids": "[]"})
        self.assertEqual(self.page.run_js(count), 0)
