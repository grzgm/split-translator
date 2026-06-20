"""Application bootstrap: configures Qt, builds the web profile and runs the main window."""

import os

# Force software rendering to avoid GPU/EGL context errors. Must be set before any Qt
# WebEngine import initialises the GPU process.
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu")

# Uncomment to open http://localhost:9222 for QWebEngineView dev tools.
# os.environ.setdefault("QTWEBENGINE_REMOTE_DEBUGGING", "9222")

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
