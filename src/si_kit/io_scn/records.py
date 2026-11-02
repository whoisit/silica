# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Alex Doss
"""Low-level decoding of Softimage's object streams (TLShell/Objects/.../Objects).

Reverse engineered from scenes we generated ourselves (see docs/research/scn-format.md). The grammar is
only partly known, so the parser relies on reliable anchors and skips what it does not understand:

* every object is a sized block  03 <u32 size> 03 <handle:cnum> <class:u16> <pbase:u16> ...
* parameters are records  <lead> <id:u16> [<x>] [<vartype:u16> <value>]
* references to other objects are  03 <u32 size> 06 <kind:cnum> <handle:cnum> <class:u16>
  (kind is a per-session number, e.g. e4 2b in one Softimage session and e3 2e in another)
* a class definition "05 00 01 00 POT 1010 ..." (tags are stored byte-reversed) follows the first reference to a new class
* class and parameter ids index the stream's GUID table (TLShell/Objects/<model>/GUIDS)
"""
import re
import struct
import uuid

MAGIC = b"IGAM"


class Lost(Exception):
    """The decoder met bytes it does not understand."""


# ---------------------------------------------------------------- scalar encodings ---------------
def cnum(d, p):
    """Compact unsigned int. High nibble tags the width: F = 4 bits, E = 12, D = 20, C = 28."""
    b = d[p]
    n = {0xF: 0, 0xE: 1, 0xD: 2, 0xC: 3}.get(b >> 4)
    if n is None:
        raise Lost("compact int tag %02x at %d" % (b, p))
    v = b & 0xF
    for i in range(n):
        v |= d[p + 1 + i] << (4 + 8 * i)
    return v, p + 1 + n


def cdouble(d, p):
    """Compact double: FF=0, FE=1, FD=-1, FC=f64, FB=f32, FA=i32, F9=i16, F8=i8."""
    b = d[p]
    if b == 0xFF:
        return 0.0, p + 1
    if b == 0xFE:
        return 1.0, p + 1
    if b == 0xFD:
        return -1.0, p + 1
    if b == 0xFC:
        return struct.unpack_from("<d", d, p + 1)[0], p + 9
    if b == 0xFB:
        return struct.unpack_from("<f", d, p + 1)[0], p + 5
    if b == 0xFA:
        return float(struct.unpack_from("<i", d, p + 1)[0]), p + 5
    if b == 0xF9:
        return float(struct.unpack_from("<h", d, p + 1)[0]), p + 3
    if b == 0xF8:
        return float(struct.unpack_from("<b", d, p + 1)[0]), p + 2
    raise Lost("compact double tag %02x at %d" % (b, p))


VT_I2, VT_I4, VT_R4, VT_R8, VT_BSTR, VT_BOOL, VT_UNKNOWN = 0x02, 0x03, 0x04, 0x05, 0x08, 0x0B, 0x0D
VT_I1, VT_UI1, VT_UI2, VT_UI4, VT_INT, VT_UINT, VT_LPWSTR = 0x10, 0x11, 0x12, 0x13, 0x16, 0x17, 0x1F
TAG = re.compile(rb"[\x20-\xff]{4}[0-9]{4}", re.S)


def value(d, p, vt):
    base = vt & 0x0FFF
    if base == VT_BOOL:
        return bool(d[p]), p + 1
    if base == VT_R8:
        return cdouble(d, p)
    if base == VT_R4:
        return struct.unpack_from("<f", d, p)[0], p + 4
    if base in (VT_I2, VT_I4, VT_I1, VT_UI1, VT_UI2, VT_UI4, VT_INT, VT_UINT):
        return cnum(d, p)
    if base in (VT_LPWSTR, VT_BSTR):
        n, p = cnum(d, p)
        return d[p:p + 2 * n].decode("utf-16-le", "replace"), p + 2 * n
    if base == VT_UNKNOWN:  # embedded COM object: CLSID + persisted chunk + 06-sized block
        q = p + 16
        if not TAG.match(d, q):
            raise Lost("VT_UNKNOWN without chunk at %d" % p)
        q += 12 + struct.unpack_from("<I", d, q + 8)[0]
        if d[q] == 6:
            q += 5 + struct.unpack_from("<I", d, q + 1)[0]
        return ("com", str(uuid.UUID(bytes_le=d[p:p + 16]))), q
    raise Lost("vartype %04x at %d" % (vt, p))


