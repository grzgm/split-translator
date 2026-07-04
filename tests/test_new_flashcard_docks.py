import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from split_translator.main_window import TranslationTool


class NewFlashcardDocksTests(unittest.TestCase):
    """Ctrl+N (new_flashcard) opens the flashcard editor in the docked state,
    even if it was left floating. Driven as an unbound method against a
    lightweight carrier (no WebEngine window)."""

    def _carrier(self, floating: bool):
        calls = []
        dock = SimpleNamespace(
            floating=floating,
            shown=False,
            setFloating=lambda value: setattr(dock, "floating", value),
            show=lambda: setattr(dock, "shown", True),
        )
        carrier = SimpleNamespace(
            flashcard_dock=dock,
            flashcard_panel=SimpleNamespace(
                new_card=lambda force=False: calls.append(("new_card", force))
                or True,
                autofill_book_example=lambda text: None,
            ),
            dictionary_panel=SimpleNamespace(
                grab_pronunciation=lambda: calls.append(("grab",))
            ),
            book_panel=SimpleNamespace(
                current_match_sentence=lambda cb: calls.append(("sentence",))
            ),
        )
        return carrier, dock

    def test_docks_a_floating_editor(self):
        carrier, dock = self._carrier(floating=True)
        TranslationTool.new_flashcard(carrier)
        self.assertFalse(dock.floating)
        self.assertTrue(dock.shown)

    def test_leaves_an_already_docked_editor_docked(self):
        carrier, dock = self._carrier(floating=False)
        TranslationTool.new_flashcard(carrier)
        self.assertFalse(dock.floating)
        self.assertTrue(dock.shown)


if __name__ == "__main__":
    unittest.main()
