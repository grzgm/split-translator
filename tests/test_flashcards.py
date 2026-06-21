import tempfile
import unittest
from pathlib import Path

from split_translator.flashcards import (
    Card,
    Sense,
    load_cards,
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
        self.assertEqual(serialise_cards([])["version"], 1)


if __name__ == "__main__":
    unittest.main()
