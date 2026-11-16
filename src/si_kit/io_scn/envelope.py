# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Alex Doss
"""Envelopes (skinning): which objects deform a polygon mesh, each point's weights and each deformer's setup pose.

The envelope operator (class 470cf890) refers, in this order, to the polymsh, the mesh's kinematic state (twice),
the weight cluster (EnvelopWeightCls), the weight property (Envelope_Weights), the mesh's own static kine state, the
weight property again, then one pair per deformer: its static kine state (the setup pose, same FSRT / ATOR blocks
as Move Component) and its kinematic state (which tells which object it is). Weight edits painted on top are a
separate object (class 052f8860) that refers to the weight property. See docs/research/scn-format.md, "Envelopes".

Deformation (checked against Softimage on the six envelopes of a 2006 production scene): with M the mesh's global
matrix, S_i the deformer's setup pose and G_i its global now, a point p of the stored mesh goes to
M^-1 sum_i w_i G_i S_i^-1 M p. That is what Blender's Armature modifier computes with bones at rest S_i, posed G_i.
"""
import struct

from . import records
from .movecomponent import _srt
from .records import Lost, cnum

ENVELOPE_OP = "470cf890-d3aa-11d0-996c-00a0243f0e60"
WEIGHTS = "c0fbfe80-e7f4-11d0-996d-00a0243f0e60"        # Envelope_Weights cluster property
WEIGHT_EDITS = "052f8860-9d51-11d4-b918-0800690c8bd0"   # painted changes on top of the weights
KINE_STATE = "12f18b50-d380-11d0-9225-08003629ea02"     # static kine state (setup pose)
POINT_CLUSTER = "e4dd8e40-1e1c-11d0-aa2e-00a0243e34c4"
ROW_END = b"\xb0\xff\xff\xff\x7f"


class Envelope:
    __slots__ = ("deformers", "poses", "weights", "edited")

    def __init__(self, deformers, poses, weights, edited):
        self.deformers = deformers  # SceneObject per deformer (None when it could not be found)
        self.poses = poses          # setup pose per deformer: (scale, rotation radians XYZ, translation), Softimage axes
        self.weights = weights      # per deformer: {point index: weight in percent}, zeros left out
        self.edited = edited        # True when painted weight changes were applied

    def __repr__(self):
        return "<Envelope %d deformers%s>" % (len(self.deformers), ", edited" if self.edited else "")


def _count(b, p):
    """Compact unsigned int, plus the 32-bit form b0 <u32> the weight rows use for long runs."""
    if b[p] == 0xB0:
        return struct.unpack_from("<I", b, p + 1)[0], p + 5
    return cnum(b, p)


def _scount(b, p):
    """Compact signed int: F / E / D / C positive (4 / 12 / 20 / 28 bits), A / 9 / 8 / 7 negative."""
    neg = {0xA: 0, 0x9: 1, 0x8: 2, 0x7: 3}.get(b[p] >> 4)
    if neg is None:
        return cnum(b, p)
    v = b[p] & 0xF
    for i in range(neg):
        v |= b[p + 1 + i] << (4 + 8 * i)
    return v - (1 << (4 + 8 * neg)), p + 1 + neg


def _refs(st, o):
    """Every reference inside object o, in order (also those the generic decoder skips)."""
    d = st.data
    out = []
    for m in records._ref_re(st.markers["object"]).finditer(d, o.start + 12, o.end):
        r = records.read_ref(d, m.start())
        if r is not None:
            out.append(r[0])
    return out


def read_weights(b, n, ndef):
    """Weight rows in the Envelope_Weights object's bytes: header f0 22 <u32> <deformer count> ..., the point count,
    zero padding, then one row per deformer of runs <(zeros << 16) | values> + values as float32 (percent).
    Returns [[n floats] per deformer] or None."""
    q = b.find(b"\xf0\x22")
    if q < 0:
        return None
    try:
        _ndef, q = cnum(b, q + 6)
        while True:                      # per-deformer entries end in ff 01; the point count follows the last
            q = b.find(b"\xff\x01", q)
            if q < 0:
                return None
            q += 2
            try:
                v, p = cnum(b, q)
            except Lost:
                continue
            if v == n:
                break
        while p < len(b) and b[p] == 0:
            p += 1
        rows = []
        for _ in range(ndef):
            row = []
            while len(row) < n:
                v, p = _count(b, p)
                zeros, vals = v >> 16, v & 0xFFFF
                row.extend([0.0] * zeros)
                row.extend(struct.unpack_from("<%df" % vals, b, p))
                p += 4 * vals
            if len(row) != n:
                return None
            rows.append(row)
    except (Lost, IndexError, struct.error):
        return None
    return rows


