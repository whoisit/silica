# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Alex Doss
# WAIT: 8
"""Live primitive + component editing (spec model.get-primitive criterion 8): T on a live cube freezes it and enters
point mode; undo brings the live primitive back. Records how many undos that takes."""
import bpy, sys
K = "bl_ext.user_default.silica"
import importlib
gn = importlib.import_module(K + ".ops.gn_primitives")
win = bpy.context.window_manager.windows[0]
views = sorted((a for a in win.screen.areas if a.type == 'VIEW_3D'), key=lambda a: (-a.y, a.x))
B = views[1]
rB = next(r for r in B.regions if r.type == 'WINDOW')
errors, steps = [], []
def s(fn, w=0.3): steps.append((fn, w))
def check(c, m):
    if not c: errors.append(m)
def run():
    if not steps:
        print("SHOT: FREEZE", "PASS" if not errors else "FAIL " + " | ".join(errors))
        return None
    fn, w = steps.pop(0)
    try: fn()
    except Exception:
        import traceback; errors.append(traceback.format_exc()[-300:])
    return w
def ev(t, v):
    win.event_simulate(type=t, value=v, x=rB.x + rB.width // 2, y=rB.y + rB.height // 2)
def setup():
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o)
    with bpy.context.temp_override(window=win, area=B, region=rB):
        bpy.ops.si.get_primitive(kind="CUBE")
    bpy.ops.ed.undo_push(message="test: cube created")
s(setup, 0.4)
s(lambda: ev('MOUSEMOVE', 'NOTHING'), 0.1)
s(lambda: (ev('T', 'PRESS'), ev('T', 'RELEASE')), 0.5)
def after_t():
    ob = bpy.context.view_layer.objects.active
    check(bpy.context.mode == 'EDIT_MESH', "T did not enter component mode (mode %s)" % bpy.context.mode)
    check(gn.live_modifier(ob) is None and len(ob.data.vertices) == 8, "T did not freeze the live cube")
    check(tuple(bpy.context.tool_settings.mesh_select_mode) == (True, False, False), "not point mode")
s(after_t)
undos = {"n": 0}
def undo_until_live():
    for i in range(1, 5):
        with bpy.context.temp_override(window=win, area=B, region=rB):
            bpy.ops.ed.undo()
        ob = bpy.data.objects.get("cube")
        if ob is not None and gn.live_modifier(ob) is not None:
            undos["n"] = i
            return
    errors.append("undo never brought the live cube back")
s(undo_until_live, 0.5)
s(lambda: print("SHOT: undos needed to get the live cube back:", undos["n"]), 0.1)
s(lambda: check(undos["n"] in (1, 2), "undo needed %d steps" % undos["n"]))
bpy.app.timers.register(run, first_interval=0.6)
