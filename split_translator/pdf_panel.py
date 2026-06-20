"""Tabbed PDF panel showing original and translation with synced scrolling and search."""

import pymupdf
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
)

from .config import Config
from .page_mapper import PageMapper
from .pdf_viewer import PDFViewer, SearchWorker


class PDFPanel(QFrame):
    def __init__(self, config: Config, parent=None):
        super().__init__(parent)

        self.config = config

        self.current_match_index = -1
        self.search_term = ""
        self.search_worker = None
        self.matches = []
        self.page_matches = {}

        self.sync_enabled = True
        self.syncing = False

        self.init_ui()

        QTimer.singleShot(100, self.init_page_mapper)

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        nav_layout = QHBoxLayout()

        self.prev_button = QPushButton("◀ Prev")
        self.prev_button.clicked.connect(self.go_to_previous)
        self.prev_button.setEnabled(False)

        self.next_button = QPushButton("Next ▶")
        self.next_button.clicked.connect(self.go_to_next)
        self.next_button.setEnabled(False)

        self.match_label = QLabel("")
        self.page_label = QLabel("")

        self.sync_checkbox = QCheckBox("Sync")
        self.sync_checkbox.setChecked(True)
        self.sync_checkbox.stateChanged.connect(self.toggle_sync)

        nav_layout.addWidget(self.prev_button)
        nav_layout.addWidget(self.next_button)
        nav_layout.addWidget(self.match_label)
        nav_layout.addStretch()
        nav_layout.addWidget(self.sync_checkbox)
        nav_layout.addWidget(self.page_label)

        layout.addLayout(nav_layout)

        self.pdf_tabs = QTabWidget()

        self.original_viewer = PDFViewer(self.config.pdf_original_path)
        self.translation_viewer = PDFViewer(self.config.pdf_translation_path)

        self.pdf_tabs.addTab(self.original_viewer, "Original")
        self.pdf_tabs.addTab(self.translation_viewer, "Translation")

        self.pdf_tabs.currentChanged.connect(self.on_tab_changed)

        self.original_viewer.scroll_area.verticalScrollBar().valueChanged.connect(
            lambda: self.on_viewer_scrolled(self.original_viewer)
        )
        self.translation_viewer.scroll_area.verticalScrollBar().valueChanged.connect(
            lambda: self.on_viewer_scrolled(self.translation_viewer)
        )

        layout.addWidget(self.pdf_tabs)

    def init_page_mapper(self):
        original_count = self.original_viewer.doc.page_count
        translation_count = self.translation_viewer.doc.page_count

        self.page_mapper = PageMapper(original_count, translation_count)

        self.page_mapper.set_anchors(self.config.page_anchors)

    def toggle_sync(self, state):
        self.sync_enabled = state == Qt.CheckState.Checked.value

    def get_current_viewer(self):
        if self.pdf_tabs.currentIndex() == 0:
            return self.original_viewer
        else:
            return self.translation_viewer

    def on_tab_changed(self, index):
        """Called when user switches tabs."""
        # Pause syncing during tab switch.
        self.syncing = True

        viewer = self.get_current_viewer()
        viewer.refresh_scale()

        # Resume syncing after refresh completes.
        QTimer.singleShot(150, self._finish_tab_change)

    def _finish_tab_change(self):
        """Called after tab change refresh completes."""
        self.syncing = False
        self.update_page_label()

    def on_viewer_scrolled(self, source_viewer):
        """Handle scroll in either viewer."""
        self.update_page_label()

        if not self.sync_enabled or self.syncing:
            return

        # Only sync from the active tab.
        current_viewer = self.get_current_viewer()
        if source_viewer != current_viewer:
            return

        # Check if source viewer is refreshing.
        if source_viewer.is_refreshing:
            return

        self.syncing = True

        if source_viewer == self.original_viewer:
            self.sync_translation_to_original()
        else:
            self.sync_original_to_translation()

        self.syncing = False

    def sync_translation_to_original(self):
        original_page = self.original_viewer.get_current_page()
        translation_page = self.page_mapper.original_to_translation(original_page)
        self.translation_viewer.scroll_to_page(translation_page)

    def sync_original_to_translation(self):
        translation_page = self.translation_viewer.get_current_page()
        original_page = self.page_mapper.translation_to_original(translation_page)
        self.original_viewer.scroll_to_page(original_page)

    def update_page_label(self):
        viewer = self.get_current_viewer()
        current_page = viewer.get_current_page()
        total_pages = viewer.doc.page_count
        self.page_label.setText(f"Page {current_page + 1} / {total_pages}")

    def update_match_label(self):
        if not self.matches:
            self.match_label.setText("No matches" if self.search_term else "")
        else:
            self.match_label.setText(
                f"{self.current_match_index + 1} / {len(self.matches)}"
            )

    def search(self, term):
        self.search_term = term.strip()
        if not self.search_term:
            return

        if self.search_worker and self.search_worker.isRunning():
            self.search_worker.cancel()
            self.search_worker.wait()

        self.match_label.setText("Searching...")
        self.prev_button.setEnabled(False)
        self.next_button.setEnabled(False)

        self.search_worker = SearchWorker(self.original_viewer.doc, self.search_term)
        self.search_worker.finished.connect(self.on_search_complete)
        self.search_worker.start()

    def on_search_complete(self, matches, page_matches):
        self.matches = matches
        self.page_matches = page_matches
        self.current_match_index = -1

        self.update_match_label()
        self.prev_button.setEnabled(len(self.matches) > 0)
        self.next_button.setEnabled(len(self.matches) > 0)

        self.original_viewer.set_highlights(page_matches)

        if self.matches:
            self.current_match_index = 0
            self.scroll_to_current_match()
            self.update_match_label()

    def go_to_next(self):
        if not self.matches:
            return
        self.current_match_index = (self.current_match_index + 1) % len(self.matches)
        self.scroll_to_current_match()
        self.update_match_label()

    def go_to_previous(self):
        if not self.matches:
            return
        self.current_match_index = (self.current_match_index - 1) % len(self.matches)
        self.scroll_to_current_match()
        self.update_match_label()

    def scroll_to_current_match(self):
        """Scroll to match in original, optionally sync translation."""
        if self.current_match_index < 0 or not self.matches:
            return

        page_num, rect = self.matches[self.current_match_index]

        mat = pymupdf.Matrix(self.original_viewer.scale, self.original_viewer.scale)
        scaled_rect = pymupdf.Rect(rect) * mat
        self.original_viewer.scroll_to_position(page_num, scaled_rect.y0)

        if self.sync_enabled:
            translation_page = self.page_mapper.original_to_translation(page_num)
            self.translation_viewer.scroll_to_page(translation_page)

    def close_doc(self):
        self.original_viewer.close_doc()
        self.translation_viewer.close_doc()
