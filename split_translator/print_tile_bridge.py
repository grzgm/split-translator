"""Bridge between clicks on a print-preview card tile and Python.

The print view registers one of these on its page over a QWebChannel. Injected
JavaScript calls `clicked(cardId)` when the user clicks a card in the preview;
this QObject re-emits it as a Qt signal the print window turns into a card load.
Mirrors `anchor_click_bridge.AnchorClickBridge`."""

from PySide6.QtCore import QObject, Signal, Slot


class PrintTileBridge(QObject):
    """Receives card-tile clicks from the print preview and re-emits them."""

    tile_clicked = Signal(str)  # the clicked tile's data-card-id

    @Slot(str)
    def clicked(self, card_id: str) -> None:
        self.tile_clicked.emit(card_id)
