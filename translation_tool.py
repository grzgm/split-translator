#!/usr/bin/env python3
import os
# Force software rendering to avoid GPU/EGL context errors
os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = "--disable-gpu"

import json
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

import pymupdf
from PyQt5.QtCore import QSize, Qt, QThread, QTimer, QUrl, pyqtSignal
from PyQt5.QtGui import QColor, QImage, QKeySequence, QPainter, QPixmap
from PyQt5.QtWebEngineWidgets import (
    QWebEngineProfile,
    QWebEngineSettings,
    QWebEngineView,
)
from PyQt5.QtWidgets import (
    QApplication,
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QPushButton,
    QScrollArea,
    QShortcut,
    QSplitter,
    QStyledItemDelegate,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

# Go to http://localhost:9222 for dev tools of opened QWebEngineView
# import os
# os.environ["QTWEBENGINE_REMOTE_DEBUGGING"] = "9222"

CONFIG_PATH = Path(__file__).parent / "config.json"


def load_config():
    """Load personal config (book paths, page anchors) from a gitignored file."""
    if not CONFIG_PATH.exists():
        sys.exit(
            f"Config file not found: {CONFIG_PATH}\n"
            "Copy config.sample.json to config.json and fill in your book paths."
        )

    with open(CONFIG_PATH, "r") as f:
        config = json.load(f)

    return config


CONFIG = load_config()
PDF_ORIGINAL_PATH = CONFIG["pdf_original_path"]
PDF_TRANSLATION_PATH = CONFIG["pdf_translation_path"]
PAGE_ANCHORS = [tuple(anchor) for anchor in CONFIG["page_anchors"]]


class SearchWorker(QThread):
    finished = pyqtSignal(list, dict)  # matches, page_matches

    def __init__(self, doc, term):
        super().__init__()
        self.doc = doc
        self.term = term
        self.cancelled = False  # Flag to check

    def run(self):
        matches = []
        page_matches = {}

        for page_num in range(len(self.doc)):
            if self.cancelled:  # Check before each page
                return

            page = self.doc[page_num]
            found = page.search_for(self.term)
            for rect in found:
                matches.append((page_num, rect))
            if found:
                page_matches[page_num] = found

        self.finished.emit(matches, page_matches)

    def cancel(self):
        self.cancelled = True


class PageMapper:
    """Maps page numbers between two PDF versions using anchor points with interpolation."""

    def __init__(self, original_page_count, translation_page_count):
        self.original_page_count = original_page_count
        self.translation_page_count = translation_page_count

        # Default anchors: start and end
        # Format: (original_page, translation_page) - 0-indexed
        self.anchors = [
            (0, 0),
            (original_page_count - 1, translation_page_count - 1),
        ]

    def set_anchors(self, anchors):
        """
        Set anchor points manually.

        Args:
            anchors: List of (original_page, translation_page) tuples, 0-indexed
        """
        if not anchors:
            return

        self.anchors = sorted(anchors, key=lambda x: x[0])

        # Ensure start anchor exists
        if self.anchors[0][0] != 0:
            self.anchors.insert(0, (0, 0))

        # Ensure end anchor exists
        last_orig = self.original_page_count - 1
        last_trans = self.translation_page_count - 1
        if self.anchors[-1][0] != last_orig:
            self.anchors.append((last_orig, last_trans))

    def add_anchor(self, original_page, translation_page):
        """Add a single anchor point."""
        # Remove existing anchor at same original page
        self.anchors = [a for a in self.anchors if a[0] != original_page]

        self.anchors.append((original_page, translation_page))
        self.anchors.sort(key=lambda x: x[0])

    def remove_anchor(self, original_page):
        """Remove anchor at specified original page (keeps start/end)."""
        if original_page == 0 or original_page == self.original_page_count - 1:
            return  # Don't remove start/end anchors

        self.anchors = [a for a in self.anchors if a[0] != original_page]

    def get_anchors(self):
        """Return current anchor points."""
        return self.anchors.copy()

    def original_to_translation(self, original_page):
        """
        Map original page number to translation page number.

        Args:
            original_page: 0-indexed page number in original PDF

        Returns:
            0-indexed page number in translation PDF
        """
        # Clamp to valid range
        original_page = max(0, min(original_page, self.original_page_count - 1))

        # Find surrounding anchors
        lower_anchor = self.anchors[0]
        upper_anchor = self.anchors[-1]

        for i in range(len(self.anchors) - 1):
            if self.anchors[i][0] <= original_page <= self.anchors[i + 1][0]:
                lower_anchor = self.anchors[i]
                upper_anchor = self.anchors[i + 1]
                break

        # Exact match
        if original_page == lower_anchor[0]:
            return lower_anchor[1]
        if original_page == upper_anchor[0]:
            return upper_anchor[1]

        # Linear interpolation
        orig_range = upper_anchor[0] - lower_anchor[0]
        trans_range = upper_anchor[1] - lower_anchor[1]

        if orig_range == 0:
            return lower_anchor[1]

        position = (original_page - lower_anchor[0]) / orig_range
        translation_page = lower_anchor[1] + (position * trans_range)

        # Clamp result
        result = int(round(translation_page))
        return max(0, min(result, self.translation_page_count - 1))

    def translation_to_original(self, translation_page):
        """
        Map translation page number to original page number.

        Args:
            translation_page: 0-indexed page number in translation PDF

        Returns:
            0-indexed page number in original PDF
        """
        # Clamp to valid range
        translation_page = max(
            0, min(translation_page, self.translation_page_count - 1)
        )

        # Find surrounding anchors (by translation page)
        lower_anchor = self.anchors[0]
        upper_anchor = self.anchors[-1]

        for i in range(len(self.anchors) - 1):
            lower_trans = self.anchors[i][1]
            upper_trans = self.anchors[i + 1][1]

            if lower_trans <= translation_page <= upper_trans:
                lower_anchor = self.anchors[i]
                upper_anchor = self.anchors[i + 1]
                break

        # Exact match
        if translation_page == lower_anchor[1]:
            return lower_anchor[0]
        if translation_page == upper_anchor[1]:
            return upper_anchor[0]

        # Linear interpolation
        orig_range = upper_anchor[0] - lower_anchor[0]
        trans_range = upper_anchor[1] - lower_anchor[1]

        if trans_range == 0:
            return lower_anchor[0]

        position = (translation_page - lower_anchor[1]) / trans_range
        original_page = lower_anchor[0] + (position * orig_range)

        # Clamp result
        result = int(round(original_page))
        return max(0, min(result, self.original_page_count - 1))


class PDFViewer(QWidget):
    """Widget that displays a single PDF with lazy loading and search."""

    def __init__(self, pdf_path, parent=None):
        super().__init__(parent)
        self.doc = pymupdf.open(pdf_path)
        self.page_labels = []
        self.rendered_pages = set()
        self.scale = 1.0
        self.page_matches = {}
        self.is_refreshing = False  # Flag to prevent re-entry

        self.init_ui()
        QTimer.singleShot(
            0,
            lambda: (
                setattr(self, "scale", self.calc_fit_scale()),
                self.create_placeholders(),
            ),
        )

        self.resize_timer = QTimer()
        self.resize_timer.setSingleShot(True)
        self.resize_timer.timeout.connect(self.on_resize_finished)

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)

        self.pages_container = QWidget()
        self.pages_layout = QVBoxLayout(self.pages_container)
        self.pages_layout.setAlignment(Qt.AlignCenter)

        self.scroll_area.setWidget(self.pages_container)
        self.scroll_area.verticalScrollBar().valueChanged.connect(self.on_scroll)

        layout.addWidget(self.scroll_area)

    def calc_fit_scale(self):
        viewport = self.scroll_area.viewport()
        scroll_area_width = viewport.rect().width() - 50
        scroll_area_height = viewport.rect().height()

        # Guard against zero dimensions (hidden widget)
        if scroll_area_width <= 0 or scroll_area_height <= 0:
            return self.scale

        page = self.doc[0]
        first_page_width = page.rect.width
        first_page_height = page.rect.height

        if first_page_width <= 0 or first_page_height <= 0:
            return 1.0

        width_scale = scroll_area_width / first_page_width
        height_scale = scroll_area_height / first_page_height

        return min(width_scale, height_scale)

    def resizeEvent(self, event):
        super().resizeEvent(event)

        if not self.page_labels or self.is_refreshing:
            return

        new_scale = self.calc_fit_scale()

        # Skip if scale hasn't changed significantly
        if abs(new_scale - self.scale) < 0.01:
            return

        self.scale = new_scale

        for page_num, label in enumerate(self.page_labels):
            page = self.doc[page_num]
            rect = page.rect
            label.setFixedSize(
                int(rect.width * self.scale), int(rect.height * self.scale)
            )

        self.resize_timer.start(150)

    def on_resize_finished(self):
        for page_num in self.rendered_pages:
            highlights = self.page_matches.get(page_num)
            pixmap = self.render_page(page_num, highlights)
            self.page_labels[page_num].setPixmap(pixmap)

    def create_placeholders(self):
        self.page_labels = []

        for page_num in range(self.doc.page_count):
            page = self.doc[page_num]
            rect = page.rect
            scaled_width = int(rect.width * self.scale)
            scaled_height = int(rect.height * self.scale)

            label = QLabel()
            label.setFixedSize(scaled_width, scaled_height)
            label.setAlignment(Qt.AlignCenter)
            label.setStyleSheet("background-color: #f0f0f0;")
            self.pages_layout.addWidget(label)
            self.page_labels.append(label)

        QTimer.singleShot(0, self.render_visible_pages)

    def render_visible_pages(self):
        viewport = self.scroll_area.viewport()
        viewport_rect = viewport.rect()
        scroll_y = self.scroll_area.verticalScrollBar().value()

        visible_top = scroll_y
        visible_bottom = scroll_y + viewport_rect.height()

        for page_num, label in enumerate(self.page_labels):
            if page_num in self.rendered_pages:
                continue

            label_top = label.geometry().top()
            label_bottom = label.geometry().bottom()

            margin = 200
            if (
                label_bottom >= visible_top - margin
                and label_top <= visible_bottom + margin
            ):
                highlights = self.page_matches.get(page_num)
                pixmap = self.render_page(page_num, highlights)
                label.setPixmap(pixmap)
                label.setStyleSheet("")
                self.rendered_pages.add(page_num)

    def on_scroll(self):
        if not self.is_refreshing:
            self.render_visible_pages()

    def render_page(self, page_num, highlights=None):
        page = self.doc[page_num]
        mat = pymupdf.Matrix(self.scale, self.scale)
        pix = page.get_pixmap(matrix=mat)
        img = QImage(
            pix.samples, pix.width, pix.height, pix.stride, QImage.Format_RGB888
        )

        if highlights:
            img = img.copy()
            painter = QPainter(img)
            painter.setCompositionMode(QPainter.CompositionMode_Multiply)
            for rect in highlights:
                scaled_rect = pymupdf.Rect(rect) * mat
                painter.fillRect(
                    int(scaled_rect.x0),
                    int(scaled_rect.y0),
                    int(scaled_rect.width),
                    int(scaled_rect.height),
                    QColor(255, 255, 0, 100),
                )
            painter.end()

        return QPixmap.fromImage(img)

    def set_highlights(self, page_matches):
        self.page_matches = page_matches

        for page_num in self.rendered_pages:
            highlights = self.page_matches.get(page_num)
            pixmap = self.render_page(page_num, highlights)
            self.page_labels[page_num].setPixmap(pixmap)

    def scroll_to_position(self, page_num, y_offset):
        if 0 <= page_num < len(self.page_labels):
            label = self.page_labels[page_num]
            label_top = label.geometry().top()
            target_y = label_top + y_offset

            self.scroll_area.verticalScrollBar().setValue(
                int(target_y - self.scroll_area.viewport().height() / 2)
            )

    def get_current_page(self):
        if not self.page_labels:
            return 0

        center_y = self.get_scroll_center()

        for i, label in enumerate(self.page_labels):
            label_top = label.geometry().top()
            label_bottom = label.geometry().bottom()
            if label_top <= center_y <= label_bottom:
                return i
            elif label_top > center_y:
                return max(0, i - 1)

        return len(self.page_labels) - 1

    def get_scroll_center(self):
        viewport_center = self.scroll_area.viewport().height() // 2
        scroll_pos = self.scroll_area.verticalScrollBar().value()
        return scroll_pos + viewport_center

    def scroll_to_page(self, page_num):
        if not self.page_labels:
            return

        page_num = max(0, min(page_num, len(self.page_labels) - 1))
        label = self.page_labels[page_num]

        label_top = label.geometry().top()
        viewport_height = self.scroll_area.viewport().height()
        label_height = label.height()

        target_scroll = label_top - (viewport_height - label_height) // 2
        target_scroll = max(0, target_scroll)

        self.scroll_area.verticalScrollBar().setValue(target_scroll)

    def refresh_scale(self):
        """Recalculate scale and re-render. Call when viewer becomes visible."""
        if not self.page_labels or self.is_refreshing:
            return

        self.is_refreshing = True
        current_page = self.get_current_page()

        # Delay to ensure geometry is updated after tab switch
        QTimer.singleShot(50, lambda: self._do_refresh_scale(current_page))

    def _do_refresh_scale(self, restore_page):
        """Actual scale refresh after delay."""
        if not self.page_labels:
            self.is_refreshing = False
            return

        new_scale = self.calc_fit_scale()

        # Only refresh if scale actually changed significantly
        if abs(new_scale - self.scale) < 0.01:
            self.is_refreshing = False
            return

        self.scale = new_scale

        for page_num, label in enumerate(self.page_labels):
            page = self.doc[page_num]
            rect = page.rect
            label.setFixedSize(
                int(rect.width * self.scale), int(rect.height * self.scale)
            )

        self.rendered_pages.clear()

        # Restore scroll position and render
        QTimer.singleShot(0, lambda: self._restore_and_render(restore_page))

    def _restore_and_render(self, page_num):
        """Restore scroll position and render visible pages."""
        self.scroll_to_page(page_num)
        self.render_visible_pages()
        self.is_refreshing = False

    def close_doc(self):
        self.doc.close()


