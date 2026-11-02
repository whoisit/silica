# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Alex Doss
"""MCP (spec mcp.mcp), background. Each panel is drawn into a recording layout, so the test sees what every button
is bound to; the bound operators are then run as the button would run them.
C1 Object / Point / Edge / Polygon switch object / edit mode and component type; C2 S / R / T x y z are the active
object's scale / rotation / location (disabled without one); C3 Global / Local / View set the orientation the
transform tools use; C4 Snap ON = use_snap, Parent parents to the active, Cut un-parents keeping transforms;
C5 the unimplemented buttons are drawn and greyed."""
import importlib
from types import SimpleNamespace

import bpy

KIT = None  # set by run.py


def _m(name):
    return importlib.import_module(KIT + "." + name)


class _Props:
    pass


class _Rec:
    """Stand-in for bpy.types.UILayout: logs every button (kind, what, kwargs, props, layout it was drawn in)."""

    def __init__(self, log, parent=None):
        self.log, self.parent = log, parent
        self.enabled = True
        self.active = True
        self.alignment = 'EXPAND'

    def _sub(self, *_a, **_k):
        return _Rec(self.log, self)
    column = row = grid_flow = box = split = _sub

    def operator(self, idname, **kw):
        p = _Props()
        self.log.append(("op", idname, kw, p, self))
        return p

    def prop(self, data, attr, **kw):
        self.log.append(("prop", (data, attr), kw, None, self))

    def menu(self, name, **kw):
        self.log.append(("menu", name, kw, None, self))

    def label(self, **kw):
        self.log.append(("label", kw.get("text", ""), kw, None, self))

    def separator(self, **_k):
        pass

    def is_enabled(self):
        r = self
        while r is not None:
            if not r.enabled:
                return False
            r = r.parent
        return True


def _draw(panel):
    log = []
    panel.draw(SimpleNamespace(layout=_Rec(log)), bpy.context)
    return log


def _ops(log, idname):
    return [(kw.get("text"), vars(p), kw) for kind, what, kw, p, _l in log if kind == "op" and what == idname]


def _scene():
    _m("mode").enter_mode()
    if bpy.context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o)
    bpy.ops.mesh.primitive_cube_add()
    cube = bpy.context.active_object
    cube.name = "cube"
    return cube


def _select(*obs, active):
    for o in bpy.context.view_layer.objects:
        o.select_set(o in obs)
    bpy.context.view_layer.objects.active = active


def test_c1_selection_filters():
    cube = _scene()
    docks = _m("ui.docks")
    got = _ops(_draw(docks.SI_PT_mcp_select), "si.select_filter")
    assert [(t, p["mode"]) for t, p, _k in got] == [("Object", 'OBJECT'), ("Point", 'VERT'), ("Edge", 'EDGE'),
                                                   ("Polygon", 'FACE')], got
    assert got[0][2].get("depress") is True                      # Object mode shows Object pressed
    _select(cube, active=cube)
    bpy.ops.si.select_filter(mode='EDGE')
    assert bpy.context.mode == 'EDIT_MESH' and tuple(bpy.context.tool_settings.mesh_select_mode) == (False, True, False)
    got = _ops(_draw(docks.SI_PT_mcp_select), "si.select_filter")
    assert [k.get("depress") for _t, _p, k in got] == [False, False, True, False], got
    bpy.ops.si.select_filter(mode='OBJECT')
    assert bpy.context.mode == 'OBJECT'


def test_c2_transform_fields():
    cube = _scene()
    docks = _m("ui.docks")
    _select(cube, active=cube)
    log = _draw(docks.SI_PT_mcp_transform)
    fields = [(what[0], what[1], kw.get("index")) for kind, what, kw, _p, _l in log
              if kind == "prop" and what[1] in ("scale", "rotation_euler", "location")]
    want = [(cube, a, i) for a in ("scale", "rotation_euler", "location") for i in range(3)]
    assert fields == want, fields
    _select(active=None)
    log = _draw(docks.SI_PT_mcp_transform)
    assert not [w for k, w, *_ in log if k == "prop" and w[1] in ("scale", "rotation_euler", "location")]
    axes = [l for k, w, _kw, _p, l in log if k == "label" and w in ("x", "y", "z")]
    assert len(axes) == 9 and not any(l.is_enabled() for l in axes), "fields not disabled without an object"


def test_c3_orientation_used_by_tools():
    from mathutils import Euler
    cube = _scene()
    docks, tools = _m("ui.docks"), _m("ops.tools")
    _select(cube, active=cube)
    slot = bpy.context.scene.transform_orientation_slots[0]
    log = _draw(docks.SI_PT_mcp_transform)
    orient = [(what, kw) for kind, what, kw, _p, _l in log if kind == "prop" and what[1] == "type"]
    assert orient and orient[0][0][0] == slot and orient[0][1].get("expand"), orient
    cube.rotation_euler = Euler((0.3, 0.5, 0.7))
    bpy.context.view_layer.update()
    try:
        slot.type = 'LOCAL'
        kind, mat = tools._orientation(bpy.context, None)
        want = cube.matrix_world.to_3x3().normalized()
        assert kind == 'LOCAL' and all(abs(a - b) < 1e-5 for r1, r2 in zip(mat, want) for a, b in zip(r1, r2)), mat
        slot.type = 'GLOBAL'
        kind, mat = tools._orientation(bpy.context, None)
        assert kind == 'GLOBAL' and mat == mat.Identity(3)
    finally:
        slot.type = 'GLOBAL'


def test_c4_snap_parent_cut():
    from mathutils import Vector
    cube = _scene()
    docks = _m("ui.docks")
    log = _draw(docks.SI_PT_mcp_snap)
    snap = [(what, kw) for kind, what, kw, _p, _l in log if kind == "prop"]
    assert snap[0][0] == (bpy.context.tool_settings, "use_snap") and snap[0][1].get("text") == "ON", snap
    bpy.ops.mesh.primitive_cube_add(location=(3, 0, 0))
    child = bpy.context.active_object
    child.name = "child"
    cube.location = (0, 2, 0)
    bpy.context.view_layer.update()
    log = _draw(docks.SI_PT_mcp_constrain)
    (pt, pp, _), = _ops(log, "object.parent_set")
    (ct, cp, _), = _ops(log, "object.parent_clear")
    assert (pt, ct) == ("Parent", "Cut"), (pt, ct)
    _select(child, cube, active=cube)
    bpy.ops.object.parent_set(**pp)                              # as the Parent button runs it
    assert child.parent == cube
    cube.location = (0, 5, 0)                                    # the child follows: world (3, 3, 0)
    bpy.context.view_layer.update()
    world = child.matrix_world.translation.copy()
    assert (world - Vector((3, 3, 0))).length < 1e-5, world
    _select(child, active=child)
    bpy.ops.object.parent_clear(**cp)                            # as the Cut button runs it
    bpy.context.view_layer.update()
    assert child.parent is None and (child.matrix_world.translation - world).length < 1e-5, \
        "Cut moved the child: %r" % child.matrix_world.translation


def test_c5_unimplemented_greyed():
    _scene()
    docks = _m("ui.docks")
    drawn = []
    for panel in (docks.SI_PT_mcp_select, docks.SI_PT_mcp_edit):
        drawn += [t for t, _p, _k in _ops(_draw(panel), "si.unmapped")]
    assert drawn == ["Scene", "Selection", "Clusters", "Freeze M", "Immed"], drawn
    assert not bpy.ops.si.unmapped.poll()                       # Blender greys a button whose operator can't run
