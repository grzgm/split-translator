"""Flashcard editor: a dock-panel widget for building one card at a time."""

from contextlib import contextmanager
from datetime import datetime

from PySide6.QtCore import QEvent, Qt, QUrl, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontMetrics,
    QIcon,
    QPainter,
    QPixmap,
)
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from .flashcard_editor_state import EditorState
from .flashcards import Card, FlashcardStore, Link, LINK_TYPES, Sense

# Placeholder used in staged links when the edited card has not been saved yet;
# replaced with the real card id at first Save (see _partner_id).
_NEW_CARD_ANCHOR = "__new__"

# A light-blue border shown on a fillable field while it is still empty, so it is
# easy to see at a glance what remains to be filled. It clears back to the default
# border the moment the field has any content.
_EMPTY_BORDER = "2px solid #aaccfe"


def _mark_empty(field) -> None:
    """Give a field the empty-field border when blank, default otherwise.

    Works for both ``QLineEdit`` (``text()``) and an editable ``QComboBox``
    (``currentText()``); the stylesheet selector is keyed off the widget's class
    so it targets the right control."""
    text = field.currentText() if isinstance(field, QComboBox) else field.text()
    type_name = type(field).__name__
    if text.strip():
        field.setStyleSheet("")
    else:
        field.setStyleSheet(f"{type_name} {{ border: {_EMPTY_BORDER}; }}")


def _fill(field: QLineEdit, text: str) -> None:
    """Set a line edit's text programmatically and scroll it to the start.

    After ``setText`` the cursor sits at the end, so an overflowing field shows
    the end of the text. Resetting the cursor to position 0 scrolls the view back
    so the beginning is visible. Used only for programmatic fills (capture, grab,
    load), not while the user types."""
    field.setText(text)
    field.setCursorPosition(0)


def _append(field: QLineEdit, text: str) -> None:
    """Append text to a line edit as a comma-separated item.

    An empty field is simply set to the text (no leading comma); a non-empty
    field gains ``", " + text``. Blank input is ignored. Like ``_fill`` this is
    for programmatic capture only, and it scrolls the field back to the start."""
    text = text.strip()
    if not text:
        return
    existing = field.text().strip()
    _fill(field, f"{existing}, {text}" if existing else text)


