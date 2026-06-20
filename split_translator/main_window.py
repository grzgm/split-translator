"""Main application window wiring history, dictionary and PDF panels together."""

from pathlib import Path

from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWebEngineCore import QWebEngineProfile
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QSplitter,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtCore import Qt

from .config import Config, PROJECT_ROOT
from .dictionary_panel import DictionaryPanel
from .history import HistoryPanel
from .pdf_panel import PDFPanel


class TranslationTool(QMainWindow):
    def __init__(self, config: Config, profile: QWebEngineProfile):
        super().__init__()
        self.config = config
        self.profile = profile

        history_file = PROJECT_ROOT / ".translation_tool_history.json"
        self.history_panel = HistoryPanel(history_file)

        self.init_ui()
        self.setup_shortcuts()
        self.connect_signals()

    def init_ui(self):
        self.setWindowTitle("Translation Tool")
        self.setGeometry(100, 100, 1800, 900)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)

        # History panel.
        history_container = QWidget()
        history_layout = QVBoxLayout(history_container)
        history_layout.setContentsMargins(0, 0, 0, 0)
        history_layout.addWidget(QLabel("Search History"))
        history_layout.addWidget(self.history_panel)
        history_container.setMaximumWidth(200)
        main_layout.addWidget(history_container)

        # Content splitter: dictionary panel + PDF panel.
        content_splitter = QSplitter(Qt.Orientation.Horizontal)

        self.dictionary_panel = DictionaryPanel(self.profile)
        self.pdf_panel = PDFPanel(self.config)

        content_splitter.addWidget(self.dictionary_panel)
        content_splitter.addWidget(self.pdf_panel)
        content_splitter.setSizes([1000, 500])

        main_layout.addWidget(content_splitter)
        self.dictionary_panel.set_focus()

        # Prepare status bar.
        self.statusBar().showMessage("", 0)

    def connect_signals(self):
        # A dictionary lookup records history and drives the PDF search.
        self.dictionary_panel.word_searched.connect(self.on_word_searched)

        # Selecting a word from history runs a fresh lookup.
        self.history_panel.word_selected.connect(self.dictionary_panel.search_word)

        # Notice when a word was first searched on an earlier day.
        self.history_panel.previous_search.connect(self.show_previous_search_notice)

    def on_word_searched(self, word: str):
        self.history_panel.add_to_history(word)
        self.pdf_panel.search(word)

    def show_previous_search_notice(self, word: str, formatted_date: str):
        self.statusBar().setStyleSheet(
            "background-color: #fff3cd; color: #856404;"
        )
        self.statusBar().showMessage(
            f'"{word}" was previously searched on {formatted_date}', 0
        )

    def setup_shortcuts(self):
        shortcut_ctrl_l = QShortcut(QKeySequence("Ctrl+L"), self)
        shortcut_ctrl_l.activated.connect(self.focus_search)

        shortcut_f6 = QShortcut(QKeySequence("F6"), self)
        shortcut_f6.activated.connect(self.focus_search)

        shortcut_f3 = QShortcut(QKeySequence("F3"), self)
        shortcut_f3.activated.connect(self.handle_search_and_pdf_navigation)
        shortcut_ctrl_f = QShortcut(QKeySequence("Ctrl+F"), self)
        shortcut_ctrl_f.activated.connect(self.handle_search_and_pdf_navigation)

        shortcut_shift_f3 = QShortcut(QKeySequence("Shift+F3"), self)
        shortcut_shift_f3.activated.connect(self.pdf_panel.go_to_previous)

        for i in range(1, 10):
            shortcut = QShortcut(QKeySequence(f"Alt+{i}"), self)
            shortcut.activated.connect(
                lambda num=i: self.dictionary_panel.play_cambridge_audio(num)
            )

    def handle_search_and_pdf_navigation(self):
        if self.dictionary_panel.search_input.hasFocus():
            self.pdf_panel.go_to_next()
        else:
            self.focus_search()

    def focus_search(self):
        self.dictionary_panel.focus_search()

    def closeEvent(self, event):
        self.history_panel.shutdown()
        self.pdf_panel.close_doc()
        super().closeEvent(event)