class PDFPanel(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)

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

        self.original_viewer = PDFViewer(PDF_ORIGINAL_PATH)
        self.translation_viewer = PDFViewer(PDF_TRANSLATION_PATH)

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

        self.page_mapper.set_anchors(PAGE_ANCHORS)

    def toggle_sync(self, state):
        self.sync_enabled = state == Qt.Checked

    def get_current_viewer(self):
        if self.pdf_tabs.currentIndex() == 0:
            return self.original_viewer
        else:
            return self.translation_viewer

    def on_tab_changed(self, index):
        """Called when user switches tabs."""
        # Pause syncing during tab switch
        self.syncing = True

        viewer = self.get_current_viewer()
        viewer.refresh_scale()

        # Resume syncing after refresh completes
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

        # Only sync from the active tab
        current_viewer = self.get_current_viewer()
        if source_viewer != current_viewer:
            return

        # Check if source viewer is refreshing
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


class SimpleDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):
        word = index.data(Qt.UserRole)["word"]
        date = index.data(Qt.UserRole)["date"]

        painter.save()

        # Draw word (large font)
        font = painter.font()
        font.setPointSize(12)
        painter.setFont(font)
        painter.drawText(option.rect.adjusted(5, 5, 0, 0), Qt.AlignLeft, word)

        # Draw date (small, grey)
        font.setPointSize(8)
        painter.setFont(font)
        painter.setPen(QColor(128, 128, 128))
        painter.drawText(option.rect.adjusted(5, 22, 0, 0), Qt.AlignLeft, date)

        painter.restore()

    def sizeHint(self, option, index):
        return QSize(option.rect.width(), 40)


