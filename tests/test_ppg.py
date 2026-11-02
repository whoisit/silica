# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Alex Doss
"""Property Editor logic (spec properties.ppg): tabs, live parameters, Revert."""
import importlib

import bpy

KIT = None  # set by run.py


def _m(name):
    return importlib.import_module(KIT + "." + name)


def _on():
    mode = _m("mode")
    if not mode.is_on():
        mode.enter_mode()


def _fresh():
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o)


def _make(kind):
    bpy.ops.si.get_primitive(kind=kind)
    return bpy.context.view_layer.objects.active


def test_cube_tabs_and_labels():
    _on()
    _fresh()
    ppg = _m("ui.ppg")
    cube = _make("CUBE")
    tabs = [t for t, _ in ppg.property_sets(cube)]
    assert tabs == ["Cube", "Polygon Mesh", "Geometry", "Kinematics", "Visibility", "Display"], tabs
    sets = dict(ppg.property_sets(cube))
    cube_rows = [label for _t, rows in sets["Cube"] for _p, label, _k in rows]
    assert cube_rows == ["Name", "Length"], cube_rows
    geo = [label for _t, rows in sets["Geometry"] for _p, label, _k in rows]
    assert geo == ["U", "V", "Base"], geo


def test_length_through_ppg_and_revert():
    _on()
    _fresh()
    ppg = _m("ui.ppg")
    gn = _m("ops.gn_primitives")
    cube = _make("CUBE")
    ppg.snapshot(cube)
    st, prop = ppg.resolve(cube, ("mod", "Cube", "Length"))
    assert getattr(st, prop) == 8.0
    setattr(st, prop, 4.0)
    cube.location = (1, 2, 3)
    assert gn.get_param(gn.live_modifier(cube), "Length") == 4.0
    # the mesh follows (live primitive)
    cube.update_tag()
    dg = bpy.context.evaluated_depsgraph_get()
    dg.update()
    xs = [v.co.x for v in cube.evaluated_get(dg).data.vertices]
    assert abs(max(xs) - 2.0) < 1e-4, max(xs)
    n = ppg.revert(cube)
    assert n == 2, n
    assert gn.get_param(gn.live_modifier(cube), "Length") == 8.0
    assert tuple(cube.location) == (0.0, 0.0, 0.0)


def test_every_row_resolves():
    _on()
    _fresh()
    ppg = _m("ui.ppg")
    for kind in ("CUBE", "SPHERE", "GRID", "CYLINDER", "CONE", "TORUS", "LIGHT_SPOT", "LIGHT_POINT", "CAMERA", "NULL",
                 "DODECAHEDRON"):
        ob = _make(kind)
        for tab, sections in ppg.property_sets(ob):
            for _title, rows in sections:
                for path, label, _kw in rows:
                    if path[0] == "grey":
                        continue
                    st, prop = ppg.resolve(ob, path)
                    assert st is not None and hasattr(st, prop), "%s %s %s: %r" % (kind, tab, label, path)


def test_light_tabs():
    _on()
    _fresh()
    ppg = _m("ui.ppg")
    spot = _make("LIGHT_SPOT")
    tabs = [t for t, _ in ppg.property_sets(spot)]
    assert tabs[0] == "Light" and "Kinematics" in tabs
    labels = [label for _t, rows in dict(ppg.property_sets(spot))["Light"] for _p, label, _k in rows]
    assert "Cone Angle" in labels and "Intensity" in labels


def test_revert_enums_and_rotation_mode():
    """Bug review: enums (strings) must revert; rotation follows the rotation mode."""
    _on()
    _fresh()
    ppg = _m("ui.ppg")
    spot = _make("LIGHT_SPOT")
    ppg.snapshot(spot)
    spot.data.type = 'POINT'
    spot.rotation_mode = 'QUATERNION'
    spot.rotation_quaternion = (0.7, 0.7, 0, 0)
    ppg.revert(spot)
    assert spot.data.type == 'SPOT', spot.data.type
    assert spot.rotation_mode == 'XYZ', spot.rotation_mode
    # the Rotation row edits the property of the current mode
    spot.rotation_mode = 'QUATERNION'
    st, prop = ppg.resolve(spot, ("rot",))
    assert prop == "rotation_quaternion", prop


def test_snapshot_by_object_not_name():
    """Bug review: delete + recreate with the same name must not inherit the old snapshot; pane / popup separate."""
    _on()
    _fresh()
    ppg = _m("ui.ppg")
    cube = _make("CUBE")
    cube.location = (5, 0, 0)
    ppg.snapshot(cube, "pane")
    bpy.data.objects.remove(cube)
    cube2 = _make("CUBE")
    assert cube2.name == "cube"
    assert not ppg.has_snapshot(cube2, "pane"), "new cube inherited the deleted cube's snapshot"
    ppg.snapshot(cube2, "pane")
    cube2.location = (1, 1, 1)
    ppg.snapshot(cube2, "popup")          # a popup on the same object must not reset the pane's Revert point
    ppg.revert(cube2, "pane")
    assert tuple(cube2.location) == (0.0, 0.0, 0.0)


def test_lock_survives_rename():
    _on()
    _fresh()
    wm = bpy.context.window_manager
    cube = _make("CUBE")
    wm.si_ppg_target = cube
    wm.si_ppg_lock = True
    cube.name = "box"
    assert wm.si_ppg_target is not None and wm.si_ppg_target.name == "box"
    wm.si_ppg_lock = False
    wm.si_ppg_target = None


def test_kinematics_and_visibility_groups_match_capture():
    _on()
    _fresh()
    ppg = _m("ui.ppg")
    sets = dict(ppg.property_sets(_make("CUBE")))
    assert [t for t, _ in sets["Kinematics"]] == ["Scaling", "Rotation", "Position"]
    assert [t for t, _ in sets["Visibility"]][0] == "General"
