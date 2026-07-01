"""Pure-logic force-directed layout for the flashcard graph.

A small Fruchterman-Reingold layout: nodes repel each other, edges act as
springs pulling their endpoints together. Initial placement is deterministic (a
circle ordered by sorted node id) so the same input always yields the same
output, which keeps it unit-testable. No Qt import; the graph window converts
these coordinates into scene positions."""

import math


def layout(
    node_ids: list[str],
    edges: list[tuple[str, str]],
    width: float = 800.0,
    height: float = 600.0,
    iterations: int = 200,
    min_separation: float = 0.0,
) -> dict[str, tuple[float, float]]:
    """Return a position (x, y) for every node id, within [0, width] x [0,
    height]. Deterministic for a given input.

    min_separation, if > 0, is the minimum centre-to-centre distance any two
    nodes must end up apart. After the force layout settles, a relaxation pass
    pushes any closer pair apart, so nodes drawn at a fixed radius never visually
    overlap on the initial load. Pass node diameter plus a gap."""
    nodes = list(node_ids)
    if not nodes:
        return {}

    # Deterministic initial placement: evenly spaced on a circle, ordered by id.
    ordered = sorted(nodes)
    cx, cy = width / 2.0, height / 2.0
    radius = min(width, height) / 3.0
    pos = {}
    n = len(ordered)
    for i, node in enumerate(ordered):
        angle = (2.0 * math.pi * i) / n
        pos[node] = [cx + radius * math.cos(angle), cy + radius * math.sin(angle)]

    if n == 1:
        only = ordered[0]
        return {only: (pos[only][0], pos[only][1])}

    area = width * height
    k = math.sqrt(area / n)  # ideal edge length
    adjacency = [(a, b) for a, b in edges if a in pos and b in pos]
    temperature = width / 10.0
    cooling = temperature / (iterations + 1)

    # The target area the settled layout is scaled into. An inner margin leaves
    # a gutter so the graph floats inside the scene rather than touching the
    # frame. This is applied ONCE at the end (in _spread_to_fill), never as a
    # per-iteration clamp: clamping inside the loop makes repelled nodes pile
    # flat against these bounds (which reads as a bug), because with many nodes
    # and few edges repulsion dominates and pushes everything outward. Letting
    # the layout settle freely gives a natural blob that the spread then fits.
    margin = min(width, height) * 0.08
    min_x, max_x = margin, width - margin
    min_y, max_y = margin, height - margin

    for _ in range(iterations):
        disp = {node: [0.0, 0.0] for node in ordered}

        # Repulsive forces between every pair.
        for i in range(n):
            for j in range(i + 1, n):
                a, b = ordered[i], ordered[j]
                dx = pos[a][0] - pos[b][0]
                dy = pos[a][1] - pos[b][1]
                dist = math.hypot(dx, dy) or 0.01
                force = (k * k) / dist
                ux, uy = dx / dist, dy / dist
                disp[a][0] += ux * force
                disp[a][1] += uy * force
                disp[b][0] -= ux * force
                disp[b][1] -= uy * force

        # Attractive forces along edges.
        for a, b in adjacency:
            dx = pos[a][0] - pos[b][0]
            dy = pos[a][1] - pos[b][1]
            dist = math.hypot(dx, dy) or 0.01
            force = (dist * dist) / k
            ux, uy = dx / dist, dy / dist
            disp[a][0] -= ux * force
            disp[a][1] -= uy * force
            disp[b][0] += ux * force
            disp[b][1] += uy * force

        # Apply displacement capped by the current temperature, then cool. No
        # clamp here: the layout settles freely and _spread_to_fill scales the
        # settled blob into the margins afterwards (see the margin comment).
        for node in ordered:
            dx, dy = disp[node]
            d = math.hypot(dx, dy) or 0.01
            step = min(d, temperature)
            pos[node][0] += (dx / d) * step
            pos[node][1] += (dy / d) * step
        temperature -= cooling

    # Spread the settled cluster out to fill the whole canvas rather than
    # clumping in the centre, while keeping connected nodes near each other
    # (this only scales and centres, it does not change relative positions).
    _spread_to_fill(ordered, pos, min_x, max_x, min_y, max_y)

    # Relax overlaps LAST so it has the final say: fixed-radius nodes never
    # visually overlap even after the spread pushed some pairs close.
    if min_separation > 0.0:
        _relax_overlaps(ordered, pos, min_separation,
                        min_x, max_x, min_y, max_y)

    return {node: (pos[node][0], pos[node][1]) for node in ordered}