# ---------------------------------------------------------------- parameter records --------------
class Param:
    __slots__ = ("id", "lead", "x", "vt", "value", "pos")

    def __repr__(self):
        return "Param(%#x, vt=%s, %r)" % (self.id if self.id is not None else -1, self.vt, self.value)


def read_record(d, p):
    """One parameter record. Lead byte bits: 0x80 another sibling follows, 0x40 group header,
    0x04 vartype + value, 0x08 vartype only, 0x30 one extra byte (two when anonymous),
    low bits 11 = anonymous (no id)."""
    r = Param()
    r.pos = p
    L = r.lead = d[p]
    q = p + 1
    r.id = r.x = r.vt = r.value = None
    if L & 0x03 != 0x03:
        r.id = struct.unpack_from("<H", d, q)[0]
        q += 2
    if L & 0x30:
        n = 2 if L & 0x03 == 0x03 else 1
        r.x = d[q:q + n]
        q += n
    if L & 0x0C:
        r.vt = struct.unpack_from("<H", d, q)[0]
        q += 2
    if L & 0x04:
        r.value, q = value(d, q, r.vt)
    return r, q


def read_params(d, p, end):
    """Records until the list terminator (01 00 00) or the first thing we cannot decode.
    Returns (params, stop_position, ok)."""
    out = []
    while p < end:
        if d[p] == 0x01:  # end of the record list ("01 00 00", or "01" + sized data blocks)
            return out, p, True
        try:
            r, q = read_record(d, p)
        except (Lost, IndexError, struct.error):
            q = _resync(d, p, end, out)
            if q is None:
                return out, p, False
            p = q
            continue
        out.append(r)
        p = q
    return out, p, True


def _resync(d, p, end, out):
    """Older scenes put a few bytes we don't understand between some records (e.g. `07 00` after a camera's
    ortho height). Parameter ids run in sequence, so skip ahead (at most 16 bytes) to a record whose id is the
    previous record's id + 1 and that decodes. Returns its position or None."""
    if not out or out[-1].id is None:
        return None
    want = out[-1].id + 1
    for s in range(p + 1, min(p + 17, end - 3)):
        if d[s] & 0x03 != 0x03 and d[s] & 0x0C and struct.unpack_from("<H", d, s + 1)[0] == want:
            try:
                read_record(d, s)
            except (Lost, IndexError, struct.error):
                continue
            return s
    return None


# ---------------------------------------------------------------- objects -------------------------
def _ref_re(om):
    """References: <om> <u32 size> 06 ..., om being the stream's object block marker (detect_markers)."""
    return re.compile(re.escape(bytes([om])) + rb"[\x05-\x0b]\x00\x00\x00\x06", re.S)  # validated by read_ref()


def _obj_re(om):
    """Candidate object headers <om> <u32 size> 03; validated by _object_at."""
    return re.compile(re.escape(bytes([om])) + rb".{4}\x03", re.S)


REF = _ref_re(3)
CLASSDEF = re.compile(rb"\x05\x00\x01\x00POT 1010", re.S)  # the "TOP " tag is stored byte-reversed


class Obj:
    """One serialized object. `params` maps definition id -> value (first occurrence wins);
    `plist` keeps the decoded records in order."""
    __slots__ = ("handle", "cls", "pbase", "start", "end", "body", "params", "plist", "refs", "children",
                 "parent", "complete", "preamble")

    def __repr__(self):
        return "<Obj h=%d cls=%#x pbase=%#x params=%d refs=%d>" % (
            self.handle, self.cls, self.pbase, len(self.plist), len(self.refs))


