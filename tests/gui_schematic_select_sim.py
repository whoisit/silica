# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Alex Doss
# WAIT: 30
"""Schematic selection (spec schematic.selection) with simulated clicks on node positions: C1 left / Shift / Ctrl /
empty, C2 middle = branch, right = tree, C3 box drag, C5 Alt+right-click opens the object menu."""
import bpy, importlib
K = "bl_ext.user_default.silica"
wm = bpy.context.window_manager
win = wm.windows[0]
from _gui import Run
R = Run("SCHEMATIC_SELECT", step=0.2)
s, check, errors, S, steps = R.s, R.check, R.errors, R.S, R.steps
def sch(): return importlib.import_module(K + ".ui.schematic")
def ex(): return importlib.import_module(K + ".ui.explorer")
def views3d(): return sorted((a for a in win.screen.areas if a.type == 'VIEW_3D'), key=lambda a: (-a.y, a.x))
def reg(a): return next(r for r in a.regions if r.type == 'WINDOW')
def ctx(): return bpy.context.temp_override(window=win, area=S["area"], region=reg(S["area"]))
def sel(): return sorted(o.name for o in bpy.context.view_layer.objects.selected)
def at(name, dx=0.5, dy=0.5):
    with ctx():
        st = sch().state(bpy.context)
    n = next(n for n in st["nodes"].values() if n.name == name)
    x, y = st["pos"][n.uid]
    r = reg(S["area"])
    rx, ry = sch().to_region(r.view2d, x + n.w * dx, y + n.h * dy)
    return int(r.x + rx), int(r.y + ry)
def empty():
    """A point on the canvas with no node under it, away from the scrollbars (an edge press goes to Blender's
    View2D scroller)."""
    r = reg(S["area"])
    with ctx():
        for fx, fy in ((0.5, 0.85), (0.15, 0.85), (0.85, 0.85), (0.5, 0.15), (0.15, 0.5), (0.85, 0.5)):
            x, y = int(r.width * fx), int(r.height * fy)
            if sch().node_at(bpy.context, x, y) is None:
                return r.x + x, r.y + y
    return r.x + r.width // 2, r.y + r.height - 50
def click(p, button='LEFTMOUSE', **mods):
    win.event_simulate(type='MOUSEMOVE', value='NOTHING', x=p[0], y=p[1])
    win.event_simulate(type=button, value='PRESS', x=p[0], y=p[1], **mods)
    win.event_simulate(type=button, value='RELEASE', x=p[0], y=p[1], **mods)
def step_click(name, button='LEFTMOUSE', **mods):
    return lambda: click(at(name) if name else empty(), button, **mods)


def setup():
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o)
    sc = bpy.context.scene
    def ob(name, parent=None):
        o = bpy.data.objects.new(name, None)
        sc.collection.objects.link(o)
        o.parent = parent
        return o
    root = ob("ss_root")
    mid = ob("ss_mid", root)
    ob("ss_leaf", mid)
    ob("ss_a")
    ob("ss_b")
    a = views3d()[0]
    with bpy.context.temp_override(window=win, area=a, region=reg(a)):
        bpy.ops.si.schematic_show()
    S["area"] = a
    a.tag_redraw()
s(setup, 0.8)
def frame():
    with ctx():
        bpy.ops.si.schematic_frame(selected=False)
s(frame, 0.5)

s(step_click("ss_a"), 0.3)
s(lambda: check(sel() == ["ss_a"], "C1 click: %r" % sel()), 0.05)
s(step_click("ss_b", shift=True), 0.3)
s(lambda: check(sel() == ["ss_a", "ss_b"], "C1 Shift+click: %r" % sel()), 0.05)
s(step_click("ss_a", ctrl=True), 0.3)
s(lambda: check(sel() == ["ss_b"], "C1 Ctrl+click: %r" % sel()), 0.05)
s(step_click(None), 0.3)
s(lambda: check(sel() == ["ss_b"], "C1 click on empty space: %r" % sel()), 0.05)

s(step_click("ss_mid", 'MIDDLEMOUSE'), 0.3)
def c2_branch():
    check(sel() == ["ss_leaf", "ss_mid"], "C2 middle click: %r" % sel())
    check("ss_mid" in ex().branch_roots, "C2 not a branch pick: %r" % ex().branch_roots)
s(c2_branch, 0.05)
s(step_click("ss_leaf", 'RIGHTMOUSE'), 0.3)
s(lambda: check(sel() == ["ss_leaf", "ss_mid", "ss_root"] and "ss_root" in ex().branch_roots,
                "C2 right click (tree): %r / %r" % (sel(), ex().branch_roots)), 0.05)

def c3_drag():
    a, b = at("ss_a", -0.3, -0.6), at("ss_b", 1.3, 1.6)
    win.event_simulate(type='MOUSEMOVE', value='NOTHING', x=a[0], y=a[1])
    win.event_simulate(type='LEFTMOUSE', value='PRESS', x=a[0], y=a[1])
    for k in range(1, 9):
        win.event_simulate(type='MOUSEMOVE', value='NOTHING', x=a[0] + (b[0] - a[0]) * k // 8,
                           y=a[1] + (b[1] - a[1]) * k // 8)
    win.event_simulate(type='LEFTMOUSE', value='RELEASE', x=b[0], y=b[1])
s(c3_drag, 0.4)
s(lambda: check(sel() == ["ss_a", "ss_b"], "C3 box: %r" % sel()), 0.05)

s(step_click("ss_a", 'RIGHTMOUSE', alt=True), 0.5)
def c5():
    check(ex().menu_target.get("node") == ("object", "ss_a"), "C5 Alt+right-click target %r" % ex().menu_target)
    win.event_simulate(type='ESC', value='PRESS', x=10, y=10)
    win.event_simulate(type='ESC', value='RELEASE', x=10, y=10)
s(c5, 0.3)
R.start(0.8)
