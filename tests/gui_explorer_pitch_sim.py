# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Alex Doss
# WAIT: 40
"""Explorer row pitch (council review 2026-11-16): the names, boxes and clicks use explorer.unit(); it must be the
row height of Blender's own layout at any UI scale and line width, or rows drift apart over a long list. Measured
by scrolling 10,000 rows to the end at three settings."""
import bpy, importlib
K = "bl_ext.user_default.silica"
wm = bpy.context.window_manager
win = wm.windows[0]
prefs = bpy.context.preferences
N = 10000
settings = [(1.0, 'AUTO'), (1.5, 'AUTO'), (1.25, 'THICK')]
errors = []
steps = []
S = {}


def ex():
    return importlib.import_module(K + ".ui.explorer")


def setup():
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o)
    sc = bpy.context.scene
    for i in range(N):
        sc.collection.objects.link(bpy.data.objects.new("p%05d" % i, None))
    a = sorted((a for a in win.screen.areas if a.type == 'VIEW_3D'), key=lambda a: (-a.y, a.x))[0]
    S["area"] = a
    with bpy.context.temp_override(window=win, area=a, region=[r for r in a.regions if r.type == 'WINDOW'][0]):
        bpy.ops.si.explorer_show()
    wm.si_explorer_scope = 'SCENE'
    wm.si_explorer_filter = 'OBJECTS'
    ex()._expanded.add("scene")


def reg():
    return next(r for r in S["area"].regions if r.type == 'WINDOW')


def apply(scale, lw):
    def go():
        prefs.view.ui_scale = scale
        prefs.view.ui_line_width = lw
        S["area"].tag_redraw()
    return go


def pan_down():
    r = reg()
    with bpy.context.temp_override(window=win, area=S["area"], region=r):
        for _ in range(60):
            bpy.ops.view2d.pan(deltax=0, deltay=-100000)
    S["area"].tag_redraw()


def measure(scale, lw):
    def go():
        r = reg()
        _x, bot = r.view2d.region_to_view(0, 0)
        n = len(ex().rows())
        true_u = (-bot - 4) / n
        u = ex().unit()
        if abs(true_u - u) > 0.01:
            errors.append("scale %s %s: layout row %.3f, unit() %.3f" % (scale, lw, true_u, u))
    return go


steps.append((setup, 1.0))
for sc_, lw in settings:
    steps += [(apply(sc_, lw), 1.0), (pan_down, 0.6), (pan_down, 0.6), (measure(sc_, lw), 0.1)]


def done():
    prefs.view.ui_scale = 1.0
    prefs.view.ui_line_width = 'AUTO'
    print("SHOT: PITCH", "PASS" if not errors else "FAIL " + " | ".join(errors))


steps.append((done, 0.2))


def run():
    if not steps:
        return None
    fn, w = steps.pop(0)
    try:
        fn()
    except Exception:
        import traceback
        traceback.print_exc()
    return w


bpy.app.timers.register(run, first_interval=1.0)
