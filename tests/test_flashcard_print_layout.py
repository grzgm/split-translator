import unittest

from split_translator.flashcard_print_layout import (
    PAGE,
    PageSpec,
    example_fill_order,
    grid_dims,
    paginate,
    render_card_tile,
    render_html,
)
from split_translator.flashcards import Card, Sense


def _cards(n):
    return [Card(headword=f"w{i}", id=str(i)) for i in range(n)]


class ExampleFillOrderTests(unittest.TestCase):
    """A tile clips what does not fit, so the fill order decides which examples
    survive. Interleaving the senses means every sense is represented before any
    sense gets a second example; the view regroups the survivors by sense for
    display."""

    def _card(self, *example_lists):
        return Card(
            headword="w", id="w",
            senses=[Sense(pos="p", examples=list(e)) for e in example_lists],
        )

    def test_takes_the_first_of_each_sense_before_any_second(self):
        card = self._card(["a1", "a2", "a3"], ["b1", "b2"])
        self.assertEqual(
            example_fill_order(card),
            [(0, "a1"), (1, "b1"), (0, "a2"), (1, "b2"), (0, "a3")],
        )

    def test_a_sense_that_runs_out_is_skipped_not_padded(self):
        # Sense b has one example; later rounds must simply pass it by.
        card = self._card(["a1", "a2", "a3"], ["b1"])
        self.assertEqual(
            example_fill_order(card),
            [(0, "a1"), (1, "b1"), (0, "a2"), (0, "a3")],
        )

    def test_three_senses_round_robin_in_sense_order(self):
        card = self._card(["a1", "a2"], ["b1"], ["c1", "c2"])
        self.assertEqual(
            example_fill_order(card),
            [(0, "a1"), (1, "b1"), (2, "c1"), (0, "a2"), (2, "c2")],
        )

    def test_a_single_sense_keeps_its_own_order(self):
        card = self._card(["a1", "a2", "a3"])
        self.assertEqual(
            example_fill_order(card),
            [(0, "a1"), (0, "a2"), (0, "a3")],
        )

    def test_an_empty_first_sense_does_not_starve_the_others(self):
        # The shape that printed nothing before: the examples all sit on a later
        # sense. The first sense contributes nothing and is simply skipped.
        card = self._card([], ["b1", "b2"])
        self.assertEqual(example_fill_order(card), [(1, "b1"), (1, "b2")])

    def test_no_senses_and_no_examples_are_empty(self):
        self.assertEqual(example_fill_order(Card(headword="w", id="w")), [])
        self.assertEqual(example_fill_order(self._card([], [])), [])

    def test_every_example_on_the_card_appears_exactly_once(self):
        card = self._card(["a1", "a2", "a3"], ["b1"], ["c1", "c2"])
        got = [text for _index, text in example_fill_order(card)]
        self.assertCountEqual(got, ["a1", "a2", "a3", "b1", "c1", "c2"])


