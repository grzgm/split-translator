"""Main application window wiring history, dictionary and PDF panels together."""


from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence, QShortcut
from PySide6.QtWebEngineCore import QWebEngineProfile
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
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

from .book_panel import BookPanel
from .config import Config
from .dictionary_panel import DictionaryPanel
from .flashcard_graph import FlashcardGraphWindow
from .flashcard_panel import FlashcardPanel
from .flashcard_print_window import FlashcardPrintWindow
from .flashcard_tags import book_tag
from .flashcards import FlashcardStore
from .history import HistoryPanel
from .shortcuts import SHORTCUTS
from .shortcuts_dialog import ShortcutsDialog
from .status_bar import StatusBar
from .workspace import read_workspace
from .workspace_dialog import WorkspaceDialog


def _grab_headword(data, search_text: str) -> str | None:
    """Which word a Cambridge grab should put in the Headword field.

    Cambridge's own headword is preferred, because it is the canonical spelling
    ("run" for a search of "running"); the raw search term is the fallback for a
    page that has none. None when there is neither, which leaves the field as it
    is. Both grabs, the passive one and the fill-empty one, read this, so the
    two cannot drift apart."""
    word = (data.get("headword") or "").strip()
    if not word:
        word = (search_text or "").strip()
    return word or None


