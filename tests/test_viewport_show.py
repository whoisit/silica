# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Alex Doss
"""Viewport Show menu (Softimage's eye icon, user request 2026-11-11): every mapped item switches real per-view
Blender settings; toggles and Check All / Check None act on the right items."""
import importlib
import types

import bpy

KIT = None  # set by run.py

OWNERS = {"space": bpy.types.SpaceView3D, "overlay": bpy.types.View3DOverlay, "shading": bpy.types.View3DShading}


def _fake_view(vp):
    """A stand-in 3D view holding every setting the menu touches (background tests have no real 3D view)."""
    v = types.SimpleNamespace(overlay=types.SimpleNamespace(), shading=types.SimpleNamespace())
    for item in vp.SHOW_MENU:
        if isinstance(item, tuple) and item[1]:
            for owner, attr in item[1]:
                setattr(v if owner == "space" else getattr(v, owner), attr, True)
    return v


def test_show_menu():
    vp = importlib.import_module(KIT + ".ui.viewport")
    items = [i for i in vp.SHOW_MENU if isinstance(i, tuple)]
    assert len(items) >= 45, len(items)                       # every captured item is listed
    for name, targets in items:
        for owner, attr in targets or ():
            assert attr in OWNERS[owner].bl_rna.properties, (name, owner, attr)
    v = _fake_view(vp)
    # toggling one item switches all of its Blender settings
    vp.set_show(v, "3D Geometry", not vp.show_state(v, "3D Geometry"))
    assert not v.show_object_viewport_mesh and not v.show_object_viewport_surf and not v.show_object_viewport_font
    assert vp.show_state(v, "Lights") and vp.show_state(v, "Frame Rate") is None      # others unchanged; greyed = None
    # Check None of the objects group hides object types only, not viewport aids or components
    op = types.SimpleNamespace(group="objects", on=False, item="")
    vp.SI_OT_show_toggle.execute(op, types.SimpleNamespace(space_data=v))
    assert not v.show_object_viewport_light and not v.show_object_viewport_empty and not v.show_object_viewport_camera
    assert v.show_gizmo and v.overlay.show_floor and v.overlay.show_object_origins
    # bug 2026-11-11: after Check None, single items could not be switched back on (the operator remembered
    # group="objects" from the Check None call). Its settings must not be remembered between calls.
    mode = importlib.import_module(KIT + ".mode")
    if not mode.is_on():
        mode.enter_mode()
    props = bpy.ops.si.show_toggle.get_rna_type().properties
    for prop in ("item", "group", "on"):
        assert props[prop].is_skip_save, prop
