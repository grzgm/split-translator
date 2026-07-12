"""Status bar with dismissible notices and a flash that marks every new message.

Two kinds of message share the bar:

- A **notice** (:meth:`StatusBar.show_notice`) is highlighted and has no timeout.
  It stays until the user closes it with the X button, so a notice cannot be
  missed by looking away. The previously-searched and plural notices use this.
- A **message** (:meth:`StatusBar.show_message`) is a transient confirmation that
  clears itself after a timeout ("Saved flashcard", "Copied translation prompt").

Both flash on arrival. Without the flash a notice replacing a same-coloured
notice changes only its text, which is easy to miss; the flash blinks the
background between a deep amber and a transparent gap, so a *replacement* is as
visible as a *first* message.
"""

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import QStatusBar, QToolButton

# The settled colours. NOTICE is the long-standing yellow highlight; MESSAGE
# leaves the bar in the palette's default (an empty stylesheet).
NOTICE_STYLE = "background-color: #fff3cd; color: #856404;"
MESSAGE_STYLE = ""

# The flash colour, a deeper amber than NOTICE_STYLE so a pulse is visible even
# when a notice replaces a notice that was already yellow.
FLASH_STYLE = "background-color: #ffc720; color: #6b4e00;"

# The "off" half of each pulse. The background goes transparent rather than back
# to the settled colour: dipping a yellow notice to pale yellow is a weak blink,
# while dipping it to no background at all is unmistakable. The text keeps the
# flash's dark colour so it stays readable against the bare bar.
FLASH_OFF_STYLE = "background-color: transparent; color: #6b4e00;"

# Two pulses, then settle. Each half-pulse holds for FLASH_MS, so the whole
# animation runs FLASH_COUNT * 2 * FLASH_MS: brief enough not to nag.
FLASH_MS = 140
FLASH_COUNT = 2


class StatusBar(QStatusBar):
    """The application status bar.

    Owns the notice styling, the arrival flash and the close button, so the main
    window only has to say what to show, not how to show it.
    """

    #: Emitted when the user dismisses a notice with the close button.
    notice_dismissed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        # The close button is a permanent widget: showMessage covers ordinary
        # widgets, so a plain addWidget button would vanish under the very notice
        # it is meant to dismiss.
        self._close_button = QToolButton()
        self._close_button.setText("X")
        self._close_button.setToolTip("Dismiss this notice")
        self._close_button.setAutoRaise(True)
        self._close_button.clicked.connect(self.dismiss_notice)
        self.addPermanentWidget(self._close_button)
        # Shown only while a notice is up: a transient message clears itself, so
        # offering a close button for it would be pointless.
        self._close_button.hide()

        # The colour the bar returns to once the flash finishes. It is also the
        # colour restored between pulses.
        self._settled_style = MESSAGE_STYLE

        self._flash_timer = QTimer(self)
        self._flash_timer.setInterval(FLASH_MS)
        self._flash_timer.timeout.connect(self._on_flash_tick)
        # Counts down half-pulses: each tick toggles the colour, so a full pulse
        # (flash on, flash off) is two ticks.
        self._flash_ticks_left = 0

        self.messageChanged.connect(self._on_message_changed)

    def show_notice(self, text: str):
        """Show a highlighted notice that stays until it is dismissed."""
        self._settled_style = NOTICE_STYLE
        self._close_button.show()
        # A timeout of 0 means "no timeout": the notice stays until dismissed.
        self.showMessage(text, 0)
        self._start_flash()

    def show_message(self, text: str, timeout: int = 4000):
        """Show a transient message that clears itself after ``timeout`` ms."""
        self._settled_style = MESSAGE_STYLE
        self._close_button.hide()
        self.showMessage(text, timeout)
        self._start_flash()

    def dismiss_notice(self):
        """Clear the bar, as the close button does."""
        # clearMessage drives messageChanged with an empty string, which resets
        # the style and hides the button in _on_message_changed.
        self.clearMessage()
        self.notice_dismissed.emit()

    def _start_flash(self):
        self._flash_ticks_left = FLASH_COUNT * 2
        self.setStyleSheet(FLASH_STYLE)
        self._flash_timer.start()

    def _on_flash_tick(self):
        self._flash_ticks_left -= 1
        if self._flash_ticks_left <= 0:
            self._flash_timer.stop()
            self.setStyleSheet(self._settled_style)
            return
        # Odd ticks land on the transparent gap, even ticks back on the flash, so
        # the bar blinks rather than just fading in once. The settled colour is
        # only applied at the end, by the branch above.
        flashing = self._flash_ticks_left % 2 == 0
        self.setStyleSheet(FLASH_STYLE if flashing else FLASH_OFF_STYLE)

    def _on_message_changed(self, message: str):
        # The bar went empty: either a transient message timed out or the notice
        # was dismissed. Drop the highlight so the colour does not linger, stop
        # any in-flight flash, and take the close button away.
        if not message:
            self._flash_timer.stop()
            self._flash_ticks_left = 0
            self._settled_style = MESSAGE_STYLE
            self.setStyleSheet(MESSAGE_STYLE)
            self._close_button.hide()
