"""Pure-logic builder for the flashcard print HTML.

No Qt import, so the grid maths, the front/back interleaving and the
column-mirrored backs unit-test headless. Each card contributes a fixed-size
front tile and back tile; sheets are emitted front, back, front, back, ... so
a long-edge duplex flip puts each back behind its own front. Overflowing tile
content is clipped (the physical size is fixed) and flagged on screen only."""

import html as _html
from dataclasses import dataclass

from .flashcards import Card, REDACTION_TOKEN


# The token rendered as a fixed-width fill-in blank on the printed back.
_BLANK_HTML = '<span class="blank">_____</span>'


@dataclass(frozen=True)
class PageSpec:
    paper_w_mm: float = 210.0
    paper_h_mm: float = 297.0
    margin_mm: float = 8.0
    card_w_mm: float = 72.0
    card_h_mm: float = 65.0
    # Duplex registration nudge: how many mm to shift the back sheet so it lands
    # on its front despite the printer's mechanical two-sided offset. back_offset_mm
    # is the vertical nudge (positive moves the back up); back_offset_x_mm is the
    # horizontal nudge (positive moves the back right). Vertical defaults to 3mm to
    # compensate the known printer drift; 0 on either axis applies no shift there.
    back_offset_mm: float = 3.0
    back_offset_x_mm: float = 0.0


PAGE = PageSpec()


