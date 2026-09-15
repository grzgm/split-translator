import unittest
from pathlib import Path

from PySide6.QtWebEngineCore import QWebEngineProfile
from PySide6.QtWidgets import QApplication

from split_translator.book_loader import BookDocument
from split_translator.book_view import BookView

app = QApplication.instance() or QApplication([])


def _doc():
    return BookDocument(
        html=(
            "<h1 data-stid='b0'>Title</h1>"
            "<p data-stid='b1'>Body text here.</p>"
        ),
        block_ids=["b0", "b1"],
        title="T",
    )


class BookViewConstructionTests(unittest.TestCase):
    def test_constructs_with_document_and_profile(self):
        profile = QWebEngineProfile()
        view = BookView(_doc(), profile)
        self.assertTrue(hasattr(view, "scrolled"))
        self.assertTrue(callable(view.scroll_to))
        self.assertTrue(callable(view.request_scroll_state))
        self.assertTrue(callable(view.find))

    def test_backs_onto_a_temp_file_and_loads_it_by_url(self):
        # The view renders from a file:// URL, not setHtml, so a book larger
        # than setHtml's ~2 MB cap still renders. The temp file exists while the
        # view does.
        profile = QWebEngineProfile()
        view = BookView(_doc(), profile)
        self.assertTrue(view._rendered.path.exists())
        self.assertTrue(view._rendered.url().isLocalFile())

    def test_release_rendered_deletes_the_temp_file(self):
        profile = QWebEngineProfile()
        view = BookView(_doc(), profile)
        path = view._rendered.path
        self.assertTrue(path.exists())
        view.release_rendered()
        self.assertFalse(path.exists())

    def test_accepts_initial_scroll(self):
        profile = QWebEngineProfile()
        view = BookView(_doc(), profile, initial_scroll=("b1", 0.5))
        self.assertEqual(view._initial_scroll, ("b1", 0.5))

    def test_restore_calls_scroll_to_on_successful_load(self):
        profile = QWebEngineProfile()
        view = BookView(_doc(), profile, initial_scroll=("b1", 0.5))
        calls = []
        view.scroll_to = lambda bid, frac: calls.append((bid, frac))
        view._restore_initial_scroll(True)
        self.assertEqual(calls, [("b1", 0.5)])

    def test_restore_reemits_position_so_cache_stays_correct(self):
        # scroll_to suppresses its echoed scrollPositionChanged, so the restore
        # must re-announce the position; otherwise the only thing a listener
        # sees from load is the document top, which would be persisted on close.
        # A restored position has no section, so it is never mirrored.
        profile = QWebEngineProfile()
        view = BookView(_doc(), profile, initial_scroll=("b1", 0.5))
        view.scroll_to = lambda bid, frac: None  # stub out the JS scroll
        emitted = []
        view.scrolled.connect(lambda *args: emitted.append(args))
        view._restore_initial_scroll(True)
        self.assertEqual(emitted, [("b1", 0.5, -1, 0.0)])

    def test_restore_waits_for_a_successful_load(self):
        # A failed first load (ok=False) must not consume the one-shot: a later
        # successful load still restores.
        profile = QWebEngineProfile()
        view = BookView(_doc(), profile, initial_scroll=("b1", 0.5))
        calls = []
        view.scroll_to = lambda bid, frac: calls.append((bid, frac))
        view._restore_initial_scroll(False)
        self.assertEqual(calls, [])  # nothing yet
        view._restore_initial_scroll(True)
        self.assertEqual(calls, [("b1", 0.5)])  # restored on the good load


class BookViewReapplyScrollTests(unittest.TestCase):
    def test_reapply_scroll_scrolls_now_and_arms_a_pending_reapply(self):
        # Re-applying records the target and scrolls once immediately; the
        # immediate scroll is best effort against whatever layout exists now.
        profile = QWebEngineProfile()
        view = BookView(_doc(), profile)
        calls = []
        view.scroll_to = lambda bid, frac: calls.append((bid, frac))
        view.reapply_scroll("b1", 0.5)
        self.assertEqual(calls, [("b1", 0.5)])
        self.assertEqual(view._pending_reapply, ("b1", 0.5))

    def test_contents_size_change_reruns_the_pending_scroll_when_visible(self):
        # The settling reflow (a contentsSizeChanged) must re-run the scroll so
        # the final offset is computed against the settled, visible layout. Stub
        # isVisible since an unshown test view is not visible by default.
        from PySide6.QtCore import QSizeF

        profile = QWebEngineProfile()
        view = BookView(_doc(), profile)
        view.isVisible = lambda: True
        view._pending_reapply = ("b1", 0.5)
        calls = []
        view.scroll_to = lambda bid, frac: calls.append((bid, frac))
        view._on_contents_size_changed(QSizeF(800, 1000))
        self.assertEqual(calls, [("b1", 0.5)])

    def test_contents_size_change_does_not_scroll_while_hidden(self):
        # A reflow can fire on a hidden tab (window resize, or the tab hidden
        # again mid-settle). Scrolling then would bake a wrong offset against the
        # provisional hidden layout, so the gate must skip it and keep the
        # pending target armed for the next time the tab is shown.
        from PySide6.QtCore import QSizeF

        profile = QWebEngineProfile()
        view = BookView(_doc(), profile)
        view.isVisible = lambda: False
        view._pending_reapply = ("b1", 0.5)
        calls = []
        view.scroll_to = lambda bid, frac: calls.append((bid, frac))
        view._on_contents_size_changed(QSizeF(800, 1000))
        self.assertEqual(calls, [])  # gated: not scrolled while hidden
        self.assertEqual(view._pending_reapply, ("b1", 0.5))  # still armed

    def test_contents_size_change_without_pending_is_a_noop(self):
        from PySide6.QtCore import QSizeF

        profile = QWebEngineProfile()
        view = BookView(_doc(), profile)
        view.isVisible = lambda: True
        view._pending_reapply = None
        calls = []
        view.scroll_to = lambda bid, frac: calls.append((bid, frac))
        view._on_contents_size_changed(QSizeF(800, 1000))
        self.assertEqual(calls, [])

    def test_user_scroll_clears_the_pending_reapply(self):
        # A genuine (non-suppressed) scroll means the user moved, so a later
        # reflow must not yank them back: the pending re-apply is dropped. Stub
        # the page read so no real async JS races test teardown.
        profile = QWebEngineProfile()
        view = BookView(_doc(), profile)
        view.page().runJavaScript = lambda *a, **k: None
        view._pending_reapply = ("b1", 0.5)
        view._suppress_scroll = False
        view.request_scroll_state()
        self.assertIsNone(view._pending_reapply)

    def test_suppressed_scroll_keeps_the_pending_reapply(self):
        # The scroll_to that reapply issues echoes a suppressed scroll; that
        # must not clear the pending re-apply (it is not a user move).
        profile = QWebEngineProfile()
        view = BookView(_doc(), profile)
        view._pending_reapply = ("b1", 0.5)
        view._suppress_scroll = True
        view.request_scroll_state()
        self.assertEqual(view._pending_reapply, ("b1", 0.5))


