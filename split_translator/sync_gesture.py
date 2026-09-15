"""Which of two side-by-side book views is driving a synced scroll.

When both editions are on screen, mirroring a scroll into one view makes that
view report a scroll of its own a moment later: the echo. Mirrored back, the
echo scrolls the view the reader is actually moving, and a slow scroll barely
moves at all. The cure is to let only the view the reader last touched drive,
and to ignore the other view while a mirror is settling.

It knows nothing about views or mappings. A surface passes whatever identifies
each view to allow() before mirroring, and calls begin_mirror() just before it
scrolls the other view.
"""

from PySide6.QtCore import QObject, QTimer

# How long after a mirror the other view's reports count as its echo. The echo
# and its settle chain take a few milliseconds; 150ms covers them without
# stopping the reader from grabbing the other view after a brief pause.
ECHO_WINDOW_MS = 150


class SyncGesture(QObject):
    """The owner of the current scroll gesture, and the echo window."""

    def __init__(self, parent=None, window_ms: int = ECHO_WINDOW_MS):
        super().__init__(parent)
        self._owner = None
        self._in_flight = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(window_ms)
        self._timer.timeout.connect(self.settle)

    @property
    def owner(self):
        """The view behind the latest allowed scroll, or None."""
        return self._owner

    @property
    def in_flight(self) -> bool:
        """Whether a mirror is still settling."""
        return self._in_flight

    def allow(self, source) -> bool:
        """Whether a scroll reported by source may drive the other view.

        A report from any view but the owner while a mirror settles is that
        mirror's echo, so it is refused. Every other report is genuine and makes
        its view the owner: the view last touched wins."""
        if (
            self._in_flight
            and self._owner is not None
            and source is not self._owner
        ):
            return False
        self._owner = source
        return True

    def begin_mirror(self) -> None:
        """Open, or keep open, the echo window. Call just before scrolling the
        other view. Every call restarts the timer, so the window lasts for as
        long as the reader keeps scrolling."""
        self._in_flight = True
        self._timer.start()

    def settle(self) -> None:
        """Close the echo window, so the next report from either view counts
        as genuine. The timer calls this."""
        self._in_flight = False
