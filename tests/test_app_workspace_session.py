"""One event loop for the whole process: a workspace switch swaps windows inside
it instead of restarting it.

Qt WebEngine cannot survive `QApplication.exec()` running a second time. Once a
web view has existed, the second exec and quit jump through a null pointer
inside `aboutToQuit` and the process segfaults; a bare window with no web view
survives the same loop. `app.main` used to run `exec()` once per workspace, so
the second switch crashed. These tests pin the replacement: the session opens a
window, reacts to it closing by opening the next workspace or quitting, and
never runs the loop again.

The crash itself needs a real display and real web views, so it is verified by
driving the real window; what is tested here is the session's decisions.
"""

import os
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from split_translator.app import WorkspaceSession
from split_translator.main_window import TranslationTool

qapp = QApplication.instance() or QApplication([])


class _FakeWindow(QObject):
    """Just what the session touches on a main window: the closed signal, the
    two attributes it reads after a close, show and deleteLater."""

    closed = Signal()

    def __init__(self, config, profile, log):
        super().__init__()
        self.config = config
        self.profile = profile
        self.next_workspace = None
        self.pending_rename = None
        self.shown = False
        self.deleted = False
        log.append(("build", config))

    def show(self):
        self.shown = True

    def deleteLater(self):
        self.deleted = True


class _FakeConfig(str):
    """A loaded config, reduced to what the session reads. A str, so assertions
    can name it plainly, with the `name` a real Config carries: the warning
    shown when a workspace fails to open quotes it."""

    @property
    def name(self):
        return f"Workspace {self}"


def _settle():
    """Run the deferred close handling. The session never builds the next
    window inside the old one's closeEvent, so a close is handled on the next
    pass of the event loop."""
    for _ in range(3):
        qapp.processEvents()


