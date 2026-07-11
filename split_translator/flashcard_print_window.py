"""The Print window: a fixed, non-dockable top-level window pairing the print
selection editor (left) with the print preview (right). Opened from the main
window's View menu (Ctrl+Shift+P). It follows the FlashcardGraphWindow pattern:
a plain QWidget top-level window given the shared store."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QSplitter, QVBoxLayout, QWidget

from .flashcard_print_panel import FlashcardPrintPanel
from .flashcard_print_view import PrintView
from .flashcards import FlashcardStore


class FlashcardPrintWindow(QWidget):
    """Pick cards on the left, preview and print on the right."""

    def __init__(self, store: FlashcardStore, parent=None):
        super().__init__(parent)
        self.store = store
        self.setWindowTitle("Print Flashcards")
        self.resize(1200, 800)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        self.panel = FlashcardPrintPanel(store)
        self.print_view = PrintView()
        splitter.addWidget(self.panel)
        splitter.addWidget(self.print_view)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([440, 760])
        outer.addWidget(splitter)

        self.panel.selection_changed.connect(self.refresh_preview)
        # A card edited and saved here (or elsewhere) refreshes the preview and
        # keeps a deleted/renamed card out of it.
        self.store.cards_changed.connect(self.refresh_preview)

    def refresh_preview(self) -> None:
        self.print_view.set_cards(self.panel.selected_cards())
