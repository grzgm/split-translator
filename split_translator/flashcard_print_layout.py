"""Pure-logic builder for the flashcard print HTML.

No Qt import, so the grid maths, the front/back interleaving and the
column-mirrored backs unit-test headless. Each card contributes a fixed-size
front tile and back tile; sheets are emitted front, back, front, back, ... so
a long-edge duplex flip puts each back behind its own front. Overflowing tile
content is clipped (the physical size is fixed) and flagged on screen only."""

import html as _html
from dataclasses import dataclass

from .flashcards import Card


@dataclass(frozen=True)
class PageSpec:
    paper_w_mm: float = 210.0
    paper_h_mm: float = 297.0
    margin_mm: float = 8.0
    card_w_mm: float = 72.0
    card_h_mm: float = 65.0


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


def render_card_tile(card: Card, side: str) -> str:
    """Inner HTML of one tile. side is 'front' or 'back'."""
    if card is None:
        return '<div class="tile tile--empty"></div>'
    if side == "front":
        star = _STAR_SVG if card.starred else ""
        notation = (
            f'<div class="own-notation">{_esc(card.own_notation)}</div>'
            if card.own_notation else ""
        )
        examples = ""
        first = card.senses[0] if card.senses else None
        if first and first.examples:
            items = "".join(
                f'<div class="example">{_esc(ex)}</div>' for ex in first.examples
            )
            examples = f'<div class="example-list">{items}</div>'
        return (
            f'<div class="tile tile--front" data-card-id="{_esc(card.id)}">'
            f'{star}'
            f'<div class="headword">{_esc(card.headword)}</div>'
            f'{notation}{examples}'
            f'</div>'
        )
    senses = ""
    for sense in card.senses:
        pos = f'<div class="part-of-speech">{_esc(sense.pos)}</div>' if sense.pos else '<div class="part-of-speech"></div>'
        meanings = (
            f'<div class="meanings">'
            f'<div class="meaning--polish">{_esc(sense.polish)}</div>'
            f'<div class="meaning--english">{_esc(sense.english)}</div>'
            f'</div>'
        )
        senses += f'<div class="sense">{pos}{meanings}</div>'
    return (
        f'<div class="tile tile--back" data-card-id="{_esc(card.id)}">'
        f'{senses}'
        f'</div>'
    )


def _styles(page: PageSpec, cols: int, has_starred: bool = False) -> str:
    star_css = ".star { position: absolute; top: 3mm; right: 3mm; }" if has_starred else ""
    return f"""
/* The @page margin is left at 0 and the page margin is applied as padding on a
   full-page sheet box in the print block below. Relying on the @page margin put
   the content at the physical page corner in the web engine's PDF export (the
   margin was not honoured), which misaligned every sheet and let the grid bleed
   onto the next page. A full-page sheet with internal padding is exact. */
@page {{ size: {int(page.paper_w_mm)}mm {int(page.paper_h_mm)}mm; margin: 0; }}
* {{ box-sizing: border-box; }}
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
  .tile.is-overflow {{ outline: none; }}
  /* The card grid is narrower than the printable width, so it sits at the left
     margin. A long-edge duplex flip mirrors the page left-to-right, so the back
     grid has to be right-aligned to land on top of the flipped front (the front
     stays left-aligned). Push the columns to the right edge; combined with the
     per-row column reversal, each back then sits exactly behind its own front. */
  .sheet--back {{ justify-content: end; }}
  /* Optional cut guides between the tightly packed cards, toggled by a body
     class. outline (not border) is used so the line never consumes layout space
     or shifts the card content; with no offset, adjacent tiles' shared edges
     coincide into a single line rather than two. The web engine's PDF export
     clamps every stroke to about 0.75pt, so this is as thin as a printed line
     can be. The higher specificity also restores the line on an overflow tile,
     whose screen-only red outline is cleared above. */
  body.print-cut-lines .tile {{ outline: 0.1mm solid #000000; outline-offset: 0; }}
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
  /* Each sheet is drawn as a clearly bordered page with a caption. */
  .sheet {{
    border: 1px solid #7a7f8a;
    box-shadow: 0 1px 4px rgba(0, 0, 0, 0.25);
    background: #ffffff;
  }}
  .sheet-caption {{
    display: block;
    font-family: "Inter", sans-serif;
    font-size: 9pt;
    color: #55606e;
    margin: 0 0 4px 2px;
  }}
  .tile.is-overflow {{ outline: 2px solid red; outline-offset: -2px; }}
  body.show-borders .tile {{ border: 1px solid #000000; }}
}}
"""


_KIND_LABEL = {"front": "front", "back": "back"}


def _sheet_block(sheet: dict, kind_of_sheet: str, sheet_number: int, first: bool) -> str:
    """One sheet: a screen-only caption plus the tile grid. `first` marks the
    very first sheet in the document so print does not page-break before it."""
    tiles = "".join(render_card_tile(cell, kind_of_sheet) for cell in sheet["cells"])
    first_class = " sheet--first" if first else ""
    caption = (
        f'<div class="sheet-caption">Sheet {sheet_number} '
        f'{_KIND_LABEL.get(kind_of_sheet, kind_of_sheet)}</div>'
    )
    return (
        f'<div class="sheet-page">{caption}'
        f'<div class="sheet sheet--{kind_of_sheet}{first_class}">{tiles}</div>'
        f'</div>'
    )


def render_html(cards: list[Card], page: PageSpec = PAGE) -> str:
    cols, _rows = grid_dims(page)
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
                sheet, sheet["kind"], sheet_number, is_first_sheet
            )
        body += f'<div class="sheet-pair">{blocks}</div>'
    has_starred = any(card is not None and card.starred for card in cards)
    return (
        "<!DOCTYPE html><html lang=\"en\"><head><meta charset=\"UTF-8\">"
        f"<style>{_styles(page, cols, has_starred)}</style></head>"
        f"<body>{body}</body></html>"
    )
