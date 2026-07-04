import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel

from split_translator.shortcuts import ShortcutEntry
from split_translator.shortcuts_dialog import ShortcutsDialog

app = QApplication.instance() or QApplication([])


class ShortcutsDialogTests(unittest.TestCase):
    """ShortcutsDialog renders a read-only, group-headed list built from a
    registry of ShortcutEntry rows. Built offscreen; Esc/close is Qt-native and
    not unit-tested here."""

    def _entries(self):
        return [
            ShortcutEntry("Ctrl+L", "Focus the search box", "Dictionary",
                          handler="focus_search"),
            ShortcutEntry("Alt+1..9", "Play audio 1..9", "Dictionary",
                          note="Alt+1/Alt+2 play the card's audio when focused"),
            ShortcutEntry("Ctrl+N", "New card", "Flashcards",
                          handler="new_flashcard"),
        ]

    def _all_label_text(self, dialog):
        return [lbl.text() for lbl in dialog.findChildren(QLabel)]

    def test_shows_every_entry_keys_and_description(self):
        dialog = ShortcutsDialog(self._entries())
        texts = self._all_label_text(dialog)
        blob = "\n".join(texts)
        for keys in ("Ctrl+L", "Alt+1..9", "Ctrl+N"):
            self.assertIn(keys, blob)
        for desc in ("Focus the search box", "Play audio 1..9", "New card"):
            self.assertIn(desc, blob)

    def test_renders_a_heading_per_distinct_group(self):
        dialog = ShortcutsDialog(self._entries())
        blob = "\n".join(self._all_label_text(dialog))
        # Group order from the registry: Dictionary before Flashcards, and each
        # group name appears as a heading.
        self.assertIn("Dictionary", blob)
        self.assertIn("Flashcards", blob)
        self.assertLess(blob.index("Dictionary"), blob.index("Flashcards"))

    def test_shows_the_note_sub_line(self):
        dialog = ShortcutsDialog(self._entries())
        blob = "\n".join(self._all_label_text(dialog))
        self.assertIn("Alt+1/Alt+2 play the card's audio when focused", blob)

    def test_groups_absent_from_the_entries_are_not_shown(self):
        # Only groups present in the given entries render a heading; an unused
        # group from GROUP_ORDER (e.g. "Book", "View") must not appear.
        dialog = ShortcutsDialog(self._entries())
        blob = "\n".join(self._all_label_text(dialog))
        self.assertNotIn("Book", blob)
        self.assertNotIn("View", blob)


if __name__ == "__main__":
    unittest.main()
