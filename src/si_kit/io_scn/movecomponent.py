# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Alex Doss
"""Move Component operators (Translate / Rotate / Scale on components of an unfrozen mesh).

Each operator object refers to the polymsh, a cluster (named Point_INTERNAL, Edge_INTERNAL or Polygon_INTERNAL:
the move keeps the component type it was made on) and two StaticKineStates: `Static_KineState` (reference) and
`Static_KineState1` (the move). See docs/research/scn-format.md, "Move Component".
"""
import math
import struct

from .records import Lost, cnum

MOVE_OP = "389e27dd-5fb0-11d2-b11c-00a0c906811e"
CLUSTERS = {"e4dd8e40-1e1c-11d0-aa2e-00a0243e34c4",    # point cluster
            "600e50f0-52fc-11d2-a924-00a024190119",    # edge cluster
            "600e50f1-52fc-11d2-a924-00a024190119"}    # polygon cluster
ELEMENTS = "16681c01-c066-11d2-a95b-00a024190119"
KINE_STATE = "12f18b50-d380-11d0-9225-08003629ea02"
P_NAME = "2b91c031-677a-11d1-b0cf-00a024c79287"
COMPONENT = {"Point_INTERNAL": "pnt", "Edge_INTERNAL": "edge", "Polygon_INTERNAL": "poly"}


class Move:
    __slots__ = ("component", "elements", "ref", "move")

    def __init__(self, component, elements, ref, move):
        self.component = component    # 'pnt', 'edge' or 'poly'
        self.elements = elements      # component indices, in Softimage's numbering
        self.ref = ref                # (scale, rotation radians XYZ, translation) of the reference state
        self.move = move              # (scale, rotation, translation) of the moved state

    def __repr__(self):
        return "<Move %s %s %s>" % (self.component, self.elements, self.move)


def _name(st, o):
    for k, v in o.params.items():
        if st.guid(k) == P_NAME:
            return v
    return None


def _srt(d, o):
    """FSRT1010 <u32 size> <u16 1> <3d scale> <byte> <3d translation> ATOR <u32> <u32> <byte> <3d rotation>."""
    p = d.find(b"FSRT1010", o.start, o.end)
    a = d.find(b"ATOR", p, o.end) if p >= 0 else -1
    if p < 0 or a < 0:
        return None
    scl = struct.unpack_from("<3d", d, p + 14)
    pos = struct.unpack_from("<3d", d, p + 39)
    rot = struct.unpack_from("<3d", d, a + 13)
    return scl, rot, pos


def _elements(d, o):
    """... 0c 00 01 <tag> <u32 n> 00 <cnum count> <count cnums> in the object the cluster refers to. The tag
    byte is numbered per stream (11 in 2015 scenes, 0f in older ones)."""
    p = d.find(b"\x0c\x00\x01", o.start, o.end)
    while p >= 0:
        p += 2                                   # at 01 <tag>
        try:
            n = struct.unpack_from("<I", d, p + 2)[0]
            q = p + 6
            if 0 < n < o.end - q + 1 and d[q] == 0:
                count, q = cnum(d, q + 1)
                out = []
                for _ in range(count):
                    v, q = cnum(d, q)
                    out.append(v)
                if q == p + 6 + n:
                    return out
        except (Lost, IndexError, struct.error):
            pass
        p = d.find(b"\x0c\x00\x01", p + 1, o.end)
    return None


def read_moves(st, polymsh):
    """The polymsh's Move Component operators, bottom of the stack first (by object handle, which follows
    creation order). Returns [Move], or None if one could not be decoded."""
    d = st.data
    ops = [st.by_handle[h] for h, _c, _p in polymsh.refs
           if h in st.by_handle and st.guid(st.by_handle[h].pbase) == MOVE_OP]
    out = []
    for op in sorted(ops, key=lambda o: o.handle):
        comp = elements = None
        states = {}
        for h, _c, _p in op.refs:
            r = st.by_handle.get(h)
            if r is None:
                continue
            g = st.guid(r.pbase)
            if g in CLUSTERS:
                comp = COMPONENT.get((_name(st, r) or "").rstrip("0123456789"))
                for h2, _c2, _p2 in r.refs:
                    e = st.by_handle.get(h2)
                    if e is not None and st.guid(e.pbase) == ELEMENTS:
                        elements = _elements(d, e)
            elif g == KINE_STATE:
                states[_name(st, r)] = _srt(d, r)
        ref, move = states.get("Static_KineState"), states.get("Static_KineState1")
        if comp is None or elements is None or ref is None or move is None:
            return None
        out.append(Move(comp, elements, ref, move))
    return out


# ------------------------------------------------------------------ applying --------------------------------
def _matrix(scl, rot, pos):
    """4x4 row-major: translation x rotation (XYZ order: X first) x scale."""
    cx, cy, cz = (math.cos(a) for a in rot)
    sx, sy, sz = (math.sin(a) for a in rot)
    # R = Rz * Ry * Rx
    r = [[cy * cz, sx * sy * cz - cx * sz, cx * sy * cz + sx * sz],
         [cy * sz, sx * sy * sz + cx * cz, cx * sy * sz - sx * cz],
         [-sy, sx * cy, cx * cy]]
    return [[r[i][0] * scl[0], r[i][1] * scl[1], r[i][2] * scl[2], pos[i]] for i in range(3)] + [[0, 0, 0, 1]]


def _inverse(m):
    """Inverse of an affine 4x4 (3x3 part invertible)."""
    a = [row[:3] for row in m[:3]]
    det = (a[0][0] * (a[1][1] * a[2][2] - a[1][2] * a[2][1]) - a[0][1] * (a[1][0] * a[2][2] - a[1][2] * a[2][0])
           + a[0][2] * (a[1][0] * a[2][1] - a[1][1] * a[2][0]))
    inv = [[(a[(j + 1) % 3][(i + 1) % 3] * a[(j + 2) % 3][(i + 2) % 3]
             - a[(j + 1) % 3][(i + 2) % 3] * a[(j + 2) % 3][(i + 1) % 3]) / det for j in range(3)] for i in range(3)]
    t = [-sum(inv[i][k] * m[k][3] for k in range(3)) for i in range(3)]
    return [inv[i] + [t[i]] for i in range(3)] + [[0, 0, 0, 1]]


def _mul(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(4)) for j in range(4)] for i in range(4)]


def apply_moves(points, moves):
    """Points (Softimage axes, Softimage point order) after point moves. Each move: p' = M1 M0^-1 p, with M0 the
    reference state and M1 the moved one (object space, about the object's origin). Returns new points, or None
    when a move is not on points."""
    pts = [list(p) for p in points]
    for mv in moves:
        if mv.component != "pnt":
            return None
        m = _mul(_matrix(*mv.move), _inverse(_matrix(*mv.ref)))
        for i in mv.elements:
            x, y, z = pts[i]
            pts[i] = [m[r][0] * x + m[r][1] * y + m[r][2] * z + m[r][3] for r in range(3)]
    return [tuple(p) for p in pts]
