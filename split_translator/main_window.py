"""Main application window wiring history, dictionary and PDF panels together."""

from pathlib import Path

from PySide6.QtGui import QAction, QKeySequence, QShortcut
from PySide6.QtWebEngineCore import QWebEngineProfile
from PySide6.QtWidgets import (
    QDockWidget,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QSplitter,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtCore import Qt

from .config import Config, CONFIG_DIR
from .dictionary_panel import DictionaryPanel
from .flashcard_panel import FlashcardPanel
from .flashcard_graph import FlashcardGraphWindow
from .flashcards import FlashcardStore
from .history import HistoryPanel
from .book_panel import BookPanel


class TranslationTool(QMainWindow):
    def __init__(self, config: Config, profile: QWebEngineProfile):
        super().__init__()
        self.config = config
        self.profile = profile

        history_file = CONFIG_DIR / "history.json"
        self.history_panel = HistoryPanel(history_file)

        flashcards_file = CONFIG_DIR / "flashcards.json"
        self.flashcard_store = FlashcardStore(flashcards_file)
        self.flashcard_panel = FlashcardPanel(self.flashcard_store)
        self.flashcard_graph_window = None

        self.init_ui()
        self.setup_menu()
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

    def setup_menu(self):
        # A View menu reachable without keyboard shortcuts. PySide6's bundled Qt
        # ships no KDE platform-theme plugin, so a top menu bar cannot export to
        # the Plasma Global Menu and would just take a strip at the top. Instead
        # the menu is a single button living in the status bar, so it shares that
        # bottom row and adds no extra strip.
        #
        # The actions also own their Ctrl+Shift+F / Ctrl+Shift+A shortcuts (the
        # matching QShortcuts are removed from setup_shortcuts to avoid an
        # ambiguous binding), so the sequences keep working and show in the menu.
        flashcard_action = QAction("Flashcard Editor", self)
        flashcard_action.setShortcut(QKeySequence("Ctrl+Shift+F"))
        flashcard_action.triggered.connect(self.toggle_flashcard)

        anchor_action = QAction("Sync Editor", self)
        anchor_action.setShortcut(QKeySequence("Ctrl+Shift+A"))
        anchor_action.triggered.connect(self.book_panel.open_anchor_editor)

        graph_action = QAction("Flashcard Graph", self)
        graph_action.triggered.connect(self.open_flashcard_graph)

        view_menu = QMenu("View", self)
        view_menu.addAction(flashcard_action)
        view_menu.addAction(anchor_action)
        view_menu.addAction(graph_action)

        view_button = QToolButton()
        view_button.setText("View")
        view_button.setMenu(view_menu)
        view_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)

        # A permanent widget sits on the right of the status bar and is never
        # hidden by showMessage. (A normal addWidget would be covered the moment
        # a status notice is shown, which is why the button kept disappearing.)
        self.statusBar().addPermanentWidget(view_button)

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
        # A "replace" button on a Cambridge pronunciation captures that clip's
        # region and URL into the current card's audio.
        self.dictionary_panel.audio_capture_requested.connect(
            self.flashcard_panel.set_audio
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
                lambda num=i: self.play_audio_shortcut(num)
            )

        # Ctrl+Shift+F (Flashcard) and Ctrl+Shift+A (Sync Editor) live on their
        # View-menu actions in setup_menu, which provide the application-wide
        # shortcut. Defining a QShortcut here too would make the sequence
        # ambiguous and neither would fire.

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

        shortcut_dock_flashcard = QShortcut(QKeySequence("Alt+D"), self)
        shortcut_dock_flashcard.activated.connect(self.toggle_flashcard_dock)

    def handle_search_and_pdf_navigation(self):
        if self.dictionary_panel.search_input.hasFocus():
            self.book_panel.go_to_next()
        else:
            self.focus_search()

    def play_audio_shortcut(self, num: int):
        # While the flashcard editor is focused, Alt+1 / Alt+2 play that card's
        # UK / US pronunciation; every other case (and Alt+3..9) plays the
        # dictionary's Cambridge audio as before.
        if num in (1, 2) and self.flashcard_panel.has_focus():
            self.flashcard_panel.play_audio("uk" if num == 1 else "us")
            return
        self.dictionary_panel.play_cambridge_audio(num)

    def toggle_flashcard_dock(self):
        # Alt+D flips the flashcard editor between floating and docked, mirroring
        # the float button in the dock's title bar. It only acts while the editor
        # has focus, so the sequence stays free everywhere else.
        if not self.flashcard_panel.has_focus():
            return
        self.flashcard_dock.setFloating(not self.flashcard_dock.isFloating())
        # Docking moves focus off the editor, which would block the next Alt+D.
        # Put it back so the shortcut keeps toggling without a click in between.
        self.flashcard_panel.focus_editor()

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

    def open_flashcard_graph(self):
        if self.flashcard_graph_window is None:
            self.flashcard_graph_window = FlashcardGraphWindow(self.flashcard_store)
            self.flashcard_graph_window.card_activated.connect(
                self.on_graph_card_activated
            )
            # Refresh the graph in place whenever cards or links change, so the
            # window stays current without losing manually arranged positions.
            self.flashcard_store.cards_changed.connect(
                self.refresh_flashcard_graph
            )
        self.flashcard_graph_window.rebuild()
        self.flashcard_graph_window.show()
        self.flashcard_graph_window.raise_()
        self.flashcard_graph_window.activateWindow()

    def refresh_flashcard_graph(self):
        window = self.flashcard_graph_window
        if window is not None and window.isVisible():
            window.refresh()

    def on_graph_card_activated(self, card_id: str):
        card = next(
            (c for c in self.flashcard_store.cards if c.id == card_id), None
        )
        if card is None:
            return
        self.flashcard_dock.show()
        self.flashcard_panel.load_card(card)

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