class BookViewSectionTests(unittest.TestCase):
    def test_a_scroll_report_carries_both_positions(self):
        import json

        view = BookView(_doc(), QWebEngineProfile())
        emitted = []
        view.scrolled.connect(lambda *args: emitted.append(args))
        view._on_scroll_state(
            json.dumps({"id": "b1", "fraction": 0.5, "section": 2, "share": 0.25})
        )
        self.assertEqual(emitted, [("b1", 0.5, 2, 0.25)])

    def test_a_report_without_a_section_says_minus_one(self):
        import json

        view = BookView(_doc(), QWebEngineProfile())
        emitted = []
        view.scrolled.connect(lambda *args: emitted.append(args))
        view._on_scroll_state(json.dumps({"id": "b1", "fraction": 0.5}))
        self.assertEqual(emitted, [("b1", 0.5, -1, 0.0)])

    def test_set_sections_sends_the_starts_and_remembers_them(self):
        view = BookView(_doc(), QWebEngineProfile())
        calls = []
        view.page().runJavaScript = lambda js, *a, **k: calls.append(js)
        view.set_sections(["top", "b0", "end"])
        self.assertEqual(view._section_starts, ["top", "b0", "end"])
        self.assertIn('["top", "b0", "end"]', calls[-1])

    def test_a_load_reapplies_the_sections(self):
        # Starts pushed before the page has loaded would be lost with it.
        view = BookView(_doc(), QWebEngineProfile())
        calls = []
        view.page().runJavaScript = lambda js, *a, **k: calls.append(js)
        view.set_sections(["top", "b0", "end"])
        calls.clear()
        view._inject_search_mark(True)
        self.assertTrue(any('["top", "b0", "end"]' in js for js in calls))

    def test_scroll_to_section_sends_the_position_and_suppresses_the_echo(self):
        view = BookView(_doc(), QWebEngineProfile())
        calls = []
        view.page().runJavaScript = lambda js, *a, **k: calls.append(js)
        view.scroll_to_section(2, 0.25)
        self.assertTrue(view._suppress_scroll)
        self.assertIn("(2, 0.25)", calls[-1])

    def test_reapply_section_scrolls_now_and_arms_a_pending_section(self):
        view = BookView(_doc(), QWebEngineProfile())
        calls = []
        view.scroll_to_section = lambda k, s: calls.append((k, s))
        view._pending_reapply = ("b1", 0.5)
        view.reapply_section(2, 0.25)
        self.assertEqual(calls, [(2, 0.25)])
        self.assertEqual(view._pending_section, (2, 0.25))
        self.assertIsNone(view._pending_reapply)

    def test_reapply_scroll_drops_a_pending_section(self):
        view = BookView(_doc(), QWebEngineProfile())
        view.scroll_to = lambda bid, frac: None
        view._pending_section = (2, 0.25)
        view.reapply_scroll("b1", 0.5)
        self.assertIsNone(view._pending_section)

    def test_a_reflow_reruns_the_pending_section_when_visible(self):
        from PySide6.QtCore import QSizeF

        view = BookView(_doc(), QWebEngineProfile())
        view.isVisible = lambda: True
        view._pending_section = (2, 0.25)
        calls = []
        view.scroll_to_section = lambda k, s: calls.append((k, s))
        view._on_contents_size_changed(QSizeF(800, 1000))
        self.assertEqual(calls, [(2, 0.25)])

    def test_a_user_scroll_clears_the_pending_section(self):
        view = BookView(_doc(), QWebEngineProfile())
        view.page().runJavaScript = lambda *a, **k: None
        view._pending_section = (2, 0.25)
        view._suppress_scroll = False
        view.request_scroll_state()
        self.assertIsNone(view._pending_section)


class BookViewSearchMarkTests(unittest.TestCase):
    def test_mark_search_blocks_runs_the_toggle_js_with_the_ids(self):
        profile = QWebEngineProfile()
        view = BookView(_doc(), profile)
        calls = []
        view.page().runJavaScript = lambda js, *a, **k: calls.append(js)
        view.mark_search_blocks(["b0", "b1"])
        self.assertEqual(len(calls), 1)
        self.assertIn("st-search-block", calls[0])
        self.assertIn('["b0", "b1"]', calls[0])

    def test_clear_search_mark_runs_the_toggle_js_with_no_ids(self):
        profile = QWebEngineProfile()
        view = BookView(_doc(), profile)
        calls = []
        view.page().runJavaScript = lambda js, *a, **k: calls.append(js)
        view.clear_search_mark()
        self.assertEqual(len(calls), 1)
        self.assertIn("st-search-block", calls[0])
        self.assertIn("([])", calls[0])

    def test_matched_block_id_forwards_the_blocks_id_to_the_callback(self):
        # The occurrence-count JS returns the block id; matched_block_id forwards
        # it (or "" for no match). Stub runJavaScript to invoke the callback with
        # a canned id, so no real page read runs.
        profile = QWebEngineProfile()
        view = BookView(_doc(), profile)

        def fake_run(js, callback):
            self.assertIn('"needle"', js)  # term is JSON-quoted into the JS
            self.assertIn(", 3)", js)  # the 1-based match index is passed in
            callback("b1")

        view.page().runJavaScript = fake_run
        got = []
        view.matched_block_id("needle", 3, got.append)
        self.assertEqual(got, ["b1"])

    def test_matched_block_id_passes_empty_string_when_no_block(self):
        profile = QWebEngineProfile()
        view = BookView(_doc(), profile)
        view.page().runJavaScript = lambda js, callback: callback(None)
        got = []
        view.matched_block_id("needle", 1, got.append)
        self.assertEqual(got, [""])  # None becomes ""


class BookViewNormaliseTests(unittest.TestCase):
    """The paragraph-spacing normalisation toggle injects a style element and
    flips its enabled state, without reloading the page."""

    def test_default_is_off_and_injects_disabled(self):
        profile = QWebEngineProfile()
        view = BookView(_doc(), profile)  # normalise defaults to False
        calls = []
        view.page().runJavaScript = lambda js, *a, **k: calls.append(js)
        view._apply_normalise()
        self.assertEqual(len(calls), 1)
        self.assertIn("st-normalise-style", calls[0])
        self.assertIn("false", calls[0].rsplit(")", 2)[-2])  # enabled arg is false

    def test_constructed_with_normalise_applies_enabled(self):
        profile = QWebEngineProfile()
        view = BookView(_doc(), profile, normalise=True)
        calls = []
        view.page().runJavaScript = lambda js, *a, **k: calls.append(js)
        view._apply_normalise()
        self.assertIn("st-normalise-style", calls[0])
        self.assertTrue(calls[0].rstrip().endswith("true);"))  # enabled = true

    def test_set_normalise_toggles_the_flag(self):
        # The enabled flag is the injection's last argument.
        profile = QWebEngineProfile()
        view = BookView(_doc(), profile)
        calls = []
        view.page().runJavaScript = lambda js, *a, **k: calls.append(js)
        view.set_normalise(True)
        self.assertTrue(view._normalise)
        self.assertTrue(calls[-1].rstrip().endswith("true);"))
        view.set_normalise(False)
        self.assertFalse(view._normalise)
        self.assertTrue(calls[-1].rstrip().endswith("false);"))

    def test_normalise_css_carries_the_expected_rules(self):
        # The injected CSS zeroes block margins, sets a uniform paragraph gap and
        # collapses the blank spacer blocks the loader marked data-st-spacer,
        # so any book (p- or div-paragraph) levels. The default spec
        # (all multipliers at 1.0) renders exactly as the fixed rules always did.
        # Asserted against the actual _apply_normalise call site (not against
        # NormaliseSpec().css() directly), which is what normalise_spec's own
        # test suite already covers and this class exists to guard against.
        profile = QWebEngineProfile()
        view = BookView(_doc(), profile)
        calls = []
        view.page().runJavaScript = lambda js, *a, **k: calls.append(js)
        view._apply_normalise()
        css = calls[0]
        self.assertIn("margin-block: 0.6em", css)
        self.assertIn("[data-st-spacer]", css)
        self.assertIn("line-height", css)


