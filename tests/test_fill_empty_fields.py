"""The Fill button, panel side.

The gap fill is the deliberate counterpart of the passive auto-grabs: it runs
whatever state the card is in, but it writes only where the card is still
blank, and it leaves the card's altered flag exactly as it found it. That last
rule is what these tests pin hardest: a blank new card stays as open to the
passive grabs as a freshly cleared one, a card the user was editing stays
altered, and a saved card stays unaltered."""

import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from split_translator.flashcard_panel import FlashcardPanel
from split_translator.flashcards import Card, FlashcardStore, Sense

app = QApplication.instance() or QApplication([])


GRAB = {
    "ipa_uk": "/uk/",
    "ipa_us": "/us/",
    "audio_uk_url": "https://example.test/uk.mp3",
    "audio_us_url": "https://example.test/us.mp3",
    "spelling_uk": "colour",
    "spelling_us": "color",
    "word": "run",
}


class FillEmptyTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.store = FlashcardStore(Path(tmp.name) / "cards.json")
        self.panel = FlashcardPanel(self.store)

    def _grab(self, **overrides):
        data = dict(GRAB, **overrides)
        return self.panel.fill_empty_pronunciation(
            data["ipa_uk"],
            data["ipa_us"],
            data["audio_uk_url"],
            data["audio_us_url"],
            data["spelling_uk"],
            data["spelling_us"],
            word=data["word"],
        )

    def _load_saved_card(self):
        self.store.cards = [
            Card(
                headword="address",
                id="id-addr",
                senses=[Sense(polish="adres")],
            )
        ]
        self.panel._refresh_saved_list()
        self.panel._on_saved_clicked(self.panel.saved_list.item(0))

    # --- what it fills --------------------------------------------------

    def test_it_fills_every_blank_field(self):
        self.assertTrue(self._grab())
        self.assertEqual(self.panel.headword_input.text(), "run")
        self.assertEqual(self.panel.ipa_uk_input.text(), "/uk/")
        self.assertEqual(self.panel.ipa_us_input.text(), "/us/")
        self.assertEqual(self.panel.spelling_uk_input.text(), "colour")
        self.assertEqual(self.panel.spelling_us_input.text(), "color")

    def test_it_leaves_a_filled_field_alone(self):
        self.panel.ipa_uk_input.setText("mine")
        self._grab()
        self.assertEqual(self.panel.ipa_uk_input.text(), "mine")
        # The other blanks are still filled: it is per field, not all or nothing.
        self.assertEqual(self.panel.ipa_us_input.text(), "/us/")

    def test_whitespace_does_not_count_as_filled(self):
        self.panel.ipa_uk_input.setText("   ")
        self._grab()
        self.assertEqual(self.panel.ipa_uk_input.text(), "/uk/")

    def test_it_fills_missing_audio_only(self):
        self.panel.set_audio("uk", "https://example.test/mine.mp3")
        self._grab()
        self.assertEqual(
            self.panel._audio_uk_url, "https://example.test/mine.mp3"
        )
        self.assertEqual(self.panel._audio_us_url, GRAB["audio_us_url"])
        self.assertTrue(self.panel.play_us_button.isEnabled())

    def test_a_page_with_nothing_to_offer_changes_nothing(self):
        filled = self.panel.fill_empty_pronunciation(
            None, None, None, None, None, None, word=None
        )
        self.assertFalse(filled)
        self.assertEqual(self.panel.headword_input.text(), "")

    def test_a_card_with_no_gaps_reports_nothing_filled(self):
        self._grab()
        self.assertFalse(self._grab())

    def test_the_headword_is_filled_only_while_blank(self):
        self.assertTrue(self.panel.fill_empty_headword("running"))
        self.assertEqual(self.panel.headword_input.text(), "running")
        self.assertFalse(self.panel.fill_empty_headword("other"))
        self.assertEqual(self.panel.headword_input.text(), "running")

    # --- the book example -----------------------------------------------

    def test_it_fills_a_blank_first_example_and_tags_the_book(self):
        self.assertTrue(
            self.panel.fill_empty_book_example("A sentence.", "book:alice")
        )
        self.assertEqual(
            self.panel._rows()[0].first_example_text(), "A sentence."
        )
        self.assertIn("book:alice", self.panel.tags_input.text())

    def test_it_leaves_a_filled_first_example_and_does_not_tag(self):
        self.panel._rows()[0].set_first_example("Mine.")
        self.assertFalse(
            self.panel.fill_empty_book_example("A sentence.", "book:alice")
        )
        self.assertEqual(self.panel._rows()[0].first_example_text(), "Mine.")
        # Nothing was taken from the book, so there is no source to record.
        self.assertEqual(self.panel.tags_input.text(), "")

    def test_a_blank_sentence_does_nothing(self):
        self.assertFalse(self.panel.fill_empty_book_example("  ", "book:alice"))
        self.assertEqual(self.panel.tags_input.text(), "")

    # --- the altered flag is left exactly as it was ----------------------

    def test_an_untouched_new_card_stays_unaltered(self):
        self._grab()
        self.panel.fill_empty_book_example("A sentence.", "book:alice")
        self.assertFalse(self.panel.state.altered)

    def test_an_untouched_new_card_still_accepts_a_passive_grab_after(self):
        # The point of staying unaltered: the next page load can still refill,
        # exactly as it would on a freshly cleared card.
        self._grab()
        self.panel.autofill_pronunciation(
            "/new uk/", None, None, None, None, None, word="walk"
        )
        self.assertEqual(self.panel.ipa_uk_input.text(), "/new uk/")

    def test_a_card_the_user_was_editing_stays_altered(self):
        self.panel.own_notation_input.setText("my note")
        self.assertTrue(self.panel.state.altered)
        self._grab()
        self.assertTrue(self.panel.state.altered)

    def test_a_loaded_saved_card_stays_unaltered(self):
        self._load_saved_card()
        self._grab()
        self.assertFalse(self.panel.state.altered)
        # It did fill: the card had no IPA.
        self.assertEqual(self.panel.ipa_uk_input.text(), "/uk/")

    def test_it_leaves_the_printed_flag_alone(self):
        self._load_saved_card()
        self.panel.set_printed(True)
        self._grab()
        self.panel.fill_empty_book_example("A sentence.", "book:alice")
        self.assertTrue(self.panel.is_printed())

    def test_the_empty_field_markers_follow_what_was_filled(self):
        self._grab()
        self.assertEqual(
            self.panel.ipa_uk_input.property("emptyField"), "false"
        )
        self.assertEqual(
            self.panel.own_notation_input.property("emptyField"), "true"
        )


if __name__ == "__main__":
    unittest.main()
