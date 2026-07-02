"""Pure-logic editor state for the flashcard panel.

One small object answers two questions the editor keeps asking: which mode is
the editor in (building a new card, or editing a saved one) and has the user
altered the current card since it was last loaded, cleared or saved. No Qt
import, so it unit-tests headless like page_mapper and graph_layout. The panel
holds exactly one instance and every mode/altered decision reads it."""

from dataclasses import dataclass


@dataclass
class EditorState:
    """The editor's mode and altered baseline.

    mode is "new" while building a fresh card and "editing" while a saved card
    is loaded. loaded_card_id and loaded_created_at carry the saved card's id
    and original creation time so Save updates it in place and keeps its
    timestamp. altered is True once the user changes anything since the last
    load, clear or save; programmatic fills never set it."""

    mode: str = "new"
    loaded_card_id: str | None = None
    loaded_created_at: str | None = None
    altered: bool = False

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

    def to_editing(self, card_id: str, created_at: str | None) -> None:
        """Enter editing a saved card. A freshly loaded card is a clean
        baseline, so altered is cleared."""
        self.mode = "editing"
        self.loaded_card_id = card_id
        self.loaded_created_at = created_at
        self.altered = False

    def mark_altered(self) -> None:
        """Record a genuine user edit."""
        self.altered = True
