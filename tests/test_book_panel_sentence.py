import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QFrame

from split_translator.book_panel import BookPanel

app = QApplication.instance() or QApplication([])


class BookSentenceEmitTests(unittest.TestCase):
    """BookPanel emits book_sentence_matched from its find landing point, but
    only for an Original-tab match. Translation-tab searches and zero-match
    results emit nothing (the "Original only, no fuzzing" rule). Driven against
    a stubbed panel so no WebEngine page is built."""

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

        # Stub the two views. The active view's match_sentence yields `sentence`.
        def make_view():
            v = SimpleNamespace()
            v.match_sentence = lambda term, index, cb: cb(sentence)
            return v

        panel.original_view = make_view()
        panel.translation_view = make_view()
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

    def test_no_emit_on_translation_tab(self):
        panel, emitted = self._panel(active_is_original=False)
        panel._on_find_result(2, 5)
        self.assertEqual(emitted, [])

    def test_no_emit_on_zero_matches(self):
        panel, emitted = self._panel(active_is_original=True)
        panel._on_find_result(0, 0)
        self.assertEqual(emitted, [])


if __name__ == "__main__":
    unittest.main()