class SaveWorker(QThread):
    def __init__(self, filepath, data):
        super().__init__()
        self.filepath = filepath
        self.data = data

    def run(self):
        with open(self.filepath, "w") as f:
            json.dump(self.data, f, indent=2)


class TranslationTool(QMainWindow):
    handle_google_correction_signal = pyqtSignal(str)

    blocked_selectors = [
        # "#ad-banner",
        # "#sidebar-ad",
        # "#ad_leftslot",
        # "#ad_leftslot2",
        # "#ad_rightslot",
        # "#ad_topslot",
        # ".advertisement",
        # ".ad-container",
        # "[data-ad]",
        # "iframe[src*='doubleclick']",
        # "iframe[src*='googlesyndication']",
        # # IDs
        # "#ad-container",
        # "#google-ads",
        # "#sidebar-advertisement",
        # # Classes
        # ".ad",
        # ".ads",
        # ".advertisement",
        # ".sponsored",
        # ".promoted",
        # # Data attributes
        # "[data-ad]",
        # "[data-advertisement]",
        # "[data-google-query-id]",
        # Specific elements
        "iframe[src*='ads']",
        "div[id^='google_ads']",  # ID starts with google_ads
        "div[id*='ad_leftslot']",  # ID starts with google_ads
        "div[id*='ad_rightslot']",  # ID starts with google_ads
        "div[id*='ad_topslot']",  # ID starts with google_ads
    ]

    def __init__(self):
        super().__init__()
        self.handle_google_correction_signal.connect(self.handle_google_correction)
        self.save_worker = None
        self.history_file = Path(__file__).parent / ".translation_tool_history.json"
        self.history = self.load_history()
        self.init_ui()
        self.setup_shortcuts()
        self.update_history_list()

    def init_ui(self):
        self.setWindowTitle("Translation Tool")
        self.setGeometry(100, 100, 1800, 900)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)

        # History panel
        history_panel = QWidget()
        history_layout = QVBoxLayout(history_panel)
        history_layout.setContentsMargins(0, 0, 0, 0)
        history_label = QLabel("Search History")
        history_layout.addWidget(history_label)
        self.history_list = QListWidget()
        self.history_list.setItemDelegate(SimpleDelegate())
        self.history_list.itemClicked.connect(self.on_history_click)
        self.history_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.history_list.customContextMenuRequested.connect(
            self.show_history_context_menu
        )
        history_layout.addWidget(self.history_list)
        clear_button = QPushButton("Clear History")
        clear_button.clicked.connect(self.clear_history)
        history_layout.addWidget(clear_button)
        history_panel.setMaximumWidth(200)
        main_layout.addWidget(history_panel)

        # Content splitter
        content_splitter = QSplitter(Qt.Horizontal)
        dict_widget = QWidget()
        dict_layout = QVBoxLayout(dict_widget)
        dict_layout.setContentsMargins(0, 0, 0, 0)

        # Search bar
        search_layout = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Enter word to translate...")
        self.search_input.returnPressed.connect(self.search)
        search_button = QPushButton("Search")
        search_button.clicked.connect(self.search)
        correction_button = QPushButton("Get Correction")
        correction_button.clicked.connect(self.get_correction)
        search_layout.addWidget(self.search_input)
        search_layout.addWidget(search_button)
        search_layout.addWidget(correction_button)
        dict_layout.addLayout(search_layout)

        # Web views
        main_splitter = QSplitter(Qt.Horizontal)
        left_splitter = QSplitter(Qt.Vertical)

        # Set user agent for all views
        profile = QWebEngineProfile.defaultProfile()
        profile.setHttpUserAgent(
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )

        settings = profile.settings()
        settings.setAttribute(QWebEngineSettings.PlaybackRequiresUserGesture, False)

        self.cambridge_en_view = QWebEngineView()
        self.cambridge_pl_view = QWebEngineView()

        left_splitter.addWidget(self.cambridge_en_view)
        left_splitter.addWidget(self.cambridge_pl_view)
        left_splitter.setSizes([1, 1])

        right_splitter = QSplitter(Qt.Vertical)

        self.google_tabs = QTabWidget()
        self.google_meaning_view = QWebEngineView()
        self.google_translate_view = QWebEngineView()
        self.google_tabs.addTab(self.google_meaning_view, "Meaning")
        self.google_tabs.addTab(self.google_translate_view, "Po polsku")

        self.babla_view = QWebEngineView()

        right_splitter.addWidget(self.google_tabs)
        right_splitter.addWidget(self.babla_view)
        right_splitter.setSizes([400, 400])

        main_splitter.addWidget(left_splitter)
        main_splitter.addWidget(right_splitter)
        main_splitter.setSizes([500, 500])
        dict_layout.addWidget(main_splitter)

        # Connect loadFinished signal for each web view
        self.cambridge_en_view.loadFinished.connect(
            lambda: self.remove_ads(self.cambridge_en_view)
        )
        self.cambridge_pl_view.loadFinished.connect(
            lambda: self.remove_ads(self.cambridge_pl_view)
        )
        self.google_meaning_view.loadFinished.connect(
            lambda: self.remove_ads(self.google_meaning_view)
        )
        self.google_translate_view.loadFinished.connect(
            lambda: self.remove_ads(self.google_translate_view)
        )
        self.babla_view.loadFinished.connect(lambda: self.remove_ads(self.babla_view))

        self.pdf_panel = PDFPanel()

        content_splitter.addWidget(dict_widget)
        content_splitter.addWidget(self.pdf_panel)
        content_splitter.setSizes([1000, 500])

        main_layout.addWidget(content_splitter)
        self.search_input.setFocus()

        # Prepare Status Bar
        self.statusBar().showMessage("", 0)

    def remove_ads(self, view):
        selectors_js = ", ".join(f'"{s}"' for s in self.blocked_selectors)

        js_code = f"""
        (function() {{
            const selectors = [{selectors_js}];
            
            function removeAds() {{
                selectors.forEach(selector => {{
                    document.querySelectorAll(selector).forEach(el => {{
                        el.remove();
                    }});
                }});
            }}
            
            // Remove existing ads
            removeAds();
            
            // Watch for new elements
            const observer = new MutationObserver(removeAds);
            observer.observe(document.body, {{
                childList: true,
                subtree: true
            }});
        }})();
        """

        view.page().runJavaScript(js_code)

    def setup_shortcuts(self):
        shortcut_ctrl_l = QShortcut(QKeySequence("Ctrl+L"), self)
        shortcut_ctrl_l.activated.connect(self.focus_search)

        shortcut_f6 = QShortcut(QKeySequence("F6"), self)
        shortcut_f6.activated.connect(self.focus_search)

        shortcut_f3 = QShortcut(QKeySequence("F3"), self)
        shortcut_f3.activated.connect(self.handle_search_and_pdf_navigation)
        shortcut_f3 = QShortcut(QKeySequence("Ctrl+F"), self)
        shortcut_f3.activated.connect(self.handle_search_and_pdf_navigation)

        shortcut_shift_f3 = QShortcut(QKeySequence("Shift+F3"), self)
        shortcut_shift_f3.activated.connect(self.pdf_panel.go_to_previous)

        for i in range(1, 10):
            shortcut = QShortcut(QKeySequence(f"Alt+{i}"), self)
            shortcut.activated.connect(lambda num=i: self.play_cambridge_audio(num))

    def play_cambridge_audio(self, audio_num=1):
        js_code = f"audio{audio_num}.load(); audio{audio_num}.play();"
        self.cambridge_en_view.page().runJavaScript(js_code)

    def handle_search_and_pdf_navigation(self):
        if self.search_input.hasFocus():
            self.pdf_panel.go_to_next()
        else:
            self.focus_search()

    def focus_search(self):
        self.search_input.setFocus()
        self.search_input.selectAll()

    def load_history(self):
        if self.history_file.exists():
            try:
                with open(self.history_file, "r") as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                return []
        return []

    def save_history(self):
        # Cancel previous save if still running
        if self.save_worker and self.save_worker.isRunning():
            self.save_worker.wait()

        # Save in background
        self.save_worker = SaveWorker(self.history_file, self.history.copy())
        self.save_worker.start()

    def add_to_history(self, word):
        today = datetime.now().date()
        existing_entry = None
        existing_index = None

        # Find existing entry
        for i, item in enumerate(self.history):
            if item["word"] == word:
                existing_entry = item
                existing_index = i
                break

        if existing_entry:
            existing_date = datetime.fromisoformat(existing_entry["date"]).date()

            if existing_date == today:
                # Same day - move to top, update timestamp
                self.history.pop(existing_index)
                entry = {"word": word, "date": datetime.now().isoformat()}
                self.history.insert(0, entry)
            else:
                # Different day - keep old entry, just add new one
                entry = {"word": word, "date": datetime.now().isoformat()}
                self.history.insert(0, entry)
                self.show_previous_search_notice(word, existing_date)
        else:
            # New word
            entry = {"word": word, "date": datetime.now().isoformat()}
            self.history.insert(0, entry)

        self.save_history()
        self.update_history_list()

    def show_previous_search_notice(self, word, original_date):
        formatted_date = original_date.strftime("%Y-%m-%d")
        self.statusBar().setStyleSheet("background-color: #fff3cd; color: #856404;")
        self.statusBar().showMessage(
            f'"{word}" was previously searched on {formatted_date}', 0
        )

    def update_history_list(self):
        self.history_list.setUpdatesEnabled(False)  # Pause rendering
        self.history_list.clear()

        for entry in self.history:
            word = entry["word"]
            date_str = entry["date"]
            try:
                date_obj = datetime.fromisoformat(date_str)
                formatted_date = date_obj.strftime("%Y-%m-%d %H:%M")
            except (ValueError, TypeError):
                formatted_date = date_str

            item = QListWidgetItem()
            item.setData(Qt.UserRole, {"word": word, "date": formatted_date})
            self.history_list.addItem(item)
        self.history_list.setUpdatesEnabled(True)  # Resume and repaint once

    def on_history_click(self, item):
        word = item.data(Qt.UserRole)["word"]
        self.search_input.setText(word)
        self.search()

    def clear_history(self):
        self.history = []
        self.save_history()
        self.update_history_list()

    def show_history_context_menu(self, position):
        item = self.history_list.itemAt(position)
        if not item:
            return

        menu = QMenu()
        delete_action = menu.addAction("Delete")
        search_action = menu.addAction("Search again")

        action = menu.exec_(self.history_list.mapToGlobal(position))

        if action == delete_action:
            word = item.data(Qt.UserRole)["word"]
            for i, entry in enumerate(self.history):
                if entry["word"] == word:
                    self.history.pop(i)
                    self.history_list.takeItem(i)
                    break
            self.save_history()
        elif action == search_action:
            word = item.data(Qt.UserRole)["word"]
            self.search_input.setText(word)
            self.search()

    def search(self):
        word = self.search_input.text().strip()
        if word:
            self.add_to_history(word)

            encoded_word = quote(word)

            cambridge_en_url = (
                f"https://dictionary.cambridge.org/dictionary/english/{encoded_word}"
            )
            self.cambridge_en_view.setUrl(QUrl(cambridge_en_url))

            cambridge_pl_url = f"https://dictionary.cambridge.org/pl/dictionary/english-polish/{encoded_word}"
            self.cambridge_pl_view.setUrl(QUrl(cambridge_pl_url))

            # Two Google searches
            google_meaning_url = (
                f"https://www.google.pl/search?q={encoded_word}+meaning"
            )
            self.google_meaning_view.setUrl(QUrl(google_meaning_url))

            google_translate_url = f"https://translate.google.com/?sl=en&tl=pl&text={encoded_word}&op=translate"
            google_translate_url = (
                f"https://www.google.pl/search?q={encoded_word}+po+polsku"
            )
            self.google_translate_view.setUrl(QUrl(google_translate_url))

            babla_url = f"https://www.google.pl/search?q={encoded_word}+po+polsku"
            self.babla_view.setUrl(QUrl(babla_url))

            self.pdf_panel.search(word)

    def get_correction(self):
        js_code = """
        (function() {
            const link = document.querySelector('a[href*="spell=1"]');
            if (!link) return null;
            
            const fullText = link.textContent.trim().replace(/\s+/g, ' ');
            
            // Remove the trailing "meaning" added by the app
            return fullText.replace(/\s+meaning$/i, '');
        })();
        """
        self.google_meaning_view.page().runJavaScript(
            js_code, lambda result: self.handle_google_correction_signal.emit(result)
        )

    def handle_google_correction(self, result):
        if result:
            corrected = result.replace(" meaning", "").strip()
            self.search_input.setText(corrected)
            self.search()

    def closeEvent(self, event):
        self.pdf_panel.close_doc()
        super().closeEvent(event)


def main():
    app = QApplication(sys.argv)
    window = TranslationTool()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
