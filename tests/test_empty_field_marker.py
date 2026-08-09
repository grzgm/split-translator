"""The empty-field marker must never change a field's geometry.

Filling a field is not allowed to move anything: the marker that shows which
fields are still blank has to be purely a colour change. That rules out a
stylesheet ``border``, which switches a widget out of the native style's box
model and resizes it (a line edit loses 2px of height, the POS combo over half
its width), so every widget below and beside it would jump the moment the field
was typed into. These tests pin the sizes across both states, on the real
widgets a sense row builds."""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QPalette
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFormLayout,
    QLineEdit,
    QWidget,
)

from split_translator.flashcard_editor_base import (
    _EMPTY_TINT,
    SenseRow,
    _mark_empty,
)

app = QApplication.instance() or QApplication([])


def _base(field) -> str:
    return field.palette().color(QPalette.ColorRole.Base).name()


def _default_base() -> str:
    return QApplication.palette().color(QPalette.ColorRole.Base).name()


class GeometryTests(unittest.TestCase):
    """Empty and filled are the same size, for every marked widget type."""

    def _sizes(self, field, fill):
        _mark_empty(field)
        empty = field.sizeHint()
        fill(field)
        _mark_empty(field)
        return empty, field.sizeHint()

    def test_a_line_edit_keeps_its_size_when_filled(self):
        empty, filled = self._sizes(QLineEdit(), lambda f: f.setText("run"))
        self.assertEqual(empty, filled)

    def test_the_pos_combo_keeps_its_size_when_filled(self):
        row = SenseRow()
        empty, filled = self._sizes(
            row.pos_combo, lambda f: f.setCurrentText("v")
        )
        self.assertEqual(empty, filled)

    def test_a_sense_row_field_keeps_its_size_when_filled(self):
        row = SenseRow()
        empty = row.polish_input.sizeHint()
        row.polish_input.setText("biegac")
        self.assertEqual(empty, row.polish_input.sizeHint())

    def test_the_marker_never_uses_a_stylesheet(self):
        # The mechanism, not just the symptom: a stylesheet on these controls is
        # what resized them, so the marker must leave the stylesheet alone.
        field = QLineEdit()
        _mark_empty(field)
        self.assertEqual(field.styleSheet(), "")
        field.setText("run")
        _mark_empty(field)
        self.assertEqual(field.styleSheet(), "")

    def test_filling_one_row_does_not_move_the_rows_below(self):
        # The user-visible requirement, end to end: type into the first field of
        # a form and nothing else may move.
        host = QWidget()
        form = QFormLayout(host)
        fields = []
        for i in range(4):
            field = QLineEdit()
            field.textChanged.connect(lambda _=None, f=field: _mark_empty(f))
            _mark_empty(field)
            form.addRow(f"Row {i}", field)
            fields.append(field)
        host.resize(400, 300)
        host.show()
        app.processEvents()
        before = [(f.x(), f.y(), f.size()) for f in fields]
        fields[0].setText("run")
        app.processEvents()
        self.assertEqual(before, [(f.x(), f.y(), f.size()) for f in fields])


class TintTests(unittest.TestCase):
    """The marker itself: tinted while blank, default background once filled."""

    def test_an_empty_field_is_tinted(self):
        field = QLineEdit()
        _mark_empty(field)
        self.assertEqual(_base(field), _EMPTY_TINT)

    def test_a_filled_field_returns_to_the_default_background(self):
        field = QLineEdit()
        _mark_empty(field)
        field.setText("run")
        _mark_empty(field)
        self.assertEqual(_base(field), _default_base())

    def test_a_whitespace_only_field_counts_as_empty(self):
        field = QLineEdit()
        field.setText("   ")
        _mark_empty(field)
        self.assertEqual(_base(field), _EMPTY_TINT)

    def test_an_editable_combo_passes_the_tint_to_its_editor(self):
        # The text a combo shows is drawn by its internal line edit, so the tint
        # is only visible if it reaches that child.
        combo = QComboBox()
        combo.setEditable(True)
        combo.addItems(["n", "v"])
        combo.setCurrentText("")
        _mark_empty(combo)
        self.assertEqual(_base(combo.lineEdit()), _EMPTY_TINT)

    def test_a_filled_combo_returns_to_the_default_background(self):
        row = SenseRow()
        row.pos_combo.setCurrentText("v")
        self.assertEqual(_base(row.pos_combo), _default_base())

    def test_a_field_is_marked_as_it_is_typed_into_and_cleared(self):
        # The editor wires textChanged to the marker; the round trip has to work
        # in both directions, not just on the first fill.
        row = SenseRow()
        self.assertEqual(_base(row.english_input), _EMPTY_TINT)
        row.english_input.setText("to move fast")
        self.assertEqual(_base(row.english_input), _default_base())
        row.english_input.clear()
        self.assertEqual(_base(row.english_input), _EMPTY_TINT)


if __name__ == "__main__":
    unittest.main()
