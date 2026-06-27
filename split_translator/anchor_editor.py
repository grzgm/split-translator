"""Side-by-side anchor editor: shows both editions and captures matching block-id
pairs into the anchor store, which feeds the reader's content sync."""

from PySide6.QtWebEngineCore import QWebEngineProfile
from PySide6.QtWidgets import (
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .anchor_store import AnchorStore
from .book_loader import BookDocument
from .book_view import BookView


class AnchorEditor(QWidget):
    """Two editions side by side; capture matching anchor pairs."""

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
        self._pending_original_id = ""

        self.init_ui()
        self.refresh()

    def init_ui(self):
        layout = QVBoxLayout(self)

        views = QHBoxLayout()
        self.original_view = BookView(self.original_document, self._profile_ref)
        self.translation_view = BookView(
            self.translation_document, self._profile_ref
        )
        views.addWidget(self.original_view)
        views.addWidget(self.translation_view)
        layout.addLayout(views)

        controls = QHBoxLayout()
        self.add_button = QPushButton("Add anchor here")
        self.add_button.clicked.connect(self._on_add_clicked)
        self.remove_button = QPushButton("Remove selected")
        self.remove_button.clicked.connect(self._remove_selected)
        controls.addWidget(self.add_button)
        controls.addWidget(self.remove_button)
        controls.addStretch()
        layout.addLayout(controls)

        self.anchor_list = QListWidget()
        layout.addWidget(self.anchor_list)

    def refresh(self) -> None:
        self.anchor_list.clear()
        for original_id, translation_id in self.anchor_store.anchors:
            item = QListWidgetItem(f"{original_id}  =  {translation_id}")
            item.setData(256, original_id)  # Qt.UserRole == 256
            self.anchor_list.addItem(item)

    def _on_add_clicked(self) -> None:
        # Read each view's topmost block id, then capture the pair once both are
        # known. The reads are asynchronous, so chain them.
        def got_original(original_id: str) -> None:
            self._pending_original_id = original_id

            def got_translation(translation_id: str) -> None:
                if original_id and translation_id:
                    self._capture_pair(original_id, translation_id)

            self.translation_view.topmost_block_id(got_translation)

        self.original_view.topmost_block_id(got_original)

    def _capture_pair(self, original_id: str, translation_id: str) -> None:
        self.anchor_store.add(original_id, translation_id)
        self.refresh()
        self._on_changed()

    def _remove_selected(self) -> None:
        item = self.anchor_list.currentItem()
        if item is None:
            return
        original_id = item.data(256)
        self.anchor_store.remove(original_id)
        self.refresh()
        self._on_changed()
