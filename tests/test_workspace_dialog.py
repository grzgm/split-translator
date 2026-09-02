import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

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


_SAVE = QMessageBox.StandardButton.Save
_DISCARD = QMessageBox.StandardButton.Discard
_CANCEL = QMessageBox.StandardButton.Cancel


def _leaving(answer):
    """Stub the unsaved-changes prompt with a fixed answer."""
    return patch.object(WorkspaceDialog, "_ask_leaving", return_value=answer)


class _AlwaysSaves:
    """Mixin for tests about what a save does, not about being asked to save.

    Leaving a workspace with unsaved edits prompts, so without this every one of
    these tests would block on a modal.
    """

    def setUp(self):
        patcher = _leaving(_SAVE)
        patcher.start()
        self.addCleanup(patcher.stop)


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


class DialogFolderLabelTests(unittest.TestCase):
    """The detail pane names the folder, so two workspaces sharing a display
    name can be told apart, and so the folder a rename will move is visible."""

    def test_it_shows_the_selected_workspace_folder(self):
        with _Root() as root:
            created = root.workspace("Lalka")
            dialog = WorkspaceDialog(None)
            self.assertEqual(dialog.folder_label.text(), created.slug)

    def test_same_named_workspaces_show_different_folders(self):
        with _Root() as root:
            first = root.workspace("Lalka")
            second = root.workspace("Lalka")
            self.assertNotEqual(first.slug, second.slug)
            dialog = WorkspaceDialog(None)
            dialog.select_slug(first.slug)
            self.assertEqual(dialog.folder_label.text(), first.slug)
            dialog.select_slug(second.slug)
            self.assertEqual(dialog.folder_label.text(), second.slug)


class DialogDuplicateNameTests(unittest.TestCase):
    """Two workspaces may not share a display name: two rows reading alike
    cannot be told apart in the list."""

    def test_open_is_disabled_while_the_name_matches_another(self):
        with _Root() as root:
            root.workspace("Lalka")
            target = root.workspace("Solaris")
            dialog = WorkspaceDialog(None)
            dialog.select_slug(target.slug)
            dialog.name_input.setText("Lalka")
            dialog.on_edited()
            self.assertFalse(dialog.open_button.isEnabled())
            self.assertIn("already called that", dialog.problem_label.text())

    def test_the_check_ignores_case_and_surrounding_space(self):
        with _Root() as root:
            root.workspace("Lalka")
            target = root.workspace("Solaris")
            dialog = WorkspaceDialog(None)
            dialog.select_slug(target.slug)
            dialog.name_input.setText("  lALKA  ")
            dialog.on_edited()
            self.assertFalse(dialog.open_button.isEnabled())

    def test_a_workspace_keeping_its_own_name_is_not_a_conflict(self):
        with _Root() as root:
            root.workspace("Lalka")
            dialog = WorkspaceDialog(None)
            dialog.name_input.setText("Lalka")
            dialog.on_edited()
            self.assertTrue(dialog.open_button.isEnabled())

    def test_workspaces_that_already_share_a_name_still_open(self):
        # Created outside the dialog, as a pre-rule or hand-edited config would
        # be. Refusing these would strand the user with two workspaces neither
        # of which can be opened.
        with _Root() as root:
            first = root.workspace("Lalka")
            second = root.workspace("Lalka")
            self.assertNotEqual(first.slug, second.slug)
            dialog = WorkspaceDialog(None)
            dialog.select_slug(first.slug)
            self.assertTrue(dialog.open_button.isEnabled())
            dialog.select_slug(second.slug)
            self.assertTrue(dialog.open_button.isEnabled())

    def test_a_colliding_name_is_never_saved_on_a_row_change(self):
        # A row change offers to save, so without a guard on the save itself the
        # rejected name would reach disk by the back door.
        with _Root() as root:
            root.workspace("Lalka")
            target = root.workspace("Solaris")
            dialog = WorkspaceDialog(None)
            dialog.select_slug(target.slug)
            dialog.name_input.setText("Lalka")
            dialog.on_edited()
            with _leaving(_SAVE), patch(
                "split_translator.workspace_dialog.QMessageBox.warning"
            ) as warning:
                dialog.select_slug("lalka")
            warning.assert_called_once()
            self.assertEqual(read_workspace(target.dir).name, "Solaris")
            self.assertFalse((root.path / "lalka-2").exists())
            # The refusal leaves the user on the row, with the name to fix.
            self.assertEqual(dialog.selected().slug, target.slug)

    def test_new_refuses_a_name_already_used(self):
        with _Root() as root:
            root.workspace("Lalka")
            dialog = WorkspaceDialog(None)
            with patch.object(WorkspaceDialog, "_ask_name", return_value="Lalka"), \
                 patch("split_translator.workspace_dialog.QMessageBox") as box:
                dialog.new_workspace()
            box.warning.assert_called_once()
            self.assertEqual(dialog.list_widget.count(), 1)

    def test_duplicate_refuses_a_name_already_used(self):
        with _Root() as root:
            source = root.workspace("Lalka")
            root.workspace("Solaris")
            dialog = WorkspaceDialog(None)
            dialog.select_slug(source.slug)
            with patch.object(WorkspaceDialog, "_ask_name", return_value="Solaris"), \
                 patch("split_translator.workspace_dialog.QMessageBox") as box:
                dialog.duplicate_selected()
            box.warning.assert_called_once()
            self.assertEqual(dialog.list_widget.count(), 2)


