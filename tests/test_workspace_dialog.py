import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtWidgets import QApplication, QDialog

from split_translator import workspace as workspace_module
from split_translator.workspace import Workspace, create_workspace, read_workspace
from split_translator.workspace_dialog import WorkspaceDialog, workspace_counts

app = QApplication.instance() or QApplication([])


class _Root:
    """A temporary workspaces root, patched in for the duration of a test.

    The dialog calls the workspace functions without a root, and those functions
    resolve WORKSPACES_DIR from their module inside the body (Task 1), so
    patching the constant here redirects every one of them. This is exactly why
    those arguments default to None rather than to the constant.
    """

    def __init__(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name)
        self._patch = patch.object(workspace_module, "WORKSPACES_DIR", self.path)

    def __enter__(self):
        self._patch.start()
        return self

    def __exit__(self, *exc):
        self._patch.stop()
        self._tmp.cleanup()
        return False

    def books(self):
        """Two files that exist, so Open can be enabled."""
        original = self.path / "a.epub"
        translation = self.path / "b.epub"
        original.write_text("", encoding="utf-8")
        translation.write_text("", encoding="utf-8")
        return str(original), str(translation)

    def workspace(self, name, with_books=True):
        created = create_workspace(name, self.path)
        if not with_books:
            return created
        original, translation = self.books()
        edited = Workspace(
            slug=created.slug,
            name=created.name,
            dir=created.dir,
            original_path=original,
            translation_path=translation,
        )
        workspace_module.save_workspace(edited)
        return edited


class WorkspaceCountsTests(unittest.TestCase):
    def test_counts_cards_and_searches(self):
        with _Root() as root:
            created = root.workspace("Lalka")
            (created.dir / "flashcards.json").write_text(
                json.dumps({"version": 4, "cards": [{"id": "1"}, {"id": "2"}]}),
                encoding="utf-8",
            )
            (created.dir / "history.json").write_text(
                json.dumps([{"word": "a"}, {"word": "b"}, {"word": "c"}]),
                encoding="utf-8",
            )
            self.assertEqual(workspace_counts(created), (2, 3))

    def test_missing_files_count_as_zero(self):
        with _Root() as root:
            self.assertEqual(workspace_counts(root.workspace("Empty")), (0, 0))


class DialogListTests(unittest.TestCase):
    def test_lists_every_workspace_by_name(self):
        with _Root() as root:
            root.workspace("Solaris")
            root.workspace("Lalka")
            dialog = WorkspaceDialog(None)
            labels = [
                dialog.list_widget.item(i).text()
                for i in range(dialog.list_widget.count())
            ]
            self.assertEqual(labels, ["Lalka", "Solaris"])

    def test_selects_and_marks_the_current_workspace(self):
        with _Root() as root:
            root.workspace("Solaris")
            current = root.workspace("Lalka")
            dialog = WorkspaceDialog(current.slug)
            self.assertEqual(dialog.selected().slug, current.slug)
            self.assertIn("Lalka", dialog.list_widget.currentItem().text())


class DialogOpenGuardTests(unittest.TestCase):
    def test_open_is_disabled_while_a_book_path_does_not_resolve(self):
        with _Root() as root:
            root.workspace("Nowhere", with_books=False)
            dialog = WorkspaceDialog(None)
            self.assertFalse(dialog.open_button.isEnabled())

    def test_open_is_enabled_once_both_books_resolve(self):
        with _Root() as root:
            root.workspace("Lalka")
            dialog = WorkspaceDialog(None)
            self.assertTrue(dialog.open_button.isEnabled())

    def test_typing_a_missing_path_disables_open(self):
        with _Root() as root:
            root.workspace("Lalka")
            dialog = WorkspaceDialog(None)
            dialog.original_input.setText("/definitely/not/here.epub")
            dialog.on_edited()
            self.assertFalse(dialog.open_button.isEnabled())


class DialogEditTests(unittest.TestCase):
    def test_edits_are_written_when_the_selection_changes(self):
        with _Root() as root:
            first = root.workspace("Aaa")
            root.workspace("Bbb")
            dialog = WorkspaceDialog(first.slug)
            dialog.name_input.setText("Aaa renamed")
            dialog.on_edited()
            dialog.list_widget.setCurrentRow(1)
            self.assertEqual(read_workspace(first.dir).name, "Aaa renamed")

    def test_accept_writes_edits_and_reports_the_chosen_slug(self):
        with _Root() as root:
            created = root.workspace("Lalka")
            dialog = WorkspaceDialog(created.slug)
            dialog.original_input.setText(created.translation_path)
            dialog.on_edited()
            dialog.accept()
            self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
            self.assertEqual(dialog.chosen, created.slug)
            self.assertEqual(
                read_workspace(created.dir).original_path, created.translation_path
            )


