"""Flashcard editor: a dock-panel widget for building one card at a time."""

from datetime import datetime

from PySide6.QtCore import QEvent, Qt, QUrl, Signal
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .flashcards import Card, FlashcardStore, Sense


class SenseRow(QFrame):
    """One editable sense: POS combo, Polish field, English field, a remove button
    and a small list of usage examples beneath them."""

    activated = Signal(object)
    remove_requested = Signal(object)

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
        self.add_example_button.clicked.connect(lambda: self.add_example())
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

    def add_example(self, text: str = "") -> None:
        """Append an example field (focusing the active row first)."""
        self.activated.emit(self)
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(2)

        field_input = QLineEdit()
        field_input.setPlaceholderText("Example")
        field_input.setToolTip("Alt+X: add the web-view selection as an example")
        field_input.setText(text)
        field_input.installEventFilter(self)
        row.example_input = field_input

        remove = QPushButton("x")
        remove.setMaximumWidth(28)
        remove.clicked.connect(lambda: self._remove_example(row))

        row_layout.addWidget(field_input)
        row_layout.addWidget(remove)
        self.examples_container.addWidget(row)

    def add_example_text(self, text: str) -> None:
        """Append an example carrying captured text (skips blank input)."""
        text = text.strip()
        if text:
            self.add_example(text)

    def _remove_example(self, row) -> None:
        self.examples_container.removeWidget(row)
        row.deleteLater()

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
        self.player = None
        self.audio_output = None
        self.init_ui()
        self.add_sense()

    def init_ui(self):
        layout = QVBoxLayout(self)

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

        ipa_row = QHBoxLayout()
        self.ipa_uk_input = QLineEdit()
        self.ipa_uk_input.setPlaceholderText("IPA UK")
        self.ipa_uk_input.setToolTip(
            "New from word: filled from the Cambridge page"
        )
        self.ipa_us_input = QLineEdit()
        self.ipa_us_input.setPlaceholderText("IPA US")
        self.ipa_us_input.setToolTip(
            "New from word: filled from the Cambridge page"
        )
        ipa_row.addWidget(self.ipa_uk_input)
        ipa_row.addWidget(self.ipa_us_input)
        form.addRow("IPA", ipa_row)

        audio_row = QHBoxLayout()
        self.play_uk_button = QPushButton("play UK")
        self.play_uk_button.clicked.connect(lambda: self.play_audio("uk"))
        self.play_us_button = QPushButton("play US")
        self.play_us_button.clicked.connect(lambda: self.play_audio("us"))
        audio_row.addWidget(self.play_uk_button)
        audio_row.addWidget(self.play_us_button)
        form.addRow("Audio", audio_row)

        self.own_notation_input = QLineEdit()
        form.addRow("Own notation", self.own_notation_input)

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
            "from the Cambridge page"
        )
        self.clear_button = QPushButton("Clear")
        self.clear_button.clicked.connect(self.clear_editor)
        self.save_button = QPushButton("Save")
        self.save_button.clicked.connect(self.save_card)
        buttons.addWidget(self.new_button)
        buttons.addWidget(self.clear_button)
        buttons.addWidget(self.save_button)
        layout.addLayout(buttons)

        layout.addStretch()
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
        self._ensure_active_row().polish_input.setText(text)

    def set_english_selection(self, text: str):
        text = text.strip()
        if not text:
            return
        self._ensure_active_row().english_input.setText(text)

    def add_example_selection(self, text: str):
        text = text.strip()
        if not text:
            return
        self._ensure_active_row().add_example_text(text)

    # --- pronunciation --------------------------------------------------

    def set_pronunciation(
        self,
        ipa_uk,
        ipa_us,
        audio_uk_url,
        audio_us_url,
        spelling_uk=None,
        spelling_us=None,
    ):
        if ipa_uk:
            self.ipa_uk_input.setText(ipa_uk)
        if ipa_us:
            self.ipa_us_input.setText(ipa_us)
        if audio_uk_url:
            self._audio_uk_url = audio_uk_url
        if audio_us_url:
            self._audio_us_url = audio_us_url
        # Only fill spelling when empty, so a manual edit is never overwritten.
        if spelling_uk and not self.spelling_uk_input.text().strip():
            self.spelling_uk_input.setText(spelling_uk)
        if spelling_us and not self.spelling_us_input.text().strip():
            self.spelling_us_input.setText(spelling_us)
        self._update_play_buttons()

    def _update_play_buttons(self):
        self.play_uk_button.setEnabled(bool(self._audio_uk_url))
        self.play_us_button.setEnabled(bool(self._audio_us_url))

    # --- star -----------------------------------------------------------

    def _on_star_toggled(self, checked: bool):
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
        return Card(
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
            created_at=now,
            updated_at=now,
        )

    def save_card(self):
        card = self.build_card()
        if card is None:
            self.save_rejected.emit("Cannot save flashcard: headword is empty")
            return
        self.store.add_card(card)
        headword = card.headword
        self._reset_editor()
        self.card_saved.emit(headword)

    def new_card(self, word: str):
        if self.has_content() and not self._confirm_discard():
            return
        self._reset_editor()
        self.headword_input.setText(word)

    def clear_editor(self):
        if self.has_content() and not self._confirm_discard():
            return
        self._reset_editor()

    def _reset_editor(self):
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

    def _confirm_discard(self) -> bool:
        reply = QMessageBox.question(
            self,
            "Discard flashcard?",
            "The current flashcard has unsaved changes. Discard them?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        return reply == QMessageBox.StandardButton.Yes