def grid_dims(page: PageSpec) -> tuple[int, int]:
    """Columns and rows that fit inside the printable area, packed tightly."""
    usable_w = page.paper_w_mm - 2 * page.margin_mm
    usable_h = page.paper_h_mm - 2 * page.margin_mm
    cols = max(1, int(usable_w // page.card_w_mm))
    rows = max(1, int(usable_h // page.card_h_mm))
    return cols, rows


def _mirror_rows(cells: list, cols: int) -> list:
    """Reverse the column order within each row (for the back sheet)."""
    out = []
    for start in range(0, len(cells), cols):
        row = cells[start:start + cols]
        out.extend(reversed(row))
    return out


def paginate(cards: list[Card], page: PageSpec) -> list[dict]:
    """Sheets in print order: for each group of cols*rows cards, a front sheet
    (natural order) then a back sheet (each row column-reversed). Cells are
    padded with None to a full grid so the mirror and cut lines stay aligned."""
    cols, rows = grid_dims(page)
    per_sheet = cols * rows
    sheets = []
    for start in range(0, len(cards), per_sheet):
        group = list(cards[start:start + per_sheet])
        group += [None] * (per_sheet - len(group))
        sheets.append({"kind": "front", "cells": list(group)})
        sheets.append({"kind": "back", "cells": _mirror_rows(group, cols)})
    return sheets


_STAR_SVG = (
    '<svg class="star" xmlns="http://www.w3.org/2000/svg" viewBox="0 -960 960 960" '
    'width="16" height="16" fill="#000000">'
    '<path d="m233-120 65-281L80-590l288-25 112-265 112 265 288 25-218 189 65 '
    '281-247-149-247 149Z"/></svg>'
)


def _esc(text: str) -> str:
    return _html.escape(text or "")


def example_fill_order(card: Card) -> list[tuple[int, int, str]]:
    """Every example on the card, interleaved across its senses: the first
    example of each sense, then the second of each, and so on. Each item is
    (sense index, example index within that sense, example text).

    A tile is a fixed physical size and clips whatever does not fit, so the order
    the examples are added in is what decides which ones survive. Interleaving
    means every sense gets an example on the card before any sense gets a second
    one, instead of a wordy first sense crowding the later senses off it
    entirely.

    The example index is carried because the rendered tile tags each example with
    it, which is how the page reports a kept example back to Python as a
    (sense, example) pair.

    This is only the fill order. The print view fills a tile in this order, and
    then regroups whatever fitted back into sense order for display, so the card
    still reads as all of sense one, then all of sense two."""
    senses = card.senses or []
    deepest = max((len(s.examples or []) for s in senses), default=0)
    order = []
    for rank in range(deepest):
        for index, sense in enumerate(senses):
            examples = sense.examples or []
            if rank < len(examples):
                order.append((index, rank, examples[rank]))
    return order


def example_sense_order(card: Card) -> list[tuple[int, int, str]]:
    """Every example on the card in reading order: all of sense one, then all of
    sense two. Same triples as example_fill_order, in the order a hand-picked
    set prints in. No interleaving is needed there, because a hand-picked set is
    rendered whole and nothing will be dropped."""
    order = []
    for sense_index, sense in enumerate(card.senses or []):
        for example_index, text in enumerate(sense.examples or []):
            order.append((sense_index, example_index, text))
    return order


def incompleteness(card: Card) -> str | None:
    """How badly the card needs correcting, or None when nothing is missing.

    The preview tints a card by this level so the ones worth fixing stand out
    before any paper is used. A card only has to fail one check to be flagged,
    and one failing several is reported at its worst level, since a tile carries
    a single tint.

    "high" is a missing headword or a missing own pronunciation, either of which
    leaves the printed card close to useless. "medium" is a card with no usage
    example at all. "low" is a sense missing its Polish or its English text,
    which still prints something but only half of it.

    A card with no senses falls out as "medium": it has no examples either, and
    that is the worse of the two things it is missing."""
    if not (card.headword or "").strip():
        return "high"
    if not (card.own_notation or "").strip():
        return "high"
    senses = card.senses or []
    if not any((text or "").strip() for s in senses for text in (s.examples or [])):
        return "medium"
    if any(
        not (s.polish or "").strip() or not (s.english or "").strip()
        for s in senses
    ):
        return "low"
    return None


def _tile_classes(card: Card, side: str) -> str:
    """The class attribute for a card's tile, including its incompleteness tint
    when it has one. Both sides carry it, so a card needing attention is obvious
    on whichever sheet is being looked at."""
    classes = ["tile", f"tile--{side}"]
    level = incompleteness(card)
    if level:
        classes.append(f"tile--incomplete-{level}")
    return " ".join(classes)


def render_card_tile(
    card: Card,
    side: str,
    blank_headwords: bool = True,
    chosen: set | None = None,
) -> str:
    """Inner HTML of one tile. side is 'front' or 'back'. When blank_headwords is
    true, each REDACTION_TOKEN in an English definition renders as a blank.

    chosen is a set of (sense index, example index) pairs when the user has
    hand-picked this card's examples, or None to leave the card to the browser's
    fit measurement. None and an empty set differ: an empty set is a deliberate
    "print no examples"."""
    if card is None:
        return '<div class="tile tile--empty"></div>'
    if side == "front":
        star = _STAR_SVG if card.starred else ""
        notation = (
            f'<div class="own-notation">{_esc(card.own_notation)}</div>'
            if card.own_notation else ""
        )
        # Auto mode emits every example in fill order, not reading order, and
        # tagged with the sense and position it came from: the view drops what
        # does not fit, puts the survivors back into sense order, and reports
        # them back to Python by those two indices. See example_fill_order.
        #
        # A hand-picked set instead emits exactly the chosen examples in reading
        # order (nothing will be dropped, so there is nothing to interleave for)
        # and marks the list so the fit skips it.
        if chosen is None:
            fill = example_fill_order(card)
            fit_attr = ""
        else:
            fill = [
                (sense_index, example_index, text)
                for sense_index, example_index, text in example_sense_order(card)
                if (sense_index, example_index) in chosen
            ]
            fit_attr = ' data-fit="manual"'
        examples = ""
        if fill:
            items = "".join(
                f'<div class="example" data-sense="{sense_index}"'
                f' data-example="{example_index}">{_esc(text)}</div>'
                for sense_index, example_index, text in fill
            )
            examples = f'<div class="example-list"{fit_attr}>{items}</div>'
        return (
            f'<div class="{_tile_classes(card, "front")}" data-card-id="{_esc(card.id)}">'
            f'{star}'
            f'<div class="headword">{_esc(card.headword)}</div>'
            f'{notation}{examples}'
            f'</div>'
        )
    senses = ""
    for sense in card.senses:
        pos = f'<div class="part-of-speech">{_esc(sense.pos)}</div>' if sense.pos else '<div class="part-of-speech"></div>'
        english = _esc(sense.english)
        if blank_headwords:
            # Safe only because REDACTION_TOKEN has no HTML-special characters:
            # _esc leaves it intact, so this replace still matches the token.
            english = english.replace(REDACTION_TOKEN, _BLANK_HTML)
        meanings = (
            f'<div class="meanings">'
            f'<div class="meaning--polish">{_esc(sense.polish)}</div>'
            f'<div class="meaning--english">{english}</div>'
            f'</div>'
        )
        senses += f'<div class="sense">{pos}{meanings}</div>'
    return (
        f'<div class="{_tile_classes(card, "back")}" data-card-id="{_esc(card.id)}">'
        f'{senses}'
        f'</div>'
    )


def _fmt_mm(value: float) -> str:
    """Format a mm length without a trailing ``.0`` (3.0 -> "3", 2.5 -> "2.5").
    Negative zero is normalised to "0" so a zero axis never reads "-0"."""
    if value == 0:
        value = 0.0
    return f"{value:g}"


def _styles(page: PageSpec, cols: int) -> str:
    # The star rule is emitted whether or not any card is starred, which is what
    # makes this whole stylesheet independent of the cards. That matters because
    # the preview updates by replacing the body alone and never rebuilds the head
    # (see PrintView._body_swap_script): a stylesheet that varied with the cards
    # would go stale the moment a starred card entered or left the selection.
    # Paper and card sizes come from PAGE and never change at runtime, and the
    # back offsets ride CSS variables the preview sets live, so nothing else here
    # varies either. The cost when nothing is starred is one unused rule.
    star_css = ".star { position: absolute; top: 3mm; right: 3mm; }"
    # The back sheet's duplex registration nudge is carried by two CSS variables
    # so the print preview can update it live (see PrintView._back_offset_js)
    # without rebuilding the whole document. --back-dx shifts the back right
    # (positive X); --back-dy shifts it up when the setting is positive, so the
    # vertical value is negated here. The print-only transform below consumes
    # them, and a 0mm value is a harmless no-op translate.
    dx = _fmt_mm(page.back_offset_x_mm)
    dy = _fmt_mm(-page.back_offset_mm)
    return f"""
/* The @page margin is left at 0 and the page margin is applied as padding on a
   full-page sheet box in the print block below. Relying on the @page margin put
   the content at the physical page corner in the web engine's PDF export (the
   margin was not honoured), which misaligned every sheet and let the grid bleed
   onto the next page. A full-page sheet with internal padding is exact. */
@page {{ size: {int(page.paper_w_mm)}mm {int(page.paper_h_mm)}mm; margin: 0; }}
* {{ box-sizing: border-box; }}
:root {{ --back-dx: {dx}mm; --back-dy: {dy}mm; }}
html, body {{ margin: 0; padding: 0; background: #ffffff; color: #000000; }}
.sheet {{
  display: grid;
  grid-template-columns: repeat({cols}, {int(page.card_w_mm)}mm);
  grid-auto-rows: {int(page.card_h_mm)}mm;
  gap: 0;
}}
.tile {{
  position: relative;
  width: {int(page.card_w_mm)}mm;
  height: {int(page.card_h_mm)}mm;
  padding: 4mm;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}}
{star_css}
.headword {{ font-family: "Inter", sans-serif; font-size: 12pt; text-align: center; }}
.own-notation {{ font-family: "Inter", sans-serif; text-align: center; margin: 1mm 0 3mm; }}
.own-notation::before {{ content: "["; }}
.own-notation::after {{ content: "]"; }}
.example-list {{ display: flex; flex-direction: column; gap: 1mm; }}
.example {{ font-family: "Lora", serif; font-size: 8pt; }}
.sense {{ display: flex; margin-bottom: 2mm; }}
.part-of-speech {{ font-family: "Inter", sans-serif; box-sizing: border-box; flex: 0 0 3.75ch; text-align: center; font-size: 8pt; }}
.part-of-speech::before {{ content: "{{"; }}
.part-of-speech::after {{ content: "}}"; }}
.meanings {{ display: flex; flex-direction: column; gap: 1mm; }}
.meaning--polish {{ font-family: "Inter", sans-serif; font-size: 8pt; }}
.meaning--english {{ font-family: "Lora", serif; font-size: 8pt; }}
.blank {{ font-family: "Lora", serif; }}
.sheet-caption {{ display: none; }}
@media print {{
  /* Each sheet is exactly one physical page and carries the page margin as its
     own padding, so the card grid is inset correctly and every sheet breaks
     cleanly at the page boundary (no bleed onto the next page). align-content
     keeps the rows at the top rather than stretching them. */
  .sheet-pair {{ display: block; }}
  .sheet {{
    width: {int(page.paper_w_mm)}mm;
    height: {int(page.paper_h_mm)}mm;
    padding: {int(page.margin_mm)}mm;
    align-content: start;
    break-before: page;
  }}
  .sheet--first {{ break-before: auto; }}
  /* Both markers are screen-only aids, so neither reaches paper. Their rules
     live in the screen block below and so do not apply here at all; these are
     the same belt and braces the overflow outline has always carried, because a
     printed card tinted blue would waste a sheet. */
  .tile.is-overflow {{ outline: none; }}
  .tile.tile--selected {{ outline: none; background: transparent; }}
  .tile.tile--incomplete-low,
  .tile.tile--incomplete-medium,
  .tile.tile--incomplete-high {{ background: transparent; }}
  /* The card grid is narrower than the printable width, so it sits at the left
     margin. A long-edge duplex flip mirrors the page left-to-right, so the back
     grid has to be right-aligned to land on top of the flipped front (the front
     stays left-aligned). Push the columns to the right edge; combined with the
     per-row column reversal, each back then sits exactly behind its own front.
     The transform reads the --back-* variables (set from the page spec and
     updated live by the preview) to raise or shift the back by the duplex nudge,
     cancelling the printer's mechanical two-sided offset; 0mm is a no-op. */
  .sheet--back {{ justify-content: end; transform: translate(var(--back-dx), var(--back-dy)); }}
  /* Optional cut guides between the tightly packed cards, toggled by a body
     class. Each interior line is drawn exactly once: every tile draws its top
     and left edge, the last column adds a right edge and the last row a bottom
     edge, so a shared edge is never drawn twice (which would double its
     thickness). A thin border with box-sizing: border-box keeps the tile at its
     exact size. The web engine's PDF export clamps every stroke to about 0.75pt,
     so this is as thin as a printed line can be. Empty trailing cells are still
     tiles, so the grid (padded to a full page) always draws a complete block. */
  body.print-cut-lines .tile {{
    border-top: 0.1mm solid #000000;
    border-left: 0.1mm solid #000000;
  }}
  body.print-cut-lines .tile:nth-child({cols}n) {{
    border-right: 0.1mm solid #000000;
  }}
  body.print-cut-lines .tile:nth-last-child(-n+{cols}) {{
    border-bottom: 0.1mm solid #000000;
  }}
}}
@media screen {{
  body {{ background: #e9ebf0; padding: 16px; }}
  /* Front and back of one physical sheet sit side by side in a row when the
     window is wide enough, and wrap to stack when it is not. */
  .sheet-pair {{
    display: flex;
    flex-wrap: wrap;
    gap: 16px;
    margin-bottom: 24px;
    align-items: flex-start;
  }}
  /* Show the whole physical page on screen (not just the card block): the sheet
     is the full paper size with the margin as padding, so the empty page margins
     around the cards are visible and it is clear how the cards sit on the page.
     align-content keeps the grid at the top of the page as it prints. */
  .sheet {{
    width: {int(page.paper_w_mm)}mm;
    height: {int(page.paper_h_mm)}mm;
    padding: {int(page.margin_mm)}mm;
    align-content: start;
    border: 1px solid #7a7f8a;
    box-shadow: 0 1px 4px rgba(0, 0, 0, 0.25);
    background: #ffffff;
  }}
  /* The back grid sits where it will print: right-aligned. (The duplex nudge is
     print-only, so it is not applied on screen.) */
  .sheet--back {{ justify-content: end; }}
  .sheet-caption {{
    display: block;
    font-family: "Inter", sans-serif;
    font-size: 9pt;
    color: #55606e;
    margin: 0 0 4px 2px;
  }}
  /* A tile is a click target in the preview (clicking one loads that card),
     so it reads as one. Screen only: the printed card is not clickable. */
  .tile[data-card-id] {{ cursor: pointer; }}
  /* The card currently loaded in the editor, marked on both its front and its
     back so it is obvious which card the sidebar and the editor are showing.
     Same blue as the saved-list row tint and the anchor editor's selection, so
     one selection colour runs through the app. An outline rather than a border
     keeps the tile at its exact size, matching the overflow marker.

     Deliberately listed before the overflow rule: a clipped card is a warning
     and must keep its red outline even while selected. That falls out of
     specificity too (.tile.is-overflow carries two classes to this rule's one),
     but the order says so plainly. The blue tint still shows underneath, so a
     card that is both selected and overflowing reads as both. */
  .tile--selected {{
    outline: 2px solid #1a73e8;
    outline-offset: -2px;
    background: #e8f0fe;
  }}
  /* A card with something missing, tinted so it is easy to pick out before any
     paper is used. The three levels run pale to strong with how badly the card
     needs correcting (see incompleteness), so a wall of cards sorts itself by
     eye. Amber rather than red, which stays the overflow warning's colour.

     Listed after the selected rule so the tint wins the background: a card that
     is both loaded and incomplete keeps the blue selection outline over an amber
     body, and neither signal is lost. */
  .tile--incomplete-low {{ background: #fff8e1; }}
  .tile--incomplete-medium {{ background: #ffe082; }}
  .tile--incomplete-high {{ background: #ffca28; }}
  .tile.is-overflow {{ outline: 2px solid red; outline-offset: -2px; }}
  body.show-borders .tile {{ border: 1px solid #000000; }}
}}
"""


def _sheet_block(
    sheet: dict,
    kind_of_sheet: str,
    sheet_number: int,
    first: bool,
    blank_headwords: bool,
    choices: dict,
) -> str:
    """One sheet: a screen-only caption plus the tile grid. `first` marks the
    very first sheet in the document so print does not page-break before it.
    `choices` maps a card id to its hand-picked example set; a card absent from
    it is left to the browser's fit."""
    tiles = "".join(
        render_card_tile(
            cell,
            kind_of_sheet,
            blank_headwords,
            choices.get(cell.id) if cell is not None else None,
        )
        for cell in sheet["cells"]
    )
    first_class = " sheet--first" if first else ""
    caption = (
        f'<div class="sheet-caption">Sheet {sheet_number} {kind_of_sheet}</div>'
    )
    return (
        f'<div class="sheet-page">{caption}'
        f'<div class="sheet sheet--{kind_of_sheet}{first_class}">{tiles}</div>'
        f'</div>'
    )


def render_body(
    cards: list[Card],
    page: PageSpec = PAGE,
    blank_headwords: bool = True,
    choices: dict | None = None,
) -> str:
    """The sheets markup alone, with no document around it.

    Split out from render_html because everything that changes while the Print
    window is open (the cards, the hand-picked example sets, headword blanking)
    changes only this. The preview swaps this into the live document rather than
    reloading the whole page, which is what stops it blinking; see
    PrintView._body_swap_script."""
    choices = choices or {}
    sheets = paginate(cards, page)
    # paginate emits sheets as consecutive front, back, front, back, ... pairs.
    # On screen each pair is shown side by side; on paper each sheet is its own
    # page. Group them two at a time into a pair wrapper.
    body = ""
    for pair_index in range(0, len(sheets), 2):
        pair = sheets[pair_index:pair_index + 2]
        sheet_number = pair_index // 2 + 1
        blocks = ""
        for offset, sheet in enumerate(pair):
            is_first_sheet = pair_index == 0 and offset == 0
            blocks += _sheet_block(
                sheet,
                sheet["kind"],
                sheet_number,
                is_first_sheet,
                blank_headwords,
                choices,
            )
        body += f'<div class="sheet-pair">{blocks}</div>'
    return body


def render_html(
    cards: list[Card],
    page: PageSpec = PAGE,
    blank_headwords: bool = True,
    choices: dict | None = None,
) -> str:
    """The whole document: a content-independent head plus the sheets body.

    Used for the preview's first load and for any print or PDF export. Later
    preview updates go through render_body instead."""
    cols, _rows = grid_dims(page)
    return (
        "<!DOCTYPE html><html lang=\"en\"><head><meta charset=\"UTF-8\">"
        f"<style>{_styles(page, cols)}</style></head>"
        f"<body>{render_body(cards, page, blank_headwords, choices)}</body></html>"
    )
