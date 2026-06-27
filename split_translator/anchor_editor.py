"""Side-by-side anchor editor: click a paragraph in each edition to select it,
then bind the two selections into an anchor. Saved anchors stay highlighted in
both views; clicking an anchor in the list jumps both views to it."""

from PySide6.QtWebEngineCore import QWebEngineProfile
from PySide6.QtWidgets import (
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .anchor_book_view import AnchorBookView
from .anchor_store import AnchorStore
from .book_loader import BookDocument

_ORIGINAL_ID_ROLE = 256  # Qt.UserRole
_TRANSLATION_ID_ROLE = 257  # Qt.UserRole + 1


class AnchorEditor(QWidget):
    """Two editions side by side; click to select a block on each, then bind."""

    def __init__(
        self,
        original_document: BookDocument,
        translation_document: BookDocument,
        anchor_store: AnchorStore,
        profile: QWebEngineProfile,
        on_changed,
        parent=None,
    ):
        super().__init__(parent)
        self.original_document = original_document
        self.translation_document = translation_document
        self.anchor_store = anchor_store
        self._profile_ref = profile
        self._on_changed = on_changed

        self._selected_original: str | None = None
        self._selected_translation: str | None = None

        self.init_ui()
        self.refresh()
        self._refresh_highlights()

    def init_ui(self):
        layout = QVBoxLayout(self)

        views = QHBoxLayout()
        self.original_view = AnchorBookView(
            self.original_document, self._profile_ref
        )
        self.translation_view = AnchorBookView(
            self.translation_document, self._profile_ref
        )
        self.original_view.block_clicked.connect(self._on_original_clicked)
        self.translation_view.block_clicked.connect(self._on_translation_clicked)
        views.addWidget(self.original_view)
        views.addWidget(self.translation_view)
        layout.addLayout(views)

        controls = QHBoxLayout()
        self.add_button = QPushButton("Add anchor here")
        self.add_button.setEnabled(False)
        self.add_button.clicked.connect(self._on_add_clicked)
        self.remove_button = QPushButton("Remove selected")
        self.remove_button.clicked.connect(self._remove_selected)
        controls.addWidget(self.add_button)
        controls.addWidget(self.remove_button)
        controls.addStretch()
        layout.addLayout(controls)

        self.anchor_list = QListWidget()
        self.anchor_list.itemClicked.connect(self._on_anchor_clicked)
        layout.addWidget(self.anchor_list)

    def _on_original_clicked(self, block_id: str) -> None:
        self._selected_original = block_id
        self.original_view.set_selected(block_id)
        self._update_add_enabled()

    def _on_translation_clicked(self, block_id: str) -> None:
        self._selected_translation = block_id
        self.translation_view.set_selected(block_id)
        self._update_add_enabled()

    def _update_add_enabled(self) -> None:
        self.add_button.setEnabled(
            self._selected_original is not None
            and self._selected_translation is not None
        )

    def _on_add_clicked(self) -> None:
        if self._selected_original is None or self._selected_translation is None:
            return
        self.anchor_store.add(self._selected_original, self._selected_translation)
        self.refresh()
        self._on_changed()

        # Clear both selections; the just-bound blocks now show as anchored.
        self._selected_original = None
        self._selected_translation = None
        self.original_view.set_selected("")
        self.translation_view.set_selected("")
        self._update_add_enabled()
        self._refresh_highlights()

    def _refresh_highlights(self) -> None:
        original_ids = [pair[0] for pair in self.anchor_store.anchors]
        translation_ids = [pair[1] for pair in self.anchor_store.anchors]
        self.original_view.set_anchored(original_ids)
        self.translation_view.set_anchored(translation_ids)

    def refresh(self) -> None:
        self.anchor_list.clear()
        for original_id, translation_id in self.anchor_store.anchors:
            item = QListWidgetItem(f"{original_id}  =  {translation_id}")
            item.setData(_ORIGINAL_ID_ROLE, original_id)
            item.setData(_TRANSLATION_ID_ROLE, translation_id)
            self.anchor_list.addItem(item)

    def _on_anchor_clicked(self, item: QListWidgetItem) -> None:
        original_id = item.data(_ORIGINAL_ID_ROLE)
        translation_id = item.data(_TRANSLATION_ID_ROLE)
        # Jump both views to the pair and emphasise it; this does NOT change the
        # selection state, so it cannot enable "Add anchor here".
        self.original_view.scroll_to(original_id, 0.0)
        self.translation_view.scroll_to(translation_id, 0.0)
        self.original_view.set_jump(original_id)
        self.translation_view.set_jump(translation_id)

    def _remove_selected(self) -> None:
        item = self.anchor_list.currentItem()
        if item is None:
            return
        original_id = item.data(_ORIGINAL_ID_ROLE)
        self.anchor_store.remove(original_id)
        self.refresh()
        self._refresh_highlights()
        self._on_changed()
