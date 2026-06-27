"""Tabbed book panel showing original and translation editions in web views, with
native full-text search and content-anchor scroll sync."""

from PySide6.QtCore import Qt
from PySide6.QtWebEngineCore import QWebEngineProfile
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
)

from .anchor_editor import AnchorEditor
from .anchor_store import AnchorStore, anchor_path_for
from .book_loader import load_book
from .book_sync import BookSync
from .book_view import BookView
from .config import Config, PROJECT_ROOT


class BookPanel(QFrame):
    def __init__(self, config: Config, profile: QWebEngineProfile, parent=None):
        super().__init__(parent)
        self.config = config
        self.profile = profile

        self.search_term = ""
        self.match_count = 0
        self.current_match = 0
        self.sync_enabled = True

        self.original_document = load_book(config.pdf_original_path)
        self.translation_document = load_book(config.pdf_translation_path)

        self.anchor_store = AnchorStore(
            anchor_path_for(
                config.pdf_original_path,
                config.pdf_translation_path,
                PROJECT_ROOT,
            )
        )
        self.book_sync = BookSync(
            len(self.original_document.block_ids),
            len(self.translation_document.block_ids),
        )
        self.book_sync.set_anchors(
            self.anchor_store.resolve(
                self.original_document.block_ids,
                self.translation_document.block_ids,
            )
        )

        self.anchor_editor = None

        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        nav_layout = QHBoxLayout()

        self.prev_button = QPushButton("Prev")
        self.prev_button.clicked.connect(self.go_to_previous)
        self.prev_button.setEnabled(False)

        self.next_button = QPushButton("Next")
        self.next_button.clicked.connect(self.go_to_next)
        self.next_button.setEnabled(False)

        self.match_label = QLabel("")
        self.position_label = QLabel("")

        self.sync_checkbox = QCheckBox("Sync")
        self.sync_checkbox.setChecked(True)
        self.sync_checkbox.stateChanged.connect(self.toggle_sync)

        nav_layout.addWidget(self.prev_button)
        nav_layout.addWidget(self.next_button)
        nav_layout.addWidget(self.match_label)
        nav_layout.addStretch()
        nav_layout.addWidget(self.sync_checkbox)
        nav_layout.addWidget(self.position_label)
        layout.addLayout(nav_layout)

        self.tabs = QTabWidget()
        self.original_view = BookView(self.original_document, self.profile)
        self.translation_view = BookView(self.translation_document, self.profile)
        self.tabs.addTab(self.original_view, "Original")
        self.tabs.addTab(self.translation_view, "Translation")
        layout.addWidget(self.tabs)

        self.original_view.scrolled.connect(
            lambda bid, frac: self._sync_from(self.original_view, bid, frac)
        )
        self.translation_view.scrolled.connect(
            lambda bid, frac: self._sync_from(self.translation_view, bid, frac)
        )
        self.tabs.currentChanged.connect(self._update_position_label)

    def _sync_from(self, source_view, block_id: str, fraction: float) -> None:
        self._update_position_label()
        if not self.sync_enabled:
            return
        # Only mirror from the active tab.
        if source_view is not self.current_view():
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

    def _update_position_label(self) -> None:
        view = self.current_view()
        if view is self.original_view:
            total = len(self.original_document.block_ids)
        else:
            total = len(self.translation_document.block_ids)
        self.position_label.setText(f"{total} blocks")

    def toggle_sync(self, state):
        self.sync_enabled = state == Qt.CheckState.Checked.value

    def current_view(self) -> BookView:
        if self.tabs.currentIndex() == 0:
            return self.original_view
        return self.translation_view

    def update_match_label(self):
        if not self.match_count:
            self.match_label.setText("No matches" if self.search_term else "")
        else:
            self.match_label.setText(f"{self.current_match} / {self.match_count}")

    def search(self, term: str) -> None:
        self.search_term = term.strip()
        if not self.search_term:
            return
        self.current_match = 0
        self.current_view().find(
            self.search_term, True, self._on_search_result
        )

    def _on_search_result(self, count: int) -> None:
        self.match_count = count
        self.current_match = 1 if count else 0
        self.prev_button.setEnabled(count > 0)
        self.next_button.setEnabled(count > 0)
        self.update_match_label()

    def go_to_next(self) -> None:
        if not self.match_count:
            return
        self.current_match = self.current_match % self.match_count + 1
        self.current_view().find(self.search_term, True, lambda _c: None)
        self.update_match_label()

    def go_to_previous(self) -> None:
        if not self.match_count:
            return
        self.current_match = (self.current_match - 2) % self.match_count + 1
        self.current_view().find(self.search_term, False, lambda _c: None)
        self.update_match_label()

    def _reseed_sync(self) -> None:
        self.book_sync.set_anchors(
            self.anchor_store.resolve(
                self.original_document.block_ids,
                self.translation_document.block_ids,
            )
        )

    def open_anchor_editor(self) -> None:
        if self.anchor_editor is None:
            self.anchor_editor = AnchorEditor(
                self.original_document,
                self.translation_document,
                self.anchor_store,
                self.profile,
                self._reseed_sync,
            )
            self.anchor_editor.setWindowTitle("Anchor editor")
            self.anchor_editor.resize(1200, 800)
        self.anchor_editor.show()
        self.anchor_editor.raise_()

    def close_doc(self) -> None:
        # Web views own no file handles to close; clear any active find so the
        # native highlight does not linger.
        self.original_view.find("", True, lambda _c: None)
        self.translation_view.find("", True, lambda _c: None)
        # Close the anchor editor if open so its pages are released before the
        # shared web profile is torn down (avoids the "profile released but page
        # not deleted" warning).
        if self.anchor_editor is not None:
            self.anchor_editor.close()
        # Await any in-flight anchor write so anchors are not lost on quit.
        self.anchor_store.shutdown()