class DialogRenameTests(unittest.TestCase):
    def test_renaming_a_workspace_that_is_not_open_moves_its_folder_now(self):
        with _Root() as root:
            other = root.workspace("Other")
            target = root.workspace("Lalka")
            dialog = WorkspaceDialog(other.slug)
            dialog.select_slug(target.slug)
            dialog.name_input.setText("Lalka Prus")
            dialog.on_edited()
            dialog.accept()
            self.assertFalse(target.dir.exists())
            moved = root.path / "lalka-prus"
            self.assertEqual(read_workspace(moved).name, "Lalka Prus")
            self.assertEqual(dialog.chosen, "lalka-prus")
            self.assertIsNone(dialog.rename)

    def test_renaming_the_open_workspace_defers_the_folder_move(self):
        # Its stores still hold paths into this folder, so the move has to wait
        # until closeEvent has flushed them.
        with _Root() as root:
            current = root.workspace("Lalka")
            dialog = WorkspaceDialog(current.slug)
            dialog.name_input.setText("Lalka Prus")
            dialog.on_edited()
            dialog.accept()
            self.assertTrue(current.dir.exists())
            self.assertEqual(dialog.rename, (current.slug, "lalka-prus"))
            self.assertEqual(dialog.chosen, "lalka-prus")

    def test_opening_without_renaming_never_moves_the_folder(self):
        # A workspace whose slug no longer matches its name (an old collision
        # suffix, say) must not be quietly moved just by being opened.
        with _Root() as root:
            create_workspace("Lalka", root.path)
            second = root.workspace("Lalka")
            self.assertEqual(second.slug, "lalka-2")
            dialog = WorkspaceDialog(None)
            dialog.select_slug("lalka-2")
            dialog.accept()
            self.assertTrue(second.dir.exists())
            self.assertEqual(dialog.chosen, "lalka-2")
            self.assertIsNone(dialog.rename)


class DialogDeleteTests(unittest.TestCase):
    def test_delete_is_refused_for_the_last_workspace(self):
        with _Root() as root:
            root.workspace("Only")
            dialog = WorkspaceDialog(None)
            self.assertFalse(dialog.delete_button.isEnabled())

    def test_delete_is_refused_for_the_currently_open_workspace(self):
        # Its stores hold paths into that folder and recreate it on their next
        # write, so deleting it would lose the deck and leave a zombie folder.
        with _Root() as root:
            current = root.workspace("Open one")
            other = root.workspace("Other")
            dialog = WorkspaceDialog(current.slug)
            dialog.select_slug(current.slug)
            self.assertFalse(dialog.delete_button.isEnabled())
            dialog.select_slug(other.slug)
            self.assertTrue(dialog.delete_button.isEnabled())

    def test_delete_selected_refuses_the_open_workspace_when_called_directly(self):
        with _Root() as root:
            current = root.workspace("Open one")
            root.workspace("Other")
            dialog = WorkspaceDialog(current.slug)
            dialog.select_slug(current.slug)
            with patch.object(WorkspaceDialog, "_confirm_delete", return_value=True):
                dialog.delete_selected()
            self.assertTrue(current.dir.exists())
            self.assertEqual(dialog.list_widget.count(), 2)

    def test_delete_removes_the_selected_workspace(self):
        with _Root() as root:
            first = root.workspace("Aaa")
            root.workspace("Bbb")
            dialog = WorkspaceDialog(None)
            dialog.select_slug(first.slug)
            with patch.object(WorkspaceDialog, "_confirm_delete", return_value=True):
                dialog.delete_selected()
            self.assertFalse(first.dir.exists())
            self.assertEqual(dialog.list_widget.count(), 1)


class DialogNewTests(unittest.TestCase):
    def test_new_creates_and_selects_an_empty_workspace(self):
        with _Root() as root:
            root.workspace("Existing")
            dialog = WorkspaceDialog(None)
            with patch.object(WorkspaceDialog, "_ask_name", return_value="Fresh"):
                dialog.new_workspace()
            self.assertEqual(dialog.selected().name, "Fresh")
            # No books yet, so it cannot be opened.
            self.assertFalse(dialog.open_button.isEnabled())
