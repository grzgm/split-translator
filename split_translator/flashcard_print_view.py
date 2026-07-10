"""Right side of the Print window: a web-engine preview of the print sheets plus
its controls. It renders the pure-logic layout HTML, flags overflowing tiles on
screen (never in print), toggles on-screen cut borders, and prints the preview.

The live rendering, the overflow marking and the actual print cannot be unit
tested (they need a live QWebEngineView); they are verified with a runtime
walkthrough. Only construction and the JS-builder strings are covered by tests."""

from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtWebEngineWidgets import QWebEngineView

from .flashcard_print_layout import PAGE, render_html
from .flashcards import Card


class PrintView(QWidget):
    """Preview + Print button + Show cut borders toggle."""

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

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        controls = QHBoxLayout()
        self.borders_checkbox = QCheckBox("Show cut borders")
        self.borders_checkbox.setToolTip(
            "Draw thin borders around each card on screen to help cutting. "
            "They are not printed."
        )
        self.borders_checkbox.toggled.connect(self._on_borders_toggled)
        self.print_button = QPushButton("Print")
        self.print_button.clicked.connect(self.print_cards)
        controls.addWidget(self.borders_checkbox)
        controls.addStretch()
        controls.addWidget(self.print_button)
        outer.addLayout(controls)

        self.view = QWebEngineView()
        self.view.loadFinished.connect(self._on_load_finished)
        outer.addWidget(self.view, stretch=1)

    def show_borders(self) -> bool:
        return self.borders_checkbox.isChecked()

    def set_cards(self, cards: list[Card]) -> None:
        self._cards = list(cards)
        self.view.setHtml(render_html(self._cards, PAGE))

    def _on_load_finished(self, ok: bool) -> None:
        if not ok:
            return
        page = self.view.page()
        page.runJavaScript(self._borders_js(self.show_borders()))
        page.runJavaScript(self._OVERFLOW_JS)

    def _borders_js(self, on: bool) -> str:
        action = "add" if on else "remove"
        return f"document.body.classList.{action}('show-borders');"

    def _on_borders_toggled(self, checked: bool) -> None:
        self.view.page().runJavaScript(self._borders_js(checked))

    def print_cards(self) -> None:
        from PySide6.QtPrintSupport import QPrintDialog, QPrinter

        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        dialog = QPrintDialog(printer, self)
        if dialog.exec() != QPrintDialog.DialogCode.Accepted:
            return
        # QWebEngineView.print is asynchronous; keep a reference so the printer is
        # not collected before the job finishes.
        self._active_printer = printer
        self.view.print(printer)
