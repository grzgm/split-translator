import unittest

from split_translator.anchor_groups import build_groups
from split_translator.book_align import _bead_anchors, align_batch, fold, tokens

# Invented names, one per story paragraph, shared by both editions the way
# character and place names are. The rest of each paragraph is filler that
# differs between the two languages.
NAMES = [
    "Zorander", "Quillon", "Mervash", "Tolvane", "Brisket", "Kestrin",
    "Halbrook", "Yarrowby", "Durnhelm", "Fenwyck", "Oskarro", "Plimmet",
]
FILLER_ORIGINAL = "walked along the winding road and said nothing to anyone"
FILLER_TRANSLATION = "szedl kreta droga i nie powiedzial nikomu ani slowa"


def _original(name, repeat=1):
    return " ".join(f"{name} {FILLER_ORIGINAL}." for _ in range(repeat))


def _translation(name, repeat=1):
    return " ".join(f"{name} {FILLER_TRANSLATION}." for _ in range(repeat))


def _ids(count, prefix="b"):
    return [f"{prefix}{i}" for i in range(count)]


def _align(original_texts, translation_texts, fixed=(), start=0, count=None,
           original_kept=None, translation_kept=None):
    original_ids = _ids(len(original_texts))
    translation_ids = _ids(len(translation_texts), "t")
    groups = build_groups(list(fixed), original_ids, translation_ids)
    return align_batch(
        original_ids,
        original_texts,
        translation_ids,
        translation_texts,
        groups,
        start,
        len(original_texts) if count is None else count,
        original_kept or range(len(original_texts)),
        translation_kept or range(len(translation_texts)),
    )


class TokenTests(unittest.TestCase):
    def test_fold_drops_diacritics_and_straightens_apostrophes(self):
        l_stroke = chr(0x142)
        curly = chr(0x2019)
        self.assertEqual(fold("G" + l_stroke + "OS"), "glos")
        self.assertEqual(fold("Caf" + chr(0xE9)), "cafe")
        self.assertEqual(fold("Farad" + curly + "n"), "farad'n")

    def test_long_words_are_cut_short_ones_dropped_numbers_kept(self):
        self.assertEqual(
            tokens("The Preacher came in 10191 to Arrakis"),
            ["preac", "came", "#10191", "arrak"],
        )


class BeadAnchorTests(unittest.TestCase):
    ORIGINAL = _ids(6)
    TRANSLATION = _ids(6, "t")

    def _anchors(self, a0, a1, b0, b1):
        return _bead_anchors(self.ORIGINAL, self.TRANSLATION, a0, a1, b0, b1)

    def test_one_to_one_gives_one_anchor(self):
        self.assertEqual(self._anchors(2, 3, 4, 5), [("b2", "t4")])

    def test_one_to_several_anchors_the_first_and_last(self):
        self.assertEqual(self._anchors(2, 3, 1, 4), [("b2", "t1"), ("b2", "t3")])

    def test_several_to_one_anchors_the_first_and_last(self):
        self.assertEqual(self._anchors(2, 4, 1, 2), [("b2", "t1"), ("b3", "t1")])

    def test_two_to_two_gives_two_single_pairs(self):
        self.assertEqual(self._anchors(2, 4, 1, 3), [("b2", "t1"), ("b3", "t2")])


