import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QPageSize
from PySide6.QtPrintSupport import QPrinter
from PySide6.QtWidgets import QApplication

from split_translator.flashcard_print_layout import PAGE
from split_translator.flashcard_print_view import PrintView
from split_translator.flashcards import Card, Sense

app = QApplication.instance() or QApplication([])


class PdfExportRoutingTests(unittest.TestCase):
    """"Print to File (PDF)" must not go through QPrinter.

    QWebEngineView.print paints the page into the QPrinter, which flattens it to
    a bitmap: the PDF then holds a picture of the sheet with no selectable or
    searchable text. Chromium's own printToPdf keeps the text as text, so a file
    destination is routed there instead. A real printer still goes through
    QPrinter, which is what carries the printer, tray and copy count.

    The export itself needs a live web engine and is verified by a runtime
    walkthrough; what is pinned here is that the two destinations are told
    apart."""

    def _view(self):
        view = PrintView()
        view.set_cards([Card(headword="alpha", id="a")])
        self.addCleanup(view.deleteLater)
        exported, printed = [], []
        view._export_pdf = lambda printer: exported.append(printer)
        view.view.print = lambda printer: printed.append(printer)
        return view, exported, printed

    def test_a_file_destination_goes_to_the_pdf_exporter(self):
        view, exported, printed = self._view()
        printer = QPrinter()
        printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
        printer.setOutputFileName("/tmp/cards.pdf")
        view._send_to(printer)
        self.assertEqual(len(exported), 1)
        self.assertEqual(printed, [])

    def test_a_real_printer_still_goes_through_qprinter(self):
        view, exported, printed = self._view()
        printer = QPrinter()
        printer.setOutputFormat(QPrinter.OutputFormat.NativeFormat)
        view._send_to(printer)
        self.assertEqual(len(printed), 1)
        self.assertEqual(exported, [])

    def test_the_printer_is_kept_alive_for_the_async_print(self):
        # QWebEngineView.print is asynchronous; dropping the QPrinter before the
        # job finishes would collect it mid-print.
        view, _exported, _printed = self._view()
        printer = QPrinter()
        printer.setOutputFormat(QPrinter.OutputFormat.NativeFormat)
        view._send_to(printer)
        self.assertIs(view._active_printer, printer)

    def test_export_without_a_filename_does_nothing(self):
        # Nothing to write to, so there is no file to produce.
        view = PrintView()
        self.addCleanup(view.deleteLater)
        wrote = []
        view.view.page().printToPdf = lambda *a, **kw: wrote.append(a)
        printer = QPrinter()
        printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
        view._export_pdf(printer)
        self.assertEqual(wrote, [])

    def test_export_drops_the_page_margins(self):
        # The sheet's CSS already places everything on the page. A margin here
        # would inset it a second time and every card would miss its cut lines.
        # The default QPageLayout mode silently clamps a zero margin up to the
        # device minimum, so the mode has to be changed for it to take.
        view = PrintView()
        self.addCleanup(view.deleteLater)
        seen = []
        view.view.page().printToPdf = lambda path, layout: seen.append(layout)
        printer = QPrinter()
        printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
        printer.setOutputFileName("/tmp/cards.pdf")
        printer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
        view._export_pdf(printer)

        self.assertEqual(len(seen), 1)
        margins = seen[0].margins()
        self.assertEqual(
            (margins.left(), margins.top(), margins.right(), margins.bottom()),
            (0, 0, 0, 0),
        )

    def test_captured_ids_emit_on_successful_completion(self):
        view = PrintView()
        view.set_cards([Card(headword="a", id="a"), Card(headword="b", id="b")])
        emitted = []
        view.cards_printed.connect(lambda ids: emitted.append(list(ids)))
        view._capture_printing_ids()
        view._on_print_finished(True)
        self.assertEqual(emitted, [["a", "b"]])

    def test_no_emit_on_failed_completion(self):
        view = PrintView()
        view.set_cards([Card(headword="a", id="a")])
        emitted = []
        view.cards_printed.connect(lambda ids: emitted.append(list(ids)))
        view._capture_printing_ids()
        view._on_print_finished(False)
        self.assertEqual(emitted, [])

    def test_pdf_completion_emits_on_success(self):
        view = PrintView()
        view.set_cards([Card(headword="a", id="a")])
        emitted = []
        view.cards_printed.connect(lambda ids: emitted.append(list(ids)))
        view._capture_printing_ids()
        view._on_pdf_finished("/tmp/x.pdf", True)
        self.assertEqual(emitted, [["a"]])


