"""Bridge between injected anchor-editor page clicks and Python.

Each editor book view registers one of these on its page over a QWebChannel.
Injected JavaScript calls `clicked(dataStid)` when the user clicks a paragraph;
this QObject re-emits it as a Qt signal the editor handles. Mirrors
`capture_bridge.CaptureBridge`."""

from PySide6.QtCore import QObject, Signal, Slot


class AnchorClickBridge(QObject):
    """Receives paragraph clicks from an editor book view and re-emits them."""

    block_clicked = Signal(str)  # the clicked data-stid

    @Slot(str)
    def clicked(self, block_id: str) -> None:
        self.block_clicked.emit(block_id)
