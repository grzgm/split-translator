"""Shared flashcard editor: card fields, senses, saved list, lifecycle.

FlashcardEditorBase holds everything about building and saving one card that
is common to every editor variant. Saved-list row behaviour that differs
between variants (for example FlashcardPanel's tick-to-link controls, or
FlashcardPrintPanel's tick-to-print checkboxes) is factored behind five
overridable hooks (_configure_saved_item, _on_saved_item_changed,
_saved_controls_widget, _on_saved_list_refreshed, _loaded_row_is_checkable)
and a link-persistence seam (_links_to_persist, _after_save) around
save_card, so a subclass can add its own saved-list semantics without
touching this file."""

from contextlib import contextmanager
from datetime import datetime

from PySide6.QtCore import QByteArray, QEvent, QPointF, QRectF, QSize, Qt, QUrl, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFontMetrics,
    QIcon,
    QPainter,
    QPen,
    QPixmap,
    QPolygonF,
)
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStyle,
    QStyledItemDelegate,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .field_marker import attach_empty_marker, mark_empty
from .flashcard_autofill import Target
from .flashcard_editor_state import EditorState
from .flashcard_fields import CARD_FIELDS
from .flashcard_tags import format_tags, normalise_tag, parse_tags
from .flashcards import Card, FlashcardStore, Sense


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


class SavedCardsList(QListWidget):
    """The saved-cards list, with Enter/Return set to load the focused card.

    Arrowing through the list moves the focus row; Space toggles that row's
    checkbox (the default list behaviour, left untouched); Enter or Return loads
    the focused card, mirroring a click on its text. ``item_activated_by_key``
    carries the focused item so the editor can load it. All other keys fall
    through to the default handler.

    ``key_handled`` fires after each key press is handled. The editor uses it to
    clear the "a checkbox click is in progress" guard: that guard exists to stop
    the mouse click that co-fires with a mouse checkbox toggle from also loading
    the card, but a keyboard Space toggle fires no such click, so without this the
    guard would linger and swallow the next real text click."""

    item_activated_by_key = Signal(QListWidgetItem)
    key_handled = Signal()

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            item = self.currentItem()
            if item is not None:
                self.item_activated_by_key.emit(item)
                event.accept()
                return
        # Default handling first: a Space press toggles the current row's
        # checkbox here, which sets the editor's checkbox-click guard. Announce
        # afterwards so the editor can clear that guard (a keyboard toggle fires
        # no co-firing mouse click for the guard to suppress).
        super().keyPressEvent(event)
        self.key_handled.emit()


class PosPopupView(QListView):
    """The drop-down list of the POS combo, where a letter picks rather than seeks.

    Qt's own popup treats letters as an incremental *search*: it accumulates them
    into a prefix, only moves the highlight, and never commits, so choosing "v"
    means typing it and then pressing Enter or clicking. Worse for these codes,
    the prefix is sticky. Typing "v" then "a" searches for "va", matches nothing,
    and the highlight stops responding until the prefix times out, which makes the
    list feel dead depending on how fast you type.

    Here a plain letter is a choice instead. It jumps to the next code starting
    with that letter, emits ``row_chosen`` so the owner can commit it, and leaves
    the popup open, so the value is set the moment the key is pressed and you can
    keep pressing to change your mind. Because several codes share a first letter,
    repeats cycle: "a" walks adj then adv, "p" walks pre, pro, phr. Any other key
    (arrows, Enter, Escape) falls through to the default handler untouched."""

    #: Emitted with the row a letter key just picked, for the owner to commit.
    row_chosen = Signal(int)

    def keyPressEvent(self, event) -> None:
        text = event.text().strip().lower()
        # Bare letters only. Modified keys stay with Qt so shortcuts still work.
        if len(text) == 1 and text.isalpha() and not event.modifiers():
            if self._jump_to_letter(text):
                event.accept()
                return
        super().keyPressEvent(event)

    def _jump_to_letter(self, letter: str) -> bool:
        """Highlight the next code starting with ``letter``, cycling on repeats.

        Returns False when no code starts with it, leaving the key to Qt so the
        current value is not disturbed."""
        model = self.model()
        if model is None:
            return False
        rows = [
            row
            for row in range(model.rowCount())
            if str(model.index(row, 0).data() or "").lower().startswith(letter)
        ]
        if not rows:
            return False
        # Step past the current row so pressing the same letter again advances to
        # the next code sharing it, and wrap back to the first once past the end.
        current = self.currentIndex().row()
        later = [row for row in rows if row > current]
        row = later[0] if later else rows[0]
        self.setCurrentIndex(model.index(row, 0))
        self.row_chosen.emit(row)
        return True


# The sense row's border in both states. Set once per row; set_active flips the
# activeRow property rather than replacing this sheet, because replacing it
# re-polishes every child (see field_marker for what that used to break). The
# inactive border is transparent rather than absent so the row is exactly the
# same size active and inactive.
_SENSE_ROW_STYLE = (
    "#senseRow { border: 2px solid transparent; border-radius: 4px; }"
    '#senseRow[activeRow="true"] { border-color: #0a84ff; }'
)


