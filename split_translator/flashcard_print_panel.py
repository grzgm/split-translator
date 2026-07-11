"""Left side of the Print window: the shared flashcard editor whose saved-list
checkboxes choose which cards to print. No dictionary/search wiring (the Print
window never connects those signals) and no card linking."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QListWidgetItem

from .flashcard_editor_base import FlashcardEditorBase
from .flashcards import Card


class FlashcardPrintPanel(FlashcardEditorBase):
    """Editor plus a print-selection set driven by the saved-list checkboxes."""

    selection_changed = Signal()

    def _configure_saved_item(self, item: QListWidgetItem, card: Card) -> None:
        # Every row is a print checkbox, unchecked by default. Both steps are
        # needed for a box to actually render: the ItemIsUserCheckable flag AND a
        # value in the CheckStateRole data role. A QListWidgetItem draws no check
        # indicator until its check state has been set at least once, so set it
        # explicitly here (the list is rebuilt from scratch on every refresh, so
        # there is no prior tick on this item to preserve).
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(Qt.CheckState.Unchecked)

    def _on_saved_item_changed(self, item: QListWidgetItem) -> None:
        self.selection_changed.emit()

    def _loaded_row_is_checkable(self) -> bool:
        return True

    def selected_ids(self) -> list[str]:
        ids = []
        for i in range(self.saved_list.count()):
            item = self.saved_list.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                ids.append(item.data(Qt.ItemDataRole.UserRole))
        return ids

    def selected_cards(self) -> list[Card]:
        wanted = self.selected_ids()
        by_id = {c.id: c for c in self.store.cards}
        return [by_id[i] for i in wanted if i in by_id]
