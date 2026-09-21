import subprocess
import sys
import unittest

from split_translator.block_ids import resolve_block_id, resolve_position


class ResolveBlockIdTests(unittest.TestCase):
    """A stored id can stop being a paragraph (a spacer lost its id), so it is
    resolved to the nearest paragraph by number."""

    IDS = ["b0", "b3", "b7"]

    def test_a_paragraph_id_resolves_to_itself(self):
        self.assertEqual(resolve_block_id(self.IDS, "b3"), "b3")

    def test_a_lost_id_moves_forward_to_the_next_paragraph(self):
        self.assertEqual(resolve_block_id(self.IDS, "b4"), "b7")

    def test_a_lost_id_moves_back_when_asked(self):
        self.assertEqual(resolve_block_id(self.IDS, "b4", forward=False), "b3")

    def test_past_the_last_paragraph_it_falls_back_to_the_last(self):
        self.assertEqual(resolve_block_id(self.IDS, "b9"), "b7")

    def test_before_the_first_paragraph_moving_back_falls_forward(self):
        self.assertEqual(resolve_block_id(["b2", "b5"], "b1", forward=False), "b2")

    def test_an_unreadable_id_resolves_to_nothing(self):
        self.assertIsNone(resolve_block_id(self.IDS, ""))
        self.assertIsNone(resolve_block_id(self.IDS, "chapter1"))

    def test_no_paragraphs_resolve_to_nothing(self):
        self.assertIsNone(resolve_block_id([], "b1"))


class ResolvePositionTests(unittest.TestCase):
    def test_a_position_on_a_paragraph_is_unchanged(self):
        self.assertEqual(resolve_position(["b0", "b3"], ("b3", 0.4)), ("b3", 0.4))

    def test_a_position_on_a_lost_block_starts_at_the_next_paragraph(self):
        # The fraction belonged to the lost block, so it is not carried over.
        self.assertEqual(resolve_position(["b0", "b3"], ("b1", 0.4)), ("b3", 0.0))

    def test_no_position_stays_none(self):
        self.assertIsNone(resolve_position(["b0"], None))

    def test_an_unresolvable_position_becomes_none(self):
        self.assertIsNone(resolve_position([], ("b1", 0.2)))


class ImportTests(unittest.TestCase):
    def test_the_section_logic_does_not_load_the_pdf_library(self):
        # book_sync and the aligner handle ids and text only; loading them must
        # not pull in pymupdf, which only the book loader needs.
        code = (
            "import sys, split_translator.book_sync; "
            "print('pymupdf' in sys.modules)"
        )
        result = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True, check=True
        )
        self.assertEqual(result.stdout.strip(), "False")


if __name__ == "__main__":
    unittest.main()
