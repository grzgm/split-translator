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
            autofill_book_example=lambda s, tag="": captured.update(
                sentence=s, tag=tag
            )
        )
        carrier = SimpleNamespace(
            flashcard_dock=SimpleNamespace(isVisible=lambda: dock_visible),
            flashcard_panel=panel,
            book_tag="book:dracula",
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

    def test_forwards_the_source_book_tag(self):
        carrier, captured = self._carrier(dock_visible=True)
        self._run(carrier, "She saw the dog run.")
        self.assertEqual(captured.get("tag"), "book:dracula")


class NewFlashcardBookExampleTests(unittest.TestCase):
    """New from word clears the editor and then pulls in both the Cambridge grab
    AND the current book sentence, so a fresh card's first example is populated
    from the book without waiting for the next book match. Driven as an unbound
    method against a lightweight carrier (no WebEngine window)."""

    def _carrier(self, new_card_ok, book_sentence):
        captured = {}
        flashcard_panel = SimpleNamespace(
            new_card=lambda force=False: new_card_ok,
            autofill_headword=lambda w: captured.update(seed=w),
            autofill_book_example=lambda s, tag="": captured.update(
                sentence=s, tag=tag
            ),
        )
        carrier = SimpleNamespace(
            flashcard_dock=SimpleNamespace(
                show=lambda: None, setFloating=lambda value: None
            ),
            flashcard_panel=flashcard_panel,
            dictionary_panel=SimpleNamespace(
                search_input=SimpleNamespace(text=lambda: "running"),
                grab_pronunciation=lambda: captured.setdefault("grabbed", True),
            ),
            book_panel=SimpleNamespace(
                current_match_sentence=lambda cb: cb(book_sentence)
            ),
            book_tag="book:dracula",
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

    def test_new_from_word_forwards_the_source_book_tag(self):
        carrier, captured = self._carrier(
            new_card_ok=True, book_sentence="She saw the dog run."
        )
        TranslationTool.new_flashcard(carrier)
        self.assertEqual(captured.get("tag"), "book:dracula")


class SourceBookTagTests(unittest.TestCase):
    """The tag naming a card's source book comes from the Original edition, the
    only one book search runs on. Driven as an unbound method against a
    lightweight carrier (no WebEngine window)."""

    def _carrier(self):
        return SimpleNamespace(
            config=SimpleNamespace(
                original_path="/books/Dracula - Bram Stoker.epub",
                translation_path="/books/Drakula - polskie wydanie.epub",
            )
        )

    def test_tag_comes_from_the_original_edition(self):
        # The two editions give different tags, so this fails if the derivation
        # ever reads translation_path instead.
        self.assertEqual(
            TranslationTool._source_book_tag(self._carrier()),
            "book:dracula - bram stoker",
        )

    def test_no_tag_without_a_configured_book(self):
        carrier = SimpleNamespace(
            config=SimpleNamespace(original_path="", translation_path="")
        )
        self.assertEqual(TranslationTool._source_book_tag(carrier), "")


class WordSearchedClearsEditorTests(unittest.TestCase):
    """on_word_searched clears the flashcard editor before the search's page
    loads auto-fill it, so a new word starts from a blank card. Driven as an
    unbound method against a lightweight carrier (no WebEngine window)."""

    def _carrier(self):
        order = []
        carrier = SimpleNamespace(
            flashcard_panel=SimpleNamespace(
                prepare_for_new_search=lambda: order.append("prepare"),
                autofill_headword=lambda w: order.append(("seed", w)),
            ),
            history_panel=SimpleNamespace(
                add_to_history=lambda w: order.append(("history", w))
            ),
            book_panel=SimpleNamespace(
                search=lambda w: order.append(("book", w))
            ),
        )
        return carrier, order

    def test_prepares_editor_first(self):
        carrier, order = self._carrier()
        TranslationTool.on_word_searched(carrier, "walk")
        # The clear runs before the book search (and before anything that could
        # fill the editor for the new word).
        self.assertEqual(order[0], "prepare")
        self.assertIn(("history", "walk"), order)
        self.assertIn(("book", "walk"), order)

    def test_seeds_the_headword_after_the_clear(self):
        # The seed must follow the clear, or the clear would wipe it.
        carrier, order = self._carrier()
        TranslationTool.on_word_searched(carrier, "walk")
        self.assertEqual(order[:2], ["prepare", ("seed", "walk")])


if __name__ == "__main__":
    unittest.main()
