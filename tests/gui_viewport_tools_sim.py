# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Alex Doss
# WAIT: 26
"""Viewport maximize + memo cams (specs viewport.maximize, viewport.memo-cams).
Run: python -I tools/dev.py guitest"""
import bpy, sys
K = "bl_ext.user_default.silica"
vt = sys.modules[K + ".ui.viewport_tools"]
win = bpy.context.window_manager.windows[0]
errors, steps = [], []


def panes():
    return vt.panes(win.screen)


def rects():
    return [(a.x, a.y, a.width, a.height) for a in panes()]


def others():
    names = ("PROPERTIES", "DOPESHEET_EDITOR")
    return sorted((a.type, a.x, a.y, a.width, a.height) for a in win.screen.areas
                  if a not in panes() and a.type in names)


def s(fn, wait=0.25):
    steps.append((fn, wait))


def check(cond, msg):
    if not cond:
        errors.append(msg)


def run():
    if not steps:
        print("SHOT: VIEWTOOLS", "PASS" if not errors else "FAIL " + " | ".join(errors))
        return None
    fn, wait = steps.pop(0)
    try:
        fn()
    except Exception:
        import traceback
        errors.append(traceback.format_exc()[-400:])
    return wait


def maxi(i, how):
    a = panes()[i]
    r = next(r for r in a.regions if r.type == 'WINDOW')
    with bpy.context.temp_override(window=win, area=a, region=r):
        bpy.ops.si.view_maximize('EXEC_DEFAULT', how=how)


def start():
    global base, base_others
    base, base_others = rects(), others()
    check(len(base) == 4, "need 4 panes, got %d" % len(base))
s(start)

# C1 full maximize of B (top right) and restore exactly; toolbar / MCP / timeline unchanged (C4)
s(lambda: maxi(1, 'FULL'), 0.9)
def c1():
    b = panes()[1]
    blk = base
    check(b.width > 0.9 * (blk[0][2] + blk[1][2]) and b.height > 0.9 * (blk[0][3] + blk[2][3]),
          "C1 B not maximized: %r" % ((b.width, b.height),))
    check(others() == base_others, "C4 docks/timeline changed")
s(c1)
s(lambda: maxi(1, 'RESTORE'), 0.9)
s(lambda: check(rects() == base, "C1 restore not exact: %r vs %r" % (rects(), base)))

# C2 horizontal: B's row takes the full width, heights unchanged
s(lambda: maxi(1, 'HORIZONTAL'), 0.9)
def c2():
    b, a = panes()[1], panes()[0]
    check(b.width > 0.9 * (base[0][2] + base[1][2]) and abs(b.height - base[1][3]) <= 2, "C2 horizontal: %r" % ((b.width, b.height),))
s(c2)
s(lambda: maxi(1, 'RESTORE'), 0.9)
s(lambda: check(rects() == base, "C2 restore not exact"))

# C3 vertical: C (bottom left) takes the full height, widths unchanged
s(lambda: maxi(2, 'VERTICAL'), 0.9)
def c3():
    c = panes()[2]
    check(c.height > 0.9 * (base[0][3] + base[2][3]) and abs(c.width - base[2][2]) <= 2, "C3 vertical: %r" % ((c.width, c.height),))
    check(others() == base_others, "C4 docks/timeline changed (vertical)")
s(c3)
s(lambda: maxi(2, 'RESTORE'), 0.9)
s(lambda: check(rects() == base, "C3 restore not exact"))

# C6 reset size: equal panes
s(lambda: maxi(0, 'HORIZONTAL'), 0.9)
s(lambda: maxi(0, 'RESET'), 0.9)
def c6():
    r = rects()
    check(abs(r[0][2] - r[1][2]) <= 4 and abs(r[0][3] - r[2][3]) <= 4, "C6 reset not equal: %r" % (r,))
s(c6)

# the user's bug (2026-11-01): F12 with the mouse over a view, and the header button path with the mouse over
# the header, failed because Blender's area_move refuses to run while the mouse is over a region
def f12_press():
    b = panes()[1]
    win.event_simulate(type='MOUSEMOVE', value='NOTHING', x=b.x + 120, y=b.y + 80)
s(f12_press, 0.2)
s(lambda: (win.event_simulate(type='F12', value='PRESS', x=panes()[1].x + 120, y=panes()[1].y + 80),
           win.event_simulate(type='F12', value='RELEASE', x=panes()[1].x + 120, y=panes()[1].y + 80)), 1.0)
def f12_check():
    global after_reset
    b = panes()[1]
    check(vt.is_maximized(win.screen) and b.width > 0.85 * (base[0][2] + base[1][2]), "F12 over a view did not maximize")
s(f12_check)
s(lambda: (win.event_simulate(type='F12', value='PRESS', x=panes()[1].x + 120, y=panes()[1].y + 80),
           win.event_simulate(type='F12', value='RELEASE', x=panes()[1].x + 120, y=panes()[1].y + 80)), 1.0)
s(lambda: check(not vt.is_maximized(win.screen), "F12 again did not restore"))
def header_button():
    a = panes()[2]
    hdr = next(r for r in a.regions if r.type == 'HEADER')
    win.event_simulate(type='MOUSEMOVE', value='NOTHING', x=hdr.x + hdr.width - 10, y=hdr.y + hdr.height // 2)
s(header_button, 0.2)
def header_invoke():
    a = panes()[2]
    hdr = next(r for r in a.regions if r.type == 'HEADER')
    with bpy.context.temp_override(window=win, area=a, region=hdr):
        bpy.ops.si.view_maximize('INVOKE_DEFAULT')
s(header_invoke, 1.0)
s(lambda: check(vt.is_maximized(win.screen), "header button path (mouse over the header) did not maximize"))
s(lambda: maxi(2, 'RESTORE'), 0.9)

# memo cams on view B: store, navigate, recall, clear
def memo():
    a = panes()[1]
    r = next(r for r in a.regions if r.type == 'WINDOW')
    r3 = a.spaces.active.region_3d
    with bpy.context.temp_override(window=win, area=a, region=r):
        r3.view_distance = 33.0
        bpy.ops.si.memo_cam('EXEC_DEFAULT', slot=0, action='STORE')
        check(vt.memo_slot(win.screen, a, 0) is not None, "M2 store failed")
        r3.view_distance = 80.0
        r3.view_rotation = (0.7, 0.7, 0, 0)
        bpy.ops.si.memo_cam('EXEC_DEFAULT', slot=0, action='RECALL')
        check(abs(r3.view_distance - 33.0) < 1e-4, "M3 recall distance %.2f" % r3.view_distance)
        res = bpy.ops.si.memo_cam('EXEC_DEFAULT', slot=2, action='RECALL')
        check(res == {'CANCELLED'}, "M4 empty slot did something")
        bpy.ops.si.memo_cam('EXEC_DEFAULT', slot=0, action='CLEAR')
        check(vt.memo_slot(win.screen, a, 0) is None, "M4 clear failed")
s(memo)

bpy.app.timers.register(run, first_interval=0.6)
