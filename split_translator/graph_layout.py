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
) -> dict[str, tuple[float, float]]:
    """Return a position (x, y) for every node id, within [0, width] x [0,
    height]. Deterministic for a given input."""
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

        # Apply displacement capped by the current temperature, then cool.
        for node in ordered:
            dx, dy = disp[node]
            d = math.hypot(dx, dy) or 0.01
            step = min(d, temperature)
            pos[node][0] += (dx / d) * step
            pos[node][1] += (dy / d) * step
            pos[node][0] = min(width, max(0.0, pos[node][0]))
            pos[node][1] = min(height, max(0.0, pos[node][1]))
        temperature -= cooling

    return {node: (pos[node][0], pos[node][1]) for node in ordered}