class ExampleTileMarkupTests(unittest.TestCase):
    """The tile carries the examples in fill order, each tagged with the sense it
    came from, because the view has to regroup them by sense once it knows how
    many fitted."""

    def test_examples_are_emitted_in_fill_order_and_tagged(self):
        card = Card(
            headword="w", id="w",
            senses=[
                Sense(pos="v", examples=["a1", "a2"]),
                Sense(pos="n", examples=["b1"]),
            ],
        )
        html = render_card_tile(card, "front")
        self.assertIn('<div class="example" data-sense="0">a1</div>', html)
        self.assertIn('<div class="example" data-sense="1">b1</div>', html)
        self.assertIn('<div class="example" data-sense="0">a2</div>', html)
        # Interleaved: b1 comes before a2, so the second sense is on the card
        # even if there is only room for two examples.
        self.assertLess(html.index(">b1<"), html.index(">a2<"))

    def test_example_text_is_escaped(self):
        card = Card(
            headword="w", id="w",
            senses=[Sense(pos="v", examples=["a <b> & c"])],
        )
        html = render_card_tile(card, "front")
        self.assertIn("a &lt;b&gt; &amp; c", html)
        self.assertNotIn("<b>", html)

    def test_a_card_with_no_examples_has_no_example_list(self):
        card = Card(headword="w", id="w", senses=[Sense(pos="v")])
        self.assertNotIn("example-list", render_card_tile(card, "front"))


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
        # Assert on the star marker itself (the SVG element and its CSS rule), not
        # a bare "star" substring: unrelated CSS words such as "start" contain
        # "star" and would otherwise trip the check.
        plain = render_html([Card(headword="x", id="x")])
        starred = render_html([Card(headword="y", id="y", starred=True)])
        self.assertNotIn('class="star"', plain)
        self.assertIn('class="star"', starred)

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

    def test_every_sense_contributes_its_examples(self):
        # The bug this replaced: only card.senses[0].examples were rendered, so
        # an example captured onto any later sense never reached the page.
        card = Card(
            headword="shed", id="s",
            senses=[
                Sense(pos="v", examples=["He shed his coat."]),
                Sense(pos="n", examples=["A shed in the garden."]),
            ],
        )
        html = render_html([card])
        self.assertIn("He shed his coat.", html)
        self.assertIn("A shed in the garden.", html)

    def test_examples_on_a_later_sense_alone_still_render(self):
        # The worst case of that bug: nothing printed at all, because the first
        # sense happened to carry no examples.
        card = Card(
            headword="shed", id="s",
            senses=[
                Sense(pos="v"),
                Sense(pos="n", examples=["A shed in the garden."]),
            ],
        )
        self.assertIn("A shed in the garden.", render_html([card]))

    def test_empty_selection_renders_a_document_without_tiles(self):
        html = render_html([])
        self.assertIn("<html", html.lower())
        self.assertNotIn('class="tile', html)

    def test_zero_sense_card_renders_without_crashing(self):
        # A card with no senses is a plausible partially-filled state. Its back
        # tile is blank (no sense rows), but rendering must not crash and the
        # front still shows the headword.
        html = render_html([Card(headword="lonely", id="ls")])
        self.assertIn("lonely", html)
        self.assertIn("tile--back", html)

    def test_front_and_back_are_grouped_in_a_pair(self):
        # One card yields a front sheet and a back sheet; they are wrapped in a
        # single sheet-pair so the preview can show them side by side. Match the
        # sheet class use (`class="sheet sheet--front"`), not a bare token, since
        # the print CSS also names `.sheet--back` in a rule.
        html = render_html(_cards(1))
        self.assertEqual(html.count('class="sheet-pair"'), 1)
        self.assertEqual(html.count('class="sheet sheet--front'), 1)
        self.assertEqual(html.count('class="sheet sheet--back'), 1)

    def test_two_full_sheets_make_two_pairs(self):
        # 9 cards span two physical sheets (8 + 1), so two front/back pairs.
        html = render_html(_cards(9))
        self.assertEqual(html.count('class="sheet-pair"'), 2)

    def test_pair_is_a_flex_row_on_screen(self):
        html = render_html(_cards(1))
        # The side-by-side pairing is screen-only (flex-wrap so it stacks when
        # narrow); print keeps one sheet per page.
        self.assertIn(".sheet-pair {", html)
        self.assertIn("flex-wrap: wrap", html)

    def test_each_sheet_has_a_page_border_and_caption_on_screen(self):
        html = render_html(_cards(1))
        # A visible page border for each sheet, and a caption naming it.
        self.assertIn("Sheet 1 front", html)
        self.assertIn("Sheet 1 back", html)
        self.assertIn("sheet-caption", html)

    def test_print_keeps_one_sheet_per_page(self):
        # The print invariant must survive the screen-only pairing: every sheet
        # page-breaks except the first, so duplex stays one sheet per page.
        html = render_html(_cards(9))  # 4 sheets across 2 pairs
        self.assertIn("break-before: page", html)
        # Exactly one sheet element carries the first-sheet class (the CSS rule
        # `.sheet--first {` also contains the token, so match the class use).
        self.assertEqual(html.count("sheet--front sheet--first"), 1)

    def test_page_margin_is_zero_and_applied_as_sheet_padding(self):
        # The web engine's PDF export did not honour an @page margin (content
        # landed at the physical page corner and the grid bled onto the next
        # page). Instead the @page margin is 0 and each print sheet is a full-page
        # box that carries the margin as its own padding.
        html = render_html(_cards(1), PAGE)
        # The @page at-rule (not the explanatory comment that also names it) sets
        # a zero margin.
        page_rule = html.split("@page {")[1].split("}")[0]
        self.assertIn("margin: 0", page_rule)
        print_block = html.split("@media print")[1].split("@media screen")[0]
        # The print sheet is sized to the full physical page and padded by the
        # margin so the card grid is inset correctly.
        self.assertIn(f"width: {int(PAGE.paper_w_mm)}mm", print_block)
        self.assertIn(f"height: {int(PAGE.paper_h_mm)}mm", print_block)
        self.assertIn(f"padding: {int(PAGE.margin_mm)}mm", print_block)

    def test_print_cut_lines_draw_each_edge_once(self):
        # A hairline cut guide is printed between the tightly-packed cards, toggled
        # by a body class (print-only). Each shared edge is drawn exactly once: a
        # tile draws its top and left, the last column adds a right edge and the
        # last row a bottom edge. Drawing all four sides on every tile would double
        # every interior line's thickness, which is the bug this avoids.
        cols, _rows = grid_dims(PAGE)
        html = render_html(_cards(1))
        print_block = html.split("@media print")[1].split("@media screen")[0]
        self.assertIn("body.print-cut-lines .tile", print_block)
        self.assertIn("border-top", print_block)
        self.assertIn("border-left", print_block)
        # The outer right/bottom edges are drawn once via the last column/row.
        self.assertIn(f".tile:nth-child({cols}n)", print_block)
        self.assertIn(f".tile:nth-last-child(-n+{cols})", print_block)

    def test_back_offset_shifts_the_back_sheet_up_in_print(self):
        # A per-printer duplex registration nudge: the back sheet can be moved by
        # a configurable number of mm so it lands on its front despite the
        # printer's mechanical offset. It is a print-only transform on the back
        # sheet; the default raises the back by 3mm (negative Y).
        from dataclasses import replace
        html = render_html(_cards(1), replace(PAGE, back_offset_mm=3.0))
        print_block = html.split("@media print")[1].split("@media screen")[0]
        self.assertIn("translate(0mm, -3mm)", print_block)
        # Zero offset on both axes draws no transform (nothing to compensate).
        zero = render_html(
            _cards(1), replace(PAGE, back_offset_mm=0.0, back_offset_x_mm=0.0)
        )
        zero_print = zero.split("@media print")[1].split("@media screen")[0]
        self.assertNotIn("translate", zero_print)

    def test_back_offset_horizontal_shifts_the_back_sheet_right(self):
        # The horizontal nudge moves the back right (positive X) for printers that
        # also drift sideways.
        from dataclasses import replace
        html = render_html(
            _cards(1), replace(PAGE, back_offset_mm=0.0, back_offset_x_mm=2.0)
        )
        print_block = html.split("@media print")[1].split("@media screen")[0]
        self.assertIn("translate(2mm, 0mm)", print_block)

    def test_default_page_has_a_3mm_back_offset(self):
        # The shipped default compensates the known printer drift.
        self.assertEqual(PAGE.back_offset_mm, 3.0)

    def test_back_sheet_is_right_aligned_for_duplex(self):
        # The card grid is narrower than the printable width, so it is
        # left-aligned by default. A long-edge duplex flip mirrors the page
        # horizontally, so the back grid must be RIGHT-aligned to land on top of
        # the flipped front; otherwise both sides hug the same edge and the backs
        # miss their fronts. Assert the print CSS right-aligns the back grid.
        html = render_html(_cards(2))
        # Isolate the print block.
        print_block = html.split("@media print")[1].split("@media screen")[0]
        self.assertIn(".sheet--back", print_block)
        self.assertIn("justify-content: end", print_block)

    def test_caption_is_hidden_by_default_and_shown_on_screen(self):
        html = render_html(_cards(1))
        # Base rule hides the caption; the screen block reveals it. This keeps it
        # out of the printed output.
        self.assertIn(".sheet-caption { display: none; }", html)


if __name__ == "__main__":
    unittest.main()
