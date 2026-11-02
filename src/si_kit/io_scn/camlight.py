# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Alex Doss
"""Camera and light settings (corpus cases cam_* and light_*; see docs/research/scn-format.md).

Cameras and lights keep their settings as ordinary parameters on their primitive. A light's colour and intensity
sit in its light shader, an object the light refers to (class 6495c5c1, the shader's ProgID in UTF-16 near its
start) whose values are stored as indexed records:  (85|05) 02 00 <u16 index> 01 <u16 type> <value>  with type 4 =
float32, 0x0b = bool (1 byte). Indices follow the shader's definition; only Softimage's own soft_light is mapped
here. Redshift / Arnold light shaders are named, not mapped.
"""
import re
import struct

CAMERA_PARAMS = {
    "41e88660-9a1c-11d0-a4c7-00aa00624c2d": "fov",           # degrees
    "20d78b60-9a4f-11d0-a4c7-00aa00624c2d": "fovtype",       # 0 vertical, 1 horizontal
    "130500f0-3664-11d0-850b-00a02417d029": "proj",          # 0 orthographic, 1 perspective
    "5adfe2f0-3998-11d1-84a5-00aa00135f7b": "orthoheight",
    "130500f4-3664-11d0-850b-00a02417d029": "near",
    "130500f5-3664-11d0-850b-00a02417d029": "far",
    "130500f3-3664-11d0-850b-00a02417d029": "aspect",
    "3e03e0f6-773b-11d3-a295-08003658d403": "pixelratio",
    "130500f2-3664-11d0-850b-00a02417d029": "planewidth",
    "658f6c10-cb80-11d2-8bcd-00aa006130ef": "std",
}
LIGHT_PARAMS = {
    "914f1f00-4257-11d0-8294-00a0243e366b": "Type",          # 0 point, 1 infinite, 2 spot
    "07c5edeb-52a4-11d0-8298-00a0243e366b": "LightCone",     # spot cone, degrees
    "4dce3d88-a0f3-409a-ab23-6110a78cddc1": "Near",
    "8d7af084-a19a-4a5f-b96b-a3b05b05e9e1": "Far",
}
SHADER = "6495c5c1-fd18-474e-9703-aea66631f7a7"
FCURVE = "e2a86051-f669-11d1-8d60-080036f3cc02"   # an animated parameter's function curve
# soft_light values by offset from the colour's alpha record. Record indices shift between Softimage versions
# (alpha is 8 in 2015 scenes, 5 in older ones), but alpha is the only record with lead byte 05 and the order
# around it is fixed: red green blue alpha intensity shadow factor atten start stop spread.
SOFT_LIGHT = {-3: "red", -2: "green", -1: "blue", 1: "intensity", 2: "shadow", 4: "atten", 5: "start", 6: "stop",
              7: "spread"}
_PROGID = re.compile(rb"((?:[\x20-\x7e]\x00){4,80})")


def _params(st, o, table):
    """Named parameter values; "animated": True when the primitive refers to function curves (then some values
    are only the static base under the animation; which ones is not decoded yet)."""
    out = {}
    for k, v in o.params.items():
        name = table.get(st.guid(k))
        if name is not None:
            out[name] = v
    if any(h in st.by_handle and st.guid(st.by_handle[h].pbase) == FCURVE for h, _c, _p in o.refs):
        out["animated"] = True
    return out


def read_camera(st, prim):
    return _params(st, prim, CAMERA_PARAMS)


def shader_progid(d, o):
    m = _PROGID.search(d, o.start, min(o.end, o.start + 160))
    return m.group(1).decode("utf-16-le") if m else None


def shader_records(d, o, leads=None):
    """{index: value} of a shader object's float / bool records. A record may carry a 16-byte GUID after the
    index (shaders that embed their definition, e.g. a scene's default light). `leads`, if given, collects
    {index: lead byte}."""
    out = {}
    i, end = o.start, o.end - 8
    while i < end:
        if d[i] in (0x85, 0x05) and d[i + 1] == 0x02 and d[i + 2] == 0:
            for skip in (0, 16):
                t = i + 5 + skip
                if t + 3 < o.end and d[t] == 0x01:
                    idx, typ = struct.unpack_from("<H", d, i + 3)[0], struct.unpack_from("<H", d, t + 1)[0]
                    if typ == 4 and t + 7 <= o.end:
                        out.setdefault(idx, struct.unpack_from("<f", d, t + 3)[0])
                        if leads is not None:
                            leads.setdefault(idx, d[i])
                        i = t + 7
                        break
                    if typ == 0x0B:
                        out.setdefault(idx, bool(d[t + 3]))
                        if leads is not None:
                            leads.setdefault(idx, d[i])
                        i = t + 4
                        break
            else:
                i += 1
            continue
        i += 1
    return out


def read_light(st, prim):
    """Light settings; "shader" = the ProgID of its first light shader; "soft_light" = {red, green, blue,
    intensity, shadow, atten, start, stop, spread} when that shader is Softimage's soft_light."""
    out = _params(st, prim, LIGHT_PARAMS)
    d = st.data
    first = None
    for h, _c, _p in prim.refs:
        o = st.by_handle.get(h)
        if o is None or st.guid(o.pbase) != SHADER:
            continue
        progid = shader_progid(d, o)
        if first is None:
            first = progid
            out["shader"] = progid
        if progid != first:
            break
        # a light refers to its shader twice (two objects, same ProgID); only one holds the values
        if progid and progid.startswith("Softimage.soft_light"):
            leads = {}
            rec = shader_records(d, o, leads)
            alpha = [i for i, lead in sorted(leads.items()) if lead == 0x05 and isinstance(rec[i], float)]
            if not alpha:
                continue
            sl = dict((name, rec[alpha[0] + k]) for k, name in SOFT_LIGHT.items() if alpha[0] + k in rec)
            if len(sl) == len(SOFT_LIGHT):
                out["soft_light"] = sl
                break
    return out