class BookViewNormaliseSpecTests(unittest.TestCase):
    """The view builds its normalisation stylesheet from a spec and can be
    handed a new one live, on the same injection path as the on/off toggle."""

    def _view(self, **kwargs):
        from split_translator.book_view import BookView as _BookView

        return _BookView(_doc(), QWebEngineProfile(), **kwargs)

    def _injected(self, view):
        """The JS the view sends for one _apply_normalise call."""
        seen = []
        view.page().runJavaScript = lambda js, *a: seen.append(js)
        view._apply_normalise()
        return seen[0]

    def test_defaults_to_the_fixed_spec(self):
        from split_translator.normalise_spec import NormaliseSpec

        view = self._view()
        self.assertEqual(view._normalise_spec, NormaliseSpec())

    def test_a_given_spec_reaches_the_injected_css(self):
        from split_translator.normalise_spec import NormaliseSpec

        view = self._view(spec=NormaliseSpec(font=0.9))
        self.assertIn("font-size: 90%", self._injected(view))

    def test_set_normalise_spec_changes_the_injected_css(self):
        from split_translator.normalise_spec import NormaliseSpec

        view = self._view()
        self.assertIn("font-size: 100%", self._injected(view))
        view.set_normalise_spec(NormaliseSpec(font=1.2, gap=0.5))
        css = self._injected(view)
        self.assertIn("font-size: 120%", css)
        self.assertIn("margin-block: 0.3em", css)

    def test_the_toggle_still_carries_its_own_flag(self):
        # The spec and the on/off flag are independent: a spec change must not
        # silently switch normalisation on. The stub is installed before the
        # first call rather than via _injected afterwards: a real (unstubbed)
        # QWebEnginePage.runJavaScript call followed by reassigning that same
        # attribute crashes the PySide6 WebEngine binding under the offscreen
        # platform, so every real call on a given view must go through a stub
        # already in place, never the other way round.
        from split_translator.normalise_spec import NormaliseSpec

        view = self._view(normalise=False)
        seen = []
        view.page().runJavaScript = lambda js, *a: seen.append(js)
        view.set_normalise_spec(NormaliseSpec(font=0.9))
        # The enabled flag is the injection's last argument.
        self.assertTrue(seen[-1].rstrip().endswith("false);"))

    def test_the_style_text_is_set_on_every_call_not_only_on_create(self):
        # A spec change reaches the page through the same injection as the
        # toggle, so the text has to be reassigned each time. Setting it only
        # inside the "element does not exist yet" branch would make the first
        # spec permanent.
        from split_translator import book_view

        js = book_view._NORMALISE_STYLE_JS
        self.assertEqual(js.count("style.textContent = css;"), 1)
        self.assertGreater(
            js.index("style.textContent = css;"), js.index("appendChild")
        )

    def test_no_blank_block_walk_remains(self):
        # Spacers are marked by the loader and collapsed by the stylesheet, so
        # the injection only rewrites the style element: nothing walks the
        # book's blocks, however often a spin box fires.
        from split_translator import book_view

        js = book_view._NORMALISE_STYLE_JS
        self.assertNotIn("querySelectorAll", js)
        self.assertNotIn("st-blank", js)
        self.assertNotIn("retag", js)


class AnchorBookViewSpecTests(unittest.TestCase):
    def test_forwards_the_spec_to_the_base_view(self):
        from split_translator.anchor_book_view import AnchorBookView
        from split_translator.normalise_spec import NormaliseSpec

        spec = NormaliseSpec(gap=0.75)
        view = AnchorBookView(_doc(), QWebEngineProfile(), spec=spec)
        self.assertEqual(view._normalise_spec, spec)


import tempfile

from split_translator.book_panel import BookPanel
from split_translator.config import Config
from split_translator.layout import LAYOUT_BOOK, LAYOUT_NORMAL
from tests.fixtures.make_fixtures import make_epub


def _config(d, layout=LAYOUT_NORMAL):
    epub = make_epub(d)
    return Config(
        name="Test",
        dir=Path(d),
        original_path=epub,
        translation_path=epub,
        page_anchors=[],
        layout=layout,
    )


class BookPanelContractTests(unittest.TestCase):
    def test_constructs_and_exposes_the_main_window_contract(self):
        with tempfile.TemporaryDirectory() as d:
            profile = QWebEngineProfile()
            panel = BookPanel(_config(d), profile)
            for name in ("search", "go_to_next", "go_to_previous", "close_doc"):
                self.assertTrue(callable(getattr(panel, name)), name)

    def test_sync_checkbox_defaults_on(self):
        with tempfile.TemporaryDirectory() as d:
            profile = QWebEngineProfile()
            panel = BookPanel(_config(d), profile)
            self.assertTrue(panel.sync_checkbox.isChecked())

    def test_search_with_blank_term_is_a_noop(self):
        with tempfile.TemporaryDirectory() as d:
            profile = QWebEngineProfile()
            panel = BookPanel(_config(d), profile)
            panel.search("   ")  # must not raise

    def test_position_label_counts_paragraphs(self):
        with tempfile.TemporaryDirectory() as d:
            profile = QWebEngineProfile()
            panel = BookPanel(_config(d), profile)
            panel._update_position_label()
            self.assertEqual(panel.position_label.text(), "4 paragraphs")


from split_translator.book_sync import SectionMap
from split_translator.normalise_spec import ORIGINAL_SIDE, TRANSLATION_SIDE


class BookPanelSyncWiringTests(unittest.TestCase):
    def test_panel_builds_a_section_map_and_anchor_store(self):
        with tempfile.TemporaryDirectory() as d:
            profile = QWebEngineProfile()
            panel = BookPanel(_config(d), profile)
            self.addCleanup(panel.anchor_store.shutdown)
            self.assertIsInstance(panel.section_map, SectionMap)
            self.assertTrue(callable(panel._sync_from))

    def test_both_views_are_given_their_section_starts(self):
        with tempfile.TemporaryDirectory() as d:
            panel = BookPanel(_config(d), QWebEngineProfile())
            self.addCleanup(panel.anchor_store.shutdown)
            self.assertEqual(
                panel.original_view._section_starts,
                panel.section_map.section_starts(ORIGINAL_SIDE),
            )
            self.assertEqual(
                panel.translation_view._section_starts,
                panel.section_map.section_starts(TRANSLATION_SIDE),
            )

    def test_sync_disabled_does_not_raise_on_scroll(self):
        with tempfile.TemporaryDirectory() as d:
            profile = QWebEngineProfile()
            panel = BookPanel(_config(d), profile)
            self.addCleanup(panel.anchor_store.shutdown)
            panel.sync_enabled = False
            panel._sync_from(panel.original_view, "b0", 0.0)  # must not raise


