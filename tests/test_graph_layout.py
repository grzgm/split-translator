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
                # Shortfall compensation hands a clamped node's leftover shift to
                # its partner, so the target is met cleanly (small epsilon only
                # for float rounding), not left overlapping at the border.
                self.assertGreaterEqual(
                    math.hypot(ax - bx, ay - by), sep - 0.01)

    def test_min_separation_is_deterministic(self):
        nodes = [f"n{i}" for i in range(8)]
        edges = [("n0", "n1"), ("n2", "n3")]
        a = layout(nodes, edges, min_separation=70.0)
        b = layout(nodes, edges, min_separation=70.0)
        self.assertEqual(a, b)

    def test_spread_fills_the_canvas(self):
        # After the spread pass the nodes should reach out toward the canvas
        # edges (within the 8% inner margin), not clump in the middle third.
        nodes = [f"n{i}" for i in range(10)]
        edges = [("n0", "n1"), ("n1", "n2"), ("n3", "n4")]
        w, h = 800.0, 600.0
        pos = layout(nodes, edges, width=w, height=h)
        xs = [x for x, _ in pos.values()]
        ys = [y for _, y in pos.values()]
        span_x = max(xs) - min(xs)
        span_y = max(ys) - min(ys)
        # Uniform scaling fills one axis fully; the other fills proportionally.
        # Either way the layout must span far more than the old middle third
        # (~1/3 of the canvas). Assert the larger span fills most of its axis.
        avail_w = w * (1 - 2 * 0.08)
        avail_h = h * (1 - 2 * 0.08)
        fill = max(span_x / avail_w, span_y / avail_h)
        self.assertGreater(fill, 0.9)

    def test_many_nodes_few_edges_do_not_pile_on_the_border(self):
        # The real failure case: many cards with almost no links. Repulsion
        # dominates and, with a hard in-loop clamp, flings every node flat
        # against the frame (reads as a bug). Most nodes must settle in the
        # interior, not on the margin rectangle.
        nodes = [f"n{i}" for i in range(41)]
        edges = [("n0", "n1"), ("n2", "n3")]
        w, h = 900.0, 640.0
        margin = min(w, h) * 0.08
        min_x, max_x = margin, w - margin
        min_y, max_y = margin, h - margin
        pos = layout(nodes, edges, width=w, height=h)
        on_edge = 0
        for x, y in pos.values():
            if (abs(x - min_x) < 1 or abs(x - max_x) < 1
                    or abs(y - min_y) < 1 or abs(y - max_y) < 1):
                on_edge += 1
        # A handful touching the edge is fine (they define the bounding box the
        # spread scales to); the bulk must be interior.
        self.assertLess(on_edge, len(nodes) // 4)

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
