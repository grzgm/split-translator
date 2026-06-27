import unittest

from split_translator.book_sync import BookSync


class BookSyncTests(unittest.TestCase):
    def test_start_and_end_anchors_always_present(self):
        s = BookSync(100, 80)
        anchors = s.get_anchors()
        self.assertEqual(anchors[0], (0, 0))
        self.assertEqual(anchors[-1], (99, 79))

    def test_exact_anchor_maps_exactly(self):
        s = BookSync(100, 80)
        s.set_anchors([(10, 8)])
        self.assertEqual(s.original_to_translation(10, 0.0), (8, 0.0))

    def test_midpoint_interpolates_between_anchors(self):
        s = BookSync(100, 80)
        s.set_anchors([(0, 0), (10, 20)])
        # Halfway from index 0 to index 10 on the original (index 5) maps to the
        # halfway point on the translation span 0..20, i.e. index 10.
        index, fraction = s.original_to_translation(5, 0.0)
        self.assertEqual(index, 10)
        self.assertAlmostEqual(fraction, 0.0, places=6)

    def test_inverse_round_trips_at_an_anchor(self):
        s = BookSync(100, 80)
        s.set_anchors([(10, 8)])
        self.assertEqual(s.translation_to_original(8, 0.0), (10, 0.0))

    def test_clamps_out_of_range_index(self):
        s = BookSync(100, 80)
        index, _ = s.original_to_translation(9999, 0.0)
        self.assertEqual(index, 79)

    def test_remove_does_not_drop_start_or_end(self):
        s = BookSync(100, 80)
        s.set_anchors([(10, 8)])
        s.remove_anchor(0)
        s.remove_anchor(99)
        self.assertEqual(s.get_anchors()[0], (0, 0))
        self.assertEqual(s.get_anchors()[-1], (99, 79))

    def test_set_anchors_forces_start_to_zero_zero(self):
        s = BookSync(100, 80)
        s.set_anchors([(0, 50)])
        self.assertEqual(s.get_anchors()[0], (0, 0))

    def test_add_anchor_cannot_overwrite_start(self):
        s = BookSync(100, 80)
        s.add_anchor(0, 50)
        self.assertEqual(s.get_anchors()[0], (0, 0))

    def test_add_anchor_cannot_overwrite_end(self):
        s = BookSync(100, 80)
        s.add_anchor(99, 50)
        self.assertEqual(s.get_anchors()[-1], (99, 79))

    def test_add_anchor_midpoint_changes_mapping(self):
        s = BookSync(100, 80)
        index_before, _ = s.original_to_translation(50, 0.0)
        s.add_anchor(50, 10)
        index_after, _ = s.original_to_translation(50, 0.0)
        self.assertNotEqual(index_before, index_after)

    def test_translation_to_original_midpoint(self):
        s = BookSync(100, 80)
        s.set_anchors([(0, 0), (10, 20)])
        # translation index 10 is the midpoint of 0..20, so it should map back
        # to original index 5 (the midpoint of 0..10).
        index, fraction = s.translation_to_original(10, 0.0)
        self.assertEqual(index, 5)
        self.assertAlmostEqual(fraction, 0.0, places=6)
