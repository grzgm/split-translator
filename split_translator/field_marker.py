"""The empty-field marker: a light-blue fill on a field that is still blank.

The marker exists so it is easy to see at a glance what remains to be filled. It
is a Qt style rule driven by a dynamic property, which is the third mechanism
tried here; the first two both failed, in ways worth recording so they are not
repeated.

A stylesheet ``border`` (the original) switches a widget out of the native
style's box model and so resizes it. A line edit lost 2px of height and the POS
combo over half its width, which meant filling a field moved every widget below
and beside it.

A ``QPalette`` tint (the replacement) cannot affect geometry, but it does not
survive. Qt re-polishes every descendant when a widget's stylesheet changes, and
that re-polish restores the palette Qt cached for the child at its first polish.
``SenseRow.set_active`` used to set a stylesheet on the row, so activating a row
resurrected the tint each field had when the row was built, marking fields the
user had already filled.

A dynamic property read by a style rule survives both problems. The rule sets
only ``background-color``, which is geometry-neutral, and a re-polish
re-evaluates the rule against the property rather than restoring a snapshot.

The rule is attached to the field itself and never to an ancestor: any
stylesheet on an ancestor pulls every descendant into QStyleSheetStyle and
changes their metrics, which is enough on its own to shrink an editable combo
from 72px to 37px wide."""

from PySide6.QtWidgets import QComboBox

#: The fill a field carries while it is still empty.
EMPTY_TINT = "#eaf2ff"

#: The rule attached to each marked field. It matches on the ``emptyField``
#: dynamic property, which is what lets a re-polish recompute the fill.
EMPTY_FIELD_RULE = (
    f'QLineEdit[emptyField="true"] {{ background-color: {EMPTY_TINT}; }}'
)


def _editor(field):
    """The widget that draws the text. An editable combo delegates to its own
    line edit, so that is where both the rule and the property belong."""
    return field.lineEdit() if isinstance(field, QComboBox) else field


def _is_blank(field) -> bool:
    text = field.currentText() if isinstance(field, QComboBox) else field.text()
    return not text.strip()


def mark_empty(field) -> None:
    """Bring a field's marker in step with its content.

    Wired to ``textChanged``, so it runs on every keystroke and does nothing
    unless the blank/filled state actually flipped: setting a property and
    re-polishing on each character would be wasted work."""
    target = _editor(field)
    value = "true" if _is_blank(field) else "false"
    if target.property("emptyField") == value:
        return
    target.setProperty("emptyField", value)
    target.style().unpolish(target)
    target.style().polish(target)


def attach_empty_marker(field) -> None:
    """Give a field the marker rule and its starting state.

    Call once, where the field is built. ``mark_empty`` keeps it in step from
    then on."""
    target = _editor(field)
    target.setStyleSheet(EMPTY_FIELD_RULE)
    mark_empty(field)
