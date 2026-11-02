# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Alex Doss
"""Materials of a Softimage .scn: material libraries, materials, shader nodes and their values / connections.

Reverse engineered from scenes we generated (corpus cases mat_*) and checked against Softimage's own answers
(tools/sicapture/softimage/dump_materials_truth.py). See docs/research/scn-format.md, "Materials".

* `TLShell/Sources` (+ `Sources_GUIDS`) holds the libraries, materials and shaders, with the object-stream encoding.
* A shader object starts with an `MFDS1010` chunk (its ProgID), then a parameter block. Shader parameter records:
  lead with low bits 01, `<id u16> <index u16> [GUID on the index's first use in the stream] <flag byte>
  [<vartype u16> <value> if lead & 04] [<u16> if lead & 08]`; 0x40 opens a group (colour, vector) whose children
  follow until one without the 0x80 sibling bit. Indices are numbered per stream in first-use order; the GUIDs are
  named in `TLShell/Shader Definitions` (one `POT 1010` definition per parameter).
* After an object's records: `01 01` and a block holding a table `<count u16>` x `(3, 1, <definition id>, <flags>)`;
  entries with flags 7 are connected inputs. Then one sized block per connected input, in table order, ending in
  a reference `06 b0 ff ff ff ff <handle cnum> <class u16>` to the source object (shader or image clip).
* Material ports (surface, shadow, ...) are the material's value-less parameters; their definition GUIDs are in
  `PORTS` below.
"""
import re
import struct
import uuid
from collections import namedtuple

from . import records

P_NAME = "2b91c031-677a-11d1-b0cf-00a024c79287"
CLS_MATERIAL = "4c4f7500-51ef-11d0-854e-00a02417d029"
CLS_LIBRARY = "61782e14-9177-412e-bf9b-2b44b9a668dd"
CLS_COMPOUND = "b42f2cc7-4fa7-44b7-96d7-026e634988a0"   # render tree compound: exposed parameters, inner nodes
COMPOUND = "XSIRTCOMPOUND"                              # Softimage's ProgID for compounds
SHADER_CHUNK = b"MFDS1010"   # "SDFM" byte-reversed
# Material port definitions, in Softimage's parameter order.
PORTS = {
    "d7f221a0-58f4-11d0-8552-00a02417d029": "surface",
    "d7f221a1-58f4-11d0-8552-00a02417d029": "volume",
    "d7f221a2-58f4-11d0-8552-00a02417d029": "environment",
    "d7f221a3-58f4-11d0-8552-00a02417d029": "contour",
    "d7f221a4-58f4-11d0-8552-00a02417d029": "displacement",
    "d7f221a5-58f4-11d0-8552-00a02417d029": "shadow",
    "d7f221a6-58f4-11d0-8552-00a02417d029": "photon",
    "d7f221a7-58f4-11d0-8552-00a02417d029": "photonvolume",
    "d7f23496-58f4-11d0-8552-00a02417d029": "normal",
    "1cc97a93-a4d7-4852-97c5-f080a53689ef": "lightmap",
    "ec4ebe1b-704b-4a0a-a056-2915cfbeaf13": "realtime",
    "86289318-962c-433b-9c3d-befad4bfe806": "material",
}
_REF = re.compile(rb"\x06\xb0\xff\xff\xff\xff", re.S)
_POT = re.compile(rb"POT 1010", re.S)

Link = namedtuple("Link", "shader port")                        # a connected parameter
ClusterMaterial = namedtuple("ClusterMaterial", "name polygons material")


class Shader:
    def __init__(self, handle, progid):
        self.handle = handle
        self.progid = progid
        self.name = None
        self.params = {}          # script name -> value | dict (compound) | Link
        self.clip = None          # image shaders: the ImageClip connected to `tex`
        self.instance = {}        # per-object string parameters: {name: [value per owner]}

    def __repr__(self):
        return "<Shader %s %s>" % (self.name, self.progid)


class Material:
    def __init__(self, handle, name, library):
        self.handle = handle
        self.name = name
        self.library = library
        self.ports = {}           # port script name -> Shader

    @property
    def key(self):
        return "%s.%s" % (self.library, self.name)

    def __repr__(self):
        return "<Material %s>" % self.key


