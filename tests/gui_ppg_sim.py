# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Alex Doss
# WAIT: 40
"""Property Editor (spec properties.ppg), GUI: every tab of every object type DRAWS without errors (the Visibility
bug found in review), Enter, Explorer icon operator -> right tab, popup on creation (on / off / docked pane), Recycle
and Lock (by reference), mode off restores panes."""
import bpy, sys, importlib
K = "bl_ext.user_default.silica"
ppg = importlib.import_module(K + ".ui.ppg")
docks = importlib.import_module(K + ".ui.docks")
mode = importlib.import_module(K + ".mode")
prefs = importlib.import_module(K + ".prefs")
win = bpy.context.window_manager.windows[0]
wm = bpy.context.window_manager
errors, steps = [], []
saved = {}
def s(fn, w=0.25): steps.append((fn, w))
def check(c, m):
    if not c: errors.append(m)
def run():
    if not steps:
        prefs.get().ppg_on_create = saved.get("ppg", True)        # leave the preference as the runner set it
        print("SHOT: PPG", "PASS" if not errors else "FAIL " + " | ".join(errors))
        return None
    fn, w = steps.pop(0)
    try: fn()
    except Exception:
        import traceback; errors.append(traceback.format_exc()[-300:])
    return w
def views():
    return sorted((a for a in win.screen.areas if a.type == 'VIEW_3D'), key=lambda a: (-a.y, a.x))
def reg(a, t='WINDOW'):
    return next(r for r in a.regions if r.type == t)
def redraw():
    with bpy.context.temp_override(window=win):
        bpy.ops.wm.redraw_timer(type='DRAW_WIN', iterations=1)


def setup():
    global A, B
    saved["ppg"] = prefs.get().ppg_on_create
    prefs.get().ppg_on_create = False
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o)
    A, B = views()[0], views()[1]
    with bpy.context.temp_override(window=win, area=B, region=reg(B)):
        for k in ("SPHERE", "LIGHT_SPOT", "CAMERA", "NULL", "DODECAHEDRON", "CUBE"):
            bpy.ops.si.get_primitive(kind=k)
    wm.si_ppg_popup_target = None
s(setup, 0.3)

# docked pane in A; draw every tab of every object type: no errors, rows drawn
def pane():
    global P
    with bpy.context.temp_override(window=win, area=A, region=reg(A)):
        bpy.ops.si.ppg_show()
    P = next(a for a in win.screen.areas if a.type == 'PROPERTIES' and docks.space_role(a.spaces.active) == "PPG")
s(pane, 0.4)
def draw_all():
    """One step per (object, tab): select, show the tab, let Blender redraw for real, then check."""
    ppg.draw_errors.clear()
    for name in [o.name for o in bpy.context.scene.objects]:
        ob = bpy.data.objects[name]
        for tab, _sections in ppg.property_sets(ob):
            def show(name=name, tab=tab):
                vl = bpy.context.view_layer
                for o in vl.objects:
                    o.select_set(False)
                vl.objects[name].select_set(True)
                vl.objects.active = vl.objects[name]
                wm.si_ppg_tab = tab
                ppg.drawn_rows.pop(tab, None)
                P.tag_redraw()
            def verify(name=name, tab=tab):
                check(ppg.drawn_rows.get(tab, 0) > 0 or tab == "Polygon Mesh", "%s / %s: nothing drawn" % (name, tab))
            steps.insert(0, (verify, 0.0))
            steps.insert(0, (show, 0.12))
    steps_order = []
s(lambda: None, 0.0)
def queue_draw_all():
    # insert the per-tab steps right after this one, in order
    before = len(steps)
    draw_all()
    added = steps[:len(steps) - before]
    del steps[:len(steps) - before]
    # pairs were inserted in reverse: restore the natural order
    pairs = [added[i:i + 2] for i in range(0, len(added), 2)][::-1]
    for pr in reversed(pairs):
        steps[0:0] = pr
s(queue_draw_all, 0.0)
s(lambda: check(not ppg.draw_errors, "draw errors: %s" % ppg.draw_errors[:3]), 0.1)

# Enter over view B opens the PPG of the selection (the cube)
def select_only(name):
    vl = bpy.context.view_layer
    for o in vl.objects:
        o.select_set(False)
    vl.objects[name].select_set(True)
    vl.objects.active = vl.objects[name]
def enter():
    select_only("cube")
    r = reg(B)
    win.event_simulate(type='MOUSEMOVE', value='NOTHING', x=r.x + 100, y=r.y + 100)
    win.event_simulate(type='RET', value='PRESS', x=r.x + 100, y=r.y + 100)
    win.event_simulate(type='RET', value='RELEASE', x=r.x + 100, y=r.y + 100)
