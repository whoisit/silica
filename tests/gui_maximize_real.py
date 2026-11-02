# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Alex Doss
# WAIT: 8
# SIMULATE: 0
"""Maximize with REAL cursor input (no event simulation): the path the user hit on 2026-11-01
(Blender's area_move refuses to run while the mouse is over a region). Run without --simulate:
python -I tools/dev.py shot OUT.png --mode on --wait 8 --script tests/gui_maximize_real.py"""
import bpy, sys
K = "bl_ext.user_default.silica"
vt = sys.modules[K + ".ui.viewport_tools"]
win = bpy.context.window_manager.windows[0]
errors, steps = [], []
def s(fn, w=0.3): steps.append((fn, w))
def check(c, m):
    if not c: errors.append(m)
def run():
    if not steps:
        print("SHOT: MAXREAL", "PASS" if not errors else "FAIL " + " | ".join(errors))
        return None
    fn, w = steps.pop(0)
    try: fn()
    except Exception:
        import traceback; errors.append(traceback.format_exc()[-300:])
    return w
def rects(): return [(a.x, a.y, a.width, a.height) for a in vt.panes(win.screen)]
def start():
    global base, B
    base = rects()
    B = vt.panes(win.screen)[1]
    win.cursor_warp(B.x + 120, B.y + 80)          # the real mouse over view B
s(start, 0.4)
def invoke():
    r = next(r for r in B.regions if r.type == 'WINDOW')
    with bpy.context.temp_override(window=win, area=B, region=r):
        bpy.ops.si.view_maximize('INVOKE_DEFAULT')
s(invoke, 1.2)
s(lambda: check(vt.is_maximized(win.screen) and B.width > 0.85 * (base[0][2] + base[1][2]),
                "real cursor over view: not maximized %r" % (rects(),)))
s(invoke, 1.2)
s(lambda: check(not vt.is_maximized(win.screen) and rects() == base, "real cursor: restore not exact %r vs %r" % (rects(), base)))
bpy.app.timers.register(run, first_interval=0.8)
