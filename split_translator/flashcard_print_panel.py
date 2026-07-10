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
        # Every non-loaded row is a print checkbox, unchecked by default. (The
        # loaded row is handled by the base, which keeps it visually marked; make
        # it checkable here too so the card being edited can also be printed.)
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        if item.checkState() not in (Qt.CheckState.Checked, Qt.CheckState.Unchecked):
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
