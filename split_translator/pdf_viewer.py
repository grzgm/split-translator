"""Single-PDF viewer widget with lazy rendering, search highlighting and a search worker."""

import pymupdf
from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QLabel, QScrollArea, QVBoxLayout, QWidget


class SearchWorker(QThread):
    """Searches a PDF document for a term off the UI thread."""

    # Declared as `object` rather than `list`/`dict`: the payload holds pymupdf.Rect
    # values, which PySide6 cannot marshal into a QVariantMap across a queued (cross-thread)
    # connection. With `object` PySide6 passes the Python objects by reference unchanged.
    # (PyQt5's sip passed them through regardless, which is why this worked before.)
    finished = Signal(object, object)  # matches, page_matches

    def __init__(self, doc, term):
        super().__init__()
        self.doc = doc
        self.term = term
        self.cancelled = False  # Flag to check.

    def run(self):
        matches = []
        page_matches = {}

        for page_num in range(len(self.doc)):
            if self.cancelled:  # Check before each page.
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


class PDFViewer(QWidget):
    """Widget that displays a single PDF with lazy loading and search."""

    def __init__(self, pdf_path, parent=None):
        super().__init__(parent)
        self.doc = pymupdf.open(pdf_path)
        self.page_labels = []
        self.rendered_pages = set()
        self.scale = 1.0
        self.page_matches = {}
        self.is_refreshing = False  # Flag to prevent re-entry.

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
        self.pages_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.scroll_area.setWidget(self.pages_container)
        self.scroll_area.verticalScrollBar().valueChanged.connect(self.on_scroll)

        layout.addWidget(self.scroll_area)

    def calc_fit_scale(self):
        viewport = self.scroll_area.viewport()
        scroll_area_width = viewport.rect().width() - 50
        scroll_area_height = viewport.rect().height()

        # Guard against zero dimensions (hidden widget).
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

        # Skip if scale hasn't changed significantly.
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
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
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
            pix.samples,
            pix.width,
            pix.height,
            pix.stride,
            QImage.Format.Format_RGB888,
        )

        if highlights:
            img = img.copy()
            painter = QPainter(img)
            painter.setCompositionMode(
                QPainter.CompositionMode.CompositionMode_Multiply
            )
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

        # Delay to ensure geometry is updated after tab switch.
        QTimer.singleShot(50, lambda: self._do_refresh_scale(current_page))

    def _do_refresh_scale(self, restore_page):
        """Actual scale refresh after delay."""
        if not self.page_labels:
            self.is_refreshing = False
            return

        new_scale = self.calc_fit_scale()

        # Only refresh if scale actually changed significantly.
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

        # Restore scroll position and render.
        QTimer.singleShot(0, lambda: self._restore_and_render(restore_page))

    def _restore_and_render(self, page_num):
        """Restore scroll position and render visible pages."""
        self.scroll_to_page(page_num)
        self.render_visible_pages()
        self.is_refreshing = False

    def close_doc(self):
        self.doc.close()
