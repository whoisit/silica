# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Alex Doss
"""Simulated keyboard/mouse: Softimage sticky/supra tools, drag-anywhere transform, S navigation, Q region,
clean views, mode off while a sticky tool runs.
Run: python -I tools/dev.py shot OUT.png --mode on --simulate 1 --wait 1 --script tests/gui_keys_sim.py"""
import bpy, sys
K = "bl_ext.user_default.silica"
tools = sys.modules[K + ".ops.tools"]
mode = sys.modules[K + ".mode"]
win = bpy.context.window_manager.windows[0]
views = sorted((a for a in win.screen.areas if a.type == 'VIEW_3D'), key=lambda a: (-a.y, a.x))
B = views[1]
cx, cy = B.x + B.width // 2, B.y + B.height // 2
errors = []
steps = []


def ev(t, v, x=None, y=None):
    win.event_simulate(type=t, value=v, x=cx if x is None else x, y=cy if y is None else y)


def s(fn, wait=0.2):
    steps.append((fn, wait))


def check(cond, msg):
    if not cond:
        errors.append(msg)


def run():
    if not steps:
        print("SHOT: SIM", "PASS" if not errors else "FAIL " + "; ".join(errors))
        return None
    fn, wait = steps.pop(0)
    try:
        fn()
    except Exception as e:
        errors.append("%s: %r" % (getattr(fn, "__name__", "?"), e))
    return wait


def setup():
    global ob
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o)
    region = next(r for r in B.regions if r.type == 'WINDOW')
    with bpy.context.temp_override(window=win, area=B, region=region):
        bpy.ops.si.get_primitive(kind="SPHERE")
    ob = bpy.context.view_layer.objects.active
    sp = B.spaces.active
    check(not sp.show_gizmo_navigate, "navigation gizmo visible")
    check(not sp.overlay.show_cursor, "3D cursor visible")
    check(not sp.overlay.show_text, "text overlay visible")
    ev('MOUSEMOVE', 'NOTHING')
s(setup, 0.3)

# tap V: sticky translate
s(lambda: ev('V', 'PRESS'), 0.05)
s(lambda: ev('V', 'RELEASE'), 0.3)
s(lambda: check(tools.state["sticky"] == 'MOVE' and tools.state["active"] is not None,
                "tap V: sticky=%s active=%s" % (tools.state["sticky"], tools.state["active"])))
# drag anywhere (empty space, away from the sphere) moves the selection
def drag_start():
    global loc0
    loc0 = ob.location.copy()
    ev('MOUSEMOVE', 'NOTHING', cx + 200, cy + 120)
s(drag_start, 0.1)
s(lambda: ev('LEFTMOUSE', 'PRESS', cx + 200, cy + 120), 0.1)
for i in range(1, 9):
    s((lambda k: (lambda: ev('MOUSEMOVE', 'NOTHING', cx + 200 + 15 * k, cy + 120)))(i), 0.04)
s(lambda: ev('LEFTMOUSE', 'RELEASE', cx + 320, cy + 120), 0.3)
s(lambda: check((ob.location - loc0).length > 0.5, "drag anywhere with V did not move (%r)" % (tuple(ob.location),)))

# hold S during sticky V: middle drag dollies, release returns to V
def hold_s():
    global d0
    d0 = B.spaces.active.region_3d.view_distance
    ev('S', 'PRESS')
s(hold_s, 0.4)
s(lambda: ev('MIDDLEMOUSE', 'PRESS'), 0.1)
for i in range(1, 8):
    s((lambda k: (lambda: ev('MOUSEMOVE', 'NOTHING', cx, cy + 12 * k)))(i), 0.04)
s(lambda: ev('MIDDLEMOUSE', 'RELEASE', cx, cy + 84), 0.2)
s(lambda: ev('S', 'RELEASE', cx, cy + 84), 0.4)
s(lambda: check(abs(B.spaces.active.region_3d.view_distance - d0) > 0.01, "hold S + middle drag did not dolly"))
s(lambda: check(tools.state["active"] is not None and tools.state["active"].tool == 'MOVE',
                "after hold S: back to %s (want MOVE)" % (tools.state["active"] and tools.state["active"].tool)))

# Esc: back to selection
s(lambda: ev('ESC', 'PRESS'), 0.05)
s(lambda: ev('ESC', 'RELEASE'), 0.2)
s(lambda: check(tools.state["active"] is None and tools.state["sticky"] == 'SELECT', "Esc did not end the tool"))

# hold C: rotate while held, then back to selection (the last sticky tool)
s(lambda: ev('C', 'PRESS'), 0.4)
s(lambda: check(tools.state["active"] is not None and tools.state["active"].tool == 'ROTATE', "hold C: no rotate tool"))
s(lambda: ev('C', 'RELEASE'), 0.3)
s(lambda: check(tools.state["active"] is None, "after hold C: a tool is still active"))

# Q + drag: render region
s(lambda: ev('MOUSEMOVE', 'NOTHING', cx - 150, cy - 100), 0.1)
s(lambda: ev('Q', 'PRESS', cx - 150, cy - 100), 0.05)
s(lambda: ev('Q', 'RELEASE', cx - 150, cy - 100), 0.2)
s(lambda: ev('LEFTMOUSE', 'PRESS', cx - 150, cy - 100), 0.1)
s(lambda: ev('MOUSEMOVE', 'NOTHING', cx + 150, cy + 100), 0.1)
s(lambda: ev('LEFTMOUSE', 'RELEASE', cx + 150, cy + 100), 0.5)
s(lambda: check(B.spaces.active.use_render_border and B.spaces.active.shading.type == 'RENDERED', "Q drag: no region"))

# sticky V, then switch the mode off and keep moving the mouse: must not crash
s(lambda: ev('V', 'PRESS'), 0.05)
s(lambda: ev('V', 'RELEASE'), 0.3)
s(lambda: mode.exit_mode(), 0.2)
for i in range(4):
    s((lambda k: (lambda: ev('MOUSEMOVE', 'NOTHING', cx + 10 * k, cy)))(i), 0.05)
s(lambda: ev('LEFTMOUSE', 'PRESS'), 0.05)
s(lambda: ev('LEFTMOUSE', 'RELEASE'), 0.2)
s(lambda: check(not mode.is_on(), "mode still on"))
s(lambda: mode.enter_mode(), 0.5)

bpy.app.timers.register(run, first_interval=0.5)
