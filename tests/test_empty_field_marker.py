"""The editor's use of the empty-field marker.

Two rules, both of which the editor has broken before. Filling a field must
never resize it, so nothing on the card moves as it is filled in. And a field's
marker must depend on that field alone: activating a sense row or adding an
example must not repaint a field the user already filled."""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFormLayout,
    QLineEdit,
    QWidget,
)

from split_translator.field_marker import attach_empty_marker, mark_empty
from split_translator.flashcard_editor_base import SenseRow

app = QApplication.instance() or QApplication([])


def _flag(field):
    target = field.lineEdit() if isinstance(field, QComboBox) else field
    return target.property("emptyField")


def _filled_row():
    """A sense row with every top field filled, so any marker that appears
    afterwards is wrong."""
    row = SenseRow()
    row.pos_combo.setCurrentText("v")
    row.polish_input.setText("biegac")
    row.english_input.setText("to move fast")
    return row


class GeometryTests(unittest.TestCase):
    def test_a_sense_row_field_keeps_its_size_when_filled(self):
        row = SenseRow()
        empty = row.polish_input.sizeHint()
        row.polish_input.setText("biegac")
        self.assertEqual(empty, row.polish_input.sizeHint())

    def test_the_pos_combo_keeps_its_size_when_filled(self):
        row = SenseRow()
        empty = row.pos_combo.sizeHint()
        row.pos_combo.setCurrentText("v")
        self.assertEqual(empty, row.pos_combo.sizeHint())

    def test_filling_one_row_does_not_move_the_rows_below(self):
        host = QWidget()
        form = QFormLayout(host)
        fields = []
        for i in range(4):
            field = QLineEdit()
            field.textChanged.connect(lambda _=None, f=field: mark_empty(f))
            attach_empty_marker(field)
            form.addRow(f"Row {i}", field)
            fields.append(field)
        host.resize(400, 300)
        host.show()
        app.processEvents()
        before = [(f.x(), f.y(), f.size()) for f in fields]
        fields[0].setText("run")
        app.processEvents()
        self.assertEqual(before, [(f.x(), f.y(), f.size()) for f in fields])


class MarkerFollowsTheFieldTests(unittest.TestCase):
    def test_empty_sense_fields_are_marked(self):
        row = SenseRow()
        self.assertEqual(_flag(row.pos_combo), "true")
        self.assertEqual(_flag(row.polish_input), "true")
        self.assertEqual(_flag(row.english_input), "true")

    def test_filled_sense_fields_are_not_marked(self):
        row = _filled_row()
        self.assertEqual(_flag(row.pos_combo), "false")
        self.assertEqual(_flag(row.polish_input), "false")
        self.assertEqual(_flag(row.english_input), "false")

    def test_a_field_is_re_marked_when_it_is_cleared(self):
        row = _filled_row()
        row.english_input.clear()
        self.assertEqual(_flag(row.english_input), "true")

    def test_a_blank_example_is_marked_and_clears_when_typed(self):
        row = SenseRow()
        row.add_example()
        field = row._example_rows()[0].example_input
        self.assertEqual(_flag(field), "true")
        field.setText("she ran")
        self.assertEqual(_flag(field), "false")

    def test_a_captured_example_is_not_marked(self):
        row = SenseRow()
        row.add_example("she ran")
        field = row._example_rows()[0].example_input
        self.assertEqual(_flag(field), "false")


class ActivationTests(unittest.TestCase):
    """The bug this fixes: the row's own styling used to repaint its children's
    markers, so filled fields lit up when a row was activated or an example was
    added."""

    def test_activating_a_row_does_not_mark_filled_fields(self):
        row = _filled_row()
        row.set_active(True)
        self.assertEqual(_flag(row.pos_combo), "false")
        self.assertEqual(_flag(row.polish_input), "false")
        self.assertEqual(_flag(row.english_input), "false")

    def test_deactivating_a_row_does_not_mark_filled_fields(self):
        row = _filled_row()
        row.set_active(True)
        row.set_active(False)
        self.assertEqual(_flag(row.pos_combo), "false")
        self.assertEqual(_flag(row.polish_input), "false")
        self.assertEqual(_flag(row.english_input), "false")

    def test_adding_an_example_does_not_mark_filled_fields(self):
        row = _filled_row()
        row.add_example()
        self.assertEqual(_flag(row.pos_combo), "false")
        self.assertEqual(_flag(row.polish_input), "false")
        self.assertEqual(_flag(row.english_input), "false")

    def test_activation_still_shows_and_hides_the_highlight(self):
        row = SenseRow()
        row.set_active(True)
        self.assertEqual(row.property("activeRow"), "true")
        row.set_active(False)
        self.assertEqual(row.property("activeRow"), "false")

    def test_the_row_keeps_one_stylesheet_carrying_both_states(self):
        # Swapping the sheet per activation is what re-polished the children.
        row = SenseRow()
        sheet = row.styleSheet()
        row.set_active(True)
        self.assertEqual(row.styleSheet(), sheet)
        self.assertIn("#0a84ff", sheet)
        self.assertIn("transparent", sheet)

    def test_the_row_is_the_same_size_active_and_inactive(self):
        row = SenseRow()
        row.set_active(False)
        inactive = row.sizeHint()
        row.set_active(True)
        self.assertEqual(row.sizeHint(), inactive)


if __name__ == "__main__":
    unittest.main()
