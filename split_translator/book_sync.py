"""Maps a reading position between two editions of a book using content anchors.

A position is (block_index, fraction): the integer index of a block within its
edition plus how far the viewport has scrolled toward the next block (0..1).
Anchors are (original_index, translation_index) pairs; mapping interpolates
linearly between the two bracketing anchors. This is the content-anchor successor
to the page-number PageMapper."""

from dataclasses import dataclass

from .anchor_groups import Group
from .normalise_spec import ORIGINAL_SIDE, TRANSLATION_SIDE

# Section starts that are not paragraphs: the top and the end of the document.
TOP = "top"
END = "end"

_FRONT = "front"
_STRETCH = "stretch"
_GROUP = "group"
_BACK = "back"


@dataclass(frozen=True)
class _Section:
    kind: str
    original: range
    translation: range

    def paragraphs(self, side: str) -> range:
        """Positions of this section's paragraphs in that side's list."""
        return self.original if side == ORIGINAL_SIDE else self.translation


def _other(side: str) -> str:
    return TRANSLATION_SIDE if side == ORIGINAL_SIDE else ORIGINAL_SIDE


def _weights(ids: list[str], texts: list[str]) -> list[int]:
    """Each paragraph's share of the text: its length, at least 1, so a
    paragraph whose text is not known still counts."""
    return [
        max(1, len(texts[i])) if i < len(texts) else 1 for i in range(len(ids))
    ]


class SectionMap:
    """Both editions cut into the same sections, so a reading position can be
    passed from one edition to the other as a section and a share of it.

    In order: front matter from the document top, then stretches between
    anchor groups alternating with the groups, then back matter to the document
    end. The page measures sections by their rendered height; this class knows
    only paragraphs and their text, and answers the questions that need no page:
    which paragraphs to mark, and which paragraph a position falls in."""

    def __init__(
        self,
        original_ids: list[str],
        original_texts: list[str],
        translation_ids: list[str],
        translation_texts: list[str],
        groups: list[Group],
    ):
        self._ids = {
            ORIGINAL_SIDE: list(original_ids),
            TRANSLATION_SIDE: list(translation_ids),
        }
        self._weights = {
            ORIGINAL_SIDE: _weights(original_ids, original_texts),
            TRANSLATION_SIDE: _weights(translation_ids, translation_texts),
        }
        self._positions = {
            side: {bid: i for i, bid in enumerate(ids)}
            for side, ids in self._ids.items()
        }
        self._sections = self._build(groups)
        self._section_at = {}
        for side, ids in self._ids.items():
            section_at = [0] * len(ids)
            for k, section in enumerate(self._sections):
                for i in section.paragraphs(side):
                    section_at[i] = k
            self._section_at[side] = section_at

    def _build(self, groups: list[Group]) -> list[_Section]:
        original_count = len(self._ids[ORIGINAL_SIDE])
        translation_count = len(self._ids[TRANSLATION_SIDE])
        sections = [_Section(_FRONT, range(0, 0), range(0, 0))]
        original, translation = 0, 0

        def add_stretch(original_range: range, translation_range: range) -> None:
            if len(original_range) or len(translation_range):
                sections.append(
                    _Section(_STRETCH, original_range, translation_range)
                )

        for group in groups:
            add_stretch(
                range(original, group.original_first),
                range(translation, group.translation_first),
            )
            sections.append(
                _Section(
                    _GROUP,
                    range(group.original_first, group.original_last + 1),
                    range(group.translation_first, group.translation_last + 1),
                )
            )
            original = group.original_last + 1
            translation = group.translation_last + 1
        add_stretch(
            range(original, original_count), range(translation, translation_count)
        )
        sections.append(
            _Section(
                _BACK,
                range(original_count, original_count),
                range(translation_count, translation_count),
            )
        )
        return sections

    @property
    def section_count(self) -> int:
        return len(self._sections)

    def section_starts(self, side: str) -> list[str]:
        """Where each section begins on that side: a paragraph id, or TOP for
        the front matter, which begins at the document top. A section with no
        paragraphs on this side begins where the next one with paragraphs
        begins, or at END, so it has no height here."""
        ids = self._ids[side]
        starts = [END] * len(self._sections)
        following = END
        for k in range(len(self._sections) - 1, -1, -1):
            section = self._sections[k]
            paragraphs = section.paragraphs(side)
            if len(paragraphs):
                following = ids[paragraphs.start]
            starts[k] = TOP if section.kind == _FRONT else following
        return starts

    def section_of(self, side: str, paragraph_id: str) -> int:
        """The section holding a paragraph. KeyError for an id that is not a
        paragraph of that side."""
        return self._section_at[side][self._positions[side][paragraph_id]]

    def counterpart(self, side: str, paragraph_id: str) -> list[str]:
        """The paragraphs on the other side to mark for a paragraph on this one.

        In a group, every paragraph of the group on the other side. Elsewhere,
        the other side's paragraph at the same share of the section's text,
        measured at the middle of this paragraph. Empty for an unknown id, or
        when the section has no paragraphs on the other side."""
        position = self._positions[side].get(paragraph_id)
        if position is None:
            return []
        k = self._section_at[side][position]
        section = self._sections[k]
        other = _other(side)
        destination = section.paragraphs(other)
        if not len(destination):
            return []
        if section.kind == _GROUP:
            return self._ids[other][destination.start : destination.stop]
        source = section.paragraphs(side)
        weights = self._weights[side]
        before = sum(weights[source.start : position])
        total = sum(weights[source.start : source.stop])
        share = (before + weights[position] / 2) / total
        return [self.paragraph_at(other, k, share)[0]]

    def paragraph_at(
        self, side: str, section: int, share: float
    ) -> tuple[str, float]:
        """The paragraph at a share of a section's text on that side, and how
        far into that paragraph (0 at its start, 1 at its end).

        A section with no paragraphs there gives the start of the next
        paragraph after it, or the end of the last paragraph when none follows.
        ("", 0.0) when the side has no paragraphs at all."""
        ids = self._ids[side]
        if not ids:
            return ("", 0.0)
        paragraphs = self._sections[section].paragraphs(side)
        if not len(paragraphs):
            for later in self._sections[section + 1 :]:
                if len(later.paragraphs(side)):
                    return (ids[later.paragraphs(side).start], 0.0)
            return (ids[-1], 1.0)
        share = min(1.0, max(0.0, share))
        weights = self._weights[side]
        target = share * sum(weights[paragraphs.start : paragraphs.stop])
        passed = 0
        for i in paragraphs:
            if target < passed + weights[i]:
                return (ids[i], (target - passed) / weights[i])
            passed += weights[i]
        return (ids[paragraphs.stop - 1], 1.0)


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
