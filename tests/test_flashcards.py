import tempfile
import unittest
from pathlib import Path

from split_translator.flashcards import (
    Card,
    FlashcardStore,
    Sense,
    headword_forms,
    load_cards,
    redact_card_definitions,
    redact_headword,
    serialise_cards,
    write_cards,
)


class SenseTests(unittest.TestCase):
    def test_round_trip(self):
        sense = Sense(pos="n", polish="adres", english="the details of a place")
        self.assertEqual(Sense.from_dict(sense.to_dict()), sense)

    def test_is_empty(self):
        self.assertTrue(Sense().is_empty)
        self.assertTrue(Sense(pos="n").is_empty)
        self.assertFalse(Sense(polish="adres").is_empty)
        self.assertFalse(Sense(english="a place").is_empty)
        self.assertFalse(Sense(examples=["She lives at that address."]).is_empty)
        self.assertTrue(Sense(examples=["  "]).is_empty)

    def test_round_trip_with_examples(self):
        sense = Sense(
            pos="n",
            polish="adres",
            english="the details of a place",
            examples=["She lives at that address.", "Send it to my address."],
        )
        restored = Sense.from_dict(sense.to_dict())
        self.assertEqual(restored, sense)
        self.assertEqual(restored.examples, sense.examples)

    def test_from_dict_defaults_examples_empty(self):
        sense = Sense.from_dict({"pos": "n", "polish": "adres", "english": "a place"})
        self.assertEqual(sense.examples, [])


class CardTests(unittest.TestCase):
    def test_round_trip_preserves_fields(self):
        card = Card(
            headword="address",
            ipa_uk="/əˈdres/",
            audio_uk_url="https://example.test/a.mp3",
            senses=[Sense(pos="n", polish="adres", english="a place")],
        )
        restored = Card.from_dict(card.to_dict())
        self.assertEqual(restored, card)

    def test_optional_fields_default_none(self):
        card = Card(headword="dog")
        self.assertIsNone(card.spelling_uk)
        self.assertIsNone(card.audio_uk_url)
        self.assertEqual(card.senses, [])

    def test_starred_defaults_false_and_round_trips(self):
        self.assertFalse(Card(headword="dog").starred)
        card = Card(headword="dog", starred=True)
        self.assertTrue(Card.from_dict(card.to_dict()).starred)

    def test_starred_defaults_false_for_old_cards(self):
        card = Card.from_dict({"headword": "dog"})
        self.assertFalse(card.starred)

    def test_printed_defaults_false_and_round_trips(self):
        self.assertFalse(Card(headword="dog").printed)
        card = Card(headword="dog", printed=True)
        self.assertTrue(Card.from_dict(card.to_dict()).printed)

    def test_printed_defaults_false_for_old_cards(self):
        card = Card.from_dict({"headword": "dog"})
        self.assertFalse(card.printed)

    def test_round_trip_preserves_tags(self):
        card = Card(headword="address", tags=["book:dracula", "noun"])
        restored = Card.from_dict(card.to_dict())
        self.assertEqual(restored.tags, ["book:dracula", "noun"])
        self.assertEqual(restored, card)

    def test_tags_default_to_an_empty_list(self):
        self.assertEqual(Card(headword="dog").tags, [])
        self.assertEqual(Card.from_dict({"headword": "dog"}).tags, [])

    def test_from_dict_cleans_and_dedupes_tags(self):
        card = Card.from_dict(
            {"headword": "dog", "tags": [" Gothic ", "gothic", None]}
        )
        self.assertEqual(card.tags, ["gothic"])

    def test_tags_are_normalised_on_construction(self):
        # Not just on the from_dict path: the saved-cards filter compares stored
        # tags raw, so every card must carry them canonical however it was built.
        card = Card(headword="dog", tags=[" Gothic ", "gothic", "PHRASAL  verb"])
        self.assertEqual(card.tags, ["gothic", "phrasal verb"])

    def test_a_malformed_tags_value_on_construction_gives_no_tags(self):
        self.assertEqual(Card(headword="dog", tags="gothic").tags, [])

    def test_from_dict_tolerates_a_malformed_tags_value(self):
        card = Card.from_dict({"headword": "dog", "tags": "gothic"})
        self.assertEqual(card.tags, [])

    def test_serialise_reports_schema_version_4(self):
        self.assertEqual(serialise_cards([])["version"], 4)


