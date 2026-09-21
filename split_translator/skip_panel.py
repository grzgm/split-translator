"""The skip fields as a widget: how many paragraphs each edition leaves out at
its start and at its end.

Front matter (a title page, an introduction only one edition has) and back
matter (a glossary) would otherwise be matched against the story. The widget
holds counts and announces changes; it knows nothing about books, views or
storage, so its owner decides what a change means, as with NormalisePanel."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .normalise_spec import ORIGINAL_SIDE, TRANSLATION_SIDE

AT_START = "start"
AT_END = "end"

#: One column per edition, in the order the editor shows them.
_COLUMNS = ((ORIGINAL_SIDE, "Original"), (TRANSLATION_SIDE, "Translation"))

#: One row per field.
_ROWS = ((AT_START, "Skip at start"), (AT_END, "Skip at end"))

_TOOLTIPS = {
    AT_START: "Skip every paragraph before the one selected in that edition",
    AT_END: "Skip every paragraph after the one selected in that edition",
}


class SkipPanel(QWidget):
    """Two counts per edition, each with a From selection button."""

    #: (side, AT_START or AT_END) after a user edit. Seeding never emits.
    changed = Signal(str, str)
    #: (side, AT_START or AT_END) when a From selection button is clicked; the
    #: owner knows the selection and sets the box.
    from_selection = Signal(str, str)

    def __init__(self, original_count: int, translation_count: int, parent=None):
        super().__init__(parent)
        self._counts = {
            ORIGINAL_SIDE: original_count,
            TRANSLATION_SIDE: translation_count,
        }
        # True while boxes are filled or re-ranged programmatically, so that
        # never reads back as a user edit.
        self._loading = False
        self._boxes: dict[tuple[str, str], QSpinBox] = {}
        self._buttons: dict[tuple[str, str], QPushButton] = {}
        self.init_ui()
        for side, _title in _COLUMNS:
            self._update_ranges(side)

    def init_ui(self) -> None:
        outer = QVBoxLayout(self)
        grid = QGridLayout()
        for column, (_side, title) in enumerate(_COLUMNS, start=1):
            label = QLabel(title)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            grid.addWidget(label, 0, column)
        for row, (which, title) in enumerate(_ROWS, start=1):
            grid.addWidget(QLabel(title), row, 0)
            for column, (side, _title) in enumerate(_COLUMNS, start=1):
                box = QSpinBox()
                # A typed value commits once, on Enter or focus-out, rather than
                # after every keystroke (see NormalisePanel).
                box.setKeyboardTracking(False)
                box.valueChanged.connect(
                    lambda _=None, s=side, w=which: self._on_edited(s, w)
                )
                button = QPushButton("From selection")
                button.setToolTip(_TOOLTIPS[which])
                button.clicked.connect(
                    lambda _=False, s=side, w=which: self.from_selection.emit(s, w)
                )
                cell = QHBoxLayout()
                cell.addWidget(box, 1)
                cell.addWidget(button)
                grid.addLayout(cell, row, column)
                self._boxes[(side, which)] = box
                self._buttons[(side, which)] = button
        outer.addLayout(grid)
        outer.addStretch()

    def box(self, side: str, which: str) -> QSpinBox:
        return self._boxes[(side, which)]

    def button(self, side: str, which: str) -> QPushButton:
        return self._buttons[(side, which)]

    def skip(self, side: str) -> tuple[int, int]:
        """(paragraphs skipped at the start, paragraphs skipped at the end)."""
        return (
            self.box(side, AT_START).value(),
            self.box(side, AT_END).value(),
        )

    def set_skip(self, side: str, start: int, end: int) -> None:
        """Fill one edition's boxes without announcing anything, clamped so at
        least one paragraph stays kept."""
        room = max(0, self._counts[side] - 1)
        start = min(max(0, start), room)
        end = min(max(0, end), room - start)
        self._loading = True
        try:
            self.box(side, AT_START).setMaximum(room)
            self.box(side, AT_END).setMaximum(room)
            self.box(side, AT_START).setValue(start)
            self.box(side, AT_END).setValue(end)
        finally:
            self._loading = False
        self._update_ranges(side)

    def _update_ranges(self, side: str) -> None:
        # Each box may take whatever the other leaves, minus the one paragraph
        # that always stays kept. Lowering a maximum never clamps a value here,
        # because the two values already fit together.
        count = self._counts[side]
        room = max(0, count - 1)
        start, end = self.skip(side)
        self._loading = True
        try:
            self.box(side, AT_START).setMaximum(max(0, room - end))
            self.box(side, AT_END).setMaximum(max(0, room - start))
        finally:
            self._loading = False
        for which, _title in _ROWS:
            self.box(side, which).setEnabled(count > 0)
            self.button(side, which).setEnabled(count > 0)

    def _on_edited(self, side: str, which: str) -> None:
        if self._loading:
            return
        self._update_ranges(side)
        self.changed.emit(side, which)
