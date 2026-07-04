import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QWidget

from split_translator.main_window import TranslationTool
from split_translator.shortcuts import SHORTCUTS

app = QApplication.instance() or QApplication([])


class ShortcutBindingTests(unittest.TestCase):
    """setup_shortcuts drives the real bindings off the registry. These tests
    exercise the two pieces that do not need the (WebEngine-heavy) main window:
    the dotted-handler resolver, and the binding builder run against a stub."""

    def test_resolve_handler_walks_dotted_paths(self):
        target = lambda: None
        carrier = SimpleNamespace(
            focus_search=lambda: "top",
            book_panel=SimpleNamespace(go_to_previous=target),
        )
        # Bare name resolves to the method on the carrier.
        self.assertIs(
            TranslationTool._resolve_handler(carrier, "focus_search"),
            carrier.focus_search,
        )
        # Dotted name walks attributes.
        self.assertIs(
            TranslationTool._resolve_handler(carrier, "book_panel.go_to_previous"),
            target,
        )

    def test_build_registry_shortcuts_creates_one_per_handler_entry(self):
        # A real QWidget parent so QShortcut construction is valid, but no
        # WebEngine. Give it stub attributes for every handler the registry
        # names so the connect() calls resolve.
        parent = QWidget()

        handlers = {
            e.handler for e in SHORTCUTS if e.handler and "." not in e.handler
        }
        for name in handlers:
            setattr(parent, name, lambda: None)
        parent.book_panel = SimpleNamespace(go_to_previous=lambda: None)
        parent.flashcard_panel = SimpleNamespace(save_card=lambda: None)

        created = TranslationTool._build_registry_shortcuts(parent)

        expected = {e.keys for e in SHORTCUTS if e.handler is not None}
        got = {sc.key().toString() for sc in created}
        self.assertEqual(got, expected)

    def test_display_only_entries_get_no_shortcut(self):
        parent = QWidget()
        handlers = {
            e.handler for e in SHORTCUTS if e.handler and "." not in e.handler
        }
        for name in handlers:
            setattr(parent, name, lambda: None)
        parent.book_panel = SimpleNamespace(go_to_previous=lambda: None)
        parent.flashcard_panel = SimpleNamespace(save_card=lambda: None)

        created = TranslationTool._build_registry_shortcuts(parent)
        got = {sc.key().toString() for sc in created}
        # The two View-menu shortcuts are display-only: no QShortcut for them.
        self.assertNotIn("Ctrl+Shift+F", got)
        self.assertNotIn("Ctrl+Shift+A", got)


if __name__ == "__main__":
    unittest.main()
