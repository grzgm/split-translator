import unittest

from split_translator.flashcard_print_layout import (
    PAGE,
    PageSpec,
    grid_dims,
    paginate,
    render_html,
)
from split_translator.flashcards import Card, Sense


def _cards(n):
    return [Card(headword=f"w{i}", id=str(i)) for i in range(n)]


class GridDimsTests(unittest.TestCase):
    def test_a4_8mm_is_two_by_four(self):
        self.assertEqual(grid_dims(PAGE), (2, 4))


class PaginateTests(unittest.TestCase):
    def test_empty_selection_has_no_sheets(self):
        self.assertEqual(paginate([], PAGE), [])

    def test_one_card_makes_a_front_and_a_back_sheet(self):
        sheets = paginate(_cards(1), PAGE)
        self.assertEqual([s["kind"] for s in sheets], ["front", "back"])

    def test_cells_are_padded_to_grid_size(self):
        sheets = paginate(_cards(1), PAGE)
        self.assertEqual(len(sheets[0]["cells"]), 8)
        self.assertEqual(len(sheets[1]["cells"]), 8)
        # front cell 0 is the card, rest None
        self.assertEqual(sheets[0]["cells"][0].id, "0")
        self.assertTrue(all(c is None for c in sheets[0]["cells"][1:]))

    def test_back_columns_are_mirrored_per_row(self):
        # 2 columns: front row [0,1] -> back row [1,0]; front [2,3] -> back [3,2]
        sheets = paginate(_cards(8), PAGE)
        front, back = sheets[0]["cells"], sheets[1]["cells"]
        self.assertEqual([c.id for c in front], ["0", "1", "2", "3", "4", "5", "6", "7"])
        self.assertEqual([c.id for c in back], ["1", "0", "3", "2", "5", "4", "7", "6"])

    def test_ninth_card_starts_a_second_pair_of_sheets(self):
        sheets = paginate(_cards(9), PAGE)
        self.assertEqual([s["kind"] for s in sheets], ["front", "back", "front", "back"])
        self.assertEqual(sheets[2]["cells"][0].id, "8")

    def test_back_mirror_keeps_none_padding_aligned(self):
        # a lone card: back row is [None, card0] so it sits behind front card0
        sheets = paginate(_cards(1), PAGE)
        back = sheets[1]["cells"]
        self.assertIsNone(back[0])
        self.assertEqual(back[1].id, "0")


class RenderHtmlTests(unittest.TestCase):
    def test_contains_page_and_card_dimensions(self):
        html = render_html(_cards(1))
        self.assertIn("@page", html)
        self.assertIn("72mm", html)
        self.assertIn("65mm", html)

    def test_star_only_for_starred_cards(self):
        plain = render_html([Card(headword="x", id="x")])
        starred = render_html([Card(headword="y", id="y", starred=True)])
        self.assertNotIn("star", plain.lower())
        self.assertIn("star", starred.lower())

    def test_overflow_and_border_rules_are_screen_scoped(self):
        html = render_html(_cards(1))
        self.assertIn("@media print", html)
        self.assertIn("is-overflow", html)
        self.assertIn("show-borders", html)

    def test_no_background_colours(self):
        html = render_html(_cards(1))
        self.assertNotIn("wheat", html)

    def test_sense_fields_render(self):
        card = Card(
            headword="abortive", id="z",
            senses=[Sense(pos="v", polish="nieudany", english="fails early")],
        )
        html = render_html([card])
        self.assertIn("abortive", html)
        self.assertIn("nieudany", html)
        self.assertIn("fails early", html)
        self.assertIn("v", html)

    def test_empty_selection_renders_a_document_without_tiles(self):
        html = render_html([])
        self.assertIn("<html", html.lower())
        self.assertNotIn('class="tile', html)


if __name__ == "__main__":
    unittest.main()
