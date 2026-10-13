"""The reader marking the matching sentence inside the matching paragraph.

The paragraph marks are unchanged: the sentence mark sits inside them, in a
stronger colour. That layering is what makes a mistaken sentence harmless,
because the passage is still marked and only the line inside it would be
wrong, so the rules here are about when NOT to mark a sentence:

- the paragraph holds one sentence, where the paragraph mark already says
  everything a sentence mark could
- the paragraphs are not an anchored pair, so the counterpart paragraph is an
  estimate and a sentence inside it would be a guess within a guess
- the page counted the paragraph's sentences differently from Python
- a newer search owns the marks by the time this answer arrives

The panel is real and so are its views; only the two marking calls on the
views are recorded, so no page work runs."""

import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWebEngineCore import QWebEngineProfile
from PySide6.QtWidgets import QApplication

from split_translator.anchor_groups import build_groups
from split_translator.book_loader import BookDocument
from split_translator.book_panel import BookPanel
from split_translator.book_sync import SectionMap
from split_translator.config import Config
from split_translator.layout import LAYOUT_NORMAL
from split_translator.normalise_spec import ORIGINAL_SIDE
from tests.fixtures.make_fixtures import make_epub

app = QApplication.instance() or QApplication([])

#: Three paragraphs a side. The middle pair is anchored and holds several
#: sentences, with the translation splitting the original's first one.
ORIGINAL_TEXTS = [
    "Front matter.",
    "Fremen must return to Arrakis and to the faith of his fathers in the deep"
    " desert of the south. The Imperium offers him nothing at all."
    " It will rob him of his soul.",
    "Back matter.",
]
TRANSLATION_TEXTS = [
    "Front matter.",
    "Fremen musi wrocic na Arrakis. Musi wrocic do wiary ojcow na glebokiej"
    " pustyni poludnia. Imperium nie oferuje mu zupelnie niczego."
    " Okradnie go z duszy.",
    "Back matter.",
]
IDS = ["b0", "b1", "b2"]


class SentenceMarkingTests(unittest.TestCase):
    def _panel(self, anchors=(("b1", "b1"),)):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        config = Config(
            name="Test",
            dir=Path(directory.name),
            original_path=make_epub(directory.name),
            translation_path=make_epub(directory.name),
            page_anchors=[],
            layout=LAYOUT_NORMAL,
        )
        panel = BookPanel(config, QWebEngineProfile())
        self.addCleanup(panel.anchor_store.shutdown)
        self.addCleanup(panel.anchor_store.filepath.unlink, missing_ok=True)
        # Swap in texts worth cutting into sentences, and the sections that go
        # with them. The views are left alone; only their marking is recorded.
        panel.original_document = BookDocument(
            html="", block_ids=list(IDS), title="T", block_texts=list(ORIGINAL_TEXTS)
        )
        panel.translation_document = BookDocument(
            html="", block_ids=list(IDS), title="T",
            block_texts=list(TRANSLATION_TEXTS),
        )
        panel.section_map = SectionMap(
            IDS,
            ORIGINAL_TEXTS,
            IDS,
            TRANSLATION_TEXTS,
            build_groups(list(anchors), IDS, IDS),
            original_kept=range(1, 2),
            translation_kept=range(1, 2),
        )
        panel.search_term = "faith"
        panel.current_match = 1
        self.marks = {"original": [], "translation": []}
        for name, view in (
            ("original", panel.original_view),
            ("translation", panel.translation_view),
        ):
            view.mark_sentence = (
                lambda bid, index, count, word=None, n=name:
                    self.marks[n].append((bid, index, count, word))
            )
            view.clear_sentence_mark = (
                lambda n=name: self.marks[n].append("cleared")
            )
        return panel

    def _answer(
        self, panel, index, count, term=None, match=None, other=True, word=(0, 6)
    ):
        """The page's answer arriving: sentence `index` of `count` in b1, with
        the found word at `word` within the paragraph."""
        BookPanel._on_match_sentence(
            panel,
            panel.original_view,
            panel.translation_view if other else None,
            "b1",
            term if term is not None else panel.search_term,
            match if match is not None else panel.current_match,
            index,
            count,
            word,
        )

    def test_both_sides_are_marked(self):
        panel = self._panel()
        self._answer(panel, 0, 3)
        # The original's first sentence, and the two Polish sentences it became
        # are answered by the first of them.
        self.assertEqual(self.marks["original"], [("b1", 0, 3, (0, 6))])
        # The other edition has no match in it to leave out.
        self.assertEqual(self.marks["translation"], [("b1", 0, 4, None)])

    def test_a_later_sentence_keeps_its_place_past_the_split(self):
        panel = self._panel()
        self._answer(panel, 1, 3)
        self.assertEqual(self.marks["original"], [("b1", 1, 3, (0, 6))])
        self.assertEqual(self.marks["translation"], [("b1", 2, 4, None)])

    def test_a_paragraph_of_one_sentence_is_not_marked(self):
        panel = self._panel()
        self._answer(panel, 0, 1)
        self.assertEqual(self.marks["original"], ["cleared"])

    def test_no_match_clears_both(self):
        panel = self._panel()
        self._answer(panel, -1, 0)
        self.assertEqual(self.marks["original"], ["cleared"])
        self.assertEqual(self.marks["translation"], ["cleared"])

    def test_a_paragraph_outside_a_group_clears_the_other_side(self):
        # No anchors, so b1's counterpart is an estimate between anchors.
        panel = self._panel(anchors=())
        self._answer(panel, 0, 3)
        self.assertEqual(self.marks["original"], [("b1", 0, 3, (0, 6))])
        self.assertEqual(self.marks["translation"], ["cleared"])

    def test_a_count_the_page_disagrees_with_clears_the_other_side(self):
        # The page counted nine sentences where Python counts three, so the
        # index cannot be trusted to mean the same sentence.
        panel = self._panel()
        self._answer(panel, 0, 9)
        self.assertEqual(self.marks["translation"], ["cleared"])

    def test_a_stale_answer_is_dropped(self):
        # A newer search owns the marks; its own answer is on its way.
        panel = self._panel()
        self._answer(panel, 0, 3, term="other")
        self._answer(panel, 0, 3, match=7)
        self.assertEqual(self.marks["original"], [])
        self.assertEqual(self.marks["translation"], [])

    def test_with_sync_off_only_the_searched_edition_is_marked(self):
        panel = self._panel()
        self._answer(panel, 0, 3, other=False)
        self.assertEqual(self.marks["original"], [("b1", 0, 3, (0, 6))])
        self.assertEqual(self.marks["translation"], [])

    def test_the_read_is_asked_for_with_the_current_term_and_match(self):
        panel = self._panel()
        asked = []
        panel.original_view.match_sentence_at = (
            lambda term, index, cb: asked.append((term, index))
        )
        BookPanel._mark_sentences(
            panel, panel.original_view, panel.translation_view, "b1"
        )
        self.assertEqual(asked, [("faith", 1)])


if __name__ == "__main__":
    unittest.main()
