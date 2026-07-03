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


if __name__ == "__main__":
    unittest.main()
