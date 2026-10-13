"""Which sentence of the other edition answers a sentence of this one.

The paragraphs are already known to correspond (they come from one anchor
group), so the question is where the other side was cut, not whether the two
belong together. Sentence counts rarely match: measured over the manual
anchors of a real book pair, two thirds of groups have the same number of
sentences on both sides, a quarter differ by one and a tenth by more, because
a translator splits a line of dialogue or runs two sentences together.

Everything here is pure logic and runs headless."""

import unittest

from split_translator.sentence_sync import counterpart_sentence, split


class SplitTests(unittest.TestCase):
    """The sentence rule: a sentence ends at . ! or ? followed by whitespace or
    the end of the text. It mirrors _SENTENCE_BOUNDS_JS in book_view, which
    does the same cutting in the page; the two must agree, and the sentence
    count travels with every mark so a disagreement is caught rather than
    marking the wrong line."""

    def test_cuts_at_the_three_terminators(self):
        self.assertEqual(
            split("One. Two! Three? Four."),
            ["One.", "Two!", "Three?", "Four."],
        )

    def test_text_with_no_terminator_is_one_sentence(self):
        self.assertEqual(split("No full stop here"), ["No full stop here"])

    def test_a_terminator_not_followed_by_space_does_not_cut(self):
        # Decimal points and ellipses inside a word stay inside the sentence.
        self.assertEqual(split("It cost 3.50 in all."), ["It cost 3.50 in all."])

    def test_trailing_text_after_the_last_terminator_is_kept(self):
        self.assertEqual(split("Done. And more"), ["Done.", "And more"])

    def test_an_empty_text_is_one_empty_sentence(self):
        # One sentence, so a paragraph always has at least one, and a count of
        # 1 means "nothing to distinguish inside it".
        self.assertEqual(split(""), [""])

    def test_an_abbreviation_does_cut(self):
        # A known limitation, left alone: the page splits the same way, so the
        # two sides agree, and the aligner absorbs the extra piece as a
        # one-to-two bead rather than going out of step.
        self.assertEqual(split("Mr. Smith left."), ["Mr.", "Smith left."])


#: Two paragraphs that say the same thing, cut differently. The Polish-like
#: side splits the first sentence in two, as a translator does with dialogue.
HERE = [
    "Fremen must return to Arrakis and to the faith of his fathers in the sand."
    " The Imperium offers him nothing. It will rob him of his soul."
]
THERE = [
    "Fremen musi wrocic na Arrakis. Musi wrocic do wiary ojcow na piasku."
    " Imperium nie oferuje mu niczego. Okradnie go z duszy."
]


class CounterpartSentenceTests(unittest.TestCase):
    def test_a_sentence_split_in_two_maps_to_the_first_half(self):
        # Sentence 1 here became sentences 1 and 2 there; the mark goes on the
        # first, where the sentence starts.
        self.assertEqual(counterpart_sentence(HERE, THERE, 0, 0, 3), (0, 0, 4))

    def test_the_sentences_after_a_split_keep_their_place(self):
        self.assertEqual(counterpart_sentence(HERE, THERE, 0, 1, 3), (0, 2, 4))
        self.assertEqual(counterpart_sentence(HERE, THERE, 0, 2, 3), (0, 3, 4))

    def test_it_reads_back_the_other_way_round(self):
        # The two Polish halves both answer the one English sentence.
        self.assertEqual(counterpart_sentence(THERE, HERE, 0, 0, 4), (0, 0, 3))
        self.assertEqual(counterpart_sentence(THERE, HERE, 0, 1, 4), (0, 0, 3))

    def test_a_group_of_several_paragraphs_counts_across_them(self):
        # A group can cover more than one paragraph a side. Sentences are
        # numbered across the group's text, then turned back into a paragraph
        # and an index within it.
        here = ["One. Two.", "Three. Four."]
        there = ["One. Two. Three.", "Four."]
        self.assertEqual(counterpart_sentence(here, there, 1, 0, 2)[0], 0)
        self.assertEqual(counterpart_sentence(here, there, 1, 1, 2)[0], 1)

    def test_a_count_that_does_not_match_marks_nothing(self):
        # The count comes from the page, which cut the text itself. A
        # disagreement means the index may not mean the same sentence, so
        # nothing is marked and the paragraph mark stands alone.
        self.assertIsNone(counterpart_sentence(HERE, THERE, 0, 0, 9))

    def test_a_single_sentence_on_the_other_side_marks_nothing(self):
        # Marking the only sentence of a paragraph would just repaint the
        # paragraph, which is already marked.
        self.assertIsNone(counterpart_sentence(["A. B."], ["Jedno zdanie."], 0, 0, 2))

    def test_an_index_outside_the_paragraph_marks_nothing(self):
        self.assertIsNone(counterpart_sentence(HERE, THERE, 0, 7, 3))

    def test_a_paragraph_outside_the_group_marks_nothing(self):
        self.assertIsNone(counterpart_sentence(HERE, THERE, 4, 0, 3))

    def test_nothing_on_the_other_side_marks_nothing(self):
        self.assertIsNone(counterpart_sentence(HERE, [], 0, 0, 3))
        self.assertIsNone(counterpart_sentence([], THERE, 0, 0, 3))


if __name__ == "__main__":
    unittest.main()