class PrintViewTests(unittest.TestCase):
    def test_constructs_with_defaults(self):
        # The view carries the render inputs as plain state now; the widgets
        # that set them live in the sidebar.
        view = PrintView()
        self.assertFalse(view.show_borders())
        self.assertTrue(view.print_cut_lines())
        self.assertEqual(view.back_offset(), PAGE.back_offset_mm)
        self.assertEqual(view.back_offset_x(), PAGE.back_offset_x_mm)

    def test_set_cards_does_not_raise(self):
        view = PrintView()
        view.set_cards([Card(headword="alpha", id="a")])

    def test_borders_js_toggles_class(self):
        view = PrintView()
        self.assertIn("add", view._borders_js(True))
        self.assertIn("remove", view._borders_js(False))
        self.assertIn("show-borders", view._borders_js(True))

    def test_overflow_js_marks_tiles(self):
        view = PrintView()
        self.assertIn("is-overflow", view._OVERFLOW_JS)
        self.assertIn("scrollHeight", view._OVERFLOW_JS)

    def test_fit_examples_js_measures_and_regroups(self):
        # Only the browser knows how tall a wrapped sentence renders, so the fit
        # is measured in-page: fill until the tile overflows, then sort the
        # survivors back into sense order.
        view = PrintView()
        js = view._FIT_EXAMPLES_JS
        self.assertIn("scrollHeight", js)
        self.assertIn("example-list", js)
        self.assertIn("dataset.sense", js)
        self.assertIn("sort", js)

    def test_cut_lines_js_toggles_body_class(self):
        view = PrintView()
        self.assertIn("add", view._cut_lines_js(True))
        self.assertIn("remove", view._cut_lines_js(False))
        self.assertIn("print-cut-lines", view._cut_lines_js(True))

    def test_set_cards_uses_both_back_offsets(self):
        # The rendered HTML must carry the chosen back offsets as the live CSS
        # variables, so the printed back sheet moves. The vertical value is
        # negated (a positive setting raises the back).
        view = PrintView()
        view.set_back_offsets(5.0, 2.0)
        html = view._render()
        self.assertIn("--back-dx: 2mm", html)
        self.assertIn("--back-dy: -5mm", html)

    def test_back_offset_js_sets_the_css_variables(self):
        # An offset change updates the print transform's CSS variables in place
        # via JS (no full reload), which is what keeps the preview responsive.
        view = PrintView()
        view.set_back_offsets(4.0, 1.5)
        js = view._back_offset_js()
        self.assertIn("setProperty", js)
        self.assertIn("--back-dx", js)
        self.assertIn("1.5mm", js)
        self.assertIn("--back-dy", js)
        self.assertIn("-4mm", js)

    def test_set_choices_reaches_the_rendered_html(self):
        # A hand-picked set has to survive into the document the preview loads
        # and the printer prints, not just live in the sidebar.
        view = PrintView()
        card = Card(
            headword="w", id="w",
            senses=[Sense(pos="v", examples=["keep me", "drop me"])],
        )
        view.set_cards([card])
        view.set_choices({"w": {(0, 0)}})
        html = view._render()
        self.assertIn("keep me", html)
        self.assertNotIn("drop me", html)

    def test_fit_js_skips_a_hand_picked_list(self):
        # The fit measurement must leave a manual card alone, or it would trim
        # the set the user explicitly asked for.
        view = PrintView()
        self.assertIn(':not([data-fit="manual"])', view._FIT_EXAMPLES_JS)


class BlankHeadwordsToggleTests(unittest.TestCase):
    def _view(self):
        view = PrintView()
        self.addCleanup(view.deleteLater)
        view.set_cards([Card(headword="cat", id="c",
                            senses=[Sense(english="a {{word}} naps")])])
        return view

    def test_blanking_is_on_by_default(self):
        self.assertTrue(self._view().blank_headwords())

    def test_render_blanks_token_when_on(self):
        html = self._view()._render()
        self.assertIn('class="blank"', html)
        self.assertNotIn("{{word}}", html)

    def test_render_shows_literal_token_when_off(self):
        view = self._view()
        view.set_blank_headwords(False)
        html = view._render()
        self.assertIn("{{word}}", html)
        self.assertNotIn('class="blank"', html)


