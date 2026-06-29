"""Maps a reading position between two editions of a book using content anchors.

A position is (block_index, fraction): the integer index of a block within its
edition plus how far the viewport has scrolled toward the next block (0..1).
Anchors are (original_index, translation_index) pairs; mapping interpolates
linearly between the two bracketing anchors. This is the content-anchor successor
to the page-number PageMapper."""


def _to_scalar(index: int, fraction: float) -> float:
    return index + fraction


def _from_scalar(value: float, last_index: int) -> tuple[int, float]:
    if value < 0:
        value = 0.0
    if value > last_index:
        value = float(last_index)
    index = int(value)
    fraction = value - index
    return index, fraction


class BookSync:
    """Maps positions between two editions via interpolated content anchors."""

    def __init__(self, original_block_count: int, translation_block_count: int):
        self.original_last = max(0, original_block_count - 1)
        self.translation_last = max(0, translation_block_count - 1)
        self.anchors: list[tuple[int, int]] = [
            (0, 0),
            (self.original_last, self.translation_last),
        ]

    def set_anchors(self, anchors: list[tuple[int, int]]) -> None:
        # Drop any caller-supplied pairs at the reserved endpoint positions (0
        # and original_last) before inserting the canonical fixed endpoints.
        filtered = [
            a for a in anchors if a[0] != 0 and a[0] != self.original_last
        ]
        merged = sorted(filtered, key=lambda a: a[0])
        merged.insert(0, (0, 0))
        merged.append((self.original_last, self.translation_last))
        self.anchors = merged

    def get_anchors(self) -> list[tuple[int, int]]:
        return self.anchors.copy()

    def add_anchor(self, original_index: int, translation_index: int) -> None:
        if original_index in (0, self.original_last):
            return
        self.anchors = [a for a in self.anchors if a[0] != original_index]
        self.anchors.append((original_index, translation_index))
        self.anchors.sort(key=lambda a: a[0])

    def remove_anchor(self, original_index: int) -> None:
        if original_index in (0, self.original_last):
            return
        self.anchors = [a for a in self.anchors if a[0] != original_index]

    def original_to_translation(
        self, index: int, fraction: float
    ) -> tuple[int, float]:
        return self._map_scroll(index, fraction, from_original=True)

    def translation_to_original(
        self, index: int, fraction: float
    ) -> tuple[int, float]:
        return self._map_scroll(index, fraction, from_original=False)

    def _map_scroll(
        self, index: int, fraction: float, from_original: bool
    ) -> tuple[int, float]:
        # Map a scroll position. The destination BLOCK is the block the source
        # position lands in (the interpolation between anchors decides this), but
        # the destination FRACTION is the source's own in-block fraction, NOT the
        # interpolated sub-block fraction.
        #
        # The interpolated sub-block fraction is an artefact of where the scalar
        # lands between anchors: scrolling the original to a clean block top
        # (fraction 0.0) between anchors yields a non-zero destination fraction,
        # which then scrolls the translation a couple hundred pixels PAST the top
        # of the matching block (the "translation is a bit too far up/ahead"
        # drift). Carrying the source fraction instead maps top to top and middle
        # to middle; at an exact anchor it is unchanged (the interpolated
        # fraction there already equals the source fraction at the boundary).
        dst_index, _ = self._map(index, fraction, from_original)
        bounded = fraction
        if bounded < 0.0:
            bounded = 0.0
        elif bounded > 1.0:
            bounded = 1.0
        return dst_index, bounded

    def original_block_to_translation(self, index: int) -> int:
        """Map a whole original block to the single best-matching translation
        block index. Where the scroll mappers map a point (a block plus a scroll
        fraction), this maps the block's centre, so a block whose top maps to,
        say, 60.8 picks the block its body sits in (61) rather than its top edge
        alone pointing at 60. Use this for block-level marking."""
        return self._map_block(index, from_original=True)

    def translation_block_to_original(self, index: int) -> int:
        """Map a whole translation block to the best-matching original block
        index (see `original_block_to_translation`)."""
        return self._map_block(index, from_original=False)

    def _map_block(self, index: int, from_original: bool) -> int:
        # Map the block CENTRE (fraction 0.5), not its top edge, and take the
        # block that centre lands in (the floor of the mapped scalar, which is
        # exactly what _map returns as its index). Mapping the top edge biases
        # the result one block early when a block maps high into a destination
        # block (e.g. original block 51's top maps to 60.8, truncating to 60);
        # mapping the centre lands inside the block the source block overlaps
        # (61). No extra rounding: _map already floors to the containing block.
        dst_index, _ = self._map(index, 0.5, from_original)
        return dst_index

    def _map(
        self, index: int, fraction: float, from_original: bool
    ) -> tuple[int, float]:
        src_key = 0 if from_original else 1
        dst_key = 1 if from_original else 0
        src_last = self.original_last if from_original else self.translation_last
        dst_last = self.translation_last if from_original else self.original_last

        pos = _to_scalar(max(0, min(index, src_last)), fraction)

        # Bracket the source position between two anchors (by source coordinate).
        ordered = sorted(self.anchors, key=lambda a: a[src_key])
        lower = ordered[0]
        upper = ordered[-1]
        for i in range(len(ordered) - 1):
            if ordered[i][src_key] <= pos <= ordered[i + 1][src_key]:
                lower, upper = ordered[i], ordered[i + 1]
                break

        src_span = upper[src_key] - lower[src_key]
        dst_span = upper[dst_key] - lower[dst_key]
        if src_span == 0:
            return _from_scalar(float(lower[dst_key]), dst_last)
        ratio = (pos - lower[src_key]) / src_span
        dst_value = lower[dst_key] + ratio * dst_span
        return _from_scalar(dst_value, dst_last)