def definition_names(data):
    """GUID -> script name of every parameter definition in `TLShell/Shader Definitions`."""
    out = {}
    for m in _POT.finditer(data):
        p = m.start()
        try:
            g = str(uuid.UUID(bytes_le=data[p + 12:p + 28]))
            n = struct.unpack_from("<I", data, p + 36)[0]
            if 0 < n < 200 and g not in out:
                out[g] = data[p + 40:p + 40 + 2 * n].decode("utf-16-le")
        except (struct.error, UnicodeDecodeError, ValueError):
            continue
    return out


class _Ctx:
    def __init__(self, data, guids, names):
        self.d = data
        self.guids = guids
        self.names = names
        self.index = {}           # shader parameter index -> definition GUID (first-use order)
        self.trace = None         # debugging: list of (name, lead, flag, vartype, value) when set


_SIGNED = {0xA: 0, 0xB: 1, 0x9: 2, 0x8: 3}   # negative compact ints: tag -> extra bytes (cf. F, E, D, C)
_INTS = (records.VT_I2, records.VT_I4, records.VT_I1, records.VT_INT)


def _value(d, p, vt):
    """records.value, plus negative compact integers (`af` = -1): tags A / B / 9 / 8 mirror F / E / D / C and
    hold the value in two's complement of their width (4, 12, 20, 28 bits)."""
    if (vt & 0x0FFF) in _INTS and (d[p] >> 4) in _SIGNED:
        n = _SIGNED[d[p] >> 4]
        v = d[p] & 0xF
        for i in range(n):
            v |= d[p + 1 + i] << (4 + 8 * i)
        return v - (1 << (4 + 8 * n)), p + 1 + n
    if (vt & 0x0FFF) == records.VT_UNKNOWN and not records.TAG.match(d, p + 16):
        # embedded COM object (e.g. a curve): CLSID, then one sized block `<marker> <u32 size>`
        q = p + 16
        return ("com", str(uuid.UUID(bytes_le=d[p:q]))), q + 5 + struct.unpack_from("<I", d, q + 1)[0]
    return records.value(d, p, vt)


def _read_list(ctx, q, end):
    """Records until one without the 0x80 sibling bit. Returns ({name: value}, generic {id: value}, position)."""
    d = ctx.d
    out, generic = {}, {}
    while q < end:
        L = d[q]
        if L & 0x03 == 0x01:                      # shader parameter
            idx = struct.unpack_from("<H", d, q + 3)[0]
            q += 5
            if idx not in ctx.index:
                ctx.index[idx] = str(uuid.UUID(bytes_le=d[q:q + 16]))
                q += 16
            flag = d[q]
            q += 1
            value = vt = None
            if L & 0x04:
                vt = struct.unpack_from("<H", d, q)[0]
                value, q = _value(d, q + 2, vt)
            if L & 0x08:
                q += 2
            name = ctx.names.get(ctx.index[idx], "#%d" % idx)
            if ctx.trace is not None:
                ctx.trace.append((name, L, flag, vt, value))
        else:
            r, q = records.read_record(d, q)
            if L & 0x0C == 0x0C:                  # vartype + value, then one more u16 (as in shader records)
                q += 2
            value = r.value
            name = None
            if r.id is not None and r.vt is not None and L & 0x04:
                generic.setdefault(ctx.guids.get(r.id), value)
        if L & 0x40:
            value, sub, q = _read_list(ctx, q, end)
            generic.update((k, v) for k, v in sub.items() if k not in generic)
        if name is not None:
            out[name] = value
        elif isinstance(value, dict):              # an unnamed group (the block's own wrapper): its children
            out.update(value)
        if not L & 0x80:
            break
    return out, generic, q


def _name(d, p, end, guids):
    """The Name record (`84 <id> 1f 00 <cnum n> <UTF-16>`) in a record list, by its definition GUID."""
    ids = {i for i, g in guids.items() if g == P_NAME}
    while p < end - 6:
        if d[p] in (0x84, 0x04, 0x8c, 0x0c) and struct.unpack_from("<H", d, p + 1)[0] in ids and d[p + 3:p + 5] == b"\x1f\x00":
            n, q = records.cnum(d, p + 5)
            return d[q:q + 2 * n].decode("utf-16-le", "replace")
        p += 1
    return None


