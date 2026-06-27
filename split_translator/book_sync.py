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
        return self._map(index, fraction, from_original=True)

    def translation_to_original(
        self, index: int, fraction: float
    ) -> tuple[int, float]:
        return self._map(index, fraction, from_original=False)

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
