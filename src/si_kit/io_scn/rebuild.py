# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Alex Doss
"""Live primitives rebuilt in Softimage's own point and polygon order (Softimage axes, Y up), so operators that
name components by index (Move Component) can be replayed. Orders measured from Softimage 2015 (corpus prim_*).
Only what the scenes need so far: the grid (any subdivisions), the 1 x 1 x 1 cube and the sphere (any U / V range)."""
import math

from . import movecomponent

_CUBE_POLYS = [[0, 2, 3, 1], [0, 1, 5, 4], [0, 4, 6, 2], [1, 3, 7, 5], [2, 6, 7, 3], [4, 5, 7, 6]]


def primitive_mesh(gen):
    """(points, polygons) of a live primitive in Softimage's order, or None when not supported here."""
    kind, p = gen["type"], gen["params"]
    if kind == "grid":
        u, v = p.get("subdivu", 8), p.get("subdivv", 8)
        lu, lv = p.get("ulength", 8.0), p.get("vlength", 8.0)
        pts = [(-lu / 2 + lu * i / u, 0.0, -lv / 2 + lv * j / v) for i in range(u + 1) for j in range(v + 1)]
        polys = [[i * (v + 1) + j, i * (v + 1) + j + 1, (i + 1) * (v + 1) + j + 1, (i + 1) * (v + 1) + j]
                 for i in range(u) for j in range(v)]
        return pts, polys
    if kind == "cube" and (p.get("subdivu", 1), p.get("subdivv", 1), p.get("subdivbase", 1)) == (1, 1, 1):
        h = p.get("length", 8.0) / 2
        pts = [(x, y, z) for z in (-h, h) for y in (-h, h) for x in (-h, h)]
        return pts, [list(f) for f in _CUBE_POLYS]
    if kind == "sphere":
        return _sphere(p)
    return None


def _sphere(p):
    """Sphere with any U / V range. V is measured from the bottom pole (0) to the top (180), U from -X towards +Z.
    Points: bottom pole (if V starts at 0), top pole (if V ends at 180), then one column per U step, each with its
    rings from bottom to top; a full U turn does not repeat the first column. Polygons per column pair: the
    bottom triangle, the quads, the top triangle."""
    r = p.get("radius", 4.0)
    u, v = p.get("subdivu", 8), p.get("subdivv", 8)
    su, eu = p.get("startuangle", 0.0), p.get("enduangle", 360.0)
    sv, ev = p.get("startvangle", 0.0), p.get("endvangle", 180.0)
    full_u = abs((eu - su) - 360.0) < 1e-9
    bottom, top = sv == 0.0, ev == 180.0
    rings = [math.radians(sv + (ev - sv) * k / v) for k in range(v + 1)]
    rings = rings[1 if bottom else 0:v if top else v + 1]
    ncols = u if full_u else u + 1
    pts, poles = [], {}
    if bottom:
        poles["b"] = len(pts)
        pts.append((0.0, -r, 0.0))
    if top:
        poles["t"] = len(pts)
        pts.append((0.0, r, 0.0))
    cols = []
    for c in range(ncols):
        a = math.radians(su + (eu - su) * c / u)
        col = []
        for t in rings:
            rho = r * math.sin(t)
            col.append(len(pts))
            pts.append((-rho * math.cos(a), -r * math.cos(t), rho * math.sin(a)))
        cols.append(col)
    polys = []
    for c in range(u):
        a, b = cols[c], cols[(c + 1) % ncols]
        if bottom:
            polys.append([b[0], a[0], poles["b"]])
        for j in range(len(rings) - 1):
            polys.append([a[j], b[j], b[j + 1], a[j + 1]])
        if top:
            polys.append([a[-1], b[-1], poles["t"]])
    return pts, polys


def with_moves(gen, moves):
    """The live primitive with its point moves applied: (points, polygons), or None when the primitive or a
    move (edge / polygon components) is not supported."""
    mesh = primitive_mesh(gen)
    if mesh is None or moves is None:
        return None
    pts = movecomponent.apply_moves(mesh[0], moves)
    return None if pts is None else (pts, mesh[1])
