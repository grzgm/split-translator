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


class LinkStorageTests(unittest.TestCase):
    def test_serialise_includes_version_2_and_links(self):
        cards = [Card(headword="a", id="a"), Card(headword="b", id="b")]
        links = [Link(a_id="a", b_id="b", type="synonym")]
        data = serialise_cards(cards, links)
        self.assertEqual(data["version"], 2)
        self.assertEqual(SCHEMA_VERSION, 2)
        self.assertEqual(data["links"], [{"a_id": "a", "b_id": "b",
                                          "type": "synonym"}])

    def test_round_trip_cards_and_links(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "f.json"
            cards = [Card(headword="a", id="a"), Card(headword="b", id="b")]
            links = [Link(a_id="a", b_id="b", type="related")]
            write_cards(p, serialise_cards(cards, links))
            loaded_cards, loaded_links = load_flashcards(p)
            self.assertEqual(len(loaded_cards), 2)
            self.assertEqual(loaded_links, links)

    def test_v1_file_loads_with_empty_links(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "f.json"
            p.write_text(
                '{"version": 1, "cards": [{"id": "a", "headword": "a"}]}',
                encoding="utf-8",
            )
            cards, links = load_flashcards(p)
            self.assertEqual(len(cards), 1)
            self.assertEqual(links, [])

    def test_dangling_links_pruned_on_load(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "f.json"
            # Link references "gone", which is not among the cards.
            data = {
                "version": 2,
                "cards": [{"id": "a", "headword": "a"}],
                "links": [{"a_id": "a", "b_id": "gone", "type": "synonym"}],
            }
            import json
            p.write_text(json.dumps(data), encoding="utf-8")
            cards, links = load_flashcards(p)
            self.assertEqual(links, [])

    def test_missing_file_returns_empty_pair(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(load_flashcards(Path(d) / "none.json"), ([], []))

    def test_unknown_type_survives_round_trip(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "f.json"
            cards = [Card(headword="a", id="a"), Card(headword="b", id="b")]
            links = [Link(a_id="a", b_id="b", type="custom")]
            write_cards(p, serialise_cards(cards, links))
            _cards, loaded_links = load_flashcards(p)
            self.assertEqual(loaded_links[0].type, "custom")


class StoreLinkTests(unittest.TestCase):
    def _store(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        store = FlashcardStore(Path(tmp.name) / "f.json")
        self.addCleanup(store.shutdown)
        store.cards = [
            Card(headword="a", id="a"),
            Card(headword="b", id="b"),
            Card(headword="c", id="c"),
        ]
        return store

    def test_set_links_for_adds_links(self):
        store = self._store()
        store.set_links_for("a", [Link("a", "b", "synonym"),
                                  Link("a", "c", "related")])
        store.shutdown()
        self.assertEqual(len(store.links), 2)
        self.assertEqual({l.b_id for l in store.links}, {"b", "c"})

    def test_links_for_returns_links_touching_card(self):
        store = self._store()
        store.set_links_for("a", [Link("a", "b", "synonym")])
        self.assertEqual(len(store.links_for("a")), 1)
        self.assertEqual(len(store.links_for("b")), 1)  # symmetric
        self.assertEqual(len(store.links_for("c")), 0)

    def test_set_links_for_replaces_only_that_cards_links(self):
        store = self._store()
        store.set_links_for("a", [Link("a", "b", "synonym")])
        store.set_links_for("c", [Link("c", "b", "related")])
        # Replacing a's links must not remove c-b.
        store.set_links_for("a", [Link("a", "c", "antonym")])
        types = {(min(l.a_id, l.b_id), max(l.a_id, l.b_id)): l.type
                 for l in store.links}
        self.assertEqual(types[("a", "c")], "antonym")
        self.assertEqual(types[("b", "c")], "related")
        self.assertNotIn(("a", "b"), types)  # a-b was dropped

    def test_set_links_for_dedups_symmetric_pairs(self):
        store = self._store()
        store.set_links_for("a", [Link("a", "b", "synonym"),
                                  Link("b", "a", "synonym")])
        self.assertEqual(len(store.links), 1)

    def test_set_links_for_persists(self):
        store = self._store()
        store.set_links_for("a", [Link("a", "b", "synonym")])
        store.shutdown()
        _cards, links = load_flashcards(store.filepath)
        self.assertEqual(len(links), 1)

    def test_cards_changed_emitted_on_set_links(self):
        store = self._store()
        fired = []
        store.cards_changed.connect(lambda: fired.append(True))
        store.set_links_for("a", [Link("a", "b", "synonym")])
        self.assertEqual(fired, [True])
