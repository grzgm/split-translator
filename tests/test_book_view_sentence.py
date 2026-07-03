import json
import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from split_translator.book_view import BookView, _MATCH_SENTENCE_JS

app = QApplication.instance() or QApplication([])


class MatchSentenceTests(unittest.TestCase):
    """BookView.match_sentence runs the extraction JS in the page and hands the
    result string to the callback. The JS itself needs a live book page and is
    verified manually; here the method is driven against a stub page so the
    Python contract (JSON substitution, callback receives a string, empty ->
    "") is checked without WebEngine."""

    def _view_with_stub_page(self, js_return):
        # Bypass BookView.__init__ (which loads a real page) and inject a stub
        # page whose runJavaScript immediately invokes the callback.
        view = BookView.__new__(BookView)
        captured = {}

        class StubPage:
            def runJavaScript(self, js, cb):
                captured["js"] = js
                cb(js_return)

        view.page = lambda: StubPage()
        return view, captured

    def test_passes_sentence_to_callback(self):
        # The real page returns JSON.stringify({sentence: ...}); stub that.
        view, captured = self._view_with_stub_page(
            json.dumps({"sentence": "She saw the dog run."})
        )
        got = []
        view.match_sentence("dog", 2, got.append)
        self.assertEqual(got, ["She saw the dog run."])
        # The term and index were substituted into the JS as JSON.
        self.assertIn('"dog"', captured["js"])
        self.assertIn("2", captured["js"])

    def test_malformed_payload_becomes_empty_string(self):
        # A non-JSON page result (should not happen in practice) fails soft to
        # "" rather than feeding garbage into the flashcard example.
        view, _ = self._view_with_stub_page("not json at all")
        got = []
        view.match_sentence("dog", 1, got.append)
        self.assertEqual(got, [""])

    def test_empty_result_becomes_empty_string(self):
        view, _ = self._view_with_stub_page(None)
        got = []
        view.match_sentence("dog", 1, got.append)
        self.assertEqual(got, [""])

    def test_extraction_js_is_ascii(self):
        self.assertTrue(_MATCH_SENTENCE_JS.isascii())


if __name__ == "__main__":
    unittest.main()
