"""Anchors grouped by the paragraphs they share.

An anchor links one original paragraph to one translation paragraph. Anchors
that share a paragraph on either side belong to one group, which is how one
paragraph is matched to several: a paragraph split in two in the other edition
takes two anchors from the same paragraph. A group covers every paragraph from
its first to its last on each side, the paragraphs in between included.

Groups keep the reading order: ordered by their original paragraphs, each group
ends before the next begins on both sides. Two groups that overlap, or whose
order differs between the editions (they cross), cannot both hold.

Anchors come in two kinds: manual ones made in the editor and automatic ones
made by the aligner. Each kind forms groups of its own; an automatic group
that touches a manual one is ignored, so the manual anchors always win.

Pure logic with no Qt import, so it unit-tests headless."""

import bisect
from dataclasses import dataclass

Anchor = tuple[str, str]


@dataclass(frozen=True)
class Group:
    """Anchors joined through shared paragraphs, and the paragraphs they cover.

    The four bounds are inclusive positions in each edition's paragraph list."""

    anchors: tuple[Anchor, ...]
    original_first: int
    original_last: int
    translation_first: int
    translation_last: int

    def precedes(self, other: "Group") -> bool:
        """Whether this group ends before `other` begins, in both editions."""
        return (
            self.original_last < other.original_first
            and self.translation_last < other.translation_first
        )

    def conflicts_with(self, other: "Group") -> bool:
        """Whether the two groups overlap or cross, so they cannot both hold."""
        return not (self.precedes(other) or other.precedes(self))

    def within(self, original_kept: range, translation_kept: range) -> bool:
        """Whether every paragraph the group covers is kept on both sides (see
        the skip fields). A group that reaches into front or back matter is
        ignored for sync."""
        return (
            original_kept.start <= self.original_first
            and self.original_last < original_kept.stop
            and translation_kept.start <= self.translation_first
            and self.translation_last < translation_kept.stop
        )


def _index(ids: list[str]) -> dict[str, int]:
    return {bid: i for i, bid in enumerate(ids)}


def _unique(anchors: list[Anchor]) -> list[Anchor]:
    """The anchors in stored order, each exact duplicate after the first
    dropped."""
    seen: set[Anchor] = set()
    unique = []
    for anchor in anchors:
        if anchor not in seen:
            seen.add(anchor)
            unique.append(anchor)
    return unique


