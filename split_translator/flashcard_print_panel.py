"""Left side of the Print window: the shared flashcard editor whose saved-list
checkboxes choose which cards to print. No dictionary/search wiring (the Print
window never connects those signals) and no card linking."""

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtWidgets import QListWidgetItem

from .flashcard_editor_base import FlashcardEditorBase
from .flashcards import Card


class FlashcardPrintPanel(FlashcardEditorBase):
    """Editor plus a print-selection set driven by the saved-list checkboxes.

    The set of chosen cards is kept in ``_selected_ids`` (by card id), which is
    the source of truth rather than the list widget: the saved list is rebuilt
    from scratch on every refresh (for example when a card is loaded for editing),
    so the ticks would otherwise be lost. Each rebuilt row restores its tick from
    this set, so loading a card leaves the print selection intact.

    Shift-clicking a checkbox ticks the whole range from the last plainly clicked
    row to the shift-clicked row (inclusive), so a run of cards can be selected at
    once. The Shift state and the pressed row are captured on the mouse press (via
    an event filter on the list viewport), because the modifier is not reliably
    readable from the later ``itemChanged`` signal.
    """

    selection_changed = Signal()

    def __init__(self, store, parent=None):
        # Initialised before super().__init__ because the base constructor calls
        # _refresh_saved_list -> _configure_saved_item, which reads these.
        self._selected_ids: set[str] = set()
        # Row index of the last row whose checkbox was clicked without Shift; the
        # anchor a following Shift-click extends the range from. None until a
        # first plain click.
        self._range_anchor_row: int | None = None
        # Captured on each list mouse press: whether Shift was held and which row
        # was pressed. Consumed by the next _on_saved_item_changed.
        self._pending_shift = False
        self._pending_press_row: int | None = None
        super().__init__(store, parent)
        # Watch the list viewport so a checkbox click's Shift state and target row
        # are known before the check state toggles.
        self.saved_list.viewport().installEventFilter(self)

    # --- event capture --------------------------------------------------

    def eventFilter(self, obj, event):
        if (
            obj is self.saved_list.viewport()
            and event.type() == QEvent.Type.MouseButtonPress
        ):
            self._pending_shift = bool(
                event.modifiers() & Qt.KeyboardModifier.ShiftModifier
            )
            item = self.saved_list.itemAt(event.position().toPoint())
            self._pending_press_row = (
                self.saved_list.row(item) if item is not None else None
            )
        return super().eventFilter(obj, event)

    # --- saved-list hooks -----------------------------------------------

    def _configure_saved_item(self, item: QListWidgetItem, card: Card) -> None:
        # Every row is a print checkbox. Both steps are needed for a box to
        # actually render: the ItemIsUserCheckable flag AND a value in the
        # CheckStateRole data role (a QListWidgetItem draws no indicator until its
        # check state has been set at least once). Restore the tick from the
        # persistent selection set so a list rebuild keeps the print selection.
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        card_id = item.data(Qt.ItemDataRole.UserRole)
        checked = card_id in self._selected_ids
        item.setCheckState(
            Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        )

    def _on_saved_item_changed(self, item: QListWidgetItem) -> None:
        # A genuine (non-programmatic) check-state change. Update the persistent
        # set, extend a Shift-click into a range, and announce the change once.
        self._sync_id_from_item(item)
        if self._pending_shift and self._range_anchor_row is not None:
            self._apply_shift_range(item)
        else:
            self._range_anchor_row = self.saved_list.row(item)
        self._pending_shift = False
        self._pending_press_row = None
        self.selection_changed.emit()

    def _loaded_row_is_checkable(self) -> bool:
        return True

    # --- selection state ------------------------------------------------

    def _sync_id_from_item(self, item: QListWidgetItem) -> None:
        card_id = item.data(Qt.ItemDataRole.UserRole)
        if item.checkState() == Qt.CheckState.Checked:
            self._selected_ids.add(card_id)
        else:
            self._selected_ids.discard(card_id)

    def _apply_shift_range(self, item: QListWidgetItem) -> None:
        """Tick every row between the anchor and this row (inclusive), matching
        this row's new state. Runs under the reentrancy guard so the batch of
        setCheckState calls does not re-enter this handler."""
        target_state = item.checkState()
        end = self.saved_list.row(item)
        start = self._range_anchor_row
        lo, hi = (start, end) if start <= end else (end, start)
        self._suppress_item_changed = True
        try:
            for row in range(lo, hi + 1):
                row_item = self.saved_list.item(row)
                if not (row_item.flags() & Qt.ItemFlag.ItemIsUserCheckable):
                    continue
                row_item.setCheckState(target_state)
                self._sync_id_from_item(row_item)
        finally:
            self._suppress_item_changed = False
        # The shift-clicked row becomes the new anchor for a subsequent range.
        self._range_anchor_row = end

    def selected_ids(self) -> list[str]:
        # Return the chosen ids in list (top-to-bottom) order, from the persistent
        # set filtered to rows still present, so a rebuilt or filtered list stays
        # consistent with what is stored.
        ids = []
        for i in range(self.saved_list.count()):
            item = self.saved_list.item(i)
            card_id = item.data(Qt.ItemDataRole.UserRole)
            if card_id in self._selected_ids:
                ids.append(card_id)
        return ids

    def selected_cards(self) -> list[Card]:
        wanted = self.selected_ids()
        by_id = {c.id: c for c in self.store.cards}
        return [by_id[i] for i in wanted if i in by_id]
