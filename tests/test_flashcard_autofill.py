"""The passive fills' round: which targets may still be written, and when.

Pure logic, so no Qt and no display. The panel-level story these rules exist
for is in test_autofill_while_loading."""

import unittest

from split_translator.flashcard_autofill import AutofillRound, Target
from split_translator.flashcard_editor_state import EditorState
from split_translator.flashcard_fields import CARD_FIELDS


class TargetNamesTests(unittest.TestCase):
    def test_the_text_targets_are_registry_field_names(self):
        # What lets each field name its own target from the one wiring loop in
        # _wire_fields. Rename a registry field without renaming its target here
        # and that field would quietly stop closing to the fills.
        names = {spec.name for spec in CARD_FIELDS}
        for target in (
            Target.HEADWORD,
            Target.SPELLING_UK,
            Target.SPELLING_US,
            Target.IPA_UK,
            Target.IPA_US,
        ):
            self.assertIn(target, names)

    def test_the_other_targets_are_not_registry_fields(self):
        # The clips and the example are not text fields, so they are named in
        # the module alone and must not collide with a field.
        names = {spec.name for spec in CARD_FIELDS}
        for target in (Target.AUDIO_UK, Target.AUDIO_US, Target.EXAMPLE):
            self.assertNotIn(target, names)

    def test_region_helpers_pick_the_right_target(self):
        self.assertEqual(Target.audio("uk"), Target.AUDIO_UK)
        self.assertEqual(Target.audio("us"), Target.AUDIO_US)
        self.assertEqual(Target.ipa("uk"), Target.IPA_UK)
        self.assertEqual(Target.ipa("us"), Target.IPA_US)


class AutofillRoundTests(unittest.TestCase):
    def test_a_fresh_round_allows_everything(self):
        # A fresh editor holds a fresh unaltered card, so it starts open.
        round_ = AutofillRound()
        self.assertTrue(round_.is_open)
        self.assertTrue(round_.allows(Target.HEADWORD))
        self.assertTrue(round_.allows(Target.EXAMPLE))

    def test_taking_a_target_closes_only_that_one(self):
        round_ = AutofillRound()
        round_.take(Target.HEADWORD)
        self.assertFalse(round_.allows(Target.HEADWORD))
        self.assertTrue(round_.allows(Target.IPA_UK))
        self.assertTrue(round_.allows(Target.EXAMPLE))

    def test_is_taken_reports_the_same_thing_without_the_open_flag(self):
        round_ = AutofillRound()
        round_.take(Target.IPA_UK)
        self.assertTrue(round_.is_taken(Target.IPA_UK))
        self.assertFalse(round_.is_taken(Target.IPA_US))

    def test_a_blank_target_is_ignored(self):
        # Fields with no fill behind them (Own notation, Tags) and edits with no
        # target at all (a staged link) pass through here harmlessly.
        round_ = AutofillRound()
        round_.take("")
        self.assertTrue(round_.allows(Target.HEADWORD))
        self.assertFalse(round_.is_taken(""))

    def test_a_shut_round_allows_nothing_it_had_not_taken(self):
        round_ = AutofillRound()
        round_.close()
        self.assertFalse(round_.is_open)
        self.assertFalse(round_.allows(Target.HEADWORD))
        self.assertFalse(round_.allows(Target.EXAMPLE))

    def test_restart_reopens_and_frees_every_target(self):
        round_ = AutofillRound()
        round_.take(Target.HEADWORD)
        round_.close()
        round_.restart()
        self.assertTrue(round_.is_open)
        self.assertTrue(round_.allows(Target.HEADWORD))

    def test_a_target_stays_taken_across_repeated_takes(self):
        round_ = AutofillRound()
        round_.take(Target.HEADWORD)
        round_.take(Target.HEADWORD)
        self.assertFalse(round_.allows(Target.HEADWORD))


class EditorStateRoundTests(unittest.TestCase):
    def test_mark_altered_takes_the_named_target(self):
        state = EditorState()
        state.mark_altered(Target.HEADWORD)
        self.assertTrue(state.altered)
        self.assertFalse(state.autofill.allows(Target.HEADWORD))
        self.assertTrue(state.autofill.allows(Target.IPA_UK))

    def test_mark_altered_without_a_target_frees_every_fill(self):
        # An edit that is not a fill target (the printed toggle, a staged link)
        # still alters the card, but must not shut a page load out of it.
        state = EditorState()
        state.mark_altered()
        self.assertTrue(state.altered)
        self.assertTrue(state.autofill.allows(Target.HEADWORD))

    def test_begin_autofill_opens_a_round_on_an_unaltered_card(self):
        state = EditorState()
        state.autofill.close()
        self.assertTrue(state.begin_autofill())
        self.assertTrue(state.autofill.allows(Target.HEADWORD))

    def test_begin_autofill_shuts_the_round_on_an_altered_card(self):
        # A search made while the card was being edited leaves it out entirely.
        state = EditorState()
        state.mark_altered(Target.HEADWORD)
        self.assertFalse(state.begin_autofill())
        self.assertFalse(state.autofill.is_open)
        self.assertFalse(state.autofill.allows(Target.IPA_UK))

    def test_begin_autofill_frees_targets_taken_earlier(self):
        state = EditorState()
        state.mark_altered(Target.HEADWORD)
        state.to_new()  # a clear: fresh baseline
        state.begin_autofill()
        self.assertTrue(state.autofill.allows(Target.HEADWORD))

    def test_a_clear_or_new_restarts_the_round(self):
        state = EditorState()
        state.mark_altered(Target.HEADWORD)
        state.autofill.close()
        state.to_new()
        self.assertTrue(state.autofill.allows(Target.HEADWORD))

    def test_a_load_or_save_shuts_the_round(self):
        # A saved card, just loaded or just saved, takes no passive fill: a book
        # match (F3) or a page grab must not rewrite what was saved. The altered
        # baseline still resets, as it does at every other baseline.
        state = EditorState()
        state.mark_altered(Target.HEADWORD)
        state.to_editing("id-1", "t")
        self.assertFalse(state.altered)
        self.assertFalse(state.autofill.is_open)
        self.assertFalse(state.autofill.allows(Target.EXAMPLE))
        self.assertFalse(state.autofill.allows(Target.IPA_UK))

    def test_a_search_on_a_saved_card_opens_a_round_again(self):
        # The search replaces the unaltered saved card with a fresh one, and
        # that one takes part.
        state = EditorState()
        state.to_editing("id-1", "t")
        self.assertTrue(state.begin_autofill())
        self.assertTrue(state.autofill.allows(Target.EXAMPLE))


if __name__ == "__main__":
    unittest.main()
