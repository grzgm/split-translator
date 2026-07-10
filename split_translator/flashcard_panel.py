"""Flashcard editor: a dock-panel widget for building one card at a time.

FlashcardPanel is FlashcardEditorBase plus the tick-to-link controls: a
"Link as" category combo under the saved list, and the staging/persistence of
Link records alongside the edited card. See flashcard_editor_base for the
shared editor (card fields, senses, saved list, lifecycle)."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QWidget

from .flashcard_editor_base import FlashcardEditorBase, SenseRow, _mark_empty
from .flashcards import FlashcardStore, Link, LINK_TYPES

# Re-exported so existing imports keep working:
# `from split_translator.flashcard_panel import SenseRow` (tests) and
# `_mark_empty` (used only internally, kept importable for parity).
__all__ = ["FlashcardPanel", "SenseRow"]

# Placeholder used in staged links when the edited card has not been saved yet;
# replaced with the real card id at first Save (see _partner_id).
_NEW_CARD_ANCHOR = "__new__"


class FlashcardPanel(FlashcardEditorBase):
    """FlashcardEditorBase with tick-to-link controls under the saved list.

    The "Link as" combo chooses a relationship category; ticking a saved
    card's checkbox stages a Link between it and the card being edited
    (_staged_links), keyed to the edited card by a placeholder anchor until
    the first Save gives it a real id (_edit_anchor/_partner_id). Save writes
    the staged links alongside the card via the base's _links_to_persist /
    _after_save seam."""

    def __init__(self, store: FlashcardStore, parent=None):
        # _staged_links must exist before super().__init__() runs: the base
        # constructor calls _refresh_saved_list(), which (via the
        # _on_saved_list_refreshed hook) calls _retick_saved_list(), which
        # reads _staged_links.
        self._staged_links = []
        super().__init__(store, parent)

    # --- saved-list hooks (link-specific overrides) ----------------------

    def _saved_controls_widget(self) -> QWidget | None:
        controls = QWidget()
        link_controls = QHBoxLayout(controls)
        link_controls.setContentsMargins(0, 0, 0, 0)
        link_controls.addWidget(QLabel("Link as"))
        self.link_category_combo = QComboBox()
        for key, label, _colour in LINK_TYPES:
            self.link_category_combo.addItem(label, key)
        self.link_category_combo.setToolTip(
            "Choose a relationship; the rows below tick to show the edited card's "
            "links of this kind. Tick or untick a card to link or unlink it."
        )
        self.link_category_combo.currentIndexChanged.connect(
            lambda _=None: self._retick_saved_list()
        )
        link_controls.addWidget(self.link_category_combo)
        link_controls.addStretch()
        return controls

    def _configure_saved_item(self, item, card) -> None:
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(Qt.CheckState.Unchecked)

    def _on_saved_list_refreshed(self) -> None:
        self._retick_saved_list()

    def _on_saved_item_changed(self, item) -> None:
        partner = item.data(Qt.ItemDataRole.UserRole)
        category = self._current_category()
        checked = item.checkState() == Qt.CheckState.Checked
        self._staged_links = [
            l for l in self._staged_links
            if not (self._partner_id(l) == partner and l.type == category)
        ]
        if checked:
            self._staged_links.append(Link(self._edit_anchor(), partner, category))
        self._on_user_edit()

    # --- save seam (link-specific overrides) ------------------------------

    def _links_to_persist(self, card) -> list:
        return [
            Link(card.id, self._partner_id(link), link.type)
            for link in self._staged_links
        ]

    def _after_save(self, card) -> None:
        # Re-seed the staged links from the store (mirroring load_card) so
        # they are keyed by the card's real id, and the retick after this call
        # (via _refresh_saved_list -> _on_saved_list_refreshed) lands correctly.
        self._staged_links = list(self.store.links_for(card.id))

    # --- links ------------------------------------------------------------

    def _current_category(self) -> str:
        return self.link_category_combo.currentData()

    def _retick_saved_list(self) -> None:
        category = self._current_category()
        linked_partners = {
            self._partner_id(l) for l in self._staged_links if l.type == category
        }
        self._suppress_item_changed = True
        try:
            for i in range(self.saved_list.count()):
                item = self.saved_list.item(i)
                if not (item.flags() & Qt.ItemFlag.ItemIsUserCheckable):
                    continue
                partner = item.data(Qt.ItemDataRole.UserRole)
                state = (
                    Qt.CheckState.Checked
                    if partner in linked_partners
                    else Qt.CheckState.Unchecked
                )
                item.setCheckState(state)
        finally:
            self._suppress_item_changed = False

    def _edit_anchor(self) -> str:
        return self.state.loaded_card_id or _NEW_CARD_ANCHOR

    def _partner_id(self, link: Link) -> str:
        anchor = self._edit_anchor()
        return link.b_id if link.a_id == anchor else link.a_id
