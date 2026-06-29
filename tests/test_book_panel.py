import unittest

from PySide6.QtWidgets import QApplication
from PySide6.QtWebEngineCore import QWebEngineProfile

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
        profile = QWebEngineProfile()
        view = BookView(_doc(), profile, initial_scroll=("b1", 0.5))
        view.scroll_to = lambda bid, frac: None  # stub out the JS scroll
        emitted = []
        view.scrolled.connect(lambda bid, frac: emitted.append((bid, frac)))
        view._restore_initial_scroll(True)
        self.assertEqual(emitted, [("b1", 0.5)])

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


import tempfile

from split_translator.config import Config
from split_translator.book_panel import BookPanel
from tests.fixtures.make_fixtures import make_epub


def _config(d):
    epub = make_epub(d)
    return Config(
        original_path=epub,
        translation_path=epub,
        page_anchors=[],
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


from split_translator.book_sync import BookSync


class BookPanelSyncWiringTests(unittest.TestCase):
    def test_panel_builds_a_book_sync_and_anchor_store(self):
        with tempfile.TemporaryDirectory() as d:
            profile = QWebEngineProfile()
            panel = BookPanel(_config(d), profile)
            self.addCleanup(panel.anchor_store.shutdown)
            self.assertIsInstance(panel.book_sync, BookSync)
            self.assertTrue(callable(panel._sync_from))

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

            from split_translator.anchor_store import AnchorStore, READER_SURFACE

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
                AnchorStore,
                READER_SURFACE,
                anchor_path_for,
            )
            from split_translator.config import CONFIG_DIR

            path = anchor_path_for(
                cfg.original_path, cfg.translation_path, CONFIG_DIR
            )
            seed = AnchorStore(path)
            seed.set_scroll(READER_SURFACE, ("b1", 0.0), ("b1", 0.0))
            seed.shutdown()
            self.addCleanup(path.unlink, missing_ok=True)

            panel = self._panel(cfg, profile)
            self.assertEqual(panel.original_view._initial_scroll, ("b1", 0.0))
            self.assertEqual(panel.translation_view._initial_scroll, ("b1", 0.0))


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

    def test_mirror_records_the_mapped_target_for_the_hidden_side(self):
        # The core fix: mirroring a scroll on the active Original records the
        # anchor-MAPPED target for the hidden Translation (not the hidden view's
        # own drifted report). The fixture uses one book for both editions, so
        # the mapping is identity: original "b1" maps to translation "b1". (The
        # exact fraction is set by the anchor interpolation, so we assert the
        # block id and that the cache and target agree.)
        with tempfile.TemporaryDirectory() as d:
            profile = QWebEngineProfile()
            panel = self._panel(_config(d), profile)
            # Original is the current tab (index 0). Stub the hidden view scroll
            # so no real JS runs.
            panel.translation_view.scroll_to = lambda bid, frac: None
            bid = panel.original_document.block_ids[1]
            panel._sync_from(panel.original_view, bid, 0.25)
            self.assertIsNotNone(panel._translation_sync_target)
            self.assertEqual(panel._translation_sync_target[0], bid)
            # The cache holds the same mapped target, so close persists it.
            self.assertEqual(
                panel._translation_scroll, panel._translation_sync_target
            )

    def test_switch_reapplies_the_mapped_target_over_a_drifted_cache(self):
        # Even if the scroll cache somehow held a wrong (drifted) value, the
        # switch must prefer the mapped sync target.
        with tempfile.TemporaryDirectory() as d:
            profile = QWebEngineProfile()
            panel = self._panel(_config(d), profile)
            panel._translation_sync_target = ("b3", 0.25)
            panel._translation_scroll = ("b99", 0.99)  # a drifted/wrong cache
            calls = []
            panel.translation_view.reapply_scroll = (
                lambda b, f: calls.append((b, f))
            )
            panel.tabs.setCurrentIndex(1)
            self.assertEqual(calls, [("b3", 0.25)])  # mapped target wins

    def test_hidden_view_drift_echo_is_ignored(self):
        # A scroll reported by the hidden tab while it has a pending mapped
        # target is a drift echo; it must not corrupt the cache or the target.
        with tempfile.TemporaryDirectory() as d:
            profile = QWebEngineProfile()
            panel = self._panel(_config(d), profile)
            # Original is current; arm a pending target for the hidden
            # Translation and a correct cache.
            panel._translation_sync_target = ("b3", 0.25)
            panel._translation_scroll = ("b3", 0.25)
            # The hidden Translation drifts and reports a wrong end position.
            panel._sync_from(panel.translation_view, "b99", 0.99)
            self.assertEqual(panel._translation_scroll, ("b3", 0.25))  # untouched
            self.assertEqual(panel._translation_sync_target, ("b3", 0.25))

    def test_user_scrolling_active_tab_clears_its_sync_target(self):
        # Once the user moves the active tab themselves, its mapped target is
        # stale and must be cleared, so a later switch back honours the user's
        # real position, not an old mapped one.
        with tempfile.TemporaryDirectory() as d:
            profile = QWebEngineProfile()
            panel = self._panel(_config(d), profile)
            panel.original_view.scroll_to = lambda bid, frac: None
            panel.translation_view.scroll_to = lambda bid, frac: None
            panel._original_sync_target = ("b0", 0.0)  # a stale mapped target
            bid = panel.original_document.block_ids[2]
            panel._sync_from(panel.original_view, bid, 0.5)  # user scrolls
            self.assertIsNone(panel._original_sync_target)


class BookPanelEditorTests(unittest.TestCase):
    def test_open_anchor_editor_is_callable_and_reseeds_sync(self):
        with tempfile.TemporaryDirectory() as d:
            profile = QWebEngineProfile()
            panel = BookPanel(_config(d), profile)
            self.addCleanup(panel.anchor_store.shutdown)
            self.assertTrue(callable(panel.open_anchor_editor))
            # Simulate an anchor change and confirm sync re-seeds without error.
            panel.anchor_store.anchors = [
                (
                    panel.original_document.block_ids[0],
                    panel.translation_document.block_ids[0],
                )
            ]
            panel._reseed_sync()
            self.assertIn(
                (0, 0), panel.book_sync.get_anchors()
            )
