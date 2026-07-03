import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from split_translator.main_window import TranslationTool


class BookSentenceRoutingTests(unittest.TestCase):
    """on_book_sentence_matched forwards the sentence to the flashcard panel
    only while the flashcard dock is visible. Driven as an unbound method
    against a lightweight carrier (no WebEngine window)."""

    def _carrier(self, dock_visible):
        captured = {}
        panel = SimpleNamespace(
            autofill_book_example=lambda s: captured.setdefault("sentence", s)
        )
        carrier = SimpleNamespace(
            flashcard_dock=SimpleNamespace(isVisible=lambda: dock_visible),
            flashcard_panel=panel,
        )
        return carrier, captured

    def _run(self, carrier, sentence):
        TranslationTool.on_book_sentence_matched(carrier, sentence)

    def test_forwards_sentence_when_dock_visible(self):
        carrier, captured = self._carrier(dock_visible=True)
        self._run(carrier, "She saw the dog run.")
        self.assertEqual(captured.get("sentence"), "She saw the dog run.")

    def test_no_forward_when_dock_hidden(self):
        carrier, captured = self._carrier(dock_visible=False)
        self._run(carrier, "She saw the dog run.")
        self.assertEqual(captured, {})  # autofill_book_example never called


if __name__ == "__main__":
    unittest.main()
