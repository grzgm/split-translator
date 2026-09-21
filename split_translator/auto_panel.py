"""The Automatic anchors tab as a widget: which original paragraphs a batch
covers (a start and a count) and the buttons that generate or remove it.

It holds numbers and announces requests; it knows nothing about books, the
aligner or storage, so its owner decides what a request means, as with
SkipPanel. Paragraphs are shown counted from 1 and handed over as 0-based
positions."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

#: How many original paragraphs a batch covers unless changed.
DEFAULT_COUNT = 100


class AutoAnchorPanel(QWidget):
    """A start and a count of original paragraphs, with Generate and Remove."""

    #: (start position, count) when Generate is clicked.
    generate = Signal(int, int)
    #: (start position, count) when Remove automatic is clicked.
    remove = Signal(int, int)
    #: The From selection button was clicked; the owner knows the selection
    #: and calls set_start.
    from_selection = Signal()

    def __init__(self, original_count: int, parent=None):
        super().__init__(parent)
        self._paragraphs = original_count
        self._busy = False
        self.init_ui()
        self._update_enabled()

    def init_ui(self) -> None:
        outer = QVBoxLayout(self)
        top = max(1, self._paragraphs)

        self.start_box = QSpinBox()
        self.start_box.setRange(1, top)
        # A typed value commits once, on Enter or focus-out (see SkipPanel).
        self.start_box.setKeyboardTracking(False)
        self.start_box.setToolTip(
            "The first original paragraph of the batch, counted from 1"
        )
        self.from_selection_button = QPushButton("From selection")
        self.from_selection_button.setToolTip(
            "Start the batch at the paragraph selected in the original"
        )
        self.from_selection_button.clicked.connect(
            lambda _=False: self.from_selection.emit()
        )
        self.count_box = QSpinBox()
        self.count_box.setRange(1, top)
        self.count_box.setValue(min(DEFAULT_COUNT, top))
        self.count_box.setKeyboardTracking(False)
        self.count_box.setToolTip("How many original paragraphs the batch covers")

        grid = QGridLayout()
        start_row = QHBoxLayout()
        start_row.addWidget(self.start_box, 1)
        start_row.addWidget(self.from_selection_button)
        grid.addWidget(QLabel("Start"), 0, 0)
        grid.addLayout(start_row, 0, 1)
        grid.addWidget(QLabel("Count"), 1, 0)
        grid.addWidget(self.count_box, 1, 1)
        outer.addLayout(grid)

        self.generate_button = QPushButton("Generate")
        self.generate_button.setToolTip(
            "Match the batch's paragraphs automatically, replacing its earlier "
            "automatic anchors"
        )
        self.generate_button.clicked.connect(
            lambda _=False: self.generate.emit(self.start(), self.count())
        )
        self.remove_button = QPushButton("Remove automatic")
        self.remove_button.setToolTip("Remove the batch's automatic anchors")
        self.remove_button.clicked.connect(
            lambda _=False: self.remove.emit(self.start(), self.count())
        )
        buttons = QHBoxLayout()
        buttons.addWidget(self.generate_button)
        buttons.addWidget(self.remove_button)
        buttons.addStretch()
        outer.addLayout(buttons)
        outer.addStretch()

    def start(self) -> int:
        """The batch's first original paragraph, as a 0-based position."""
        return self.start_box.value() - 1

    def count(self) -> int:
        return self.count_box.value()

    def set_start(self, position: int) -> None:
        """Show a 0-based position as the start, clamped to the edition."""
        last = max(0, self._paragraphs - 1)
        self.start_box.setValue(min(max(0, position), last) + 1)

    def set_busy(self, busy: bool) -> None:
        """Disable Generate and Remove automatic while a batch is aligned."""
        self._busy = busy
        self._update_enabled()

    def _update_enabled(self) -> None:
        has_paragraphs = self._paragraphs > 0
        for widget in (self.start_box, self.count_box, self.from_selection_button):
            widget.setEnabled(has_paragraphs)
        for button in (self.generate_button, self.remove_button):
            button.setEnabled(has_paragraphs and not self._busy)
