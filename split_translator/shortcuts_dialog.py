"""A modal cheat-sheet of the app's keyboard shortcuts, built from the shortcut
registry (see shortcuts.py). Opened with Ctrl+/; dismissed with Esc or Close."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGridLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from .shortcuts import GROUP_ORDER


class ShortcutsDialog(QDialog):
    """Renders the given ShortcutEntry list as a read-only, group-headed table.

    Purely presentational: it takes the entries and builds widgets, and knows
    nothing about the main window or the handlers. Groups appear in GROUP_ORDER,
    but only those actually present among the entries."""

    def __init__(self, entries, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Keyboard shortcuts")

        outer = QVBoxLayout(self)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(4, 4, 4, 4)

        for group in GROUP_ORDER:
            group_entries = [e for e in entries if e.group == group]
            if not group_entries:
                continue

            heading = QLabel(group)
            heading_font = heading.font()
            heading_font.setBold(True)
            heading.setFont(heading_font)
            content_layout.addWidget(heading)

            grid = QGridLayout()
            grid.setColumnStretch(1, 1)
            row = 0
            for entry in group_entries:
                keys = QLabel(entry.keys)
                keys.setTextInteractionFlags(Qt.TextSelectableByMouse)
                keys_font = keys.font()
                keys_font.setBold(True)
                keys.setFont(keys_font)
                description = QLabel(entry.description)
                description.setWordWrap(True)
                grid.addWidget(keys, row, 0, Qt.AlignTop)
                grid.addWidget(description, row, 1)
                row += 1
                if entry.note:
                    note = QLabel(entry.note)
                    note.setWordWrap(True)
                    note.setStyleSheet("color: gray; font-size: 11px;")
                    grid.addWidget(note, row, 1)
                    row += 1

            grid_holder = QFrame()
            grid_holder.setLayout(grid)
            content_layout.addWidget(grid_holder)

        content_layout.addStretch()
        scroll.setWidget(content)
        outer.addWidget(scroll)

        # Close button (Esc also dismisses via QDialog's native reject).
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

        self.resize(520, 460)
