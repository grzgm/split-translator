"""Right side of the Print window: a web-engine preview of the print sheets plus
its controls. It renders the pure-logic layout HTML, flags overflowing tiles on
screen (never in print), toggles on-screen cut borders, and prints the preview.

The live rendering, the overflow marking and the actual print cannot be unit
tested (they need a live QWebEngineView); they are verified with a runtime
walkthrough. Only construction and the JS-builder strings are covered by tests."""

from dataclasses import replace

from PySide6.QtCore import QMarginsF, Signal
from PySide6.QtGui import QPageLayout
from PySide6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtWebEngineWidgets import QWebEngineView

from .flashcard_print_layout import PAGE, render_html
from .flashcards import Card


class PrintView(QWidget):
    """Preview + Print button + Show cut borders (screen) and Print cut lines
    (print) toggles."""

    toggle_printed_requested = Signal()
    cards_printed = Signal(list)

    # Fits each front tile's examples to the tile, then puts the survivors back
    # into sense order. Runs after each load, before _OVERFLOW_JS.
    #
    # Only the browser knows how tall a sentence renders once it has wrapped, so
    # this cannot be decided when the HTML is built. The layout emits every
    # example interleaved across the senses (the first of each sense, then the
    # second of each; see example_fill_order) and tags each with the sense it came
    # from. Filling the tile in that document order therefore gives every sense an
    # example before any sense gets a second one.
    #
    # The example that first overflows is kept, not dropped: it fills the tile to
    # its edge and its clipped last line reads as "there is more here", which is
    # how the rest of an overlong tile already behaves. That does leave the tile
    # genuinely overflowing, so _OVERFLOW_JS then flags it on screen, which is a
    # true statement: the card holds more examples than it can show.
    #
    # Reordering cannot change the total height (same boxes, same widths), so the
    # set that fitted still fits after it is regrouped.
    _FIT_EXAMPLES_JS = """
(function () {
  var lists = document.querySelectorAll('.tile--front .example-list');
  for (var i = 0; i < lists.length; i++) {
    var list = lists[i];
    var tile = list.closest('.tile');
    if (!tile) { continue; }
    var items = [];
    while (list.firstChild) {
      items.push(list.removeChild(list.firstChild));
    }
    var kept = [];
    for (var k = 0; k < items.length; k++) {
      list.appendChild(items[k]);
      kept.push(items[k]);
      if (tile.scrollHeight > tile.clientHeight) { break; }
    }
    // Stable, so the examples of one sense keep their own order.
    kept.sort(function (a, b) {
      return Number(a.dataset.sense) - Number(b.dataset.sense);
    });
    for (var k = 0; k < kept.length; k++) {
      list.appendChild(kept[k]);
    }
  }
})();
"""

    # Marks every tile whose content overflows its fixed box. Runs after each
    # load; toggles a class in-page, so no value returns to Python.
    _OVERFLOW_JS = """
(function () {
  var tiles = document.querySelectorAll('.tile');
  for (var i = 0; i < tiles.length; i++) {
    var t = tiles[i];
    var over = t.scrollHeight > t.clientHeight || t.scrollWidth > t.clientWidth;
    if (over) { t.classList.add('is-overflow'); }
    else { t.classList.remove('is-overflow'); }
  }
})();
"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cards: list[Card] = []
        self._printing_ids: list[str] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        controls = QHBoxLayout()
        self.borders_checkbox = QCheckBox("Show cut borders")
        self.borders_checkbox.setToolTip(
            "Draw thin borders around each card on screen to help cutting. "
            "They are not printed."
        )
        self.borders_checkbox.toggled.connect(self._on_borders_toggled)
        # Prints a hairline between the cards so they are easy to cut apart. On by
        # default. The line is drawn with an outline, so it never shifts the card
        # content, and it appears only in the printed output.
        self.cut_lines_checkbox = QCheckBox("Print cut lines")
        self.cut_lines_checkbox.setToolTip(
            "Print a thin cut guide between the cards to make them easy to cut "
            "out. Only affects the printed output, not the on-screen preview."
        )
        self.cut_lines_checkbox.setChecked(True)
        self.cut_lines_checkbox.toggled.connect(self._on_cut_lines_toggled)
        # Duplex registration nudge: raises the printed back side by this many mm
        # so it lands on its front despite the printer's mechanical two-sided
        # offset. Only affects the printed output, not the on-screen preview.
        back_offset_label = QLabel("Back offset up (mm)")
        self.back_offset_spin = QDoubleSpinBox()
        self.back_offset_spin.setRange(-15.0, 15.0)
        self.back_offset_spin.setSingleStep(0.5)
        self.back_offset_spin.setValue(PAGE.back_offset_mm)
        self.back_offset_spin.setToolTip(
            "Raise the printed back side by this many mm so it lines up with its "
            "front (compensates the printer's vertical two-sided registration). "
            "Only affects the printed output, not the preview."
        )
        self.back_offset_spin.valueChanged.connect(self._on_back_offset_changed)
        back_offset_x_label = QLabel("right (mm)")
        self.back_offset_x_spin = QDoubleSpinBox()
        self.back_offset_x_spin.setRange(-15.0, 15.0)
        self.back_offset_x_spin.setSingleStep(0.5)
        self.back_offset_x_spin.setValue(PAGE.back_offset_x_mm)
        self.back_offset_x_spin.setToolTip(
            "Shift the printed back side right by this many mm (compensates the "
            "printer's horizontal two-sided registration). Only affects the "
            "printed output, not the preview."
        )
        self.back_offset_x_spin.valueChanged.connect(self._on_back_offset_changed)
        self.toggle_printed_button = QPushButton("Toggle printed")
        self.toggle_printed_button.setToolTip(
            "Flip the printed flag on the currently selected cards. If they are "
            "all printed, this clears them; otherwise it marks them all printed."
        )
        self.toggle_printed_button.clicked.connect(self.toggle_printed_requested)
        self.print_button = QPushButton("Print")
        self.print_button.clicked.connect(self.print_cards)
        controls.addWidget(self.borders_checkbox)
        controls.addWidget(self.cut_lines_checkbox)
        controls.addWidget(back_offset_label)
        controls.addWidget(self.back_offset_spin)
        controls.addWidget(back_offset_x_label)
        controls.addWidget(self.back_offset_x_spin)
        controls.addWidget(self.toggle_printed_button)
        controls.addStretch()
        controls.addWidget(self.print_button)
        outer.addLayout(controls)

        self.view = QWebEngineView()
        self.view.loadFinished.connect(self._on_load_finished)
        self.view.printFinished.connect(self._on_print_finished)
        self.view.pdfPrintingFinished.connect(self._on_pdf_finished)
        outer.addWidget(self.view, stretch=1)

    def show_borders(self) -> bool:
        return self.borders_checkbox.isChecked()

    def print_cut_lines(self) -> bool:
        return self.cut_lines_checkbox.isChecked()

    def back_offset(self) -> float:
        return self.back_offset_spin.value()

    def back_offset_x(self) -> float:
        return self.back_offset_x_spin.value()

    def _render(self) -> str:
        """Build the print HTML for the current cards and back offsets."""
        page = replace(
            PAGE,
            back_offset_mm=self.back_offset(),
            back_offset_x_mm=self.back_offset_x(),
        )
        return render_html(self._cards, page)

    def set_cards(self, cards: list[Card]) -> None:
        self._cards = list(cards)
        self.view.setHtml(self._render())

    def _on_back_offset_changed(self, _value: float) -> None:
        # The offset only shows in print, so the on-screen preview is unchanged,
        # but re-render so the next Print uses the new value.
        self.view.setHtml(self._render())

    def _on_load_finished(self, ok: bool) -> None:
        if not ok:
            return
        page = self.view.page()
        page.runJavaScript(self._borders_js(self.show_borders()))
        page.runJavaScript(self._cut_lines_js(self.print_cut_lines()))
        # Fit the examples first: it decides what each tile ends up holding, and
        # the overflow flag has to describe the tile as it will actually print.
        page.runJavaScript(self._FIT_EXAMPLES_JS)
        page.runJavaScript(self._OVERFLOW_JS)

    def _borders_js(self, on: bool) -> str:
        action = "add" if on else "remove"
        return f"document.body.classList.{action}('show-borders');"

    def _on_borders_toggled(self, checked: bool) -> None:
        self.view.page().runJavaScript(self._borders_js(checked))

    def _cut_lines_js(self, on: bool) -> str:
        action = "add" if on else "remove"
        return f"document.body.classList.{action}('print-cut-lines');"

    def _on_cut_lines_toggled(self, checked: bool) -> None:
        self.view.page().runJavaScript(self._cut_lines_js(checked))

    def print_cards(self) -> None:
        from PySide6.QtPrintSupport import QPrintDialog, QPrinter

        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        dialog = QPrintDialog(printer, self)
        if dialog.exec() != QPrintDialog.DialogCode.Accepted:
            return
        self._send_to(printer)

    def _send_to(self, printer) -> None:
        """Route the sheets to whatever the dialog settled on.

        "Print to File (PDF)" goes to Chromium's own PDF exporter rather than
        through the printer. QWebEngineView.print paints the page into the
        QPrinter, which flattens it to a bitmap: that PDF is a picture of the
        sheet, with no selectable or searchable text, and is hundreds of times
        larger. printToPdf keeps the text as text. Both lay the page out from the
        same CSS, so the cards come out the same physical size either way.

        A real printer still goes through QPrinter. Rasterising costs nothing
        there (it is ink either way), and the QPrinter is what carries the chosen
        printer, tray and copy count."""
        from PySide6.QtPrintSupport import QPrinter

        self._capture_printing_ids()

        if printer.outputFormat() == QPrinter.OutputFormat.PdfFormat:
            self._export_pdf(printer)
            return

        # QWebEngineView.print is asynchronous; keep a reference so the printer is
        # not collected before the job finishes.
        self._active_printer = printer
        self.view.print(printer)

    def _capture_printing_ids(self) -> None:
        """Remember which cards this print job covers. The preview shows exactly
        the selected cards, so their ids are the cards to flag on success."""
        self._printing_ids = [c.id for c in self._cards]

    def _on_print_finished(self, success: bool) -> None:
        self._emit_printed_if(success)

    def _on_pdf_finished(self, _path: str, success: bool) -> None:
        self._emit_printed_if(success)

    def _emit_printed_if(self, success: bool) -> None:
        ids = self._printing_ids
        self._printing_ids = []
        if success and ids:
            self.cards_printed.emit(ids)

    def _export_pdf(self, printer) -> None:
        """Write the sheets to the chosen PDF file with real, selectable text."""
        path = printer.outputFileName()
        if not path:
            return
        # Take the paper size and orientation the dialog settled on, but no
        # margins: the sheet's own CSS already positions everything on the page,
        # so a margin here would inset it a second time and shift every card.
        # FullPageMode is what allows a zero margin at all; the default mode
        # silently clamps it up to the device's minimum and the cards would land
        # off their cut lines.
        layout = printer.pageLayout()
        layout.setUnits(QPageLayout.Unit.Millimeter)
        layout.setMode(QPageLayout.Mode.FullPageMode)
        layout.setMargins(QMarginsF(0, 0, 0, 0))
        self.view.page().printToPdf(path, layout)
