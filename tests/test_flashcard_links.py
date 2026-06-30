import tempfile
import unittest
from pathlib import Path

from split_translator.flashcards import (
    Card,
    FlashcardStore,
    Link,
    LINK_TYPES,
    SCHEMA_VERSION,
    load_flashcards,
    serialise_cards,
    write_cards,
)


class LinkTests(unittest.TestCase):
    def test_round_trip(self):
        link = Link(a_id="x", b_id="y", type="synonym")
        self.assertEqual(Link.from_dict(link.to_dict()), link)

    def test_ids_stored_in_canonical_order(self):
        # Constructing with b before a normalises so a_id <= b_id.
        link = Link(a_id="y", b_id="a", type="related")
        self.assertEqual(link.a_id, "a")
        self.assertEqual(link.b_id, "y")

    def test_canonical_order_makes_pairs_equal(self):
        self.assertEqual(
            Link(a_id="a", b_id="b", type="synonym"),
            Link(a_id="b", b_id="a", type="synonym"),
        )

    def test_type_is_free_form_string(self):
        link = Link(a_id="a", b_id="b", type="custom-relation")
        self.assertEqual(Link.from_dict(link.to_dict()).type, "custom-relation")


class LinkTypesTests(unittest.TestCase):
    def test_ships_the_four_types_in_order(self):
        keys = [key for key, _label, _colour in LINK_TYPES]
        self.assertEqual(keys, ["synonym", "similar", "related", "antonym"])

    def test_each_type_has_label_and_colour(self):
        for key, label, colour in LINK_TYPES:
            self.assertTrue(label)
            self.assertTrue(colour.startswith("#"))
