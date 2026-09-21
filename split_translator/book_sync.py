"""Both editions cut into matching sections, so a reading position passes from
one edition to the other as a section and a share of it.

Anchors cut the books: each anchor group is a section, and the stretches
between groups are sections too, with front matter before the first kept
paragraph and back matter after the last (see the skip fields). A section may
have no paragraphs on one side, and then no height there. The page measures
sections by rendered height (see book_view); this module holds the
paragraph-level logic, with no Qt import."""

from dataclasses import dataclass

from .anchor_groups import Group
from .block_ids import resolve_block_id
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


def _checked(kept: range | None, count: int) -> range:
    """The kept range, or every paragraph when none is given or it does not
    fit the edition."""
    if kept is None or kept.start < 0 or kept.stop > count or kept.start >= kept.stop:
        return range(0, count)
    return range(kept.start, kept.stop)


def kept_range(
    block_ids: list[str], first_id: str | None, last_id: str | None
) -> range:
    """Positions of the paragraphs kept between the skip fields.

    An absent id keeps that end. A first id that is no longer a paragraph
    resolves forward and a last id backward (see resolve_block_id), so the
    boundary moves inward rather than letting skipped text back in. Everything
    is kept when the resolved ends would leave no paragraph."""
    count = len(block_ids)
    position = {bid: i for i, bid in enumerate(block_ids)}
    start, stop = 0, count
    if first_id is not None:
        resolved = resolve_block_id(block_ids, first_id, forward=True)
        if resolved is not None:
            start = position[resolved]
    if last_id is not None:
        resolved = resolve_block_id(block_ids, last_id, forward=False)
        if resolved is not None:
            stop = position[resolved] + 1
    if start >= stop:
        return range(0, count)
    return range(start, stop)


class SectionMap:
    """Both editions cut into the same sections, so a reading position can be
    passed from one edition to the other as a section and a share of it.

    In order: front matter from the document top (the paragraphs before the
    first kept one), then stretches between anchor groups alternating with the
    groups, then back matter to the document end (the paragraphs after the
    last kept one). Groups that reach outside the kept range are ignored. The
    page measures sections by their rendered height; this class knows only
    paragraphs and their text, and answers the questions that need no page:
    which paragraphs to mark, and which paragraph a position falls in."""

    def __init__(
        self,
        original_ids: list[str],
        original_texts: list[str],
        translation_ids: list[str],
        translation_texts: list[str],
        groups: list[Group],
        original_kept: range | None = None,
        translation_kept: range | None = None,
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
        self._kept = {
            ORIGINAL_SIDE: _checked(original_kept, len(original_ids)),
            TRANSLATION_SIDE: _checked(translation_kept, len(translation_ids)),
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
        original_kept = self._kept[ORIGINAL_SIDE]
        translation_kept = self._kept[TRANSLATION_SIDE]
        sections = [
            _Section(
                _FRONT,
                range(0, original_kept.start),
                range(0, translation_kept.start),
            )
        ]
        original, translation = original_kept.start, translation_kept.start

        def add_stretch(original_range: range, translation_range: range) -> None:
            if len(original_range) or len(translation_range):
                sections.append(
                    _Section(_STRETCH, original_range, translation_range)
                )

        for group in groups:
            if not group.within(original_kept, translation_kept):
                continue
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
            range(original, original_kept.stop),
            range(translation, translation_kept.stop),
        )
        sections.append(
            _Section(
                _BACK,
                range(original_kept.stop, original_count),
                range(translation_kept.stop, translation_count),
            )
        )
        return sections

    @property
    def section_count(self) -> int:
        return len(self._sections)

    def kept(self, side: str) -> range:
        """Positions of that side's kept paragraphs (everything but front and
        back matter)."""
        return self._kept[side]

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
