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

    def test_min_separation_keeps_nodes_apart(self):
        # Many nodes, no edges, so the force layout alone can leave pairs close;
        # the relaxation pass must push every pair at least min_separation apart.
        nodes = [f"n{i}" for i in range(12)]
        sep = 80.0
        pos = layout(nodes, [], width=800, height=600, min_separation=sep)
        items = list(pos.values())
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                (ax, ay), (bx, by) = items[i], items[j]
                # Allow a tiny epsilon: border clamping can shave a hair off.
                self.assertGreaterEqual(math.hypot(ax - bx, ay - by), sep - 1.0)

    def test_min_separation_is_deterministic(self):
        nodes = [f"n{i}" for i in range(8)]
        edges = [("n0", "n1"), ("n2", "n3")]
        a = layout(nodes, edges, min_separation=70.0)
        b = layout(nodes, edges, min_separation=70.0)
        self.assertEqual(a, b)

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
