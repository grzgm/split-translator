"""Tabbed book panel showing original and translation editions in web views, with
native full-text search. Scroll sync is added in a later change; this panel keeps
the Sync checkbox state but does not yet mirror scrolling."""

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

from .book_loader import load_book
from .book_view import BookView
from .config import Config


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

    def close_doc(self) -> None:
        # Web views own no file handles to close; clear any active find so the
        # native highlight does not linger.
        self.original_view.find("", True, lambda _c: None)
        self.translation_view.find("", True, lambda _c: None)