class BookPanelCloseTests(unittest.TestCase):
    def test_close_doc_shuts_down_anchor_store(self):
        with tempfile.TemporaryDirectory() as d:
            profile = QWebEngineProfile()
            panel = BookPanel(_config(d), profile)
            # close_doc writes the store under the .config dir; remove it after.
            self.addCleanup(
                panel.anchor_store.filepath.unlink, missing_ok=True
            )
            real_shutdown = panel.anchor_store.shutdown
            shutdown_called = []

            def tracking_shutdown():
                shutdown_called.append(True)
                real_shutdown()

            panel.anchor_store.shutdown = tracking_shutdown
            panel.close_doc()
            self.assertTrue(
                shutdown_called,
                "close_doc() must call anchor_store.shutdown() to await in-flight writes",
            )


class BookPanelScrollMemoryTests(unittest.TestCase):
    def _panel(self, cfg, profile):
        # BookPanel writes its anchor store under the real .config dir, so
        # register both the in-flight-write wait and removal of the store file
        # to keep the repo directory clean after the test.
        panel = BookPanel(cfg, profile)
        self.addCleanup(panel.anchor_store.shutdown)
        self.addCleanup(panel.anchor_store.filepath.unlink, missing_ok=True)
        return panel

    def test_sync_from_caches_each_sides_scroll(self):
        with tempfile.TemporaryDirectory() as d:
            profile = QWebEngineProfile()
            panel = self._panel(_config(d), profile)
            panel.sync_enabled = False  # isolate the caching from mirroring
            panel._sync_from(panel.original_view, "b3", 0.25)
            panel._sync_from(panel.translation_view, "b7", 0.5)
            self.assertEqual(panel._original_scroll, ("b3", 0.25))
            self.assertEqual(panel._translation_scroll, ("b7", 0.5))

    def test_close_doc_persists_scroll_to_store(self):
        with tempfile.TemporaryDirectory() as d:
            profile = QWebEngineProfile()
            cfg = _config(d)
            panel = self._panel(cfg, profile)
            panel.sync_enabled = False
            panel._sync_from(panel.original_view, "b3", 0.25)
            panel._sync_from(panel.translation_view, "b7", 0.5)
            store_path = panel.anchor_store.filepath
            panel.close_doc()  # writes and shuts down

            from split_translator.anchor_store import READER_SURFACE, AnchorStore

            reloaded = AnchorStore(store_path)
            self.addCleanup(reloaded.shutdown)
            self.assertEqual(
                reloaded.get_scroll(READER_SURFACE), (("b3", 0.25), ("b7", 0.5))
            )

    def test_load_top_emit_then_restore_emit_leaves_cache_at_restored(self):
        # Reproduces the load-time clobber: during load the view emits the top
        # (b0, 0.0); the restore then emits the saved position. The cache (and
        # thus what close persists) must end at the restored position, not top.
        with tempfile.TemporaryDirectory() as d:
            profile = QWebEngineProfile()
            panel = self._panel(_config(d), profile)
            panel.sync_enabled = False
            # Simulate the load-time scrollPositionChanged reading the top.
            panel._sync_from(panel.original_view, "b0", 0.0)
            # Then the restore re-announces the saved position.
            panel._sync_from(panel.original_view, "b5", 0.4)
            self.assertEqual(panel._original_scroll, ("b5", 0.4))

    def test_panel_seeds_scroll_from_store(self):
        # A store that already holds positions should hand them to the views as
        # their initial scroll.
        with tempfile.TemporaryDirectory() as d:
            profile = QWebEngineProfile()
            cfg = _config(d)
            # Prime the store file before the panel reads it.
            from split_translator.anchor_store import (
                READER_SURFACE,
                AnchorStore,
                anchor_path_for,
            )
            path = anchor_path_for(
                cfg.original_path, cfg.translation_path, cfg.dir
            )
            seed = AnchorStore(path)
            seed.set_scroll(READER_SURFACE, ("b1", 0.0), ("b1", 0.0))
            seed.shutdown()
            self.addCleanup(path.unlink, missing_ok=True)

            panel = self._panel(cfg, profile)
            self.assertEqual(panel.original_view._initial_scroll, ("b1", 0.0))
            self.assertEqual(panel.translation_view._initial_scroll, ("b1", 0.0))

    def test_a_saved_position_on_a_lost_block_reopens_at_a_paragraph(self):
        # The fixture's paragraphs are b0..b3. A saved id that is no longer a
        # paragraph resolves to the next one, or the last when none follows.
        with tempfile.TemporaryDirectory() as d:
            profile = QWebEngineProfile()
            cfg = _config(d)
            from split_translator.anchor_store import (
                READER_SURFACE,
                AnchorStore,
                anchor_path_for,
            )
            path = anchor_path_for(
                cfg.original_path, cfg.translation_path, cfg.dir
            )
            seed = AnchorStore(path)
            seed.set_scroll(READER_SURFACE, ("b99", 0.5), ("b1", 0.25))
            seed.shutdown()
            self.addCleanup(path.unlink, missing_ok=True)

            panel = self._panel(cfg, profile)
            self.assertEqual(panel.original_view._initial_scroll, ("b3", 0.0))
            self.assertEqual(panel.translation_view._initial_scroll, ("b1", 0.25))


