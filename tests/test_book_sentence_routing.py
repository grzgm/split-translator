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


class NewFlashcardBookExampleTests(unittest.TestCase):
    """New from word clears the editor and then pulls in both the Cambridge grab
    AND the current book sentence, so a fresh card's first example is populated
    from the book without waiting for the next book match. Driven as an unbound
    method against a lightweight carrier (no WebEngine window)."""

    def _carrier(self, new_card_ok, book_sentence):
        captured = {}
        flashcard_panel = SimpleNamespace(
            new_card=lambda force=False: new_card_ok,
            autofill_book_example=lambda s: captured.setdefault("sentence", s),
        )
        carrier = SimpleNamespace(
            flashcard_dock=SimpleNamespace(show=lambda: None),
            flashcard_panel=flashcard_panel,
            dictionary_panel=SimpleNamespace(
                grab_pronunciation=lambda: captured.setdefault("grabbed", True)
            ),
            book_panel=SimpleNamespace(
                current_match_sentence=lambda cb: cb(book_sentence)
            ),
        )
        return carrier, captured

    def test_new_from_word_fills_book_example(self):
        carrier, captured = self._carrier(
            new_card_ok=True, book_sentence="She saw the dog run."
        )
        TranslationTool.new_flashcard(carrier)
        self.assertEqual(captured.get("sentence"), "She saw the dog run.")
        self.assertTrue(captured.get("grabbed"))  # Cambridge grab still happens

    def test_new_from_word_no_book_example_when_no_match(self):
        # No current Original match: current_match_sentence hands back "".
        carrier, captured = self._carrier(new_card_ok=True, book_sentence="")
        TranslationTool.new_flashcard(carrier)
        self.assertEqual(captured.get("sentence"), "")

    def test_new_from_word_declined_does_not_fill(self):
        # The user declined to discard an in-progress card: new_card returns
        # False, so neither the grab nor the book example runs.
        carrier, captured = self._carrier(
            new_card_ok=False, book_sentence="She saw the dog run."
        )
        TranslationTool.new_flashcard(carrier)
        self.assertEqual(captured, {})


if __name__ == "__main__":
    unittest.main()
