"""The deferred folder rename the workspace session performs between two windows.

The move itself cannot run while the window is up, because its stores hold
absolute paths into that folder, so the session in app.py does it once the
window has closed and everything has flushed. What is tested here is the
decision around the move, which is pure logic: whether it happened, and which
folder the session should open next.
"""

import unittest
from unittest.mock import patch

from split_translator.app import apply_pending_rename


class PendingRenameTests(unittest.TestCase):
    def test_no_pending_rename_opens_the_chosen_slug(self):
        with patch("split_translator.app.rename_workspace_folder") as move:
            self.assertEqual(apply_pending_rename(None, "lalka"), "lalka")
        move.assert_not_called()

    def test_a_successful_move_opens_the_new_slug(self):
        with patch("split_translator.app.rename_workspace_folder") as move:
            slug = apply_pending_rename(("lalka", "lalka-prus"), "lalka-prus")
        move.assert_called_once_with("lalka", "lalka-prus")
        self.assertEqual(slug, "lalka-prus")

    def test_a_failed_move_is_reported_and_opens_the_folder_that_exists(self):
        # The new slug was never created, so opening it would fail. The old
        # folder is still there and its config.json already carries the new
        # name, so that is the one to open.
        with patch(
            "split_translator.app.rename_workspace_folder",
            side_effect=OSError("read-only file system"),
        ), patch("split_translator.app.QMessageBox.warning") as warning:
            slug = apply_pending_rename(("lalka", "lalka-prus"), "lalka-prus")
        self.assertEqual(warning.call_count, 1)
        self.assertEqual(slug, "lalka")

    def test_a_failed_move_leaves_a_different_chosen_workspace_alone(self):
        # The rename was owed on the workspace that was open, but the user
        # opened another one, which the failure has nothing to do with.
        with patch(
            "split_translator.app.rename_workspace_folder",
            side_effect=OSError("read-only file system"),
        ), patch("split_translator.app.QMessageBox.warning"):
            slug = apply_pending_rename(("lalka", "lalka-prus"), "solaris")
        self.assertEqual(slug, "solaris")

    def test_a_failed_move_on_quit_still_reports_no_next_workspace(self):
        with patch(
            "split_translator.app.rename_workspace_folder",
            side_effect=OSError("read-only file system"),
        ), patch("split_translator.app.QMessageBox.warning"):
            self.assertIsNone(apply_pending_rename(("lalka", "lalka-prus"), None))


if __name__ == "__main__":
    unittest.main()


class PendingRenameCollisionTests(unittest.TestCase):
    """A failed move must not send the loop to the wrong workspace.

    The fallback to the old folder is only right when the target folder is not
    there. If another workspace claimed that slug after the move was recorded,
    which is exactly what makes the move fail, the slug the user chose is a real
    workspace and opening the old folder would open the wrong one.
    """

    def test_falls_back_to_the_old_slug_when_the_target_is_absent(self):
        with patch(
            "split_translator.app.rename_workspace_folder",
            side_effect=OSError("read-only"),
        ), patch("split_translator.app.QMessageBox"), patch(
            "split_translator.app.workspace_dir"
        ) as target:
            target.return_value.is_dir.return_value = False
            slug = apply_pending_rename(("lalka", "lalka-prus"), "lalka-prus")
        self.assertEqual(slug, "lalka")

    def test_keeps_the_chosen_slug_when_another_workspace_holds_it(self):
        with patch(
            "split_translator.app.rename_workspace_folder",
            side_effect=OSError("target exists"),
        ), patch("split_translator.app.QMessageBox"), patch(
            "split_translator.app.workspace_dir"
        ) as target:
            target.return_value.is_dir.return_value = True
            slug = apply_pending_rename(("lalka", "lalka-prus"), "lalka-prus")
        self.assertEqual(slug, "lalka-prus")
