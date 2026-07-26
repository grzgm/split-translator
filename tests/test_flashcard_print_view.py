import json
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QPageSize
from PySide6.QtPrintSupport import QPrinter
from PySide6.QtWidgets import QApplication, QDialog, QRadioButton, QTabWidget

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

    def test_the_job_starts_on_long_edge_duplex(self):
        # The sheets are laid out for a long-edge flip and no other: the backs
        # are mirrored to land on their own fronts once the paper turns about
        # its long edge. Short-edge binding would print every back upside down.
        view = PrintView()
        self.addCleanup(view.deleteLater)
        self.assertEqual(
            view._new_printer().duplex(), QPrinter.DuplexMode.DuplexLongSide
        )

    def test_the_print_dialog_opens_on_the_preset_printer(self):
        # The preset is worth nothing if print_cards builds a plain QPrinter of
        # its own, so pin that the dialog is handed the pre-set one.
        import PySide6.QtPrintSupport as print_support

        view = PrintView()
        self.addCleanup(view.deleteLater)
        shown = []

        # A real QDialog, so the Options-tab step meets a dialog with none of
        # the widgets it looks for, exactly as it would on a platform with a
        # native print dialog.
        class _RejectingDialog(QDialog):
            def __init__(self, printer, parent):
                super().__init__(parent)
                shown.append(printer)

            def exec(self):
                return self.DialogCode.Rejected

        original = print_support.QPrintDialog
        print_support.QPrintDialog = _RejectingDialog
        try:
            view.print_cards()
        finally:
            print_support.QPrintDialog = original

        self.assertEqual(len(shown), 1)
        self.assertEqual(shown[0].duplex(), QPrinter.DuplexMode.DuplexLongSide)

    def test_the_dialog_opens_on_the_two_sided_setting(self):
        # Qt builds the dialog collapsed and on its Copies tab, which puts the
        # long-edge default this window sets two clicks out of sight.
        #
        # The dialog is never shown here: a QPrintDialog segfaults under the
        # offscreen platform once the web engine is loaded, so what is asserted
        # is the state it would be shown in. The two assertions before the call
        # pin what Qt builds, so this cannot quietly pass on a future Qt that
        # already opens where it should.
        from PySide6.QtPrintSupport import QPrintDialog, QPrinter

        view = PrintView()
        self.addCleanup(view.deleteLater)
        dialog = QPrintDialog(QPrinter(), None)
        self.addCleanup(dialog.deleteLater)
        tabs = dialog.findChild(QTabWidget)
        duplex = dialog.findChild(QRadioButton, "duplexLong")
        self.assertIsNotNone(duplex, "Qt's dialog no longer has a duplex radio")
        self.assertFalse(tabs.isVisibleTo(dialog))
        self.assertFalse(tabs.widget(tabs.currentIndex()).isAncestorOf(duplex))

        view._open_on_options_tab(dialog)

        self.assertTrue(tabs.isVisibleTo(dialog))
        self.assertTrue(tabs.widget(tabs.currentIndex()).isAncestorOf(duplex))

    def test_a_dialog_without_those_widgets_is_left_alone(self):
        # A native print dialog has none of the widgets this hunts for. It must
        # come out untouched rather than raising or clicking something else.
        view = PrintView()
        self.addCleanup(view.deleteLater)
        dialog = QDialog()
        self.addCleanup(dialog.deleteLater)
        view._open_on_options_tab(dialog)  # must not raise

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