class BookPanelTabSwitchTests(unittest.TestCase):
    def _panel(self, cfg, profile):
        panel = BookPanel(cfg, profile)
        self.addCleanup(panel.anchor_store.shutdown)
        self.addCleanup(panel.anchor_store.filepath.unlink, missing_ok=True)
        return panel

    def test_switching_tab_reapplies_the_shown_views_cached_position(self):
        # The bug: a scroll mirrored into the hidden Translation tab baked a
        # wrong pixel offset against the hidden layout. Switching to it must
        # re-apply its cached (block_id, fraction) against the visible layout.
        with tempfile.TemporaryDirectory() as d:
            profile = QWebEngineProfile()
            panel = self._panel(_config(d), profile)
            calls = []
            panel.translation_view.reapply_scroll = (
                lambda bid, frac: calls.append((bid, frac))
            )
            panel._translation_scroll = ("b1", 0.25)
            panel.tabs.setCurrentIndex(1)  # show Translation
            self.assertEqual(calls, [("b1", 0.25)])

    def test_switching_back_reapplies_the_original_views_cached_position(self):
        with tempfile.TemporaryDirectory() as d:
            profile = QWebEngineProfile()
            panel = self._panel(_config(d), profile)
            panel.tabs.setCurrentIndex(1)
            calls = []
            panel.original_view.reapply_scroll = (
                lambda bid, frac: calls.append((bid, frac))
            )
            panel._original_scroll = ("b0", 0.0)
            panel.tabs.setCurrentIndex(0)  # back to Original
            self.assertEqual(calls, [("b0", 0.0)])

    def test_switching_with_no_cached_position_does_not_reapply(self):
        with tempfile.TemporaryDirectory() as d:
            profile = QWebEngineProfile()
            panel = self._panel(_config(d), profile)
            panel._translation_scroll = None
            called = []
            panel.translation_view.reapply_scroll = (
                lambda bid, frac: called.append((bid, frac))
            )
            panel.tabs.setCurrentIndex(1)  # must not raise, must not reapply
            self.assertEqual(called, [])

    def test_mirror_records_the_section_target_for_the_hidden_side(self):
        # Mirroring a scroll on the active Original records the section position
        # for the hidden Translation, and caches the paragraph it falls in so
        # close persists the right spot rather than the hidden view's drift.
        with tempfile.TemporaryDirectory() as d:
            profile = QWebEngineProfile()
            panel = self._panel(_config(d), profile)
            calls = []
            panel.translation_view.scroll_to_section = (
                lambda k, s: calls.append((k, s))
            )
            panel._sync_from(panel.original_view, "b1", 0.25, 1, 0.3)
            self.assertEqual(calls, [(1, 0.3)])
            self.assertEqual(panel._translation_sync_target, (1, 0.3))
            self.assertEqual(
                panel._translation_scroll,
                panel.section_map.paragraph_at(TRANSLATION_SIDE, 1, 0.3),
            )

    def test_a_position_without_a_section_is_not_mirrored(self):
        # A restored position, or a report from a page whose starts have not
        # arrived, is cached but has nothing to pass on.
        with tempfile.TemporaryDirectory() as d:
            panel = self._panel(_config(d), QWebEngineProfile())
            calls = []
            panel.translation_view.scroll_to_section = (
                lambda k, s: calls.append((k, s))
            )
            panel._sync_from(panel.original_view, "b1", 0.25)
            panel._sync_from(panel.original_view, "b1", 0.25, 99, 0.5)
            self.assertEqual(calls, [])
            self.assertEqual(panel._original_scroll, ("b1", 0.25))

    def test_switch_reapplies_the_section_target_over_a_drifted_cache(self):
        with tempfile.TemporaryDirectory() as d:
            profile = QWebEngineProfile()
            panel = self._panel(_config(d), profile)
            panel._translation_sync_target = (1, 0.25)
            panel._translation_scroll = ("b99", 0.99)  # a drifted/wrong cache
            sections, paragraphs = [], []
            panel.translation_view.reapply_section = (
                lambda k, s: sections.append((k, s))
            )
            panel.translation_view.reapply_scroll = (
                lambda b, f: paragraphs.append((b, f))
            )
            panel.tabs.setCurrentIndex(1)
            self.assertEqual(sections, [(1, 0.25)])  # the section target wins
            self.assertEqual(paragraphs, [])

    def test_hidden_view_drift_echo_is_ignored(self):
        # A scroll reported by the hidden tab while it has a pending target is
        # a drift echo; it must not corrupt the cache or the target.
        with tempfile.TemporaryDirectory() as d:
            profile = QWebEngineProfile()
            panel = self._panel(_config(d), profile)
            panel._translation_sync_target = (1, 0.25)
            panel._translation_scroll = ("b3", 0.25)
            panel._sync_from(panel.translation_view, "b99", 0.99, 2, 0.9)
            self.assertEqual(panel._translation_scroll, ("b3", 0.25))
            self.assertEqual(panel._translation_sync_target, (1, 0.25))

    def test_user_scrolling_active_tab_clears_its_sync_target(self):
        with tempfile.TemporaryDirectory() as d:
            profile = QWebEngineProfile()
            panel = self._panel(_config(d), profile)
            panel.translation_view.scroll_to_section = lambda k, s: None
            panel._original_sync_target = (1, 0.0)  # a stale target
            panel._sync_from(panel.original_view, "b2", 0.5, 1, 0.5)
            self.assertIsNone(panel._original_sync_target)


class BookPanelSearchMarkTests(unittest.TestCase):
    def _panel(self, cfg, profile):
        panel = BookPanel(cfg, profile)
        self.addCleanup(panel.anchor_store.shutdown)
        self.addCleanup(panel.anchor_store.filepath.unlink, missing_ok=True)
        return panel

    def _stub_marks(self, panel):
        # Record mark/clear calls per view; stub matched_block_id so the active
        # view reports a canned block without running real page JS.
        marks = {"orig": [], "trans": []}
        panel.original_view.mark_search_blocks = lambda ids: marks["orig"].append(ids)
        panel.translation_view.mark_search_blocks = lambda ids: marks["trans"].append(ids)
        panel.original_view.clear_search_mark = lambda: marks["orig"].append(None)
        panel.translation_view.clear_search_mark = lambda: marks["trans"].append(None)
        return marks

    def test_match_marks_the_paragraph_and_its_counterpart_in_the_other(self):
        # With no anchors the book is one stretch, and both editions are the
        # same book, so the same share of the text lands on the same paragraph:
        # marking b1 in the original marks b1 too.
        with tempfile.TemporaryDirectory() as d:
            profile = QWebEngineProfile()
            panel = self._panel(_config(d), profile)
            marks = self._stub_marks(panel)
            bid = panel.original_document.block_ids[1]
            panel.original_view.matched_block_id = (
                lambda term, index, cb: cb(bid)
            )
            panel.search_term = "needle"
            panel._mark_current_match(1, 1)
            self.assertEqual(marks["orig"], [[bid]])
            self.assertEqual(marks["trans"], [[bid]])  # same book, same paragraph

    def test_no_match_clears_both_marks(self):
        with tempfile.TemporaryDirectory() as d:
            profile = QWebEngineProfile()
            panel = self._panel(_config(d), profile)
            marks = self._stub_marks(panel)
            panel.search_term = "needle"
            panel._mark_current_match(0, 0)  # zero matches
            self.assertEqual(marks["orig"], [None])
            self.assertEqual(marks["trans"], [None])

    def test_empty_matched_block_clears_both_marks(self):
        # A match count but no resolvable block (the term spans nodes oddly)
        # clears rather than marking nothing.
        with tempfile.TemporaryDirectory() as d:
            profile = QWebEngineProfile()
            panel = self._panel(_config(d), profile)
            marks = self._stub_marks(panel)
            panel.original_view.matched_block_id = lambda term, index, cb: cb("")
            panel.search_term = "needle"
            panel._mark_current_match(1, 1)
            self.assertEqual(marks["orig"], [None])
            self.assertEqual(marks["trans"], [None])

    def test_sync_off_marks_only_the_active_view(self):
        with tempfile.TemporaryDirectory() as d:
            profile = QWebEngineProfile()
            panel = self._panel(_config(d), profile)
            marks = self._stub_marks(panel)
            panel.sync_enabled = False
            bid = panel.original_document.block_ids[1]
            panel.original_view.matched_block_id = (
                lambda term, index, cb: cb(bid)
            )
            panel.search_term = "needle"
            panel._mark_current_match(1, 1)
            self.assertEqual(marks["orig"], [[bid]])
            self.assertEqual(marks["trans"], [None])  # other side cleared, not marked

    def test_blank_search_clears_both_marks(self):
        with tempfile.TemporaryDirectory() as d:
            profile = QWebEngineProfile()
            panel = self._panel(_config(d), profile)
            marks = self._stub_marks(panel)
            panel.search("   ")  # blank term
            self.assertEqual(marks["orig"], [None])
            self.assertEqual(marks["trans"], [None])

    def test_counter_uses_the_absolute_match_index(self):
        # The find result's activeMatch is the match's absolute position in the
        # book. The label must show it ("3 / 4"), not a hardcoded "1 / N", so a
        # search that lands on the 3rd occurrence reads 3, not 1.
        with tempfile.TemporaryDirectory() as d:
            profile = QWebEngineProfile()
            panel = self._panel(_config(d), profile)
            self._stub_marks(panel)
            panel.search_term = "needle"
            # Stub the block lookup so marking does not run real page JS.
            panel.original_view.matched_block_id = (
                lambda term, index, cb: cb("")
            )
            panel._on_find_result(active=3, count=4)
            self.assertEqual(panel.current_match, 3)
            self.assertEqual(panel.match_count, 4)
            self.assertEqual(panel.match_label.text(), "3 / 4")

    def test_mark_locates_block_by_the_active_match_index(self):
        # The block is found from the find's activeMatch (1-based), not the
        # scroll position, so a wrap-around to the first match marks the right
        # block. Capture the index passed to matched_block_id.
        with tempfile.TemporaryDirectory() as d:
            profile = QWebEngineProfile()
            panel = self._panel(_config(d), profile)
            self._stub_marks(panel)
            panel.search_term = "needle"
            seen = []
            panel.original_view.matched_block_id = (
                lambda term, index, cb: (seen.append(index), cb(""))
            )
            panel._on_find_result(active=1, count=4)  # wrapped to the first match
            self.assertEqual(seen, [1])  # located by index 1, not by scroll

    def test_matched_block_with_no_translation_paragraphs_clears_and_does_not_raise(self):
        # A scanned or image-only translation has no paragraphs to mark.
        with tempfile.TemporaryDirectory() as d:
            profile = QWebEngineProfile()
            panel = self._panel(_config(d), profile)
            marks = self._stub_marks(panel)
            panel.translation_document.block_ids = []
            panel.section_map = panel._build_section_map()
            bid = panel.original_document.block_ids[1]
            panel._on_matched_block(
                panel.original_view, panel.translation_view, bid
            )  # must not raise
            self.assertEqual(marks["trans"], [None])

    def test_a_match_in_a_group_marks_the_whole_group_in_the_other(self):
        # b1 is anchored to b1 and to b2, so it matches both.
        with tempfile.TemporaryDirectory() as d:
            panel = self._panel(_config(d), QWebEngineProfile())
            marks = self._stub_marks(panel)
            panel.anchor_store.anchors = [("b1", "b1"), ("b1", "b2")]
            panel.section_map = panel._build_section_map()
            panel._on_matched_block(
                panel.original_view, panel.translation_view, "b1"
            )
            self.assertEqual(marks["orig"], [["b1"]])
            self.assertEqual(marks["trans"], [["b1", "b2"]])

    def test_zero_active_match_clears_marks(self):
        # A find that reports no active match (active=0) clears both marks rather
        # than trying to locate a 0th block.
        with tempfile.TemporaryDirectory() as d:
            profile = QWebEngineProfile()
            panel = self._panel(_config(d), profile)
            marks = self._stub_marks(panel)
            panel.search_term = "needle"
            panel._on_find_result(active=0, count=0)
            self.assertEqual(panel.current_match, 0)
            self.assertEqual(marks["orig"], [None])
            self.assertEqual(marks["trans"], [None])


