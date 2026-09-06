"""The normalisation multipliers as a widget: six spin boxes and a reset.

Three values per edition (see normalise_spec), laid out as a small grid with
one column per edition. The widget holds numbers and announces changes; it knows
nothing about books, views or storage, so its owner decides what a change means.
That is the same split every other panel here follows.

Greying it out is the owner's job too, done by calling setEnabled(False) on the
whole widget: while the Normalise toggle is off the injected stylesheet is
disabled outright, so the multipliers do nothing and live-looking controls would
be a lie."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .normalise_spec import (
    MAX_SCALE,
    MIN_SCALE,
    ORIGINAL_SIDE,
    TRANSLATION_SIDE,
    NormaliseSpec,
)

#: One row per NormaliseSpec field: the field name and its label. The names are
#: the dataclass's own, so building a spec from the boxes needs no mapping.
_ROWS = (
    ("font", "Font"),
    ("line_height", "Line height"),
    ("gap", "Paragraph gap"),
)

#: One column per edition, in the order the editor shows them.
_COLUMNS = ((ORIGINAL_SIDE, "Original"), (TRANSLATION_SIDE, "Translation"))

#: How far one arrow click moves a multiplier. Small enough to trim by, large
#: enough that bringing two editions into step is a handful of clicks.
_STEP = 0.05


class NormalisePanel(QWidget):
    """Six multipliers, three per edition, plus a reset to the default spec."""

    #: (side, NormaliseSpec) for the side that just changed. Only one side is
    #: ever announced per edit; reset announces both, in column order.
    changed = Signal(str, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        # True while the boxes are being filled programmatically, so seeding
        # stored values never reads back as a user edit (the same guard the
        # workspace dialog uses when loading a workspace into its form).
        self._loading = False
        self._boxes: dict[tuple[str, str], QDoubleSpinBox] = {}
        self.init_ui()
        self._update_reset()

    def init_ui(self) -> None:
        outer = QVBoxLayout(self)

        grid = QGridLayout()
        for column, (_side, title) in enumerate(_COLUMNS, start=1):
            label = QLabel(title)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            grid.addWidget(label, 0, column)
        for row, (field, title) in enumerate(_ROWS, start=1):
            grid.addWidget(QLabel(title), row, 0)
            for column, (side, _title) in enumerate(_COLUMNS, start=1):
                box = self._make_box(side, field)
                self._boxes[(side, field)] = box
                grid.addWidget(box, row, column)
        outer.addLayout(grid)

        # The grid sits at the top; the reset goes to the bottom right, the same
        # shape the workspace dialog's Save row has.
        outer.addStretch()
        buttons = QHBoxLayout()
        buttons.addStretch()
        self.reset_button = QPushButton("Reset to default")
        self.reset_button.setToolTip(
            "Put every multiplier back to 1.00x, the spacing the app uses "
            "when nothing is customised"
        )
        self.reset_button.clicked.connect(self.reset)
        buttons.addWidget(self.reset_button)
        outer.addLayout(buttons)

    def _make_box(self, side: str, field: str) -> QDoubleSpinBox:
        box = QDoubleSpinBox()
        box.setRange(MIN_SCALE, MAX_SCALE)
        box.setSingleStep(_STEP)
        box.setDecimals(2)
        # The suffix is what stops these reading as sizes: 0.90x is nine tenths
        # of the default, not nine tenths of a pixel.
        box.setSuffix("x")
        box.setValue(1.0)
        box.valueChanged.connect(lambda _=None, s=side: self._on_edited(s))
        return box

    # --- reading and writing the values ---------------------------------

    def box(self, side: str, field: str) -> QDoubleSpinBox:
        """One side's spin box for one field. The tests drive the panel through
        this rather than reaching into a private dict."""
        return self._boxes[(side, field)]

    def spec(self, side: str) -> NormaliseSpec:
        """One edition's multipliers as they stand in the boxes."""
        return NormaliseSpec(
            **{field: self.box(side, field).value() for field, _ in _ROWS}
        )

    def specs(self) -> tuple[NormaliseSpec, NormaliseSpec]:
        """Both editions', in column order."""
        return (self.spec(ORIGINAL_SIDE), self.spec(TRANSLATION_SIDE))

    def set_specs(
        self, original: NormaliseSpec, translation: NormaliseSpec
    ) -> None:
        """Fill the boxes from stored values without announcing anything.
        Seeding is not a user edit, so nothing is applied or persisted off it."""
        self._loading = True
        try:
            for side, spec in ((ORIGINAL_SIDE, original), (TRANSLATION_SIDE, translation)):
                for field, _title in _ROWS:
                    self.box(side, field).setValue(getattr(spec, field))
        finally:
            self._loading = False
        self._update_reset()

    def reset(self) -> None:
        """Put every field back to 1.00x and announce both sides, so an owner
        with two views to update hears about each of them."""
        self.set_specs(NormaliseSpec(), NormaliseSpec())
        for side, _title in _COLUMNS:
            self.changed.emit(side, self.spec(side))

    # --- edits ----------------------------------------------------------

    def _on_edited(self, side: str) -> None:
        if self._loading:
            return
        self._update_reset()
        self.changed.emit(side, self.spec(side))

    def _update_reset(self) -> None:
        # Live only while something differs from the default, so a greyed Reset
        # means there is nothing to undo.
        self.reset_button.setEnabled(
            not all(spec.is_default for spec in self.specs())
        )
