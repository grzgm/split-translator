"""The single source of truth for the app's keyboard shortcuts.

``main_window.setup_shortcuts`` iterates ``SHORTCUTS`` to create the real
bindings (every entry whose ``handler`` is set), and the Ctrl+/ overlay
(``shortcuts_dialog.ShortcutsDialog``) renders the same list. Adding a shortcut
is one entry here, so the bindings and the reference can never drift.

Entries with no ``handler`` are display-only: they appear in the overlay but are
wired elsewhere (the two View-menu actions) or are a range (Alt+1..9), neither of
which is a plain single ``QShortcut``.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ShortcutEntry:
    keys: str
    description: str
    group: str
    handler: str | None = None
    note: str | None = None


# Groups are rendered in this order in the overlay.
GROUP_ORDER = ["Dictionary", "Book", "Flashcards", "View"]

SHORTCUTS = [
    # Dictionary
    ShortcutEntry("Ctrl+L", "Focus the search box (and select all)", "Dictionary",
                  handler="focus_search"),
    ShortcutEntry("F6", "Focus the search box", "Dictionary",
                  handler="focus_search"),
    ShortcutEntry("Ctrl+T", "Copy contextual-translation prompt", "Dictionary",
                  handler="copy_translation_prompt"),
    ShortcutEntry("Alt+1..9", "Play Cambridge audio 1..9", "Dictionary",
                  note="Alt+1/Alt+2 play the card's UK/US audio when the "
                       "flashcard editor is focused"),
    # Book
    ShortcutEntry("F3", "Next book match, or focus search when the search box "
                  "is focused", "Book",
                  handler="handle_search_and_pdf_navigation"),
    ShortcutEntry("Ctrl+F", "Next book match, or focus search when the search "
                  "box is focused", "Book",
                  handler="handle_search_and_pdf_navigation"),
    ShortcutEntry("Shift+F3", "Previous book match", "Book",
                  handler="book_panel.go_to_previous"),
    # Flashcards
    ShortcutEntry("Ctrl+N", "New card from the current word", "Flashcards",
                  handler="new_flashcard"),
    ShortcutEntry("Ctrl+S", "Save card", "Flashcards",
                  handler="flashcard_panel.save_card"),
    ShortcutEntry("Alt+P", "Add selection to Polish (active sense)", "Flashcards",
                  handler="capture_to_polish"),
    ShortcutEntry("Alt+E", "Add selection to English (active sense)", "Flashcards",
                  handler="capture_to_english"),
    ShortcutEntry("Alt+X", "Add selection to Example (active sense)", "Flashcards",
                  handler="capture_to_example"),
    ShortcutEntry("Alt+D", "Toggle the editor between floating and docked "
                  "(when the editor is focused)", "Flashcards",
                  handler="toggle_flashcard_dock"),
    # View
    ShortcutEntry("Ctrl+Shift+F", "Flashcard editor (View menu)", "View"),
    ShortcutEntry("Ctrl+Shift+A", "Sync editor (View menu)", "View"),
    ShortcutEntry("Ctrl+/", "Show this keyboard-shortcuts list", "View",
                  handler="show_shortcuts"),
]
