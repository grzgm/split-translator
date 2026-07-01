"""Flashcard relationship graph: a separate window drawing cards as nodes and
links as colour-coded edges, using native QGraphicsView. Layout comes from the
pure-logic graph_layout module; this file is the Qt presentation and the
interactions (drag, click-to-activate, type filter, node search) and an
incremental refresh that preserves manually arranged node positions."""

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QPainter,
    QPen,
)
from PySide6.QtWidgets import (
    QCheckBox,
    QGraphicsDropShadowEffect,
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

_NODE_RADIUS = 26.0
_SCENE_W = 900.0
_SCENE_H = 640.0

# A calm, modern palette.
_CANVAS = "#f4f6fb"          # light view background
_NODE_FILL = "#ffffff"       # node body
_NODE_FILL_STAR = "#fff6da"  # starred node body (warm)
_NODE_EDGE = "#c3ccd8"       # node outline
_NODE_EDGE_STAR = "#e0a800"  # starred node outline
_LABEL_COLOUR = "#2b3440"    # headword text
_HIGHLIGHT = "#ffd35c"       # search hit fill
_FIT_MARGIN = 60.0           # scene padding when fitting the view
_CLICK_SLOP = 4.0            # max scene-pixel travel still counted as a click


class _NodeItem(QGraphicsEllipseItem):
    """A draggable node. Reports clicks to the window and, on every move, tells
    the window to follow with the node's label, its edges and its stored
    position."""

    def __init__(self, card_id: str, window, starred: bool):
        super().__init__(-_NODE_RADIUS, -_NODE_RADIUS,
                         2 * _NODE_RADIUS, 2 * _NODE_RADIUS)
        self.card_id = card_id
        self._window = window
        self._starred = starred
        self.setFlag(QGraphicsEllipseItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(
            QGraphicsEllipseItem.GraphicsItemFlag.ItemSendsGeometryChanges, True
        )
        self.setAcceptHoverEvents(True)
        self._apply_base_style()
        self.setZValue(1)
        self._press_scene_pos = None

        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(16)
        shadow.setOffset(0, 3)
        shadow.setColor(QColor(30, 40, 60, 70))
        self.setGraphicsEffect(shadow)

    def _apply_base_style(self) -> None:
        fill = _NODE_FILL_STAR if self._starred else _NODE_FILL
        outline = _NODE_EDGE_STAR if self._starred else _NODE_EDGE
        self.setBrush(QBrush(QColor(fill)))
        self.setPen(QPen(QColor(outline), 3 if self._starred else 2))

    def highlight(self) -> None:
        self.setBrush(QBrush(QColor(_HIGHLIGHT)))
        self.setPen(QPen(QColor(_NODE_EDGE_STAR), 3))

    def mousePressEvent(self, event):
        # Remember where the press started so mouseReleaseEvent can tell a click
        # (activate the card) from a drag (move the node). Emitting on press
        # would fire on every click-and-hold, opening the card the moment you
        # start dragging.
        self._press_scene_pos = event.scenePos()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        start = self._press_scene_pos
        self._press_scene_pos = None
        super().mouseReleaseEvent(event)
        if start is None:
            return
        moved = event.scenePos() - start
        # A few pixels of travel is still a click, not a drag.
        if abs(moved.x()) <= _CLICK_SLOP and abs(moved.y()) <= _CLICK_SLOP:
            self._window._emit_node_clicked(self.card_id)

    def hoverEnterEvent(self, event):
        self.setPen(QPen(QColor("#4a90d9"), 3))
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self._apply_base_style()
        super().hoverLeaveEvent(event)

    def itemChange(self, change, value):
        # Fired for every position change because ItemSendsGeometryChanges is
        # set. value is the node's new QPointF position; tell the window to move
        # the label and edges and record the new position.
        if change == QGraphicsEllipseItem.GraphicsItemChange.ItemPositionHasChanged:
            self._window._on_node_moved(self.card_id)
        return super().itemChange(change, value)


class FlashcardGraphWindow(QWidget):
    """Window showing the flashcard relationship graph."""

    card_activated = Signal(str)

    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self.setWindowTitle("Flashcard Graph")
        self.resize(960, 760)

        self._nodes = {}            # card_id -> _NodeItem
        self._labels = {}           # card_id -> QGraphicsSimpleTextItem
        self._edges = {}            # (a_id, b_id, type) -> QGraphicsLineItem
        self._node_positions = {}   # card_id -> (x, y)
        self._hidden_types = set()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 14, 14, 14)
        outer.setSpacing(10)

        controls = QHBoxLayout()
        controls.setSpacing(8)
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Find a card")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.returnPressed.connect(
            lambda: self.focus_node(self.search_input.text())
        )
        find_button = QPushButton("Find")
        find_button.clicked.connect(
            lambda: self.focus_node(self.search_input.text())
        )
        fit_button = QPushButton("Fit to view")
        fit_button.clicked.connect(self.fit_to_content)
        controls.addWidget(self.search_input, stretch=1)
        controls.addWidget(find_button)
        controls.addWidget(fit_button)
        outer.addLayout(controls)

        # Type filter checkboxes, one per shipped type, colour-swatched in text.
        self.type_checks = {}
        legend = QHBoxLayout()
        legend.setSpacing(14)
        show_label = QLabel("Show:")
        show_label.setStyleSheet("color: #55606e;")
        legend.addWidget(show_label)
        for key, label, colour in LINK_TYPES:
            box = QCheckBox(label)
            box.setChecked(True)
            box.setStyleSheet(f"color: {colour}; font-weight: 600;")
            box.toggled.connect(
                lambda checked, k=key: self.set_type_visible(k, checked)
            )
            self.type_checks[key] = box
            legend.addWidget(box)
        legend.addStretch()
        outer.addLayout(legend)

        self.scene = QGraphicsScene(self)
        self.view = QGraphicsView(self.scene)
        self.view.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.view.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.view.setFrameShape(QGraphicsView.Shape.NoFrame)
        self.view.setBackgroundBrush(QBrush(QColor(_CANVAS)))
        self.view.setStyleSheet("QGraphicsView { border-radius: 10px; }")
        outer.addWidget(self.view, stretch=1)

        self.setStyleSheet(
            "QLineEdit, QPushButton {"
            " padding: 6px 12px; border: 1px solid #c3ccd8;"
            " border-radius: 6px; background: #ffffff; }"
            "QPushButton { font-weight: 600; }"
            "QPushButton:hover { background: #eef3fb; }"
        )

    # --- helpers --------------------------------------------------------

    def colour_for(self, type_key: str) -> str:
        for key, _label, colour in LINK_TYPES:
            if key == type_key:
                return colour
        return LINK_FALLBACK_COLOUR

    def _emit_node_clicked(self, card_id: str) -> None:
        self.card_activated.emit(card_id)

    def _on_node_moved(self, card_id: str) -> None:
        """Follow a node that has just moved: keep its label beside it, record
        its new position, and reposition every edge touching it."""
        node = self._nodes.get(card_id)
        if node is None:
            return
        pos = node.pos()
        self._node_positions[card_id] = (pos.x(), pos.y())
        self._place_label(card_id, pos)
        for (a_id, b_id, _type), line in self._edges.items():
            if card_id in (a_id, b_id):
                a = self._nodes.get(a_id)
                b = self._nodes.get(b_id)
                if a is not None and b is not None:
                    self._position_edge(line, a, b)

    def _place_label(self, card_id: str, pos: QPointF) -> None:
        """Centre the headword under its node."""
        label = self._labels.get(card_id)
        if label is None:
            return
        rect = label.boundingRect()
        label.setPos(QPointF(
            pos.x() - rect.width() / 2.0,
            pos.y() + _NODE_RADIUS + 4.0,
        ))

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
        # Keep node bodies (plus their labels' breathing room) from overlapping
        # on the initial layout: separate centres by more than a node diameter.
        min_sep = 2 * _NODE_RADIUS + 44.0
        self._node_positions = layout(
            node_ids, edges, _SCENE_W, _SCENE_H, min_separation=min_sep
        )

        for card in self.store.cards:
            self._add_node_item(card)
        for link in self.store.links:
            self._add_edge_item(link)
        self._apply_type_visibility()
        self.fit_to_content()

    def _add_node_item(self, card) -> None:
        x, y = self._node_positions.get(card.id, (_SCENE_W / 2, _SCENE_H / 2))
        node = _NodeItem(card.id, self, bool(card.starred))
        node.setPos(QPointF(x, y))
        self.scene.addItem(node)
        self._nodes[card.id] = node

        label = QGraphicsSimpleTextItem(card.headword)
        label.setZValue(2)
        font = QFont()
        font.setPointSize(10)
        font.setWeight(QFont.Weight.DemiBold)
        label.setFont(font)
        label.setBrush(QBrush(QColor(_LABEL_COLOUR)))
        self.scene.addItem(label)
        self._labels[card.id] = label
        self._place_label(card.id, QPointF(x, y))

    def _add_edge_item(self, link) -> None:
        a = self._nodes.get(link.a_id)
        b = self._nodes.get(link.b_id)
        if a is None or b is None:
            return
        line = QGraphicsLineItem()
        line.setZValue(0)
        pen = QPen(QColor(self.colour_for(link.type)), 2.5)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        line.setPen(pen)
        line.link_type = link.type
        self._edges[self._edge_key(link)] = line
        self.scene.addItem(line)
        self._position_edge(line, a, b)

    def _position_edge(self, line, a, b) -> None:
        pa, pb = a.pos(), b.pos()
        line.setLine(pa.x(), pa.y(), pb.x(), pb.y())

    # --- fit / view -----------------------------------------------------

    def fit_to_content(self) -> None:
        """Frame the whole graph with a margin so nodes are never pinned to the
        window edge. Falls back to the scene rect when there is nothing yet."""
        rect = self.scene.itemsBoundingRect()
        if rect.isNull():
            return
        padded = rect.adjusted(
            -_FIT_MARGIN, -_FIT_MARGIN, _FIT_MARGIN, _FIT_MARGIN
        )
        self.scene.setSceneRect(padded)
        self.view.fitInView(padded, Qt.AspectRatioMode.KeepAspectRatio)

    def showEvent(self, event):
        # First real geometry is only known once shown; fit then so the initial
        # frame is correct rather than using a zero-sized viewport.
        super().showEvent(event)
        self.fit_to_content()

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
                return (p.x() + 50.0, p.y() + 50.0)
            if link.b_id == card_id and link.a_id in self._nodes:
                p = self._nodes[link.a_id].pos()
                return (p.x() + 50.0, p.y() + 50.0)
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
                node.highlight()
                return