class SenseRow(QFrame):
    """One editable sense: POS combo, Polish field, English field, a remove button
    and a small list of usage examples beneath them."""

    activated = Signal(object)
    remove_requested = Signal(object)
    edited = Signal()

    POS_OPTIONS = ["n", "v", "adj", "adv", "prep", "conj", "pron", "phrase"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("senseRow")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(2, 2, 2, 2)
        outer.setSpacing(2)

        top = QHBoxLayout()

        self.pos_combo = QComboBox()
        self.pos_combo.setEditable(True)
        self.pos_combo.addItems(self.POS_OPTIONS)
        self.pos_combo.setCurrentText("")
        self.pos_combo.setMaximumWidth(70)

        self.polish_input = QLineEdit()
        self.polish_input.setPlaceholderText("Polish")
        self.polish_input.setToolTip("Alt+P: add the web-view selection here")
        self.english_input = QLineEdit()
        self.english_input.setPlaceholderText("English definition")
        self.english_input.setToolTip("Alt+E: add the web-view selection here")

        # Mark the POS dropdown and the Polish/English fields while empty and keep
        # each marker in sync as it is typed into or filled by capture.
        self.pos_combo.currentTextChanged.connect(
            lambda _=None: _mark_empty(self.pos_combo)
        )
        self.pos_combo.currentTextChanged.connect(lambda _=None: self.edited.emit())
        _mark_empty(self.pos_combo)
        for field in (self.polish_input, self.english_input):
            field.textChanged.connect(lambda _=None, f=field: _mark_empty(f))
            field.textChanged.connect(lambda _=None: self.edited.emit())
            _mark_empty(field)

        self.remove_button = QPushButton("x")
        self.remove_button.setMaximumWidth(28)
        self.remove_button.clicked.connect(lambda: self.remove_requested.emit(self))

        top.addWidget(self.pos_combo)
        top.addWidget(self.polish_input)
        top.addWidget(self.english_input)
        top.addWidget(self.remove_button)
        outer.addLayout(top)

        # Examples: a variable-length list of one-line fields, each with a remove
        # button. Capture appends a new row; "+ example" adds a blank one to type.
        self.examples_container = QVBoxLayout()
        self.examples_container.setContentsMargins(0, 0, 0, 0)
        self.examples_container.setSpacing(2)
        outer.addLayout(self.examples_container)

        self.add_example_button = QPushButton("+ example")
        self.add_example_button.setToolTip(
            "Add a usage example (or use the + buttons on the Cambridge page)"
        )
        self.add_example_button.clicked.connect(
            lambda: self.add_example(focus=True)
        )
        outer.addWidget(self.add_example_button)

        for widget in (self.pos_combo, self.polish_input, self.english_input):
            widget.installEventFilter(self)

        self.set_active(False)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.FocusIn:
            self.activated.emit(self)
        return super().eventFilter(obj, event)

    def set_active(self, active: bool):
        color = "#0a84ff" if active else "transparent"
        self.setStyleSheet(
            f"#senseRow {{ border: 2px solid {color}; border-radius: 4px; }}"
        )

    # --- examples -------------------------------------------------------

    def _example_rows(self) -> list:
        rows = []
        for i in range(self.examples_container.count()):
            widget = self.examples_container.itemAt(i).widget()
            if widget is not None:
                rows.append(widget)
        return rows

    def add_example(self, text: str = "", focus: bool = False) -> None:
        """Append an example field (focusing the active row first). With
        ``focus`` the new field takes keyboard focus, so a manual "+ example"
        click can be typed into straight away."""
        self.activated.emit(self)
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(2)

        field_input = QLineEdit()
        field_input.setPlaceholderText("Example")
        field_input.setToolTip("Alt+X: add the web-view selection as an example")
        field_input.installEventFilter(self)
        _fill(field_input, text)
        # Mark the example field while it is empty (kept in sync as it is typed).
        field_input.textChanged.connect(
            lambda _=None, f=field_input: _mark_empty(f)
        )
        field_input.textChanged.connect(lambda _=None: self.edited.emit())
        _mark_empty(field_input)
        row.example_input = field_input

        remove = QPushButton("x")
        remove.setMaximumWidth(28)
        remove.clicked.connect(lambda: self._remove_example(row))

        row_layout.addWidget(field_input)
        row_layout.addWidget(remove)
        self.examples_container.addWidget(row)

        # Adding an example row is itself an edit. The pre-fill above happens
        # before the textChanged hook is wired, so announce it explicitly here.
        # During a programmatic load the panel routes this through its
        # programmatic guard, so it does not mark the card altered then.
        self.edited.emit()

        if focus:
            field_input.setFocus()

    def add_example_text(self, text: str) -> None:
        """Append an example carrying captured text (skips blank input)."""
        text = text.strip()
        if text:
            self.add_example(text)

    def set_first_example(self, text: str) -> None:
        """Set the first example field's text, creating one if the sense has no
        example row yet. Used by the book-sentence auto-fill, which owns the
        first example while the card is unaltered. Later example rows are left
        untouched."""
        rows = self._example_rows()
        if not rows:
            self.add_example(text)
            return
        rows[0].example_input.setText(text)

    def _remove_example(self, row) -> None:
        self.examples_container.removeWidget(row)
        row.deleteLater()
        self.edited.emit()

    def examples(self) -> list:
        result = []
        for row in self._example_rows():
            text = row.example_input.text().strip()
            if text:
                result.append(text)
        return result

    def to_sense(self) -> Sense:
        return Sense(
            pos=self.pos_combo.currentText().strip(),
            polish=self.polish_input.text().strip(),
            english=self.english_input.text().strip(),
            examples=self.examples(),
        )


class FlashcardPanel(QWidget):
    """Editor that builds one card at a time and saves it to the store.

    A single EditorState answers the two questions the editor keeps asking:
    which mode (new or editing) and has the user altered the card. Every user
    edit routes through _on_user_edit (sets altered); every programmatic fill
    runs inside _programmatic() (never sets altered). Three indicators, the
    Save button label, the read-only Id field and the loaded-row dot, are all
    refreshed by _apply_state_to_ui so they can never disagree."""

    card_saved = Signal(str)
    save_rejected = Signal(str)
    card_loaded = Signal(str)  # headword of a card just loaded into the editor

    _STAR_EMPTY = "Star"
    _STAR_SET = "Starred"

    def __init__(self, store: FlashcardStore, parent=None):
        super().__init__(parent)
        self.store = store
        self.state = EditorState()
        self.active_row = None
        self._audio_uk_url = None
        self._audio_us_url = None
        # True while a programmatic fill runs (load, autofill, capture, reset)
        # so _on_user_edit is a no-op and those fills never set altered.
        self._programmatic_depth = 0
        self.player = None
        self.audio_output = None
        self._staged_links = []
        # Guards for the saved-list checkbox behaviour (unchanged from before).
        self._reticking = False
        self._checkbox_click = False
        self.init_ui()
        self.add_sense()
        self._refresh_saved_list()
        # Sense rows added during init seeded the active row before the state
        # existed; the card is unaltered at startup.
        self.state.to_new()
        self._apply_state_to_ui()

    # --- programmatic-fill guard ----------------------------------------

    @contextmanager
    def _programmatic(self):
        """Run a block of programmatic field writes without marking the card
        altered. Reentrant, so nested guarded fills are safe."""
        self._programmatic_depth += 1
        try:
            yield
        finally:
            self._programmatic_depth -= 1

    def _on_user_edit(self, *_args) -> None:
        """A genuine user edit. No-op during a programmatic fill."""
        if self._programmatic_depth == 0:
            self.state.mark_altered()

    def init_ui(self):
        outer = QVBoxLayout(self)

        editor_widget = QWidget()
        layout = QVBoxLayout(editor_widget)
        layout.setContentsMargins(0, 0, 0, 0)

        form = QFormLayout()

        # Read-only Id field: empty in new mode, shows the loaded card's id when
        # editing. Disabled and read-only, a pure indicator; it is never wired
        # to _on_user_edit.
        self.id_input = QLineEdit()
        self.id_input.setReadOnly(True)
        self.id_input.setEnabled(False)
        self.id_input.setPlaceholderText("new card")
        form.addRow("Id", self.id_input)

        headword_row = QHBoxLayout()
        self.headword_input = QLineEdit()
        self.headword_input.setToolTip(
            "Ctrl+N: fill from the search box (New from word)"
        )
        self.star_button = QPushButton(self._STAR_EMPTY)
        self.star_button.setCheckable(True)
        self.star_button.setMaximumWidth(70)
        self.star_button.setToolTip("Star this card (mark as important)")
        self.star_button.toggled.connect(self._on_star_toggled)
        headword_row.addWidget(self.headword_input)
        headword_row.addWidget(self.star_button)
        form.addRow("Headword", headword_row)

        spelling_row = QHBoxLayout()
        self.spelling_uk_input = QLineEdit()
        self.spelling_uk_input.setPlaceholderText("UK spelling")
        self.spelling_uk_input.setToolTip(
            "New from word: filled from the Cambridge page (when it differs UK/US)"
        )
        self.spelling_us_input = QLineEdit()
        self.spelling_us_input.setPlaceholderText("US spelling")
        self.spelling_us_input.setToolTip(
            "New from word: filled from the Cambridge page (when it differs UK/US)"
        )
        spelling_row.addWidget(self.spelling_uk_input)
        spelling_row.addWidget(self.spelling_us_input)
        form.addRow("Spelling", spelling_row)

        speaker_icon = self.style().standardIcon(
            QStyle.StandardPixmap.SP_MediaVolume
        )

        ipa_row = QHBoxLayout()
        self.ipa_uk_input = QLineEdit()
        self.ipa_uk_input.setPlaceholderText("IPA UK")
        self.ipa_uk_input.setToolTip("New from word: filled from the Cambridge page")
        self.play_uk_button = QPushButton()
        self.play_uk_button.setIcon(speaker_icon)
        self.play_uk_button.setMaximumWidth(32)
        self.play_uk_button.setToolTip("Play UK pronunciation")
        self.play_uk_button.clicked.connect(lambda: self.play_audio("uk"))

        self.ipa_us_input = QLineEdit()
        self.ipa_us_input.setPlaceholderText("IPA US")
        self.ipa_us_input.setToolTip("New from word: filled from the Cambridge page")
        self.play_us_button = QPushButton()
        self.play_us_button.setIcon(speaker_icon)
        self.play_us_button.setMaximumWidth(32)
        self.play_us_button.setToolTip("Play US pronunciation")
        self.play_us_button.clicked.connect(lambda: self.play_audio("us"))

        ipa_row.addWidget(self.ipa_uk_input)
        ipa_row.addWidget(self.play_uk_button)
        ipa_row.addWidget(self.ipa_us_input)
        ipa_row.addWidget(self.play_us_button)
        form.addRow("IPA", ipa_row)

        self.own_notation_input = QLineEdit()
        form.addRow("Own notation", self.own_notation_input)

        # Mark every fillable card field while empty; keep the marker in sync and
        # route genuine user typing into _on_user_edit.
        for field in (
            self.headword_input,
            self.spelling_uk_input,
            self.spelling_us_input,
            self.ipa_uk_input,
            self.ipa_us_input,
            self.own_notation_input,
        ):
            field.textChanged.connect(lambda _=None, f=field: _mark_empty(f))
            field.textChanged.connect(self._on_user_edit)
            _mark_empty(field)

        layout.addLayout(form)

        layout.addWidget(QLabel("Senses"))
        self.senses_container = QVBoxLayout()
        senses_widget = QWidget()
        senses_widget.setLayout(self.senses_container)
        layout.addWidget(senses_widget)

        self.add_sense_button = QPushButton("+ Add sense")
        self.add_sense_button.clicked.connect(self.add_sense)
        layout.addWidget(self.add_sense_button)

        buttons = QHBoxLayout()
        self.new_button = QPushButton("New from word")
        self.new_button.setToolTip(
            "Ctrl+N: start a card and fill headword, IPA, spelling and audio "
            "from the Cambridge page. Ctrl+click skips the discard confirmation."
        )
        self.clear_button = QPushButton("Clear")
        self.clear_button.setToolTip(
            "Empty the editor. Ctrl+click skips the discard confirmation."
        )
        self.clear_button.clicked.connect(self.clear_editor)
        # The Save button label switches with the mode: "Add card" when new,
        # "Save changes" when editing (set in _apply_state_to_ui).
        self.save_button = QPushButton("Add card")
        self.save_button.clicked.connect(self.save_card)
        buttons.addWidget(self.new_button)
        buttons.addWidget(self.clear_button)
        buttons.addWidget(self.save_button)
        layout.addLayout(buttons)
        layout.addStretch()

        self.editor_scroll = QScrollArea()
        self.editor_scroll.setWidgetResizable(True)
        self.editor_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.editor_scroll.setWidget(editor_widget)

        saved_widget = QWidget()
        saved_layout = QVBoxLayout(saved_widget)
        saved_layout.setContentsMargins(0, 0, 0, 0)
        saved_layout.addWidget(QLabel("Saved cards"))
        self.saved_filter = QLineEdit()
        self.saved_filter.setPlaceholderText("Filter saved cards")
        self.saved_filter.setClearButtonEnabled(True)
        self.saved_filter.textChanged.connect(self._apply_saved_filter)
        saved_layout.addWidget(self.saved_filter)
        self.saved_list = QListWidget()
        self.saved_list.setToolTip(
            "Click a card's text to load it; tick its box to link it in the chosen category"
        )
        self.saved_list.itemClicked.connect(self._on_saved_clicked)
        self.saved_list.itemChanged.connect(self._on_item_changed)
        saved_layout.addWidget(self.saved_list, stretch=1)

        link_controls = QHBoxLayout()
        link_controls.addWidget(QLabel("Link as"))
        self.link_category_combo = QComboBox()
        for key, label, _colour in LINK_TYPES:
            self.link_category_combo.addItem(label, key)
        self.link_category_combo.setToolTip(
            "Choose a relationship; the rows below tick to show the edited card's "
            "links of this kind. Tick or untick a card to link or unlink it."
        )
        self.link_category_combo.currentIndexChanged.connect(
            lambda _=None: self._retick_saved_list()
        )
        link_controls.addWidget(self.link_category_combo)
        link_controls.addStretch()
        saved_layout.addLayout(link_controls)

        self.editor_splitter = QSplitter(Qt.Orientation.Vertical)
        self.editor_splitter.addWidget(self.editor_scroll)
        self.editor_splitter.addWidget(saved_widget)
        self.editor_splitter.setChildrenCollapsible(False)
        self.editor_splitter.setStretchFactor(0, 0)
        self.editor_splitter.setStretchFactor(1, 1)
        self.editor_splitter.setSizes([480, 160])
        outer.addWidget(self.editor_splitter)

        self._update_play_buttons()

    # --- state -> UI ----------------------------------------------------

    def _apply_state_to_ui(self) -> None:
        """Refresh the three mode indicators from the state in one place: the
        Save button label and the read-only Id field. (The loaded-row dot is set
        in _refresh_saved_list, which reads the same state.)"""
        if self.state.is_editing:
            self.save_button.setText("Save changes")
            self.id_input.setText(self.state.loaded_card_id or "")
        else:
            self.save_button.setText("Add card")
            self.id_input.setText("")

    # --- sense rows -----------------------------------------------------

    def _rows(self) -> list:
        rows = []
        for i in range(self.senses_container.count()):
            widget = self.senses_container.itemAt(i).widget()
            if isinstance(widget, SenseRow):
                rows.append(widget)
        return rows

    def add_sense(self):
        row = SenseRow()
        row.activated.connect(self.set_active_row)
        row.remove_requested.connect(self.remove_sense)
        row.edited.connect(self._on_user_edit)
        self.senses_container.addWidget(row)
        self.set_active_row(row)

    def set_active_row(self, row):
        self.active_row = row
        for candidate in self._rows():
            candidate.set_active(candidate is row)

    def set_active_index(self, index: int):
        rows = self._rows()
        if 1 <= index <= len(rows):
            self.set_active_row(rows[index - 1])

    def remove_sense(self, row):
        self._on_user_edit()
        rows = self._rows()
        if len(rows) <= 1:
            row.pos_combo.setCurrentText("")
            row.polish_input.clear()
            row.english_input.clear()
            return
        self.senses_container.removeWidget(row)
        row.deleteLater()
        if self.active_row is row:
            self.set_active_row(self._rows()[0])

    def _ensure_active_row(self):
        rows = self._rows()
        if self.active_row in rows:
            return self.active_row
        if rows:
            self.set_active_row(rows[-1])
            return self.active_row
        self.add_sense()
        return self.active_row

    # --- capture --------------------------------------------------------

    def set_polish_selection(self, text: str):
        text = text.strip()
        if not text:
            return
        _fill(self._ensure_active_row().polish_input, text)

    def set_english_selection(self, text: str):
        text = text.strip()
        if not text:
            return
        _fill(self._ensure_active_row().english_input, text)

    def append_polish_selection(self, text: str):
        _append(self._ensure_active_row().polish_input, text)

    def append_english_selection(self, text: str):
        _append(self._ensure_active_row().english_input, text)

    def add_example_selection(self, text: str):
        text = text.strip()
        if not text:
            return
        self._ensure_active_row().add_example_text(text)

    def autofill_book_example(self, sentence: str) -> None:
        """Passive auto-fill of the book match sentence into the first sense's
        first example. Same rule as autofill_pronunciation: only while the card
        is unaltered, and written through the programmatic guard so the fill
        itself never marks the card altered (which lets a later book match
        refill again). A blank sentence is ignored."""
        sentence = (sentence or "").strip()
        if not sentence:
            return
        if self.state.altered:
            return
        with self._programmatic():
            self._rows()[0].set_first_example(sentence)

    # --- pronunciation / auto-grab --------------------------------------

    def autofill_pronunciation(
        self,
        ipa_uk,
        ipa_us,
        audio_uk_url,
        audio_us_url,
        spelling_uk=None,
        spelling_us=None,
        word=None,
    ):
        """Passive auto-grab from a Cambridge page load. Refill the headword,
        IPA, spelling and audio only while the card is unaltered; once the user
        has altered it, do nothing silently (no dialog, no overwrite). The
        refill runs programmatically so it never marks the card altered, which
        lets a later page load refill again."""
        if self.state.altered:
            return
        # Write every grab field (even to empty) so a re-fill clears values the
        # previous word had but the new one lacks.
        with self._programmatic():
            _fill(self.headword_input, word or "")
            _fill(self.ipa_uk_input, ipa_uk or "")
            _fill(self.ipa_us_input, ipa_us or "")
            _fill(self.spelling_uk_input, spelling_uk or "")
            _fill(self.spelling_us_input, spelling_us or "")
            self._audio_uk_url = audio_uk_url or None
            self._audio_us_url = audio_us_url or None
        self._update_play_buttons()

    def _update_play_buttons(self):
        self.play_uk_button.setEnabled(bool(self._audio_uk_url))
        self.play_us_button.setEnabled(bool(self._audio_us_url))

    def set_audio(self, region: str, url: str, ipa: str | None = None) -> None:
        """Replace one region's pronunciation audio (and its IPA) with a clip
        captured from the Cambridge page. A deliberate single-field edit, so it
        marks the card altered; that is what makes a later passive grab leave
        the edited card alone."""
        if region == "uk":
            with self._programmatic():
                self._audio_uk_url = url or None
                if ipa:
                    self.ipa_uk_input.setText(ipa)
        elif region == "us":
            with self._programmatic():
                self._audio_us_url = url or None
                if ipa:
                    self.ipa_us_input.setText(ipa)
        else:
            return
        self.state.mark_altered()
        self._update_play_buttons()

    # --- star -----------------------------------------------------------

    def _on_star_toggled(self, checked: bool):
        self._on_user_edit()
        self.star_button.setText(self._STAR_SET if checked else self._STAR_EMPTY)
        self.star_button.setStyleSheet(
            "background-color: #f0b400; color: #000; font-weight: bold;"
            if checked
            else ""
        )

    def set_starred(self, starred: bool):
        self.star_button.setChecked(bool(starred))

    def is_starred(self) -> bool:
        return self.star_button.isChecked()

    def play_audio(self, which: str):
        url = self._audio_uk_url if which == "uk" else self._audio_us_url
        if not url:
            return
        if self.player is None:
            self.player = QMediaPlayer(self)
            self.audio_output = QAudioOutput(self)
            self.player.setAudioOutput(self.audio_output)
        self.player.stop()
        self.player.setSource(QUrl())
        self.player.setSource(QUrl(url))
        self.player.play()

    # --- card lifecycle -------------------------------------------------

    def has_content(self) -> bool:
        text_inputs = (
            self.headword_input,
            self.spelling_uk_input,
            self.spelling_us_input,
            self.ipa_uk_input,
            self.ipa_us_input,
            self.own_notation_input,
        )
        if any(widget.text().strip() for widget in text_inputs):
            return True
        if self._audio_uk_url or self._audio_us_url:
            return True
        return any(not row.to_sense().is_empty for row in self._rows())

    def build_card(self):
        headword = self.headword_input.text().strip()
        if not headword:
            return None
        senses = [row.to_sense() for row in self._rows()]
        senses = [sense for sense in senses if not sense.is_empty]
        now = datetime.now().isoformat(timespec="seconds")
        card = Card(
            headword=headword,
            spelling_uk=self.spelling_uk_input.text().strip() or None,
            spelling_us=self.spelling_us_input.text().strip() or None,
            ipa_uk=self.ipa_uk_input.text().strip() or None,
            ipa_us=self.ipa_us_input.text().strip() or None,
            own_notation=self.own_notation_input.text().strip() or None,
            audio_uk_url=self._audio_uk_url,
            audio_us_url=self._audio_us_url,
            senses=senses,
            starred=self.is_starred(),
            created_at=self.state.loaded_created_at or now,
            updated_at=now,
        )
        if self.state.loaded_card_id:
            card.id = self.state.loaded_card_id
        return card

    def save_card(self):
        card = self.build_card()
        if card is None:
            self.save_rejected.emit("Cannot save flashcard: headword is empty")
            return
        rebased = [
            Link(card.id, self._partner_id(link), link.type)
            for link in self._staged_links
        ]
        self.store.save_card_with_links(card, rebased)
        headword = card.headword
        # Save keeps the card loaded rather than clearing the editor: the just
        # saved card becomes the loaded card in unaltered editing mode, so its
        # fields stay put and a brand-new card turns into an existing one without
        # any wipe. Re-seed the staged links from the store (mirroring load_card)
        # so they are keyed by the card's real id, and refresh the list so the
        # dot lands on this card's row.
        self.state.to_editing(card.id, card.created_at or None)
        self._staged_links = list(self.store.links_for(card.id))
        self._apply_state_to_ui()
        self._refresh_saved_list()
        self.card_saved.emit(headword)

    @staticmethod
    def ctrl_held() -> bool:
        return bool(
            QApplication.keyboardModifiers() & Qt.KeyboardModifier.ControlModifier
        )

    def has_focus(self) -> bool:
        focused = QApplication.focusWidget()
        return focused is not None and (
            focused is self or self.isAncestorOf(focused)
        )

    def focus_editor(self) -> None:
        self.headword_input.setFocus()

    def new_card(self, force: bool = False) -> bool:
        """Clear the editor for a fresh card. Returns False if the user declined
        to discard unsaved content. force skips the confirmation. The headword is
        not seeded here: the caller re-grabs the Cambridge page, which fills it
        (see main_window.new_flashcard / on_pronunciation_grabbed)."""
        if not force and self.state.altered and not self._confirm_discard():
            return False
        self._reset_editor()
        return True

    def prepare_for_new_search(self) -> None:
        """Clear the editor before a new dictionary search auto-fills it, so the
        new word replaces the previous card completely (senses, examples, star,
        own notation, staged links, loaded-card id), not just the grab fields.

        Only when the card is unaltered: a freshly saved card, a card loaded for
        viewing, one holding only a previous passive auto-fill, or an empty card
        are all reset to a fresh unsaved new card. An altered card is left
        completely untouched, with no discard prompt (a search is passive, so it
        never nags); that is why this calls _reset_editor directly rather than
        new_card/clear_editor, which would prompt.

        Called once per search from main_window.on_word_searched, synchronously
        before the pronunciation grab and the book-sentence fill. Because it runs
        up front and NOT inside the repeating page-load handlers, the book
        example filled afterwards survives later same-search Cambridge reloads.
        """
        if self.state.altered:
            return
        self._reset_editor()

    def clear_editor(self):
        if (
            not self.ctrl_held()
            and self.state.altered
            and not self._confirm_discard()
        ):
            return
        self._reset_editor()

    def _reset_editor(self):
        with self._programmatic():
            for widget in (
                self.headword_input,
                self.spelling_uk_input,
                self.spelling_us_input,
                self.ipa_uk_input,
                self.ipa_us_input,
                self.own_notation_input,
            ):
                widget.clear()
            self._audio_uk_url = None
            self._audio_us_url = None
            self._update_play_buttons()
            self.star_button.setChecked(False)
            for row in self._rows():
                self.senses_container.removeWidget(row)
                row.deleteLater()
            self.active_row = None
            self.add_sense()
            self._staged_links = []
            self.saved_list.clearSelection()
        # Back to a fresh, unaltered card.
        self.state.to_new()
        self._apply_state_to_ui()
        self._refresh_saved_list()
        self._scroll_editor_to_top()

    def _scroll_editor_to_top(self) -> None:
        scroll = getattr(self, "editor_scroll", None)
        if scroll is not None:
            scroll.verticalScrollBar().setValue(0)

    # --- saved cards list -----------------------------------------------

    def _loaded_marker_icon(self) -> QIcon:
        cached = getattr(self, "_loaded_icon", None)
        if cached is not None:
            return cached
        width = self.style().pixelMetric(
            QStyle.PixelMetric.PM_IndicatorWidth
        ) or 16
        bold = self.saved_list.font()
        bold.setBold(True)
        row_height = QFontMetrics(bold).height() + 4
        pixmap = QPixmap(width, row_height)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QBrush(QColor("#0a84ff")))
        painter.setPen(Qt.PenStyle.NoPen)
        diameter = max(4, int(width * 0.5))
        x = (width - diameter) / 2.0
        y = (row_height - diameter) / 2.0
        painter.drawEllipse(int(x), int(y), diameter, diameter)
        painter.end()
        self._loaded_icon = QIcon(pixmap)
        return self._loaded_icon

    def _refresh_saved_list(self):
        self._reticking = True
        try:
            self.saved_list.clear()
            for card in self.store.cards:
                label = card.headword
                if card.starred:
                    label = f"{self._STAR_SET}: {label}"
                item = QListWidgetItem(label)
                item.setData(Qt.ItemDataRole.UserRole, card.id)
                if card.id == self.state.loaded_card_id:
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
                    item.setIcon(self._loaded_marker_icon())
                    font = item.font()
                    font.setBold(True)
                    item.setFont(font)
                    item.setBackground(QBrush(QColor("#e8f0fe")))
                else:
                    item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                    item.setCheckState(Qt.CheckState.Unchecked)
                self.saved_list.addItem(item)
            self._apply_saved_filter()
        finally:
            self._reticking = False
        self._retick_saved_list()

    def _apply_saved_filter(self, text: str = "") -> None:
        needle = self.saved_filter.text().strip().lower()
        for i in range(self.saved_list.count()):
            item = self.saved_list.item(i)
            item.setHidden(bool(needle) and needle not in item.text().lower())

    def _on_saved_clicked(self, item):
        if self._checkbox_click:
            self._checkbox_click = False
            return
        card_id = item.data(Qt.ItemDataRole.UserRole)
        card = next((c for c in self.store.cards if c.id == card_id), None)
        if card is not None:
            self.load_card(card)

    def load_card(self, card: Card) -> bool:
        """Load a saved card for review or editing. Asks to discard unsaved
        content first (unless Ctrl is held). A later Save updates this card in
        place. Returns False if the user declined to discard."""
        if (
            not self.ctrl_held()
            and self.state.altered
            and not self._confirm_discard()
        ):
            return False
        self._reset_editor()  # clears fields; sets state.to_new()
        with self._programmatic():
            _fill(self.headword_input, card.headword)
            _fill(self.spelling_uk_input, card.spelling_uk or "")
            _fill(self.spelling_us_input, card.spelling_us or "")
            _fill(self.ipa_uk_input, card.ipa_uk or "")
            _fill(self.ipa_us_input, card.ipa_us or "")
            _fill(self.own_notation_input, card.own_notation or "")
            self._audio_uk_url = card.audio_uk_url
            self._audio_us_url = card.audio_us_url
            self._update_play_buttons()
            self.set_starred(card.starred)

            for row in self._rows():
                self.senses_container.removeWidget(row)
                row.deleteLater()
            self.active_row = None
            if card.senses:
                for sense in card.senses:
                    self.add_sense()
                    row = self.active_row
                    row.pos_combo.setCurrentText(sense.pos)
                    _fill(row.polish_input, sense.polish)
                    _fill(row.english_input, sense.english)
                    for example in sense.examples:
                        row.add_example(example)
                self.set_active_index(1)
            else:
                self.add_sense()

            self._staged_links = list(self.store.links_for(card.id))
        # Enter editing mode: a clean baseline, so altered stays False.
        self.state.to_editing(card.id, card.created_at or None)
        self._apply_state_to_ui()
        self._refresh_saved_list()
        # Announce the load so the main window can look the headword up in the
        # dictionary (without touching history); a no-op if nothing listens.
        self.card_loaded.emit(card.headword)
        return True

    def _confirm_discard(self) -> bool:
        reply = QMessageBox.question(
            self,
            "Unsaved changes",
            "You have unsaved changes. Discard them?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        return reply == QMessageBox.StandardButton.Yes

    # --- links ----------------------------------------------------------

    def _current_category(self) -> str:
        return self.link_category_combo.currentData()

    def _retick_saved_list(self) -> None:
        category = self._current_category()
        linked_partners = {
            self._partner_id(l) for l in self._staged_links if l.type == category
        }
        self._reticking = True
        try:
            for i in range(self.saved_list.count()):
                item = self.saved_list.item(i)
                if not (item.flags() & Qt.ItemFlag.ItemIsUserCheckable):
                    continue
                partner = item.data(Qt.ItemDataRole.UserRole)
                state = (
                    Qt.CheckState.Checked
                    if partner in linked_partners
                    else Qt.CheckState.Unchecked
                )
                item.setCheckState(state)
        finally:
            self._reticking = False

    def _on_item_changed(self, item) -> None:
        if self._reticking:
            return
        self._checkbox_click = True
        partner = item.data(Qt.ItemDataRole.UserRole)
        category = self._current_category()
        checked = item.checkState() == Qt.CheckState.Checked
        self._staged_links = [
            l for l in self._staged_links
            if not (self._partner_id(l) == partner and l.type == category)
        ]
        if checked:
            self._staged_links.append(Link(self._edit_anchor(), partner, category))
        self._on_user_edit()

    def _edit_anchor(self) -> str:
        return self.state.loaded_card_id or _NEW_CARD_ANCHOR

    def _partner_id(self, link: Link) -> str:
        anchor = self._edit_anchor()
        return link.b_id if link.a_id == anchor else link.a_id
