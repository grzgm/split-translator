import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

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
        # A captured value longer than the field shows its beginning, not its
        # end: the cursor is reset to position 0 after the fill.
        panel, _ = self._panel()
        long_text = "a very long english definition that overflows the field width"
        panel.set_english_selection(long_text)
        row = panel.active_row
        self.assertEqual(row.english_input.text(), long_text)
        self.assertEqual(row.english_input.cursorPosition(), 0)

    def test_has_focus_true_when_a_child_has_focus(self):
        panel, _ = self._panel()
        # The panel must be shown for a child to actually take keyboard focus.
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
        # No pronunciation grabbed yet: play_audio must not raise and must not
        # build a player. This is what makes Alt+1 / Alt+2 safe on an empty card.
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

    # Real keyboard focus cannot be asserted under the offscreen platform
    # (focusWidget() is always None), so these check that setFocus is invoked on
    # the right field instead, which is what drives the focus on a live display.
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
        self.assertEqual(
            card.senses[0].examples, ["She lives at that address."]
        )

    def test_sense_kept_when_only_examples(self):
        panel, _ = self._panel()
        panel.headword_input.setText("address")
        panel.add_example_selection("She lives at that address.")
        card = panel.build_card()
        self.assertEqual(len(card.senses), 1)
        self.assertEqual(card.senses[0].polish, "")
        self.assertEqual(
            card.senses[0].examples, ["She lives at that address."]
        )

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

    def test_save_persists_and_clears(self):
        panel, store = self._panel()
        panel.headword_input.setText("address")
        panel.set_polish_selection("adres")
        panel.save_card()
        store.shutdown()
        self.assertEqual(len(store.cards), 1)
        self.assertEqual(panel.headword_input.text(), "")

    def test_build_card_carries_star(self):
        panel, _ = self._panel()
        panel.headword_input.setText("address")
        self.assertFalse(panel.build_card().starred)
        panel.set_starred(True)
        self.assertTrue(panel.build_card().starred)

    def test_save_resets_star(self):
        panel, store = self._panel()
        panel.headword_input.setText("address")
        panel.set_starred(True)
        panel.save_card()
        store.shutdown()
        self.assertTrue(store.cards[0].starred)
        self.assertFalse(panel.is_starred())

    def test_grab_fills_everything_when_editor_empty(self):
        panel, _ = self._panel()
        panel.set_pronunciation("/aa/", "/bb/", "a.mp3", None, "uk", "us", word="run")
        self.assertEqual(panel.headword_input.text(), "run")
        self.assertEqual(panel.ipa_uk_input.text(), "/aa/")
        self.assertEqual(panel.ipa_us_input.text(), "/bb/")
        self.assertEqual(panel.spelling_uk_input.text(), "uk")
        self.assertEqual(panel.spelling_us_input.text(), "us")
        self.assertEqual(panel._audio_uk_url, "a.mp3")

    def test_grab_fills_nothing_when_any_field_has_value(self):
        panel, _ = self._panel()
        panel.ipa_uk_input.setText("/mine/")  # one field already filled
        panel.set_pronunciation("/aa/", "/bb/", "a.mp3", None, "uk", "us", word="run")
        # Nothing is touched, not even the empty fields.
        self.assertEqual(panel.headword_input.text(), "")
        self.assertEqual(panel.ipa_uk_input.text(), "/mine/")
        self.assertEqual(panel.ipa_us_input.text(), "")
        self.assertEqual(panel.spelling_uk_input.text(), "")
        self.assertIsNone(panel._audio_uk_url)

    def test_grab_blocked_by_headword_value(self):
        panel, _ = self._panel()
        panel.headword_input.setText("kept")
        panel.set_pronunciation("/aa/", None, None, None, word="run")
        self.assertEqual(panel.headword_input.text(), "kept")
        self.assertEqual(panel.ipa_uk_input.text(), "")

    def test_grab_blocked_by_existing_audio(self):
        panel, _ = self._panel()
        panel._audio_uk_url = "old.mp3"
        panel.set_pronunciation("/aa/", None, None, None, word="run")
        self.assertEqual(panel.headword_input.text(), "")
        self.assertEqual(panel.ipa_uk_input.text(), "")

    def test_new_card_clears_without_setting_headword(self):
        panel, _ = self._panel()
        # Empty editor: no discard prompt, returns True, clears.
        self.assertTrue(panel.new_card("run"))
        self.assertEqual(panel.headword_input.text(), "")

    def test_new_card_returns_false_when_discard_declined(self):
        panel, _ = self._panel()
        panel.headword_input.setText("keep")
        panel._confirm_discard = lambda: False
        self.assertFalse(panel.new_card("run"))
        self.assertEqual(panel.headword_input.text(), "keep")

    def test_new_card_force_skips_confirmation(self):
        panel, _ = self._panel()
        panel.headword_input.setText("keep")
        asked = []
        panel._confirm_discard = lambda: asked.append(True) or False
        self.assertTrue(panel.new_card("run", force=True))
        self.assertEqual(asked, [])  # never prompted
        self.assertEqual(panel.headword_input.text(), "")  # cleared

    def test_clear_editor_ctrl_skips_confirmation(self):
        panel, _ = self._panel()
        panel.headword_input.setText("keep")
        asked = []
        panel._confirm_discard = lambda: asked.append(True) or False
        panel.ctrl_held = lambda: True
        panel.clear_editor()
        self.assertEqual(asked, [])  # never prompted
        self.assertEqual(panel.headword_input.text(), "")  # cleared

    def test_clear_editor_without_ctrl_confirms(self):
        panel, _ = self._panel()
        panel.headword_input.setText("keep")
        panel.ctrl_held = lambda: False
        panel._confirm_discard = lambda: False  # decline
        panel.clear_editor()
        self.assertEqual(panel.headword_input.text(), "keep")  # not cleared

    # --- empty-field marking --------------------------------------------
    # A blank fillable field carries a "border" style; a filled one does not.

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
        row.add_example()  # blank "+ example" row
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
        panel.set_pronunciation("/wn/", "/wun/", "u.mp3", None, word="one")
        self.assertFalse(self._marked(panel.headword_input))
        self.assertFalse(self._marked(panel.ipa_uk_input))
        # No spelling came through, so those stay marked.
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
        # The list is built at construction from whatever the store already holds.
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
        self.assertEqual(panel._loaded_card_id, "id-addr")
        row = panel.active_row
        self.assertEqual(row.pos_combo.currentText(), "n")
        self.assertEqual(row.polish_input.text(), "adres")
        self.assertEqual(row.english_input.text(), "a place")
        self.assertEqual(row.examples(), ["my address"])

    def test_loading_starred_card_reflects_star(self):
        panel, store = self._panel()
        self._seed(panel, store)
        panel._on_saved_clicked(panel.saved_list.item(1))  # receive (starred)
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
        # Editor reset and back to creating a fresh card.
        self.assertEqual(panel.headword_input.text(), "")
        self.assertIsNone(panel._loaded_card_id)

    def test_save_after_new_card_adds_not_updates(self):
        panel, store = self._panel()
        self._seed(panel, store)
        panel._on_saved_clicked(panel.saved_list.item(0))  # load address
        panel.new_card("fresh", force=True)  # forget the loaded id
        self.assertIsNone(panel._loaded_card_id)
        panel.headword_input.setText("fresh")
        panel.save_card()
        store.shutdown()
        self.assertEqual(len(store.cards), 3)  # a brand new card
        self.assertEqual(store.cards[0].headword, "fresh")

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
        panel._confirm_discard = lambda: False  # decline the discard
        self.assertFalse(panel.load_card(store.cards[0]))
        self.assertEqual(panel.headword_input.text(), "inprogress")
        self.assertIsNone(panel._loaded_card_id)

    # --- unsaved-changes prompt gating ----------------------------------
    # The discard prompt is gated on actual edits, not just on content: a
    # freshly loaded (or reset) card reads as clean, so viewing a different
    # card does not prompt; only a genuine edit re-arms the prompt.

    def test_empty_editor_is_not_dirty(self):
        panel, _ = self._panel()
        self.assertFalse(panel._dirty)

    def test_typing_marks_dirty(self):
        panel, _ = self._panel()
        panel.headword_input.setText("run")
        self.assertTrue(panel._dirty)

    def test_loading_a_card_leaves_it_clean(self):
        panel, store = self._panel()
        self._seed(panel, store)
        panel._on_saved_clicked(panel.saved_list.item(0))  # load "address"
        self.assertFalse(panel._dirty)

    def test_loading_then_loading_again_does_not_prompt(self):
        panel, store = self._panel()
        self._seed(panel, store)
        panel.ctrl_held = lambda: False
        asked = []
        panel._confirm_discard = lambda: asked.append(True) or False
        panel._on_saved_clicked(panel.saved_list.item(0))  # load "address"
        # Switching to another card without editing must not prompt.
        self.assertTrue(panel.load_card(store.cards[1]))
        self.assertEqual(asked, [])
        self.assertEqual(panel.headword_input.text(), "receive")

    def test_editing_loaded_card_then_loading_prompts(self):
        panel, store = self._panel()
        self._seed(panel, store)
        panel.ctrl_held = lambda: False
        panel._on_saved_clicked(panel.saved_list.item(0))  # load "address"
        panel.active_row.polish_input.setText("adres pocztowy")  # a real edit
        self.assertTrue(panel._dirty)
        asked = []
        panel._confirm_discard = lambda: asked.append(True) or False
        self.assertFalse(panel.load_card(store.cards[1]))  # declined
        self.assertEqual(asked, [True])  # prompted because edited

    def test_save_leaves_editor_clean(self):
        panel, _ = self._panel()
        panel.headword_input.setText("run")
        self.assertTrue(panel._dirty)
        panel.save_card()
        self.assertFalse(panel._dirty)

    def test_starring_marks_dirty(self):
        panel, _ = self._panel()
        panel.set_starred(True)
        self.assertTrue(panel._dirty)

    def test_adding_an_example_marks_dirty(self):
        panel, _ = self._panel()
        panel.active_row.add_example("an example", focus=False)
        self.assertTrue(panel._dirty)

    def test_capturing_audio_only_marks_dirty(self):
        # A grab that fills only audio (no headword/IPA/spelling) sets the URLs
        # by direct assignment, which fires no textChanged; it must still mark
        # the card dirty so the captured audio is not silently discarded.
        panel, _ = self._panel()
        panel.set_pronunciation(
            ipa_uk=None,
            ipa_us=None,
            audio_uk_url="https://example/uk.mp3",
            audio_us_url=None,
        )
        self.assertTrue(panel._dirty)


if __name__ == "__main__":
    unittest.main()
