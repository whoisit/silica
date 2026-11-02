# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Alex Doss
# WAIT: 8
"""Axis lock in component mode follows the component's frame (user report 2026-11-01): a cube rotated 30° about X,
top polygon selected, orientation Local (= Blender NORMAL in component mode, Softimage semantics). V, press on the
gizmo Z arrow (the polygon normal), drag: the polygon moves only along its normal, not along world Z."""
import math
import bmesh
import bpy, sys
from bpy_extras.view3d_utils import location_3d_to_region_2d
from mathutils import Vector, Matrix
K = "bl_ext.user_default.silica"
win = bpy.context.window_manager.windows[0]
views = sorted((a for a in win.screen.areas if a.type == 'VIEW_3D'), key=lambda a: (-a.y, a.x))
B = views[1]
region = next(r for r in B.regions if r.type == 'WINDOW')
errors, steps = [], []
def s(fn, w=0.15): steps.append((fn, w))
def check(c, m):
    if not c: errors.append(m)
def run():
    if not steps:
        print("SHOT: GIZMO_NORMAL", "PASS" if not errors else "FAIL " + " | ".join(errors))
        return None
    fn, w = steps.pop(0)
    try: fn()
    except Exception:
        import traceback; errors.append(traceback.format_exc()[-400:])
    return w
def ev(t, v, x, y): win.event_simulate(type=t, value=v, x=int(x), y=int(y))


def face_center_world():
    ob = bpy.context.edit_object
    bm = bmesh.from_edit_mesh(ob.data)
    f = next(f for f in bm.faces if f.select)
    return ob.matrix_world @ f.calc_center_median()


def setup(orient):
    def f():
        global ob, normal
        for o in list(bpy.data.objects):
            bpy.data.objects.remove(o)
        with bpy.context.temp_override(window=win, area=B, region=region):
            bpy.ops.si.get_primitive(kind="ICOSAHEDRON")      # faces tilted against the object axes
        ob = bpy.context.view_layer.objects.active
        with bpy.context.temp_override(window=win, area=B, region=region):
            bpy.ops.object.mode_set(mode='EDIT')
            bpy.ops.mesh.select_mode(type='FACE')
            bpy.ops.mesh.select_all(action='DESELECT')
        bm = bmesh.from_edit_mesh(ob.data)
        bm.faces.ensure_lookup_table()
        # a face whose normal is far from every world / object axis
        face = max(bm.faces, key=lambda f: min(abs(f.normal.x), abs(f.normal.y), abs(f.normal.z)))
        face.select = True
        bmesh.update_edit_mesh(ob.data)
        normal = (ob.matrix_world.to_3x3() @ face.normal).normalized()
        bpy.context.scene.transform_orientation_slots[0].type = orient
        r3 = B.spaces.active.region_3d
        r3.view_perspective = 'PERSP'
        r3.view_rotation = (0.82, 0.43, 0.18, 0.33)
        r3.view_location = face_center_world()
        r3.view_distance = 30
    f.__name__ = "setup_" + orient
    return f


def arrow_point():
    r3 = B.spaces.active.region_3d
    piv = face_center_world()
    p2 = location_3d_to_region_2d(region, r3, piv)
    q2 = location_3d_to_region_2d(region, r3, piv + r3.view_rotation @ Vector((1, 0, 0)))
    length = bpy.context.preferences.view.gizmo_size * bpy.context.preferences.system.ui_scale / (q2 - p2).length
    e = location_3d_to_region_2d(region, r3, piv + normal * length * 0.7)
    return region.x + e.x, region.y + e.y


cx, cy = region.x + region.width // 2, region.y + region.height // 2


def case(orient):
    s(setup(orient), 0.4)
    s(lambda: ev('MOUSEMOVE', 'NOTHING', cx, cy), 0.05)
    s(lambda: (ev('V', 'PRESS', cx, cy), ev('V', 'RELEASE', cx, cy)), 0.3)
    pos = {}
    def begin():
        pos["c0"] = face_center_world()
        pos["p"] = arrow_point()
        ev('MOUSEMOVE', 'NOTHING', *pos["p"])
    s(begin, 0.1)
    s(lambda: ev('LEFTMOUSE', 'PRESS', *pos["p"]), 0.1)
    for i in range(1, 9):
        s((lambda k: (lambda: ev('MOUSEMOVE', 'NOTHING', pos["p"][0] + 6 * k, pos["p"][1] + 8 * k)))(i), 0.04)
    s(lambda: ev('LEFTMOUSE', 'RELEASE', pos["p"][0] + 48, pos["p"][1] + 64), 0.3)
    def check_move():
        d = face_center_world() - pos["c0"]
        check(d.length > 0.2, "%s: polygon did not move (%.3f)" % (orient, d.length))
        if d.length > 0.2:
            off_axis = (d - normal * d.dot(normal)).length
            check(off_axis < 1e-3 * max(1.0, d.length) + 1e-4, "%s: moved off the normal: %r (normal %r)"
                  % (orient, tuple(round(x, 3) for x in d), tuple(round(x, 3) for x in normal)))
    s(check_move)
    s(lambda: (ev('ESC', 'PRESS', cx, cy), ev('ESC', 'RELEASE', cx, cy)), 0.2)
    def back():
        with bpy.context.temp_override(window=win, area=B, region=region):
            bpy.ops.object.mode_set(mode='OBJECT')
    s(back, 0.2)


case('NORMAL')     # the user's setting
case('LOCAL')      # Softimage Local in component mode = the component's frame

bpy.app.timers.register(run, first_interval=0.6)