class StorageTests(unittest.TestCase):
    def test_load_missing_returns_empty(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(load_cards(Path(d) / "none.json"), [])

    def test_load_malformed_returns_empty(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "bad.json"
            p.write_text("{ not valid json", encoding="utf-8")
            self.assertEqual(load_cards(p), [])

    def test_write_then_load_round_trip(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "cards.json"
            cards = [
                Card(
                    headword="address",
                    senses=[Sense(pos="n", polish="adres", english="a place")],
                )
            ]
            write_cards(p, serialise_cards(cards))
            loaded = load_cards(p)
            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0].headword, "address")
            self.assertEqual(loaded[0].senses[0].polish, "adres")

    def test_serialise_has_version(self):
        self.assertEqual(serialise_cards([])["version"], 4)


class StoreUpdateTests(unittest.TestCase):
    def _store(self):
        tmp = tempfile.TemporaryDirectory()
        store = FlashcardStore(Path(tmp.name) / "cards.json")
        self.addCleanup(tmp.cleanup)
        self.addCleanup(store.shutdown)
        return store

    def test_update_card_replaces_in_place(self):
        store = self._store()
        store.cards = [
            Card(headword="address", id="a", senses=[Sense(polish="adres")]),
            Card(headword="receive", id="b"),
        ]
        edited = Card(headword="address", id="a", senses=[Sense(polish="adres2")])
        self.assertTrue(store.update_card(edited))
        self.assertEqual(len(store.cards), 2)  # no duplicate added
        self.assertEqual(store.cards[0].senses[0].polish, "adres2")

    def test_update_card_keeps_position(self):
        store = self._store()
        store.cards = [Card(headword="a", id="a"), Card(headword="b", id="b")]
        store.update_card(Card(headword="b-edited", id="b"))
        # The edited card stays where it was, not moved to the top.
        self.assertEqual([c.headword for c in store.cards], ["a", "b-edited"])

    def test_update_card_returns_false_when_id_missing(self):
        store = self._store()
        store.cards = [Card(headword="a", id="a")]
        self.assertFalse(store.update_card(Card(headword="x", id="zzz")))
        self.assertEqual(len(store.cards), 1)

    def test_set_printed_flags_matching_cards(self):
        store = self._store()
        store.cards = [Card(headword="a", id="a"), Card(headword="b", id="b")]
        self.assertTrue(store.set_printed(["a"], True))
        self.assertTrue(store.cards[0].printed)
        self.assertFalse(store.cards[1].printed)

    def test_set_printed_ignores_unknown_ids(self):
        store = self._store()
        store.cards = [Card(headword="a", id="a")]
        self.assertFalse(store.set_printed(["zzz"], True))

    def test_set_printed_noop_returns_false(self):
        store = self._store()
        store.cards = [Card(headword="a", id="a", printed=True)]
        self.assertFalse(store.set_printed(["a"], True))

    def test_set_printed_can_clear(self):
        store = self._store()
        store.cards = [Card(headword="a", id="a", printed=True)]
        self.assertTrue(store.set_printed(["a"], False))
        self.assertFalse(store.cards[0].printed)

    def test_delete_card_removes_only_that_card(self):
        store = self._store()
        store.cards = [
            Card(headword="a", id="a"),
            Card(headword="b", id="b"),
            Card(headword="c", id="c"),
        ]
        self.assertTrue(store.delete_card("b"))
        self.assertEqual([c.headword for c in store.cards], ["a", "c"])

    def test_delete_card_returns_false_when_id_missing(self):
        store = self._store()
        store.cards = [Card(headword="a", id="a")]
        fired = []
        store.cards_changed.connect(lambda: fired.append(True))
        self.assertFalse(store.delete_card("zzz"))
        self.assertEqual(len(store.cards), 1)
        self.assertEqual(fired, [])  # no write, no refresh

    def test_delete_card_reaches_the_file(self):
        store = self._store()
        store.cards = [Card(headword="a", id="a"), Card(headword="b", id="b")]
        store.delete_card("a")
        store.shutdown()
        self.assertEqual([c.headword for c in load_cards(store.filepath)], ["b"])


class HeadwordFormsTests(unittest.TestCase):
    def test_collects_headword_and_spellings_longest_first(self):
        card = Card(headword="color", id="c", spelling_uk="colour")
        self.assertEqual(headword_forms(card), ["colour", "color"])

    def test_lowercases_and_dedups_and_drops_empty(self):
        card = Card(headword="Cat", id="c", spelling_uk="cat", spelling_us=None)
        self.assertEqual(headword_forms(card), ["cat"])


class RedactHeadwordTests(unittest.TestCase):
    def test_exact_word_becomes_token(self):
        self.assertEqual(redact_headword("a cat sits", ["cat"]), "a {{word}} sits")

    def test_case_insensitive(self):
        self.assertEqual(redact_headword("Cat naps", ["cat"]), "{{word}} naps")

    def test_keeps_short_inflection_suffix(self):
        self.assertEqual(redact_headword("two cats", ["cat"]), "two {{word}}s")
        self.assertEqual(redact_headword("abandoned it", ["abandon"]),
                         "{{word}}ed it")

    def test_does_not_match_inside_a_longer_word(self):
        # "egory" is not an inflection suffix, so "category" is left intact.
        self.assertEqual(redact_headword("a category", ["cat"]), "a category")

    def test_spelling_variant_matches(self):
        forms = ["colour", "color"]
        self.assertEqual(redact_headword("the color red", forms),
                         "the {{word}} red")

    def test_multiple_occurrences(self):
        self.assertEqual(redact_headword("cat and cat", ["cat"]),
                         "{{word}} and {{word}}")

    def test_idempotent_existing_token_preserved(self):
        once = redact_headword("a cat sits", ["cat"])
        self.assertEqual(redact_headword(once, ["cat"]), once)

    def test_empty_text_or_no_forms(self):
        self.assertEqual(redact_headword("", ["cat"]), "")
        self.assertEqual(redact_headword("a cat", []), "a cat")


class RedactCardDefinitionsTests(unittest.TestCase):
    def test_rewrites_each_sense_english_in_place(self):
        card = Card(headword="cat", id="c", senses=[
            Sense(english="a cat sleeps"),
            Sense(english="the cats ran"),
        ])
        redact_card_definitions(card)
        self.assertEqual(card.senses[0].english, "a {{word}} sleeps")
        self.assertEqual(card.senses[1].english, "the {{word}}s ran")

    def test_leaves_polish_and_examples_untouched(self):
        card = Card(headword="cat", id="c", senses=[
            Sense(polish="kot to cat", english="a cat",
                  examples=["the cat sat"]),
        ])
        redact_card_definitions(card)
        self.assertEqual(card.senses[0].polish, "kot to cat")
        self.assertEqual(card.senses[0].examples, ["the cat sat"])
        self.assertEqual(card.senses[0].english, "a {{word}}")


class StoreRedactionTests(unittest.TestCase):
    def _store(self):
        tmp = tempfile.TemporaryDirectory()
        store = FlashcardStore(Path(tmp.name) / "cards.json")
        self.addCleanup(tmp.cleanup)
        self.addCleanup(store.shutdown)
        return store

    def test_add_card_redacts_english_in_memory(self):
        store = self._store()
        store.add_card(Card(headword="cat", id="c",
                            senses=[Sense(english="a cat sleeps")]))
        self.assertEqual(store.cards[0].senses[0].english, "a {{word}} sleeps")

    def test_update_card_redacts_english(self):
        store = self._store()
        store.cards = [Card(headword="cat", id="c", senses=[Sense(english="x")])]
        store.update_card(Card(headword="cat", id="c",
                              senses=[Sense(english="the cats ran")]))
        self.assertEqual(store.cards[0].senses[0].english, "the {{word}}s ran")

    def test_add_card_persists_token_to_disk(self):
        store = self._store()
        store.add_card(Card(headword="cat", id="c",
                            senses=[Sense(english="a cat")]))
        store.shutdown()  # flush the background write
        raw = store.filepath.read_text(encoding="utf-8")
        self.assertIn("{{word}}", raw)

    def test_resaving_is_idempotent(self):
        store = self._store()
        store.add_card(Card(headword="cat", id="c",
                            senses=[Sense(english="a cat")]))
        store.update_card(store.cards[0])
        self.assertEqual(store.cards[0].senses[0].english, "a {{word}}")

    def test_save_card_with_links_redacts_english(self):
        store = self._store()
        store.save_card_with_links(
            Card(headword="cat", id="c", senses=[Sense(english="a cat naps")]),
            [],
        )
        self.assertEqual(store.cards[0].senses[0].english, "a {{word}} naps")


if __name__ == "__main__":
    unittest.main()
