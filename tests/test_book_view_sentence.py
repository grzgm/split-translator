import json
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from split_translator.book_view import _MATCH_SENTENCE_JS, BookView

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


class MarkSentenceTests(unittest.TestCase):
    """BookView.mark_sentence fills the marking script with the paragraph, the
    sentence and the count it was chosen from. The script itself needs a real
    page (see test_sentence_mark_js); here the Python contract is checked
    against a stub page."""

    def _view_with_stub_page(self):
        view = BookView.__new__(BookView)
        calls = []

        class StubPage:
            def runJavaScript(self, js, cb=None):
                calls.append(js)

        view.page = lambda: StubPage()
        return view, calls

    def test_the_paragraph_sentence_and_count_go_into_the_script(self):
        view, calls = self._view_with_stub_page()
        view.mark_sentence("b7", 3, 9)
        self.assertEqual(len(calls), 1)
        self.assertIn('"b7"', calls[0])
        self.assertIn('("b7", 3, 9, null)', calls[0])
        self.assertIn("st-search-sentence", calls[0])

    def test_clearing_sends_an_empty_paragraph(self):
        view, calls = self._view_with_stub_page()
        view.clear_sentence_mark()
        self.assertIn('("", -1, 0, null)', calls[0])

    def test_the_found_word_goes_in_so_the_mark_can_leave_it_out(self):
        view, calls = self._view_with_stub_page()
        view.mark_sentence("b7", 3, 9, (12, 18))
        self.assertIn('("b7", 3, 9, [12, 18])', calls[0])

    def test_a_missing_paragraph_clears_rather_than_marking(self):
        view, calls = self._view_with_stub_page()
        view.mark_sentence("", 2, 5)
        self.assertIn('("", 2, 5, null)', calls[0])


class MatchSentenceAtTests(unittest.TestCase):
    """The richer read: the sentence text, its place in the paragraph and how
    many sentences that paragraph holds. match_sentence is the same read with
    the place dropped."""

    def _view_with_stub_page(self, js_return):
        view = BookView.__new__(BookView)

        class StubPage:
            def runJavaScript(self, js, cb):
                cb(js_return)

        view.page = lambda: StubPage()
        return view

    def test_the_place_and_the_word_come_through(self):
        view = self._view_with_stub_page(
            json.dumps(
                {"sentence": "She saw it.", "index": 2, "count": 5, "word": [4, 7]}
            )
        )
        got = []
        view.match_sentence_at("saw", 1, lambda *args: got.append(args))
        self.assertEqual(got, [("She saw it.", 2, 5, (4, 7))])

    def test_no_match_reports_no_place(self):
        view = self._view_with_stub_page(
            json.dumps({"sentence": "", "index": -1, "count": 0, "word": None})
        )
        got = []
        view.match_sentence_at("zzz", 1, lambda *args: got.append(args))
        self.assertEqual(got, [("", -1, 0, None)])

    def test_an_empty_answer_reports_no_place(self):
        view = self._view_with_stub_page("")
        got = []
        view.match_sentence_at("zzz", 1, lambda *args: got.append(args))
        self.assertEqual(got, [("", -1, 0, None)])

    def test_a_malformed_word_is_dropped(self):
        view = self._view_with_stub_page(
            json.dumps(
                {"sentence": "She saw it.", "index": 2, "count": 5, "word": [4]}
            )
        )
        got = []
        view.match_sentence_at("saw", 1, lambda *args: got.append(args))
        self.assertEqual(got, [("She saw it.", 2, 5, None)])

    def test_match_sentence_still_hands_over_the_text_alone(self):
        view = self._view_with_stub_page(
            json.dumps(
                {"sentence": "She saw it.", "index": 2, "count": 5, "word": [4, 7]}
            )
        )
        got = []
        view.match_sentence("saw", 1, got.append)
        self.assertEqual(got, ["She saw it."])
