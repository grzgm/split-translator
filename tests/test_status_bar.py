import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from split_translator.status_bar import (
    FLASH_COUNT,
    FLASH_OFF_STYLE,
    FLASH_STYLE,
    MESSAGE_STYLE,
    NOTICE_STYLE,
    StatusBar,
)

app = QApplication.instance() or QApplication([])


class StatusBarTests(unittest.TestCase):
    def _bar(self):
        return StatusBar()

    def _finish_flash(self, bar):
        # Drive the flash to completion without waiting on the real timer: each
        # tick is one half-pulse, so the animation is FLASH_COUNT * 2 ticks.
        for _ in range(FLASH_COUNT * 2):
            bar._on_flash_tick()

    def test_notice_has_no_timeout_and_stays(self):
        # A notice must survive on its own; only a dismiss (or a later message)
        # may clear it. currentMessage() still returning the text is what proves
        # no timeout was set.
        bar = self._bar()
        bar.show_notice("previously searched")
        self.assertEqual(bar.currentMessage(), "previously searched")

    def test_notice_shows_the_close_button(self):
        bar = self._bar()
        self.assertTrue(bar._close_button.isHidden())
        bar.show_notice("previously searched")
        self.assertFalse(bar._close_button.isHidden())

    def test_message_does_not_show_the_close_button(self):
        # A transient message clears itself, so a close button for it would be
        # pointless.
        bar = self._bar()
        bar.show_message("Saved flashcard")
        self.assertTrue(bar._close_button.isHidden())

    def test_notice_settles_on_the_highlight_colour(self):
        bar = self._bar()
        bar.show_notice("previously searched")
        self._finish_flash(bar)
        self.assertEqual(bar.styleSheet(), NOTICE_STYLE)

    def test_message_settles_on_no_highlight(self):
        bar = self._bar()
        bar.show_message("Saved flashcard")
        self._finish_flash(bar)
        self.assertEqual(bar.styleSheet(), MESSAGE_STYLE)

    def test_new_notice_flashes(self):
        # The reason the flash exists: a notice replacing a same-coloured notice
        # changes only its text. The flash must fire on the *second* notice too,
        # or the replacement goes unnoticed.
        bar = self._bar()
        bar.show_notice("first")
        self._finish_flash(bar)
        self.assertEqual(bar.styleSheet(), NOTICE_STYLE)
        bar.show_notice("second")
        self.assertEqual(bar.styleSheet(), FLASH_STYLE)

    def test_message_flashes(self):
        bar = self._bar()
        bar.show_message("Saved flashcard")
        self.assertEqual(bar.styleSheet(), FLASH_STYLE)

    def test_flash_pulses_then_settles(self):
        # The exact blink: amber, transparent, amber, transparent, then settle.
        # The gap must be FLASH_OFF_STYLE, not the settled colour: dipping a
        # yellow notice to pale yellow is the weak blink this replaced.
        bar = self._bar()
        bar.show_notice("previously searched")
        seen = [bar.styleSheet()]
        for _ in range(FLASH_COUNT * 2):
            bar._on_flash_tick()
            seen.append(bar.styleSheet())
        self.assertEqual(
            seen,
            [FLASH_STYLE, FLASH_OFF_STYLE] * FLASH_COUNT + [NOTICE_STYLE],
        )
        self.assertFalse(bar._flash_timer.isActive())

    def test_flash_gap_is_transparent_not_the_settled_colour(self):
        # Guards the whole point of the transparent dip: a notice mid-blink must
        # not simply show its own settled yellow.
        bar = self._bar()
        bar.show_notice("previously searched")
        bar._on_flash_tick()  # first gap
        self.assertEqual(bar.styleSheet(), FLASH_OFF_STYLE)
        self.assertNotEqual(bar.styleSheet(), NOTICE_STYLE)

    def test_dismiss_clears_the_notice(self):
        bar = self._bar()
        bar.show_notice("previously searched")
        bar.dismiss_notice()
        self.assertEqual(bar.currentMessage(), "")
        self.assertTrue(bar._close_button.isHidden())
        self.assertEqual(bar.styleSheet(), MESSAGE_STYLE)

    def test_dismiss_emits_notice_dismissed(self):
        bar = self._bar()
        dismissed = []
        bar.notice_dismissed.connect(lambda: dismissed.append(True))
        bar.show_notice("previously searched")
        bar.dismiss_notice()
        self.assertEqual(len(dismissed), 1)

    def test_close_button_click_dismisses(self):
        bar = self._bar()
        bar.show_notice("previously searched")
        bar._close_button.click()
        self.assertEqual(bar.currentMessage(), "")

    def test_dismiss_stops_an_in_flight_flash(self):
        # Dismissing mid-flash must not leave the timer running, or it would
        # repaint the bar after it was cleared.
        bar = self._bar()
        bar.show_notice("previously searched")
        self.assertTrue(bar._flash_timer.isActive())
        bar.dismiss_notice()
        self.assertFalse(bar._flash_timer.isActive())
        self.assertEqual(bar.styleSheet(), MESSAGE_STYLE)

    def test_message_after_a_notice_drops_the_highlight(self):
        # A transient message following a notice must not inherit the notice's
        # yellow: it settles on the plain style and hides the close button.
        bar = self._bar()
        bar.show_notice("previously searched")
        self._finish_flash(bar)
        bar.show_message("Saved flashcard")
        self._finish_flash(bar)
        self.assertEqual(bar.styleSheet(), MESSAGE_STYLE)
        self.assertTrue(bar._close_button.isHidden())

    def test_notice_after_a_message_takes_the_highlight(self):
        bar = self._bar()
        bar.show_message("Saved flashcard")
        self._finish_flash(bar)
        bar.show_notice("previously searched")
        self._finish_flash(bar)
        self.assertEqual(bar.styleSheet(), NOTICE_STYLE)
        self.assertFalse(bar._close_button.isHidden())


if __name__ == "__main__":
    unittest.main()