_INSTANCE = re.compile(rb"\x01(..)\x1f\x00", re.S)
# Parameters that name a per-object property (texture projection, vertex colour, weight map). Their records hold
# an integer 0 and their definitions look like integer ones, so they are known by name (or (ProgID, name)).
INSTANCE_STRINGS = {"tspace_id", "anisotropy_uvChannel", "anisotropy_tangentChannel", "anisotropy_channel",
                    "vprop", "map",
                    ("Softimage.sib_vertex_color_alpha.1.0", "alpha")}


def _instance_strings(d, lo, hi, guids, names):
    """Instance-data strings of a shader: records `01 <id u16> 1f 00 <cnum n> <UTF-16>` between its ProgID and
    its parameter block; the id names the parameter definition. Returns {name: [value per owner]}."""
    out = {}
    for m in _INSTANCE.finditer(d, lo, hi):
        name = names.get(guids.get(struct.unpack_from("<H", m.group(1))[0]))
        if name is None:
            continue
        try:
            n, q = records.cnum(d, m.end())
        except (records.Lost, IndexError):
            continue
        if q + 2 * n <= hi:
            out.setdefault(name, []).append(d[q:q + 2 * n].decode("utf-16-le", "replace"))
    return out


def _param_block(d, p, end):
    """Position of the first sized block (marker + u32) at or after p whose payload starts with 0x48."""
    while p + 6 <= end:
        size = struct.unpack_from("<I", d, p + 1)[0]
        if d[p + 5] == 0x48 and p + 5 + size <= end:
            return p, size
        if p + 5 + size > end:
            return None, 0
        p += 5 + size
    return None, 0


def _connections(ctx, q, end):
    """After a record list: `01 01` + table block + connection blocks. Returns [(definition GUID, handle)]."""
    d = ctx.d
    if q + 2 > end or d[q] != 0x01 or d[q + 1] != 0x01:
        return []
    q += 2
    size = struct.unpack_from("<I", d, q + 1)[0]
    lo, hi = q + 5, min(q + 5 + size, end)
    n = struct.unpack_from("<H", d, lo)[0]
    entries = [struct.unpack_from("<HHHH", d, lo + 2 + 8 * i) for i in range(n)]
    wanted = [ctx.guids.get(e[2]) for e in entries if e[3] == 7]
    out = []
    p = lo + 2 + 8 * n
    for g in wanted:
        if p + 5 > hi:
            break
        bsize = struct.unpack_from("<I", d, p + 1)[0]
        m = _REF.search(d, p + 5, p + 5 + bsize)
        if m:
            h, _ = records.cnum(d, m.end())
            out.append((g, h))
        p += 5 + bsize
    return out