class BodySwapTests(unittest.TestCase):
    """A refresh replaces the sheets inside the live document instead of loading
    a fresh page. setHtml tears the document down and Chromium paints a blank
    frame in the gap, which is the blink that made ticking an example
    unpleasant.

    The swap itself needs a live page, so what is pinned here is which path a
    refresh takes and what the swap script contains."""

    def _view(self):
        view = PrintView()
        self.addCleanup(view.deleteLater)
        view._cards = [Card(headword="alpha", id="a")]
        loaded, scripts = [], []
        view.view.setHtml = lambda html: loaded.append(html)
        view.view.page().runJavaScript = (
            lambda js, *cb: scripts.append(js)
        )
        return view, loaded, scripts

    def test_the_first_refresh_loads_a_whole_document(self):
        view, loaded, scripts = self._view()
        view._reload_preview()
        self.assertEqual(len(loaded), 1)
        self.assertIn("<!DOCTYPE html>", loaded[0])
        self.assertEqual(scripts, [])

    def test_a_later_refresh_swaps_the_body_instead(self):
        view, loaded, scripts = self._view()
        view._document_loaded = True
        view._reload_preview()
        self.assertEqual(loaded, [])
        self.assertEqual(len(scripts), 1)
        self.assertIn("document.body.innerHTML", scripts[0])

    def test_a_failed_load_leaves_the_next_refresh_on_the_full_path(self):
        # Swapping a body into a document that never loaded would do nothing at
        # all, and the preview would sit empty.
        view, loaded, _scripts = self._view()
        view._on_load_finished(False)
        view._reload_preview()
        self.assertEqual(len(loaded), 1)

    def test_a_successful_load_arms_the_swap_path(self):
        view, _loaded, _scripts = self._view()
        self.assertFalse(view._document_loaded)
        view._on_load_finished(True)
        self.assertTrue(view._document_loaded)

    def test_the_swap_carries_the_body_as_a_json_string_literal(self):
        # Arbitrary markup has to survive being embedded in a script, so it is
        # passed as JSON rather than pasted in raw. Assert it round-trips: the
        # literal in the script must decode back to exactly the rendered body,
        # quotes, backslashes and angle brackets intact.
        view = PrintView()
        self.addCleanup(view.deleteLater)
        view.set_cards([
            Card(headword='q"uote \\ <b>', id="a",
                 senses=[Sense(pos="v", examples=['He said "no" & left.'])]),
        ])
        script = view._body_swap_script()
        marker = "document.body.innerHTML = "
        start = script.index(marker) + len(marker)
        # raw_decode reads exactly one JSON value from that offset, so it stops
        # at the end of the literal without any hand-rolled quote matching.
        decoded, _end = json.JSONDecoder().raw_decode(script, start)
        self.assertEqual(decoded, view._render_body())

    def test_the_swap_measures_the_new_tiles(self):
        # New tiles arrive unmeasured, so the fit and the overflow flagging have
        # to run again, and the measurement still has to reach Python.
        view = PrintView()
        self.addCleanup(view.deleteLater)
        script = view._body_swap_script()
        self.assertIn("__stFit", script)
        self.assertIn("is-overflow", script)
        self.assertIn("JSON.stringify", script)
        self.assertLess(
            script.index("document.body.innerHTML"), script.index("__stFit")
        )

    def test_the_swap_preserves_the_scroll_position_itself(self):
        # An innerHTML assignment empties the body for an instant; a browser that
        # relayouts in that instant would clamp the scroll to the top. Saving and
        # restoring inside the same synchronous script closes that window.
        view = PrintView()
        self.addCleanup(view.deleteLater)
        script = view._body_swap_script()
        self.assertIn("window.scrollY", script)
        self.assertIn("window.scrollTo(x, y)", script)
        self.assertLess(
            script.index("window.scrollY"), script.index("document.body.innerHTML")
        )
        self.assertLess(
            script.index("document.body.innerHTML"),
            script.index("window.scrollTo(x, y)"),
        )

    def test_the_swap_reflects_the_current_cards_and_choices(self):
        view = PrintView()
        self.addCleanup(view.deleteLater)
        view.set_cards([
            Card(headword="cat", id="c",
                 senses=[Sense(pos="v", examples=["keep me", "drop me"])]),
        ])
        view.set_choices({"c": {(0, 0)}})
        script = view._body_swap_script()
        self.assertIn("keep me", script)
        self.assertNotIn("drop me", script)

    def test_the_swap_carries_no_document_wrapper(self):
        # The head is deliberately left alone, so the payload must be the sheets
        # alone. A whole document nested inside body would be invalid markup.
        view = PrintView()
        self.addCleanup(view.deleteLater)
        view.set_cards([Card(headword="alpha", id="a")])
        script = view._body_swap_script()
        self.assertNotIn("<!DOCTYPE html>", script)
        self.assertNotIn("<style>", script)


class SelectedTileTests(unittest.TestCase):
    """The card loaded in the editor is marked in the preview too, so the saved
    list, the editor, the sidebar and the sheets all point at one card. It is a
    class toggle rather than a re-render, and it has to survive the reloads and
    body swaps that replace the tiles it sits on."""

    def _view(self):
        view = PrintView()
        self.addCleanup(view.deleteLater)
        return view

    def test_nothing_is_marked_to_begin_with(self):
        self.assertIsNone(self._view()._selected_card_id)

    def test_setting_a_card_records_it(self):
        view = self._view()
        view.set_selected_card("c")
        self.assertEqual(view._selected_card_id, "c")

    def test_clearing_with_none_records_nothing(self):
        view = self._view()
        view.set_selected_card("c")
        view.set_selected_card(None)
        self.assertIsNone(view._selected_card_id)

    def test_an_empty_id_clears_rather_than_marking_nothing(self):
        # An empty string would build a selector matching no tile, which happens
        # to work, but storing it as None keeps "nothing selected" one value.
        view = self._view()
        view.set_selected_card("c")
        view.set_selected_card("")
        self.assertIsNone(view._selected_card_id)

    def test_the_script_clears_any_previous_mark_first(self):
        # Loading another card must unmark the old one, or every card ever
        # loaded would stay highlighted.
        view = self._view()
        view.set_selected_card("c")
        js = view._selected_js()
        self.assertIn("classList.remove('tile--selected')", js)
        self.assertLess(
            js.index("classList.remove"), js.index("classList.add")
        )

    def test_the_script_marks_the_card_by_id(self):
        view = self._view()
        view.set_selected_card("c")
        js = view._selected_js()
        self.assertIn('var id = "c";', js)
        self.assertIn("data-card-id", js)
        self.assertIn("classList.add('tile--selected')", js)

    def test_the_id_is_embedded_as_a_json_literal(self):
        view = self._view()
        view.set_selected_card('we"ird\\id')
        js = view._selected_js()
        marker = "var id = "
        start = js.index(marker) + len(marker)
        decoded, _end = json.JSONDecoder().raw_decode(js, start)
        self.assertEqual(decoded, 'we"ird\\id')

    def test_marking_nothing_leaves_the_script_a_plain_clear(self):
        view = self._view()
        js = view._selected_js()
        self.assertIn('var id = "";', js)
        self.assertIn("classList.remove('tile--selected')", js)

    def test_the_mark_is_reapplied_after_a_reload(self):
        # A reload builds fresh tiles, so the class has to go back on.
        view = self._view()
        view.set_selected_card("c")
        self.assertIn("tile--selected", view._load_script())

    def test_the_mark_is_reapplied_after_a_body_swap(self):
        # A body swap replaces the tiles the class was sitting on.
        view = self._view()
        view.set_selected_card("c")
        self.assertIn("tile--selected", view._body_swap_script())


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
        # Anchor on the script's own return, not on any JSON.stringify: other
        # blocks in the script use that call too.
        self.assertLess(
            script.index("window.scrollTo"), script.index("return JSON.stringify")
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
