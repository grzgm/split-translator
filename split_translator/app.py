"""Application bootstrap: configures Qt, builds the web profile and runs the main window."""

# The web engine used to be pinned to software rendering here (a "--disable-gpu"
# Chromium flag) to dodge GPU/EGL context errors. That made every web view paint
# and scroll on the CPU, which left the print preview visibly laggy to scroll, so
# the flag is gone and the GPU is used again.
#
# If a machine does hit GPU trouble (blank or black web panes, EGL errors), force
# software rendering from the shell for that run, without changing the code:
#     QTWEBENGINE_CHROMIUM_FLAGS=--disable-gpu .venv/bin/python -m split_translator
# Qt reads that variable itself, so nothing here needs to set it.
#
# For QWebEngineView dev tools, launch with QTWEBENGINE_REMOTE_DEBUGGING=9222 set
# and open http://localhost:9222

import os
import sys

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from . import APP_DISPLAY_NAME, APP_NAME
from .config import load_config
from .main_window import TranslationTool
from .web import create_web_profile
from .workspace import (
    config_path_for,
    rename_workspace_folder,
    set_last_workspace,
    startup_slug,
    workspace_dir,
)
from .workspace_dialog import WorkspaceDialog


def pick_workspace() -> str | None:
    """Show the picker and return the chosen slug, or None if the user cancels.

    Built with no current workspace, so it never defers a folder move: any
    rename it makes is applied immediately, because no stores hold those paths.
    """
    dialog = WorkspaceDialog(None)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None
    return dialog.chosen


def choose_startup_workspace() -> str | None:
    """The workspace to open, asking only when it cannot be decided."""
    slug = startup_slug()
    if slug is not None:
        return slug
    return pick_workspace()


def apply_pending_rename(
    pending: tuple[str, str] | None, next_slug: str | None
) -> str | None:
    """Perform the deferred folder move, and report the slug to open next.

    The move waits until here because it cannot run while the window's stores
    hold paths into that folder. A failure is reported and not rolled back, as
    the spec asks: the new name is already in the workspace's config.json and
    the workspace still loads from its old folder. That folder is then the one
    to open, because the slug the dialog allocated was never created.
    """
    if pending is None:
        return next_slug
    old_slug, new_slug = pending
    try:
        rename_workspace_folder(old_slug, new_slug)
    except OSError as exc:
        QMessageBox.warning(
            None,
            "Could not rename the workspace folder",
            f"The new name is saved, but the folder is still named "
            f"'{old_slug}':\n\n{exc}\n\n"
            "The workspace still opens normally.",
        )
        # Fall back to the folder that still exists, but only when the target
        # really is absent. A different workspace may have claimed that slug
        # since the move was recorded, which is what made the move fail; opening
        # the old folder then would open the wrong workspace.
        if next_slug == new_slug and not workspace_dir(new_slug).is_dir():
            return old_slug
    return next_slug


def main() -> int:
    # Set the application name before creating QApplication so QStandardPaths resolves
    # the profile directory to ~/.local/share/split-translator (and the right place on
    # other OSes). The organization name is left unset so the path is not nested twice.
    QCoreApplication.setApplicationName(APP_NAME)

    # Ask for the desktop portal's file dialogs instead of Qt's own plain ones.
    # Qt only offers a native dialog when a platform theme plugin supplies one,
    # and it looks for those plugins in PySide6's bundled directory, which holds
    # the portal and GTK themes but not KDEPlasmaPlatformTheme6.so. That one
    # lives in the system Qt plugin directory PySide6 never searches, which is
    # why the file chooser is the plain Qt widget dialog. Pointing at the system
    # directory instead would mix system Qt libraries into a PySide6 process and
    # break the moment the two versions diverge, whereas the portal plugin is
    # already bundled here and talks to whichever backend the desktop provides.
    # setdefault so the choice can still be overridden from the shell.
    os.environ.setdefault("QT_QPA_PLATFORMTHEME", "xdgdesktopportal")

    app = QApplication(sys.argv)
    # setApplicationDisplayName lives on QGuiApplication and needs the instance to exist.
    app.setApplicationDisplayName(APP_DISPLAY_NAME)

    # The profile is parented to the app so it outlives every view that uses it.
    # That is also what lets cookies, cache and Cloudflare clearance survive a
    # workspace switch: only the window is rebuilt, never the profile.
    profile = create_web_profile(app)

    slug = choose_startup_workspace()
    while slug is not None:
        set_last_workspace(slug)
        config = load_config(config_path_for(slug))
        try:
            window = TranslationTool(config, profile)
        except Exception as exc:
            # both_books_resolve only proves the book files exist. A file with an
            # unsupported extension, or a corrupt epub or pdf, still raises out of
            # BookPanel's constructor, so this is the net that sends the user back
            # to the picker to repair the paths rather than killing the app.
            QMessageBox.warning(
                None,
                "Could not open workspace",
                f"'{config.name}' could not be opened:\n\n{exc}\n\n"
                "Check its book paths.",
            )
            slug = pick_workspace()
            continue
        window.show()
        app.exec()
        # The folder move is deferred to here because it cannot run while the
        # window's stores hold paths into that folder. The dialog already
        # allocated the new slug and set next_workspace to it, so no slug is
        # discovered here; only a failed move changes which one is opened.
        # settings.json needs no repair either: the next iteration records the
        # slug it opens the workspace with.
        slug = apply_pending_rename(window.pending_rename, window.next_workspace)
        window.deleteLater()

    return 0


if __name__ == "__main__":
    sys.exit(main())