class SenseRow(QFrame):
    """One editable sense: POS combo, Polish field, English field, a remove button
    and a small list of usage examples beneath them."""

    activated = Signal(object)
    remove_requested = Signal(object)
    edited = Signal()
    # The row's FIRST example changed by hand: typed into, captured into, or
    # removed. Separate from edited because that slot is the one the book
    # sentence auto-fills, so the editor has to know when the user takes it
    # over; every other edit here leaves the passive fills alone.
    first_example_edited = Signal()

    # Every code is at most three letters, so the combo (and the printed card)
    # stays narrow. Keep these in sync with ``DictionaryPanel._POS_MAP``, which
    # is what the capture buttons feed into this combo.
    POS_OPTIONS = ["n", "v", "adj", "adv", "pre", "con", "pro", "phr"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("senseRow")
        self.setStyleSheet(_SENSE_ROW_STYLE)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(2, 2, 2, 2)
        outer.setSpacing(2)

        top = QHBoxLayout()

        self.pos_combo = QComboBox()
        self.pos_combo.setEditable(True)
        # A letter typed in the open drop-down picks that code straight away and
        # keeps the list up (see PosPopupView). The view only highlights; setting
        # the value is the combo's job, so the row commits what the view picked.
        self.pos_popup = PosPopupView()
        self.pos_combo.setView(self.pos_popup)
        self.pos_popup.row_chosen.connect(self.pos_combo.setCurrentIndex)
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
            lambda _=None: mark_empty(self.pos_combo)
        )
        self.pos_combo.currentTextChanged.connect(lambda _=None: self.edited.emit())
        attach_empty_marker(self.pos_combo)
        for field in (self.polish_input, self.english_input):
            field.textChanged.connect(lambda _=None, f=field: mark_empty(f))
            field.textChanged.connect(lambda _=None: self.edited.emit())
            attach_empty_marker(field)

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
        """Show or hide the active-row highlight.

        Only the property changes: the row's stylesheet is set once in __init__
        and carries both states. Replacing the sheet here (as this used to do)
        re-polished every child, and a re-polish restores the palette Qt cached
        for that child when the row was built, which resurrected stale
        empty-field markers on fields the user had already filled."""
        self.setProperty("activeRow", "true" if active else "false")
        self.style().unpolish(self)
        self.style().polish(self)

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
            lambda _=None, f=field_input: mark_empty(f)
        )
        field_input.textChanged.connect(lambda _=None: self.edited.emit())
        field_input.textChanged.connect(
            lambda _=None, r=row: self._first_example_changed(r)
        )
        attach_empty_marker(field_input)
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
        # A capture into a sense with no examples yet lands in the first slot,
        # which the pre-fill wrote before the hook existed; say so here.
        self._first_example_changed(row)

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
        # Through _fill, like every other programmatic fill: a plain setText
        # leaves the cursor at the end, so a sentence wider than the field shows
        # its end and reads as right-aligned next to the examples below it.
        _fill(rows[0].example_input, text)

    def first_example_text(self) -> str:
        """The first example row's text, or "" when the sense has no example row
        yet. Lets a gap fill see whether the slot set_first_example writes into
        is still free."""
        rows = self._example_rows()
        return rows[0].example_input.text().strip() if rows else ""

    def _is_first_example(self, row) -> bool:
        rows = self._example_rows()
        return bool(rows) and rows[0] is row

    def _first_example_changed(self, row) -> None:
        """Announce a change to the slot the book-sentence fill owns, but only
        when the changed row really is that slot. The second and later examples
        are nobody's target, so they stay silent here."""
        if self._is_first_example(row):
            self.first_example_edited.emit()

    def _remove_example(self, row) -> None:
        # Read before the removal: afterwards the next row is the first one.
        was_first = self._is_first_example(row)
        self.examples_container.removeWidget(row)
        row.deleteLater()
        self.edited.emit()
        if was_first:
            self.first_example_edited.emit()

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


# Material Symbols "print" glyph, filled and outlined. The path data is centred
# in the 0 -960 960 960 viewBox, so it rasterises centred in a square pixmap.
# "{fill}" is replaced with the wanted colour before rendering.
_PRINTER_FILL_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 -960 960 960" '
    'fill="{fill}"><path d="M720-680H240v-160h480v160Zm0 220q17 0 28.5-11.5'
    'T760-500q0-17-11.5-28.5T720-540q-17 0-28.5 11.5T680-500q0 17 11.5 28.5'
    'T720-460Zm-80 260v-160H320v160h320Zm80 80H240v-160H80v-240q0-51 35-85.5'
    't85-34.5h560q51 0 85.5 34.5T880-520v240H720v160Z"/></svg>'
)
_PRINTER_OUTLINE_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 -960 960 960" '
    'fill="{fill}"><path d="M640-640v-120H320v120h-80v-200h480v200h-80Zm-480 '
    '80h640-640Zm560 100q17 0 28.5-11.5T760-500q0-17-11.5-28.5T720-540q-17 0'
    '-28.5 11.5T680-500q0 17 11.5 28.5T720-460Zm-80 260v-160H320v160h320Zm80 '
    '80H240v-160H80v-240q0-51 35-85.5t85-34.5h560q51 0 85.5 34.5T880-520v240'
    'H720v160Zm80-240v-160q0-17-11.5-28.5T760-560H200q-17 0-28.5 11.5T160-520'
    'v160h80v-80h480v80h80Z"/></svg>'
)


def _printer_pixmap(size: int, colour: str, filled: bool = True) -> QPixmap:
    """A printer glyph rendered from the Material Symbols "print" icon (filled
    or outlined), coloured by substituting the SVG fill. Rasterised onto a
    transparent square so it centres on a button or a saved-list row. With
    filled=False the outlined variant is used for the "off" toggle state."""
    template = _PRINTER_FILL_SVG if filled else _PRINTER_OUTLINE_SVG
    svg = template.replace("{fill}", colour)
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter, QRectF(0, 0, size, size))
    painter.end()
    return pixmap


def _star_pixmap(size: int, colour: str, filled: bool = True) -> QPixmap:
    """A small five-point star, matching the printer glyph's weight. With
    filled=False it is stroked as an outline, used for the "off" state of the
    toggle button."""
    import math
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    if filled:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor(colour)))
    else:
        painter.setPen(QPen(QColor(colour), max(1.0, size / 16.0)))
        painter.setBrush(Qt.BrushStyle.NoBrush)
    cx = cy = size / 2.0
    # Leave room for the outline stroke so it is not clipped at the edges.
    outer = size / 2.0 - (0.0 if filled else max(1.0, size / 16.0))
    inner = outer * 0.5
    points = []
    for i in range(10):
        r = outer if i % 2 == 0 else inner
        angle = math.pi / 2 + i * math.pi / 5
        points.append(
            QPointF(cx + r * math.cos(angle), cy - r * math.sin(angle))
        )
    painter.drawPolygon(QPolygonF(points))
    painter.end()
    return pixmap


class SavedCardRowDelegate(QStyledItemDelegate):
    """Draws the normal row, then overlays right-edge glyphs for the printed
    and starred roles: the star glyph at the far right, and the printer icon
    to its left when both are set. Only adds to the default painting; the
    checkbox, the loaded-card marker and the row tint are untouched."""

    def __init__(self, printed_role: int, starred_role: int, parent=None):
        super().__init__(parent)
        self._printed_role = printed_role
        self._starred_role = starred_role
        self._icon = _printer_pixmap(14, "#4a90d9")
        self._star = _star_pixmap(14, "#f0b400")

    def paint(self, painter, option, index):
        super().paint(painter, option, index)
        rect = option.rect
        x = rect.right() - self._star.width() - 4
        y = rect.top() + (rect.height() - self._star.height()) // 2
        if bool(index.data(self._starred_role)):
            painter.drawPixmap(x, y, self._star)
            x -= self._icon.width() + 2
        if bool(index.data(self._printed_role)):
            painter.drawPixmap(x, y, self._icon)


