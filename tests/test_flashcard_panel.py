import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLineEdit

from split_translator.flashcard_panel import FlashcardPanel
from split_translator.flashcards import Card, FlashcardStore, Sense

app = QApplication.instance() or QApplication([])


class FlashcardPanelTests(unittest.TestCase):
    def _panel(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        store = FlashcardStore(Path(tmp.name) / "cards.json")
        return FlashcardPanel(store), store

    # --- mode indicators ------------------------------------------------

    def test_starts_in_new_mode(self):
        panel, _ = self._panel()
        self.assertTrue(panel.state.is_new)
        self.assertEqual(panel.save_button.text(), "Add card")
        self.assertEqual(panel.id_input.text(), "")

    def test_id_field_is_read_only_and_disabled(self):
        panel, _ = self._panel()
        self.assertTrue(panel.id_input.isReadOnly())
        self.assertFalse(panel.id_input.isEnabled())

    def test_loading_shows_editing_mode_and_id(self):
        panel, store = self._panel()
        store.cards = [Card(headword="address", id="id-addr")]
        panel._refresh_saved_list()
        panel._on_saved_clicked(panel.saved_list.item(0))
        self.assertTrue(panel.state.is_editing)
        self.assertEqual(panel.save_button.text(), "Save changes")
        self.assertEqual(panel.id_input.text(), "id-addr")

    def test_clear_returns_to_new_mode(self):
        panel, store = self._panel()
        store.cards = [Card(headword="address", id="id-addr")]
        panel._refresh_saved_list()
        panel._on_saved_clicked(panel.saved_list.item(0))
        panel.ctrl_held = lambda: True  # skip the discard prompt
        panel.clear_editor()
        self.assertTrue(panel.state.is_new)
        self.assertEqual(panel.save_button.text(), "Add card")
        self.assertEqual(panel.id_input.text(), "")

    def test_save_stays_in_editing_mode(self):
        panel, store = self._panel()
        store.cards = [Card(headword="address", id="id-addr")]
        panel._refresh_saved_list()
        panel._on_saved_clicked(panel.saved_list.item(0))
        panel.headword_input.setText("address2")
        panel.save_card()
        # Save keeps the card loaded: still editing, fields intact, unaltered.
        self.assertTrue(panel.state.is_editing)
        self.assertEqual(panel.save_button.text(), "Save changes")
        self.assertEqual(panel.id_input.text(), "id-addr")
        self.assertEqual(panel.headword_input.text(), "address2")
        self.assertFalse(panel.state.altered)

    def test_saving_new_card_enters_editing_mode_of_that_card(self):
        panel, store = self._panel()
        panel.headword_input.setText("newword")
        panel.ipa_uk_input.setText("/nw/")
        self.assertTrue(panel.state.is_new)
        panel.save_card()
        # The brand-new card becomes the loaded card without any field wipe.
        self.assertTrue(panel.state.is_editing)
        self.assertEqual(panel.id_input.text(), store.cards[0].id)
        self.assertEqual(panel.save_button.text(), "Save changes")
        self.assertEqual(panel.headword_input.text(), "newword")
        self.assertEqual(panel.ipa_uk_input.text(), "/nw/")
        self.assertFalse(panel.state.altered)

    def test_saved_card_row_shows_the_dot_after_saving_new(self):
        panel, store = self._panel()
        panel.headword_input.setText("newword")
        panel.save_card()
        # The saved card's own row is the loaded row: not checkable, has the dot.
        saved_id = store.cards[0].id
        item = next(
            panel.saved_list.item(i)
            for i in range(panel.saved_list.count())
            if panel.saved_list.item(i).data(Qt.ItemDataRole.UserRole) == saved_id
        )
        self.assertFalse(
            bool(item.flags() & Qt.ItemFlag.ItemIsUserCheckable)
        )
        self.assertFalse(item.icon().isNull())

    # --- basic editing --------------------------------------------------

    def test_starts_with_one_active_sense(self):
        panel, _ = self._panel()
        self.assertEqual(len(panel._rows()), 1)
        self.assertIs(panel.active_row, panel._rows()[0])

    def test_capture_routes_to_active_row(self):
        panel, _ = self._panel()
        panel.set_polish_selection("adres")
        panel.set_english_selection("the details of where someone lives")
        row = panel.active_row
        self.assertEqual(row.polish_input.text(), "adres")
        self.assertEqual(
            row.english_input.text(), "the details of where someone lives"
        )

    def test_capture_scrolls_field_to_start(self):
        panel, _ = self._panel()
        long_text = "a very long english definition that overflows the field width"
        panel.set_english_selection(long_text)
        row = panel.active_row
        self.assertEqual(row.english_input.text(), long_text)
        self.assertEqual(row.english_input.cursorPosition(), 0)

    def test_has_focus_true_when_a_child_has_focus(self):
        panel, _ = self._panel()
        panel.show()
        panel.headword_input.setFocus()
        QApplication.processEvents()
        self.assertTrue(panel.has_focus())
        panel.hide()

    def test_has_focus_false_when_nothing_focused(self):
        panel, _ = self._panel()
        panel.clearFocus()
        QApplication.processEvents()
        self.assertFalse(panel.has_focus())

    def test_play_audio_is_noop_without_url(self):
        panel, _ = self._panel()
        self.assertIsNone(panel.player)
        panel.play_audio("uk")
        panel.play_audio("us")
        self.assertIsNone(panel.player)

    def test_add_sense_makes_new_row_active(self):
        panel, _ = self._panel()
        panel.add_sense()
        self.assertEqual(len(panel._rows()), 2)
        self.assertIs(panel.active_row, panel._rows()[1])

    def test_append_polish_sets_empty_field(self):
        panel, _ = self._panel()
        panel.append_polish_selection("ksiazka")
        self.assertEqual(panel.active_row.polish_input.text(), "ksiazka")

    def test_append_polish_comma_joins_non_empty_field(self):
        panel, _ = self._panel()
        panel.set_polish_selection("ksiazka")
        panel.append_polish_selection("tom")
        panel.append_polish_selection("wolumin")
        self.assertEqual(
            panel.active_row.polish_input.text(), "ksiazka, tom, wolumin"
        )

    def test_append_polish_skips_blank(self):
        panel, _ = self._panel()
        panel.set_polish_selection("ksiazka")
        panel.append_polish_selection("   ")
        self.assertEqual(panel.active_row.polish_input.text(), "ksiazka")

    def test_append_english_comma_joins_non_empty_field(self):
        panel, _ = self._panel()
        panel.set_english_selection("a book")
        panel.append_english_selection("a volume")
        self.assertEqual(
            panel.active_row.english_input.text(), "a book, a volume"
        )

    def test_append_scrolls_field_to_start(self):
        panel, _ = self._panel()
        long_text = "a very long english definition that overflows the field width"
        panel.append_english_selection(long_text)
        self.assertEqual(panel.active_row.english_input.cursorPosition(), 0)

    def test_example_capture_appends_to_active_row(self):
        panel, _ = self._panel()
        panel.add_example_selection("She lives at that address.")
        panel.add_example_selection("Send it to my address.")
        row = panel.active_row
        self.assertEqual(
            row.examples(),
            ["She lives at that address.", "Send it to my address."],
        )

    def test_example_capture_skips_blank(self):
        panel, _ = self._panel()
        panel.add_example_selection("   ")
        self.assertEqual(panel.active_row.examples(), [])

    def test_add_example_with_focus_calls_setfocus(self):
        panel, _ = self._panel()
        focused = []
        orig = QLineEdit.setFocus
        try:
            QLineEdit.setFocus = lambda self, *a: focused.append(self)
            panel.active_row.add_example(focus=True)
        finally:
            QLineEdit.setFocus = orig
        field = panel.active_row._example_rows()[-1].example_input
        self.assertIn(field, focused)

    def test_example_capture_does_not_focus(self):
        panel, _ = self._panel()
        focused = []
        orig = QLineEdit.setFocus
        try:
            QLineEdit.setFocus = lambda self, *a: focused.append(self)
            panel.active_row.add_example_text("She lives at that address.")
        finally:
            QLineEdit.setFocus = orig
        self.assertEqual(focused, [])

    def test_build_card_carries_examples(self):
        panel, _ = self._panel()
        panel.headword_input.setText("address")
        panel.set_english_selection("the details of a place")
        panel.add_example_selection("She lives at that address.")
        card = panel.build_card()
        self.assertEqual(len(card.senses), 1)
        self.assertEqual(card.senses[0].examples, ["She lives at that address."])

    def test_sense_kept_when_only_examples(self):
        panel, _ = self._panel()
        panel.headword_input.setText("address")
        panel.add_example_selection("She lives at that address.")
        card = panel.build_card()
        self.assertEqual(len(card.senses), 1)
        self.assertEqual(card.senses[0].polish, "")
        self.assertEqual(card.senses[0].examples, ["She lives at that address."])

    def test_build_card_requires_headword(self):
        panel, _ = self._panel()
        self.assertIsNone(panel.build_card())

    def test_build_card_drops_empty_senses(self):
        panel, _ = self._panel()
        panel.headword_input.setText("address")
        panel.active_row.pos_combo.setCurrentText("n")
        panel.set_polish_selection("adres")
        panel.add_sense()  # second, left empty
        card = panel.build_card()
        self.assertEqual(card.headword, "address")
        self.assertEqual(len(card.senses), 1)
        self.assertEqual(card.senses[0].pos, "n")
        self.assertEqual(card.senses[0].polish, "adres")

    def test_save_persists_and_keeps_fields(self):
        panel, store = self._panel()
        panel.headword_input.setText("address")
        panel.set_polish_selection("adres")
        panel.save_card()
        store.shutdown()
        self.assertEqual(len(store.cards), 1)
        # Fields are kept, not cleared; the editor now edits the saved card.
        self.assertEqual(panel.headword_input.text(), "address")
        self.assertTrue(panel.state.is_editing)
        self.assertEqual(panel.state.loaded_card_id, store.cards[0].id)
        self.assertFalse(panel.state.altered)

    def test_build_card_carries_star(self):
        panel, _ = self._panel()
        panel.headword_input.setText("address")
        self.assertFalse(panel.build_card().starred)
        panel.set_starred(True)
        self.assertTrue(panel.build_card().starred)

    def test_save_keeps_star_and_persists_it(self):
        panel, store = self._panel()
        panel.headword_input.setText("address")
        panel.set_starred(True)
        panel.save_card()
        store.shutdown()
        self.assertTrue(store.cards[0].starred)
        # The card stays loaded, so the star stays set in the editor too.
        self.assertTrue(panel.is_starred())

    # --- auto-grab (autofill_pronunciation) -----------------------------

    def test_grab_fills_everything_when_editor_empty(self):
        panel, _ = self._panel()
        panel.autofill_pronunciation("/aa/", "/bb/", "a.mp3", None, "uk", "us", word="run")
        self.assertEqual(panel.headword_input.text(), "run")
        self.assertEqual(panel.ipa_uk_input.text(), "/aa/")
        self.assertEqual(panel.ipa_us_input.text(), "/bb/")
        self.assertEqual(panel.spelling_uk_input.text(), "uk")
        self.assertEqual(panel.spelling_us_input.text(), "us")
        self.assertEqual(panel._audio_uk_url, "a.mp3")

    def test_grab_does_not_mark_altered(self):
        # A passive autofill is programmatic, so it must leave the card unaltered
        # (so the next page load can refill it and no discard prompt fires).
        panel, _ = self._panel()
        panel.autofill_pronunciation("/aa/", "/bb/", "a.mp3", None, "uk", "us", word="run")
        self.assertFalse(panel.state.altered)

    def test_second_grab_replaces_unaltered_autofill(self):
        panel, _ = self._panel()
        panel.autofill_pronunciation("/aa/", "/bb/", "a.mp3", "ax.mp3", "uk", "us", word="run")
        panel.autofill_pronunciation("/cc/", None, "c.mp3", None, "uk2", None, word="walk")
        self.assertEqual(panel.headword_input.text(), "walk")
        self.assertEqual(panel.ipa_uk_input.text(), "/cc/")
        self.assertEqual(panel.spelling_uk_input.text(), "uk2")
        self.assertEqual(panel._audio_uk_url, "c.mp3")
        # Fields the new word lacks are cleared, not left from the first word.
        self.assertEqual(panel.ipa_us_input.text(), "")
        self.assertEqual(panel.spelling_us_input.text(), "")
        self.assertIsNone(panel._audio_us_url)

    def test_grab_blocked_after_user_edits_a_field(self):
        # Once the user has altered the card, a passive grab does nothing.
        panel, _ = self._panel()
        panel.autofill_pronunciation("/aa/", "/bb/", "a.mp3", None, "uk", "us", word="run")
        panel.headword_input.setText("my own word")  # user edit -> altered
        panel.autofill_pronunciation("/cc/", "/dd/", "c.mp3", None, "uk2", "us2", word="walk")
        self.assertEqual(panel.headword_input.text(), "my own word")
        self.assertEqual(panel.ipa_uk_input.text(), "/aa/")  # unchanged
        self.assertEqual(panel.spelling_uk_input.text(), "uk")
        self.assertEqual(panel._audio_uk_url, "a.mp3")

    def test_grab_refills_a_loaded_but_unaltered_card(self):
        # Uniform rule: an unaltered loaded card IS refilled by a passive grab.
        panel, _ = self._panel()
        card = Card(headword="loaded", ipa_uk="/ld/", senses=[])
        panel.load_card(card)
        self.assertFalse(panel.state.altered)
        panel.autofill_pronunciation("/cc/", None, "c.mp3", None, word="walk")
        self.assertEqual(panel.headword_input.text(), "walk")
        self.assertEqual(panel.ipa_uk_input.text(), "/cc/")

    def test_grab_leaves_an_altered_loaded_card_alone(self):
        panel, _ = self._panel()
        card = Card(headword="loaded", ipa_uk="/ld/", senses=[])
        panel.load_card(card)
        panel.headword_input.setText("touched")  # user edit -> altered
        panel.autofill_pronunciation("/cc/", None, "c.mp3", None, word="walk")
        self.assertEqual(panel.headword_input.text(), "touched")
        self.assertEqual(panel.ipa_uk_input.text(), "/ld/")

    # --- prepare_for_new_search (clear before new-search auto-fill) ------

    def test_prepare_clears_stale_senses_then_new_word_fills(self):
        # An unaltered loaded card is fully cleared before the new word fills it:
        # the old senses/examples must not linger under the new word.
        panel, _ = self._panel()
        card = Card(
            headword="old",
            senses=[
                Sense(pos="n", polish="stary", examples=["old ex"]),
                Sense(pos="v", polish="drugi"),
            ],
        )
        panel.load_card(card)
        self.assertFalse(panel.state.altered)
        panel.prepare_for_new_search()
        panel.autofill_pronunciation("/nw/", None, "n.mp3", None, word="new")
        panel.autofill_book_example("A new sentence.")
        self.assertEqual(panel.headword_input.text(), "new")
        self.assertEqual(len(panel._rows()), 1)
        self.assertEqual(panel._rows()[0].polish_input.text(), "")
        self.assertEqual(panel._rows()[0].examples(), ["A new sentence."])
        self.assertTrue(panel.state.is_new)
        self.assertFalse(panel.state.altered)
        self.assertIsNone(panel.state.loaded_card_id)

    def test_prepare_clears_star_and_own_notation_and_audio(self):
        panel, _ = self._panel()
        card = Card(
            headword="w",
            starred=True,
            own_notation="mine",
            audio_uk_url="u.mp3",
            senses=[],
        )
        panel.load_card(card)
        panel.prepare_for_new_search()
        self.assertFalse(panel.star_button.isChecked())
        self.assertEqual(panel.own_notation_input.text(), "")
        self.assertIsNone(panel._audio_uk_url)
        self.assertFalse(panel.play_uk_button.isEnabled())

    def test_prepare_on_freshly_saved_card_clears_it(self):
        # A just-saved (unaltered, editing) card is cleared to a fresh new card;
        # the saved card itself still exists in the store.
        panel, store = self._panel()
        panel.headword_input.setText("book")
        panel.active_row.polish_input.setText("ksiazka")
        panel.save_card()
        self.assertTrue(panel.state.is_editing)
        panel.prepare_for_new_search()
        self.assertEqual(panel.headword_input.text(), "")
        self.assertEqual(len(panel._rows()), 1)
        self.assertEqual(panel._rows()[0].polish_input.text(), "")
        self.assertTrue(panel.state.is_new)
        self.assertIsNone(panel.state.loaded_card_id)
        self.assertEqual(len(store.cards), 1)  # the saved card is untouched

    def test_book_example_survives_repeated_grabs_after_prepare(self):
        # Regression guard for the previous broken attempt: the clear happens
        # once, up front, so later same-search pronunciation grabs do not wipe
        # the book example.
        panel, _ = self._panel()
        panel.prepare_for_new_search()
        panel.autofill_pronunciation("/aa/", "/bb/", "a.mp3", None, "uk", "us", word="run")
        panel.autofill_book_example("She saw the dog run.")
        self.assertEqual(panel._rows()[0].examples(), ["She saw the dog run."])
        for _ in range(2):  # same-search Cambridge reloads
            panel.autofill_pronunciation("/aa/", "/bb/", "a.mp3", None, "uk", "us", word="run")
            self.assertEqual(panel._rows()[0].examples(), ["She saw the dog run."])
        self.assertEqual(panel.headword_input.text(), "run")
        self.assertFalse(panel.state.altered)

    def test_prepare_leaves_altered_card_untouched(self):
        # An altered card is not cleared and never prompts.
        panel, _ = self._panel()
        panel.headword_input.setText("editing")  # user edit -> altered
        panel._rows()[0].polish_input.setText("robie")
        panel.star_button.setChecked(True)
        self.assertTrue(panel.state.altered)

        def _tripwire():
            raise AssertionError("prepare_for_new_search must not prompt")

        panel._confirm_discard = _tripwire
        panel.prepare_for_new_search()
        self.assertEqual(panel.headword_input.text(), "editing")
        self.assertEqual(panel._rows()[0].polish_input.text(), "robie")
        self.assertTrue(panel.star_button.isChecked())
        self.assertTrue(panel.state.altered)

    def test_prepare_then_autofills_skip_altered_card(self):
        # End to end: a search never clobbers in-progress work.
        panel, _ = self._panel()
        panel.headword_input.setText("editing")
        panel._rows()[0].polish_input.setText("robie")
        self.assertTrue(panel.state.altered)
        panel.prepare_for_new_search()
        panel.autofill_pronunciation("/cc/", None, "c.mp3", None, word="walk")
        panel.autofill_book_example("ignored")
        self.assertEqual(panel.headword_input.text(), "editing")
        self.assertEqual(panel._rows()[0].examples(), [])

    def test_prepare_on_empty_editor_is_harmless(self):
        panel, _ = self._panel()
        self.assertTrue(panel.state.is_new)
        panel.prepare_for_new_search()
        self.assertEqual(len(panel._rows()), 1)
        self.assertEqual(panel._rows()[0].examples(), [])
        self.assertTrue(panel.state.is_new)
        self.assertFalse(panel.state.altered)

    def test_ctrl_n_seed_path_does_not_use_prepare(self):
        # Documents that the Ctrl+N seed order (new_card + grab + book example)
        # is orthogonal to prepare_for_new_search and keeps its book example.
        panel, _ = self._panel()
        panel.new_card(force=True)
        panel.autofill_pronunciation("/aa/", None, "a.mp3", None, word="run")
        panel.autofill_book_example("seed sentence")
        self.assertEqual(panel._rows()[0].examples(), ["seed sentence"])

    # --- explicit-action prompts ----------------------------------------

    def test_new_card_clears_without_setting_headword(self):
        panel, _ = self._panel()
        self.assertTrue(panel.new_card())
        self.assertEqual(panel.headword_input.text(), "")

    def test_new_card_returns_false_when_discard_declined(self):
        panel, _ = self._panel()
        panel.headword_input.setText("keep")
        panel._confirm_discard = lambda: False
        self.assertFalse(panel.new_card())
        self.assertEqual(panel.headword_input.text(), "keep")

    def test_new_card_force_skips_confirmation(self):
        panel, _ = self._panel()
        panel.headword_input.setText("keep")
        asked = []
        panel._confirm_discard = lambda: asked.append(True) or False
        self.assertTrue(panel.new_card(force=True))
        self.assertEqual(asked, [])
        self.assertEqual(panel.headword_input.text(), "")

    def test_clear_editor_ctrl_skips_confirmation(self):
        panel, _ = self._panel()
        panel.headword_input.setText("keep")
        asked = []
        panel._confirm_discard = lambda: asked.append(True) or False
        panel.ctrl_held = lambda: True
        panel.clear_editor()
        self.assertEqual(asked, [])
        self.assertEqual(panel.headword_input.text(), "")

    def test_clear_editor_without_ctrl_confirms(self):
        panel, _ = self._panel()
        panel.headword_input.setText("keep")
        panel.ctrl_held = lambda: False
        panel._confirm_discard = lambda: False
        panel.clear_editor()
        self.assertEqual(panel.headword_input.text(), "keep")

    # --- altered flag ---------------------------------------------------

    def test_empty_editor_is_unaltered(self):
        panel, _ = self._panel()
        self.assertFalse(panel.state.altered)

    def test_typing_marks_altered(self):
        panel, _ = self._panel()
        panel.headword_input.setText("run")
        self.assertTrue(panel.state.altered)

    def test_loading_a_card_leaves_it_unaltered(self):
        panel, store = self._panel()
        store.cards = [Card(headword="address", id="id-addr",
                            senses=[Sense(pos="n", polish="adres")])]
        panel._refresh_saved_list()
        panel._on_saved_clicked(panel.saved_list.item(0))
        self.assertFalse(panel.state.altered)

    def test_save_leaves_editor_unaltered(self):
        panel, _ = self._panel()
        panel.headword_input.setText("run")
        self.assertTrue(panel.state.altered)
        panel.save_card()
        self.assertFalse(panel.state.altered)

    def test_starring_marks_altered(self):
        panel, _ = self._panel()
        panel.set_starred(True)
        self.assertTrue(panel.state.altered)

    def test_adding_an_example_marks_altered(self):
        panel, _ = self._panel()
        panel.active_row.add_example("an example", focus=False)
        self.assertTrue(panel.state.altered)

    # --- replace audio from the page (set_audio) ------------------------

    def test_set_audio_sets_only_that_region(self):
        panel, _ = self._panel()
        panel.headword_input.setText("run")
        panel.ipa_uk_input.setText("/old/")
        panel.set_audio("uk", "https://example/new-uk.mp3", "/new/")
        self.assertEqual(panel._audio_uk_url, "https://example/new-uk.mp3")
        self.assertIsNone(panel._audio_us_url)
        self.assertEqual(panel.headword_input.text(), "run")
        self.assertEqual(panel.ipa_uk_input.text(), "/new/")

    def test_set_audio_us_is_the_mirror(self):
        panel, _ = self._panel()
        panel.set_audio("us", "https://example/new-us.mp3", "/yu/")
        self.assertEqual(panel._audio_us_url, "https://example/new-us.mp3")
        self.assertEqual(panel.ipa_us_input.text(), "/yu/")
        self.assertIsNone(panel._audio_uk_url)
        self.assertEqual(panel.ipa_uk_input.text(), "")

    def test_set_audio_keeps_existing_ipa_when_none_captured(self):
        panel, _ = self._panel()
        panel.ipa_uk_input.setText("/keep/")
        panel.set_audio("uk", "https://example/new-uk.mp3", None)
        self.assertEqual(panel.ipa_uk_input.text(), "/keep/")

    def test_set_audio_ipa_defaults_to_none(self):
        panel, _ = self._panel()
        panel.ipa_uk_input.setText("/keep/")
        panel.set_audio("uk", "https://example/new-uk.mp3")
        self.assertEqual(panel.ipa_uk_input.text(), "/keep/")

    def test_set_audio_enables_that_speaker_button(self):
        panel, _ = self._panel()
        self.assertFalse(panel.play_uk_button.isEnabled())
        panel.set_audio("uk", "https://example/new-uk.mp3")
        self.assertTrue(panel.play_uk_button.isEnabled())
        self.assertFalse(panel.play_us_button.isEnabled())

    def test_set_audio_marks_the_card_altered(self):
        panel, _ = self._panel()
        self.assertFalse(panel.state.altered)
        panel.set_audio("uk", "https://example/new-uk.mp3")
        self.assertTrue(panel.state.altered)

    def test_set_audio_blocks_a_later_passive_grab(self):
        panel, _ = self._panel()
        panel.autofill_pronunciation("/aa/", "/bb/", "a.mp3", None, "uk", "us", word="run")
        panel.set_audio("uk", "https://example/replaced.mp3", "/zz/")
        panel.autofill_pronunciation("/cc/", "/dd/", "c.mp3", None, "uk2", "us2", word="walk")
        self.assertEqual(panel.headword_input.text(), "run")
        self.assertEqual(panel.ipa_uk_input.text(), "/zz/")
        self.assertEqual(panel._audio_uk_url, "https://example/replaced.mp3")

    def test_set_audio_unknown_region_is_a_noop(self):
        panel, _ = self._panel()
        panel.set_audio("xx", "https://example/x.mp3")
        self.assertIsNone(panel._audio_uk_url)
        self.assertIsNone(panel._audio_us_url)
        self.assertFalse(panel.state.altered)

    def test_set_audio_empty_url_clears_that_region(self):
        panel, _ = self._panel()
        panel._audio_uk_url = "old.mp3"
        panel.set_audio("uk", "")
        self.assertIsNone(panel._audio_uk_url)
        self.assertFalse(panel.play_uk_button.isEnabled())

    # --- empty-field marking --------------------------------------------

    @staticmethod
    def _marked(field):
        return "border" in field.styleSheet()

    def _card_fields(self, panel):
        return (
            panel.headword_input,
            panel.spelling_uk_input,
            panel.spelling_us_input,
            panel.ipa_uk_input,
            panel.ipa_us_input,
            panel.own_notation_input,
        )

    def test_empty_card_fields_are_marked(self):
        panel, _ = self._panel()
        self.assertTrue(all(self._marked(f) for f in self._card_fields(panel)))

    def test_empty_sense_fields_are_marked(self):
        panel, _ = self._panel()
        row = panel.active_row
        self.assertTrue(self._marked(row.pos_combo))
        self.assertTrue(self._marked(row.polish_input))
        self.assertTrue(self._marked(row.english_input))

    def test_setting_pos_clears_its_marker(self):
        panel, _ = self._panel()
        row = panel.active_row
        row.pos_combo.setCurrentText("n")
        self.assertFalse(self._marked(row.pos_combo))
        row.pos_combo.setCurrentText("")
        self.assertTrue(self._marked(row.pos_combo))

    def test_blank_example_is_marked_and_clears_when_typed(self):
        panel, _ = self._panel()
        row = panel.active_row
        row.add_example()
        field = row._example_rows()[-1].example_input
        self.assertTrue(self._marked(field))
        field.setText("She lives here.")
        self.assertFalse(self._marked(field))

    def test_captured_example_is_not_marked(self):
        panel, _ = self._panel()
        row = panel.active_row
        row.add_example_text("She lives here.")
        field = row._example_rows()[-1].example_input
        self.assertFalse(self._marked(field))

    def test_filling_a_field_clears_its_marker(self):
        panel, _ = self._panel()
        panel.headword_input.setText("dog")
        self.assertFalse(self._marked(panel.headword_input))
        panel.active_row.polish_input.setText("pies")
        self.assertFalse(self._marked(panel.active_row.polish_input))

    def test_clearing_a_field_re_marks_it(self):
        panel, _ = self._panel()
        panel.headword_input.setText("dog")
        panel.headword_input.clear()
        self.assertTrue(self._marked(panel.headword_input))

    def test_grab_clears_markers_on_filled_fields(self):
        panel, _ = self._panel()
        panel.autofill_pronunciation("/wn/", "/wun/", "u.mp3", None, word="one")
        self.assertFalse(self._marked(panel.headword_input))
        self.assertFalse(self._marked(panel.ipa_uk_input))
        self.assertTrue(self._marked(panel.spelling_uk_input))

    def test_reset_re_marks_card_and_new_sense(self):
        panel, _ = self._panel()
        panel.headword_input.setText("dog")
        panel.active_row.polish_input.setText("pies")
        panel._reset_editor()
        self.assertTrue(all(self._marked(f) for f in self._card_fields(panel)))
        new_row = panel.active_row
        self.assertTrue(self._marked(new_row.polish_input))
        self.assertTrue(self._marked(new_row.english_input))

    # --- saved-cards list -----------------------------------------------

    def _seed(self, panel, store):
        store.cards = [
            Card(
                headword="address",
                ipa_uk="/adres/",
                id="id-addr",
                created_at="2026-01-01T00:00:00",
                senses=[
                    Sense(pos="n", polish="adres", english="a place",
                          examples=["my address"])
                ],
            ),
            Card(headword="receive", id="id-recv", starred=True,
                 created_at="2026-01-02T00:00:00"),
        ]
        panel._refresh_saved_list()

    def _labels(self, panel):
        return [
            panel.saved_list.item(i).text()
            for i in range(panel.saved_list.count())
        ]

    def test_saved_list_lists_cards_with_star_marker(self):
        panel, store = self._panel()
        self._seed(panel, store)
        self.assertEqual(self._labels(panel), ["address", "Starred: receive"])

    def test_saved_list_starts_from_stored_cards(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        store = FlashcardStore(Path(tmp.name) / "cards.json")
        store.cards = [Card(headword="preexisting", id="p")]
        panel = FlashcardPanel(store)
        self.assertEqual(self._labels(panel), ["preexisting"])

    def test_clicking_saved_card_loads_it(self):
        panel, store = self._panel()
        self._seed(panel, store)
        panel._on_saved_clicked(panel.saved_list.item(0))
        self.assertEqual(panel.headword_input.text(), "address")
        self.assertEqual(panel.ipa_uk_input.text(), "/adres/")
        self.assertEqual(panel.state.loaded_card_id, "id-addr")
        row = panel.active_row
        self.assertEqual(row.pos_combo.currentText(), "n")
        self.assertEqual(row.polish_input.text(), "adres")
        self.assertEqual(row.english_input.text(), "a place")
        self.assertEqual(row.examples(), ["my address"])

    def test_loading_starred_card_reflects_star(self):
        panel, store = self._panel()
        self._seed(panel, store)
        panel._on_saved_clicked(panel.saved_list.item(1))
        self.assertTrue(panel.is_starred())

    def test_editing_loaded_card_saves_in_place(self):
        panel, store = self._panel()
        self._seed(panel, store)
        panel._on_saved_clicked(panel.saved_list.item(0))
        panel.active_row.polish_input.setText("adres pocztowy")
        panel.save_card()
        store.shutdown()
        self.assertEqual(len(store.cards), 2)  # updated, not duplicated
        addr = next(c for c in store.cards if c.id == "id-addr")
        self.assertEqual(addr.senses[0].polish, "adres pocztowy")
        self.assertEqual(addr.created_at, "2026-01-01T00:00:00")  # preserved
        # Editor stays on the card, unaltered, fields intact.
        self.assertEqual(panel.headword_input.text(), "address")
        self.assertTrue(panel.state.is_editing)
        self.assertEqual(panel.state.loaded_card_id, "id-addr")
        self.assertFalse(panel.state.altered)

    def test_save_after_new_card_adds_not_updates(self):
        panel, store = self._panel()
        self._seed(panel, store)
        panel._on_saved_clicked(panel.saved_list.item(0))
        panel.new_card(force=True)
        self.assertTrue(panel.state.is_new)
        panel.headword_input.setText("fresh")
        panel.save_card()
        # The new card was added and is now the loaded card.
        self.assertEqual(len(store.cards), 3)
        self.assertEqual(store.cards[0].headword, "fresh")
        self.assertTrue(panel.state.is_editing)
        self.assertEqual(panel.state.loaded_card_id, store.cards[0].id)
        # Saving again updates in place, does not duplicate.
        panel.save_card()
        store.shutdown()
        self.assertEqual(len(store.cards), 3)

    def test_saved_list_refreshes_after_save(self):
        panel, store = self._panel()
        self._seed(panel, store)
        panel.headword_input.setText("brandnew")
        panel.save_card()
        self.assertIn("brandnew", self._labels(panel))

    def test_load_declined_keeps_current_editor(self):
        panel, store = self._panel()
        self._seed(panel, store)
        panel.headword_input.setText("inprogress")
        panel.ctrl_held = lambda: False
        panel._confirm_discard = lambda: False
        self.assertFalse(panel.load_card(store.cards[0]))
        self.assertEqual(panel.headword_input.text(), "inprogress")
        self.assertTrue(panel.state.is_new)

    def test_loading_then_loading_again_does_not_prompt(self):
        panel, store = self._panel()
        self._seed(panel, store)
        panel.ctrl_held = lambda: False
        asked = []
        panel._confirm_discard = lambda: asked.append(True) or False
        panel._on_saved_clicked(panel.saved_list.item(0))
        self.assertTrue(panel.load_card(store.cards[1]))
        self.assertEqual(asked, [])
        self.assertEqual(panel.headword_input.text(), "receive")

    def test_editing_loaded_card_then_loading_prompts(self):
        panel, store = self._panel()
        self._seed(panel, store)
        panel.ctrl_held = lambda: False
        panel._on_saved_clicked(panel.saved_list.item(0))
        panel.active_row.polish_input.setText("adres pocztowy")
        self.assertTrue(panel.state.altered)
        asked = []
        panel._confirm_discard = lambda: asked.append(True) or False
        self.assertFalse(panel.load_card(store.cards[1]))
        self.assertEqual(asked, [True])

    # --- card_loaded signal (drives the no-history dictionary lookup) ----

    def test_load_emits_card_loaded_with_headword(self):
        panel, store = self._panel()
        self._seed(panel, store)
        loaded = []
        panel.card_loaded.connect(loaded.append)
        panel._on_saved_clicked(panel.saved_list.item(0))
        self.assertEqual(loaded, ["address"])

    def test_declined_load_does_not_emit_card_loaded(self):
        panel, store = self._panel()
        self._seed(panel, store)
        panel.headword_input.setText("inprogress")
        panel.ctrl_held = lambda: False
        panel._confirm_discard = lambda: False
        loaded = []
        panel.card_loaded.connect(loaded.append)
        self.assertFalse(panel.load_card(store.cards[0]))
        self.assertEqual(loaded, [])

    # --- editor / saved-list splitter -----------------------------------

    def test_editor_splitter_holds_scroll_then_list(self):
        from PySide6.QtWidgets import QScrollArea

        panel, _ = self._panel()
        splitter = panel.editor_splitter
        self.assertEqual(splitter.count(), 2)
        self.assertIsInstance(splitter.widget(0), QScrollArea)
        self.assertTrue(splitter.widget(1).isAncestorOf(panel.saved_list))

    def test_editor_scroll_is_resizable_and_not_collapsible(self):
        panel, _ = self._panel()
        self.assertTrue(panel.editor_scroll.widgetResizable())
        self.assertFalse(panel.editor_splitter.childrenCollapsible())

    def test_reset_scrolls_editor_to_top(self):
        panel, _ = self._panel()
        panel.resize(400, 250)
        panel.show()
        QApplication.processEvents()
        self.addCleanup(panel.hide)
        bar = panel.editor_scroll.verticalScrollBar()
        bar.setValue(bar.maximum())
        self.assertGreater(bar.value(), 0)
        panel._reset_editor()
        self.assertEqual(bar.value(), 0)

    def test_loading_a_card_scrolls_editor_to_top(self):
        panel, store = self._panel()
        self._seed(panel, store)
        panel.resize(400, 250)
        panel.show()
        QApplication.processEvents()
        self.addCleanup(panel.hide)
        bar = panel.editor_scroll.verticalScrollBar()
        bar.setValue(bar.maximum())
        self.assertGreater(bar.value(), 0)
        panel._on_saved_clicked(panel.saved_list.item(0))
        self.assertEqual(bar.value(), 0)

    # --- SenseRow.set_first_example ------------------------------------
    def test_set_first_example_creates_when_empty(self):
        from split_translator.flashcard_panel import SenseRow
        row = SenseRow()
        row.set_first_example("She saw the dog run.")
        self.assertEqual(row.examples(), ["She saw the dog run."])

    def test_set_first_example_overwrites_existing_first(self):
        from split_translator.flashcard_panel import SenseRow
        row = SenseRow()
        row.add_example("first")
        row.add_example("second")
        row.set_first_example("replaced")
        # First example replaced, later examples untouched.
        self.assertEqual(row.examples(), ["replaced", "second"])

    # --- autofill_book_example -----------------------------------------
    def test_book_example_fills_first_sense_first_slot_when_unaltered(self):
        panel, _ = self._panel()
        panel.autofill_book_example("She saw the dog run.")
        self.assertEqual(
            panel._rows()[0].examples(), ["She saw the dog run."]
        )

    def test_book_example_replaces_on_second_call(self):
        panel, _ = self._panel()
        panel.autofill_book_example("first sentence")
        panel.autofill_book_example("second sentence")
        self.assertEqual(panel._rows()[0].examples(), ["second sentence"])

    def test_book_example_does_not_mark_altered(self):
        panel, _ = self._panel()
        panel.autofill_book_example("a sentence")
        self.assertFalse(panel.state.altered)
        # Because it stayed unaltered, a later call still fills (proves the
        # guard held and the gate stays open).
        panel.autofill_book_example("next sentence")
        self.assertEqual(panel._rows()[0].examples(), ["next sentence"])

    def test_book_example_ignored_when_altered(self):
        panel, _ = self._panel()
        panel.headword_input.setText("edited")  # genuine user edit -> altered
        panel.autofill_book_example("should be ignored")
        self.assertEqual(panel._rows()[0].examples(), [])

    def test_book_example_blank_is_noop(self):
        panel, _ = self._panel()
        panel.autofill_book_example("   ")
        self.assertEqual(panel._rows()[0].examples(), [])
        self.assertFalse(panel.state.altered)


if __name__ == "__main__":
    unittest.main()
