# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Alex Doss
"""Move Center operators (`center`, Softimage's Transform > Move Center / center manipulation).

Moving an object's center changes the object's own transform; the geometry gets a `center` operator holding the
inverse, so the points stay where they are in the world. The operator's parameter records sit in its own object
(after an `MRFD1010` chunk): scale (3 doubles), rotation in degrees (3), translation (3), applied to the points
below it as p' = T R S p (object space, the same order as Move Component). Decoded from corpus cases `ctr_*`
(translate, rotate, scale, translate + rotate, a frozen mesh scaled 0.01): docs/research/scn-format.md,
"Move Center".
"""
import math

from . import movecomponent, records

CENTER_OP = "08420bb0-f664-11d2-912f-00a0244eeb76"
_G = "-f664-11d2-912f-00a0244eeb76"
PARAMS = {"08420bb1" + _G: ("scl", 0), "08420bb2" + _G: ("scl", 1), "08420bb3" + _G: ("scl", 2),
          "08420bb4" + _G: ("rot", 0), "08420bb5" + _G: ("rot", 1), "08420bb6" + _G: ("rot", 2),
          "08420bb7" + _G: ("pos", 0), "08420bb8" + _G: ("pos", 1), "08420bb9" + _G: ("pos", 2)}


class Center:
    __slots__ = ("handle", "scl", "rot", "pos")

    def __init__(self, handle, scl, rot, pos):
        self.handle = handle          # object handle: creation order, to sequence with point moves
        self.scl, self.rot, self.pos = scl, rot, pos      # rot in radians, XYZ

    def __repr__(self):
        return "<Center scl %s rot %s pos %s>" % (self.scl, [math.degrees(a) for a in self.rot], self.pos)


def _params(st, o):
    d = st.data
    p = d.find(b"MRFD1010", o.start, o.end)
    if p < 0:
        return None
    for q in range(p + 8, o.end):
        if d[q] != 0x48:                          # the record group of the operator's parameters
            continue
        ps, _stop, ok = records.read_params(d, q, o.end)
        got = {}
        for r in ps:
            key = PARAMS.get(st.guid(r.id)) if r.id is not None else None
            if key is not None and isinstance(r.value, float):
                got[key] = r.value
        if ok and len(got) == len(PARAMS):
            return got
    return None


def read_centers(st, polymsh):
    """The polymsh's Move Center operators, by creation order. [] when there are none; None when one is there
    but could not be decoded."""
    ops = [st.by_handle[h] for h, _c, _p in polymsh.refs
           if h in st.by_handle and st.guid(st.by_handle[h].pbase) == CENTER_OP]
    out = []
    for op in sorted(ops, key=lambda o: o.handle):
        got = _params(st, op)
        if got is None:
            return None
        v = {k: [got[(k, i)] for i in range(3)] for k in ("scl", "rot", "pos")}
        out.append(Center(op.handle, tuple(v["scl"]), tuple(math.radians(a) for a in v["rot"]), tuple(v["pos"])))
    return out


def apply_center(points, c):
    """Points (Softimage axes and order) after one Move Center operator: p' = T R S p."""
    m = movecomponent._matrix(c.scl, c.rot, c.pos)
    return [tuple(m[r][0] * x + m[r][1] * y + m[r][2] * z + m[r][3] for r in range(3)) for x, y, z in points]
