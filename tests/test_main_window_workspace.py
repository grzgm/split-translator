import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtWidgets import QApplication, QDialog, QWidget

from split_translator.config import Config
from split_translator.main_window import TranslationTool

app = QApplication.instance() or QApplication([])


class CloseEventTests(unittest.TestCase):
    """The graph and print windows have no parent, so they are independent
    top-level windows. Left open they keep app.exec() from returning, which
    would hang a workspace switch, and they hold the outgoing workspace's store,
    so a survivor would show the previous workspace's deck."""

    def test_close_event_closes_the_graph_and_print_windows(self):
        graph = QWidget()
        printer = QWidget()
        graph.show()
        printer.show()
        # Called unbound against a stub: the method reads two attributes and
        # nothing else, so building a real window (which needs books on disk and
        # a web profile) would buy nothing.
        stub = type("Stub", (), {
            "flashcard_graph_window": graph,
            "flashcard_print_window": printer,
        })()
        TranslationTool.close_child_windows(stub)
        self.assertFalse(graph.isVisible())
        self.assertFalse(printer.isVisible())

    def test_close_child_windows_tolerates_windows_never_opened(self):
        stub = type("Stub", (), {
            "flashcard_graph_window": None,
            "flashcard_print_window": None,
        })()
        # Must not raise.
        TranslationTool.close_child_windows(stub)



class _StubWindow:
    """Just the attributes open_workspaces touches.

    Building a real window would need books on disk and a web profile, and the
    method only reads its config and sets three things on itself.
    """

    def __init__(self, config):
        self.config = config
        self.next_workspace = None
        self.pending_rename = None
        self.closed = False

    def close(self):
        self.closed = True


def _fake_dialog(chosen, rename=None):
    """A stand-in for WorkspaceDialog that reports a fixed result."""

    class FakeDialog:
        def __init__(self, current, parent=None):
            self.chosen = chosen
            self.rename = rename

        def exec(self):
            return QDialog.DialogCode.Accepted

    return FakeDialog


class _Workspace:
    """A workspace folder on disk, plus the Config the window loaded from it."""

    def __init__(self, name="Lalka"):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name) / "lalka"
        self.dir.mkdir()
        self.name = name

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self._tmp.cleanup()
        return False

    def write(self, name, original="/books/a.epub"):
        """Write the config.json the picker just saved."""
        (self.dir / "config.json").write_text(
            json.dumps(
                {
                    "name": name,
                    "original_path": original,
                    "translation_path": "/books/b.epub",
                }
            ),
            encoding="utf-8",
        )

    def config(self, original="/books/a.epub"):
        """The config the running window is holding."""
        return Config(
            name=self.name,
            dir=self.dir,
            original_path=original,
            translation_path="/books/b.epub",
            page_anchors=[],
        )


class ReopenTheSameWorkspaceTests(unittest.TestCase):
    """Reopening the workspace that is already open rebuilds the window only
    when something the window was built from has changed."""

    def _open(self, workspace, chosen):
        stub = _StubWindow(workspace.config())
        with patch(
            "split_translator.main_window.WorkspaceDialog",
            _fake_dialog(chosen),
        ):
            TranslationTool.open_workspaces(stub)
        return stub

    def test_a_renamed_workspace_rebuilds_so_the_title_follows_the_name(self):
        # The slug is unchanged, so there is no folder move to force a rebuild,
        # but the window title still names the old workspace.
        with _Workspace() as workspace:
            workspace.write("Lalka!")
            stub = self._open(workspace, workspace.dir.name)
            self.assertTrue(stub.closed)
            self.assertEqual(stub.next_workspace, workspace.dir.name)

    def test_changed_book_paths_rebuild(self):
        with _Workspace() as workspace:
            workspace.write("Lalka", original="/books/other.epub")
            stub = self._open(workspace, workspace.dir.name)
            self.assertTrue(stub.closed)

    def test_nothing_changed_is_a_no_op(self):
        with _Workspace() as workspace:
            workspace.write("Lalka")
            stub = self._open(workspace, workspace.dir.name)
            self.assertFalse(stub.closed)
            self.assertIsNone(stub.next_workspace)


if __name__ == "__main__":
    unittest.main()