def read(cf):
    """Materials of an open .scn (cfb.CompoundFile): {"<Library>.<Name>": Material}, plus {handle: Shader}."""
    if not cf.exists("TLShell/Sources"):
        return {}, {}
    d = cf.read("TLShell/Sources")
    guids = records.guid_table(cf.read("TLShell/Sources_GUIDS")) if cf.exists("TLShell/Sources_GUIDS") else {}
    names = definition_names(cf.read("TLShell/Shader Definitions")) if cf.exists("TLShell/Shader Definitions") else {}
    ctx = _Ctx(d, guids, names)
    warnings = []
    if not names:
        warnings.append("materials: this scene has no shader definitions (saved by an old Softimage version); "
                        "shaders are not identified")
    markers = records.detect_markers(d)
    om = markers["object"]
    objs = records._scan_objects(d, 12, len(d), None, [], om, records._obj_re(om))
    objs.sort(key=lambda o: o.start)          # shader parameter indices are numbered in stream order
    shaders, mats, by_handle = {}, [], {}
    lib_of = {}                               # material handle -> library name (a library lists its materials)
    for o in objs:
        by_handle[o.handle] = o
        kind = guids.get(o.pbase)
        p = o.body
        progid = None
        if d[p:p + 8] == SHADER_CHUNK:
            n = struct.unpack_from("<I", d, p + 13)[0]
            progid = d[p + 17:p + 17 + 2 * n].decode("utf-16-le", "replace")
            p += 17 + 2 * n
        elif kind == CLS_COMPOUND:
            progid = COMPOUND
        elif kind not in (CLS_LIBRARY, CLS_MATERIAL):
            continue                              # image clips, sources, ...: not needed here
        start, size = _param_block(d, p, o.end)
        if start is None:
            continue
        if kind == CLS_LIBRARY:
            # name, then references to its materials (its other records hold COM data we don't need)
            name = _name(d, start + 5, start + 5 + size, guids)
            for m in _REF.finditer(d, start, o.end):
                lib_of.setdefault(records.cnum(d, m.end())[0], name)
            continue
        try:
            params, generic, q = _read_list(ctx, start + 5, start + 5 + size)
        except (records.Lost, IndexError, struct.error) as e:
            if progid == COMPOUND:                # keep the compound itself: it is reported as not converted
                s = Shader(o.handle, progid)
                s.name = _name(d, start + 5, start + 5 + size, guids)
                s._conns = []
                shaders[o.handle] = s
            else:
                warnings.append("%s object %d not decoded (%s)" % (progid or "material", o.handle, e))
            continue
        name = generic.get(P_NAME)
        conns = _connections(ctx, q, start + 5 + size)
        if kind == CLS_MATERIAL:
            m = Material(o.handle, name, None)
            m._conns = conns
            mats.append(m)
        elif progid is not None:
            s = Shader(o.handle, progid)
            s.name = name
            s.params = {k: v for k, v in params.items() if not k.startswith("#")}
            # String parameters that are per-object instance data (tspace_id, ...) are 0 in the records; their
            # values sit in a block before the parameter block, one entry per owner. Softimage shows the first.
            s.instance = _instance_strings(d, p, start, guids, names)
            for k in s.params:
                if k in INSTANCE_STRINGS or (progid, k) in INSTANCE_STRINGS:
                    s.params[k] = ""                  # no owner entry: Softimage shows an empty name
            for k, vals in s.instance.items():
                if k in s.params:
                    s.params[k] = vals[0]
            s._conns = conns
            shaders[o.handle] = s
    for s in shaders.values():
        for g, h in s._conns:
            pname = names.get(g)
            src = shaders.get(h)
            if pname is None:
                continue
            if src is not None:
                s.params[pname] = Link(src, None)
            elif pname == "tex":
                s.clip = h
        del s._conns
    out = {}
    for m in mats:
        m.library = lib_of.get(m.handle)
        for g, h in m._conns:
            port = PORTS.get(g)
            if port and h in shaders:
                m.ports[port] = shaders[h]
        del m._conns
        out.setdefault(m.key, m)
    read.warnings = warnings
    return out, shaders


# ---------------------------------------------------------------- assignment ----------------------------
CLS_PROXY = "a0d4a4e1-7b7a-445b-a871-c55a9988dfdc"     # MaterialProxy: the material's path as text
CLS_CLUSTER = "600e50f1"                               # cluster (prefix of its class GUID)
CLS_ELEMENTS = "16681c01"                              # a cluster's element list
CLS_GROUP = "9d0673c2"                                 # group: refers to its members' bodies
_PATH = re.compile(rb"S\x00o\x00u\x00r\x00c\x00e\x00s\x00\.\x00M\x00a\x00t\x00e\x00r\x00i\x00a\x00l\x00s\x00\.\x00"
                   rb"(?:[\x20-\x7e]\x00)+", re.S)


def proxy_key(st, o):
    """'<Library>.<Material>' named by a MaterialProxy object, or None."""
    m = _PATH.search(st.data, o.start, o.end)
    if m is None:
        return None
    parts = m.group(0).decode("utf-16-le").split(".")
    return ".".join(parts[2:4]) if len(parts) >= 4 else None


