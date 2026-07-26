import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QPageSize
from PySide6.QtPrintSupport import QPrinter
from PySide6.QtWidgets import QApplication

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
    def test_constructs_with_controls(self):
        view = PrintView()
        self.assertIsNotNone(view.borders_checkbox)
        self.assertFalse(view.show_borders())

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

    def test_cut_lines_checkbox_defaults_on(self):
        view = PrintView()
        self.assertIsNotNone(view.cut_lines_checkbox)
        self.assertTrue(view.print_cut_lines())

    def test_cut_lines_js_toggles_body_class(self):
        view = PrintView()
        self.assertIn("add", view._cut_lines_js(True))
        self.assertIn("remove", view._cut_lines_js(False))
        self.assertIn("print-cut-lines", view._cut_lines_js(True))

    def test_back_offset_spinbox_defaults_to_3mm(self):
        view = PrintView()
        self.assertIsNotNone(view.back_offset_spin)
        self.assertEqual(view.back_offset(), 3.0)

    def test_horizontal_back_offset_spinbox_defaults_to_zero(self):
        view = PrintView()
        self.assertIsNotNone(view.back_offset_x_spin)
        self.assertEqual(view.back_offset_x(), 0.0)

    def test_set_cards_uses_both_back_offsets(self):
        # The rendered HTML must carry the chosen back offsets as the live CSS
        # variables, so the printed back sheet moves. The vertical value is
        # negated (a positive setting raises the back).
        view = PrintView()
        view.back_offset_spin.setValue(5.0)
        view.back_offset_x_spin.setValue(2.0)
        html = view._render()
        self.assertIn("--back-dx: 2mm", html)
        self.assertIn("--back-dy: -5mm", html)

    def test_back_offset_js_sets_the_css_variables(self):
        # An offset change updates the print transform's CSS variables in place
        # via JS (no full reload), which is what keeps the preview responsive.
        view = PrintView()
        view.back_offset_spin.setValue(4.0)
        view.back_offset_x_spin.setValue(1.5)
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

    def test_checkbox_on_by_default(self):
        self.assertTrue(self._view().blank_headwords_checkbox.isChecked())

    def test_render_blanks_token_when_checked(self):
        html = self._view()._render()
        self.assertIn('class="blank"', html)
        self.assertNotIn("{{word}}", html)

    def test_render_shows_literal_token_when_unchecked(self):
        view = self._view()
        view.blank_headwords_checkbox.setChecked(False)
        html = view._render()
        self.assertIn("{{word}}", html)
        self.assertNotIn('class="blank"', html)


if __name__ == "__main__":
    unittest.main()
