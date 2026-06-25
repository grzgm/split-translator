"""Search-history panel: persistent list of looked-up words with a custom row delegate."""

import json
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QThread, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QStyledItemDelegate,
    QVBoxLayout,
    QWidget,
)


class SimpleDelegate(QStyledItemDelegate):
    """Draws a history row as a large word with a small grey date underneath."""

    def paint(self, painter, option, index):
        data = index.data(Qt.ItemDataRole.UserRole)
        word = data["word"]
        date = data["date"]

        painter.save()

        # Draw word (large font).
        font = painter.font()
        font.setPointSize(12)
        painter.setFont(font)
        painter.drawText(
            option.rect.adjusted(5, 5, 0, 0), Qt.AlignmentFlag.AlignLeft, word
        )

        # Draw date (small, grey).
        font.setPointSize(8)
        painter.setFont(font)
        painter.setPen(QColor(128, 128, 128))
        painter.drawText(
            option.rect.adjusted(5, 22, 0, 0), Qt.AlignmentFlag.AlignLeft, date
        )

        painter.restore()

    def sizeHint(self, option, index):
        return QSize(option.rect.width(), 40)


class SaveWorker(QThread):
    """Writes history to disk off the UI thread."""

    def __init__(self, filepath, data):
        super().__init__()
        self.filepath = filepath
        self.data = data

    def run(self):
        with open(self.filepath, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2)


class HistoryPanel(QWidget):
    """Sidebar widget that owns the search history and persists it to disk.

    Emits ``word_selected`` when the user picks a word (click, context menu, or re-search)
    and ``previous_search`` when a word that was searched on an earlier day is added again.
    """

    word_selected = Signal(str)
    previous_search = Signal(str, str)  # word, formatted original date

    def __init__(self, history_file: Path, parent=None):
        super().__init__(parent)
        self.history_file = history_file
        self.save_worker = None
        self.history = self.load_history()

        self.init_ui()
        self.update_history_list()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.history_list = QListWidget()
        self.history_list.setItemDelegate(SimpleDelegate())
        self.history_list.itemClicked.connect(self.on_history_click)
        self.history_list.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        self.history_list.customContextMenuRequested.connect(
            self.show_history_context_menu
        )
        layout.addWidget(self.history_list)

        clear_button = QPushButton("Clear History")
        clear_button.clicked.connect(self.clear_history)
        layout.addWidget(clear_button)

    def load_history(self):
        if self.history_file.exists():
            try:
                with open(self.history_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                return []
        return []

    def save_history(self):
        # Cancel previous save if still running.
        if self.save_worker and self.save_worker.isRunning():
            self.save_worker.wait()

        # Save in background.
        self.save_worker = SaveWorker(self.history_file, self.history.copy())
        self.save_worker.start()

    def add_to_history(self, word):
        today = datetime.now().date()
        existing_entry = None
        existing_index = None

        # Find existing entry.
        for i, item in enumerate(self.history):
            if item["word"] == word:
                existing_entry = item
                existing_index = i
                break

        if existing_entry:
            existing_date = datetime.fromisoformat(existing_entry["date"]).date()

            if existing_date == today:
                # Same day - move to top, update timestamp.
                self.history.pop(existing_index)
                entry = {"word": word, "date": datetime.now().isoformat()}
                self.history.insert(0, entry)
            else:
                # Different day - keep old entry, just add new one.
                entry = {"word": word, "date": datetime.now().isoformat()}
                self.history.insert(0, entry)
                self.previous_search.emit(word, existing_date.strftime("%Y-%m-%d"))
        else:
            # New word.
            entry = {"word": word, "date": datetime.now().isoformat()}
            self.history.insert(0, entry)

        self.save_history()
        self.update_history_list()

    def remove_word(self, word):
        """Remove every history entry for a word (used when Get Correction
        replaces a misspelled lookup). Saves and refreshes only if something
        was removed."""
        remaining = [entry for entry in self.history if entry["word"] != word]
        if len(remaining) == len(self.history):
            return
        self.history = remaining
        self.save_history()
        self.update_history_list()

    def update_history_list(self):
        self.history_list.setUpdatesEnabled(False)  # Pause rendering.
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
            item.setData(
                Qt.ItemDataRole.UserRole, {"word": word, "date": formatted_date}
            )
            self.history_list.addItem(item)
        self.history_list.setUpdatesEnabled(True)  # Resume and repaint once.

    def on_history_click(self, item):
        word = item.data(Qt.ItemDataRole.UserRole)["word"]
        self.word_selected.emit(word)

    def clear_history(self):
        self.history = []
        self.save_history()
        self.update_history_list()

    def shutdown(self):
        """Wait for any in-flight save so the worker thread is not destroyed mid-write."""
        if self.save_worker and self.save_worker.isRunning():
            self.save_worker.wait()

    def show_history_context_menu(self, position):
        item = self.history_list.itemAt(position)
        if not item:
            return

        menu = QMenu()
        delete_action = menu.addAction("Delete")
        search_action = menu.addAction("Search again")

        action = menu.exec(self.history_list.mapToGlobal(position))

        if action == delete_action:
            word = item.data(Qt.ItemDataRole.UserRole)["word"]
            for i, entry in enumerate(self.history):
                if entry["word"] == word:
                    self.history.pop(i)
                    self.history_list.takeItem(i)
                    break
            self.save_history()
        elif action == search_action:
            word = item.data(Qt.ItemDataRole.UserRole)["word"]
            self.word_selected.emit(word)
