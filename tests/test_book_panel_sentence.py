import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QFrame

from split_translator.book_panel import BookPanel

app = QApplication.instance() or QApplication([])


class BookSentenceEmitTests(unittest.TestCase):
    """BookPanel emits book_sentence_matched from its find landing point. Search
    always runs on the Original edition, so the sentence is read from the
    Original view whichever tab is active; only a zero-match result emits nothing
    (the "Original only, no fuzzing" rule). Driven against a stubbed panel so no
    WebEngine page is built."""

    def _panel(self, active_is_original, sentence="A sentence."):
        panel = BookPanel.__new__(BookPanel)
        # BookPanel.__init__ is skipped (it builds real WebEngine views), but the
        # QFrame base still needs its C++ side constructed, otherwise the
        # inherited Signal is bound to an invalid QObject and .connect() below
        # raises "Signal source has been deleted".
        QFrame.__init__(panel)
        panel.search_term = "dog"
        panel.match_count = 0
        panel.current_match = 0

        # Stub the two views. Only the Original view is ever read for the
        # sentence; give the Translation view a match_sentence that fails the
        # test if it is ever consulted.
        def make_view():
            v = SimpleNamespace()
            v.match_sentence = lambda term, index, cb: cb(sentence)
            return v

        panel.original_view = make_view()
        panel.translation_view = make_view()
        panel.translation_view.match_sentence = lambda *a: self.fail(
            "Translation view must never be read for the sentence"
        )
        panel._active = (
            panel.original_view if active_is_original else panel.translation_view
        )
        panel.current_view = lambda: panel._active

        # Neutralise UI/highlight side effects of _on_find_result.
        panel.prev_button = SimpleNamespace(setEnabled=lambda *_: None)
        panel.next_button = SimpleNamespace(setEnabled=lambda *_: None)
        panel.update_match_label = lambda: None
        panel._mark_current_match = lambda *_: None

        emitted = []
        panel.book_sentence_matched.connect(emitted.append)
        return panel, emitted

    def test_emits_sentence_on_original_match(self):
        panel, emitted = self._panel(active_is_original=True, sentence="She saw the dog run.")
        panel._on_find_result(2, 5)
        self.assertEqual(emitted, ["She saw the dog run."])

    def test_emits_from_original_even_while_translation_tab_shows(self):
        # The user may flip to the Translation tab to read after searching. The
        # match is still an Original one, so the sentence is emitted from the
        # Original view, not suppressed and not read from Translation.
        panel, emitted = self._panel(
            active_is_original=False, sentence="She saw the dog run."
        )
        panel._on_find_result(2, 5)
        self.assertEqual(emitted, ["She saw the dog run."])

    def test_no_emit_on_zero_matches(self):
        panel, emitted = self._panel(active_is_original=True)
        panel._on_find_result(0, 0)
        self.assertEqual(emitted, [])


class CurrentMatchSentenceTests(unittest.TestCase):
    """BookPanel.current_match_sentence extracts the sentence for the CURRENT
    match on demand (for the Ctrl+T translation prompt). Search always runs on
    the Original edition, so it reads the Original view whichever tab is active
    and calls back with "" only when there is no current match. Driven against a
    stubbed panel so no WebEngine page is built."""

    def _panel(self, active_is_original, current_match, sentence="A sentence."):
        panel = BookPanel.__new__(BookPanel)
        QFrame.__init__(panel)
        panel.search_term = "dog"
        panel.current_match = current_match

        def make_view():
            v = SimpleNamespace()
            v.match_sentence = lambda term, index, cb: cb(sentence)
            return v

        panel.original_view = make_view()
        panel.translation_view = make_view()
        panel.translation_view.match_sentence = lambda *a: self.fail(
            "Translation view must never be read for the sentence"
        )
        panel._active = (
            panel.original_view if active_is_original else panel.translation_view
        )
        panel.current_view = lambda: panel._active
        return panel

    def test_yields_sentence_on_original_match(self):
        panel = self._panel(
            active_is_original=True, current_match=2, sentence="She saw the dog run."
        )
        got = []
        panel.current_match_sentence(got.append)
        self.assertEqual(got, ["She saw the dog run."])

    def test_yields_from_original_even_while_translation_tab_shows(self):
        # Reading on the Translation tab does not suppress the prompt: the match
        # is an Original one, so its sentence is still yielded from the Original.
        panel = self._panel(
            active_is_original=False, current_match=2, sentence="She saw the dog run."
        )
        got = []
        panel.current_match_sentence(got.append)
        self.assertEqual(got, ["She saw the dog run."])

    def test_empty_on_no_current_match(self):
        panel = self._panel(active_is_original=True, current_match=0)
        got = []
        panel.current_match_sentence(got.append)
        self.assertEqual(got, [""])


if __name__ == "__main__":
    unittest.main()
