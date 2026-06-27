"""Main application window wiring history, dictionary and PDF panels together."""

from pathlib import Path

from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWebEngineCore import QWebEngineProfile
from PySide6.QtWidgets import (
    QDockWidget,
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
from .flashcard_panel import FlashcardPanel
from .flashcards import FlashcardStore
from .history import HistoryPanel
from .book_panel import BookPanel


class TranslationTool(QMainWindow):
    def __init__(self, config: Config, profile: QWebEngineProfile):
        super().__init__()
        self.config = config
        self.profile = profile

        history_file = PROJECT_ROOT / ".translation_tool_history.json"
        self.history_panel = HistoryPanel(history_file)

        flashcards_file = PROJECT_ROOT / ".translation_tool_flashcards.json"
        self.flashcard_store = FlashcardStore(flashcards_file)
        self.flashcard_panel = FlashcardPanel(self.flashcard_store)

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

        # Content splitter: dictionary panel + book panel.
        content_splitter = QSplitter(Qt.Orientation.Horizontal)

        self.dictionary_panel = DictionaryPanel(self.profile)
        self.book_panel = BookPanel(self.config, self.profile)

        content_splitter.addWidget(self.dictionary_panel)
        content_splitter.addWidget(self.book_panel)
        content_splitter.setSizes([1000, 500])

        main_layout.addWidget(content_splitter)
        self.dictionary_panel.set_focus()

        # Prepare status bar. Drop any highlight style once the bar goes empty
        # (for example when a timed notice clears) so the colour does not linger.
        self.statusBar().showMessage("", 0)
        self.statusBar().messageChanged.connect(self._on_status_message_changed)

        self.flashcard_dock = QDockWidget("Flashcard", self)
        self.flashcard_dock.setWidget(self.flashcard_panel)
        self.addDockWidget(
            Qt.DockWidgetArea.RightDockWidgetArea, self.flashcard_dock
        )
        # Open detached: float it as a separate window from the start. It stays
        # re-dockable, so dragging it back into the main window keeps it there.
        self.flashcard_dock.setFloating(True)
        self.flashcard_dock.hide()

    def connect_signals(self):
        # A dictionary lookup records history and drives the book search.
        self.dictionary_panel.word_searched.connect(self.on_word_searched)

        # Selecting a word from history runs a fresh lookup.
        self.history_panel.word_selected.connect(self.dictionary_panel.search_word)

        # Notice when a word was first searched on an earlier day.
        self.history_panel.previous_search.connect(self.show_previous_search_notice)

        # Get Correction drops the misspelled entry; the corrected lookup that
        # follows re-adds the right word through word_searched.
        self.dictionary_panel.correction_applied.connect(
            lambda wrong, corrected: self.history_panel.remove_word(wrong)
        )

        # Flashcard editor wiring. A Ctrl+click on the button skips the discard
        # confirmation; the Ctrl+N shortcut keeps the confirmation (Ctrl is part
        # of the shortcut, not a deliberate skip).
        self.flashcard_panel.new_button.clicked.connect(
            lambda: self.new_flashcard(force=self.flashcard_panel.ctrl_held())
        )
        self.dictionary_panel.pronunciation_grabbed.connect(
            self.on_pronunciation_grabbed
        )
        self.dictionary_panel.grammar_grabbed.connect(self.on_grammar_grabbed)
        self.dictionary_panel.selection_capture_requested.connect(
            self.on_capture_requested
        )
        self.dictionary_panel.sense_capture_requested.connect(
            self.on_sense_capture_requested
        )
        self.flashcard_panel.sense_count_changed.connect(
            self.dictionary_panel.set_sense_count
        )
        # Sync the initial sense count (the editor starts with one sense).
        self.dictionary_panel.set_sense_count(len(self.flashcard_panel._rows()))
        self.flashcard_panel.card_saved.connect(
            lambda headword: self.statusBar().showMessage(
                f'Saved flashcard "{headword}"', 4000
            )
        )
        self.flashcard_panel.save_rejected.connect(
            lambda message: self.statusBar().showMessage(message, 4000)
        )

    def on_word_searched(self, word: str):
        self.history_panel.add_to_history(word)
        self.book_panel.search(word)

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
        shortcut_shift_f3.activated.connect(self.book_panel.go_to_previous)

        for i in range(1, 10):
            shortcut = QShortcut(QKeySequence(f"Alt+{i}"), self)
            shortcut.activated.connect(
                lambda num=i: self.dictionary_panel.play_cambridge_audio(num)
            )

        shortcut_toggle_card = QShortcut(QKeySequence("Ctrl+Shift+F"), self)
        shortcut_toggle_card.activated.connect(self.toggle_flashcard)

        shortcut_new_card = QShortcut(QKeySequence("Ctrl+N"), self)
        shortcut_new_card.activated.connect(self.new_flashcard)

        shortcut_save_card = QShortcut(QKeySequence("Ctrl+S"), self)
        shortcut_save_card.activated.connect(self.flashcard_panel.save_card)

        shortcut_to_polish = QShortcut(QKeySequence("Alt+P"), self)
        shortcut_to_polish.activated.connect(self.capture_to_polish)

        shortcut_to_english = QShortcut(QKeySequence("Alt+E"), self)
        shortcut_to_english.activated.connect(self.capture_to_english)

        shortcut_to_example = QShortcut(QKeySequence("Alt+X"), self)
        shortcut_to_example.activated.connect(self.capture_to_example)

        shortcut_anchor_editor = QShortcut(QKeySequence("Ctrl+Shift+A"), self)
        shortcut_anchor_editor.activated.connect(
            self.book_panel.open_anchor_editor
        )

    def handle_search_and_pdf_navigation(self):
        if self.dictionary_panel.search_input.hasFocus():
            self.book_panel.go_to_next()
        else:
            self.focus_search()

    def focus_search(self):
        self.dictionary_panel.focus_search()

    def toggle_flashcard(self):
        if self.flashcard_dock.isVisible():
            self.flashcard_dock.hide()
            return
        self.flashcard_dock.show()
        # Grab the already-loaded page now; the panel ignores it unless the
        # editor is empty. (A still-loading page also fires the auto-grab on
        # load.)
        self.dictionary_panel.grab_pronunciation()

    def new_flashcard(self, force: bool = False):
        word = self.dictionary_panel.search_input.text().strip()
        self.flashcard_dock.show()
        # Clear first (the editor is then empty, so the grab fills everything).
        # Skip if the user declined to discard an in-progress card (force bypasses
        # the confirmation, used on a Ctrl+click of the button).
        if not self.flashcard_panel.new_card(word, force=force):
            return
        self.dictionary_panel.grab_pronunciation()

    def capture_to_polish(self):
        text = self.dictionary_panel.focused_selection()
        if not text:
            return
        self.flashcard_dock.show()
        self.flashcard_panel.set_polish_selection(text)

    def capture_to_english(self):
        text = self.dictionary_panel.focused_selection()
        if not text:
            return
        self.flashcard_dock.show()
        self.flashcard_panel.set_english_selection(text)

    def capture_to_example(self):
        text = self.dictionary_panel.focused_selection()
        if not text:
            return
        self.flashcard_dock.show()
        self.flashcard_panel.add_example_selection(text)

    def on_capture_requested(self, field: str, text: str):
        self.flashcard_dock.show()
        self._route_capture(field, text)

    def _route_capture(self, field: str, text: str):
        if field == "polish":
            self.flashcard_panel.set_polish_selection(text)
        elif field == "example":
            self.flashcard_panel.add_example_selection(text)
        else:
            self.flashcard_panel.set_english_selection(text)

    def on_sense_capture_requested(
        self, text: str, field: str, target: str, pos: str
    ):
        self.flashcard_dock.show()
        if target == "new":
            self.flashcard_panel.add_sense()
        elif target.isdigit():
            # A specific 1-based sense index chosen from the page dropdown.
            self.flashcard_panel.set_active_index(int(target))
        self._route_capture(field, text)
        if pos:
            row = self.flashcard_panel.active_row
            if row is not None and not row.pos_combo.currentText().strip():
                row.pos_combo.setCurrentText(pos)

    def _on_status_message_changed(self, message: str):
        if not message:
            self.statusBar().setStyleSheet("")

    def on_grammar_grabbed(self, data):
        if not data or not data.get("plural"):
            return
        word = self.dictionary_panel.search_input.text().strip()
        label = f'"{word}" is plural' if word else "This word is plural"
        # Same yellow highlight as the previously-searched notice; a timeout so it
        # clears on its own.
        self.statusBar().setStyleSheet(
            "background-color: #fff3cd; color: #856404;"
        )
        self.statusBar().showMessage(label, 6000)

    def on_pronunciation_grabbed(self, data):
        # Fires on every Cambridge English page load. Only fill the flashcard
        # editor when the dock is open; the panel itself drops the data unless
        # all of its fields are empty (all-or-nothing).
        if not self.flashcard_dock.isVisible():
            return
        if not data or not any(data.values()):
            return
        word = self.dictionary_panel.search_input.text().strip()
        self.flashcard_panel.set_pronunciation(
            data.get("ipa_uk"),
            data.get("ipa_us"),
            data.get("audio_uk_url"),
            data.get("audio_us_url"),
            data.get("spelling_uk"),
            data.get("spelling_us"),
            word=word or None,
        )

    def closeEvent(self, event):
        self.history_panel.shutdown()
        self.flashcard_store.shutdown()
        self.book_panel.close_doc()
        super().closeEvent(event)
