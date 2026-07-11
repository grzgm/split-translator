import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from split_translator.shortcuts import SHORTCUTS, GROUP_ORDER, ShortcutEntry


# Map the first segment of a dotted handler to the class that owns the method,
# so a handler name can be checked statically without building the (WebEngine)
# main window. A bare handler (no dot) must be a TranslationTool method.
def _resolve_handler(handler: str) -> bool:
    from split_translator.main_window import TranslationTool
    from split_translator.book_panel import BookPanel
    from split_translator.flashcard_panel import FlashcardPanel

    owners = {
        "book_panel": BookPanel,
        "flashcard_panel": FlashcardPanel,
    }
    if "." not in handler:
        return hasattr(TranslationTool, handler)
    head, tail = handler.split(".", 1)
    owner = owners.get(head)
    return owner is not None and hasattr(owner, tail)


class ShortcutsRegistryTests(unittest.TestCase):
    """SHORTCUTS is the single source of truth for the app's keyboard shortcuts.
    These pure tests guard the invariants the binding builder and the overlay
    both rely on, without constructing the (WebEngine-heavy) main window."""

    def test_every_entry_has_keys_description_and_group(self):
        for e in SHORTCUTS:
            self.assertTrue(e.keys.strip(), f"empty keys: {e}")
            self.assertTrue(e.description.strip(), f"empty description: {e}")
            self.assertTrue(e.group.strip(), f"empty group: {e}")

    def test_every_group_is_in_group_order(self):
        for e in SHORTCUTS:
            self.assertIn(e.group, GROUP_ORDER, f"unknown group: {e.group}")

    def test_every_handler_resolves(self):
        # A typo in a handler name would silently create a dead shortcut; this
        # catches it. Bare names must be TranslationTool methods; dotted names
        # resolve against the owning child-panel class.
        for e in SHORTCUTS:
            if e.handler is not None:
                self.assertTrue(
                    _resolve_handler(e.handler),
                    f"handler does not resolve: {e.handler}",
                )

    def test_no_duplicate_key_sequences_among_real_bindings(self):
        # Only handler-bearing entries become real QShortcuts; two of those with
        # the same sequence would make the binding ambiguous. Display-only rows
        # (no handler) are exempt. Note F6/Ctrl+L share a handler but differ in
        # sequence, so they are not duplicates.
        seqs = [e.keys for e in SHORTCUTS if e.handler is not None]
        self.assertEqual(len(seqs), len(set(seqs)), f"duplicate sequences: {seqs}")

    def test_ctrl_slash_is_a_real_binding(self):
        entry = next((e for e in SHORTCUTS if e.keys == "Ctrl+/"), None)
        self.assertIsNotNone(entry)
        self.assertEqual(entry.handler, "show_shortcuts")

    def test_view_menu_shortcuts_are_display_only(self):
        # Ctrl+Shift+F / Ctrl+Shift+A live on their View-menu QActions; they must
        # NOT get a QShortcut here, so their handler must be None.
        for keys in ("Ctrl+Shift+F", "Ctrl+Shift+A", "Ctrl+Shift+P"):
            entry = next((e for e in SHORTCUTS if e.keys == keys), None)
            self.assertIsNotNone(entry, f"missing overlay entry: {keys}")
            self.assertIsNone(entry.handler, f"{keys} must be display-only")


if __name__ == "__main__":
    unittest.main()
