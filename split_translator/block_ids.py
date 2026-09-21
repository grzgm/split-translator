"""Paragraph ids, and stored ids and positions resolved to a paragraph.

Paragraph ids have the form bN, numbered in document order by the book loader.
A stored id stops naming a paragraph when its block no longer has text of its
own, so these helpers find the nearest paragraph instead. Standard library
only, so modules that handle ids alone (the section logic, the aligner) do not
load the PDF library that the loader needs."""

import re


_BLOCK_ID_RE = re.compile(r"b(\d+)")


def resolve_block_id(
    block_ids: list[str], wanted: str, forward: bool = True
) -> str | None:
    """The paragraph id to use for a stored id.

    `wanted` itself while it is still a paragraph. Otherwise the nearest
    paragraph after it by number, or before it when `forward` is false, falling
    back to the other direction at either end of the book. A stored id stops
    being a paragraph when the block it names has no text of its own (a spacer
    lost its id). None when there are no paragraphs or the id is not of the bN
    form.

    Relies on `block_ids` being in document order, so ascending by number,
    which `assign_block_ids` guarantees."""
    if wanted in block_ids:
        return wanted
    match = _BLOCK_ID_RE.fullmatch(wanted or "")
    if match is None or not block_ids:
        return None
    number = int(match.group(1))
    after = [bid for bid in block_ids if int(bid[1:]) > number]
    before = [bid for bid in block_ids if int(bid[1:]) < number]
    if forward:
        return after[0] if after else before[-1]
    return before[-1] if before else after[0]


def resolve_position(
    block_ids: list[str], position: tuple[str, float] | None
) -> tuple[str, float] | None:
    """A saved (block id, fraction) position that points at a paragraph.

    Unchanged while its block is still a paragraph. When the block has stopped
    being a paragraph, this reopens at the nearest following paragraph, or the
    last paragraph when none follows (see resolve_block_id); the fraction
    belonged to the old block and is dropped, so the new block's own top
    (fraction 0.0) is used. The view still centres that point on screen, so
    the restored position sits at mid-screen, not the top of the viewport.
    None when there is no position or it cannot be resolved."""
    if position is None:
        return None
    block_id, fraction = position
    resolved = resolve_block_id(block_ids, block_id)
    if resolved is None:
        return None
    return (resolved, fraction if resolved == block_id else 0.0)
