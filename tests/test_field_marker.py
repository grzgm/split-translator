"""The empty-field marker helper, on its own.

The marker has to do two things at once: show which fields are still blank, and
never change a field's size or leak onto a field nobody touched. These tests pin
both, including the re-polish that broke the previous implementation."""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QWidget,
)

from split_translator.field_marker import (
    EMPTY_TINT,
    attach_empty_marker,
    mark_empty,
)

app = QApplication.instance() or QApplication([])


def _flag(field):
    """The marker state as the style rule sees it."""
    target = field.lineEdit() if isinstance(field, QComboBox) else field
    return target.property("emptyField")


def _combo(text=""):
    combo = QComboBox()
    combo.setEditable(True)
    combo.addItems(["n", "v"])
    combo.setCurrentText(text)
    return combo


class MarkerStateTests(unittest.TestCase):
    def test_a_blank_field_is_marked(self):
        field = QLineEdit()
        attach_empty_marker(field)
        self.assertEqual(_flag(field), "true")

    def test_a_filled_field_is_not_marked(self):
        field = QLineEdit()
        field.setText("run")
        attach_empty_marker(field)
        self.assertEqual(_flag(field), "false")

    def test_whitespace_only_counts_as_blank(self):
        field = QLineEdit()
        field.setText("   ")
        attach_empty_marker(field)
        self.assertEqual(_flag(field), "true")

    def test_the_marker_follows_the_content_both_ways(self):
        field = QLineEdit()
        attach_empty_marker(field)
        field.setText("run")
        mark_empty(field)
        self.assertEqual(_flag(field), "false")
        field.clear()
        mark_empty(field)
        self.assertEqual(_flag(field), "true")

    def test_marking_twice_is_stable(self):
        field = QLineEdit()
        attach_empty_marker(field)
        mark_empty(field)
        mark_empty(field)
        self.assertEqual(_flag(field), "true")

    def test_a_combo_is_marked_on_its_editor(self):
        # An editable combo draws its text with an internal line edit, so that
        # is the widget the rule has to match; marking the combo itself would
        # pull the combo into the stylesheet box model and resize it.
        combo = _combo()
        attach_empty_marker(combo)
        self.assertEqual(combo.lineEdit().property("emptyField"), "true")
        self.assertIsNone(combo.property("emptyField"))

    def test_a_filled_combo_is_not_marked(self):
        combo = _combo("v")
        attach_empty_marker(combo)
        self.assertEqual(_flag(combo), "false")

    def test_the_rule_carries_the_tint(self):
        field = QLineEdit()
        attach_empty_marker(field)
        self.assertIn(EMPTY_TINT, field.styleSheet())


class GeometryTests(unittest.TestCase):
    """The marker must never resize the field it marks."""

    def test_the_marked_field_is_native_sized_in_both_states(self):
        native = QLineEdit()
        native.setText("run")
        field = QLineEdit()
        field.setText("run")
        attach_empty_marker(field)
        filled = field.sizeHint()
        field.clear()
        mark_empty(field)
        self.assertEqual(filled, native.sizeHint())
        self.assertEqual(field.sizeHint(), native.sizeHint())


class RePolishTests(unittest.TestCase):
    """The regression that killed the palette implementation.

    Qt re-polishes every descendant when a widget's stylesheet changes, and a
    re-polish restores the palette Qt cached for that child at its first polish.
    A property read by a style rule is recomputed instead, so it survives."""

    def _row(self):
        host = QWidget()
        host.setObjectName("senseRow")
        layout = QHBoxLayout(host)
        field = QLineEdit()
        combo = _combo()
        button = QPushButton("x")
        layout.addWidget(field)
        layout.addWidget(combo)
        layout.addWidget(button)
        host.setStyleSheet("#senseRow { border: 2px solid transparent; }")
        return host, field, combo, button

    def test_the_marker_survives_a_parent_stylesheet_change(self):
        host, field, combo, _button = self._row()
        field.setText("run")
        attach_empty_marker(field)
        combo.setCurrentText("v")
        attach_empty_marker(combo)
        host.setStyleSheet("#senseRow { border: 2px solid #0a84ff; }")
        self.assertEqual(_flag(field), "false")
        self.assertEqual(_flag(combo), "false")

    def test_the_marker_survives_a_parent_property_repolish(self):
        host, field, combo, _button = self._row()
        field.setText("run")
        attach_empty_marker(field)
        combo.setCurrentText("v")
        attach_empty_marker(combo)
        host.setProperty("activeRow", "true")
        host.style().unpolish(host)
        host.style().polish(host)
        self.assertEqual(_flag(field), "false")
        self.assertEqual(_flag(combo), "false")

    def test_marking_a_field_leaves_its_neighbours_alone(self):
        _host, field, combo, button = self._row()
        combo_before = combo.sizeHint()
        button_before = button.sizeHint()
        attach_empty_marker(field)
        self.assertEqual(combo.sizeHint(), combo_before)
        self.assertEqual(button.sizeHint(), button_before)


if __name__ == "__main__":
    unittest.main()
