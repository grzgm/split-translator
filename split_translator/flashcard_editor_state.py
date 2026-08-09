"""Pure-logic editor state for the flashcard panel.

One small object answers two questions the editor keeps asking: which mode is
the editor in (building a new card, or editing a saved one) and has the user
altered the current card since it was last loaded, cleared or saved. No Qt
import, so it unit-tests headless like page_mapper and graph_layout. The panel
holds exactly one instance and every mode/altered decision reads it."""

from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass
class EditorState:
    """The editor's mode and altered baseline.

    mode is "new" while building a fresh card and "editing" while a saved card
    is loaded. loaded_card_id and loaded_created_at carry the saved card's id
    and original creation time so Save updates it in place and keeps its
    timestamp. altered is True once the user changes anything since the last
    load, clear or save; programmatic fills never set it.

    altered is a property rather than a plain field so every change to it runs
    through one place. Setting it fires on_altered_changed, but only when the
    flag actually flips, so a listener hears one notification per transition and
    not one per keystroke. That is what lets the panel announce "this card has
    unsaved edits" without every writer here having to remember to.

    printed_flag_altered is altered again, one level down, for the card's
    printed flag: True once the user has changed that flag by hand since the
    same baseline. It is needed because editing anything that appears on the
    printed card clears the flag by itself (the paper copy stops matching the
    card the moment it changes), and that automatic clear must not undo a
    deliberate choice."""

    mode: str = "new"
    loaded_card_id: str | None = None
    loaded_created_at: str | None = None
    #: True once the user has set the printed flag by hand for the card now in
    #: the editor. Cleared by to_new and to_editing, so every load, clear and
    #: save starts from a fresh baseline, exactly like altered.
    printed_flag_altered: bool = False
    #: Called with the new value whenever altered flips. Stays a plain callable
    #: rather than a Qt signal so this module keeps its no-Qt, headless-testable
    #: character; the panel adapts it to a signal.
    on_altered_changed: Callable[[bool], None] | None = None
    _altered: bool = field(default=False, repr=False)

    @property
    def altered(self) -> bool:
        return self._altered

    @altered.setter
    def altered(self, value: bool) -> None:
        value = bool(value)
        if value == self._altered:
            return
        self._altered = value
        if self.on_altered_changed is not None:
            self.on_altered_changed(value)

    @property
    def is_new(self) -> bool:
        return self.mode == "new"

    @property
    def is_editing(self) -> bool:
        return self.mode == "editing"

    def to_new(self) -> None:
        """Reset to building a fresh, unaltered card."""
        self.mode = "new"
        self.loaded_card_id = None
        self.loaded_created_at = None
        self.altered = False
        self.printed_flag_altered = False

    def to_editing(self, card_id: str, created_at: str | None) -> None:
        """Enter editing a saved card. A freshly loaded card is a clean
        baseline, so altered is cleared."""
        self.mode = "editing"
        self.loaded_card_id = card_id
        self.loaded_created_at = created_at
        self.altered = False
        self.printed_flag_altered = False

    def mark_altered(self) -> None:
        """Record a genuine user edit."""
        self.altered = True

    def mark_printed_flag_altered(self) -> None:
        """Record that the user set the printed flag by hand."""
        self.printed_flag_altered = True
