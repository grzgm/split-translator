import unittest

from split_translator.anchor_groups import (
    Group,
    add_conflict,
    build_groups,
    first_conflict,
    group_paragraphs,
    resolve_manual,
)

IDS = [f"b{i}" for i in range(10)]


def _groups(anchors):
    return build_groups(anchors, IDS, IDS)


class BuildGroupsTests(unittest.TestCase):
    def test_one_anchor_is_one_group_of_one_paragraph_each_side(self):
        self.assertEqual(
            _groups([("b2", "b3")]),
            [Group((("b2", "b3"),), 2, 2, 3, 3)],
        )

    def test_anchors_sharing_an_original_paragraph_join(self):
        # b2 is split in two in the translation: it matches b3 to b5.
        (group,) = _groups([("b2", "b3"), ("b2", "b5")])
        self.assertEqual(
            (group.original_first, group.original_last), (2, 2)
        )
        self.assertEqual(
            (group.translation_first, group.translation_last), (3, 5)
        )

    def test_anchors_sharing_a_translation_paragraph_join(self):
        (group,) = _groups([("b2", "b3"), ("b4", "b3")])
        self.assertEqual(
            (group.original_first, group.original_last), (2, 4)
        )
        self.assertEqual(
            (group.translation_first, group.translation_last), (3, 3)
        )

    def test_a_chain_of_shared_paragraphs_is_one_group(self):
        (group,) = _groups([("b1", "b1"), ("b1", "b2"), ("b3", "b2")])
        self.assertEqual(len(group.anchors), 3)
        self.assertEqual(
            (group.original_first, group.original_last), (1, 3)
        )
        self.assertEqual(
            (group.translation_first, group.translation_last), (1, 2)
        )

    def test_groups_are_ordered_by_their_original_paragraphs(self):
        groups = _groups([("b6", "b6"), ("b1", "b1")])
        self.assertEqual([g.original_first for g in groups], [1, 6])

    def test_anchors_naming_a_non_paragraph_are_left_out(self):
        groups = _groups([("b1", "b99"), ("x", "b1"), ("b2", "b2")])
        self.assertEqual([g.anchors for g in groups], [(("b2", "b2"),)])

    def test_an_exact_duplicate_counts_once(self):
        (group,) = _groups([("b1", "b1"), ("b1", "b1")])
        self.assertEqual(group.anchors, (("b1", "b1"),))

    def test_anchors_keep_their_stored_order_inside_a_group(self):
        (group,) = _groups([("b2", "b5"), ("b2", "b3")])
        self.assertEqual(group.anchors, (("b2", "b5"), ("b2", "b3")))


class ConflictTests(unittest.TestCase):
    def test_groups_in_reading_order_have_no_conflict(self):
        self.assertIsNone(first_conflict(_groups([("b1", "b1"), ("b4", "b6")])))

    def test_an_extent_reaching_into_the_next_group_is_a_conflict(self):
        # b1 matches b1 to b5, so b3 = b3 sits inside that extent.
        groups = _groups([("b1", "b1"), ("b1", "b5"), ("b3", "b3")])
        self.assertIsNotNone(first_conflict(groups))

    def test_groups_in_a_different_order_per_edition_cross(self):
        groups = _groups([("b1", "b5"), ("b3", "b2")])
        before, after = first_conflict(groups)
        self.assertTrue(before.conflicts_with(after))
        self.assertFalse(before.precedes(after))


class ResolveManualTests(unittest.TestCase):
    def test_a_later_anchor_that_crosses_is_set_aside(self):
        groups, conflicting = resolve_manual(
            [("b1", "b5"), ("b3", "b2"), ("b6", "b7")], IDS, IDS
        )
        self.assertEqual(
            [g.anchors for g in groups], [(("b1", "b5"),), (("b6", "b7"),)]
        )
        self.assertEqual(conflicting, [("b3", "b2")])

    def test_unknown_ids_are_ignored_without_being_reported(self):
        self.assertEqual(resolve_manual([("b1", "b99")], IDS, IDS), ([], []))

    def test_a_duplicate_is_neither_a_conflict_nor_counted_twice(self):
        groups, conflicting = resolve_manual(
            [("b1", "b1"), ("b1", "b1")], IDS, IDS
        )
        self.assertEqual(conflicting, [])
        self.assertEqual([g.anchors for g in groups], [(("b1", "b1"),)])


class AddConflictTests(unittest.TestCase):
    def test_growing_a_group_cleanly_is_allowed(self):
        self.assertIsNone(
            add_conflict([("b1", "b1"), ("b5", "b5")], ("b1", "b2"), IDS, IDS)
        )

    def test_a_crossing_anchor_names_the_anchor_it_crosses(self):
        self.assertEqual(
            add_conflict([("b1", "b1"), ("b5", "b5")], ("b6", "b3"), IDS, IDS),
            ("b5", "b5"),
        )

    def test_growth_that_overlaps_the_next_group_names_that_group(self):
        self.assertEqual(
            add_conflict([("b1", "b1"), ("b3", "b3")], ("b1", "b4"), IDS, IDS),
            ("b3", "b3"),
        )

    def test_an_anchor_already_set_aside_never_blocks(self):
        # b3 = b2 conflicts on load, so only b1 = b5 counts.
        self.assertIsNone(
            add_conflict([("b1", "b5"), ("b3", "b2")], ("b3", "b6"), IDS, IDS)
        )


class GroupParagraphsTests(unittest.TestCase):
    def test_lists_every_paragraph_of_the_extent_on_each_side(self):
        (group,) = _groups([("b1", "b2"), ("b3", "b2")])
        self.assertEqual(
            group_paragraphs(group, IDS, IDS), (["b1", "b2", "b3"], ["b2"])
        )