def _own_proxy(st, o):
    for h, _c, _p in o.refs:
        ref = st.by_handle.get(h)
        if ref is not None and st.guid(ref.pbase) == CLS_PROXY:
            return proxy_key(st, ref)
    return None


def _xrefs(st, o):
    """Handles of cross-stream references in o: `<marker> <u32 size> 0e <kind cnum> <handle cnum> <class u16>`."""
    d, out = st.data, []
    om = st.markers["object"]
    p = o.body
    while True:
        p = d.find(bytes([om]), p, o.end)
        if p < 0 or p + 6 > o.end:
            return out
        if d[p + 5] == 0x0E:
            try:
                size = struct.unpack_from("<I", d, p + 1)[0]
                _k, q = records.cnum(d, p + 6)
                h, q = records.cnum(d, q)
                if q + 2 == p + 5 + size:
                    out.append(h)
            except (records.Lost, IndexError, struct.error):
                pass
        p += 1


def _counted(d, r, end):
    """`<cnum count> <count cnums>` at r ending exactly at end, or None."""
    try:
        count, q = records.cnum(d, r)
        if count == 0 or count > end - q:
            return None
        out = []
        for _ in range(count):
            v, q = records.cnum(d, q)
            out.append(v)
        return out if q == end else None
    except (records.Lost, IndexError):
        return None


def cluster_elements(st, o):
    """Element indices of a cluster: a sized block `<marker> <u32 n> 00 [header] <cnum count> <count cnums>`
    filling the block (header seen on large clusters, e.g. `e3 18 00 ff 00 ff f0`). Found in the cluster's
    element-list object (2015 scenes) or in the cluster object itself (older scenes)."""
    d = st.data
    p = o.body
    while p + 6 < o.end:
        n = struct.unpack_from("<I", d, p + 1)[0]
        if d[p + 5] == 0 and 2 <= n <= o.end - p - 5:
            end = p + 5 + n
            for r in range(p + 6, min(end, p + 6 + 16)):
                out = _counted(d, r, end)
                if out is not None:
                    return out
        p += 1
    return None


def _cluster_materials(st, polymsh):
    """Polygon clusters with a material of their own: polymsh -> cluster container -> cluster -> proxy."""
    out = []
    seen = set()

    def visit(o, depth):
        for h, _c, _p in o.refs:
            ref = st.by_handle.get(h)
            if ref is None or h in seen:
                continue
            seen.add(h)
            g = st.guid(ref.pbase) or ""
            if g.startswith(CLS_CLUSTER):
                key = _own_proxy(st, ref)
                if key:
                    elems = None
                    for h2, _c2, _p2 in ref.refs:
                        e = st.by_handle.get(h2)
                        if e is not None and (st.guid(e.pbase) or "").startswith(CLS_ELEMENTS):
                            elems = cluster_elements(st, e)
                    if elems is None:
                        elems = cluster_elements(st, ref)
                    name = next((v for v in ref.params.values() if isinstance(v, str)), "?")
                    out.append(ClusterMaterial(name, elems or [], key))
            elif depth < 1:
                visit(ref, depth + 1)
    visit(polymsh, 0)
    return out


