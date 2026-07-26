"""Middle of the Print window: a web-engine preview of the print sheets. It
renders the pure-logic layout HTML, flags overflowing tiles on screen (never in
print), and prints the preview. Its render inputs (cut borders, cut lines,
headword blanking, back offsets) are plain state, set by the window from the
controls that live in the right sidebar.

The live rendering, the overflow marking and the actual print cannot be unit
tested (they need a live QWebEngineView); they are verified with a runtime
walkthrough. Only construction and the JS-builder strings are covered by tests."""

import json
from dataclasses import replace

from PySide6.QtCore import QFile, QIODevice, QMarginsF, QTimer, Signal
from PySide6.QtGui import QPageLayout
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWidgets import QVBoxLayout, QWidget
from PySide6.QtWebEngineWidgets import QWebEngineView

from .flashcard_print_layout import PAGE, render_body, render_html, _fmt_mm
from .flashcards import Card
from .print_tile_bridge import PrintTileBridge


def _qwebchannel_js() -> str:
    """Read Qt's bundled qwebchannel.js client from the resource system."""
    f = QFile(":/qtwebchannel/qwebchannel.js")
    if not f.open(QIODevice.OpenModeFlag.ReadOnly):
        return ""
    try:
        return bytes(f.readAll().data()).decode("utf-8")
    finally:
        f.close()


class PrintView(QWidget):
    """The print preview: a web view and nothing else. Its render inputs are
    plain state with setters the window calls from the sidebar's controls."""

    cards_printed = Signal(list)
    # The examples the automatic fit kept, as {card id: [(sense, example), ...]},
    # emitted after each load. Only the browser can measure a wrapped sentence,
    # so this is the only way the sidebar can show the real default.
    auto_fit_measured = Signal(dict)
    # The card id of a clicked preview tile. The window turns it into a load.
    card_clicked = Signal(str)

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
    #
    # A list the user hand-picked carries data-fit="manual" and is skipped
    # entirely: the chosen set is what prints, even when it overruns the tile.
    # _OVERFLOW_JS still runs over it, so an overrun is flagged in red.
    _FIT_EXAMPLES_JS = """
(function () {
  var fit = {};
  var lists = document.querySelectorAll(
    '.tile--front .example-list:not([data-fit="manual"])'
  );
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
    var pairs = [];
    for (var k = 0; k < kept.length; k++) {
      list.appendChild(kept[k]);
      pairs.push([Number(kept[k].dataset.sense), Number(kept[k].dataset.example)]);
    }
    var cardId = tile.getAttribute('data-card-id');
    if (cardId) { fit[cardId] = pairs; }
  }
  window.__stFit = fit;
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

    # Injected after each load. Reports a clicked tile's card id over the
    # channel. __CHANNEL_JS__ is replaced with the bundled qwebchannel.js client
    # using str.replace, not format, because that client text is full of braces.
    #
    # Every setHtml builds a fresh document, so re-attaching the listener on each
    # load is correct rather than duplicative. Both the front and the back tile
    # carry data-card-id, so either side of a card loads it; the padding tiles
    # that fill out a part-used sheet carry none and are inert.
    _TILE_CLICK_JS = """