class DialogOpenGuardTests(unittest.TestCase):
    def test_open_is_enabled_for_a_workspace_with_no_books_yet(self):
        # A workspace can be built up before its books are chosen; the book side
        # then shows a placeholder.
        with _Root() as root:
            root.workspace("Nowhere", with_books=False)
            dialog = WorkspaceDialog(None)
            self.assertTrue(dialog.open_button.isEnabled())

    def test_open_is_disabled_while_only_one_book_is_set(self):
        # Half configured is a broken setup to repair here, not an empty
        # workspace: opening it would load one edition and not the other.
        with _Root() as root:
            root.workspace("Half", with_books=False)
            dialog = WorkspaceDialog(None)
            original, _translation = root.books()
            dialog.original_input.setText(original)
            dialog.on_edited()
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


class DialogEditTests(_AlwaysSaves, unittest.TestCase):
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


class DialogRenameTests(_AlwaysSaves, unittest.TestCase):
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

    def test_renaming_the_open_workspace_back_again_cancels_the_move(self):
        # The deferred move is recorded on the first rename. Editing the name
        # back to what it was leaves the slug already correct, so the move must
        # be dropped: performing it would move the folder to a name the user
        # abandoned.
        with _Root() as root:
            current = root.workspace("Lalka")
            other = root.workspace("Other")
            dialog = WorkspaceDialog(current.slug)
            dialog.select_slug(current.slug)
            dialog.name_input.setText("Lalka Prus")
            dialog.on_edited()
            dialog.select_slug(other.slug)
            self.assertEqual(dialog.rename, (current.slug, "lalka-prus"))
            dialog.select_slug(current.slug)
            dialog.name_input.setText("Lalka")
            dialog.on_edited()
            dialog.accept()
            self.assertIsNone(dialog.rename)
            self.assertEqual(dialog.chosen, current.slug)
            self.assertTrue(current.dir.is_dir())
            self.assertFalse((root.path / "lalka-prus").exists())

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

    def test_a_rename_applied_by_changing_rows_moves_the_folder(self):
        # The folder move must not depend on the user pressing Open: selecting
        # another row saves the new name too, and the folder has to follow it.
        with _Root() as root:
            target = root.workspace("Aaa")
            root.workspace("Bbb")
            dialog = WorkspaceDialog(None)
            dialog.select_slug(target.slug)
            dialog.name_input.setText("Aaa renamed")
            dialog.on_edited()
            dialog.list_widget.setCurrentRow(1)
            self.assertFalse(target.dir.exists())
            moved = root.path / "aaa-renamed"
            self.assertEqual(read_workspace(moved).name, "Aaa renamed")

    def test_a_rename_by_row_change_keeps_the_list_and_selection_in_step(self):
        with _Root() as root:
            target = root.workspace("Aaa")
            root.workspace("Bbb")
            dialog = WorkspaceDialog(None)
            dialog.select_slug(target.slug)
            dialog.name_input.setText("Aaa renamed")
            dialog.on_edited()
            dialog.list_widget.setCurrentRow(1)
            self.assertEqual(dialog.list_widget.item(0).text(), "Aaa renamed")
            dialog.select_slug("aaa-renamed")
            self.assertEqual(dialog.selected().dir, root.path / "aaa-renamed")

    def test_a_row_change_defers_the_open_workspace_folder_move(self):
        with _Root() as root:
            current = root.workspace("Aaa")
            root.workspace("Bbb")
            dialog = WorkspaceDialog(current.slug)
            dialog.select_slug(current.slug)
            dialog.name_input.setText("Aaa renamed")
            dialog.on_edited()
            dialog.list_widget.setCurrentRow(1)
            self.assertTrue(current.dir.exists())
            self.assertEqual(dialog.rename, (current.slug, "aaa-renamed"))
            dialog.select_slug(current.slug)
            self.assertEqual(dialog.selected().dir, current.dir)

    def test_a_deferred_rename_is_still_reported_when_another_row_is_opened(self):
        # The open workspace's folder move is still owed even though the slug
        # being opened is a different workspace.
        with _Root() as root:
            current = root.workspace("Aaa")
            other = root.workspace("Bbb")
            dialog = WorkspaceDialog(current.slug)
            dialog.select_slug(current.slug)
            dialog.name_input.setText("Aaa renamed")
            dialog.on_edited()
            dialog.select_slug(other.slug)
            dialog.accept()
            self.assertEqual(dialog.chosen, other.slug)
            self.assertEqual(dialog.rename, (current.slug, "aaa-renamed"))

    def test_a_failed_folder_move_is_reported_and_the_workspace_still_opens(self):
        # The spec keeps the new name in config.json and the folder where it is:
        # the workspace still loads, only the listing is less tidy.
        with _Root() as root:
            other = root.workspace("Other")
            target = root.workspace("Lalka")
            dialog = WorkspaceDialog(other.slug)
            dialog.select_slug(target.slug)
            dialog.name_input.setText("Lalka Prus")
            dialog.on_edited()
            with patch(
                "split_translator.workspace_dialog.rename_workspace_folder",
                side_effect=OSError("read-only file system"),
            ), patch(
                "split_translator.workspace_dialog.QMessageBox.warning"
            ) as warning:
                dialog.accept()
            self.assertEqual(warning.call_count, 1)
            self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
            self.assertEqual(dialog.chosen, target.slug)
            self.assertTrue(target.dir.exists())
            self.assertEqual(read_workspace(target.dir).name, "Lalka Prus")

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
            # It has no books, which is allowed: it opens with a placeholder
            # where the book view would be.
            self.assertTrue(dialog.open_button.isEnabled())


