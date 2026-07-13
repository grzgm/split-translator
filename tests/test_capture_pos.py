"""Each dictionary site labels a sense's part of speech in its own words and its
own markup, so each gets its own label map and its own lookup rule.

The lookup itself is injected JavaScript and needs a live page, so it cannot be
unit tested; it was derived from and verified against the real bab.la, diki and
Cambridge pages. What is tested here is everything that surrounds it and that a
wrong edit would silently break:

  - every code a map can produce is one the editor's dropdown actually offers,
    because a capture writes the code straight into that dropdown;
  - each view is injected with its own site's rule and map, not another site's;
  - the maps carry the spellings the live pages really use (bab.la abbreviates
    inconsistently, which is easy to get wrong and fails silently);
  - labels that are not parts of speech are absent, so they yield no code rather
    than a wrong one."""

import json
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from PySide6.QtWebEngineCore import QWebEngineProfile

from split_translator.dictionary_panel import DictionaryPanel
from split_translator.flashcard_editor_base import SenseRow

app = QApplication.instance() or QApplication([])


def _panel():
    return DictionaryPanel(QWebEngineProfile.defaultProfile())


ALL_MAPS = {
    "cambridge": DictionaryPanel._POS_MAP,
    "babla": DictionaryPanel._BABLA_POS_MAP,
    "diki": DictionaryPanel._DIKI_POS_MAP,
}


class PosMapTests(unittest.TestCase):
    def test_every_mapped_code_is_offered_by_the_editor(self):
        # A capture writes its code straight into the sense combo, so a code the
        # combo does not offer would be written and then not be selectable.
        for site, pos_map in ALL_MAPS.items():
            for label, code in pos_map.items():
                self.assertIn(code, SenseRow.POS_OPTIONS, f"{site}: {label}")

    def test_babla_carries_both_spellings_of_its_labels(self):
        # bab.la abbreviates inconsistently: "{noun}" and "{vb}" are spelled out
        # but "{adj.}", "{adv.}" and "{conj.}" are truncated with a trailing dot.
        # A map with only the long forms resolves nothing for those, and does so
        # silently, which is exactly the bug this guards.
        pos_map = DictionaryPanel._BABLA_POS_MAP
        for short, long, code in [
            ("vb", "verb", "v"),
            ("adj.", "adjective", "adj"),
            ("adv.", "adverb", "adv"),
            ("conj.", "conjunction", "con"),
            ("prep.", "preposition", "pre"),
            ("pron.", "pronoun", "pro"),
        ]:
            self.assertEqual(pos_map.get(short), code, short)
            self.assertEqual(pos_map.get(long), code, long)

    def test_babla_does_not_map_its_non_pos_labels(self):
        # bab.la reuses span.suffix for gender, verb aspect, plural and
        # conjugation hints. None is a part of speech; each must yield no code
        # rather than a wrong one.
        pos_map = DictionaryPanel._BABLA_POS_MAP
        for label in ["f", "m", "pl", "plural", "ipf. v.", "pf. v.", "r. v.",
                      "fig.", "ex."]:
            self.assertNotIn(label, pos_map, label)

    def test_diki_labels_are_polish(self):
        pos_map = DictionaryPanel._DIKI_POS_MAP
        self.assertEqual(pos_map["rzeczownik"], "n")
        self.assertEqual(pos_map["czasownik"], "v")
        self.assertEqual(pos_map["przymiotnik"], "adj")
        self.assertEqual(pos_map["przysłówek"], "adv")


