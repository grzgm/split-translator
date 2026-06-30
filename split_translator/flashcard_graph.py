"""Flashcard relationship graph: a separate window drawing cards as nodes and
links as colour-coded edges, using native QGraphicsView. Layout comes from the
pure-logic graph_layout module; this file is the Qt presentation and the
interactions (drag, click-to-activate, type filter, node search) and an
incremental refresh that preserves manually arranged node positions."""

from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPen
from PySide6.QtWidgets import (
    QCheckBox,
    QGraphicsEllipseItem,
    QGraphicsLineItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .flashcards import LINK_FALLBACK_COLOUR, LINK_TYPES
from .graph_layout import layout

_NODE_RADIUS = 18.0
_SCENE_W = 800.0
_SCENE_H = 600.0


class _NodeItem(QGraphicsEllipseItem):
    """A draggable node that reports clicks back to the window via a callback."""

    def __init__(self, card_id: str, on_click, starred: bool):
        super().__init__(-_NODE_RADIUS, -_NODE_RADIUS,
                         2 * _NODE_RADIUS, 2 * _NODE_RADIUS)
        self.card_id = card_id
        self._on_click = on_click
        self.setFlag(QGraphicsEllipseItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(
            QGraphicsEllipseItem.GraphicsItemFlag.ItemSendsGeometryChanges, True
        )
        self.setBrush(QBrush(QColor("#cfe3ff")))
        outline = QColor("#f0b400") if starred else QColor("#2b6cb0")
        self.setPen(QPen(outline, 3 if starred else 1))
        self.setZValue(1)

    def mousePressEvent(self, event):
        self._on_click(self.card_id)
        super().mousePressEvent(event)


class FlashcardGraphWindow(QWidget):
    """Window showing the flashcard relationship graph."""

    card_activated = Signal(str)

    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self.setWindowTitle("Flashcard Graph")
        self.resize(900, 700)

        self._nodes = {}            # card_id -> _NodeItem
        self._labels = {}           # card_id -> QGraphicsSimpleTextItem
        self._edges = {}            # (a_id, b_id, type) -> QGraphicsLineItem
        self._node_positions = {}   # card_id -> (x, y)
        self._hidden_types = set()

        outer = QVBoxLayout(self)

        controls = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Find a card")
        self.search_input.returnPressed.connect(
            lambda: self.focus_node(self.search_input.text())
        )
        find_button = QPushButton("Find")
        find_button.clicked.connect(
            lambda: self.focus_node(self.search_input.text())
        )
        controls.addWidget(self.search_input)
        controls.addWidget(find_button)
        outer.addLayout(controls)

        # Type filter checkboxes, one per shipped type, colour-swatched in text.
        self.type_checks = {}
        legend = QHBoxLayout()
        legend.addWidget(QLabel("Show:"))
        for key, label, colour in LINK_TYPES:
            box = QCheckBox(label)
            box.setChecked(True)
            box.setStyleSheet(f"color: {colour}; font-weight: bold;")
            box.toggled.connect(
                lambda checked, k=key: self.set_type_visible(k, checked)
            )
            self.type_checks[key] = box
            legend.addWidget(box)
        legend.addStretch()
        outer.addLayout(legend)

        self.scene = QGraphicsScene(self)
        self.view = QGraphicsView(self.scene)
        self.view.setRenderHint(self.view.renderHints())
        self.view.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        outer.addWidget(self.view, stretch=1)

    # --- helpers --------------------------------------------------------

    def colour_for(self, type_key: str) -> str:
        for key, _label, colour in LINK_TYPES:
            if key == type_key:
                return colour
        return LINK_FALLBACK_COLOUR

    def _emit_node_clicked(self, card_id: str) -> None:
        self.card_activated.emit(card_id)

    def _edge_key(self, link) -> tuple:
        return (link.a_id, link.b_id, link.type)

    # --- build ----------------------------------------------------------

    def rebuild(self) -> None:
        """Full rebuild: lay every node out from scratch and draw all nodes and
        edges. Called when the window is opened."""
        self.scene.clear()
        self._nodes.clear()
        self._labels.clear()
        self._edges.clear()

        node_ids = [c.id for c in self.store.cards]
        edges = [(l.a_id, l.b_id) for l in self.store.links]
        self._node_positions = layout(node_ids, edges, _SCENE_W, _SCENE_H)

        for card in self.store.cards:
            self._add_node_item(card)
        for link in self.store.links:
            self._add_edge_item(link)
        self._apply_type_visibility()

    def _add_node_item(self, card) -> None:
        x, y = self._node_positions.get(card.id, (_SCENE_W / 2, _SCENE_H / 2))
        node = _NodeItem(card.id, self._emit_node_clicked, bool(card.starred))
        node.setPos(QPointF(x, y))
        self.scene.addItem(node)
        self._nodes[card.id] = node

        label = QGraphicsSimpleTextItem(card.headword)
        label.setZValue(2)
        label.setPos(QPointF(x + _NODE_RADIUS, y - _NODE_RADIUS))
        self.scene.addItem(label)
        self._labels[card.id] = label

    def _add_edge_item(self, link) -> None:
        a = self._nodes.get(link.a_id)
        b = self._nodes.get(link.b_id)
        if a is None or b is None:
            return
        line = QGraphicsLineItem()
        line.setZValue(0)
        pen = QPen(QColor(self.colour_for(link.type)), 2)
        line.setPen(pen)
        line.link_type = link.type
        self._edges[self._edge_key(link)] = line
        self.scene.addItem(line)
        self._position_edge(line, a, b)

    def _position_edge(self, line, a, b) -> None:
        pa, pb = a.pos(), b.pos()
        line.setLine(pa.x(), pa.y(), pb.x(), pb.y())

    # --- incremental refresh -------------------------------------------

    def refresh(self) -> None:
        """Update in place after the store changes, keeping existing node
        positions. New nodes get a position near a neighbour (or centre); gone
        nodes and their edges are removed; edges are rebuilt from current links."""
        current_ids = {c.id for c in self.store.cards}

        # Remove gone nodes and their labels.
        for gone in [cid for cid in self._nodes if cid not in current_ids]:
            self.scene.removeItem(self._nodes.pop(gone))
            self.scene.removeItem(self._labels.pop(gone))
            self._node_positions.pop(gone, None)

        # Add new nodes near an existing neighbour, else centre.
        for card in self.store.cards:
            if card.id in self._nodes:
                continue
            self._node_positions[card.id] = self._placement_for(card.id)
            self._add_node_item(card)

        # Rebuild edges from current links (cheap; keeps colours/types correct).
        for line in self._edges.values():
            self.scene.removeItem(line)
        self._edges.clear()
        for link in self.store.links:
            self._add_edge_item(link)
        self._apply_type_visibility()

    def _placement_for(self, card_id: str) -> tuple:
        """Position a brand-new node near its first linked neighbour, else at the
        scene centre, offset a little so two new nodes do not stack exactly."""
        for link in self.store.links:
            if link.a_id == card_id and link.b_id in self._nodes:
                p = self._nodes[link.b_id].pos()
                return (p.x() + 40.0, p.y() + 40.0)
            if link.b_id == card_id and link.a_id in self._nodes:
                p = self._nodes[link.a_id].pos()
                return (p.x() + 40.0, p.y() + 40.0)
        return (_SCENE_W / 2.0, _SCENE_H / 2.0)

    # --- type filter ----------------------------------------------------

    def set_type_visible(self, type_key: str, visible: bool) -> None:
        if visible:
            self._hidden_types.discard(type_key)
        else:
            self._hidden_types.add(type_key)
        self._apply_type_visibility()

    def _apply_type_visibility(self) -> None:
        for line in self._edges.values():
            line.setVisible(line.link_type not in self._hidden_types)

    # --- search ---------------------------------------------------------

    def focus_node(self, headword: str) -> None:
        needle = headword.strip().lower()
        if not needle:
            return
        for card in self.store.cards:
            if needle in card.headword.lower() and card.id in self._nodes:
                node = self._nodes[card.id]
                self.view.centerOn(node)
                node.setBrush(QBrush(QColor("#ffe08a")))
                return
