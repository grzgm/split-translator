"""The Automatic anchors tab as a widget: which original paragraphs a batch
covers (the selected paragraph and a count) and the buttons that generate or
remove it.

The batch starts where the selection is. There is nothing to type: the owner
reports the paragraph selected in the original and the panel shows it, so the
batch is always the passage being looked at. With no paragraph selected there
is no batch, and Generate and Remove are disabled rather than acting on a
number left over from last time.

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
    """The selected paragraph and a count, with Generate and Remove."""

    #: (start position, count) when Generate is clicked.
    generate = Signal(int, int)
    #: (start position, count) when Remove automatic is clicked.
    remove = Signal(int, int)

    def __init__(self, original_count: int, parent=None):
        super().__init__(parent)
        self._paragraphs = original_count
        self._busy = False
        #: The selected original paragraph as a 0-based position, or None when
        #: nothing is selected, which is how the editor opens.
        self._selected: int | None = None
        self.init_ui()
        self._show_selected()
        self._update_enabled()

    def init_ui(self) -> None:
        outer = QVBoxLayout(self)
        top = max(1, self._paragraphs)

        # Where the batch starts, which is the selection and so is shown
        # rather than typed.
        self.start_label = QLabel()
        self.start_label.setWordWrap(True)
        self.start_label.setToolTip(
            "The batch starts at the paragraph selected in the original"
        )
        self.count_box = QSpinBox()
        self.count_box.setRange(1, top)
        self.count_box.setValue(min(DEFAULT_COUNT, top))
        self.count_box.setKeyboardTracking(False)
        self.count_box.setToolTip("How many original paragraphs the batch covers")

        grid = QGridLayout()
        grid.addWidget(QLabel("Start"), 0, 0)
        grid.addWidget(self.start_label, 0, 1)
        grid.addWidget(QLabel("Count"), 1, 0)
        grid.addWidget(self.count_box, 1, 1)
        outer.addLayout(grid)

        self.generate_button = QPushButton("Generate")
        self.generate_button.setToolTip(
            "Match the batch's paragraphs automatically, replacing its earlier "
            "automatic anchors"
        )
        self.generate_button.clicked.connect(
            lambda _=False: self._announce(self.generate)
        )
        self.remove_button = QPushButton("Remove automatic")
        self.remove_button.setToolTip("Remove the batch's automatic anchors")
        self.remove_button.clicked.connect(
            lambda _=False: self._announce(self.remove)
        )
        buttons = QHBoxLayout()
        buttons.addWidget(self.generate_button)
        buttons.addWidget(self.remove_button)
        buttons.addStretch()
        outer.addLayout(buttons)
        outer.addStretch()

    def start(self) -> int | None:
        """The batch's first original paragraph as a 0-based position, or None
        when no paragraph is selected and so there is no batch."""
        return self._selected

    def count(self) -> int:
        return self.count_box.value()

    def set_selected(self, position: int | None) -> None:
        """The paragraph selected in the original, as a 0-based position, or
        None when the selection was cleared. A position outside the edition
        counts as nothing selected, so a stale id cannot leave the buttons
        live."""
        if position is None or not 0 <= position < self._paragraphs:
            self._selected = None
        else:
            self._selected = position
        self._show_selected()
        self._update_enabled()

    def set_busy(self, busy: bool) -> None:
        """Disable Generate and Remove automatic while a batch is aligned."""
        self._busy = busy
        self._update_enabled()

    def _announce(self, signal) -> None:
        """Ask for the batch at the selected paragraph. The buttons are
        disabled without a selection, so the guard is belt and braces."""
        if self._selected is None:
            return
        signal.emit(self._selected, self.count())

    def _show_selected(self) -> None:
        if self._selected is None:
            self.start_label.setText("Select a paragraph in the original")
            return
        self.start_label.setText(f"Paragraph {self._selected + 1}")

    def _update_enabled(self) -> None:
        has_paragraphs = self._paragraphs > 0
        self.count_box.setEnabled(has_paragraphs)
        ready = has_paragraphs and self._selected is not None and not self._busy
        for button in (self.generate_button, self.remove_button):
            button.setEnabled(ready)