(function () {
    __CHANNEL_JS__

    document.addEventListener('click', function (ev) {
        var target = ev.target;
        if (!target || !target.closest) { return; }
        var tile = target.closest('.tile[data-card-id]');
        if (!tile) { return; }
        if (window.printTileBridge) {
            window.printTileBridge.clicked(tile.getAttribute('data-card-id'));
        }
    });

    new QWebChannel(qt.webChannelTransport, function (channel) {
        window.printTileBridge = channel.objects.printTileBridge;
    });
})();
"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cards: list[Card] = []
        self._choices: dict = {}
        self._printing_ids: list[str] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        # The render inputs are plain state, set by the window from the sidebar
        # controls. Keeping them here rather than reading another widget is what
        # lets the render path be tested without building any control.
        self._show_borders = False
        self._print_cut_lines = True
        self._blank_headwords = True
        self._back_offset_mm = PAGE.back_offset_mm
        self._back_offset_x_mm = PAGE.back_offset_x_mm

        self.view = QWebEngineView()
        self.view.loadFinished.connect(self._on_load_finished)
        self.view.printFinished.connect(self._on_print_finished)
        self.view.pdfPrintingFinished.connect(self._on_pdf_finished)
        outer.addWidget(self.view, stretch=1)

        self._bridge = PrintTileBridge(self)
        self._bridge.tile_clicked.connect(self.card_clicked)
        self._channel = QWebChannel(self)
        self._channel.registerObject("printTileBridge", self._bridge)
        self.view.page().setWebChannel(self._channel)

        # Where the preview was scrolled to when the last reload started, so the
        # reloaded page can be put back there (see _reload_preview). Starts at
        # the top, which is where a fresh page loads anyway.
        self._pending_scroll = (0.0, 0.0)

        # False until a document exists to update in place. The first refresh
        # loads a whole page; every one after it swaps the body alone, which is
        # what keeps the preview from blinking. A failed load leaves this False,
        # so the next refresh loads a full page again rather than running a body
        # swap against a document that is not there.
        self._document_loaded = False

        # Coalesce rapid preview rebuilds (a burst of selection ticks, a content
        # change) into a single reload. Without this each tick reloads the whole
        # web view, which is the bulk of the perceived lag. A short window is
        # imperceptible yet collapses a burst into one setHtml.
        self._render_timer = QTimer(self)
        self._render_timer.setSingleShot(True)
        self._render_timer.setInterval(150)
        self._render_timer.timeout.connect(self._reload_preview)

    def show_borders(self) -> bool:
        return self._show_borders

    def print_cut_lines(self) -> bool:
        return self._print_cut_lines

    def blank_headwords(self) -> bool:
        return self._blank_headwords

    def back_offset(self) -> float:
        return self._back_offset_mm

    def back_offset_x(self) -> float:
        return self._back_offset_x_mm

    def set_show_borders(self, on: bool) -> None:
        # A body class, so it needs no reload.
        self._show_borders = bool(on)
        self.view.page().runJavaScript(self._borders_js(self._show_borders))

    def set_print_cut_lines(self, on: bool) -> None:
        # A body class, so it needs no reload.
        self._print_cut_lines = bool(on)
        self.view.page().runJavaScript(self._cut_lines_js(self._print_cut_lines))

    def set_blank_headwords(self, on: bool) -> None:
        # This changes the rendered text (blank against token), not just a CSS
        # class, so rebuild the preview (debounced like any other content
        # change). What is shown is what prints.
        self._blank_headwords = bool(on)
        self._schedule_reload()

    def set_back_offsets(self, up_mm: float, right_mm: float) -> None:
        # The offset only shows in print (a CSS transform on the back sheet), so
        # update the live CSS variables in place rather than reloading the whole
        # preview. The print job reads the current CSSOM, so the next Print picks
        # up the new value with no re-render.
        self._back_offset_mm = float(up_mm)
        self._back_offset_x_mm = float(right_mm)
        self.view.page().runJavaScript(self._back_offset_js())

    def _page_spec(self):
        return replace(
            PAGE,
            back_offset_mm=self.back_offset(),
            back_offset_x_mm=self.back_offset_x(),
        )

    def _render(self) -> str:
        """Build the whole print document for the current cards, offsets and
        toggles. Used for the first load; later updates go through
        _render_body."""
        return render_html(
            self._cards,
            self._page_spec(),
            blank_headwords=self._blank_headwords,
            choices=self._choices,
        )

    def _render_body(self) -> str:
        """Build just the sheets, for swapping into the live document."""
        return render_body(
            self._cards,
            self._page_spec(),
            blank_headwords=self._blank_headwords,
            choices=self._choices,
        )

    def set_cards(self, cards: list[Card]) -> None:
        # Update the card list synchronously (print and id capture read it), but
        # debounce the heavy web reload so a burst of changes reloads once.
        self._cards = list(cards)
        self._schedule_reload()

    def set_choices(self, choices: dict) -> None:
        """Replace the hand-picked example sets, keyed by card id. This changes
        the rendered text, so it needs a reload (debounced like any other
        content change)."""
        self._choices = dict(choices)
        self._schedule_reload()

    def _schedule_reload(self) -> None:
        """Restart the debounce timer; a burst of changes collapses into one
        reload once they settle."""
        self._render_timer.start()

    def _reload_preview(self) -> None:
        """Bring the preview up to date with the current cards and choices.

        Once a document exists, only its body is replaced. A setHtml would tear
        the document down and rebuild it, and Chromium paints a blank frame in
        that gap, which is the blink that made every tick of an example
        unpleasant. Nothing in the head depends on the cards (see _styles), so
        rebuilding it bought nothing."""
        if self._document_loaded:
            self.view.page().runJavaScript(
                self._body_swap_script(), self._on_fit_measured
            )
            return
        # First load only. setHtml drops the scroll position, so carry it across
        # in Python; the page it lands in cannot know where the old one was.
        point = self.view.page().scrollPosition()
        self._pending_scroll = (point.x(), point.y())
        self.view.setHtml(self._render())

    def _flush_pending_reload(self) -> None:
        """Run any pending debounced reload now (e.g. just before printing, so
        the print job renders the latest selection)."""
        if self._render_timer.isActive():
            self._render_timer.stop()
            self._reload_preview()

    def _back_offset_js(self) -> str:
        dx = _fmt_mm(self.back_offset_x())
        dy = _fmt_mm(-self.back_offset())
        return (
            f"document.documentElement.style.setProperty('--back-dx', '{dx}mm');"
            f"document.documentElement.style.setProperty('--back-dy', '{dy}mm');"
        )

    def _restore_scroll_js(self) -> str:
        """Put the preview back where it was before the reload that just
        finished. Whole pixels, because a fractional scroll offset would be
        rounded by the browser anyway."""
        x, y = self._pending_scroll
        return f"window.scrollTo({x:.0f}, {y:.0f});"

    def _measure_js(self) -> str:
        """Fit the examples to each tile, then flag any that still overflow.

        Order matters: the fit runs first so the overflow flag describes the tile
        as it will actually print. Shared by both update paths, since new tiles
        need measuring however they arrived."""
        return self._FIT_EXAMPLES_JS + self._OVERFLOW_JS

    def _body_swap_script(self) -> str:
        """Replace the sheets in place and re-measure them, with no page reload.

        The head is left alone: it carries no card-dependent styling, so there is
        nothing in it to refresh. Everything else the page holds survives too.
        The cut-border and cut-line toggles are classes on <body> itself rather
        than on its contents, the click listener is delegated on <document>, and
        the WebChannel bridge lives on <window>, so none of them need rebuilding.

        The body HTML is passed as a JSON string literal, which is the safe way
        to carry arbitrary markup (quotes, backslashes, angle brackets) into a
        script.

        Scroll is saved and restored inside this one synchronous script: an
        innerHTML assignment empties the body for an instant, and a browser that
        recomputes layout in that instant would clamp the scroll to the top and
        leave it there once the new content arrived."""
        body = json.dumps(self._render_body())
        return (
            "(function () {"
            "var x = window.scrollX, y = window.scrollY;"
            f"document.body.innerHTML = {body};"
            + self._measure_js()
            + "window.scrollTo(x, y);"
            + "return JSON.stringify(window.__stFit || {});"
            "})();"
        )

    def _load_script(self) -> str:
        """The one script run after the first load. Sets the on-screen toggles,
        measures the tiles, restores the scroll position, and returns the fit
        measurement.

        The scroll is restored last, once the DOM has settled, so it cannot be
        undone by a later layout change. The blocks stay separate IIFEs and hand
        the measurement over on window.__stFit, which is why the outer wrapper
        can return it without any of them sharing scope.

        The return value must be a string: a bare JS object arrives in the
        Python callback as an empty string (see dictionary_panel._GRAB_JS)."""
        return (
            "(function () {"
            + self._borders_js(self.show_borders())
            + self._cut_lines_js(self.print_cut_lines())
            + self._measure_js()
            + self._restore_scroll_js()
            + "return JSON.stringify(window.__stFit || {});"
            + "})();"
        )

    def _tile_click_script(self) -> str:
        return self._TILE_CLICK_JS.replace("__CHANNEL_JS__", _qwebchannel_js())

    def _on_load_finished(self, ok: bool) -> None:
        if not ok:
            return
        # A document exists now, so later refreshes can swap its body instead of
        # loading a fresh page.
        self._document_loaded = True
        # Two calls, deliberately. The click wiring returns nothing, while the
        # toggles-and-fit script returns the measurement through its callback;
        # folding them together would put the channel setup last and lose that
        # return value.
        #
        # The click wiring is injected once per loaded document, not once per
        # refresh: its listener is delegated on <document>, so a body swap leaves
        # it attached and still matching the new tiles.
        self.view.page().runJavaScript(self._tile_click_script())
        self.view.page().runJavaScript(self._load_script(), self._on_fit_measured)

    def _on_fit_measured(self, raw) -> None:
        """Parse the fit measurement the page reported and announce it. A page
        that went away mid-flight hands back None or an empty string, and a
        broken document could hand back something that is not JSON; neither is
        worth disturbing the sidebar over, so both are ignored."""
        if not raw:
            return
        try:
            measured = json.loads(raw)
        except (TypeError, ValueError):
            return
        if not isinstance(measured, dict):
            return
        self.auto_fit_measured.emit(
            {
                card_id: [(int(sense), int(index)) for sense, index in pairs]
                for card_id, pairs in measured.items()
            }
        )

    def _body_class_js(self, name: str, on: bool) -> str:
        action = "add" if on else "remove"
        return f"document.body.classList.{action}('{name}');"

    def _borders_js(self, on: bool) -> str:
        return self._body_class_js("show-borders", on)

    def _cut_lines_js(self, on: bool) -> str:
        return self._body_class_js("print-cut-lines", on)

    def print_cards(self) -> None:
        from PySide6.QtPrintSupport import QPrintDialog, QPrinter

        # The print job renders the currently loaded page, so make sure any
        # debounced reload has run before we hand it to the printer.
        self._flush_pending_reload()
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