def _spread_to_fill(ordered, pos, min_x, max_x, min_y, max_y):
    """Scale and centre the settled positions so their bounding box fills the
    [min_x, max_x] x [min_y, max_y] area. Preserves relative placement (and so
    the clustering), just uses the whole canvas instead of the middle third."""
    xs = [pos[node][0] for node in ordered]
    ys = [pos[node][1] for node in ordered]
    lo_x, hi_x = min(xs), max(xs)
    lo_y, hi_y = min(ys), max(ys)
    span_x = hi_x - lo_x
    span_y = hi_y - lo_y
    target_w = max_x - min_x
    target_h = max_y - min_y

    # Uniform scale keeps the layout's aspect ratio (no stretching). Degenerate
    # spans (all nodes on a line) scale only the non-degenerate axis.
    scale_x = target_w / span_x if span_x > 0.01 else 1.0
    scale_y = target_h / span_y if span_y > 0.01 else 1.0
    scale = min(scale_x, scale_y)

    # Centre the scaled box within the target area.
    scaled_w = span_x * scale
    scaled_h = span_y * scale
    off_x = min_x + (target_w - scaled_w) / 2.0
    off_y = min_y + (target_h - scaled_h) / 2.0
    for node in ordered:
        pos[node][0] = off_x + (pos[node][0] - lo_x) * scale
        pos[node][1] = off_y + (pos[node][1] - lo_y) * scale


def _relax_overlaps(ordered, pos, min_sep, min_x, max_x, min_y, max_y):
    """Push apart any pair of nodes closer than min_sep, so fixed-radius nodes
    do not visually overlap. Deterministic: pairs are visited in id order and no
    randomness is used. A short fixed number of passes is enough for the modest
    node counts this graph shows; leftover crowding is spread, not stacked."""
    n = len(ordered)
    for _ in range(60):
        moved = False
        for i in range(n):
            for j in range(i + 1, n):
                a, b = ordered[i], ordered[j]
                dx = pos[a][0] - pos[b][0]
                dy = pos[a][1] - pos[b][1]
                dist = math.hypot(dx, dy)
                if dist >= min_sep:
                    continue
                moved = True
                if dist < 0.01:
                    # Coincident: separate along a deterministic axis derived
                    # from their order so the result stays reproducible.
                    ux, uy = (1.0, 0.0) if i % 2 == 0 else (0.0, 1.0)
                    dist = 0.01
                else:
                    ux, uy = dx / dist, dy / dist
                shift = (min_sep - dist) / 2.0
                # Move each node half the gap, but a node pinned to the border
                # cannot move; the clamp would leave the pair overlapping. So
                # measure how far each actually moved and pass any shortfall to
                # the partner, which is usually free to absorb it.
                short_a = _shove(pos, a, ux * shift, uy * shift,
                                 min_x, max_x, min_y, max_y)
                _shove(pos, b, -ux * shift - short_a[0],
                       -uy * shift - short_a[1],
                       min_x, max_x, min_y, max_y)
        if not moved:
            break


def _shove(pos, node, dx, dy, min_x, max_x, min_y, max_y):
    """Move a node by (dx, dy), clamped to bounds. Return the (x, y) shortfall:
    how much of the requested move the clamp swallowed, so the caller can hand
    the leftover to the partner node."""
    want_x = pos[node][0] + dx
    want_y = pos[node][1] + dy
    new_x = min(max_x, max(min_x, want_x))
    new_y = min(max_y, max(min_y, want_y))
    pos[node][0] = new_x
    pos[node][1] = new_y
    return (want_x - new_x, want_y - new_y)
