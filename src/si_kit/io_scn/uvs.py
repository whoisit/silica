# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Alex Doss
"""UV sets (texture projections) of frozen polygon meshes in a Softimage .scn.

Found from corpus cases mat_uv / mat_uv2 and checked against Softimage's per-corner UVs
(tools/sicapture/softimage/dump_materials_truth.py). See docs/research/scn-format.md, "UVs".

* The polymsh refers to its cluster container (class 60f7ada0), which refers to the sample cluster
  (`Texture_Coordinates_AUTO`, class 600e50f2) and to each texture projection property (class 6630d811), named
  like the UV set (`Texture_Projection`). In older files the sample cluster refers to the properties.
* In the property: the distinct UV values as raw f32 (u, v) pairs, `<marker> <u32 size> fc <pairs>`, and an index
  per polygon node, `<marker> <u32 size> <cnum nodes> <width u8> 00 fc <nodes x width bytes>` (`fa` in place of
  `fc` in some files, same layout). The number of pairs
  is the largest index + 1.
"""
import struct
from collections import namedtuple

from . import records

CLS_CONTAINER = "60f7ada0-7e12-11d0-9960-00a0243f0e60"
CLS_UVPROP = "6630d811-0699-11d1-b723-00aa0068bf56"
CLS_SAMPLES = "600e50f2-52fc-11d2-a924-00a024190119"   # sample cluster (Texture_Coordinates_AUTO)

UVSet = namedtuple("UVSet", "name corners")     # corners: (u, v) per polygon corner, in Mesh.polygons order


def _values(d, lo, hi):
    """Candidate UV value blocks in [lo, hi): sized blocks `<marker> <u32 size> <cnum count> <count x (u, v) f32>`
    with finite values. Yields (pairs, end of the pairs)."""
    p = lo
    while p + 6 < hi:
        try:
            size = struct.unpack_from("<I", d, p + 1)[0]
            if 0 < size <= hi - p - 5:
                count, q = records.cnum(d, p + 5)
                if count and q + 8 * count <= p + 5 + size:
                    flat = struct.unpack_from("<%df" % (2 * count), d, q)
                    if all(abs(x) < 1e6 for x in flat):   # also rejects NaN
                        yield [(flat[2 * i], flat[2 * i + 1]) for i in range(count)], q + 8 * count
        except (records.Lost, IndexError, struct.error):
            pass
        p += 1


def _indices(d, lo, hi, nnodes, count):
    """Node -> value index: `<marker> <u32 size> <cnum nodes> 01 00 <cnum count> <nodes entries>`, entries of 1, 2
    or 4 bytes as the value count needs."""
    p = lo
    while p + 6 < hi:
        try:
            size = struct.unpack_from("<I", d, p + 1)[0]
            end = p + 5 + size
            if end <= hi:
                n, q = records.cnum(d, p + 5)
                if n == nnodes and d[q + 1] == 0:
                    rng, r = records.cnum(d, q + 2)
                    w, fmt = (1, "B") if count <= 0x100 else (2, "H") if count <= 0x10000 else (4, "I")
                    if rng == count and r + n * w == end:
                        return list(struct.unpack_from("<%d%s" % (n, fmt), d, r))
        except (records.Lost, IndexError, struct.error):
            pass
        p += 1
    return None


def read(st, polymsh, mesh):
    """UV sets of a frozen mesh: [UVSet], in the order Softimage lists the projections."""
    nnodes = sum(len(p) for p in mesh.polygons)
    nodes = getattr(mesh, "nodes", None)
    if nodes is None:                            # nodes in polygon order (2015 scenes)
        nodes, n = [], 0
        for poly in mesh.polygons:
            nodes.append(list(range(n, n + len(poly))))
            n += len(poly)
    out = []
    for h, _c, _p in polymsh.refs:
        cont = st.by_handle.get(h)
        if cont is None or st.guid(cont.pbase) != CLS_CONTAINER:
            continue
        props, seen = [], set()
        for h2, _c2, _p2 in cont.refs:       # on the container (2015), or on the sample cluster (older files)
            ref = st.by_handle.get(h2)
            if ref is None:
                continue
            g = st.guid(ref.pbase)
            cands = [ref] if g == CLS_UVPROP else (
                [st.by_handle.get(h3) for h3, _c3, _p3 in ref.refs] if g == CLS_SAMPLES else [])
            for c in cands:
                if c is not None and st.guid(c.pbase) == CLS_UVPROP and c.handle not in seen:
                    seen.add(c.handle)
                    props.append(c)
        for prop in sorted(props, key=lambda o: o.handle):     # creation order, as Softimage lists them
            name = next((v for v in prop.params.values() if isinstance(v, str)), "UV")
            for vals, at in _values(st.data, prop.body, prop.end):
                idx = _indices(st.data, at, prop.end, nnodes, len(vals))
                if idx is None and len(vals) == nnodes:
                    idx = range(nnodes)               # one value per node, no index array (older files)
                if idx is not None and max(idx, default=0) < len(vals):
                    out.append(UVSet(name, [vals[idx[n]] for poly in nodes for n in poly]))
                    break
    return out
