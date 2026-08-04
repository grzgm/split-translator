import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from split_translator.main_window import TranslationTool


class ToggleFlashcardDocksTests(unittest.TestCase):
    """Ctrl+Shift+F (toggle_flashcard) opens the flashcard editor docked, even
    if it was left floating, so it comes back where it starts and where Ctrl+N
    puts it. Driven as an unbound method against a lightweight carrier (no
    WebEngine window), as in test_new_flashcard_docks."""

    def _carrier(self, visible: bool, floating: bool = False):
        calls = []
        dock = SimpleNamespace(
            visible=visible,
            floating=floating,
            isVisible=lambda: dock.visible,
            setFloating=lambda value: setattr(dock, "floating", value),
            show=lambda: setattr(dock, "visible", True),
            hide=lambda: setattr(dock, "visible", False),
        )
        carrier = SimpleNamespace(
            flashcard_dock=dock,
            dictionary_panel=SimpleNamespace(
                grab_pronunciation=lambda: calls.append(("grab",))
            ),
        )
        return carrier, dock, calls

    def test_docks_a_floating_editor_when_showing_it(self):
        carrier, dock, calls = self._carrier(visible=False, floating=True)
        TranslationTool.toggle_flashcard(carrier)
        self.assertTrue(dock.visible)
        self.assertFalse(dock.floating)
        # Showing still grabs the loaded page for the auto-fill.
        self.assertEqual(calls, [("grab",)])

    def test_leaves_an_already_docked_editor_docked(self):
        carrier, dock, _ = self._carrier(visible=False, floating=False)
        TranslationTool.toggle_flashcard(carrier)
        self.assertTrue(dock.visible)
        self.assertFalse(dock.floating)

    def test_hiding_a_floating_editor_leaves_it_floating(self):
        # Hiding is the other half of the toggle and touches neither the float
        # state nor the page: the next show is what re-docks it.
        carrier, dock, calls = self._carrier(visible=True, floating=True)
        TranslationTool.toggle_flashcard(carrier)
        self.assertFalse(dock.visible)
        self.assertTrue(dock.floating)
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