class FlashcardEditorBase(QWidget):
    """Editor that builds one card at a time and saves it to the store.

    A single EditorState answers the questions the editor keeps asking: which
    mode (new or editing), has the user altered the card, and which of the
    passive fills' targets are still free. Every user edit routes through
    _on_user_edit (sets altered, and names the target it landed on); every
    programmatic fill runs inside _programmatic() (never sets altered). Edits to
    fields that are printed on the card go through _on_printed_content_edit
    instead, which does that and also clears the printed flag.

    Filling comes in two kinds, and they read that state differently. The
    passive auto-fills (autofill_headword, autofill_pronunciation,
    autofill_book_example) arrive on their own, seconds apart, as the search box,
    the book and the dictionary pages answer; each writes a target while the
    round still owns it (see flashcard_autofill), which is what lets the card be
    typed into while the pages load. The deliberate gap fill (the fill_empty_*
    methods behind the Fill button) is asked for by hand, so it runs at any time
    and writes only into blank fields. Three indicators, the Save button
    label, the read-only Id field and the loaded-row dot, are all refreshed by
    _apply_state_to_ui so they can never disagree. Whether Save is enabled
    reads the same state (see _can_save) and additionally follows the headword,
    so the button is live exactly when saving would write a card.

    Saved-list row behaviour that a subclass wants to add (for example
    tick-to-link checkboxes) is factored behind five hooks called at fixed
    seams: _configure_saved_item (per non-loaded row, on refresh),
    _on_saved_item_changed (a row's check-state changed),
    _saved_controls_widget (an optional widget placed under the list),
    _on_saved_list_refreshed (called once, at the end of a refresh) and
    _loaded_row_is_checkable (whether the loaded card's own row is routed
    through _configure_saved_item too, base default False). Saving with
    subclass-owned links alongside the card goes through _links_to_persist
    and _after_save around save_card."""

    card_saved = Signal(str)
    save_rejected = Signal(str)
    card_loaded = Signal(str)  # headword of a card just loaded into the editor
    # True once the card has unsaved edits, False again once it is saved,
    # cleared or replaced by a freshly loaded one. Fires only on the flip, not
    # per keystroke. The main window shows it as a "*" on the dock title, the
    # way a text editor marks a modified file.
    altered_changed = Signal(bool)
    # The Fill button's dropdown item was chosen. Like fill_button.clicked, the
    # panel only announces it: the main window owns the sources New fills from
    # (the search box, the Cambridge page, the book match).
    new_requested = Signal()

    #: The smallest gap left between Clear and Save, in pixels. Wider whenever
    #: the panel has room; never narrower, however narrow the panel gets.
    _SAVE_GAP = 24

    _PRINTED_ROLE = Qt.ItemDataRole.UserRole + 1
    _STARRED_ROLE = Qt.ItemDataRole.UserRole + 2
    _TAGS_ROLE = Qt.ItemDataRole.UserRole + 3

    def __init__(self, store: FlashcardStore, parent=None):
        super().__init__(parent)
        self.store = store
        self.state = EditorState()
        # The state is pure logic and holds no Qt; it announces an altered flip
        # through a plain callback, which becomes this widget's signal here.
        self.state.on_altered_changed = self._on_altered_changed
        self.active_row = None
        self._audio_uk_url = None
        self._audio_us_url = None
        # True while a programmatic fill runs (load, autofill, capture, reset)
        # so _on_user_edit is a no-op and those fills never set altered.
        self._programmatic_depth = 0
        self.player = None
        self.audio_output = None
        # Reentrancy guard for _saved_item_changed_dispatch: set while the list
        # is being repopulated/reticked programmatically, so those check-state
        # changes never reach _on_saved_item_changed.
        self._suppress_item_changed = False
        # Set while a checkbox click is being processed so the itemClicked that
        # co-fires with itemChanged does not also load the card.
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

    def _on_user_edit(self, *_args, target: str = "") -> None:
        """A genuine user edit. No-op during a programmatic fill.

        target names the passive-fill target the edit landed on, where the
        caller knows it. That is what closes one field to the fills without
        closing the rest, so the pages can keep filling around what is being
        typed while they load (see flashcard_autofill)."""
        if self._programmatic_depth == 0:
            self.state.mark_altered(target)

    def _on_printed_content_edit(self, *_args, target: str = "") -> None:
        """A user edit to something that reaches paper: the headword, the own
        notation, the star, or any sense or example. Marks the card altered like
        any edit, and additionally clears the printed flag, because what was
        printed no longer matches the card and it is due a reprint.

        The clear is skipped once the user has set the flag by hand for this
        card, so a deliberate "this one is printed" survives carrying on
        editing. It runs guarded, so the clear itself is not read back as a
        hand-set flag. Fields that never reach paper (the spellings, the IPA,
        the audio, the links) stay on _on_user_edit and leave the flag alone."""
        if self._programmatic_depth:
            return
        self._on_user_edit(target=target)
        if self.state.printed_flag_altered or not self.is_printed():
            return
        with self._programmatic():
            self.set_printed(False)

    # --- card fields (built and driven from the registry) -----------------

    def _build_fields(self) -> None:
        """Create a widget for every registered card field.

        The registry owns identity, placeholder, tooltip and the Card mapping;
        init_ui still arranges the widgets by hand, because the rows are
        genuinely bespoke (the headword shares its row with the star and printed
        toggles, and Spelling and IPA each pair two fields under one label)."""
        for spec in CARD_FIELDS:
            field = QLineEdit()
            if spec.placeholder:
                field.setPlaceholderText(spec.placeholder)
            if spec.tooltip:
                field.setToolTip(spec.tooltip)
            setattr(self, spec.attr, field)

    def _card_field_widgets(self) -> list:
        """Every registered field as (spec, widget), in registry order. The one
        place that turns the registry into live widgets, so wiring, reset, load
        and save all walk the same list."""
        return [(spec, getattr(self, spec.attr)) for spec in CARD_FIELDS]

    def _wire_fields(self) -> None:
        """Mark each field while it is empty and route typing into the right
        handler.

        A printed field's edits also clear the printed flag, because the paper
        copy stops matching the card the moment its printed content changes; the
        others only mark the card altered.

        Each field also names itself as the passive fills' target, which works
        because the registry's names are the target names (see
        flashcard_autofill.Target). A field with no fill behind it (Own notation,
        Tags) names a target nothing writes, which costs nothing."""
        for spec, field in self._card_field_widgets():
            on_edit = (
                self._on_printed_content_edit
                if spec.printed
                else self._on_user_edit
            )
            field.textChanged.connect(lambda _=None, f=field: mark_empty(f))
            field.textChanged.connect(
                lambda _=None, handler=on_edit, name=spec.name: handler(
                    target=name
                )
            )
            attach_empty_marker(field)

    def init_ui(self):
        self._build_fields()
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
        # Compact icon toggles: a filled glyph with a coloured background when
        # on, an outline glyph with no background when off.
        self._star_icon_on = QIcon(_star_pixmap(18, "#ffffff", filled=True))
        self._star_icon_off = QIcon(_star_pixmap(18, "#f0b400", filled=False))
        self._printed_icon_on = QIcon(_printer_pixmap(18, "#ffffff", filled=True))
        self._printed_icon_off = QIcon(_printer_pixmap(18, "#4a90d9", filled=False))
        self.star_button = QPushButton()
        self.star_button.setCheckable(True)
        self.star_button.setMaximumWidth(32)
        self.star_button.setIconSize(QSize(18, 18))
        self.star_button.setIcon(self._star_icon_off)
        self.star_button.setToolTip("Star this card (mark as important)")
        self.star_button.toggled.connect(self._on_star_toggled)
        headword_row.addWidget(self.headword_input)
        headword_row.addWidget(self.star_button)
        self.printed_button = QPushButton()
        self.printed_button.setCheckable(True)
        self.printed_button.setMaximumWidth(32)
        self.printed_button.setIconSize(QSize(18, 18))
        self.printed_button.setIcon(self._printed_icon_off)
        self.printed_button.setToolTip("Mark this card as printed")
        self.printed_button.toggled.connect(self._on_printed_toggled)
        headword_row.addWidget(self.printed_button)
        form.addRow("Headword", headword_row)

        spelling_row = QHBoxLayout()
        spelling_row.addWidget(self.spelling_uk_input)
        spelling_row.addWidget(self.spelling_us_input)
        form.addRow("Spelling", spelling_row)

        speaker_icon = self.style().standardIcon(
            QStyle.StandardPixmap.SP_MediaVolume
        )

        ipa_row = QHBoxLayout()
        self.play_uk_button = QPushButton()
        self.play_uk_button.setIcon(speaker_icon)
        self.play_uk_button.setMaximumWidth(32)
        self.play_uk_button.setToolTip("Play UK pronunciation")
        self.play_uk_button.clicked.connect(lambda: self.play_audio("uk"))

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

        form.addRow("Own notation", self.own_notation_input)
        form.addRow("Tags", self.tags_input)

        self._wire_fields()

        layout.addLayout(form)

        # The sense button heads its own section rather than sitting with the
        # card actions at the bottom. It acts on the list right below it, so it
        # reads as part of that list and is never mistaken for a Clear or Save.
        senses_header = QHBoxLayout()
        senses_header.addWidget(QLabel("Senses"))
        senses_header.addStretch()
        self.add_sense_button = QPushButton("+ Add sense")
        self.add_sense_button.setToolTip("Add another sense to this card")
        self.add_sense_button.clicked.connect(self.add_sense)
        senses_header.addWidget(self.add_sense_button)
        layout.addLayout(senses_header)

        self.senses_container = QVBoxLayout()
        senses_widget = QWidget()
        senses_widget.setLayout(self.senses_container)
        layout.addWidget(senses_widget)

        buttons = QHBoxLayout()
        # A split button: the wide part is Fill, the arrow beside it drops down
        # New. They share a button because they share a source (the page on
        # screen) and differ only in what they are allowed to overwrite: Fill
        # writes into blank fields only, New starts the card over.
        #
        # Fill is the wide part because it is the everyday one and it cannot
        # lose work. New replaces the card that is open, so it sits behind the
        # arrow where a misclick meant for Fill cannot reach it.
        self.fill_button = QToolButton()
        self.fill_button.setText("Fill")
        self.fill_button.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextOnly
        )
        self.fill_button.setPopupMode(
            QToolButton.ToolButtonPopupMode.MenuButtonPopup
        )
        # A tool button is compact by default; match the push buttons beside it
        # so the row keeps one height and shares its width evenly.
        self.fill_button.setSizePolicy(
            QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed
        )
        self.fill_button.setToolTip(
            "Fill only the fields that are still blank from the page on screen, "
            "keeping the card and everything already in it."
        )
        self.new_menu = QMenu(self.fill_button)
        self.new_action = self.new_menu.addAction("New")
        self.new_action.setToolTip(
            "Ctrl+N: start a card and fill headword, IPA, spelling and audio "
            "from the Cambridge page. Ctrl+click skips the discard confirmation."
        )
        self.new_action.triggered.connect(self.new_requested)
        self.fill_button.setMenu(self.new_menu)
        self.clear_button = QPushButton("Clear")
        self.clear_button.setToolTip(
            "Empty the editor. Ctrl+click skips the discard confirmation."
        )
        self.clear_button.clicked.connect(self.clear_editor)
        # The Save button label switches with the mode: "Save card" when new,
        # "Save changes" when editing (set in _apply_state_to_ui). Whether it is
        # enabled tracks the headword and the altered flag, so it is live only
        # when saving would actually write a card (see _update_save_button).
        self.save_button = QPushButton("Save card")
        self.save_button.clicked.connect(self.save_card)
        self.headword_input.textChanged.connect(self._update_save_button)
        # A tool button asks for less room than a push button, which would leave
        # the row uneven and the dropdown arrow a cramped target. Match Clear in
        # both directions instead.
        self.fill_button.setMinimumHeight(self.clear_button.sizeHint().height())
        self.fill_button.setMinimumWidth(self.clear_button.sizeHint().width())
        # Clear throws work away, so it keeps to the left with Fill and Save
        # sits on its own at the right, out of reach of a misclick meant for
        # Clear. The stretch opens the gap as wide as the panel allows and the
        # spacing keeps a gap there even when the panel is narrow.
        buttons.addWidget(self.fill_button)
        buttons.addWidget(self.clear_button)
        buttons.addStretch()
        buttons.addSpacing(self._SAVE_GAP)
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
        self.saved_filter.setPlaceholderText("Filter by headword or tag")
        self.saved_filter.setClearButtonEnabled(True)
        self.saved_filter.textChanged.connect(self._apply_saved_filter)
        saved_layout.addWidget(self.saved_filter)
        self.saved_list = SavedCardsList()
        self.saved_list.setItemDelegate(
            SavedCardRowDelegate(
                self._PRINTED_ROLE, self._STARRED_ROLE, self.saved_list
            )
        )
        # Clicking a row selects it, and a selected item is normally scrolled into
        # view. When a card partway down the list is clicked to load it, that
        # auto-scroll would move the list out from under the click, so turn it off
        # (the scroll position is preserved across the load instead).
        self.saved_list.setAutoScroll(False)
        self.saved_list.setToolTip(
            "Click a card's text (or focus it with the arrow keys and press "
            "Enter) to load it; tick its box (or press Space) to toggle it"
        )
        self.saved_list.itemClicked.connect(self._on_saved_clicked)
        # Enter/Return on the keyboard-focused row loads it, like a text click.
        self.saved_list.item_activated_by_key.connect(self._on_saved_activated)
        # After a key press (e.g. a Space checkbox toggle), clear the checkbox
        # guard so it cannot swallow the next real text click.
        self.saved_list.key_handled.connect(self._clear_checkbox_click_guard)
        self.saved_list.itemChanged.connect(self._saved_item_changed_dispatch)
        # Right-clicking a row offers to delete that card, the way the history
        # list does. Deleting is the one thing the list cannot otherwise do.
        self.saved_list.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        self.saved_list.customContextMenuRequested.connect(
            self._show_saved_context_menu
        )
        saved_layout.addWidget(self.saved_list, stretch=1)

        controls = self._saved_controls_widget()
        if controls is not None:
            saved_layout.addWidget(controls)

        self.editor_splitter = QSplitter(Qt.Orientation.Vertical)
        self.editor_splitter.addWidget(self.editor_scroll)
        self.editor_splitter.addWidget(saved_widget)
        self.editor_splitter.setChildrenCollapsible(False)
        # Both panes grow with the splitter (a stretch factor of 0 would pin one
        # of them at its starting height, which is what used to leave the editor
        # stuck at 480px however tall the panel was and hand every extra pixel
        # to the card list). Extra height is then shared in proportion to the
        # sizes below, so an even start stays even at any height.
        self.editor_splitter.setStretchFactor(0, 1)
        self.editor_splitter.setStretchFactor(1, 1)
        self.editor_splitter.setSizes([320, 320])
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
            self.save_button.setText("Save card")
            self.id_input.setText("")
        self._update_save_button()

    def _on_altered_changed(self, altered: bool) -> None:
        """The card's altered flag flipped. Announce it, and refresh the one
        piece of the UI that depends on it: whether Save is live."""
        self.altered_changed.emit(altered)
        self._update_save_button()

    def _can_save(self) -> bool:
        """Whether pressing Save would actually write a card.

        Both modes need a headword, because build_card refuses without one.
        Editing additionally needs an edit: re-saving a card nobody has touched
        would write the same card back. New mode has no such baseline, and the
        Cambridge auto-fill deliberately leaves the card unaltered, so a card
        filled entirely by a search is saveable the moment its headword
        arrives."""
        if not self.headword_input.text().strip():
            return False
        return self.state.is_new or self.state.altered

    def _update_save_button(self) -> None:
        """Enable or disable Save, and say in the tooltip why it is off.

        Ctrl+S still reaches save_card while the button is disabled, and is
        answered there with a status message, so nothing becomes unreachable."""
        enabled = self._can_save()
        self.save_button.setEnabled(enabled)
        if enabled:
            self.save_button.setToolTip("Ctrl+S: save this card")
        elif not self.headword_input.text().strip():
            self.save_button.setToolTip("A headword is needed before saving")
        else:
            self.save_button.setToolTip("No changes to save")

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
        # Everything a sense row holds (part of speech, Polish, English,
        # examples) is printed, so its edits clear the printed flag too.
        row.edited.connect(self._on_printed_content_edit)
        row.first_example_edited.connect(
            lambda r=row: self._on_first_example_edit(r)
        )
        self.senses_container.addWidget(row)
        self.set_active_row(row)

    def _on_first_example_edit(self, row) -> None:
        """The user has taken over a sense's first example.

        row.edited has already marked the card altered; this only names the
        target, so the book-sentence fill leaves that example alone while the
        rest of the card keeps filling. Only the FIRST sense's first example is
        a fill target: that is the one slot autofill_book_example writes."""
        if self._programmatic_depth:
            return
        rows = self._rows()
        if rows and rows[0] is row:
            self.state.mark_altered(Target.EXAMPLE)

    def set_active_row(self, row):
        self.active_row = row
        for candidate in self._rows():
            candidate.set_active(candidate is row)

    def set_active_index(self, index: int):
        rows = self._rows()
        if 1 <= index <= len(rows):
            self.set_active_row(rows[index - 1])

    def remove_sense(self, row):
        self._on_printed_content_edit()
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

    def add_book_tag(self, tag: str) -> None:
        """Record the book that has just filled something into this card.

        Called only from the two book-example fills, and only when one of them
        actually took a sentence: the tag records where that sentence came from,
        so a card that took nothing from the book is not tagged with it. A blank
        tag, or one the card already carries, does nothing. Otherwise the field
        is rewritten with the tag appended, inside the programmatic guard, so
        the tagging never marks the card altered (which would stop the next book
        match refilling it)."""
        tag = normalise_tag(tag)
        if not tag:
            return
        current = parse_tags(self.tags_input.text())
        if tag in current:
            return
        with self._programmatic():
            _fill(self.tags_input, format_tags(current + [tag]))

    def autofill_book_example(self, sentence: str, book_tag: str = "") -> None:
        """Passive auto-fill of the book match sentence into the first sense's
        first example, and of that book's tag into the tags field. Same rule as
        autofill_pronunciation: only while this round still owns that example
        slot, and written through the programmatic guard so the fill itself never
        marks the card altered (which lets a later book match refill again). A
        blank sentence is ignored, and the tag with it: nothing was taken from
        the book, so there is no source to record.

        Only the example decides. Writing the sense's Polish or English does not
        stop the sentence landing beneath it, so a sense can be translated by
        hand while the book match is still on its way."""
        sentence = (sentence or "").strip()
        if not sentence:
            return
        if not self.state.autofill.allows(Target.EXAMPLE):
            return
        with self._programmatic():
            self._rows()[0].set_first_example(sentence)
        self.add_book_tag(book_tag)

    # --- pronunciation / auto-grab --------------------------------------

    def autofill_headword(self, word: str) -> None:
        """Seed the headword with the phrase that was searched, before any
        dictionary page has loaded.

        Same passive rule as the other auto-fills: only while this round still
        owns the headword, and written through the programmatic guard so the seed
        never marks the card altered. A blank word is ignored.

        This is what leaves a usable headword when the sites do not load at all
        (no connection, a failed page). When a Cambridge page does load,
        autofill_pronunciation replaces the seed with the page's own canonical
        spelling."""
        word = (word or "").strip()
        if not word or not self.state.autofill.allows(Target.HEADWORD):
            return
        with self._programmatic():
            _fill(self.headword_input, word)

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
        IPA, spelling and audio, target by target: each one is written while
        this round still owns it, and silently skipped once the user has taken
        it over (no dialog, no overwrite). The refill runs programmatically so
        it never marks the card altered, which lets a later page load refill
        again.

        A page takes seconds to load, and this is what lets those seconds be
        used: typing the headword while the page is on its way keeps the typed
        headword and still gains the page's IPA, spelling and audio. A card that
        was already being edited when the search ran is outside the round
        altogether and takes nothing.

        The headword this replaces is usually the search phrase seeded up front
        by autofill_headword, so the field is filled from the moment of the
        search and gains the page's canonical spelling once it loads."""
        if not self.state.autofill.is_open:
            return
        # Write every free grab field (even to empty) so a re-fill clears values
        # the previous word had but the new one lacks. The headword is the one
        # exception: a page with no headword leaves the search-phrase seed in
        # place (see autofill_headword) rather than blanking the field.
        with self._programmatic():
            if word:
                self._autofill_field(Target.HEADWORD, self.headword_input, word)
            self._autofill_field(Target.IPA_UK, self.ipa_uk_input, ipa_uk)
            self._autofill_field(Target.IPA_US, self.ipa_us_input, ipa_us)
            self._autofill_field(
                Target.SPELLING_UK, self.spelling_uk_input, spelling_uk
            )
            self._autofill_field(
                Target.SPELLING_US, self.spelling_us_input, spelling_us
            )
            self._autofill_audio("uk", audio_uk_url)
            self._autofill_audio("us", audio_us_url)
        self._update_play_buttons()

    def _autofill_field(self, target: str, field: QLineEdit, value) -> None:
        """Write one passive-fill target, unless the user has taken it over.

        The passive half of _fill_if_empty: that one asks whether the field is
        blank, this one asks whose the field is. A blank value is written like
        any other, so a second page load clears what the previous word had and
        this one lacks. Runs inside the caller's programmatic guard, so it never
        marks the card altered."""
        if self.state.autofill.allows(target):
            _fill(field, value or "")

    def _autofill_audio(self, region: str, url) -> None:
        """The audio half of _autofill_field, mirroring _set_audio_if_empty."""
        if not self.state.autofill.allows(Target.audio(region)):
            return
        if region == "uk":
            self._audio_uk_url = url or None
        else:
            self._audio_us_url = url or None

    def _update_play_buttons(self):
        self.play_uk_button.setEnabled(bool(self._audio_uk_url))
        self.play_us_button.setEnabled(bool(self._audio_us_url))

    # --- gap fill (deliberate, blank fields only) -------------------------
    #
    # Asked for by hand, unlike the autofills above, so it runs whatever the
    # card's altered state; but it only ever writes into a field that is still
    # blank, so nothing already on the card can be lost. It leaves the card's
    # altered flag exactly as it found it: every write runs inside the
    # programmatic guard and nothing marks the card afterwards. A blank new card
    # therefore stays as open to the passive grabs as a freshly cleared one, a
    # card the user was already editing stays altered, and a saved card stays
    # unaltered.

    def _fill_if_empty(self, field: QLineEdit, value) -> bool:
        """Write a value into a field only while that field is blank, and say
        whether it wrote.

        The half of the gap fill that touches one field. It runs inside the
        caller's programmatic guard, so it never marks the card altered."""
        value = (value or "").strip()
        if not value or field.text().strip():
            return False
        _fill(field, value)
        return True

    def _set_audio_if_empty(self, region: str, url) -> bool:
        """The audio equivalent of _fill_if_empty. A region already holding a
        clip keeps it."""
        url = (url or "").strip()
        if not url:
            return False
        if region == "uk" and not self._audio_uk_url:
            self._audio_uk_url = url
            return True
        if region == "us" and not self._audio_us_url:
            self._audio_us_url = url
            return True
        return False

    def fill_empty_headword(self, word: str) -> bool:
        """Gap fill of the headword from the search phrase.

        The deliberate counterpart of autofill_headword: it runs whatever the
        card's altered state, and it writes only into a blank field, so a card
        already about something keeps its subject."""
        with self._programmatic():
            return self._fill_if_empty(self.headword_input, word)

    def fill_empty_pronunciation(
        self,
        ipa_uk,
        ipa_us,
        audio_uk_url,
        audio_us_url,
        spelling_uk=None,
        spelling_us=None,
        word=None,
    ) -> bool:
        """Gap fill from a Cambridge page: fill every blank grab field and leave
        every filled one alone.

        The deliberate counterpart of autofill_pronunciation. That one is
        passive: it runs only while the card is unaltered and then rewrites the
        whole grab, blanks included, so a later page load can replace an earlier
        one wholesale. This one is asked for by hand, so it runs at any time and
        never overwrites: it is for topping up a half-filled or saved card from
        the page now on screen."""
        with self._programmatic():
            filled = [
                self._fill_if_empty(self.headword_input, word),
                self._fill_if_empty(self.ipa_uk_input, ipa_uk),
                self._fill_if_empty(self.ipa_us_input, ipa_us),
                self._fill_if_empty(self.spelling_uk_input, spelling_uk),
                self._fill_if_empty(self.spelling_us_input, spelling_us),
                self._set_audio_if_empty("uk", audio_uk_url),
                self._set_audio_if_empty("us", audio_us_url),
            ]
        self._update_play_buttons()
        return any(filled)

    def fill_empty_book_example(self, sentence: str, book_tag: str = "") -> bool:
        """Gap fill of the book match sentence into the first sense's first
        example, and of that book's tag with it.

        The deliberate counterpart of autofill_book_example: any altered state,
        but only into a first example that is still blank. A sense row that
        already has an example keeps it, and is not tagged with the book
        either, because nothing was taken from it."""
        sentence = (sentence or "").strip()
        if not sentence:
            return False
        row = self._rows()[0]
        if row.first_example_text():
            return False
        with self._programmatic():
            row.set_first_example(sentence)
            self.add_book_tag(book_tag)
        return True

    def set_audio(self, region: str, url: str) -> None:
        """Replace one region's pronunciation clip with one captured from the
        Cambridge page, leaving that region's IPA alone (see set_ipa: the two are
        captured separately, because the block with the notation you want is
        often not the block with the clip you want).

        A deliberate single-field edit, so it marks the card altered and takes
        that one region's clip out of the passive grab's hands; the rest of the
        card still fills from the page."""
        if region == "uk":
            with self._programmatic():
                self._audio_uk_url = url or None
        elif region == "us":
            with self._programmatic():
                self._audio_us_url = url or None
        else:
            return
        self.state.mark_altered(Target.audio(region))
        self._update_play_buttons()

    def set_ipa(self, region: str, ipa: str) -> None:
        """Replace one region's IPA notation with one captured from the Cambridge
        page, leaving that region's audio clip alone. The notation half of
        set_audio; see it for why the card is marked altered."""
        if region == "uk":
            field = self.ipa_uk_input
        elif region == "us":
            field = self.ipa_us_input
        else:
            return
        with self._programmatic():
            field.setText(ipa or "")
        self.state.mark_altered(Target.ipa(region))

    # --- star -----------------------------------------------------------

    def _on_star_toggled(self, checked: bool):
        # The star is printed in the top right corner of the card front, so
        # starring is a change to the printed content like any other.
        self._on_printed_content_edit()
        self.star_button.setIcon(
            self._star_icon_on if checked else self._star_icon_off
        )
        self.star_button.setStyleSheet(
            "background-color: #f0b400;" if checked else ""
        )

    def set_starred(self, starred: bool):
        self.star_button.setChecked(bool(starred))

    def is_starred(self) -> bool:
        return self.star_button.isChecked()

    # --- printed --------------------------------------------------------

    def _on_printed_toggled(self, checked: bool):
        if self._programmatic_depth == 0:
            # Set by hand, so editing the card afterwards does not clear it
            # again (see _on_printed_content_edit). A guarded set (load, reset,
            # the resync in _refresh_saved_list) is not a decision, so it does
            # not count as by hand.
            self.state.mark_printed_flag_altered()
        self._on_user_edit()
        self.printed_button.setIcon(
            self._printed_icon_on if checked else self._printed_icon_off
        )
        self.printed_button.setStyleSheet(
            "background-color: #4a90d9;" if checked else ""
        )

    def set_printed(self, printed: bool):
        self.printed_button.setChecked(bool(printed))

    def is_printed(self) -> bool:
        return self.printed_button.isChecked()

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
        if any(
            field.text().strip() for _spec, field in self._card_field_widgets()
        ):
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
        values = {
            spec.name: spec.to_card(field.text())
            for spec, field in self._card_field_widgets()
        }
        card = Card(
            **values,
            audio_uk_url=self._audio_uk_url,
            audio_us_url=self._audio_us_url,
            senses=senses,
            starred=self.is_starred(),
            printed=self.is_printed(),
            created_at=self.state.loaded_created_at or now,
            updated_at=now,
        )
        if self.state.loaded_card_id:
            card.id = self.state.loaded_card_id
        return card

    # --- saved-list hooks (overridden by subclasses) --------------------

    def _configure_saved_item(self, item, card) -> None:
        """Set an item's checkable flags / check state / decoration. Base
        default: a plain, non-checkable row (no selection semantics)."""
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)

    def _on_saved_item_changed(self, item) -> None:
        """React to a row's check-state change. Base default: nothing."""
        return None

    def _saved_controls_widget(self):
        """Return a widget to place under the saved list, or None."""
        return None

    def _on_saved_list_refreshed(self) -> None:
        """Called at the end of _refresh_saved_list. Base default: nothing."""
        return None

    def _loaded_row_is_checkable(self) -> bool:
        """Whether the currently-loaded card's own row may be checked. Base
        default False (the dock uses the checkbox for linking, and a card cannot
        link to itself)."""
        return False

    def _saved_item_changed_dispatch(self, item) -> None:
        if getattr(self, "_suppress_item_changed", False):
            return
        self._checkbox_click = True
        self._on_saved_item_changed(item)

    def _clear_checkbox_click_guard(self) -> None:
        # Called after a key press on the list. A keyboard Space toggles the
        # checkbox (setting the guard) but produces no co-firing mouse click for
        # the guard to suppress, so clear it here or it would swallow the next
        # real text click.
        self._checkbox_click = False

    # --- link persistence seam (overridden by subclasses) ----------------

    def _links_to_persist(self, card) -> list:
        """Links to write alongside the card on Save. Base default: none."""
        return []

    def _after_save(self, card) -> None:
        """Called right after a successful save, before the UI refresh. Base
        default: nothing."""
        return None

    def save_card(self):
        card = self.build_card()
        if card is None:
            self.save_rejected.emit("Cannot save flashcard: headword is empty")
            return
        self.store.save_card_with_links(card, self._links_to_persist(card))
        headword = card.headword
        # Save keeps the card loaded rather than clearing the editor: the just
        # saved card becomes the loaded card in unaltered editing mode, so its
        # fields stay put and a brand-new card turns into an existing one without
        # any wipe.
        self.state.to_editing(card.id, card.created_at or None)
        self._after_save(card)
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

    def focus_own_notation(self) -> None:
        """Put the caret in Own notation with any existing note selected, so
        typing replaces it. Same behaviour as Ctrl+L on the dictionary search
        box (see dictionary_panel.focus_search)."""
        self.own_notation_input.setFocus()
        self.own_notation_input.selectAll()

    def new_card(self, force: bool = False) -> bool:
        """Clear the editor for a fresh card. Returns False if the user declined
        to discard unsaved content. force skips the confirmation. The headword is
        not seeded here: the caller seeds it from the search box and re-grabs the
        Cambridge page, which replaces it (see main_window.new_flashcard /
        on_pronunciation_grabbed)."""
        if not force and self.state.altered and not self._confirm_discard():
            return False
        self._reset_editor()
        return True

    def prepare_for_new_search(self) -> None:
        """Open this search's round of passive fills, and clear the editor for
        it, so the new word replaces the previous card completely (senses,
        examples, star, own notation, staged links, loaded-card id), not just the
        grab fields.

        Only when the card is unaltered: a freshly saved card, a card loaded for
        viewing, one holding only a previous passive auto-fill, or an empty card
        are all reset to a fresh unsaved new card. An altered card is left
        completely untouched, with no discard prompt (a search is passive, so it
        never nags), and its round stays shut, so this search's late-arriving
        pages write nothing into it either; that is why this calls _reset_editor
        directly rather than new_card/clear_editor, which would prompt.

        Called once per search from main_window.on_word_searched, synchronously
        before the pronunciation grab and the book-sentence fill. Because the
        round is opened here and NOT inside the repeating page-load handlers, it
        is the state of the card at the moment of the search that decides, typing
        into the fresh card afterwards closes only the fields typed in, and the
        book example filled just after survives later same-search Cambridge
        reloads.
        """
        if not self.state.begin_autofill():
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
            for _spec, field in self._card_field_widgets():
                field.clear()
            self._audio_uk_url = None
            self._audio_us_url = None
            self._update_play_buttons()
            self.star_button.setChecked(False)
            self.printed_button.setChecked(False)
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
        # clear() discards the list's scroll offset, so a rebuild would jump the
        # view back to the top. Loading a card rebuilds the list only to move the
        # loaded-row markers (dot/bold/tint), so clicking a card partway down
        # would otherwise scroll the list out from under the click. Save and
        # restore the scroll position around the rebuild, clamped to the new
        # range.
        scrollbar = self.saved_list.verticalScrollBar()
        scroll_value = scrollbar.value()
        # The rebuild also drops the list's current row (the native keyboard
        # cursor the arrow keys move from). Remember it, and note the loaded
        # card's new row, so the cursor can be restored afterwards: arrowing then
        # continues from the loaded card, not from the top.
        previous_row = self.saved_list.currentRow()
        loaded_row = -1
        self._suppress_item_changed = True
        try:
            self.saved_list.clear()
            for index, card in enumerate(self.store.cards):
                label = card.headword
                item = QListWidgetItem(label)
                item.setData(Qt.ItemDataRole.UserRole, card.id)
                item.setData(self._PRINTED_ROLE, bool(card.printed))
                item.setData(self._STARRED_ROLE, bool(card.starred))
                # The filter box matches tags, but the row label stays the
                # headword alone, so the tooltip is what explains why a
                # tag-filtered row is on show. Joined once here rather than per
                # keystroke; stored tags are already lowercase.
                item.setData(self._TAGS_ROLE, " ".join(card.tags))
                if card.tags:
                    item.setToolTip(", ".join(card.tags))
                if card.id == self.state.loaded_card_id:
                    loaded_row = index
                    item.setIcon(self._loaded_marker_icon())
                    font = item.font()
                    font.setBold(True)
                    item.setFont(font)
                    item.setBackground(QBrush(QColor("#e8f0fe")))
                    if self._loaded_row_is_checkable():
                        self._configure_saved_item(item, card)
                    else:
                        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
                else:
                    self._configure_saved_item(item, card)
                self.saved_list.addItem(item)
            self._apply_saved_filter()
        finally:
            self._suppress_item_changed = False
        # Restore the pre-rebuild scroll position. The scrollbar range is not
        # recomputed until the view lays its items out, so right after re-adding
        # the rows maximum() can still report a stale (smaller) value; clamping
        # against that would land the view short of where it was. Force the item
        # layout first so maximum() is accurate, then restore (clamped in case the
        # list genuinely shrank, e.g. a card was deleted).
        self.saved_list.doItemsLayout()
        scrollbar.setValue(min(scroll_value, scrollbar.maximum()))
        # Restore the native keyboard cursor: onto the loaded card if there is
        # one (so its blue-marked row and the arrow-key cursor coincide),
        # otherwise back onto the previously focused row (clamped, in case the
        # list shrank). Setting the current row does not load a card (it fires no
        # click), so this only moves the keyboard focus. Guarded so no item-change
        # handler treats it as a user edit.
        count = self.saved_list.count()
        target_row = loaded_row if loaded_row >= 0 else previous_row
        if count and target_row >= 0:
            self._suppress_item_changed = True
            try:
                self.saved_list.setCurrentRow(min(target_row, count - 1))
            finally:
                self._suppress_item_changed = False
        self._on_saved_list_refreshed()
        # Keep the loaded card's printed toggle in step with the store when the
        # store changed under us (bulk toggle, auto-flag) and the editor has no
        # unsaved edits. Programmatic, so it does not itself mark the card altered.
        if self.state.loaded_card_id and not self.state.altered:
            stored = next(
                (c for c in self.store.cards if c.id == self.state.loaded_card_id),
                None,
            )
            if stored is not None and stored.printed != self.is_printed():
                with self._programmatic():
                    self.set_printed(stored.printed)

    def _apply_saved_filter(self, text: str = "") -> None:
        needle = self.saved_filter.text().strip().lower()
        for i in range(self.saved_list.count()):
            item = self.saved_list.item(i)
            tags = item.data(self._TAGS_ROLE) or ""
            item.setHidden(
                bool(needle)
                and needle not in item.text().lower()
                and needle not in tags
            )

    def _on_saved_clicked(self, item):
        if self._checkbox_click:
            self._checkbox_click = False
            return
        self._load_item(item)

    def _on_saved_activated(self, item):
        # Enter/Return on the keyboard-focused row. Unlike a click, no checkbox
        # change co-fires here, so load unconditionally (no _checkbox_click
        # guard).
        self._load_item(item)

    def _load_item(self, item) -> None:
        card_id = item.data(Qt.ItemDataRole.UserRole)
        card = next((c for c in self.store.cards if c.id == card_id), None)
        if card is not None:
            self.load_card(card)

    def _show_saved_context_menu(self, position) -> None:
        """Right-click menu for a saved-list row. Delete is the only entry:
        loading a card and ticking it are each one click or one key press away,
        so repeating them here would only pad the menu. A right-click on empty
        space below the rows opens nothing."""
        item = self.saved_list.itemAt(position)
        if item is None:
            return
        menu = QMenu(self)
        delete_action = menu.addAction("Delete")
        action = menu.exec(self.saved_list.mapToGlobal(position))
        if action == delete_action:
            self.delete_saved_card(item)

    def delete_saved_card(self, item) -> bool:
        """Delete the card behind a saved-list row, after confirming. Returns
        True when the card was removed."""
        card_id = item.data(Qt.ItemDataRole.UserRole)
        card = next((c for c in self.store.cards if c.id == card_id), None)
        if card is None:
            return False
        if not self._confirm_delete(card):
            return False
        # The card is going, so whatever is in the editor for it goes too.
        # Deliberately not through clear_editor: that asks whether to discard
        # unsaved edits, which is a pointless question about a card the user has
        # just agreed to delete.
        if self.state.loaded_card_id == card_id:
            self._reset_editor()
        self.store.delete_card(card_id)
        # The store's own signal refreshes the list wherever it is wired up, but
        # the editor must not depend on its owner having done that.
        self._refresh_saved_list()
        return True

    def _confirm_delete(self, card: Card) -> bool:
        """Ask before deleting. A card is a lot of work and there is no undo, so
        unlike the history list this never deletes straight off a right-click.
        The links are named because they go with the card and are not otherwise
        visible from the list."""
        links = len(self.store.links_for(card.id))
        if links:
            detail = f" and its {links} link" + ("s" if links != 1 else "")
        else:
            detail = ""
        reply = QMessageBox.question(
            self,
            "Delete card",
            f'Delete the card "{card.headword}"{detail}? This cannot be undone.',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        return reply == QMessageBox.StandardButton.Yes

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
            for spec, field in self._card_field_widgets():
                _fill(field, spec.from_card(getattr(card, spec.name)))
            self._audio_uk_url = card.audio_uk_url
            self._audio_us_url = card.audio_us_url
            self._update_play_buttons()
            self.set_starred(card.starred)
            self.set_printed(card.printed)

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