class DialogSaveButtonTests(unittest.TestCase):
    """Edits to the detail form are written only by pressing Save."""

    def test_save_is_disabled_until_something_is_edited(self):
        with _Root() as root:
            created = root.workspace("Lalka")
            dialog = WorkspaceDialog(created.slug)
            self.assertFalse(dialog.save_button.isEnabled())
            dialog.name_input.setText("Lalka renamed")
            self.assertTrue(dialog.save_button.isEnabled())

    def test_save_writes_the_form_and_goes_quiet_again(self):
        with _Root() as root:
            created = root.workspace("Lalka")
            dialog = WorkspaceDialog(created.slug)
            dialog.name_input.setText("Lalka renamed")
            dialog.save_selected()
            self.assertEqual(read_workspace(created.dir).name, "Lalka renamed")
            self.assertFalse(dialog.save_button.isEnabled())

    def test_a_rename_is_not_written_until_save_is_pressed(self):
        # The point of the button: typing a new name changes nothing on disk.
        with _Root() as root:
            created = root.workspace("Lalka")
            dialog = WorkspaceDialog(created.slug)
            dialog.name_input.setText("Lalka renamed")
            self.assertEqual(read_workspace(created.dir).name, "Lalka")

    def test_a_book_path_is_not_written_until_save_is_pressed(self):
        # Save governs the whole detail form, not the name alone.
        with _Root() as root:
            created = root.workspace("Lalka")
            dialog = WorkspaceDialog(created.slug)
            dialog.original_input.setText(created.translation_path)
            self.assertEqual(
                read_workspace(created.dir).original_path, created.original_path
            )

    def test_save_refuses_a_name_another_workspace_already_uses(self):
        with _Root() as root:
            first = root.workspace("Aaa")
            root.workspace("Bbb")
            dialog = WorkspaceDialog(first.slug)
            dialog.name_input.setText("Bbb")
            self.assertFalse(dialog.save_button.isEnabled())
            with patch.object(WorkspaceDialog, "_reject_taken_name",
                              return_value=True) as warned:
                self.assertFalse(dialog.save_selected())
            self.assertTrue(warned.called)
            self.assertEqual(read_workspace(first.dir).name, "Aaa")


