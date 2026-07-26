import tempfile
import unittest
from pathlib import Path

from split_translator.flashcards import (
    Card,
    FlashcardStore,
    Link,
    LINK_TYPES,
    LINKS_SCHEMA_VERSION,
    SCHEMA_VERSION,
    load_cards,
    load_links,
    serialise_cards,
    serialise_links,
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
    def test_serialise_cards_omits_links(self):
        cards = [Card(headword="a", id="a"), Card(headword="b", id="b")]
        data = serialise_cards(cards)
        self.assertEqual(data["version"], 3)
        self.assertEqual(SCHEMA_VERSION, 3)
        self.assertNotIn("links", data)

    def test_serialise_links_has_own_version(self):
        links = [Link(a_id="a", b_id="b", type="synonym")]
        data = serialise_links(links)
        self.assertEqual(data["version"], LINKS_SCHEMA_VERSION)
        self.assertEqual(data["links"], [{"a_id": "a", "b_id": "b",
                                          "type": "synonym"}])

    def test_round_trip_cards_and_links_across_two_files(self):
        with tempfile.TemporaryDirectory() as d:
            cards_p = Path(d) / "cards.json"
            links_p = Path(d) / "flashcard_links.json"
            cards = [Card(headword="a", id="a"), Card(headword="b", id="b")]
            links = [Link(a_id="a", b_id="b", type="related")]
            write_cards(cards_p, serialise_cards(cards))
            write_cards(links_p, serialise_links(links))
            loaded_cards = load_cards(cards_p)
            loaded_links = load_links(links_p, {c.id for c in loaded_cards})
            self.assertEqual(len(loaded_cards), 2)
            self.assertEqual(loaded_links, links)

    def test_missing_links_file_loads_empty(self):
        with tempfile.TemporaryDirectory() as d:
            cards_p = Path(d) / "cards.json"
            write_cards(cards_p, serialise_cards([Card(headword="a", id="a")]))
            cards = load_cards(cards_p)
            links = load_links(Path(d) / "flashcard_links.json",
                               {c.id for c in cards})
            self.assertEqual(len(cards), 1)
            self.assertEqual(links, [])

    def test_no_backfill_ignores_links_embedded_in_cards_file(self):
        # A legacy combined file still has a 'links' key. Those links must NOT be
        # read back: links come only from the separate links file.
        with tempfile.TemporaryDirectory() as d:
            import json
            cards_p = Path(d) / "cards.json"
            cards_p.write_text(
                json.dumps({
                    "version": 2,
                    "cards": [{"id": "a", "headword": "a"},
                              {"id": "b", "headword": "b"}],
                    "links": [{"a_id": "a", "b_id": "b", "type": "synonym"}],
                }),
                encoding="utf-8",
            )
            cards = load_cards(cards_p)
            links = load_links(Path(d) / "flashcard_links.json",
                               {c.id for c in cards})
            self.assertEqual(len(cards), 2)
            self.assertEqual(links, [])  # embedded links are not backfilled

    def test_dangling_links_pruned_on_load(self):
        with tempfile.TemporaryDirectory() as d:
            links_p = Path(d) / "flashcard_links.json"
            # Link references "gone", which is not among the valid ids.
            write_cards(links_p, serialise_links(
                [Link(a_id="a", b_id="gone", type="synonym")]))
            links = load_links(links_p, {"a"})
            self.assertEqual(links, [])

    def test_missing_files_return_empty(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(load_cards(Path(d) / "none.json"), [])
            self.assertEqual(load_links(Path(d) / "none.json", set()), [])

    def test_unknown_type_survives_round_trip(self):
        with tempfile.TemporaryDirectory() as d:
            links_p = Path(d) / "flashcard_links.json"
            write_cards(links_p, serialise_links(
                [Link(a_id="a", b_id="b", type="custom")]))
            loaded_links = load_links(links_p, {"a", "b"})
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

    def test_set_links_for_persists_to_separate_file(self):
        store = self._store()
        store.set_links_for("a", [Link("a", "b", "synonym")])
        store.shutdown()
        # Links land in the separate links file, not the cards file.
        self.assertNotEqual(store.links_filepath, store.filepath)
        links = load_links(store.links_filepath, {c.id for c in store.cards})
        self.assertEqual(len(links), 1)
        # The cards file must not carry a links key.
        import json
        raw = json.loads(store.filepath.read_text(encoding="utf-8"))
        self.assertNotIn("links", raw)

    def test_cards_changed_emitted_on_set_links(self):
        store = self._store()
        fired = []
        store.cards_changed.connect(lambda: fired.append(True))
        store.set_links_for("a", [Link("a", "b", "synonym")])
        self.assertEqual(fired, [True])

    def test_save_card_with_links_updates_card_and_links_in_one_emit(self):
        store = self._store()
        fired = []
        store.cards_changed.connect(lambda: fired.append(True))
        edited = Card(headword="a-edited", id="a")
        store.save_card_with_links(edited, [Link("a", "b", "synonym")])
        store.shutdown()
        self.assertEqual(len(fired), 1)  # one write, one refresh
        self.assertEqual(next(c for c in store.cards if c.id == "a").headword,
                         "a-edited")
        self.assertEqual(len(store.links_for("a")), 1)

    def test_save_card_with_links_inserts_a_new_card(self):
        store = self._store()
        new_card = Card(headword="d", id="d")
        store.save_card_with_links(new_card, [])
        store.shutdown()
        self.assertEqual(store.cards[0].id, "d")  # inserted at front

    def test_save_card_with_links_preserves_other_cards_links(self):
        store = self._store()
        store.set_links_for("c", [Link("c", "b", "related")])
        store.save_card_with_links(Card(headword="a", id="a"),
                                   [Link("a", "b", "synonym")])
        store.shutdown()
        keys = {(min(l.a_id, l.b_id), max(l.a_id, l.b_id)): l.type
                for l in store.links}
        self.assertEqual(keys[("b", "c")], "related")  # untouched
        self.assertEqual(keys[("a", "b")], "synonym")
