"""The Print window: a fixed, non-dockable top-level window pairing the print
selection editor (left) with the print preview (middle) and the print sidebar
(right). Opened from the main window's View menu (Ctrl+Shift+P). It follows the
FlashcardGraphWindow pattern: a plain QWidget top-level window given the shared
store."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QSplitter, QVBoxLayout, QWidget

from .flashcard_print_choices import PrintChoices
from .flashcard_print_panel import FlashcardPrintPanel
from .flashcard_print_sidebar import PrintSidebar
from .flashcard_print_view import PrintView
from .flashcards import FlashcardStore


class FlashcardPrintWindow(QWidget):
    """Pick cards on the left, preview in the middle, tune and print on the right."""

    def __init__(self, store: FlashcardStore, parent=None):
        super().__init__(parent)
        self.store = store
        self.setWindowTitle("Print Flashcards")
        self.resize(1500, 800)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        # Which cards have a hand-picked example set. Session-scoped: it is built
        # here and dies with the window, so nothing is persisted.
        self.choices = PrintChoices()

        self.panel = FlashcardPrintPanel(store)
        self.print_view = PrintView()
        self.sidebar = PrintSidebar(self.choices)
        splitter.addWidget(self.panel)
        splitter.addWidget(self.print_view)
        splitter.addWidget(self.sidebar)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        splitter.setSizes([440, 760, 300])
        outer.addWidget(splitter)

        self.panel.selection_changed.connect(self.refresh_preview)
        self.panel.selection_changed.connect(self._refresh_sidebar)
        # A card edited and saved here (or elsewhere) refreshes the preview,
        # keeps a deleted/renamed card out of it, and drops any hand-picked
        # example set whose card has changed under it.
        self.store.cards_changed.connect(self._on_cards_changed)
        self.panel.toggle_printed_requested.connect(self._on_toggle_printed)
        self.print_view.cards_printed.connect(self._on_cards_printed)
        # An external flag change (bulk toggle or auto-flag) must refresh the
        # panel's list icons and resync the loaded card's toggle, so a later Save
        # cannot revert the flag.
        self.store.cards_changed.connect(self.panel._refresh_saved_list)
        # The sidebar follows the card loaded in the editor, through a load, a
        # clear and a save alike.
        self.panel.loaded_card_changed.connect(self._refresh_sidebar)
        self.sidebar.choice_changed.connect(self._on_choice_changed)
        # Only the browser can measure a wrapped sentence, so the automatic
        # default reaches the sidebar this way.
        self.print_view.auto_fit_measured.connect(self.sidebar.set_auto_fit)
        # Clicking a card in the preview loads it, so the preview, the saved
        # list and the sidebar all follow one card. load_card brings the usual
        # unsaved-changes prompt with it, and declining cancels the load.
        self.print_view.card_clicked.connect(self._on_tile_clicked)
        self.sidebar.borders_toggled.connect(self.print_view.set_show_borders)
        self.sidebar.cut_lines_toggled.connect(self.print_view.set_print_cut_lines)
        self.sidebar.blank_headwords_toggled.connect(
            self.print_view.set_blank_headwords
        )
        self.sidebar.back_offset_changed.connect(self._on_back_offset_changed)
        self.sidebar.print_requested.connect(self.print_view.print_cards)

        # Push the sidebar's starting values into the view once, so the two sets
        # of defaults cannot drift apart.
        self.print_view.set_show_borders(self.sidebar.show_borders())
        self.print_view.set_print_cut_lines(self.sidebar.print_cut_lines())
        self.print_view.set_blank_headwords(self.sidebar.blank_headwords())
        self._on_back_offset_changed()
        self._refresh_sidebar()

    def refresh_preview(self) -> None:
        cards = self.panel.selected_cards()
        self.print_view.set_cards(cards)
        self.sidebar.set_selection_count(len(cards))

    def _loaded_card(self):
        """The card loaded in the editor, read from the store rather than from
        the editor fields, so the sidebar lists what is actually saved."""
        card_id = self.panel.state.loaded_card_id
        if not card_id:
            return None
        return next((c for c in self.store.cards if c.id == card_id), None)

    def _refresh_sidebar(self) -> None:
        card = self._loaded_card()
        in_selection = card is not None and card.id in set(self.panel.selected_ids())
        self.sidebar.set_card(card, in_selection)
        # Mark the same card in the preview, so the saved list, the editor, the
        # sidebar and the sheets all point at one card.
        self.print_view.set_selected_card(card.id if card is not None else None)

    def _on_choice_changed(self, _card_id: str) -> None:
        self.print_view.set_choices(self.choices.as_render_map())

    def _on_back_offset_changed(self) -> None:
        self.print_view.set_back_offsets(
            self.sidebar.back_offset(), self.sidebar.back_offset_x()
        )

    def _on_cards_changed(self) -> None:
        # An edit invalidates a hand-picked set, so the card goes back to the
        # automatic choice. This covers every edit route, since the store emits
        # for the dock and the graph window too.
        dropped = self.choices.drop_stale(self.store.cards)
        if dropped:
            self.print_view.set_choices(self.choices.as_render_map())
        # The stale measurement behind a dropped choice must go too, or the
        # sidebar keeps pre-ticking against the pre-edit example list until
        # the next debounced preview reload measures it again.
        for card_id in dropped:
            self.sidebar.drop_measurement(card_id)
        self.refresh_preview()
        self._refresh_sidebar()

    def _on_toggle_printed(self) -> None:
        ids = self.panel.selected_ids()
        if not ids:
            return
        by_id = {c.id: c for c in self.store.cards}
        all_printed = all(by_id[i].printed for i in ids if i in by_id)
        self.store.set_printed(ids, not all_printed)

    def _on_cards_printed(self, card_ids) -> None:
        self.store.set_printed(card_ids, True)

    def _on_tile_clicked(self, card_id: str) -> None:
        card = next((c for c in self.store.cards if c.id == card_id), None)
        if card is not None:
            self.panel.load_card(card)