def _group_indexed(
    anchors: list[Anchor],
    original_index: dict[str, int],
    translation_index: dict[str, int],
) -> list[Group]:
    known = [
        anchor
        for anchor in _unique(anchors)
        if anchor[0] in original_index and anchor[1] in translation_index
    ]
    # Union-find over anchors joined through a shared paragraph on either side.
    parent = list(range(len(known)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    first_on_original: dict[str, int] = {}
    first_on_translation: dict[str, int] = {}
    for i, (original_id, translation_id) in enumerate(known):
        for key, table in (
            (original_id, first_on_original),
            (translation_id, first_on_translation),
        ):
            if key in table:
                parent[find(i)] = find(table[key])
            else:
                table[key] = i

    members: dict[int, list[Anchor]] = {}
    for i, anchor in enumerate(known):
        members.setdefault(find(i), []).append(anchor)

    groups = []
    for group_anchors in members.values():
        originals = [original_index[a[0]] for a in group_anchors]
        translations = [translation_index[a[1]] for a in group_anchors]
        groups.append(
            Group(
                tuple(group_anchors),
                min(originals),
                max(originals),
                min(translations),
                max(translations),
            )
        )
    groups.sort(key=lambda g: (g.original_first, g.translation_first))
    return groups


def build_groups(
    anchors: list[Anchor], original_ids: list[str], translation_ids: list[str]
) -> list[Group]:
    """Group the anchors whose two ids are both paragraphs, ordered by their
    original paragraphs. Anchors naming a non-paragraph are left out, and an
    exact duplicate counts once."""
    return _group_indexed(anchors, _index(original_ids), _index(translation_ids))


def first_conflict(groups: list[Group]) -> tuple[Group, Group] | None:
    """The first two neighbouring groups that overlap or cross, or None when the
    groups keep the reading order. `groups` must be ordered as build_groups
    orders them. Checking neighbours is enough: if every group precedes the
    next, each precedes all that follow."""
    for before, after in zip(groups, groups[1:]):
        if not before.precedes(after):
            return before, after
    return None


def resolve_manual(
    anchors: list[Anchor], original_ids: list[str], translation_ids: list[str]
) -> tuple[list[Group], list[Anchor]]:
    """The manual groups sync uses, and the stored anchors it has to ignore.

    Anchors are taken in stored order. One that would make the groups so far
    overlap or cross is set aside as conflicting: it is ignored for sync but
    stays in the file, so nothing is lost silently. That can only happen in a
    hand-edited or older file, because the editor refuses such an anchor.
    Anchors naming a non-paragraph are ignored without being reported, as
    unknown ids always were."""
    original_index = _index(original_ids)
    translation_index = _index(translation_ids)
    accepted: list[Anchor] = []
    conflicting: list[Anchor] = []
    for anchor in _unique(anchors):
        if anchor[0] not in original_index or anchor[1] not in translation_index:
            continue
        trial = _group_indexed(
            accepted + [anchor], original_index, translation_index
        )
        if first_conflict(trial) is None:
            accepted.append(anchor)
        else:
            conflicting.append(anchor)
    return _group_indexed(accepted, original_index, translation_index), conflicting


def add_conflict(
    anchors: list[Anchor],
    new: Anchor,
    original_ids: list[str],
    translation_ids: list[str],
) -> Anchor | None:
    """The stored anchor that stops `new` being added, or None when it can be.

    `new` joins any group it shares a paragraph with. It is refused when that
    grown group would overlap or cross another group, and the anchor named is
    the first of that other group, the one to look at in the editor. Only the
    groups sync uses count, so an anchor already set aside as conflicting
    never blocks a new one."""
    original_index = _index(original_ids)
    translation_index = _index(translation_ids)
    groups, _conflicting = resolve_manual(anchors, original_ids, translation_ids)
    accepted = [anchor for group in groups for anchor in group.anchors]
    trial = _group_indexed(accepted + [new], original_index, translation_index)
    grown = next((g for g in trial if new in g.anchors), None)
    if grown is None:
        return None
    for other in trial:
        if other is not grown and grown.conflicts_with(other):
            return other.anchors[0]
    return None


def group_paragraphs(
    group: Group, original_ids: list[str], translation_ids: list[str]
) -> tuple[list[str], list[str]]:
    """Every paragraph id the group covers, original side then translation."""
    return (
        original_ids[group.original_first : group.original_last + 1],
        translation_ids[group.translation_first : group.translation_last + 1],
    )


def _reading_order(groups: list[Group]) -> list[Group]:
    return sorted(groups, key=lambda g: (g.original_first, g.translation_first))


@dataclass(frozen=True)
class Resolved:
    """What sync uses from the stored anchors, and what it sets aside."""

    manual: list[Group]
    #: Manual anchors ignored because they overlap or cross earlier ones.
    conflicting: list[Anchor]
    automatic: list[Group]
    #: Automatic anchors ignored because their group touches a manual group or
    #: an earlier automatic one.
    ignored: list[Anchor]

    @property
    def groups(self) -> list[Group]:
        """Every group sync uses, manual and automatic, in reading order."""
        return _reading_order(self.manual + self.automatic)


def _clear_of(group: Group, manual: list[Group], firsts: list[int]) -> bool:
    """Whether the group shares no paragraph with any manual group and neither
    overlaps nor crosses one. `manual` keeps the reading order and `firsts`
    holds their first original paragraphs, so only the manual groups either
    side of this one need checking: every earlier one precedes those."""
    k = bisect.bisect_left(firsts, group.original_first)
    if k > 0 and not manual[k - 1].precedes(group):
        return False
    if k < len(manual) and not group.precedes(manual[k]):
        return False
    return True


def resolve(
    manual: list[Anchor],
    automatic: list[Anchor],
    original_ids: list[str],
    translation_ids: list[str],
) -> Resolved:
    """The groups sync uses from both kinds of anchor.

    Manual anchors are resolved as resolve_manual does. Automatic anchors form
    groups of their own, never joined with manual ones. An automatic group that
    shares a paragraph with a manual group, overlaps it or crosses it is
    ignored, and so is one that overlaps or crosses an earlier automatic group;
    the aligner never makes either, so they come only from a hand-edited file
    or a batch that finished after a manual edit. Runs in n log n for the
    automatic anchors, which can number in the thousands."""
    manual_groups, conflicting = resolve_manual(
        manual, original_ids, translation_ids
    )
    firsts = [g.original_first for g in manual_groups]
    automatic_groups: list[Group] = []
    ignored: list[Anchor] = []
    for group in _group_indexed(
        automatic, _index(original_ids), _index(translation_ids)
    ):
        clear = _clear_of(group, manual_groups, firsts)
        if clear and (not automatic_groups or automatic_groups[-1].precedes(group)):
            automatic_groups.append(group)
        else:
            ignored.extend(group.anchors)
    return Resolved(manual_groups, conflicting, automatic_groups, ignored)


def _in_batch(group: Group, start: int, count: int) -> bool:
    """Whether the group belongs to the batch of original paragraphs at
    positions start..start + count: its first original paragraph lies there."""
    return start <= group.original_first < start + count


def batch_anchors(resolved: Resolved, start: int, count: int) -> list[Anchor]:
    """The automatic anchors a batch replaces: those of every automatic group
    that belongs to it."""
    return [
        anchor
        for group in resolved.automatic
        if _in_batch(group, start, count)
        for anchor in group.anchors
    ]


def fixed_groups(resolved: Resolved, start: int, count: int) -> list[Group]:
    """The groups a batch must fit around, in reading order: every manual
    group, and every automatic group that does not belong to the batch, so a
    batch joins its neighbours cleanly."""
    outside = [g for g in resolved.automatic if not _in_batch(g, start, count)]
    return _reading_order(resolved.manual + outside)


def displaced_automatic(
    manual: list[Anchor],
    automatic: list[Anchor],
    new: Anchor,
    original_ids: list[str],
    translation_ids: list[str],
) -> list[Anchor]:
    """The automatic anchors a new manual anchor pushes out: those of every
    automatic group that shares a paragraph with the manual group `new` ends
    up in, overlaps it or crosses it. Empty when `new` names a non-paragraph
    or would itself be set aside as conflicting."""
    before = resolve(manual, automatic, original_ids, translation_ids)
    after, _conflicting = resolve_manual(
        manual + [new], original_ids, translation_ids
    )
    grown = next((g for g in after if new in g.anchors), None)
    if grown is None:
        return []
    return [
        anchor
        for group in before.automatic
        if group.conflicts_with(grown)
        for anchor in group.anchors
    ]
