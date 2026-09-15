import unittest

from split_translator.anchor_groups import build_groups
from split_translator.book_sync import SectionMap
from split_translator.normalise_spec import ORIGINAL_SIDE, TRANSLATION_SIDE

ORIGINAL_IDS = [f"b{i}" for i in range(6)]
TRANSLATION_IDS = [f"b{i}" for i in range(8)]


def _map(anchors=(), original_texts=None, translation_texts=None):
    groups = build_groups(list(anchors), ORIGINAL_IDS, TRANSLATION_IDS)
    return SectionMap(
        ORIGINAL_IDS,
        original_texts if original_texts is not None else ["x" * 10] * 6,
        TRANSLATION_IDS,
        translation_texts if translation_texts is not None else ["x" * 10] * 8,
        groups,
    )


class SectionMapTests(unittest.TestCase):
    def test_without_anchors_there_is_front_matter_one_stretch_and_back_matter(self):
        sections = _map()
        self.assertEqual(sections.section_count, 3)
        self.assertEqual(
            sections.section_starts(ORIGINAL_SIDE), ["top", "b0", "end"]
        )
        self.assertEqual(
            sections.section_starts(TRANSLATION_SIDE), ["top", "b0", "end"]
        )

    def test_a_group_splits_the_book_into_stretch_group_stretch(self):
        sections = _map([("b2", "b3")])
        self.assertEqual(
            sections.section_starts(ORIGINAL_SIDE),
            ["top", "b0", "b2", "b3", "end"],
        )
        self.assertEqual(
            sections.section_starts(TRANSLATION_SIDE),
            ["top", "b0", "b3", "b4", "end"],
        )

    def test_a_stretch_empty_on_both_sides_is_left_out(self):
        sections = _map([("b0", "b0")])
        self.assertEqual(
            sections.section_starts(ORIGINAL_SIDE), ["top", "b0", "b1", "end"]
        )

    def test_a_stretch_empty_on_one_side_starts_at_the_next_section_there(self):
        # Only the original has a paragraph before b1 = b0.
        sections = _map([("b1", "b0")])
        self.assertEqual(
            sections.section_starts(ORIGINAL_SIDE),
            ["top", "b0", "b1", "b2", "end"],
        )
        self.assertEqual(
            sections.section_starts(TRANSLATION_SIDE),
            ["top", "b0", "b0", "b1", "end"],
        )

    def test_a_stretch_empty_at_the_end_of_a_side_starts_at_end(self):
        sections = _map([("b5", "b3")])
        self.assertEqual(
            sections.section_starts(ORIGINAL_SIDE),
            ["top", "b0", "b5", "end", "end"],
        )
        self.assertEqual(
            sections.section_starts(TRANSLATION_SIDE),
            ["top", "b0", "b3", "b4", "end"],
        )

    def test_section_of_finds_the_section_holding_a_paragraph(self):
        sections = _map([("b2", "b3")])
        self.assertEqual(sections.section_of(ORIGINAL_SIDE, "b1"), 1)
        self.assertEqual(sections.section_of(ORIGINAL_SIDE, "b2"), 2)
        self.assertEqual(sections.section_of(ORIGINAL_SIDE, "b4"), 3)
        self.assertEqual(sections.section_of(TRANSLATION_SIDE, "b3"), 2)
        with self.assertRaises(KeyError):
            sections.section_of(ORIGINAL_SIDE, "b99")

    def test_a_paragraph_in_a_group_marks_the_whole_other_extent(self):
        sections = _map([("b2", "b3"), ("b2", "b5")])
        self.assertEqual(
            sections.counterpart(ORIGINAL_SIDE, "b2"), ["b3", "b4", "b5"]
        )
        self.assertEqual(sections.counterpart(TRANSLATION_SIDE, "b4"), ["b2"])

    def test_a_paragraph_in_a_stretch_marks_the_paragraph_at_the_same_text_share(self):
        # Six original paragraphs of 10 characters; the translation's first
        # paragraph is 30 characters and the other seven are 10 (100 in all).
        sections = _map(translation_texts=["x" * 30] + ["x" * 10] * 7)
        # b0's middle is 5 of 60 characters in: 8.3 of 100 lands in b0.
        self.assertEqual(sections.counterpart(ORIGINAL_SIDE, "b0"), ["b0"])
        # b2's middle is 25 of 60: 41.7 lands in b2 (40 to 50).
        self.assertEqual(sections.counterpart(ORIGINAL_SIDE, "b2"), ["b2"])
        # b5's middle is 55 of 60: 91.7 lands in b7 (90 to 100).
        self.assertEqual(sections.counterpart(ORIGINAL_SIDE, "b5"), ["b7"])

    def test_nothing_is_marked_when_the_other_side_of_the_section_is_empty(self):
        sections = _map([("b1", "b0")])
        self.assertEqual(sections.counterpart(ORIGINAL_SIDE, "b0"), [])

    def test_an_unknown_paragraph_has_no_counterpart(self):
        self.assertEqual(_map().counterpart(ORIGINAL_SIDE, "b99"), [])

    def test_paragraph_at_walks_the_section_text(self):
        sections = _map()
        self.assertEqual(sections.paragraph_at(ORIGINAL_SIDE, 1, 0.5), ("b3", 0.0))
        paragraph, fraction = sections.paragraph_at(ORIGINAL_SIDE, 1, 0.55)
        self.assertEqual(paragraph, "b3")
        self.assertAlmostEqual(fraction, 0.3)
        self.assertEqual(sections.paragraph_at(ORIGINAL_SIDE, 1, 1.0), ("b5", 1.0))
        self.assertEqual(sections.paragraph_at(ORIGINAL_SIDE, 1, -0.2), ("b0", 0.0))

    def test_paragraph_at_an_empty_section_uses_the_next_paragraph(self):
        sections = _map()
        self.assertEqual(sections.paragraph_at(ORIGINAL_SIDE, 0, 0.5), ("b0", 0.0))
        # Back matter has nothing after it: the end of the last paragraph.
        self.assertEqual(sections.paragraph_at(ORIGINAL_SIDE, 2, 0.5), ("b5", 1.0))

    def test_an_edition_with_no_paragraphs(self):
        sections = SectionMap([], [], TRANSLATION_IDS, ["x"] * 8, [])
        self.assertEqual(
            sections.section_starts(ORIGINAL_SIDE), ["top", "end", "end"]
        )
        self.assertEqual(sections.paragraph_at(ORIGINAL_SIDE, 1, 0.5), ("", 0.0))
        self.assertEqual(sections.counterpart(TRANSLATION_SIDE, "b0"), [])

    def test_paragraphs_without_text_weigh_one_character(self):
        sections = SectionMap(ORIGINAL_IDS, [], TRANSLATION_IDS, [], [])
        self.assertEqual(sections.paragraph_at(ORIGINAL_SIDE, 1, 0.5), ("b3", 0.0))
