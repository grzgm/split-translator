"""Right side of the Print window: the print configuration at the top, the
examples of the card loaded in the editor below it, and the Print button at the
foot. The window has no separate control bar; everything that used to sit above
the preview lives here instead.

A card starts in auto mode, where the ticks show the default the browser's fit
measurement produced (see PrintView.auto_fit_measured). Touching any tick
promotes the card to manual, taking the ticks currently on screen as the
starting point, so the hand-picked set begins from the real default rather than
from nothing. "Reset to auto" hands the card back to the fit.

The sidebar holds the PrintChoices object (a plain data object, like a store)
and no other panel: the print window is what connects it to the preview."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from .flashcard_print_choices import MANUAL, PrintChoices, auto_pairs
from .flashcard_print_layout import PAGE
from .flashcards import Card


class PrintSidebar(QWidget):
    """The print configuration, the examples list for the loaded card, and the
    Print button."""

    # The card id whose tick set just changed (by a tick or by a reset).
    choice_changed = Signal(str)
    borders_toggled = Signal(bool)
    cut_lines_toggled = Signal(bool)
    blank_headwords_toggled = Signal(bool)
    back_offset_changed = Signal()
    print_requested = Signal()

    def __init__(self, choices: PrintChoices, parent=None):
        super().__init__(parent)
        self.choices = choices
        self._card: Card | None = None
        self._in_selection = False
        # One checkbox per (sense index, example index) on the shown card.
        self._boxes: dict[tuple[int, int], QCheckBox] = {}
        # The last fit measurement per card id. Kept for every card, not just
        # the shown one, because the measurement for a card arrives whenever the
        # preview reloads, which is rarely the moment that card is shown.
        self._measured: dict[str, list[tuple[int, int]]] = {}
        # Set while the ticks are being written programmatically, so those
        # changes are not read as the user hand-picking anything.
        self._suppress = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)

        outer.addWidget(self._options_widget())

        self.title_label = QLabel("Examples")
        self.title_label.setStyleSheet("font-weight: bold;")
        outer.addWidget(self.title_label)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("color: #55606e;")
        outer.addWidget(self.status_label)

        # The rows live in their own scroll area, so a card with many examples
        # scrolls rather than stretching the whole sidebar.
        self._rows_container = QWidget()
        self._rows_layout = QVBoxLayout(self._rows_container)
        self._rows_layout.setContentsMargins(0, 0, 0, 0)
        self._rows_layout.setSpacing(2)
        self._rows_layout.addStretch()
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setWidget(self._rows_container)
        outer.addWidget(self._scroll, stretch=1)

        self.reset_button = QPushButton("Reset to auto")
        self.reset_button.setToolTip(
            "Hand this card back to the automatic choice, which fills the card "
            "with as many examples as physically fit"
        )
        self.reset_button.clicked.connect(self._on_reset)
        outer.addWidget(self.reset_button)

        self.print_button = QPushButton("Print")
        self.print_button.clicked.connect(self.print_requested)
        outer.addWidget(self.print_button)

        self.set_card(None, False)

    def _options_widget(self) -> QWidget:
        """The print configuration, at a fixed spot at the top of the sidebar so
        it stays visible however many examples a card has."""
        widget = QWidget()
        box = QVBoxLayout(widget)
        box.setContentsMargins(0, 0, 0, 0)

        heading = QLabel("Options")
        heading.setStyleSheet("font-weight: bold;")
        box.addWidget(heading)

        self.borders_checkbox = QCheckBox("Show cut borders")
        self.borders_checkbox.setToolTip(
            "Draw thin borders around each card on screen to help cutting. "
            "They are not printed."
        )
        self.borders_checkbox.toggled.connect(self.borders_toggled)
        box.addWidget(self.borders_checkbox)

        # Prints a hairline between the cards so they are easy to cut apart. On
        # by default. The line is drawn with an outline, so it never shifts the
        # card content, and it appears only in the printed output.
        self.cut_lines_checkbox = QCheckBox("Print cut lines")
        self.cut_lines_checkbox.setToolTip(
            "Print a thin cut guide between the cards to make them easy to cut "
            "out. Only affects the printed output, not the on-screen preview."
        )
        self.cut_lines_checkbox.setChecked(True)
        self.cut_lines_checkbox.toggled.connect(self.cut_lines_toggled)
        box.addWidget(self.cut_lines_checkbox)

        self.blank_headwords_checkbox = QCheckBox("Blank out headwords")
        self.blank_headwords_checkbox.setToolTip(
            "Hide headword occurrences in the English definition, shown as a "
            "blank, so the printed card is not a spoiler. Unticked prints the "
            "stored {{word}} token."
        )
        self.blank_headwords_checkbox.setChecked(True)
        self.blank_headwords_checkbox.toggled.connect(self.blank_headwords_toggled)
        box.addWidget(self.blank_headwords_checkbox)

        # Duplex registration nudge: shifts the printed back side so it lands on
        # its front despite the printer's mechanical two-sided offset. Only
        # affects the printed output, not the on-screen preview.
        offsets = QFormLayout()
        self.back_offset_spin = QDoubleSpinBox()
        self.back_offset_spin.setRange(-15.0, 15.0)
        self.back_offset_spin.setSingleStep(0.5)
        self.back_offset_spin.setValue(PAGE.back_offset_mm)
        self.back_offset_spin.setToolTip(
            "Raise the printed back side by this many mm so it lines up with its "
            "front (compensates the printer's vertical two-sided registration). "
            "Only affects the printed output, not the preview."
        )
        self.back_offset_spin.valueChanged.connect(
            lambda _value: self.back_offset_changed.emit()
        )
        offsets.addRow("Back offset up (mm)", self.back_offset_spin)

        self.back_offset_x_spin = QDoubleSpinBox()
        self.back_offset_x_spin.setRange(-15.0, 15.0)
        self.back_offset_x_spin.setSingleStep(0.5)
        self.back_offset_x_spin.setValue(PAGE.back_offset_x_mm)
        self.back_offset_x_spin.setToolTip(
            "Shift the printed back side right by this many mm (compensates the "
            "printer's horizontal two-sided registration). Only affects the "
            "printed output, not the preview."
        )
        self.back_offset_x_spin.valueChanged.connect(
            lambda _value: self.back_offset_changed.emit()
        )
        offsets.addRow("right (mm)", self.back_offset_x_spin)
        box.addLayout(offsets)

        return widget

    def show_borders(self) -> bool:
        return self.borders_checkbox.isChecked()

    def print_cut_lines(self) -> bool:
        return self.cut_lines_checkbox.isChecked()

    def blank_headwords(self) -> bool:
        return self.blank_headwords_checkbox.isChecked()

    def back_offset(self) -> float:
        return self.back_offset_spin.value()

    def back_offset_x(self) -> float:
        return self.back_offset_x_spin.value()

    # --- reads ----------------------------------------------------------

    def card_id(self) -> str | None:
        return self._card.id if self._card is not None else None

    def ticked_pairs(self) -> list[tuple[int, int]]:
        """The ticked (sense, example) pairs, in reading order."""
        return [pair for pair in sorted(self._boxes) if self._boxes[pair].isChecked()]

    # --- writes ---------------------------------------------------------

    def set_card(self, card: Card | None, in_selection: bool) -> None:
        """Show this card's examples. None shows the placeholder."""
        self._card = card
        self._in_selection = in_selection
        self._rebuild()

    def set_auto_fit(self, fit_map: dict) -> None:
        """Take in a fit measurement for any number of cards. The sidebar picks
        out the card it is showing and ignores the rest, so the window can hand
        the whole map straight over."""
        self._measured.update(fit_map)
        card_id = self.card_id()
        if card_id is None or card_id not in fit_map:
            return
        if self.choices.mode_of(card_id) == MANUAL:
            # A hand-picked set is not a measurement's business.
            return
        self._apply_ticks()

    # --- building -------------------------------------------------------

    def _rebuild(self) -> None:
        self._clear_rows()
        card = self._card
        if card is None:
            self.title_label.setText("Examples")
            self.status_label.setText("No card loaded. Click a card to load it.")
            self.reset_button.setEnabled(False)
            return

        self.title_label.setText(f"Examples: {card.headword}")
        for sense_index, sense in enumerate(card.senses or []):
            examples = sense.examples or []
            if not examples:
                continue
            self._rows_layout.insertWidget(
                self._rows_layout.count() - 1, self._sense_header(sense)
            )
            for example_index, text in enumerate(examples):
                box = QCheckBox(text)
                box.setToolTip(text)
                box.toggled.connect(self._on_box_toggled)
                self._boxes[(sense_index, example_index)] = box
                self._rows_layout.insertWidget(self._rows_layout.count() - 1, box)

        self._apply_ticks()
        self._apply_status()

    def _sense_header(self, sense) -> QLabel:
        """A per-sense heading, so it is clear which sense an example belongs to
        and why the automatic fill spreads them across the senses."""
        parts = []
        if sense.pos:
            parts.append(f"{{{sense.pos}}}")
        if sense.polish:
            parts.append(sense.polish)
        label = QLabel(" ".join(parts) if parts else "(sense)")
        label.setStyleSheet("color: #55606e; margin-top: 4px;")
        return label

    def _clear_rows(self) -> None:
        self._boxes = {}
        # Everything except the trailing stretch.
        while self._rows_layout.count() > 1:
            item = self._rows_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

    def _default_pairs(self) -> list[tuple[int, int]]:
        """The ticks to show for the card on screen.

        A manual card shows its chosen set. An auto card shows its measurement
        when there is one, and otherwise every example: a card that is not in
        the print selection never reaches the preview to be measured, and
        showing it fully ticked lets it be tuned before it is added."""
        card = self._card
        if card is None:
            return []
        chosen = self.choices.chosen_for(card.id)
        if chosen is not None:
            return sorted(chosen)
        measured = self._measured.get(card.id)
        if measured is not None:
            return sorted(measured)
        return auto_pairs(card)

    def _apply_ticks(self) -> None:
        wanted = set(self._default_pairs())
        self._suppress = True
        try:
            for pair, box in self._boxes.items():
                box.setChecked(pair in wanted)
        finally:
            self._suppress = False

    def _apply_status(self) -> None:
        card = self._card
        if card is None:
            return
        manual = self.choices.mode_of(card.id) == MANUAL
        self.reset_button.setEnabled(manual)
        if manual:
            self.status_label.setText(
                "Hand-picked. Exactly the ticked examples print, and a card "
                "that overruns is outlined in red."
            )
        elif not self._in_selection:
            self.status_label.setText(
                "Not in the print selection, so there is no measured default "
                "yet. Tick this card for print to see the automatic choice."
            )
        else:
            self.status_label.setText(
                "Automatic: as many examples as physically fit, spread across "
                "the senses."
            )

    # --- user actions ---------------------------------------------------

    def _on_box_toggled(self, _checked: bool) -> None:
        if self._suppress or self._card is None:
            return
        # Whatever is ticked now is the hand-picked set. This one path covers
        # both promoting an auto card (the ticks on screen are the measured
        # default, so the set starts from it) and editing a manual one.
        self.choices.set_manual(self._card, self.ticked_pairs())
        self._apply_status()
        self.choice_changed.emit(self._card.id)

    def _on_reset(self) -> None:
        if self._card is None:
            return
        card_id = self._card.id
        self.choices.reset(card_id)
        self._apply_ticks()
        self._apply_status()
        self.choice_changed.emit(card_id)
