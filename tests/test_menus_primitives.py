# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Alex Doss
"""Menus are built from the captured data; primitives match Softimage's defaults."""
import importlib

import bpy

KIT = None  # set by run.py


def _m(name):
    return importlib.import_module(KIT + "." + name)


def _on():
    mode = _m("mode")
    if not mode.is_on():
        mode.enter_mode()
    return mode


def test_every_mapped_path_exists():
    _on()
    build = _m("menus.build")
    from_map = _m("menus.map").MAP
    missing = sorted(p for p in from_map if p not in build.ALL_PATHS)
    assert not missing, "map keys not in the menu data: %s" % missing


def test_top_menus_registered():
    _on()
    build = _m("menus.build")
    for title, idname in build.TOP_IDS.items():
        assert hasattr(bpy.types, idname), title


def _new_scene():
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o)


def _make(kind):
    bpy.ops.si.get_primitive(kind=kind)
    return bpy.context.view_layer.objects.active


def _evaluated(ob):
    """Mesh after modifiers (live Geometry Nodes primitives have an empty base mesh)."""
    dg = bpy.context.evaluated_depsgraph_get()
    dg.update()
    return ob.evaluated_get(dg).data


def _bbox(ob):
    vs = [v.co for v in _evaluated(ob).vertices]
    return ([round(min(v[i] for v in vs), 3) for i in range(3)], [round(max(v[i] for v in vs), 3) for i in range(3)])


# kind: (points, polygons, bbox min, bbox max) - Softimage counts, Blender Z-up
EXPECT = {
    "CUBE": (8, 6, [-4, -4, -4], [4, 4, 4]),
    "SPHERE": (58, 64, [-4, -4, -4], [4, 4, 4]),
    "GRID": (81, 64, [-4, -4, 0], [4, 4, 0]),
    "CYLINDER": (42, 48, [-1, -1, -2], [1, 1, 2]),
    "CONE": (26, 32, [-1, -1, -1.333], [1, 1, 2.667]),
    "TORUS": (64, 64, [-4, -4, -1], [4, 4, 1]),
    "DISC": (72, 64, [-4, -4, 0], [4, 4, 0]),     # Softimage: annulus, inner radius 2
    "OCTAHEDRON": (6, 8, [-4, -4, -4], [4, 4, 4]),
    "TETRAHEDRON": (4, 4, None, None),
    "ICOSAHEDRON": (12, 20, None, None),
    "DODECAHEDRON": (20, 12, None, None),
}


def test_primitives_match_softimage():
    _on()
    _new_scene()
    bad = []
    for kind, (pts, polys, lo, hi) in EXPECT.items():
        ob = _make(kind)
        me = _evaluated(ob)
        if len(me.vertices) != pts or len(me.polygons) != polys:
            bad.append("%s: %d pts %d polys, want %d/%d" % (kind, len(me.vertices), len(me.polygons), pts, polys))
            continue
        if lo is not None:
            a, b = _bbox(ob)
            if any(abs(x - y) > 0.01 for x, y in zip(a + b, lo + hi)):
                bad.append("%s: bbox %s %s, want %s %s" % (kind, a, b, lo, hi))
    assert not bad, "\n".join(bad)


def test_live_primitives():
    """Spec model.get-primitive criteria 6, 7: live parameters, Freeze applies."""
    _on()
    _new_scene()
    gn = _m("ops.gn_primitives")
    for kind in gn.LIVE:
        ob = _make(kind)
        mod = gn.live_modifier(ob)
        assert mod is not None and mod.name == gn.OP_NAMES[kind], kind
        assert len(ob.data.vertices) == 0, "%s base mesh should be empty" % kind
    cube = bpy.data.objects["cube"]
    mod = gn.live_modifier(cube)
    assert gn.get_param(mod, "Length") == 8.0
    gn.set_param(mod, "Length", 4.0)
    lo, hi = _bbox(cube)
    assert abs(hi[0] - 2.0) < 0.01 and abs(lo[2] + 2.0) < 0.01, (lo, hi)
    gn.set_param(mod, "Subdivisions U", 3)
    n = len(_evaluated(cube).vertices)
    assert n == 16, "cube with 3 U subdivisions: %d points, want 16" % n      # 4 x 2 x 2
    # Freeze: modifier applied, same points, no SI modifier left
    bpy.context.view_layer.objects.active = cube
    assert gn.freeze(bpy.context, cube)
    assert gn.live_modifier(cube) is None and len(cube.data.vertices) == n


def test_softimage_names():
    _on()
    _new_scene()
    names = [_make("CUBE").name for _ in range(3)]
    assert names == ["cube", "cube1", "cube2"], names


def test_lights_and_cameras():
    _on()
    _new_scene()
    spot = _make("LIGHT_SPOT")
    assert spot.type == 'LIGHT' and spot.data.type == 'SPOT'
    assert spot.constraints[0].target.name.endswith("_Interest")
    cam = _make("CAMERA")
    assert cam.type == 'CAMERA' and abs(cam.data.angle - 0.93616) < 0.001   # 53.638 degrees
    assert cam.parent and cam.parent.name.startswith("Camera_Root")
    sun = _make("LIGHT_INFINITE")
    assert sun.data.type == 'SUN'


def test_undo_friendly_and_selected():
    _on()
    _new_scene()
    ob = _make("SPHERE")
    assert ob.select_get() and bpy.context.view_layer.objects.active == ob
    assert [o for o in bpy.context.selected_objects] == [ob]