class BookPanelForceOriginalSearchTests(unittest.TestCase):
    """The reader searches the Original edition only. A search, Next or Prev
    started while the Translation tab is showing switches to Original and finds
    there; the Translation view is never a find target."""

    def _panel(self, cfg, profile):
        panel = BookPanel(cfg, profile)
        self.addCleanup(panel.anchor_store.shutdown)
        self.addCleanup(panel.anchor_store.filepath.unlink, missing_ok=True)
        return panel

    def _stub_finds(self, panel):
        # Record which view find() runs on (and the forward flag), without
        # running the real page JS. Also stub marking so no page read follows.
        finds = {"orig": [], "trans": []}
        panel.original_view.find = (
            lambda term, forward, cb: finds["orig"].append((term, forward))
        )
        panel.translation_view.find = (
            lambda term, forward, cb: finds["trans"].append((term, forward))
        )
        panel.original_view.matched_block_id = lambda term, index, cb: cb("")
        panel.original_view.mark_search_blocks = lambda ids: None
        panel.translation_view.mark_search_blocks = lambda ids: None
        panel.original_view.clear_search_mark = lambda: None
        panel.translation_view.clear_search_mark = lambda: None
        return finds

    def test_search_from_translation_tab_switches_to_original_and_finds_there(self):
        with tempfile.TemporaryDirectory() as d:
            profile = QWebEngineProfile()
            panel = self._panel(_config(d), profile)
            panel.tabs.setCurrentIndex(1)  # Translation showing
            finds = self._stub_finds(panel)
            panel.search("needle")
            self.assertEqual(panel.tabs.currentIndex(), 0)  # switched to Original
            self.assertEqual(finds["orig"], [("needle", True)])
            self.assertEqual(finds["trans"], [])  # never searches Translation

    def test_search_from_original_tab_stays_and_finds_on_original(self):
        with tempfile.TemporaryDirectory() as d:
            profile = QWebEngineProfile()
            panel = self._panel(_config(d), profile)
            finds = self._stub_finds(panel)  # Original is the default tab
            panel.search("needle")
            self.assertEqual(panel.tabs.currentIndex(), 0)
            self.assertEqual(finds["orig"], [("needle", True)])
            self.assertEqual(finds["trans"], [])

    def test_next_from_translation_tab_switches_and_finds_forward_on_original(self):
        with tempfile.TemporaryDirectory() as d:
            profile = QWebEngineProfile()
            panel = self._panel(_config(d), profile)
            finds = self._stub_finds(panel)
            panel.search_term = "needle"
            panel.match_count = 3  # a prior search found matches
            panel.tabs.setCurrentIndex(1)  # user then read the Translation
            finds["orig"].clear()  # ignore the search above
            panel.go_to_next()
            self.assertEqual(panel.tabs.currentIndex(), 0)
            self.assertEqual(finds["orig"], [("needle", True)])
            self.assertEqual(finds["trans"], [])

    def test_prev_from_translation_tab_switches_and_finds_backward_on_original(self):
        with tempfile.TemporaryDirectory() as d:
            profile = QWebEngineProfile()
            panel = self._panel(_config(d), profile)
            finds = self._stub_finds(panel)
            panel.search_term = "needle"
            panel.match_count = 3
            panel.tabs.setCurrentIndex(1)
            finds["orig"].clear()
            panel.go_to_previous()
            self.assertEqual(panel.tabs.currentIndex(), 0)
            self.assertEqual(finds["orig"], [("needle", False)])
            self.assertEqual(finds["trans"], [])

    def test_next_with_no_matches_does_not_switch_or_find(self):
        with tempfile.TemporaryDirectory() as d:
            profile = QWebEngineProfile()
            panel = self._panel(_config(d), profile)
            finds = self._stub_finds(panel)
            panel.match_count = 0  # nothing found yet
            panel.tabs.setCurrentIndex(1)
            panel.go_to_next()
            self.assertEqual(panel.tabs.currentIndex(), 1)  # stayed put
            self.assertEqual(finds["orig"], [])
            self.assertEqual(finds["trans"], [])


