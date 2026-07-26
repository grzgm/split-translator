import unittest

from split_translator.flashcard_print_choices import (
    AUTO,
    MANUAL,
    PrintChoices,
    auto_pairs,
    example_snapshot,
)
from split_translator.flashcards import Card, Sense


def _card(card_id="c", *example_lists):
    return Card(
        headword="w", id=card_id,
        senses=[Sense(pos="p", examples=list(e)) for e in example_lists],
    )


class AutoPairsTests(unittest.TestCase):
    def test_lists_every_example_in_sense_order(self):
        card = _card("c", ["a1", "a2"], ["b1"])
        self.assertEqual(auto_pairs(card), [(0, 0), (0, 1), (1, 0)])

    def test_a_card_with_no_examples_has_no_pairs(self):
        self.assertEqual(auto_pairs(Card(headword="w", id="w")), [])


class ModeTests(unittest.TestCase):
    def test_an_unknown_card_is_auto(self):
        self.assertEqual(PrintChoices().mode_of("nobody"), AUTO)

    def test_chosen_for_an_auto_card_is_none(self):
        # None is what tells render_html to leave the card to the browser fit.
        # An empty set would mean "print no examples", which is a real state.
        self.assertIsNone(PrintChoices().chosen_for("nobody"))

    def test_set_manual_switches_the_mode_and_records_the_set(self):
        choices = PrintChoices()
        card = _card("c", ["a1", "a2"])
        choices.set_manual(card, [(0, 1)])
        self.assertEqual(choices.mode_of("c"), MANUAL)
        self.assertEqual(choices.chosen_for("c"), {(0, 1)})

    def test_an_empty_manual_set_is_still_manual(self):
        choices = PrintChoices()
        choices.set_manual(_card("c", ["a1"]), [])
        self.assertEqual(choices.mode_of("c"), MANUAL)
        self.assertEqual(choices.chosen_for("c"), set())

    def test_reset_returns_the_card_to_auto(self):
        choices = PrintChoices()
        choices.set_manual(_card("c", ["a1"]), [(0, 0)])
        choices.reset("c")
        self.assertEqual(choices.mode_of("c"), AUTO)
        self.assertIsNone(choices.chosen_for("c"))

    def test_reset_on_an_unknown_card_does_nothing(self):
        PrintChoices().reset("nobody")  # must not raise

    def test_the_returned_set_is_a_copy(self):
        # Callers tick and untick; mutating what they got back must not rewrite
        # the stored choice behind the model's back.
        choices = PrintChoices()
        choices.set_manual(_card("c", ["a1", "a2"]), [(0, 0)])
        got = choices.chosen_for("c")
        got.add((0, 1))
        self.assertEqual(choices.chosen_for("c"), {(0, 0)})


class RenderMapTests(unittest.TestCase):
    def test_only_manual_cards_appear(self):
        choices = PrintChoices()
        choices.set_manual(_card("c", ["a1", "a2"]), [(0, 0)])
        self.assertEqual(choices.as_render_map(), {"c": {(0, 0)}})

    def test_no_manual_cards_is_an_empty_map(self):
        self.assertEqual(PrintChoices().as_render_map(), {})


class DropStaleTests(unittest.TestCase):
    def test_an_edited_example_drops_the_choice(self):
        choices = PrintChoices()
        choices.set_manual(_card("c", ["a1", "a2"]), [(0, 0)])
        edited = _card("c", ["a1 reworded", "a2"])
        self.assertEqual(choices.drop_stale([edited]), ["c"])
        self.assertEqual(choices.mode_of("c"), AUTO)

    def test_an_added_example_drops_the_choice(self):
        choices = PrintChoices()
        choices.set_manual(_card("c", ["a1"]), [(0, 0)])
        self.assertEqual(choices.drop_stale([_card("c", ["a1", "a2"])]), ["c"])

    def test_an_untouched_card_keeps_its_choice(self):
        choices = PrintChoices()
        choices.set_manual(_card("c", ["a1", "a2"]), [(0, 0)])
        self.assertEqual(choices.drop_stale([_card("c", ["a1", "a2"])]), [])
        self.assertEqual(choices.chosen_for("c"), {(0, 0)})

    def test_a_flag_only_change_keeps_the_choice(self):
        # Toggling printed or starred writes the card but touches no example,
        # so the hand-picked set must survive it.
        choices = PrintChoices()
        choices.set_manual(_card("c", ["a1"]), [(0, 0)])
        flagged = _card("c", ["a1"])
        flagged.printed = True
        self.assertEqual(choices.drop_stale([flagged]), [])

    def test_a_deleted_card_drops_its_choice(self):
        choices = PrintChoices()
        choices.set_manual(_card("c", ["a1"]), [(0, 0)])
        self.assertEqual(choices.drop_stale([]), ["c"])
        self.assertEqual(choices.mode_of("c"), AUTO)

    def test_a_card_with_no_choice_is_ignored(self):
        self.assertEqual(PrintChoices().drop_stale([_card("c", ["a1"])]), [])


class SnapshotTests(unittest.TestCase):
    def test_it_is_hashable_and_comparable(self):
        card = _card("c", ["a1"], ["b1"])
        self.assertEqual(example_snapshot(card), example_snapshot(_card("c", ["a1"], ["b1"])))
        self.assertNotEqual(example_snapshot(card), example_snapshot(_card("c", ["a1"])))


if __name__ == "__main__":
    unittest.main()