class TranslationTool(QMainWindow):
    # The flashcard dock's title, and the marker appended to it while the card
    # in the editor has unsaved edits (a text editor's modified-file "*").
    _FLASHCARD_TITLE = "Flashcard"
    _ALTERED_MARKER = " *"

    def __init__(self, config: Config, profile: QWebEngineProfile):
        super().__init__()
        self.config = config
        self.profile = profile

        # Every store writes into the open workspace's own folder, which is what
        # keeps one workspace's deck and history out of another's.
        history_file = self.config.dir / "history.json"
        self.history_panel = HistoryPanel(history_file)

        flashcards_file = self.config.dir / "flashcards.json"
        flashcard_links_file = self.config.dir / "flashcard_links.json"
        self.flashcard_store = FlashcardStore(flashcards_file, flashcard_links_file)
        self.flashcard_panel = FlashcardPanel(self.flashcard_store)
        # The tag recording which book a card's example came from. Computed once
        # here because this window is the only component that knows the config,
        # and passing it with each fill (rather than handing it to the panel as
        # state) keeps the panel free of config entirely.
        self.book_tag = self._source_book_tag()
        self.flashcard_graph_window = None
        self.flashcard_print_window = None

        # Set when the user picks a different workspace (or renames the open
        # one, which moves its folder). app.main reads both after this window
        # closes: the window is rebuilt rather than re-pointed, because every
        # store's path is fixed at construction.
        self.next_workspace: str | None = None
        self.pending_rename: tuple[str, str] | None = None

        self.init_ui()
        self.setup_menu()
        self.setup_shortcuts()
        self.connect_signals()

    def _source_book_tag(self) -> str:
        """The tag naming the book a card's example came from. Taken from the
        Original edition because book search only ever runs on that one, so an
        auto-filled sentence is always an Original sentence."""
        return book_tag(self.config.original_path)

    def init_ui(self):
        # The workspace name is in the title because the panels look identical
        # from one workspace to the next.
        self.setWindowTitle(f"Translation Tool - {self.config.name}")
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

        # The status bar owns its own highlighting, arrival flash and close
        # button (see status_bar.py); the window only says what to show.
        self.status_bar = StatusBar(self)
        self.setStatusBar(self.status_bar)

        self.flashcard_dock = QDockWidget(self._FLASHCARD_TITLE, self)
        self.flashcard_dock.setWidget(self.flashcard_panel)
        self.addDockWidget(
            Qt.DockWidgetArea.RightDockWidgetArea, self.flashcard_dock
        )
        # On screen from the start, so the editor is there to capture into
        # without a toggle first, and docked into the right-hand area rather
        # than floating: the same state Ctrl+N opens it in. addDockWidget
        # already leaves it docked, so this only has to show it. It stays
        # detachable, through Alt+D or the title bar's float button.
        # Ctrl+Shift+F now hides it on the first press rather than showing it.
        self.flashcard_dock.show()

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

        print_action = QAction("Print Flashcards", self)
        print_action.setShortcut(QKeySequence("Ctrl+Shift+P"))
        print_action.triggered.connect(self.open_flashcard_print)

        workspace_action = QAction("Workspaces...", self)
        workspace_action.triggered.connect(self.open_workspaces)

        view_menu = QMenu("View", self)
        view_menu.addAction(flashcard_action)
        view_menu.addAction(anchor_action)
        view_menu.addAction(graph_action)
        view_menu.addAction(print_action)
        # Separated because this one is not a view: it changes which data the
        # whole window is showing.
        view_menu.addSeparator()
        view_menu.addAction(workspace_action)

        view_button = QToolButton()
        view_button.setText("View")
        view_button.setMenu(view_menu)
        view_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)

        # A permanent widget sits on the right of the status bar and is never
        # hidden by showMessage. (A normal addWidget would be covered the moment
        # a status notice is shown, which is why the button kept disappearing.)
        # It is added after the bar's own close button, so it sits to the right
        # of it and the close button stays next to the notice text.
        self.status_bar.addPermanentWidget(view_button)

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
        self.dictionary_panel.correction_unavailable.connect(
            self.show_correction_unavailable
        )

        # Flashcard editor wiring. A Ctrl+click on the button skips the discard
        # confirmation; the Ctrl+N shortcut keeps the confirmation (Ctrl is part
        # of the shortcut, not a deliberate skip).
        self.flashcard_panel.new_button.clicked.connect(
            lambda: self.new_flashcard(force=self.flashcard_panel.ctrl_held())
        )
        self.flashcard_panel.fill_empty_requested.connect(
            self.fill_empty_flashcard
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
        # The buttons on a Cambridge pronunciation block replace that region's
        # clip and its notation independently, so they route to a method each.
        self.dictionary_panel.audio_capture_requested.connect(
            self.flashcard_panel.set_audio
        )
        self.dictionary_panel.ipa_capture_requested.connect(
            self.flashcard_panel.set_ipa
        )
        self.flashcard_panel.card_saved.connect(
            lambda headword: self.status_bar.show_message(
                f'Saved flashcard "{headword}"'
            )
        )
        self.flashcard_panel.save_rejected.connect(
            self.status_bar.show_message
        )
        # Selecting a flashcard (saved-list click or graph activation) looks its
        # headword up in the dictionary and the book, but records no history and
        # leaves the loaded card untouched.
        self.flashcard_panel.card_loaded.connect(self.on_flashcard_loaded)
        # Unsaved edits put a "*" on the dock title, the way a text editor marks
        # a modified file.
        self.flashcard_panel.altered_changed.connect(
            self.on_flashcard_altered_changed
        )
        # A book match on the Original edition auto-fills the flashcard's first
        # example with the sentence around the match (only while the dock is
        # open and the card is unaltered).
        self.book_panel.book_sentence_matched.connect(
            self.on_book_sentence_matched
        )
        # Keep the dock's saved list and the loaded card's printed button in
        # step with external flag changes (bulk toggle / auto-flag from the
        # print window), the same way the print window's own panel already
        # does.
        self.flashcard_store.cards_changed.connect(
            self.flashcard_panel._refresh_saved_list
        )

    def on_word_searched(self, word: str):
        # A new search starts a fresh card: clear the editor first (only when the
        # current card is unaltered; an altered card is left alone) so the word's
        # pronunciation and the book sentence fill into a blank card, not on top
        # of the previous word's senses and examples. Runs once per search,
        # before the repeating page-load grabs.
        self.flashcard_panel.prepare_for_new_search()
        # Seed the headword with the phrase just searched, after the clear (which
        # would otherwise wipe it). The card then carries the word straight away,
        # even if the dictionary sites never load; when the Cambridge page does
        # arrive, the grab replaces the seed with its canonical spelling (see
        # on_pronunciation_grabbed).
        self.flashcard_panel.autofill_headword(word)
        self.history_panel.add_to_history(word)
        self.book_panel.search(word)

    def on_flashcard_altered_changed(self, altered: bool):
        # The card in the editor gained or lost unsaved edits. Mark the dock
        # title with a "*" while it has them, so the state is visible even when
        # the dock is floating as its own window and its title is the only
        # chrome on show.
        #
        # The two titles are read off the class, not off self: they are
        # constants rather than per-instance state, and reading them this way
        # lets the method be driven against a stand-in carrier in the tests (as
        # toggle_flashcard_dock is) without building the WebEngine-heavy window.
        title = TranslationTool._FLASHCARD_TITLE
        if altered:
            title += TranslationTool._ALTERED_MARKER
        self.flashcard_dock.setWindowTitle(title)

    def on_flashcard_loaded(self, headword: str):
        # A flashcard was selected and loaded into the editor. Look its headword
        # up in the dictionary and drive the book search, but skip the history
        # add and the editor reset that on_word_searched does: the card was just
        # loaded and must stay put. search_headword also disarms the passive
        # auto-grab so the Cambridge load cannot overwrite the loaded card.
        word = (headword or "").strip()
        if not word:
            return
        self.dictionary_panel.search_headword(word)
        self.book_panel.search(word)

    def show_previous_search_notice(self, word: str, formatted_date: str):
        # A notice, not a timed message: it stays until dismissed, so a word you
        # have already looked up cannot be missed by glancing away.
        self.status_bar.show_notice(
            f'"{word}" was previously searched on {formatted_date}'
        )

    def show_correction_unavailable(self, word: str):
        # Get Correction found nothing to apply (no spelling suggestion on the
        # Google meaning page, or the page hit an anti-bot wall). Say so instead
        # of failing silently.
        if word:
            message = f'No spelling correction found for "{word}"'
        else:
            message = "No word to correct"
        self.status_bar.show_message(message)

    def _resolve_handler(self, handler: str):
        # Resolve a registry handler name to the bound method it names, walking
        # dotted paths from self (e.g. "book_panel.go_to_previous"). Keeps the
        # registry able to target child-panel methods without wrapper methods.
        target = self
        for part in handler.split("."):
            target = getattr(target, part)
        return target

    def _build_registry_shortcuts(self):
        # Create a QShortcut for every registry entry that names a handler, and
        # return them. Display-only entries (handler is None: the two View-menu
        # shortcuts and the Alt+1..9 range) are skipped here and wired elsewhere.
        # The handler is walked from self (like _resolve_handler, inlined so the
        # builder depends only on self carrying the handler attributes, letting a
        # test drive it with a stub owner as self).
        created = []
        for entry in SHORTCUTS:
            if entry.handler is None:
                continue
            target = self
            for part in entry.handler.split("."):
                target = getattr(target, part)
            shortcut = QShortcut(QKeySequence(entry.keys), self)
            shortcut.activated.connect(target)
            created.append(shortcut)
        return created

    def setup_shortcuts(self):
        # Real bindings come from the shortcut registry (the single source of
        # truth the Ctrl+/ overlay also renders); see shortcuts.py.
        self._registry_shortcuts = self._build_registry_shortcuts()

        # Alt+1..9 is a range, not one binding, so it stays a loop here (the
        # overlay lists it as a single display-only entry).
        for i in range(1, 10):
            shortcut = QShortcut(QKeySequence(f"Alt+{i}"), self)
            shortcut.activated.connect(
                lambda num=i: self.play_audio_shortcut(num)
            )

        # Ctrl+Shift+F (Flashcard) and Ctrl+Shift+A (Sync Editor) live on their
        # View-menu actions in setup_menu, which provide the application-wide
        # shortcut. Defining a QShortcut here too would make the sequence
        # ambiguous and neither would fire. They are display-only registry
        # entries so the overlay still lists them.

    def show_shortcuts(self):
        # Ctrl+/: open the keyboard-shortcuts cheat sheet, built from the same
        # registry that created the bindings.
        ShortcutsDialog(SHORTCUTS, parent=self).exec()

    def copy_translation_prompt(self):
        # Ctrl+T: copy an LLM prompt asking for the contextual translation of the
        # search word, using the sentence around the current Original-edition
        # book match as context. Silent no-op (clipboard untouched) when there is
        # no search word or no Original match, matching the book auto-fill's
        # "Original only, no fuzzing" rule; a status note explains why.
        word = self.dictionary_panel.search_input.text().strip()
        if not word:
            self.status_bar.show_message(
                "No search word to build a translation prompt"
            )
            return

        def _on_sentence(sentence):
            sentence = (sentence or "").strip()
            if not sentence:
                self.status_bar.show_message(
                    "No book sentence for the current match"
                )
                return
            prompt = (
                f'Translate "{word}" to Polish in the context of "{sentence}"'
            )
            QApplication.clipboard().setText(prompt)
            self.status_bar.show_message("Copied translation prompt")

        self.book_panel.current_match_sentence(_on_sentence)

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

    def focus_own_notation(self):
        # Ctrl+P: jump straight to the card's Own notation from anywhere,
        # bringing the editor back on screen if it was hidden (like the capture
        # shortcuts do). Where the editor lives is left alone: a floating editor
        # stays floating, since docking belongs to Alt+D and Ctrl+Shift+F.
        self.flashcard_dock.show()
        self.flashcard_panel.focus_own_notation()

    def toggle_flashcard(self):
        if self.flashcard_dock.isVisible():
            self.flashcard_dock.hide()
            return
        # Open it docked, re-docking it if it was left floating, so Ctrl+Shift+F
        # brings the editor back where it starts and where Ctrl+N puts it. Alt+D
        # and the title bar's float button are how it gets detached again.
        self.flashcard_dock.setFloating(False)
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

    def open_flashcard_print(self):
        if self.flashcard_print_window is None:
            self.flashcard_print_window = FlashcardPrintWindow(self.flashcard_store)
        self.flashcard_print_window.panel._refresh_saved_list()
        self.flashcard_print_window.refresh_preview()
        self.flashcard_print_window.show()
        self.flashcard_print_window.raise_()
        self.flashcard_print_window.activateWindow()

    def open_workspaces(self):
        """Show the workspace picker.

        Choosing a different workspace, renaming the open one, or changing its
        book paths all close this window; app.main then builds a fresh one.
        Nothing is swapped in place: every store's path is fixed when it is
        constructed, and closeEvent is the only code that flushes them.
        """
        current = self.config.dir.name
        dialog = WorkspaceDialog(current, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        if dialog.chosen is None:
            return
        if dialog.chosen == current and dialog.rename is None:
            # Same workspace and same folder, so a rebuild is only needed if the
            # books or the name changed underneath us. The name counts because a
            # rename whose slug is unchanged ("Lalka" to "Lalka!") moves no
            # folder, and without it the title bar would keep the old name until
            # the next launch.
            reloaded = read_workspace(self.config.dir)
            if (
                reloaded is not None
                and reloaded.name == self.config.name
                and reloaded.original_path == self.config.original_path
                and reloaded.translation_path == self.config.translation_path
            ):
                return
        self.next_workspace = dialog.chosen
        self.pending_rename = dialog.rename
        self.close()

    def close_child_windows(self):
        """Close the flashcard graph and print windows.

        Both are created with no parent, so they are independent top-level
        windows. Two things follow: app.exec() does not return while one is
        still visible, which would hang a workspace switch, and each holds this
        workspace's flashcard store, so a survivor would sit there showing the
        previous workspace's deck.
        """
        for window in (self.flashcard_graph_window, self.flashcard_print_window):
            if window is not None:
                window.close()

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
        # Ctrl+N always opens the editor in the docked state, re-docking it if it
        # was left floating.
        self.flashcard_dock.setFloating(False)
        self.flashcard_dock.show()
        # Clear first (the editor is then empty, so the grab fills everything,
        # headword included). Skip if the user declined to discard an in-progress
        # card (force bypasses the confirmation, used on a Ctrl+click of the
        # button).
        if not self.flashcard_panel.new_card(force=force):
            return
        # Seed the headword from the search box, so the fresh card is filled even
        # when the Cambridge page never loaded; the grab below replaces it with
        # the page's own headword when it is there.
        self.flashcard_panel.autofill_headword(
            self.dictionary_panel.search_input.text()
        )
        self.dictionary_panel.grab_pronunciation()
        # Also pull the current Original-edition book sentence into the fresh
        # card's first example, so New from word populates it immediately rather
        # than only on the next book match. current_match_sentence applies the
        # Original-only gate and hands back "" when there is no match, which
        # autofill_book_example ignores.
        self.book_panel.current_match_sentence(
            lambda sentence: self.flashcard_panel.autofill_book_example(
                sentence, self.book_tag
            )
        )

    def fill_empty_flashcard(self):
        """The New button's dropdown item: same three sources as new_flashcard,
        but nothing is cleared and nothing already filled is overwritten.

        It is for the card you have half built, or an old card you have loaded
        and looked up again: whatever is still blank is filled from the search
        box, the Cambridge page on screen and the current book match, and the
        rest is left exactly as it is. The grab is taken with its own callback
        rather than through pronunciation_grabbed, so this one-shot fill reads
        the page the user is looking at and no passive listener acts on it."""
        self.flashcard_dock.setFloating(False)
        self.flashcard_dock.show()
        self.flashcard_panel.fill_empty_headword(
            self.dictionary_panel.search_input.text()
        )
        self.dictionary_panel.grab_pronunciation(self.on_fill_empty_grabbed)
        self.book_panel.current_match_sentence(
            lambda sentence: self.flashcard_panel.fill_empty_book_example(
                sentence, self.book_tag
            )
        )

    def on_fill_empty_grabbed(self, data):
        """The Cambridge page's answer to a fill-empty grab. Same headword rule
        as on_pronunciation_grabbed; the panel then fills only its blanks."""
        if not data or not any(data.values()):
            return
        self.flashcard_panel.fill_empty_pronunciation(
            data.get("ipa_uk"),
            data.get("ipa_us"),
            data.get("audio_uk_url"),
            data.get("audio_us_url"),
            data.get("spelling_uk"),
            data.get("spelling_us"),
            word=_grab_headword(
                data, self.dictionary_panel.search_input.text()
            ),
        )

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

    def _route_capture(self, field: str, text: str, append: bool = False):
        if field == "polish":
            if append:
                self.flashcard_panel.append_polish_selection(text)
            else:
                self.flashcard_panel.set_polish_selection(text)
        elif field == "example":
            # Examples always accumulate; there is no replace/append split.
            self.flashcard_panel.add_example_selection(text)
        else:
            if append:
                self.flashcard_panel.append_english_selection(text)
            else:
                self.flashcard_panel.set_english_selection(text)

    def on_sense_capture_requested(
        self, text: str, field: str, target: str, pos: str
    ):
        self.flashcard_dock.show()
        # Target strings from the injected page buttons, all acting on the sense
        # currently active in the editor:
        #   "current" -> replace the active sense's field ("set" button)
        #   "append"  -> append into the active sense's field ("add" button)
        #   "new"     -> a fresh sense, replace ("+new" button)
        append = target == "append"
        if target == "new":
            self.flashcard_panel.add_sense()
        self._route_capture(field, text, append)
        if pos:
            row = self.flashcard_panel.active_row
            if row is not None and not row.pos_combo.currentText().strip():
                row.pos_combo.setCurrentText(pos)

    def on_grammar_grabbed(self, data):
        if not data or not data.get("plural"):
            return
        word = self.dictionary_panel.search_input.text().strip()
        label = f'"{word}" is plural' if word else "This word is plural"
        # A notice like the previously-searched one: highlighted, and dismissed
        # by hand rather than on a timeout.
        self.status_bar.show_notice(label)

    def on_book_sentence_matched(self, sentence):
        # A book match on the Original edition supplies the sentence around it.
        # Fill it into the flashcard editor's first example, but only when the
        # dock is open; the panel itself uses it only while its card is
        # unaltered (see autofill_book_example).
        if not self.flashcard_dock.isVisible():
            return
        self.flashcard_panel.autofill_book_example(sentence, self.book_tag)

    def on_pronunciation_grabbed(self, data):
        # Fires on every Cambridge English page load. Only fill the flashcard
        # editor when the dock is open; the panel itself refills only while the
        # card is unaltered, and silently ignores the data once it is altered
        # (see autofill_pronunciation).
        if not self.flashcard_dock.isVisible():
            return
        if not data or not any(data.values()):
            return
        self.flashcard_panel.autofill_pronunciation(
            data.get("ipa_uk"),
            data.get("ipa_us"),
            data.get("audio_uk_url"),
            data.get("audio_us_url"),
            data.get("spelling_uk"),
            data.get("spelling_us"),
            word=_grab_headword(
                data, self.dictionary_panel.search_input.text()
            ),
        )


    def closeEvent(self, event):
        self.close_child_windows()
        self.history_panel.shutdown()
        self.flashcard_store.shutdown()
        self.book_panel.close_doc()
        super().closeEvent(event)
