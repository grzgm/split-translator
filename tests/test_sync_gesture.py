"""The scroll gesture guard shared by the surfaces that show both editions.

Mirroring a scroll into one view makes that view report a scroll of its own a
moment later. SyncGesture decides which reports may drive a mirror: the view
last touched owns the gesture, and the other view is ignored while a mirror
settles.
"""

import unittest

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from split_translator.sync_gesture import SyncGesture

app = QApplication.instance() or QApplication([])

ORIGINAL = object()
TRANSLATION = object()


def _wait(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


class SyncGestureTests(unittest.TestCase):
    def test_a_first_scroll_drives_and_takes_ownership(self):
        gesture = SyncGesture()
        self.assertTrue(gesture.allow(ORIGINAL))
        self.assertIs(gesture.owner, ORIGINAL)

    def test_the_other_view_is_refused_while_a_mirror_settles(self):
        gesture = SyncGesture()
        gesture.allow(ORIGINAL)
        gesture.begin_mirror()
        self.assertFalse(gesture.allow(TRANSLATION))
        self.assertIs(gesture.owner, ORIGINAL)

    def test_the_owner_keeps_driving_while_its_mirror_settles(self):
        gesture = SyncGesture()
        gesture.allow(ORIGINAL)
        gesture.begin_mirror()
        self.assertTrue(gesture.allow(ORIGINAL))

    def test_either_view_may_drive_when_nothing_is_settling(self):
        gesture = SyncGesture()
        gesture.allow(ORIGINAL)
        self.assertTrue(gesture.allow(TRANSLATION))
        self.assertIs(gesture.owner, TRANSLATION)

    def test_the_other_view_takes_over_once_settled(self):
        gesture = SyncGesture()
        gesture.allow(ORIGINAL)
        gesture.begin_mirror()
        gesture.settle()
        self.assertTrue(gesture.allow(TRANSLATION))
        self.assertIs(gesture.owner, TRANSLATION)

    def test_the_window_closes_by_itself(self):
        gesture = SyncGesture(window_ms=10)
        gesture.allow(ORIGINAL)
        gesture.begin_mirror()
        _wait(100)
        self.assertFalse(gesture.in_flight)
        self.assertTrue(gesture.allow(TRANSLATION))

    def test_every_mirror_keeps_the_window_open(self):
        # A steady scroll mirrors many times a second. The window has to last
        # the whole gesture, not close a fixed time after the first mirror.
        gesture = SyncGesture(window_ms=300)
        gesture.allow(ORIGINAL)
        gesture.begin_mirror()
        _wait(180)
        gesture.begin_mirror()
        _wait(180)
        self.assertTrue(gesture.in_flight)