def attach(sc):
    """Fill sc.materials / sc.shaders and every object's `material` (own, inherited, or the scene default) and
    `cluster_materials`."""
    sc.materials, sc.shaders = read(sc.cfb)
    sc.warnings.extend(read.warnings)
    # A model's own material (Scene_Root's is the scene default) is the proxy no object in its stream refers to;
    # the model's objects inherit it.
    root_key = None
    node, branch = {}, {}
    for storage, st in sc.models.items():
        referenced = {h for o in st.objects for h, _c, _p in o.refs}
        key = next((proxy_key(st, o) for o in st.objects
                    if o.handle not in referenced and st.guid(o.pbase) == CLS_PROXY), None)
        model = sc._models_by_storage.get(storage)
        if model is not None:
            branch[id(model)] = key
        elif "/Scene.Models/" not in storage:
            root_key = key
    for so in sc.objects:
        so.material, so.cluster_materials, so.uvs = None, [], []
        body = getattr(so, "body", None)
        if body is None or so.kind == "model":
            continue
        st, b = body
        node[id(so)] = _own_proxy(st, b)              # applied to the object only (node mode): on its body
        x3d = st.by_handle.get(so.handle) if so.handle is not None else None
        if x3d is not None:
            branch[id(so)] = _own_proxy(st, x3d)      # applied in branch mode: on the object, children inherit
        if so.kind == "polymsh" and so.primitive is not None:
            so.cluster_materials = _cluster_materials(st, so.primitive)
            if so.mesh is not None:
                from . import uvs
                so.uvs = uvs.read(st, so.primitive, so.mesh)
    # A group's material overrides its members' own materials; the group lists its members' bodies.
    # Members in another model's stream are cross-stream references (tag 0e); handles are unique in the scene.
    group = {}
    for st in sc.models.values():
        for o in st.objects:
            if not (st.guid(o.pbase) or "").startswith(CLS_GROUP):
                continue
            key = _own_proxy(st, o)
            if key:
                for h in [h for h, _c, _p in o.refs] + _xrefs(st, o):
                    group.setdefault(h, key)
    for so in sc.objects:
        body = getattr(so, "body", None)
        key = group.get(body[1].handle) if body is not None else None
        key = key or node.get(id(so)) or branch.get(id(so))
        cur = so.parent
        while key is None and cur is not None:
            key = branch.get(id(cur))
            cur = cur.parent
        so.material = key or root_key or "DefaultLib.Scene_Material"


# ---------------------------------------------------------------- image clips ---------------------------
CLS_CLIP = "22c3e8f8-ccea-11d2-b35b-00105a1e70de"      # ImageClip (chunk PLCI3010): name, refers to its source
CLS_IMAGE_SOURCE = "bb74aa1e"                          # image source: the file path, as stored and as resolved
_STR = re.compile(rb"\x1f\x00", re.S)


def _strings(d, lo, hi):
    """String values (`1f 00 <cnum n> <n UTF-16 chars>`) in [lo, hi), in order."""
    out = []
    for m in _STR.finditer(d, lo, hi):
        try:
            n, q = records.cnum(d, m.end())
        except (records.Lost, IndexError):
            continue
        if 0 < n < 1024 and q + 2 * n <= hi:
            try:
                s = d[q:q + 2 * n].decode("utf-16-le")
            except UnicodeDecodeError:
                continue
            if s.isprintable():
                out.append(s)
    return out


_RUN = re.compile(rb"(?:[\x20-\x7e]\x00){4,}", re.S)


def _u32_strings(d, lo, hi):
    """UTF-16 strings with a u32 length in front (how image sources store their paths), in order."""
    out = []
    for m in _RUN.finditer(d, lo + 4, hi):
        n = struct.unpack_from("<I", d, m.start() - 4)[0]
        if 0 < n <= (m.end() - m.start()) // 2:
            out.append(d[m.start():m.start() + 2 * n].decode("utf-16-le"))
    return out


def clip_paths(cf, handle):
    """File paths of the image clip `handle` (TLShell/Sources): (clip name, [paths: as stored first, then as
    resolved by Softimage when it saved]). (None, []) when not found."""
    d = cf.read("TLShell/Sources")
    guids = records.guid_table(cf.read("TLShell/Sources_GUIDS")) if cf.exists("TLShell/Sources_GUIDS") else {}
    om = records.detect_markers(d)["object"]
    objs = {o.handle: o for o in records._scan_objects(d, 12, len(d), None, [], om, records._obj_re(om))}
    clip = objs.get(handle)
    if clip is None:
        return None, []
    name = next(iter(_strings(d, clip.body, clip.end)), None)
    paths = []
    for m in _REF.finditer(d, clip.body, clip.end):
        src = objs.get(records.cnum(d, m.end())[0])
        if src is None or not (guids.get(src.pbase) or "").startswith(CLS_IMAGE_SOURCE):
            continue
        for s in _strings(d, src.body, src.end) + _u32_strings(d, src.body, src.end):
            if ("\\" in s or "/" in s) and "." in s and s not in paths:
                paths.append(s)
    return name, paths
