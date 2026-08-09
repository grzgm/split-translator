import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from split_translator.main_window import TranslationTool


class HeadwordSourceTests(unittest.TestCase):
    """``on_pronunciation_grabbed`` decides which text fills the flashcard
    Headword: Cambridge's own headword (``.hw.dhw``, returned in the grab
    payload) is preferred over the raw search term, so a search that redirects
    to a lemma ("running" -> "run") records the canonical spelling. The method
    is driven as an unbound function against a lightweight carrier, avoiding the
    WebEngine-heavy real window."""

    def _carrier(self, search_text: str):
        captured = {}
        panel = SimpleNamespace(
            autofill_pronunciation=lambda *a, **kw: captured.update(kw)
        )
        return (
            SimpleNamespace(
                flashcard_dock=SimpleNamespace(isVisible=lambda: True),
                dictionary_panel=SimpleNamespace(
                    search_input=SimpleNamespace(text=lambda: search_text)
                ),
                flashcard_panel=panel,
            ),
            captured,
        )

    def _grab(self, carrier, data):
        TranslationTool.on_pronunciation_grabbed(carrier, data)

    def test_page_headword_wins_over_search_term(self):
        carrier, captured = self._carrier(search_text="running")
        self._grab(carrier, {"headword": "run", "ipa_uk": "/rn/"})
        self.assertEqual(captured["word"], "run")

    def test_falls_back_to_search_term_when_page_has_no_headword(self):
        carrier, captured = self._carrier(search_text="running")
        self._grab(carrier, {"headword": None, "ipa_uk": "/rn/"})
        self.assertEqual(captured["word"], "running")

    def test_blank_page_headword_falls_back_to_search_term(self):
        carrier, captured = self._carrier(search_text="running")
        self._grab(carrier, {"headword": "   ", "ipa_uk": "/rn/"})
        self.assertEqual(captured["word"], "running")

    def test_page_headword_is_trimmed(self):
        carrier, captured = self._carrier(search_text="running")
        self._grab(carrier, {"headword": "  run  ", "ipa_uk": "/rn/"})
        self.assertEqual(captured["word"], "run")

    def test_a_headword_only_payload_still_fills(self):
        # A page that yields only a headword (no IPA/audio/spelling) must still
        # pass the "any value present" gate and fill the Headword.
        carrier, captured = self._carrier(search_text="")
        self._grab(carrier, {"headword": "run"})
        self.assertEqual(captured["word"], "run")

    def test_no_fill_when_dock_hidden(self):
        carrier, captured = self._carrier(search_text="running")
        carrier.flashcard_dock.isVisible = lambda: False
        self._grab(carrier, {"headword": "run"})
        self.assertEqual(captured, {})  # autofill_pronunciation never called


class SearchSeedTests(unittest.TestCase):
    """Before any page has loaded, the Headword is seeded with the phrase the
    user searched, so a card is never left blank when the dictionary sites do
    not load. Both entry points seed it: a search (``on_word_searched``) and New
    from word (``new_flashcard``, which reads the search box). The methods are
    driven as unbound functions against a lightweight carrier."""

    def _search_carrier(self):
        seeded = []
        carrier = SimpleNamespace(
            flashcard_panel=SimpleNamespace(
                prepare_for_new_search=lambda: None,
                autofill_headword=seeded.append,
            ),
            history_panel=SimpleNamespace(add_to_history=lambda w: None),
            book_panel=SimpleNamespace(search=lambda w: None),
        )
        return carrier, seeded

    def _new_card_carrier(self, search_text, new_card_ok=True):
        seeded = []
        carrier = SimpleNamespace(
            flashcard_dock=SimpleNamespace(
                show=lambda: None, setFloating=lambda value: None
            ),
            flashcard_panel=SimpleNamespace(
                new_card=lambda force=False: new_card_ok,
                autofill_headword=seeded.append,
                autofill_book_example=lambda s, tag="": None,
            ),
            dictionary_panel=SimpleNamespace(
                search_input=SimpleNamespace(text=lambda: search_text),
                grab_pronunciation=lambda: None,
            ),
            book_panel=SimpleNamespace(current_match_sentence=lambda cb: cb("")),
            book_tag="",
        )
        return carrier, seeded

    def test_a_search_seeds_the_searched_phrase(self):
        carrier, seeded = self._search_carrier()
        TranslationTool.on_word_searched(carrier, "running")
        self.assertEqual(seeded, ["running"])

    def test_new_from_word_seeds_from_the_search_box(self):
        carrier, seeded = self._new_card_carrier("running")
        TranslationTool.new_flashcard(carrier)
        self.assertEqual(seeded, ["running"])

    def test_new_from_word_seeds_nothing_when_declined(self):
        # The user kept an in-progress card, so nothing touches the editor.
        carrier, seeded = self._new_card_carrier("running", new_card_ok=False)
        TranslationTool.new_flashcard(carrier)
        self.assertEqual(seeded, [])


if __name__ == "__main__":
    unittest.main()