class DialogLeavingUnsavedTests(unittest.TestCase):
    """Leaving a workspace with unsaved edits asks what to do with them."""

    def test_a_row_change_with_no_edits_asks_nothing(self):
        with _Root() as root:
            first = root.workspace("Aaa")
            root.workspace("Bbb")
            dialog = WorkspaceDialog(first.slug)
            with patch.object(WorkspaceDialog, "_ask_leaving") as asked:
                dialog.list_widget.setCurrentRow(1)
            self.assertFalse(asked.called)

    def test_discarding_from_the_prompt_reverts_the_form(self):
        with _Root() as root:
            first = root.workspace("Aaa")
            root.workspace("Bbb")
            dialog = WorkspaceDialog(first.slug)
            dialog.name_input.setText("Aaa renamed")
            with _leaving(_DISCARD):
                dialog.list_widget.setCurrentRow(1)
            self.assertEqual(read_workspace(first.dir).name, "Aaa")
            self.assertEqual(dialog.selected().name, "Bbb")
            # Coming back shows the workspace as it still is on disk.
            with _leaving(_DISCARD):
                dialog.list_widget.setCurrentRow(0)
            self.assertEqual(dialog.name_input.text(), "Aaa")

    def test_cancelling_keeps_the_row_and_the_edits(self):
        with _Root() as root:
            first = root.workspace("Aaa")
            root.workspace("Bbb")
            dialog = WorkspaceDialog(first.slug)
            dialog.name_input.setText("Aaa renamed")
            with _leaving(_CANCEL):
                dialog.list_widget.setCurrentRow(1)
            # Still on the workspace being edited, with the typing intact.
            self.assertEqual(dialog.selected().slug, first.slug)
            self.assertEqual(dialog.list_widget.currentRow(), 0)
            self.assertEqual(dialog.name_input.text(), "Aaa renamed")
            self.assertTrue(dialog.save_button.isEnabled())

    def test_cancelling_the_prompt_keeps_the_dialog_open(self):
        with _Root() as root:
            created = root.workspace("Lalka")
            dialog = WorkspaceDialog(created.slug)
            dialog.name_input.setText("Lalka renamed")
            with _leaving(_CANCEL):
                dialog.accept()
            self.assertEqual(dialog.result(), 0)
            self.assertEqual(read_workspace(created.dir).name, "Lalka")