class AlignBatchTests(unittest.TestCase):
    def test_matching_paragraphs_pair_one_to_one(self):
        anchors = _align(
            [_original(n) for n in NAMES[:8]], [_translation(n) for n in NAMES[:8]]
        )
        self.assertEqual(anchors, [(f"b{i}", f"t{i}") for i in range(8)])

    def test_a_paragraph_split_in_the_translation_matches_both_halves(self):
        # b3 holds two names; the translation splits it in two.
        original = [_original(n) for n in NAMES[:8]]
        original[3] = _original(NAMES[3]) + " " + _original(NAMES[10])
        translation = (
            [_translation(n) for n in NAMES[:4]]
            + [_translation(NAMES[10])]
            + [_translation(n) for n in NAMES[4:8]]
        )
        anchors = _align(original, translation)
        self.assertIn(("b3", "t3"), anchors)
        self.assertIn(("b3", "t4"), anchors)
        self.assertIn(("b4", "t5"), anchors)
        self.assertIn(("b7", "t8"), anchors)

    def test_two_paragraphs_joined_in_the_translation_match_it(self):
        original = [_original(n) for n in NAMES[:8]]
        translation = [_translation(n) for n in NAMES[:8]]
        translation[5] = _translation(NAMES[5]) + " " + _translation(NAMES[6])
        del translation[6]
        anchors = _align(original, translation)
        self.assertIn(("b5", "t5"), anchors)
        self.assertIn(("b6", "t5"), anchors)
        self.assertIn(("b7", "t6"), anchors)

    def test_front_matter_only_the_translation_has_is_left_unmatched(self):
        original = [_original(n) for n in NAMES]
        translation = ["Spis", "Tom 1", "Nota"] + [_translation(n) for n in NAMES]
        anchors = _align(original, translation)
        self.assertEqual(anchors[0], ("b0", "t3"))
        self.assertFalse(any(t in ("t0", "t1", "t2") for _o, t in anchors))

    def test_fixed_groups_are_never_touched_and_the_rest_joins_them(self):
        original = [_original(n) for n in NAMES[:8]]
        translation = [_translation(n) for n in NAMES[:8]]
        anchors = _align(original, translation, fixed=[("b4", "t4")])
        self.assertNotIn("b4", [o for o, _t in anchors])
        self.assertNotIn("t4", [t for _o, t in anchors])
        self.assertIn(("b3", "t3"), anchors)
        self.assertIn(("b5", "t5"), anchors)

    def test_only_the_batch_is_anchored(self):
        original = [_original(n) for n in NAMES[:8]]
        translation = [_translation(n) for n in NAMES[:8]]
        anchors = _align(original, translation, start=2, count=3)
        self.assertEqual(anchors, [("b2", "t2"), ("b3", "t3"), ("b4", "t4")])

    def test_paragraphs_outside_the_kept_ranges_are_never_anchored(self):
        original = [_original(n) for n in NAMES[:8]]
        translation = [_translation(n) for n in NAMES[:8]]
        anchors = _align(
            original,
            translation,
            original_kept=range(1, 7),
            translation_kept=range(1, 7),
        )
        self.assertEqual(anchors, [(f"b{i}", f"t{i}") for i in range(1, 7)])

    def test_a_batch_outside_the_kept_range_gives_nothing(self):
        original = [_original(n) for n in NAMES[:8]]
        translation = [_translation(n) for n in NAMES[:8]]
        anchors = _align(
            original, translation, start=6, count=2, original_kept=range(0, 5)
        )
        self.assertEqual(anchors, [])

    def test_the_same_inputs_give_the_same_anchors(self):
        original = [_original(n, 1 + i % 3) for i, n in enumerate(NAMES)]
        translation = [_translation(n, 1 + i % 3) for i, n in enumerate(NAMES)]
        self.assertEqual(_align(original, translation), _align(original, translation))

    def test_a_stretch_much_longer_on_one_side_still_aligns(self):
        # One original paragraph against many translation paragraphs between
        # two fixed groups: the band must widen rather than fail.
        original = [_original(NAMES[0]), _original(NAMES[1]), _original(NAMES[2])]
        translation = (
            [_translation(NAMES[0])]
            + [_translation(NAMES[1])]
            + [f"Przypis {i}." for i in range(80)]
            + [_translation(NAMES[2])]
        )
        anchors = _align(
            original, translation, fixed=[("b0", "t0"), ("b2", "t82")]
        )
        self.assertIn(("b1", "t1"), anchors)


if __name__ == "__main__":
    unittest.main()