def read_edits(b, n, ndef):
    """Painted changes (class 052f8860): <u32 size> <cnum 100> <cnum deformer count>, then per deformer runs of
    [<negative count> <start point>] or [<start point>] (one value) + float32 values, each row ended by
    b0 ff ff ff 7f. The changes are added to the weights. Returns [{point: change} per deformer] or None."""
    for q in range(len(b) - 6):
        size = struct.unpack_from("<I", b, q)[0]
        if not 0 < size <= len(b) - q - 4 or b[q + 4:q + 6] != b"\xe4\x06":
            continue
        try:
            _hundred, p = cnum(b, q + 4)
            nd, p = cnum(b, p)
            if nd != ndef:
                continue
            rows, row = [], {}
            while len(rows) < ndef:
                if b[p:p + 5] == ROW_END:
                    rows.append(row)
                    row = {}
                    p += 5
                    continue
                c, p = _scount(b, p)
                if c >= 0:
                    start, count = c, 1
                else:
                    start, p = cnum(b, p)
                    count = -c
                if start + count > n:
                    raise Lost("run past the last point")
                for i, v in enumerate(struct.unpack_from("<%df" % count, b, p)):
                    row[start + i] = v
                p += 4 * count
        except (Lost, IndexError, struct.error):
            continue
        if p == q + 4 + size:
            return rows
    return None


def read_envelopes(st, polymsh, npoints, owner_of):
    """Envelopes on a polymsh. owner_of maps a kinematic state handle to its SceneObject. Returns ([Envelope],
    [problem notes])."""
    out, notes = [], []
    by = st.by_handle
    for h, _c, _p in polymsh.refs:
        op = by.get(h)
        if op is None or st.guid(op.pbase) != ENVELOPE_OP:
            continue
        refs = _refs(st, op)
        wobj = next((by[r] for r in refs if r in by and st.guid(by[r].pbase) == WEIGHTS), None)
        pairs = []
        k = refs.index(wobj.handle) + 3 if wobj is not None and wobj.handle in refs else None
        if k is not None:
            tail = refs[k:]
            pairs = list(zip(tail[0::2], tail[1::2]))
        if wobj is None or not pairs or any(by.get(s) is None or st.guid(by[s].pbase) != KINE_STATE
                                            for s, _k in pairs):
            notes.append("envelope not decoded (unexpected operator layout)")
            continue
        ndef = len(pairs)
        rows = read_weights(st.data[wobj.start:wobj.end], npoints, ndef)
        if rows is None:
            notes.append("envelope weights not decoded")
            continue
        edited = False
        for o in st.objects:
            if st.guid(o.pbase) == WEIGHT_EDITS and wobj.handle in _refs(st, o):
                edits = read_edits(st.data[o.start:o.end], npoints, ndef)
                if edits is None:
                    notes.append("painted envelope weight changes not decoded (base weights used)")
                    continue
                for row, ch in zip(rows, edits):
                    for i, v in ch.items():
                        row[i] += v
                edited = True
        deformers, poses = [], []
        for s, kin in pairs:
            deformers.append(owner_of.get(kin))
            poses.append(_srt(st.data, by[s]))
        if any(d is None for d in deformers):
            notes.append("%d envelope deformer(s) not found" % sum(1 for d in deformers if d is None))
        weights = [{i: w for i, w in enumerate(row) if w != 0.0} for row in rows]
        out.append(Envelope(deformers, poses, weights, edited))
    return out, notes


def attach(sc):
    """Read the envelopes of every polygon mesh of scene sc into SceneObject.envelopes (and .envelope_notes)."""
    owners = {}
    for so in sc.objects:
        body = getattr(so, "body", None)
        if body is None:
            continue
        st, b = body
        m = owners.setdefault(id(st), {})
        for h, _c, _p in b.refs:
            k = st.by_handle.get(h)
            if k is not None:
                m[h] = so
                for h2, _c2, _p2 in k.refs:
                    m.setdefault(h2, so)
    for so in sc.objects:
        so.envelopes, so.envelope_notes = [], []
        if so.kind != "polymsh" or so.primitive is None or so.mesh is None or "envelopop" not in so.ops:
            continue
        st = so.body[0]
        so.envelopes, so.envelope_notes = read_envelopes(st, so.primitive, len(so.mesh.points), owners.get(id(st), {}))