def _object_at(d, p, end, om=3):
    """Object header at p, or None. <om> <u32 size> 03 <handle cnum> <cls u16> <pbase u16>, where om is
    the stream's object block marker (03 in most streams, see detect_markers)."""
    if d[p] != om or p + 12 > end or d[p + 5] != 3:
        return None
    size = struct.unpack_from("<I", d, p + 1)[0]
    if size < 6 or p + 5 + size > end:
        return None
    try:
        h, q = cnum(d, p + 6)
    except (Lost, IndexError):
        return None
    if q + 4 > p + 5 + size:
        return None
    cls, pbase = struct.unpack_from("<HH", d, q)
    o = Obj()
    o.handle, o.cls, o.pbase = h, cls, pbase
    o.start, o.end, o.body = p, p + 5 + size, q + 4
    o.params, o.plist, o.refs, o.children, o.parent = {}, [], [], [], None
    o.complete, o.preamble = False, b""
    return o


OBJ_HDR = _obj_re(3)


def _scan_objects(d, lo, hi, parent, out, om=3, hdr=OBJ_HDR):
    p = lo
    while p < hi:
        m = hdr.search(d, p, hi)  # C-speed jump to the next candidate (scenes can be 200+ MB)
        if m is None:
            break
        p = m.start()
        o = _object_at(d, p, hi, om)
        if o is None:
            p += 1
            continue
        o.parent = parent
        if parent is not None:
            parent.children.append(o)
        out.append(o)
        _scan_objects(d, o.body, o.end, o, out, om, hdr)
        p = o.end
    return out


def _decode_object(d, o, ref_re=REF):
    # The parameter block is the first "01 <u32 size>" whose records start with a 0x48 group header.
    # Most objects put it right after the header; primitives (polymsh, ...) have a short preamble first.
    p = o.body
    lim = min(o.end, o.body + 64)
    while p < lim:
        if d[p] == 1 and p + 5 < o.end and d[p + 5] == 0x48:
            size = struct.unpack_from("<I", d, p + 1)[0]
            if p + 5 + size <= o.end:
                break
        p += 1
    else:
        return
    o.preamble = d[o.body:p]
    size = struct.unpack_from("<I", d, p + 1)[0]
    plist, stop, ok = read_params(d, p + 5, p + 5 + size)
    o.plist = plist
    o.complete = ok
    for r in plist:
        if r.id is not None and r.id not in o.params and r.vt is not None and r.lead & 0x04:
            o.params[r.id] = r.value
    # references that belong to this object (not to nested objects)
    # Scan only this object's own bytes (the gaps between nested objects): scanning the whole range
    # for every ancestor made large scenes quadratic.
    gaps, cur = [], o.body
    for c in o.children:
        gaps.append((cur, c.start))
        cur = c.end
    gaps.append((cur, o.end))
    for lo, hi in gaps:
        for m in ref_re.finditer(d, lo, hi):
            ref = read_ref(d, m.start())
            if ref:
                o.refs.append((ref[0], ref[1], m.start()))


def read_ref(d, p):
    """03 <u32 size> 06 <kind cnum> <handle cnum> <class u16>, with size matching the payload."""
    try:
        size = struct.unpack_from("<I", d, p + 1)[0]
        _kind, q = cnum(d, p + 6)
        h, q = cnum(d, q)
        cls = struct.unpack_from("<H", d, q)[0]
    except (Lost, IndexError, struct.error):
        return None
    if q + 2 != p + 5 + size:
        return None
    return h, cls


def read_classdefs(d, refs_by_pos):
    """class id -> (internal name, display name, description, clsid). The class id is taken from the
    reference right before the definition."""
    out = {}
    positions = sorted(refs_by_pos)
    import bisect
    for m in CLASSDEF.finditer(d):
        p = m.start() + 4  # the TOP chunk
        size = struct.unpack_from("<I", d, p + 8)[0]
        clsid = str(uuid.UUID(bytes_le=d[p + 12:p + 28]))
        q = p + 28 + 8
        names = []
        try:
            for _ in range(3):
                n = struct.unpack_from("<I", d, q)[0]
                names.append(d[q + 4:q + 4 + 2 * n].decode("utf-16-le"))
                q += 4 + 2 * n
        except (struct.error, UnicodeDecodeError):
            continue
        i = bisect.bisect_left(positions, m.start()) - 1
        if i >= 0 and m.start() - positions[i] <= 16:
            cls = refs_by_pos[positions[i]]
            out[cls] = (names[0], names[1], names[2], clsid)
    return out


