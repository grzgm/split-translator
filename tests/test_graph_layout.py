import math
import unittest

from split_translator.graph_layout import layout


class GraphLayoutTests(unittest.TestCase):
    def test_returns_a_position_for_every_node(self):
        pos = layout(["a", "b", "c"], [("a", "b")])
        self.assertEqual(set(pos), {"a", "b", "c"})
        for xy in pos.values():
            self.assertEqual(len(xy), 2)

    def test_is_deterministic(self):
        nodes = ["a", "b", "c", "d"]
        edges = [("a", "b"), ("b", "c")]
        self.assertEqual(layout(nodes, edges), layout(nodes, edges))

    def test_empty_graph_returns_empty(self):
        self.assertEqual(layout([], []), {})

    def test_connected_nodes_end_closer_than_unconnected(self):
        # a-b connected; c isolated. After layout, a and b should be closer to
        # each other than a is to c (the spring pulls connected nodes together).
        pos = layout(["a", "b", "c"], [("a", "b")], iterations=400)

        def dist(p, q):
            return math.hypot(p[0] - q[0], p[1] - q[1])

        self.assertLess(dist(pos["a"], pos["b"]), dist(pos["a"], pos["c"]))

    def test_positions_within_bounds(self):
        pos = layout(["a", "b", "c"], [("a", "b"), ("b", "c")],
                     width=500, height=400)
        for x, y in pos.values():
            self.assertGreaterEqual(x, 0)
            self.assertLessEqual(x, 500)
            self.assertGreaterEqual(y, 0)
            self.assertLessEqual(y, 400)
