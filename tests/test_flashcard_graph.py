import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from split_translator.flashcard_graph import FlashcardGraphWindow
from split_translator.flashcards import Card, FlashcardStore, Link

app = QApplication.instance() or QApplication([])


class GraphWindowTests(unittest.TestCase):
    def _store(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        store = FlashcardStore(Path(tmp.name) / "f.json")
        self.addCleanup(store.shutdown)
        store.cards = [
            Card(headword="big", id="big"),
            Card(headword="large", id="large"),
            Card(headword="small", id="small"),
        ]
        store.links = [Link("big", "large", "synonym"),
                       Link("big", "small", "antonym")]
        return store

    def test_rebuild_creates_a_node_per_card(self):
        win = FlashcardGraphWindow(self._store())
        win.rebuild()
        self.assertEqual(len(win._nodes), 3)

    def test_rebuild_creates_an_edge_per_link(self):
        win = FlashcardGraphWindow(self._store())
        win.rebuild()
        self.assertEqual(len(win._edges), 2)

    def test_colour_for_known_type(self):
        win = FlashcardGraphWindow(self._store())
        self.assertEqual(win.colour_for("synonym"), "#1b7a2f")

    def test_colour_for_unknown_type_is_fallback(self):
        win = FlashcardGraphWindow(self._store())
        self.assertEqual(win.colour_for("mystery"), "#888888")

    def test_clicking_a_node_emits_card_activated(self):
        win = FlashcardGraphWindow(self._store())
        win.rebuild()
        emitted = []
        win.card_activated.connect(emitted.append)
        win._emit_node_clicked("big")  # the click handler nodes call
        self.assertEqual(emitted, ["big"])

    def _press_release(self, node, start, end):
        # Drive the node's real press/release handlers with genuine scene mouse
        # events, so the click-vs-drag decision under test is actually executed.
        from PySide6.QtCore import QPointF, Qt
        from PySide6.QtWidgets import QGraphicsSceneMouseEvent

        press = QGraphicsSceneMouseEvent()
        press.setScenePos(QPointF(*start))
        press.setButton(Qt.MouseButton.LeftButton)
        node.mousePressEvent(press)

        release = QGraphicsSceneMouseEvent()
        release.setScenePos(QPointF(*end))
        release.setButton(Qt.MouseButton.LeftButton)
        node.mouseReleaseEvent(release)

    def test_small_movement_counts_as_click(self):
        win = FlashcardGraphWindow(self._store())
        win.rebuild()
        emitted = []
        win.card_activated.connect(emitted.append)
        self._press_release(win._nodes["big"], (10.0, 10.0), (12.0, 11.0))
        self.assertEqual(emitted, ["big"])

    def test_drag_does_not_activate_the_card(self):
        win = FlashcardGraphWindow(self._store())
        win.rebuild()
        emitted = []
        win.card_activated.connect(emitted.append)
        self._press_release(win._nodes["big"], (10.0, 10.0), (80.0, 60.0))
        self.assertEqual(emitted, [])

    def test_type_filter_hides_edges_of_that_type(self):
        win = FlashcardGraphWindow(self._store())
        win.rebuild()
        win.set_type_visible("antonym", False)
        hidden = [e for e in win._edges.values() if not e.isVisible()]
        self.assertEqual(len(hidden), 1)

    def test_refresh_keeps_existing_node_positions(self):
        store = self._store()
        win = FlashcardGraphWindow(store)
        win.rebuild()
        pos_before = dict(win._node_positions)
        # Add a new card and a link; refresh should keep old positions.
        store.cards.append(Card(headword="tiny", id="tiny"))
        store.links.append(Link("small", "tiny", "related"))
        win.refresh()
        for node_id, pos in pos_before.items():
            self.assertEqual(win._node_positions[node_id], pos)
        self.assertIn("tiny", win._node_positions)

    def test_moving_a_node_follows_label_edge_and_position(self):
        from PySide6.QtCore import QPointF
        win = FlashcardGraphWindow(self._store())
        win.rebuild()
        node = win._nodes["big"]
        label = win._labels["big"]
        # An edge that touches "big".
        edge = next(line for (a, b, _t), line in win._edges.items()
                    if "big" in (a, b))

        node.setPos(QPointF(123.0, 45.0))

        # Stored position updated to the node's new spot.
        self.assertEqual(win._node_positions["big"], (123.0, 45.0))
        # Label is centred horizontally on the node and sits below it. Its exact
        # x depends on the rendered text width, so assert the centring relation
        # (label centre == node centre) rather than a pixel value.
        rect = label.boundingRect()
        self.assertAlmostEqual(label.pos().x() + rect.width() / 2.0, 123.0)
        self.assertGreater(label.pos().y(), 45.0)   # below the node
        # The edge endpoint at "big"'s end now passes through (123, 45). Because
        # the line is drawn between the two node centres, one of its endpoints
        # equals the node's new position.
        ln = edge.line()
        endpoints = {(ln.x1(), ln.y1()), (ln.x2(), ln.y2())}
        self.assertIn((123.0, 45.0), endpoints)
