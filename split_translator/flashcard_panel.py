"""Flashcard editor: a dock-panel widget for building one card at a time."""

from datetime import datetime

from PySide6.QtCore import QEvent, Qt, QUrl, Signal
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

from .flashcards import Card, FlashcardStore, Sense

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
        # During a programmatic load the panel suppresses the dirty flag, so this
        # is harmless then.
        self.edited.emit()

        if focus:
            field_input.setFocus()

    def add_example_text(self, text: str) -> None:
        """Append an example carrying captured text (skips blank input)."""
        text = text.strip()
        if text:
            self.add_example(text)

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
    """Editor that builds one card at a time and saves it to the store."""

    card_saved = Signal(str)
    save_rejected = Signal(str)
    sense_count_changed = Signal(int)

    # Star toggle labels. Plain text (no glyph) to keep to standard characters.
    _STAR_EMPTY = "Star"
    _STAR_SET = "Starred"

    def __init__(self, store: FlashcardStore, parent=None):
        super().__init__(parent)
        self.store = store
        self.active_row = None
        self._audio_uk_url = None
        self._audio_us_url = None
        # When a saved card is loaded for editing, its id and original creation
        # time are remembered so that Save updates it in place instead of adding
        # a duplicate. Cleared whenever the editor is reset to a blank card.
        self._loaded_card_id = None
        self._loaded_created_at = None
        # Tracks whether the editor has unsaved user edits since it was last
        # loaded, cleared or saved. Programmatic fills (load, reset, capture)
        # run with `_suppress_dirty` set so they do not mark the card dirty;
        # only genuine user edits flip the flag. The discard confirmation is
        # gated on this, so viewing a freshly loaded card and clicking another
        # never prompts.
        self._dirty = False
        self._suppress_dirty = False
        # Snapshot of the grab fields exactly as the last autofill left them
        # (the six text fields plus the two audio URLs). A later search re-fills
        # the card only while the fields still match this; the moment the user
        # edits any grab field the card no longer matches and is left alone.
        # None means no autofill has run on the current (empty) editor yet.
        self._last_autofill = None
        self.player = None
        self.audio_output = None
        self.init_ui()
        self.add_sense()
        self._refresh_saved_list()
        # Sense rows added during init_ui/add_sense seeded the active row before
        # the flag existed; the card is clean at startup.
        self._dirty = False

    def init_ui(self):
        outer = QVBoxLayout(self)

        # The editor (card fields, senses and the action buttons) lives in its
        # own widget so it can be put inside a scroll area: a card taller than
        # the editor area scrolls instead of pushing the saved-cards list down.
        # A vertical splitter below makes the boundary between the editor and the
        # list user-draggable, so the editor height can be set once and stays put
        # (no UI shift when a taller or shorter card is loaded). `layout` is the
        # editor's own layout; every editor row below adds to it.
        editor_widget = QWidget()
        layout = QVBoxLayout(editor_widget)
        layout.setContentsMargins(0, 0, 0, 0)

        form = QFormLayout()

        headword_row = QHBoxLayout()
        self.headword_input = QLineEdit()
        self.headword_input.setToolTip(
            "Ctrl+N: fill from the search box (New from word)"
        )
        # Star toggle: marks a card as important to focus on. Persisted with the
        # card and reset with the editor.
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

        # IPA row: each IPA field is followed by a compact speaker button that
        # plays that region's Cambridge pronunciation. A built-in style icon is
        # used (no theme dependency and no non-standard glyph in code).
        speaker_icon = self.style().standardIcon(
            QStyle.StandardPixmap.SP_MediaVolume
        )

        ipa_row = QHBoxLayout()
        self.ipa_uk_input = QLineEdit()
        self.ipa_uk_input.setPlaceholderText("IPA UK")
        self.ipa_uk_input.setToolTip(
            "New from word: filled from the Cambridge page"
        )
        self.play_uk_button = QPushButton()
        self.play_uk_button.setIcon(speaker_icon)
        self.play_uk_button.setMaximumWidth(32)
        self.play_uk_button.setToolTip("Play UK pronunciation")
        self.play_uk_button.clicked.connect(lambda: self.play_audio("uk"))

        self.ipa_us_input = QLineEdit()
        self.ipa_us_input.setPlaceholderText("IPA US")
        self.ipa_us_input.setToolTip(
            "New from word: filled from the Cambridge page"
        )
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

        # Mark every fillable card field while empty and keep each marker in sync
        # as it is typed into or filled by a grab.
        for field in (
            self.headword_input,
            self.spelling_uk_input,
            self.spelling_us_input,
            self.ipa_uk_input,
            self.ipa_us_input,
            self.own_notation_input,
        ):
            field.textChanged.connect(lambda _=None, f=field: _mark_empty(f))
            field.textChanged.connect(self._mark_dirty)
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
        self.save_button = QPushButton("Save")
        self.save_button.clicked.connect(self.save_card)
        buttons.addWidget(self.new_button)
        buttons.addWidget(self.clear_button)
        buttons.addWidget(self.save_button)
        layout.addLayout(buttons)
        # A stretch keeps the editor rows packed at the top of the scroll area so
        # a short card does not leave the fields floating in the middle.
        layout.addStretch()

        # The editor scrolls when its content is taller than the area it is given;
        # when shorter, the editor widget fills the area (widgetResizable).
        self.editor_scroll = QScrollArea()
        self.editor_scroll.setWidgetResizable(True)
        self.editor_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.editor_scroll.setWidget(editor_widget)

        # Saved cards: a list of every stored card (newest first). Clicking a row
        # loads that card into the editor so it can be reviewed or edited.
        saved_widget = QWidget()
        saved_layout = QVBoxLayout(saved_widget)
        saved_layout.setContentsMargins(0, 0, 0, 0)
        saved_layout.addWidget(QLabel("Saved cards"))
        self.saved_list = QListWidget()
        self.saved_list.setToolTip("Click a saved card to load it for editing")
        self.saved_list.itemClicked.connect(self._on_saved_clicked)
        saved_layout.addWidget(self.saved_list, stretch=1)

        # The splitter handle is the draggable boundary that sets the editor
        # height. Stretch factor 0 on the editor and 1 on the list means that
        # when the whole panel is resized, the editor keeps its set height and
        # the saved-cards list absorbs all the extra (or lost) space. Neither
        # pane collapses to zero. setSizes seeds the initial split.
        self.editor_splitter = QSplitter(Qt.Orientation.Vertical)
        self.editor_splitter.addWidget(self.editor_scroll)
        self.editor_splitter.addWidget(saved_widget)
        self.editor_splitter.setChildrenCollapsible(False)
        self.editor_splitter.setStretchFactor(0, 0)
        self.editor_splitter.setStretchFactor(1, 1)
        self.editor_splitter.setSizes([480, 160])
        outer.addWidget(self.editor_splitter)

        self._update_play_buttons()

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
        row.edited.connect(self._mark_dirty)
        self.senses_container.addWidget(row)
        self.set_active_row(row)
        self.sense_count_changed.emit(len(self._rows()))

    def set_active_row(self, row):
        self.active_row = row
        for candidate in self._rows():
            candidate.set_active(candidate is row)

    def set_active_index(self, index: int):
        """Make the 1-based sense index active (no-op if out of range)."""
        rows = self._rows()
        if 1 <= index <= len(rows):
            self.set_active_row(rows[index - 1])

    def remove_sense(self, row):
        self._mark_dirty()
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
        self.sense_count_changed.emit(len(self._rows()))

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

    def add_example_selection(self, text: str):
        text = text.strip()
        if not text:
            return
        self._ensure_active_row().add_example_text(text)

    # --- pronunciation --------------------------------------------------

    def _grab_fields_empty(self) -> bool:
        """True when every field an automatic grab fills is still empty."""
        for widget in (
            self.headword_input,
            self.ipa_uk_input,
            self.ipa_us_input,
            self.spelling_uk_input,
            self.spelling_us_input,
        ):
            if widget.text().strip():
                return False
        return not (self._audio_uk_url or self._audio_us_url)

    def _grab_fields_snapshot(self) -> tuple:
        """Current value of every grab field, in the order the snapshot stores
        them. Compared against ``_last_autofill`` to tell an untouched autofill
        from one the user has edited."""
        return (
            self.headword_input.text(),
            self.ipa_uk_input.text(),
            self.ipa_us_input.text(),
            self.spelling_uk_input.text(),
            self.spelling_us_input.text(),
            self._audio_uk_url,
            self._audio_us_url,
        )

    def _grab_fields_unchanged_by_user(self) -> bool:
        """True when the grab fields may be overwritten by a fresh autofill:
        either every field is still empty (no autofill yet, or a cleared card),
        or they all still hold exactly what the last autofill wrote. Returns
        False once the user has edited any grab field."""
        if self._grab_fields_empty():
            return True
        return (
            self._last_autofill is not None
            and self._grab_fields_snapshot() == self._last_autofill
        )

    def set_pronunciation(
        self,
        ipa_uk,
        ipa_us,
        audio_uk_url,
        audio_us_url,
        spelling_uk=None,
        spelling_us=None,
        word=None,
    ):
        # All-or-nothing as a group: fill the headword, IPA, spelling and audio
        # only while every one of those fields is either still empty or still
        # holds exactly what the previous autofill wrote. The moment the user
        # edits any grab field the card no longer matches and a later search
        # leaves it untouched, so in-progress work is never clobbered. While the
        # fields are still the untouched autofill, a new search replaces them
        # with the new word's data.
        if not self._grab_fields_unchanged_by_user():
            return
        # Write every grab field (even to empty) so a re-fill clears values the
        # previous word had but the new one lacks; otherwise the snapshot would
        # not match on the next search. These are programmatic fills, so suppress
        # the dirty flag here and restore the "capture is intent" mark below.
        self._suppress_dirty = True
        try:
            _fill(self.headword_input, word or "")
            _fill(self.ipa_uk_input, ipa_uk or "")
            _fill(self.ipa_us_input, ipa_us or "")
            _fill(self.spelling_uk_input, spelling_uk or "")
            _fill(self.spelling_us_input, spelling_us or "")
            self._audio_uk_url = audio_uk_url or None
            self._audio_us_url = audio_us_url or None
        finally:
            self._suppress_dirty = False
        # Remember exactly what this autofill left so the next search can tell an
        # untouched autofill from one the user has since edited.
        self._last_autofill = self._grab_fields_snapshot()
        self._update_play_buttons()
        # Audio URLs are set by direct assignment (no textChanged signal), so a
        # grab that captures only audio would not otherwise mark the card dirty.
        # Capturing pronunciation is intent to build a card, so flag it here.
        if audio_uk_url or audio_us_url:
            self._mark_dirty()

    def _update_play_buttons(self):
        self.play_uk_button.setEnabled(bool(self._audio_uk_url))
        self.play_us_button.setEnabled(bool(self._audio_us_url))

    def set_audio(self, region: str, url: str) -> None:
        """Replace one region's pronunciation audio with a clip captured from the
        Cambridge page. Sets just that region's URL (UK or US) and leaves the
        IPA, headword, spelling and the other region untouched.

        Unlike set_pronunciation this is a deliberate single-field edit, not an
        autofill, so it marks the card dirty and does NOT update the autofill
        snapshot. Leaving the snapshot stale is the point: the audio URLs are
        part of it, so a changed URL makes the card count as user-edited. That is
        what makes tapping another card and New-from-word prompt to discard, and
        a later passive grab leave the edited card alone."""
        if region == "uk":
            self._audio_uk_url = url or None
        elif region == "us":
            self._audio_us_url = url or None
        else:
            return
        # A genuine edit: mark dirty directly so the discard guards fire (do not
        # route through _mark_dirty, which a suppress flag could swallow).
        self._dirty = True
        self._update_play_buttons()

    # --- star -----------------------------------------------------------

    def _on_star_toggled(self, checked: bool):
        self._mark_dirty()
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
        # Clicking the same play button twice would otherwise do nothing: setting
        # the source to the URL the player already holds is a no-op, so after the
        # clip has finished it never replays. Stop and clear the source first so
        # every click reloads and plays from the start, even for the same URL.
        self.player.stop()
        self.player.setSource(QUrl())
        self.player.setSource(QUrl(url))
        self.player.play()

    # --- card lifecycle -------------------------------------------------

    def _mark_dirty(self) -> None:
        """Record a genuine user edit. No-op while `_suppress_dirty` is set, so
        programmatic fills (load, reset, capture) never mark the card dirty."""
        if not self._suppress_dirty:
            self._dirty = True

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
        # Editing a loaded card keeps its id and original creation time so Save
        # updates that card in place; a fresh card gets a new id and timestamps.
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
            created_at=self._loaded_created_at or now,
            updated_at=now,
        )
        if self._loaded_card_id:
            card.id = self._loaded_card_id
        return card

    def save_card(self):
        card = self.build_card()
        if card is None:
            self.save_rejected.emit("Cannot save flashcard: headword is empty")
            return
        # Update the loaded card in place when editing; otherwise add a new one.
        # If the loaded card has since gone, fall back to adding it.
        if self._loaded_card_id and self.store.update_card(card):
            pass
        else:
            self.store.add_card(card)
        headword = card.headword
        self._reset_editor()
        self._refresh_saved_list()
        self.card_saved.emit(headword)

    @staticmethod
    def ctrl_held() -> bool:
        """True when Ctrl is down (used to skip the discard confirmation on a
        Ctrl+click of New from word / Clear)."""
        return bool(
            QApplication.keyboardModifiers() & Qt.KeyboardModifier.ControlModifier
        )

    def has_focus(self) -> bool:
        """True when keyboard focus is on this panel or one of its descendants.
        Used by the main window to route Alt+1 / Alt+2 to the card pronunciations
        when the editor is in use rather than to the dictionary audio."""
        focused = QApplication.focusWidget()
        return focused is not None and (
            focused is self or self.isAncestorOf(focused)
        )

    def new_card(self, word: str, force: bool = False) -> bool:
        """Clear the editor for a fresh card. Returns False if the user declined
        to discard unsaved content. ``force`` skips the confirmation. The headword
        and pronunciation are filled by the grab (see ``set_pronunciation``), not
        here, so the all-or-nothing gate sees a fully empty editor."""
        if not force and self._dirty and not self._confirm_discard():
            return False
        self._reset_editor()
        return True

    def clear_editor(self):
        # Ctrl+click skips the discard confirmation.
        if (
            not self.ctrl_held()
            and self._dirty
            and not self._confirm_discard()
        ):
            return
        self._reset_editor()

    def _reset_editor(self):
        # Clearing fields fires textChanged/toggled which would otherwise mark
        # the card dirty; suppress that so a reset leaves a clean editor.
        self._suppress_dirty = True
        try:
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
            # Back to building a fresh card: forget any loaded card and drop the
            # selection highlight on the saved-cards list.
            self._loaded_card_id = None
            self._loaded_created_at = None
            # Forget the previous autofill snapshot; the empty editor is then
            # open to a fresh autofill (and a later load cannot be mistaken for
            # an untouched autofill and overwritten).
            self._last_autofill = None
            self.saved_list.clearSelection()
        finally:
            self._suppress_dirty = False
        self._dirty = False
        self._scroll_editor_to_top()

    def _scroll_editor_to_top(self) -> None:
        """Reset the editor scroll so a freshly loaded or cleared card shows from
        the headword down, rather than keeping the previous card's scroll offset.
        Guarded so it is safe to call before init_ui has built the scroll area."""
        scroll = getattr(self, "editor_scroll", None)
        if scroll is not None:
            scroll.verticalScrollBar().setValue(0)

    # --- saved cards list -----------------------------------------------

    def _refresh_saved_list(self):
        """Rebuild the saved-cards list from the store (newest first). Each row
        shows the headword, marked with a leading star for starred cards, and
        carries its card id so a click can load it."""
        self.saved_list.clear()
        for card in self.store.cards:
            label = card.headword
            if card.starred:
                label = f"{self._STAR_SET}: {label}"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, card.id)
            self.saved_list.addItem(item)

    def _on_saved_clicked(self, item):
        card_id = item.data(Qt.ItemDataRole.UserRole)
        card = next((c for c in self.store.cards if c.id == card_id), None)
        if card is not None:
            self.load_card(card)

    def load_card(self, card: Card) -> bool:
        """Load a saved card into the editor for review or editing. Asks to
        discard unsaved content first (unless Ctrl is held); a later Save updates
        this card in place. Returns False if the user declined to discard."""
        if (
            not self.ctrl_held()
            and self._dirty
            and not self._confirm_discard()
        ):
            return False
        self._reset_editor()  # clears fields and any previous loaded id
        # Filling the editor from a saved card is not a user edit; suppress the
        # dirty flag for the whole load so the just-loaded card reads as clean
        # and switching to another card does not prompt to discard.
        self._suppress_dirty = True
        try:
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

            # Rebuild the sense rows from the card (drop the blank starter row
            # first).
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

            self._loaded_card_id = card.id
            self._loaded_created_at = card.created_at or None
        finally:
            self._suppress_dirty = False
        self._dirty = False
        return True

    def _confirm_discard(self) -> bool:
        reply = QMessageBox.question(
            self,
            "Discard flashcard?",
            "The current flashcard has unsaved changes. Discard them?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        return reply == QMessageBox.StandardButton.Yes
