"""Filling a card by hand while the dictionary pages are still loading.

The pages take seconds. A search sets three passive fills going that land at
different moments: the search-box seed at once, the book sentence soon after,
and the Cambridge grab whenever the page finishes. These tests are the story of
what the user is allowed to do in that gap, and they drive the panel the way
main_window does: prepare_for_new_search, then the fills as each source
answers.

The rule in one line: the card decides at the moment of the search whether it
takes part at all, and each field decides for itself from then on."""

import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from split_translator.flashcard_panel import FlashcardPanel
from split_translator.flashcards import Card, FlashcardStore, Sense

app = QApplication.instance() or QApplication([])

#: One Cambridge page's worth of grab, as main_window passes it on.
GRAB = dict(
    ipa_uk="/run/",
    ipa_us="/ruhn/",
    audio_uk_url="uk.mp3",
    audio_us_url="us.mp3",
    spelling_uk="run",
    spelling_us="run",
    word="run",
)


class AutofillWhileLoadingTests(unittest.TestCase):
    def _panel(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        store = FlashcardStore(Path(tmp.name) / "cards.json")
        return FlashcardPanel(store), store

    def _search(self, panel, word="run"):
        """A dictionary search, as main_window.on_word_searched runs it."""
        panel.prepare_for_new_search()
        panel.autofill_headword(word)

    def _page_loaded(self, panel, **overrides):
        """The Cambridge page, seconds later."""
        data = dict(GRAB)
        data.update(overrides)
        panel.autofill_pronunciation(
            data["ipa_uk"],
            data["ipa_us"],
            data["audio_uk_url"],
            data["audio_us_url"],
            data["spelling_uk"],
            data["spelling_us"],
            word=data["word"],
        )

    # --- typing into a card the search opened -----------------------------

    def test_a_headword_typed_while_the_page_loads_survives_it(self):
        panel, _ = self._panel()
        self._search(panel)
        panel.headword_input.setText("to run away")  # typed during the wait
        self._page_loaded(panel)
        self.assertEqual(panel.headword_input.text(), "to run away")

    def test_the_page_still_fills_everything_that_was_not_typed(self):
        panel, _ = self._panel()
        self._search(panel)
        panel.headword_input.setText("to run away")
        self._page_loaded(panel)
        self.assertEqual(panel.ipa_uk_input.text(), "/run/")
        self.assertEqual(panel.ipa_us_input.text(), "/ruhn/")
        self.assertEqual(panel.spelling_uk_input.text(), "run")
        self.assertEqual(panel._audio_uk_url, "uk.mp3")
        self.assertEqual(panel._audio_us_url, "us.mp3")

    def test_one_typed_notation_leaves_the_other_free(self):
        panel, _ = self._panel()
        self._search(panel)
        panel.ipa_uk_input.setText("/my own/")
        self._page_loaded(panel)
        self.assertEqual(panel.ipa_uk_input.text(), "/my own/")
        self.assertEqual(panel.ipa_us_input.text(), "/ruhn/")

    def test_a_typed_sense_does_not_stop_the_page(self):
        panel, _ = self._panel()
        self._search(panel)
        panel._rows()[0].polish_input.setText("biegac")
        panel._rows()[0].english_input.setText("to move fast")
        self._page_loaded(panel)
        self.assertEqual(panel.headword_input.text(), "run")
        self.assertEqual(panel.ipa_uk_input.text(), "/run/")
        # And the hand-written translation is still there.
        self.assertEqual(panel._rows()[0].polish_input.text(), "biegac")

    def test_own_notation_typed_while_the_page_loads_does_not_stop_it(self):
        # Own notation has no fill behind it, so a note written while the page
        # is held up (Cambridge's bot check can take a while to pass) costs the
        # card none of the page's fill.
        panel, _ = self._panel()
        self._search(panel, "running")
        panel.own_notation_input.setText("my note")
        self._page_loaded(panel)
        self.assertEqual(panel.own_notation_input.text(), "my note")
        self.assertEqual(panel.headword_input.text(), "run")
        self.assertEqual(panel.ipa_uk_input.text(), "/run/")
        self.assertEqual(panel._audio_uk_url, "uk.mp3")

    def test_a_typed_sense_does_not_stop_the_book_sentence(self):
        # The example slot is the book's until someone types in the slot itself.
        panel, _ = self._panel()
        self._search(panel)
        panel._rows()[0].polish_input.setText("biegac")
        panel.autofill_book_example("He began to run.", "book:dune")
        self.assertEqual(panel._rows()[0].examples(), ["He began to run."])
        self.assertEqual(panel.tags_input.text(), "book:dune")

    def test_a_typed_example_keeps_the_book_sentence_out(self):
        panel, _ = self._panel()
        self._search(panel)
        panel._rows()[0].add_example("")
        panel._rows()[0].set_first_example("my own sentence")
        panel.autofill_book_example("He began to run.", "book:dune")
        self.assertEqual(panel._rows()[0].examples(), ["my own sentence"])

    def test_a_captured_example_keeps_the_book_sentence_out(self):
        # A capture from a web page creates the first example row outright, so
        # the slot is taken without a keystroke.
        panel, _ = self._panel()
        self._search(panel)
        panel.add_example_selection("captured from the page")
        panel.autofill_book_example("He began to run.", "book:dune")
        self.assertEqual(
            panel._rows()[0].examples(), ["captured from the page"]
        )

    def test_a_typed_example_still_lets_the_page_fill(self):
        panel, _ = self._panel()
        self._search(panel)
        panel.add_example_selection("captured from the page")
        self._page_loaded(panel)
        self.assertEqual(panel.ipa_uk_input.text(), "/run/")
        self.assertEqual(panel.headword_input.text(), "run")

    def test_only_the_first_sense_owns_the_book_sentence(self):
        # The fill writes the FIRST sense's first example, so an example typed
        # into a second sense is not that slot and closes nothing.
        panel, _ = self._panel()
        self._search(panel)
        panel.add_sense()
        panel._rows()[1].add_example("second sense example")
        panel.autofill_book_example("He began to run.")
        self.assertEqual(panel._rows()[0].examples(), ["He began to run."])
        self.assertEqual(panel._rows()[1].examples(), ["second sense example"])

    def test_a_field_emptied_again_stays_the_users_own(self):
        # Deleting what you typed does not hand the field back: a field is never
        # rewritten under someone who has been in it.
        panel, _ = self._panel()
        self._search(panel)
        panel.headword_input.setText("typed then deleted")
        panel.headword_input.setText("")
        self._page_loaded(panel)
        self.assertEqual(panel.headword_input.text(), "")

    # --- a card that was already being edited -----------------------------

    def test_a_search_made_mid_edit_fills_nothing(self):
        # The old whole-card rule, kept where it belongs: search, edit, search
        # again, and the second search's pages stay out of the card.
        panel, _ = self._panel()
        self._search(panel, "run")
        panel.headword_input.setText("my own card")
        panel._rows()[0].polish_input.setText("moje")
        self._search(panel, "walk")
        self._page_loaded(panel, word="walk", ipa_uk="/wawk/")
        panel.autofill_book_example("She walked home.", "book:dune")
        self.assertEqual(panel.headword_input.text(), "my own card")
        self.assertEqual(panel.ipa_uk_input.text(), "")
        self.assertEqual(panel._rows()[0].examples(), [])
        self.assertEqual(panel.tags_input.text(), "")

    def test_the_mid_edit_search_does_not_clear_the_card(self):
        # A search is passive, so it never prompts and never discards.
        panel, _ = self._panel()
        self._search(panel, "run")
        panel.headword_input.setText("my own card")
        self._search(panel, "walk")
        self.assertEqual(panel.headword_input.text(), "my own card")
        self.assertTrue(panel.state.altered)

    def test_the_next_clean_search_opens_the_card_again(self):
        # Clearing (or saving, or loading) is a fresh baseline, so the search
        # after it fills as usual.
        panel, _ = self._panel()
        self._search(panel, "run")
        panel.headword_input.setText("my own card")
        self._search(panel, "walk")  # shut
        panel.ctrl_held = lambda: True  # skip the discard prompt
        panel.clear_editor()
        self._search(panel, "walk")
        self._page_loaded(panel, word="walk", ipa_uk="/wawk/")
        self.assertEqual(panel.headword_input.text(), "walk")
        self.assertEqual(panel.ipa_uk_input.text(), "/wawk/")

    # --- the other ways a round starts ------------------------------------

    def test_a_saved_card_is_open_to_the_next_search(self):
        # "The previous flashcard was saved, I search and start filling."
        panel, _ = self._panel()
        panel.headword_input.setText("previous")
        panel.save_card()
        self.assertFalse(panel.state.altered)
        self._search(panel)
        panel.ipa_uk_input.setText("/mine/")
        self._page_loaded(panel)
        self.assertEqual(panel.headword_input.text(), "run")
        self.assertEqual(panel.ipa_uk_input.text(), "/mine/")
        self.assertEqual(panel.spelling_uk_input.text(), "run")

    def test_a_new_card_is_open_while_its_page_loads(self):
        # The New button and Ctrl+N take the same three sources as a search, so
        # they get the same gap to type in.
        panel, _ = self._panel()
        self.assertTrue(panel.new_card(force=True))
        panel.autofill_headword("run")
        panel.headword_input.setText("run away")
        self._page_loaded(panel)
        self.assertEqual(panel.headword_input.text(), "run away")
        self.assertEqual(panel.ipa_uk_input.text(), "/run/")

    # --- a saved card, loaded or just saved, takes no passive fill ---------

    def _load(self, panel, store, card):
        """Select a saved card in the list, as a click does."""
        store.cards = [card]
        panel._refresh_saved_list()
        panel._on_saved_clicked(panel.saved_list.item(0))

    def test_book_matches_leave_a_loaded_cards_example_alone(self):
        # Selecting a card looks its headword up in the book, and F3 and
        # Shift+F3 then walk the matches. None of those sentences is the saved
        # card's to take, and neither is the book's tag.
        panel, store = self._panel()
        saved = Card(
            headword="run",
            id="id-1",
            senses=[Sense(examples=["The sentence I kept."])],
        )
        self._load(panel, store, saved)
        panel.autofill_book_example("He began to run.", "book:dune")  # lookup
        panel.autofill_book_example("They ran all night.", "book:dune")  # F3
        self.assertEqual(panel._rows()[0].examples(), ["The sentence I kept."])
        self.assertEqual(panel.tags_input.text(), "")

    def test_book_matches_leave_a_just_saved_cards_example_alone(self):
        # The report: search, save, then F3 through the book, and the saved
        # card's example changed under it.
        panel, _ = self._panel()
        self._search(panel)
        panel.autofill_book_example("He began to run.", "book:dune")
        panel.save_card()
        panel.autofill_book_example("They ran all night.", "book:dune")  # F3
        self.assertEqual(panel._rows()[0].examples(), ["He began to run."])

    def test_a_page_grab_leaves_a_loaded_card_alone(self):
        # Showing the dock grabs the Cambridge page on screen, which need not
        # even be this card's word.
        panel, store = self._panel()
        saved = Card(headword="walk", id="id-1", ipa_uk="/mine/")
        self._load(panel, store, saved)
        self._page_loaded(panel)
        self.assertEqual(panel.headword_input.text(), "walk")
        self.assertEqual(panel.ipa_uk_input.text(), "/mine/")
        self.assertIsNone(panel._audio_uk_url)

    def test_new_after_a_saved_card_fills_again(self):
        # New replaces the saved card with a fresh one, which takes part again.
        panel, store = self._panel()
        self._load(panel, store, Card(headword="walk", id="id-1"))
        self.assertTrue(panel.new_card(force=True))
        panel.autofill_book_example("He began to run.", "book:dune")
        self.assertEqual(panel._rows()[0].examples(), ["He began to run."])

    # --- the fills stay passive -------------------------------------------

    def test_typing_then_filling_leaves_one_altered_flip(self):
        # The fills write through the programmatic guard, so the card is altered
        # by the typing alone; the dock's "*" does not flicker.
        panel, _ = self._panel()
        flips = []
        panel.altered_changed.connect(flips.append)
        self._search(panel)
        panel.headword_input.setText("typed")
        self._page_loaded(panel)
        panel.autofill_book_example("He began to run.", "book:dune")
        self.assertEqual(flips, [True])


if __name__ == "__main__":
    unittest.main()
