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
from PySide6.QtWidgets import QApplication

from . import APP_DISPLAY_NAME, APP_NAME
from .config import load_config
from .main_window import TranslationTool
from .web import create_web_profile


def main() -> int:
    # Set the application name before creating QApplication so QStandardPaths resolves
    # the profile directory to ~/.local/share/split-translator (and the right place on
    # other OSes). The organization name is left unset so the path is not nested twice.
    QCoreApplication.setApplicationName(APP_NAME)

    config = load_config()

    app = QApplication(sys.argv)
    # setApplicationDisplayName lives on QGuiApplication and needs the instance to exist.
    app.setApplicationDisplayName(APP_DISPLAY_NAME)

    # The profile is parented to the app so it outlives every view that uses it.
    profile = create_web_profile(app)

    window = TranslationTool(config, profile)
    window.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
