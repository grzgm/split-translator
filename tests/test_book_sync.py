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
