# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Alex Doss
"""Simulated mouse: axis locking with the Softimage transform tools.
- V, press on the gizmo's X arrow, drag diagonally -> only X changes
- V, middle-drag off the gizmo -> only Z (Softimage middle = up) changes
- C, press on the Z rotate ring, drag -> only the Z rotation changes
Run: python -I tools/dev.py shot OUT.png --mode on --simulate 1 --wait 1 --script tests/gui_gizmo_sim.py"""
import math
import bpy, sys
from bpy_extras.view3d_utils import location_3d_to_region_2d
from mathutils import Vector
K = "bl_ext.user_default.silica"
tools = sys.modules[K + ".ops.tools"]
win = bpy.context.window_manager.windows[0]
views = sorted((a for a in win.screen.areas if a.type == 'VIEW_3D'), key=lambda a: (-a.y, a.x))
B = views[1]
region = next(r for r in B.regions if r.type == 'WINDOW')
errors, steps = [], []


def ev(t, v, x, y):
    win.event_simulate(type=t, value=v, x=int(x), y=int(y))


def s(fn, wait=0.15):
    steps.append((fn, wait))


def check(cond, msg):
    if not cond:
        errors.append(msg)


def run():
    if not steps:
        print("SHOT: GIZMO", "PASS" if not errors else "FAIL " + "; ".join(errors))
        return None
    fn, wait = steps.pop(0)
    try:
        fn()
    except Exception as e:
        import traceback
        errors.append("%s" % traceback.format_exc()[-300:])
    return wait


def screen(p3):
    r3 = B.spaces.active.region_3d
    p = location_3d_to_region_2d(region, r3, p3)
    return region.x + p.x, region.y + p.y


def gizmo_point(axis, frac=0.7):
    """screen point on the translate gizmo arrow, using the same size rule as the tool"""
    r3 = B.spaces.active.region_3d
    piv = ob.matrix_world.translation
    p2 = location_3d_to_region_2d(region, r3, piv)
    q2 = location_3d_to_region_2d(region, r3, piv + r3.view_rotation @ Vector((1, 0, 0)))
    length = bpy.context.preferences.view.gizmo_size * bpy.context.preferences.system.ui_scale / (q2 - p2).length
    return screen(piv + Vector(axis) * length * frac)


def setup():
    global ob
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o)
    with bpy.context.temp_override(window=win, area=B, region=region):
        bpy.ops.si.get_primitive(kind="CUBE")
    ob = bpy.context.view_layer.objects.active
    r3 = B.spaces.active.region_3d
    r3.view_location = (0, 0, 0)
    r3.view_distance = 40
    bpy.context.scene.transform_orientation_slots[0].type = 'GLOBAL'
s(setup, 0.4)


def drag(button, start_fn, delta, n=8):
    """start_fn() -> (x, y) is evaluated when the drag begins (the object may have moved)."""
    pos = {}
    def begin():
        pos["p"] = start_fn()
        ev('MOUSEMOVE', 'NOTHING', *pos["p"])
    s(begin, 0.1)
    s(lambda: ev(button, 'PRESS', *pos["p"]), 0.1)
    for i in range(1, n + 1):
        s((lambda k: (lambda: ev('MOUSEMOVE', 'NOTHING', pos["p"][0] + delta[0] * k / n,
                                 pos["p"][1] + delta[1] * k / n)))(i), 0.04)
    s(lambda: ev(button, 'RELEASE', pos["p"][0] + delta[0], pos["p"][1] + delta[1]), 0.3)


def tap(key, x, y):
    s(lambda: ev(key, 'PRESS', x, y), 0.05)
    s(lambda: ev(key, 'RELEASE', x, y), 0.3)


def remember(name, fn):
    def f():
        globals()[name] = fn()
    s(f, 0.05)


cx, cy = B.x + B.width // 2, B.y + B.height // 2
tap('V', cx, cy)

remember("loc0", lambda: ob.location.copy())
drag('LEFTMOUSE', lambda: gizmo_point((1, 0, 0)), (60, 45))
def check_x():
    d = ob.location - loc0
    check(abs(d.x) > 0.3 and abs(d.y) < 1e-4 and abs(d.z) < 1e-4, "X arrow drag: moved %r" % (tuple(d),))
s(check_x)

remember("loc1", lambda: ob.location.copy())
drag('MIDDLEMOUSE', lambda: (cx - 220, cy - 120), (0, 80))
def check_mid():
    d = ob.location - loc1
    check(abs(d.z) > 0.3 and abs(d.x) < 1e-4 and abs(d.y) < 1e-4, "middle drag off gizmo: moved %r" % (tuple(d),))
s(check_mid)

tap('C', cx, cy)


def ring_point():
    r3 = B.spaces.active.region_3d
    piv = ob.matrix_world.translation
    p2 = location_3d_to_region_2d(region, r3, piv)
    q2 = location_3d_to_region_2d(region, r3, piv + r3.view_rotation @ Vector((1, 0, 0)))
    length = bpy.context.preferences.view.gizmo_size * bpy.context.preferences.system.ui_scale / (q2 - p2).length
    best = None
    for k in range(24):          # the lowest point of the Z ring on screen: away from the X / Y rings
        a = 2 * math.pi * k / 24
        sx, sy = screen(piv + Vector((math.cos(a), math.sin(a), 0)) * length * 0.9)
        if best is None or sy < best[1]:
            best = (sx, sy)
    return best


remember("rot0", lambda: tuple(ob.rotation_euler))
drag('LEFTMOUSE', ring_point, (70, 0))
def check_ring():
    r = tuple(ob.rotation_euler)
    check(abs(r[2] - rot0[2]) > 0.05 and abs(r[0] - rot0[0]) < 1e-4 and abs(r[1] - rot0[1]) < 1e-4,
          "Z ring drag: rotation %r -> %r" % (rot0, r))
s(check_ring)
s(lambda: (ev('ESC', 'PRESS', cx, cy), ev('ESC', 'RELEASE', cx, cy)), 0.2)

bpy.app.timers.register(run, first_interval=0.5)
