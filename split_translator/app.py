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


def main() -> int:
    # Set the application name before creating QApplication so QStandardPaths resolves
    # the profile directory to ~/.local/share/split-translator (and the right place on
    # other OSes). The organization name is left unset so the path is not nested twice.
    QCoreApplication.setApplicationName(APP_NAME)

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
        # allocated the new slug and set next_workspace to it, so nothing is
        # discovered here. settings.json needs no repair either: the next
        # iteration records the new slug when it opens the workspace.
        if window.pending_rename is not None:
            rename_workspace_folder(*window.pending_rename)
        slug = window.next_workspace
        window.deleteLater()

    return 0


if __name__ == "__main__":
    sys.exit(main())