class WorkspaceSessionTests(unittest.TestCase):
    def setUp(self):
        self.log = []
        self.windows = []
        self.app = MagicMock()
        self.profile = object()

        def build(config, profile):
            window = _FakeWindow(config, profile, self.log)
            self.windows.append(window)
            return window

        patches = [
            patch("split_translator.app.TranslationTool", side_effect=build),
            patch("split_translator.app.set_last_workspace"),
            patch("split_translator.app.config_path_for", side_effect=lambda s: f"path:{s}"),
            patch(
                "split_translator.app.load_config",
                side_effect=lambda p: _FakeConfig(f"config<{p}>"),
            ),
            patch("split_translator.app.pick_workspace", return_value=None),
            patch("split_translator.app.QMessageBox"),
            patch(
                "split_translator.app.rename_workspace_folder",
                side_effect=lambda old, new: self.log.append(("rename", old, new)),
            ),
        ]
        self.mocks = {}
        for p in patches:
            self.mocks[p.attribute] = p.start()
            self.addCleanup(p.stop)
        self.session = WorkspaceSession(self.app, self.profile)

    # --- opening ----------------------------------------------------------

    def test_opening_a_workspace_builds_and_shows_one_window(self):
        self.assertTrue(self.session.open("lalka"))
        self.assertEqual(len(self.windows), 1)
        self.assertTrue(self.windows[0].shown)
        self.assertEqual(self.windows[0].config, "config<path:lalka>")
        self.mocks["set_last_workspace"].assert_called_once_with("lalka")

    def test_the_window_is_built_on_the_shared_profile(self):
        self.session.open("lalka")
        self.assertIs(self.windows[0].profile, self.profile)

    def test_nothing_to_open_builds_nothing(self):
        self.assertFalse(self.session.open(None))
        self.assertEqual(self.windows, [])

    def test_a_window_that_fails_to_build_sends_the_user_to_the_picker(self):
        # A corrupt or unsupported book file still raises out of the window's
        # constructor even when the path exists; the user repairs it in the
        # picker rather than losing the app.
        builds = iter([ValueError("corrupt epub")])

        def flaky(config, profile):
            error = next(builds, None)
            if error is not None:
                raise error
            window = _FakeWindow(config, profile, self.log)
            self.windows.append(window)
            return window

        self.mocks["TranslationTool"].side_effect = flaky
        self.mocks["pick_workspace"].return_value = "solaris"
        self.assertTrue(self.session.open("broken"))
        warning = self.mocks["QMessageBox"].warning
        self.assertEqual(warning.call_count, 1)
        # The message names the workspace that failed, not the one opened next.
        self.assertIn("Workspace config<path:broken>", warning.call_args.args[2])
        self.assertEqual(self.windows[0].config, "config<path:solaris>")

    def test_giving_up_in_the_picker_after_a_failure_opens_nothing(self):
        self.mocks["TranslationTool"].side_effect = ValueError("corrupt epub")
        self.assertFalse(self.session.open("broken"))

    # --- closing ----------------------------------------------------------

    def test_a_switch_opens_the_next_workspace(self):
        self.session.open("lalka")
        first = self.windows[0]
        first.next_workspace = "solaris"
        first.closed.emit()
        _settle()
        self.assertEqual(len(self.windows), 2)
        self.assertEqual(self.windows[1].config, "config<path:solaris>")
        self.assertTrue(first.deleted)
        self.app.quit.assert_not_called()

    def test_the_next_window_is_not_built_inside_the_close(self):
        # Building a window full of web views from inside the outgoing window's
        # closeEvent is exactly the kind of re-entrancy WebEngine punishes, so
        # the swap waits for the next pass of the loop.
        self.session.open("lalka")
        self.windows[0].next_workspace = "solaris"
        self.windows[0].closed.emit()
        self.assertEqual(len(self.windows), 1)
        _settle()
        self.assertEqual(len(self.windows), 2)

    def test_closing_with_nowhere_to_go_quits(self):
        self.session.open("lalka")
        self.windows[0].closed.emit()
        _settle()
        self.app.quit.assert_called_once_with()
        self.assertEqual(len(self.windows), 1)
        self.assertTrue(self.windows[0].deleted)

    def test_many_switches_never_run_the_event_loop_again(self):
        # The regression this module exists for: exec() is main's alone and runs
        # once, however many workspaces are opened.
        self.session.open("a")
        for nxt in ("b", "c", "d"):
            self.windows[-1].next_workspace = nxt
            self.windows[-1].closed.emit()
            _settle()
        self.windows[-1].closed.emit()
        _settle()
        self.assertEqual(len(self.windows), 4)
        self.app.exec.assert_not_called()
        self.app.quit.assert_called_once_with()

    def test_the_pending_rename_moves_the_folder_before_the_next_window(self):
        # The move cannot run while the outgoing window's stores hold paths into
        # the folder, and the incoming window reads from the new one.
        self.session.open("lalka")
        self.log.clear()
        self.windows[0].pending_rename = ("lalka", "lalka-prus")
        self.windows[0].next_workspace = "lalka-prus"
        self.windows[0].closed.emit()
        _settle()
        self.assertEqual(
            self.log,
            [("rename", "lalka", "lalka-prus"), ("build", "config<path:lalka-prus>")],
        )

    def test_a_repeated_close_from_the_outgoing_window_is_ignored(self):
        # Only the window currently open drives the session. A stray second
        # closed signal from one already replaced must not open a third window.
        self.session.open("lalka")
        first = self.windows[0]
        first.next_workspace = "solaris"
        first.closed.emit()
        _settle()
        first.closed.emit()
        _settle()
        self.assertEqual(len(self.windows), 2)
        self.app.quit.assert_not_called()


class MainWindowAnnouncesCloseTests(unittest.TestCase):
    def test_the_main_window_declares_a_closed_signal(self):
        # The window only announces; app.py decides what follows a close.
        self.assertIsInstance(TranslationTool.closed, Signal)


if __name__ == "__main__":
    unittest.main()
