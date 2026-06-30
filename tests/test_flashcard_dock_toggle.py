import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDockWidget, QMainWindow

from split_translator.flashcard_panel import FlashcardPanel
from split_translator.flashcards import FlashcardStore
from split_translator.main_window import TranslationTool

app = QApplication.instance() or QApplication([])


class FlashcardDockToggleTests(unittest.TestCase):
    """Alt+D flips the flashcard editor between floating and docked, but only
    while the editor has focus. The decision lives in
    ``TranslationTool.toggle_flashcard_dock``; here it is driven against a real
    dock and panel without building the whole (WebEngine-heavy) main window."""

    def _carrier(self, focused: bool):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        store = FlashcardStore(Path(tmp.name) / "cards.json")
        panel = FlashcardPanel(store)

        window = QMainWindow()
        self.addCleanup(window.close)
        dock = QDockWidget("Flashcard", window)
        dock.setWidget(panel)
        window.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)

        carrier = SimpleNamespace(flashcard_panel=panel, flashcard_dock=dock)
        # Force the focus gate's answer rather than fighting the offscreen
        # platform for real keyboard focus.
        carrier.flashcard_panel.has_focus = lambda: focused
        return carrier, dock

    def _toggle(self, carrier):
        TranslationTool.toggle_flashcard_dock(carrier)

    def test_docks_a_floating_editor_when_focused(self):
        carrier, dock = self._carrier(focused=True)
        dock.setFloating(True)
        self._toggle(carrier)
        self.assertFalse(dock.isFloating())

    def test_floats_a_docked_editor_when_focused(self):
        carrier, dock = self._carrier(focused=True)
        dock.setFloating(False)
        self._toggle(carrier)
        self.assertTrue(dock.isFloating())

    def test_does_nothing_without_focus(self):
        carrier, dock = self._carrier(focused=False)
        dock.setFloating(True)
        self._toggle(carrier)
        self.assertTrue(dock.isFloating())  # unchanged

        dock.setFloating(False)
        self._toggle(carrier)
        self.assertFalse(dock.isFloating())  # unchanged

    def test_restores_focus_so_the_next_alt_d_works(self):
        # Docking moves focus off the editor; without restoring it the focus gate
        # would block a second Alt+D. The toggle must hand focus back.
        carrier, dock = self._carrier(focused=True)
        calls = []
        carrier.flashcard_panel.focus_editor = lambda: calls.append(True)
        dock.setFloating(True)
        self._toggle(carrier)
        self.assertEqual(calls, [True])

    def test_no_focus_restore_without_focus(self):
        carrier, _dock = self._carrier(focused=False)
        calls = []
        carrier.flashcard_panel.focus_editor = lambda: calls.append(True)
        self._toggle(carrier)
        self.assertEqual(calls, [])  # gated out before any focus change


if __name__ == "__main__":
    unittest.main()
