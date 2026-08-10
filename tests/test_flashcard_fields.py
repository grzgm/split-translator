"""The card field registry, as data.

One entry per editable card field is the single source of truth for the editor:
what the widget is called, what it shows, whether it reaches paper, and how its
text maps to and from a Card. These tests pin the mapping and the invariants the
editor's loops rely on."""

import unittest
from dataclasses import FrozenInstanceError
from dataclasses import fields as dataclass_fields

from split_translator.flashcard_fields import CARD_FIELDS, CardField
from split_translator.flashcards import Card


def _spec(name):
    return next(spec for spec in CARD_FIELDS if spec.name == name)


class RegistryShapeTests(unittest.TestCase):
    def test_every_field_matches_a_card_attribute(self):
        # load_card and build_card address the Card by the field's own name, so
        # a name with no matching attribute would fail at runtime.
        attributes = {f.name for f in dataclass_fields(Card)}
        for spec in CARD_FIELDS:
            self.assertIn(spec.name, attributes)

    def test_names_are_unique(self):
        names = [spec.name for spec in CARD_FIELDS]
        self.assertEqual(len(names), len(set(names)))

    def test_the_widget_attribute_follows_the_name(self):
        self.assertEqual(_spec("spelling_uk").attr, "spelling_uk_input")

    def test_the_printed_fields_are_the_ones_shown_on_paper(self):
        printed = {spec.name for spec in CARD_FIELDS if spec.printed}
        self.assertEqual(printed, {"headword", "own_notation"})

    def test_the_registry_covers_the_editor_fields(self):
        self.assertEqual(
            [spec.name for spec in CARD_FIELDS],
            [
                "headword",
                "spelling_uk",
                "spelling_us",
                "ipa_uk",
                "ipa_us",
                "own_notation",
                "tags",
            ],
        )


class MappingTests(unittest.TestCase):
    def test_the_headword_is_stored_as_plain_text(self):
        # The headword is required, so it is "" when blank and never None.
        self.assertEqual(_spec("headword").to_card("  run  "), "run")
        self.assertEqual(_spec("headword").to_card("   "), "")

    def test_optional_text_is_stored_as_none_when_blank(self):
        spec = _spec("spelling_uk")
        self.assertEqual(spec.to_card("  colour "), "colour")
        self.assertIsNone(spec.to_card("   "))

    def test_missing_optional_text_loads_as_an_empty_field(self):
        self.assertEqual(_spec("ipa_uk").from_card(None), "")
        self.assertEqual(_spec("ipa_uk").from_card("/run/"), "/run/")

    def test_tags_map_through_the_tag_helpers(self):
        spec = _spec("tags")
        self.assertEqual(spec.to_card(" book , verb "), ["book", "verb"])
        self.assertEqual(spec.from_card(["book", "verb"]), "book, verb")

    def test_every_field_round_trips(self):
        for spec in CARD_FIELDS:
            self.assertEqual(spec.from_card(spec.to_card("value")), "value")


class DeclarationTests(unittest.TestCase):
    def test_a_field_declares_its_placeholder_and_tooltip(self):
        spec = _spec("tags")
        self.assertEqual(spec.placeholder, "comma separated")
        self.assertIn("comma separated", spec.tooltip)

    def test_a_field_is_immutable(self):
        with self.assertRaises(FrozenInstanceError):
            CARD_FIELDS[0].name = "other"

    def test_defaults_are_the_common_case(self):
        spec = CardField("example_field")
        self.assertEqual(spec.placeholder, "")
        self.assertEqual(spec.tooltip, "")
        self.assertFalse(spec.printed)


if __name__ == "__main__":
    unittest.main()
