import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from split_translator.main_window import TranslationTool


class FocusOwnNotationTests(unittest.TestCase):
    """Ctrl+P (focus_own_notation) brings the flashcard editor on screen and puts
    the caret in Own notation. Driven as an unbound method against a lightweight
    carrier (no WebEngine window)."""

    def _carrier(self, floating: bool = False):
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
                focus_own_notation=lambda: calls.append("focus")
            ),
        )
        return carrier, dock, calls

    def test_shows_the_editor_and_focuses_the_field(self):
        carrier, dock, calls = self._carrier()
        TranslationTool.focus_own_notation(carrier)
        self.assertTrue(dock.shown)
        self.assertEqual(calls, ["focus"])

    def test_leaves_a_floating_editor_floating(self):
        # Unlike Ctrl+N, this is a jump to a field, not a reset of where the
        # editor lives: docking stays with Alt+D and Ctrl+Shift+F.
        carrier, dock, _ = self._carrier(floating=True)
        TranslationTool.focus_own_notation(carrier)
        self.assertTrue(dock.floating)


if __name__ == "__main__":
    unittest.main()
