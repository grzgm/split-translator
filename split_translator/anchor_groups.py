"""Anchors grouped by the paragraphs they share.

An anchor links one original paragraph to one translation paragraph. Anchors
that share a paragraph on either side belong to one group, which is how one
paragraph is matched to several: a paragraph split in two in the other edition
takes two anchors from the same paragraph. A group covers every paragraph from
its first to its last on each side, the paragraphs in between included.

Groups keep the reading order: ordered by their original paragraphs, each group
ends before the next begins on both sides. Two groups that overlap, or whose
order differs between the editions (they cross), cannot both hold.

Pure logic with no Qt import, so it unit-tests headless."""

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
