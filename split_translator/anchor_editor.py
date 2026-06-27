"""Side-by-side anchor editor: click a paragraph in each edition to select it,
then bind the two selections into an anchor. Saved anchors stay highlighted in
both views; clicking an anchor in the list jumps both views to it."""

from PySide6.QtCore import Qt
from PySide6.QtWebEngineCore import QWebEngineProfile
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from .anchor_book_view import AnchorBookView
from .anchor_store import AnchorStore
from .book_loader import BookDocument
from .book_sync import BookSync

_ORIGINAL_ID_ROLE = 256  # Qt.UserRole
_TRANSLATION_ID_ROLE = 257  # Qt.UserRole + 1


class AnchorEditor(QWidget):
    """Two editions side by side; click to select a block on each, then bind."""

    def __init__(
        self,
        original_document: BookDocument,
        translation_document: BookDocument,
        anchor_store: AnchorStore,
        book_sync: BookSync,
        profile: QWebEngineProfile,
        on_changed,
        parent=None,
    ):
        super().__init__(parent)
        self.original_document = original_document
        self.translation_document = translation_document
        self.anchor_store = anchor_store
        self.book_sync = book_sync
        self._profile_ref = profile
        self._on_changed = on_changed

        self._selected_original: str | None = None
        self._selected_translation: str | None = None
        self.sync_enabled = True

        self.init_ui()
        self.refresh()
        self._refresh_highlights()

    def init_ui(self):
        layout = QVBoxLayout(self)

        # A vertical splitter so the boundary between the two book views (top)
        # and the controls + anchor list (bottom) can be dragged to give the
        # list more or less height.
        splitter = QSplitter(Qt.Orientation.Vertical)

        views_container = QWidget()
        views = QHBoxLayout(views_container)
        views.setContentsMargins(0, 0, 0, 0)
        self.original_view = AnchorBookView(
            self.original_document, self._profile_ref
        )
        self.translation_view = AnchorBookView(
            self.translation_document, self._profile_ref
        )
        self.original_view.block_clicked.connect(self._on_original_clicked)
        self.translation_view.block_clicked.connect(self._on_translation_clicked)
        # Optional synced scrolling between the two sides (anchor-based, like the
        # main reader). The `scrolled` signal is separate from `block_clicked`,
        # so syncing never interferes with click-to-select.
        self.original_view.scrolled.connect(
            lambda bid, frac: self._sync_from(self.original_view, bid, frac)
        )
        self.translation_view.scrolled.connect(
            lambda bid, frac: self._sync_from(self.translation_view, bid, frac)
        )
        views.addWidget(self.original_view)
        views.addWidget(self.translation_view)
        splitter.addWidget(views_container)

        # The controls stay attached to the list so they are not squashed when
        # the views are given most of the height.
        bottom_container = QWidget()
        bottom = QVBoxLayout(bottom_container)
        bottom.setContentsMargins(0, 0, 0, 0)

        controls = QHBoxLayout()
        self.add_button = QPushButton("Add anchor here")
        self.add_button.setEnabled(False)
        self.add_button.clicked.connect(self._on_add_clicked)
        self.remove_button = QPushButton("Remove selected")
        self.remove_button.clicked.connect(self._remove_selected)
        self.sync_checkbox = QCheckBox("Sync")
        self.sync_checkbox.setChecked(True)
        self.sync_checkbox.stateChanged.connect(self.toggle_sync)
        controls.addWidget(self.add_button)
        controls.addWidget(self.remove_button)
        controls.addWidget(self.sync_checkbox)
        controls.addStretch()
        bottom.addLayout(controls)

        self.anchor_list = QListWidget()
        self.anchor_list.itemClicked.connect(self._on_anchor_clicked)
        bottom.addWidget(self.anchor_list)
        splitter.addWidget(bottom_container)

        # Give the book views most of the height by default; both stay resizable.
        # setSizes seeds the initial split (book-heavy); the stretch factors keep
        # that ratio as the window resizes.
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([640, 160])

        layout.addWidget(splitter)

    def toggle_sync(self, state) -> None:
        self.sync_enabled = state == Qt.CheckState.Checked.value

    def _sync_from(self, source_view, block_id: str, fraction: float) -> None:
        """Mirror a scroll on one side to the other through the anchor mapping.
        Mirrors BookPanel._sync_from; the scroll_to echo guard in AnchorBookView
        prevents the mirrored scroll from bouncing back."""
        if not self.sync_enabled:
            return
        if source_view is self.original_view:
            try:
                index = self.original_document.block_ids.index(block_id)
            except ValueError:
                return
            dst_index, dst_fraction = self.book_sync.original_to_translation(
                index, fraction
            )
            target_id = self.translation_document.block_ids[dst_index]
            self.translation_view.scroll_to(target_id, dst_fraction)
        else:
            try:
                index = self.translation_document.block_ids.index(block_id)
            except ValueError:
                return
            dst_index, dst_fraction = self.book_sync.translation_to_original(
                index, fraction
            )
            target_id = self.original_document.block_ids[dst_index]
            self.original_view.scroll_to(target_id, dst_fraction)

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