class BookPanelNormaliseTests(unittest.TestCase):
    """The reader's Normalise checkbox seeds from the persisted per-book-pair
    flag, toggles both views live, and persists the choice."""

    def _panel(self, cfg, profile):
        panel = BookPanel(cfg, profile)
        self.addCleanup(panel.anchor_store.shutdown)
        self.addCleanup(panel.anchor_store.filepath.unlink, missing_ok=True)
        return panel

    def test_checkbox_defaults_on(self):
        # No stored flag -> default ON, and the checkbox reflects it.
        with tempfile.TemporaryDirectory() as d:
            profile = QWebEngineProfile()
            panel = self._panel(_config(d), profile)
            self.assertTrue(panel.normalise_checkbox.isChecked())
            self.assertTrue(panel._normalise)

    def test_toggle_off_sets_both_views_and_persists(self):
        with tempfile.TemporaryDirectory() as d:
            profile = QWebEngineProfile()
            panel = self._panel(_config(d), profile)
            seen = {"orig": [], "trans": []}
            panel.original_view.set_normalise = lambda v: seen["orig"].append(v)
            panel.translation_view.set_normalise = lambda v: seen["trans"].append(v)
            panel.normalise_checkbox.setChecked(False)
            self.assertFalse(panel._normalise)
            self.assertEqual(seen["orig"], [False])
            self.assertEqual(seen["trans"], [False])
            # Persisted for the reader surface.
            from split_translator.anchor_store import READER_SURFACE

            self.assertFalse(panel.anchor_store.get_normalise(READER_SURFACE))

    def test_seeds_checkbox_from_a_stored_off_flag(self):
        # A book pair whose stored reader flag is OFF opens with the box cleared
        # and the views constructed un-normalised.
        with tempfile.TemporaryDirectory() as d:
            cfg = _config(d)
            profile = QWebEngineProfile()
            from split_translator.anchor_store import (
                READER_SURFACE,
                AnchorStore,
                anchor_path_for,
            )
            path = anchor_path_for(
                cfg.original_path, cfg.translation_path, cfg.dir
            )
            seed = AnchorStore(path)
            seed.set_normalise(READER_SURFACE, False)
            seed.shutdown()
            self.addCleanup(path.unlink, missing_ok=True)

            panel = self._panel(cfg, profile)
            self.assertFalse(panel.normalise_checkbox.isChecked())
            self.assertFalse(panel.original_view._normalise)
            self.assertFalse(panel.translation_view._normalise)


class BookPanelEditorTests(unittest.TestCase):
    def test_an_anchor_change_rebuilds_the_sections_and_pushes_them(self):
        with tempfile.TemporaryDirectory() as d:
            panel = BookPanel(_config(d), QWebEngineProfile())
            self.addCleanup(panel.anchor_store.shutdown)
            panel.anchor_store.anchors = [("b1", "b1")]
            panel._rebuild_sections()
            expected = ["top", "b0", "b1", "b2", "end"]
            self.assertEqual(panel.section_map.section_starts(ORIGINAL_SIDE), expected)
            self.assertEqual(panel.original_view._section_starts, expected)
            self.assertEqual(panel.translation_view._section_starts, expected)

    def test_a_rebuild_drops_section_targets_from_the_old_map(self):
        with tempfile.TemporaryDirectory() as d:
            panel = BookPanel(_config(d), QWebEngineProfile())
            self.addCleanup(panel.anchor_store.shutdown)
            panel._original_sync_target = (2, 0.5)
            panel._translation_sync_target = (1, 0.5)
            panel._rebuild_sections()
            self.assertIsNone(panel._original_sync_target)
            self.assertIsNone(panel._translation_sync_target)

    def test_a_rebuild_hands_the_new_map_to_the_open_editor(self):
        # Closed inside the `with` block: closeEvent writes to the store, and
        # after the directory is gone that write would recreate it.
        with tempfile.TemporaryDirectory() as d:
            panel = BookPanel(_config(d), QWebEngineProfile())
            panel.open_anchor_editor()
            try:
                self.assertIs(panel.anchor_editor.section_map, panel.section_map)
                panel.anchor_store.anchors = [("b1", "b1")]
                panel._rebuild_sections()
                self.assertIs(panel.anchor_editor.section_map, panel.section_map)
                self.assertEqual(
                    panel.anchor_editor.original_view._section_starts,
                    ["top", "b0", "b1", "b2", "end"],
                )
            finally:
                panel.anchor_editor.close()
                panel.anchor_store.shutdown()


class BookPanelNormaliseSpecTests(unittest.TestCase):
    """The reader takes its per-edition multipliers from the same per-book-pair
    store the anchor editor writes, and follows changes made there live."""

    def _panel(self, cfg, profile):
        panel = BookPanel(cfg, profile)
        self.addCleanup(panel.anchor_store.shutdown)
        self.addCleanup(panel.anchor_store.filepath.unlink, missing_ok=True)
        return panel

    def test_views_default_to_the_fixed_spec(self):
        from split_translator.normalise_spec import NormaliseSpec

        with tempfile.TemporaryDirectory() as d:
            panel = self._panel(_config(d), QWebEngineProfile())
            self.assertEqual(panel.original_view._normalise_spec, NormaliseSpec())
            self.assertEqual(panel.translation_view._normalise_spec, NormaliseSpec())

    def test_views_seed_from_the_stored_specs(self):
        from split_translator.anchor_store import AnchorStore, anchor_path_for
        from split_translator.normalise_spec import NormaliseSpec

        with tempfile.TemporaryDirectory() as d:
            cfg = _config(d)
            store = AnchorStore(
                anchor_path_for(cfg.original_path, cfg.translation_path, cfg.dir)
            )
            store.set_normalise_specs(
                NormaliseSpec(font=0.9), NormaliseSpec(gap=0.7)
            )
            store.shutdown()
            panel = self._panel(cfg, QWebEngineProfile())
            self.assertAlmostEqual(panel.original_view._normalise_spec.font, 0.9)
            self.assertAlmostEqual(panel.translation_view._normalise_spec.gap, 0.7)

    def test_a_spec_change_reaches_the_matching_view_only(self):
        from split_translator.normalise_spec import ORIGINAL_SIDE, NormaliseSpec

        with tempfile.TemporaryDirectory() as d:
            panel = self._panel(_config(d), QWebEngineProfile())
            seen = {"orig": [], "trans": []}
            panel.original_view.set_normalise_spec = lambda s: seen["orig"].append(s)
            panel.translation_view.set_normalise_spec = lambda s: seen["trans"].append(s)
            panel._apply_normalise_spec(ORIGINAL_SIDE, NormaliseSpec(font=0.9))
            self.assertEqual(len(seen["orig"]), 1)
            self.assertEqual(seen["trans"], [])

    def test_the_editor_is_given_the_callback(self):
        # The reader is what wires the editor to itself; the two panels never
        # call each other directly.
        #
        # The editor is closed (and the store shut down) INSIDE the `with`
        # block, not via addCleanup: addCleanup runs at test teardown, after
        # the TemporaryDirectory has already been removed, and closeEvent
        # writes (scroll, and now the spec flush), which recreates the
        # just-deleted tree from a worker thread (write_anchors does
        # mkdir(parents=True, exist_ok=True)). That is a plausible contributor
        # to this suite's known "Directory not empty" cleanup flake.
        with tempfile.TemporaryDirectory() as d:
            panel = self._panel(_config(d), QWebEngineProfile())
            panel.open_anchor_editor()
            try:
                self.assertEqual(
                    panel.anchor_editor._on_spec_changed, panel._apply_normalise_spec
                )
            finally:
                panel.anchor_editor.close()
                panel.anchor_store.shutdown()