class AutoFitReportTests(unittest.TestCase):
    """The automatic default is only knowable in the page, so the fit script
    reports which examples it kept. The value must come back as a JSON string:
    a bare JS object arrives in the Python callback as an empty string."""

    def test_the_fit_js_records_the_card_id_and_both_indices(self):
        view = PrintView()
        js = view._FIT_EXAMPLES_JS
        self.assertIn("data-card-id", js)
        self.assertIn("dataset.example", js)
        self.assertIn("__stFit", js)

    def test_the_load_script_returns_a_json_string(self):
        view = PrintView()
        script = view._load_script()
        self.assertIn("JSON.stringify", script)
        # The fit must run before the overflow flagging, so the flag describes
        # the tile as it will actually print.
        self.assertLess(script.index("__stFit"), script.index("is-overflow"))

    def test_a_measurement_is_parsed_and_emitted(self):
        view = PrintView()
        seen = []
        view.auto_fit_measured.connect(seen.append)
        view._on_fit_measured('{"c": [[0, 0], [1, 2]]}')
        self.assertEqual(seen, [{"c": [(0, 0), (1, 2)]}])

    def test_an_empty_measurement_still_emits(self):
        # A document with no front examples at all measures nothing, and the
        # sidebar has to hear that rather than keep stale ticks.
        view = PrintView()
        seen = []
        view.auto_fit_measured.connect(seen.append)
        view._on_fit_measured("{}")
        self.assertEqual(seen, [{}])

    def test_a_failed_script_emits_nothing(self):
        # runJavaScript hands back None when the page went away mid-flight.
        view = PrintView()
        seen = []
        view.auto_fit_measured.connect(seen.append)
        view._on_fit_measured(None)
        view._on_fit_measured("")
        self.assertEqual(seen, [])

    def test_malformed_json_emits_nothing(self):
        view = PrintView()
        seen = []
        view.auto_fit_measured.connect(seen.append)
        view._on_fit_measured("not json")
        self.assertEqual(seen, [])


class TileClickTests(unittest.TestCase):
    """A click on a tile loads that card. The page reaches Python over a
    QWebChannel, the same mechanism the dictionary capture buttons and the
    anchor editor use. The click itself needs a live web engine and is verified
    by a runtime walkthrough; what is pinned here is the plumbing."""

    def test_the_bridge_re_emits_a_click(self):
        from split_translator.print_tile_bridge import PrintTileBridge
        bridge = PrintTileBridge()
        seen = []
        bridge.tile_clicked.connect(seen.append)
        bridge.clicked("card-7")
        self.assertEqual(seen, ["card-7"])

    def test_the_view_re_emits_the_bridge_signal(self):
        view = PrintView()
        seen = []
        view.card_clicked.connect(seen.append)
        view._bridge.clicked("card-7")
        self.assertEqual(seen, ["card-7"])

    def test_the_click_script_targets_tiles_with_a_card_id(self):
        view = PrintView()
        js = view._tile_click_script()
        self.assertIn(".tile[data-card-id]", js)
        self.assertIn("printTileBridge", js)

    def test_the_click_script_carries_the_channel_client(self):
        # Without Qt's bundled qwebchannel.js the page has no QWebChannel to
        # construct, so the bridge would never connect.
        view = PrintView()
        js = view._tile_click_script()
        self.assertIn("QWebChannel", js)
        self.assertNotIn("__CHANNEL_JS__", js)


class ScrollPreservationTests(unittest.TestCase):
    """setHtml replaces the document, so every reload would otherwise jump the
    preview back to the first sheet. Ticking an example on a card halfway down a
    long print run has to leave that card where it was.

    The capture itself needs a live page with real content to scroll, so what is
    pinned here is the plumbing: the position is recorded on reload and written
    back by the per-load script."""

    def test_a_fresh_view_starts_at_the_top(self):
        view = PrintView()
        self.addCleanup(view.deleteLater)
        self.assertEqual(view._pending_scroll, (0.0, 0.0))

    def test_the_restore_script_scrolls_to_the_pending_position(self):
        view = PrintView()
        self.addCleanup(view.deleteLater)
        view._pending_scroll = (0.0, 840.0)
        self.assertIn("window.scrollTo(0, 840)", view._restore_scroll_js())

    def test_a_fractional_position_is_rounded_to_whole_pixels(self):
        # scrollPosition reports floats; a fractional offset would be rounded by
        # the browser anyway, so it must not reach the page as "840.7".
        view = PrintView()
        self.addCleanup(view.deleteLater)
        view._pending_scroll = (12.4, 840.7)
        self.assertIn("window.scrollTo(12, 841)", view._restore_scroll_js())

    def test_the_load_script_restores_after_the_fit_and_before_the_return(self):
        # After the fit, so a layout change cannot undo it; before the return,
        # or it would replace the fit measurement as the script's value.
        view = PrintView()
        self.addCleanup(view.deleteLater)
        script = view._load_script()
        self.assertIn("window.scrollTo", script)
        self.assertLess(script.index("__stFit"), script.index("window.scrollTo"))
        self.assertLess(
            script.index("window.scrollTo"), script.index("JSON.stringify")
        )

    def test_reloading_records_the_current_position(self):
        # The offscreen page has nothing to scroll, so this pins that the reload
        # reads the live position rather than leaving a stale one behind.
        view = PrintView()
        self.addCleanup(view.deleteLater)
        view._pending_scroll = (99.0, 99.0)
        view.set_cards([Card(headword="alpha", id="a")])
        view._reload_preview()
        self.assertEqual(view._pending_scroll, (0.0, 0.0))


if __name__ == "__main__":
    unittest.main()
