"""The three tabbed dictionary views share one slot on screen, so a search loads
only the tab on show and holds the other two until they are revealed.

Before this, every search started six page loads, two of which nobody could see
(bab.la and diki sit behind the default "Meaning" tab). Those two are now loaded
on first reveal instead.

The loads are asynchronous, so these tests assert on what the panel decided to do
(the recorded URL, and the setUrl calls it made) rather than on a rendered page,
which would be a race."""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from PySide6.QtWebEngineCore import QWebEngineProfile

from split_translator.dictionary_panel import DictionaryPanel

app = QApplication.instance() or QApplication([])

MEANING, BABLA, DIKI = 0, 1, 2


class LazyTabTests(unittest.TestCase):
    def setUp(self):
        self.panel = DictionaryPanel(QWebEngineProfile.defaultProfile())
        # Record every load the panel asks for, without performing it: a real
        # load is asynchronous and needs the network, and what is under test is
        # which loads the panel decides to make.
        self.loaded = []
        for view in self.panel._all_views():
            view.setUrl = lambda url, v=view: self.loaded.append((v, url.toString()))

    def _search(self, word="shed"):
        self.panel.search_input.setText(word)
        self.panel.search()

    def _loaded_views(self):
        return [view for view, _url in self.loaded]

    def _pending(self, view):
        return self.panel._pending_urls.get(view)

    # --- what a search loads and what it holds back ---------------------

    def test_search_loads_the_always_visible_views(self):
        # Both Cambridge panes and the Google "po polsku" pane live in the
        # splitter, always on screen. They are unaffected by any of this.
        self._search()
        for view in [
            self.panel.cambridge_en_view,
            self.panel.cambridge_pl_view,
            self.panel.google_translate_search,
        ]:
            self.assertIn(view, self._loaded_views())

    def test_search_loads_only_the_current_tab(self):
        self._search()
        self.assertIn(self.panel.google_meaning_view, self._loaded_views())
        self.assertNotIn(self.panel.babla_view, self._loaded_views())
        self.assertNotIn(self.panel.diki_view, self._loaded_views())

    def test_the_hidden_tabs_remember_what_they_owe(self):
        self._search("shed")
        self.assertEqual(
            self._pending(self.panel.babla_view),
            "https://en.bab.la/dictionary/english-polish/shed",
        )
        self.assertEqual(
            self._pending(self.panel.diki_view), "https://www.diki.pl/shed"
        )

    def test_the_current_tab_owes_nothing(self):
        self._search()
        self.assertIsNone(self._pending(self.panel.google_meaning_view))

    # --- what a reveal does ---------------------------------------------

    def test_revealing_a_tab_loads_what_it_owed(self):
        self._search("shed")
        self.panel.google_tabs.setCurrentIndex(BABLA)
        self.assertIn(
            (self.panel.babla_view,
             "https://en.bab.la/dictionary/english-polish/shed"),
            self.loaded,
        )

    def test_revealing_one_tab_does_not_load_the_other(self):
        self._search()
        self.panel.google_tabs.setCurrentIndex(BABLA)
        self.assertNotIn(self.panel.diki_view, self._loaded_views())
        self.assertIsNotNone(self._pending(self.panel.diki_view))

    def test_a_revealed_tab_owes_nothing_afterwards(self):
        self._search()
        self.panel.google_tabs.setCurrentIndex(DIKI)
        self.assertIsNone(self._pending(self.panel.diki_view))

    def test_switching_back_and_forth_does_not_reload(self):
        # The page is kept once loaded, so flipping between tabs is instant and
        # costs nothing. Only the first reveal after a search pays for a load.
        self._search()
        self.panel.google_tabs.setCurrentIndex(BABLA)
        self.loaded.clear()
        self.panel.google_tabs.setCurrentIndex(MEANING)
        self.panel.google_tabs.setCurrentIndex(BABLA)
        self.assertEqual(self.loaded, [])

    def test_revealing_a_tab_with_nothing_owed_loads_nothing(self):
        # No search has run, so there is nothing to show.
        self.panel.google_tabs.setCurrentIndex(DIKI)
        self.assertEqual(self.loaded, [])

    # --- searching while a tab is hidden --------------------------------

    def test_the_newest_search_wins(self):
        # Three searches while bab.la is hidden must not queue three loads. Only
        # the last word is the one being looked up.
        self._search("shed")
        self._search("run")
        self._search("quickly")
        self.assertEqual(
            self._pending(self.panel.babla_view),
            "https://en.bab.la/dictionary/english-polish/quickly",
        )
        self.panel.google_tabs.setCurrentIndex(BABLA)
        babla_loads = [
            url for view, url in self.loaded if view is self.panel.babla_view
        ]
        self.assertEqual(
            babla_loads, ["https://en.bab.la/dictionary/english-polish/quickly"]
        )

    def test_a_search_while_a_tab_is_shown_loads_it_immediately(self):
        # Once bab.la is the tab on show, it is no different from the always
        # visible panes: a search loads it there and then.
        self.panel.google_tabs.setCurrentIndex(BABLA)
        self.loaded.clear()
        self._search("run")
        self.assertIn(
            (self.panel.babla_view,
             "https://en.bab.la/dictionary/english-polish/run"),
            self.loaded,
        )
        self.assertIsNone(self._pending(self.panel.babla_view))

    def test_the_tab_that_is_now_hidden_is_deferred_instead(self):
        # The Meaning tab is not privileged; it is deferred like any other once
        # it is the one out of sight.
        self.panel.google_tabs.setCurrentIndex(DIKI)
        self.loaded.clear()
        self._search("run")
        self.assertNotIn(self.panel.google_meaning_view, self._loaded_views())
        self.assertEqual(
            self._pending(self.panel.google_meaning_view),
            "https://www.google.pl/search?q=run+meaning",
        )
        self.assertIn(self.panel.diki_view, self._loaded_views())

    def test_a_stale_pending_url_is_replaced_not_kept(self):
        # Search, reveal (consuming the URL), search again while hidden: the tab
        # must owe the new word, not still be holding the old one.
        self._search("shed")
        self.panel.google_tabs.setCurrentIndex(BABLA)
        self.panel.google_tabs.setCurrentIndex(MEANING)
        self._search("run")
        self.assertEqual(
            self._pending(self.panel.babla_view),
            "https://en.bab.la/dictionary/english-polish/run",
        )


class TabVisibilityTests(unittest.TestCase):
    """Only the tabbed views can be hidden; the splitter views never are."""

    def setUp(self):
        self.panel = DictionaryPanel(QWebEngineProfile.defaultProfile())

    def test_the_splitter_views_are_always_visible(self):
        for view in [
            self.panel.cambridge_en_view,
            self.panel.cambridge_pl_view,
            self.panel.google_translate_search,
        ]:
            self.assertTrue(self.panel._is_tab_visible(view))

    def test_only_the_current_tab_is_visible(self):
        self.assertTrue(self.panel._is_tab_visible(self.panel.google_meaning_view))
        self.assertFalse(self.panel._is_tab_visible(self.panel.babla_view))
        self.assertFalse(self.panel._is_tab_visible(self.panel.diki_view))

    def test_visibility_follows_the_current_tab(self):
        self.panel.google_tabs.setCurrentIndex(DIKI)
        self.assertTrue(self.panel._is_tab_visible(self.panel.diki_view))
        self.assertFalse(self.panel._is_tab_visible(self.panel.google_meaning_view))


if __name__ == "__main__":
    unittest.main()
