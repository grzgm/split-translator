"""The POS drop-down: a letter picks a code, it does not merely seek to it.

Qt's stock popup treats letters as an incremental search that only highlights and
never commits, and whose prefix is sticky ("v" then "a" searches "va", matches
nothing, and freezes the highlight). PosPopupView replaces that: a letter sets the
value at once, leaves the list open, and repeats cycle the codes sharing a first
letter. These tests pin all of that, driving real key events at the real widgets."""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

from split_translator.flashcard_editor_base import SenseRow

app = QApplication.instance() or QApplication([])


class PosPopupTests(unittest.TestCase):
    def _row(self):
        row = SenseRow()
        # The popup only takes keys once it is up, which is how it is used.
        row.pos_combo.showPopup()
        return row

    def _type(self, row, letter):
        """Send one letter to the open popup and return the combo's value."""
        key = getattr(Qt.Key, f"Key_{letter.upper()}")
        event = QKeyEvent(
            QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier, letter
        )
        QApplication.sendEvent(row.pos_popup, event)
        return row.pos_combo.currentText()

    def test_letter_sets_the_value_immediately(self):
        # The whole point: pressing "v" is choosing "v". No Enter, no click.
        row = self._row()
        self.assertEqual(row.pos_combo.currentText(), "")
        self.assertEqual(self._type(row, "v"), "v")

    def test_letter_leaves_the_popup_open(self):
        # Committing must not double as closing: the list stays up so the choice
        # can be changed with another keypress.
        row = self._row()
        self._type(row, "v")
        self.assertTrue(row.pos_popup.isVisible())

    def test_unique_letters_pick_their_code(self):
        row = self._row()
        for letter, code in [("n", "n"), ("v", "v"), ("c", "con")]:
            self.assertEqual(self._type(row, letter), code)

    def test_repeats_cycle_codes_sharing_a_first_letter(self):
        # "a" and "p" are ambiguous (adj/adv, pre/pro/phr), so one press cannot
        # mean one code. Pressing again advances rather than sticking.
        row = self._row()
        self.assertEqual(
            [self._type(row, "a") for _ in range(3)], ["adj", "adv", "adj"]
        )

    def test_repeats_cycle_the_three_p_codes_and_wrap(self):
        row = self._row()
        self.assertEqual(
            [self._type(row, "p") for _ in range(4)], ["pre", "pro", "phr", "pre"]
        )

    def test_switching_letter_restarts_at_that_letters_first_code(self):
        # Cycling within "p" must not carry over into "a".
        row = self._row()
        self._type(row, "p")
        self._type(row, "p")  # now on "pro"
        self.assertEqual(self._type(row, "a"), "adj")

    def test_typing_two_letters_does_not_build_a_search_prefix(self):
        # The regression this replaced: Qt read "v" then "a" as the prefix "va",
        # matched nothing, and stopped responding. Each letter must stand alone.
        row = self._row()
        self.assertEqual(self._type(row, "v"), "v")
        self.assertEqual(self._type(row, "a"), "adj")
        self.assertEqual(self._type(row, "n"), "n")

    def test_unmatched_letter_leaves_the_value_alone(self):
        # No code starts with "z". The key falls through to Qt rather than
        # clearing or randomising what is already chosen.
        row = self._row()
        self._type(row, "v")
        self.assertEqual(self._type(row, "z"), "v")

    def test_every_pos_option_is_reachable_by_letter(self):
        # Guards the codes and the cycling together: if a code is added that
        # shares a first letter, it must still be typeable.
        row = self._row()
        reachable = set()
        for letter in {code[0] for code in SenseRow.POS_OPTIONS}:
            # Press the letter as many times as there are codes under it, which
            # walks the whole cycle for that letter.
            same = [c for c in SenseRow.POS_OPTIONS if c.startswith(letter)]
            for _ in range(len(same)):
                reachable.add(self._type(row, letter))
        self.assertEqual(reachable, set(SenseRow.POS_OPTIONS))

    def test_arrow_keys_still_move_the_selection(self):
        # Letters are intercepted; everything else must reach the default handler.
        row = self._row()
        down = QKeyEvent(
            QEvent.Type.KeyPress, Qt.Key.Key_Down, Qt.KeyboardModifier.NoModifier, ""
        )
        before = row.pos_popup.currentIndex().row()
        QApplication.sendEvent(row.pos_popup, down)
        self.assertEqual(row.pos_popup.currentIndex().row(), before + 1)

    def test_free_typing_a_code_outside_the_list_still_works(self):
        # The combo stays editable: capture and hand-typing may set a code the
        # list does not offer, and the popup must not interfere with that.
        row = SenseRow()
        row.pos_combo.setCurrentText("zzz")
        self.assertEqual(row.pos_combo.currentText(), "zzz")


if __name__ == "__main__":
    unittest.main()