s(enter, 0.4)
s(lambda: check(wm.si_ppg_popup_target is not None and wm.si_ppg_popup_target.name == "cube",
                "Enter: popup target %r" % wm.si_ppg_popup_target))
def esc():
    win.event_simulate(type='MOUSEMOVE', value='NOTHING', x=10, y=10)
    win.event_simulate(type='ESC', value='PRESS', x=10, y=10)
    win.event_simulate(type='ESC', value='RELEASE', x=10, y=10)
s(esc, 0.3)

# Explorer icon on a property row opens the PPG on that tab
def explorer_icon():
    with bpy.context.temp_override(window=win, area=B, region=reg(B)):
        bpy.ops.si.ppg_popup(obj="sphere", prop="Kinematics")
    check(wm.si_ppg_popup_target.name == "sphere" and wm.si_ppg_popup_tab == "Kinematics",
          "Explorer icon: %r tab %r" % (wm.si_ppg_popup_target, wm.si_ppg_popup_tab))
s(explorer_icon, 0.3)
s(esc, 0.3)

# Recycle follows the selection, Lock keeps the object (by reference: survives a rename)
def recycle_lock():
    select_only("cube")
    with bpy.context.temp_override(window=win, area=P, region=reg(P)):
        check(ppg.pane_target(bpy.context).name == "cube", "Recycle: pane does not follow the selection")
        bpy.ops.si.ppg_lock()
    check(wm.si_ppg_lock and wm.si_ppg_target.name == "cube", "Lock did not lock on the cube")
    bpy.data.objects["cube"].name = "box"
    select_only("sphere")
    with bpy.context.temp_override(window=win, area=P, region=reg(P)):
        check(ppg.pane_target(bpy.context).name == "box", "Lock lost the renamed object")
        bpy.ops.si.ppg_lock()
        check(ppg.pane_target(bpy.context).name == "sphere", "Unlock: back to Recycle")
    bpy.data.objects["box"].name = "cube"
    # nothing selected -> nothing shown (not the last active object)
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    with bpy.context.temp_override(window=win, area=P, region=reg(P)):
        check(ppg.pane_target(bpy.context) is None, "Recycle shows a deselected object")
s(recycle_lock, 0.3)

# popup on creation: a docked Recycle pane already shows the new object -> no popup
def create_with_pane():
    prefs.get().ppg_on_create = True
    wm.si_ppg_popup_target = None
    with bpy.context.temp_override(window=win, area=B, region=reg(B)):
        bpy.ops.si.get_primitive(kind="TORUS")
s(create_with_pane, 0.5)
s(lambda: check(wm.si_ppg_popup_target is None, "popup opened although a Recycle pane follows the selection"))
# no pane: preference on -> popup on the new object
def remove_pane():
    with bpy.context.temp_override(window=win, area=P, region=reg(P)):
        bpy.ops.si.view_set(view='TOP')
s(remove_pane, 0.3)
def create_no_pane():
    wm.si_ppg_popup_target = None
    with bpy.context.temp_override(window=win, area=B, region=reg(B)):
        bpy.ops.si.get_primitive(kind="CONE")
s(create_no_pane, 0.5)
s(lambda: check(wm.si_ppg_popup_target is not None and wm.si_ppg_popup_target.name == "cone",
                "popup on creation: %r" % wm.si_ppg_popup_target))
s(esc, 0.3)
def pref_off():
    prefs.get().ppg_on_create = False
    wm.si_ppg_popup_target = None
    with bpy.context.temp_override(window=win, area=B, region=reg(B)):
        bpy.ops.si.get_primitive(kind="CONE")
s(pref_off, 0.5)
s(lambda: check(wm.si_ppg_popup_target is None, "popup although the preference is off"))

# pane letters still count four panes
vp = importlib.import_module(K + ".ui.viewport")
def pane_again():
    with bpy.context.temp_override(window=win, area=A, region=reg(A)):
        bpy.ops.si.ppg_show()
    check(sum(1 for a in win.screen.areas if vp._is_pane(a)) == 4, "PPG pane not counted as a viewport pane")
s(pane_again, 0.3)

# mode off: panels / settings gone, and no kit pane left in any screen
def off_on():
    mode.exit_mode()
    check(not hasattr(bpy.types.WindowManager, "si_ppg_lock"), "mode off left PPG properties")
    check(not hasattr(bpy.types, "SI_PT_ppg_pane"), "mode off left the PPG panel")
    left = [a for scr in bpy.data.screens for a in scr.areas
            if a.type == 'PROPERTIES' and docks.space_role(a.spaces.active) in docks.PANE_ROLES]
    check(not left, "mode off left %d kit panes" % len(left))
    mode.enter_mode()
s(off_on, 0.6)
bpy.app.timers.register(run, first_interval=0.6)