class PosRuleTests(unittest.TestCase):
    """The rule says where a site puts the label relative to the element the
    capture button is attached to."""

    def test_cambridge_looks_in_an_ancestor(self):
        rule = DictionaryPanel._CAMBRIDGE_POS_RULE
        self.assertEqual(rule["mode"], "ancestor")
        self.assertEqual(rule["label"], ".pos.dpos")
        # The definition block is the most specific container and must be tried
        # before the entry body it sits in, or a page with several parts of
        # speech would tag every sense with the first one.
        self.assertEqual(rule["containers"][0], ".def-block")

    def test_babla_looks_back_from_the_translation_wrapper(self):
        # The heading is a *preceding sibling*, not an ancestor. It is a sibling
        # of the wrapper around the list (div.quick-result-overview), not of the
        # list itself, whose own previous sibling is only a language flag.
        # Anchoring on the list finds nothing at all, silently.
        rule = DictionaryPanel._BABLA_POS_RULE
        self.assertEqual(rule["mode"], "sibling")
        self.assertEqual(rule["list"], "div.quick-result-overview")
        self.assertEqual(rule["strip"], "{}")

    def test_diki_looks_back_from_the_meanings_list(self):
        rule = DictionaryPanel._DIKI_POS_RULE
        self.assertEqual(rule["mode"], "sibling")
        self.assertEqual(rule["list"], "ol.foreignToNativeMeanings")
        self.assertEqual(rule["label"], "span.partOfSpeech")

    def test_a_sibling_rule_needs_a_list_to_climb_to(self):
        for rule in [DictionaryPanel._BABLA_POS_RULE,
                     DictionaryPanel._DIKI_POS_RULE]:
            self.assertTrue(rule.get("list"))
            self.assertTrue(rule.get("label"))


class CaptureConfigTests(unittest.TestCase):
    """Each view must be injected with its own site's rule and map."""

    def test_each_site_gets_its_own_rule_and_map(self):
        panel = _panel()
        by_view = {
            view: (rule, pos_map)
            for view, _pairs, rule, pos_map in panel._capture_config()
        }
        self.assertEqual(
            by_view[panel.babla_view],
            (DictionaryPanel._BABLA_POS_RULE, DictionaryPanel._BABLA_POS_MAP),
        )
        self.assertEqual(
            by_view[panel.diki_view],
            (DictionaryPanel._DIKI_POS_RULE, DictionaryPanel._DIKI_POS_MAP),
        )
        self.assertEqual(
            by_view[panel.cambridge_en_view],
            (DictionaryPanel._CAMBRIDGE_POS_RULE, DictionaryPanel._POS_MAP),
        )
        self.assertEqual(
            by_view[panel.cambridge_pl_view],
            (DictionaryPanel._CAMBRIDGE_POS_RULE, DictionaryPanel._POS_MAP),
        )

    def test_the_google_pane_captures_without_a_part_of_speech(self):
        # Google's translation widget carries no part-of-speech markup, so it
        # gets an empty rule and sends no code, as it always has.
        panel = _panel()
        for view, _pairs, rule, pos_map in panel._capture_config():
            if view is panel.google_translate_search:
                self.assertEqual(rule, {})
                self.assertEqual(pos_map, {})
                return
        self.fail("the Google pane is not in the capture config")

    def test_every_configured_view_still_captures_polish(self):
        # Whatever else changes, each of these panes exists to capture a Polish
        # translation into the card.
        panel = _panel()
        for view, pairs, _rule, _map in panel._capture_config():
            if view is panel.cambridge_en_view:
                continue  # the English page has no translations
            fields = {p["field"] for p in pairs}
            self.assertIn("polish", fields)


class CaptureScriptTests(unittest.TestCase):
    """The generated script must carry the right site's data and no leftovers."""

    def test_script_substitutes_the_given_rule_and_map(self):
        panel = _panel()
        js = panel._capture_js(
            DictionaryPanel._DIKI_CAPTURE_PAIRS,
            DictionaryPanel._DIKI_POS_RULE,
            DictionaryPanel._DIKI_POS_MAP,
        )
        self.assertIn(json.dumps(DictionaryPanel._DIKI_POS_RULE), js)
        self.assertIn(json.dumps(DictionaryPanel._DIKI_POS_MAP), js)
        # and not another site's
        self.assertNotIn(json.dumps(DictionaryPanel._BABLA_POS_MAP), js)

    def test_no_placeholder_survives_substitution(self):
        # A placeholder left in place is a JavaScript syntax error, and the
        # script fails silently on the page.
        panel = _panel()
        for _view, pairs, rule, pos_map in panel._capture_config():
            js = panel._capture_js(pairs, rule, pos_map)
            for placeholder in ["__PAIRS__", "__POS_MAP__", "__POS_RULE__",
                                "__CHANNEL_JS__", "__BLOCK_PRON_JS__"]:
                self.assertNotIn(placeholder, js, placeholder)


if __name__ == "__main__":
    unittest.main()