_FIRST_LIST = re.compile(rb"([\x01-\x20]).{4}\xb0.{4}([\x01-\x20]).{4}\x03", re.S)


def detect_markers(d):
    """Block markers are not fixed: each stream numbers its block kinds in the order they first occur
    (00 root, 01 parameter block, then the others). Most 2015 streams give child list = 02 and
    object/reference = 03; streams whose root object writes another small block first (common in files
    saved by Softimage 2011-2014) shift them to 03 and 04. The first child list is recognisable:
    <list> <u32 size> b0 <u32 count> <obj> <u32 size> 03 <handle> <class> <pbase>."""
    for m in _FIRST_LIST.finditer(d, 12):
        p = m.start()
        lsize = struct.unpack_from("<I", d, p + 1)[0]
        osize = struct.unpack_from("<I", d, p + 11)[0]
        if p + 5 + lsize <= len(d) and 0 < osize < lsize and _object_at(d, p + 10, p + 5 + lsize, m.group(2)[0]):
            return {"list": m.group(1)[0], "object": m.group(2)[0]}
    return {"list": 2, "object": 3}


def guid_table(data):
    """TLShell/Objects/<model>/GUIDS: 'DIUG0010' <u32 size> then (u16 index, 16-byte GUID) entries."""
    if data[:4] != b"DIUG":
        return {}
    size = struct.unpack_from("<I", data, 8)[0]
    t = {}
    for o in range(12, 12 + size - 17, 18):
        t[struct.unpack_from("<H", data, o)[0]] = str(uuid.UUID(bytes_le=data[o + 2:o + 18]))
    return t


class ObjectStream:
    """Decoded TLShell/Objects/<model>/Objects stream."""

    def __init__(self, data, guids=None):
        if data[:4] != MAGIC:
            raise Lost("not an object stream")
        self.data = data
        self.guids = guids or {}
        # The stream's root block (00 <u32> 01 <u32> <records>) is the model that owns the stream
        # (Scene_Root, or a model in Scene.Models/InternalModelN); it has no object header.
        self.root_params = {}
        if len(data) > 22 and data[12] == 0 and data[17] == 1:
            size = struct.unpack_from("<I", data, 18)[0]
            plist, _stop, _ok = read_params(data, 22, min(len(data), 22 + size))
            for r in plist:
                if r.id is not None and r.id not in self.root_params and r.vt is not None and r.lead & 0x04:
                    self.root_params[r.id] = r.value
        self.markers = detect_markers(data)
        om = self.markers["object"]
        self.objects = _scan_objects(data, 12, len(data), None, [], om, _obj_re(om))
        ref_re = _ref_re(om)
        for o in self.objects:
            _decode_object(data, o, ref_re)
        self.by_handle = {o.handle: o for o in self.objects}
        refs_by_pos = {}
        for o in self.objects:
            for h, cls, pos in o.refs:
                refs_by_pos[pos] = cls
        self.classdefs = read_classdefs(data, refs_by_pos)
        # The header's "class" field is a per-instance index; the class itself is identified by pbase
        # (the definition id of the class's root parameter). Name each pbase from any instance whose
        # class definition we saw.
        self.kinds = {}
        for o in self.objects:
            c = self.classdefs.get(o.cls)
            if c and o.pbase not in self.kinds:
                self.kinds[o.pbase] = c[0]

    def guid(self, idx):
        return self.guids.get(idx)

    def kind(self, o):
        """Class name of an object ('null', 'polymsh', 'kine', '#3dobject', ...) or None."""
        return self.kinds.get(o.pbase)