class BookPanelLayoutTests(unittest.TestCase):
    def _panel(self, cfg, profile):
        panel = BookPanel(cfg, profile)
        self.addCleanup(panel.anchor_store.shutdown)
        self.addCleanup(panel.anchor_store.filepath.unlink, missing_ok=True)
        return panel

    def test_normal_view_puts_the_editions_in_tabs(self):
        with tempfile.TemporaryDirectory() as d:
            panel = self._panel(_config(d), QWebEngineProfile())
            self.assertEqual(panel.tabs.count(), 2)
            self.assertIs(panel.tabs.widget(0), panel.original_view)

    def test_book_view_shows_both_editions_at_once(self):
        with tempfile.TemporaryDirectory() as d:
            panel = self._panel(_config(d, LAYOUT_BOOK), QWebEngineProfile())
            self.assertIsNone(panel.tabs)
            parent = panel.original_view.parentWidget()
            self.assertIs(panel.translation_view.parentWidget(), parent)

    def test_the_editions_take_the_height_in_the_book_view(self):
        # The nav row's two QLabels grow vertically, so without a stretch on the
        # view area they swallow the spare height and the editions end up in a
        # short band down the panel (measured: 480px of an 853px panel).
        with tempfile.TemporaryDirectory() as d:
            panel = self._panel(_config(d, LAYOUT_BOOK), QWebEngineProfile())
            panel.resize(900, 800)
            panel.show()
            self.addCleanup(panel.hide)
            QApplication.processEvents()
            self.assertGreater(panel.original_view.height(), 700)

    def test_the_editions_take_the_height_in_the_normal_view(self):
        with tempfile.TemporaryDirectory() as d:
            panel = self._panel(_config(d), QWebEngineProfile())
            panel.resize(900, 800)
            panel.show()
            self.addCleanup(panel.hide)
            QApplication.processEvents()
            self.assertGreater(panel.original_view.height(), 700)

    def test_book_view_mirrors_a_translation_scroll_to_the_original(self):
        # Both editions are on screen, so neither is the hidden one and a scroll
        # mirrors whichever way the reader moves.
        with tempfile.TemporaryDirectory() as d:
            panel = self._panel(_config(d, LAYOUT_BOOK), QWebEngineProfile())
            panel.sync_enabled = True
            calls = []
            panel.original_view.scroll_to_section = (
                lambda k, s: calls.append((k, s))
            )
            panel._sync_from(panel.translation_view, "b3", 0.25, 1, 0.8)
            self.assertEqual(calls, [(1, 0.8)])

    def test_normal_view_ignores_a_scroll_from_the_hidden_edition(self):
        # The control for the test above: with tabs, only the front edition
        # mirrors.
        with tempfile.TemporaryDirectory() as d:
            panel = self._panel(_config(d), QWebEngineProfile())
            panel.sync_enabled = True
            calls = []
            panel.original_view.scroll_to_section = (
                lambda k, s: calls.append((k, s))
            )
            panel._sync_from(panel.translation_view, "b3", 0.25, 1, 0.8)
            self.assertEqual(calls, [])

    def test_book_view_ignores_the_echo_of_its_own_mirror(self):
        # Mirroring into the translation makes it report a scroll a moment
        # later. Mirrored back, that echo would pull the original the reader is
        # scrolling: offscreen, a slow 3000px scroll moved 24px.
        with tempfile.TemporaryDirectory() as d:
            panel = self._panel(_config(d, LAYOUT_BOOK), QWebEngineProfile())
            panel.sync_enabled = True
            to_original, to_translation = [], []
            panel.original_view.scroll_to_section = (
                lambda k, s: to_original.append((k, s))
            )
            panel.translation_view.scroll_to_section = (
                lambda k, s: to_translation.append((k, s))
            )
            panel._sync_from(panel.original_view, "b2", 0.5, 1, 0.5)
            panel._sync_from(panel.translation_view, "b2", 0.5, 1, 0.5)
            self.assertEqual(len(to_translation), 1)
            self.assertEqual(to_original, [])

    def test_book_view_ignores_the_echo_when_the_translation_drives(self):
        with tempfile.TemporaryDirectory() as d:
            panel = self._panel(_config(d, LAYOUT_BOOK), QWebEngineProfile())
            panel.sync_enabled = True
            to_original, to_translation = [], []
            panel.original_view.scroll_to_section = (
                lambda k, s: to_original.append((k, s))
            )
            panel.translation_view.scroll_to_section = (
                lambda k, s: to_translation.append((k, s))
            )
            panel._sync_from(panel.translation_view, "b2", 0.5, 1, 0.5)
            panel._sync_from(panel.original_view, "b2", 0.5, 1, 0.5)
            self.assertEqual(len(to_original), 1)
            self.assertEqual(to_translation, [])

    def test_book_view_hands_over_once_the_mirror_settles(self):
        with tempfile.TemporaryDirectory() as d:
            panel = self._panel(_config(d, LAYOUT_BOOK), QWebEngineProfile())
            panel.sync_enabled = True
            to_original = []
            panel.original_view.scroll_to_section = (
                lambda k, s: to_original.append((k, s))
            )
            panel.translation_view.scroll_to_section = lambda k, s: None
            panel._sync_from(panel.original_view, "b2", 0.5, 1, 0.5)
            panel._gesture.settle()
            panel._sync_from(panel.translation_view, "b1", 0.0, 1, 0.2)
            self.assertEqual(len(to_original), 1)

    def test_book_view_still_records_where_the_echoing_edition_is(self):
        with tempfile.TemporaryDirectory() as d:
            panel = self._panel(_config(d, LAYOUT_BOOK), QWebEngineProfile())
            panel.sync_enabled = True
            panel.original_view.scroll_to_section = lambda k, s: None
            panel.translation_view.scroll_to_section = lambda k, s: None
            panel._sync_from(panel.original_view, "b2", 0.5, 1, 0.5)
            panel._sync_from(panel.translation_view, "b1", 0.75, 1, 0.3)
            self.assertEqual(panel._translation_scroll, ("b1", 0.75))

    def test_normal_view_has_no_gesture_guard(self):
        # A hidden tab never mirrors, so the tabbed view needs no guard.
        with tempfile.TemporaryDirectory() as d:
            panel = self._panel(_config(d), QWebEngineProfile())
            self.assertIsNone(panel._gesture)

    def test_search_targets_the_original_without_tabs(self):
        with tempfile.TemporaryDirectory() as d:
            panel = self._panel(_config(d, LAYOUT_BOOK), QWebEngineProfile())
            found = []
            panel.original_view.find = (
                lambda term, forward, cb: found.append(term)
            )
            panel.search("wieczor")
            self.assertEqual(found, ["wieczor"])
            self.assertIs(panel.current_view(), panel.original_view)

    def test_sync_from_with_no_translation_paragraphs_does_not_raise(self):
        with tempfile.TemporaryDirectory() as d:
            panel = self._panel(_config(d), QWebEngineProfile())
            panel.translation_document.block_ids = []
            calls = []
            panel.translation_view.scroll_to_section = (
                lambda k, s: calls.append((k, s))
            )
            panel._sync_from(panel.original_view, "b1", 0.5, 1, 0.5)
            self.assertEqual(calls, [])

    def test_sync_from_with_no_original_paragraphs_does_not_raise(self):
        with tempfile.TemporaryDirectory() as d:
            panel = self._panel(_config(d, LAYOUT_BOOK), QWebEngineProfile())
            panel.original_document.block_ids = []
            calls = []
            panel.original_view.scroll_to_section = (
                lambda k, s: calls.append((k, s))
            )
            panel._sync_from(panel.translation_view, "b1", 0.5, 1, 0.5)
            self.assertEqual(calls, [])
