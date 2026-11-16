# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Alex Doss
# WAIT: 30
"""Explorer scopes (spec explorer.scopes) in a window: C2 scope keys over the Explorer (P, U, E, M, S) and not
elsewhere; C1 the Scope menu operator and the header label; C3 / C7 the current pass bold, a click on another pass
row only highlights it, its right-click menu's Set as Current Pass makes it the window's view layer; C8 (render.overrides) a click on
an Override row opens the partition's page, a middle click on it leaves no modal pan behind. Rows are found by position (explorer.name_x, one row per UI unit)."""
import bpy, importlib, os
K = "bl_ext.user_default.silica"
wm = bpy.context.window_manager
win = wm.windows[0]
errors, steps, S = [], [], {}
def s(fn, w=0.2): steps.append((fn, w))
def check(c, m):
    if not c: errors.append(m)
def run():
    if not steps:
        wm.si_explorer_scope = 'SCENE'
        print("SHOT: SCOPES", "PASS" if not errors else "FAIL " + " | ".join(errors))
        return None
    fn, w = steps.pop(0)
    try: fn()
    except Exception:
        import traceback; tb = traceback.format_exc().strip().splitlines(); errors.append(" / ".join(tb[-3:]))
    return w
def ex(): return importlib.import_module(K + ".ui.explorer")
def views3d(): return sorted((a for a in win.screen.areas if a.type == 'VIEW_3D'), key=lambda a: (-a.y, a.x))
def reg(a): return next(r for r in a.regions if r.type == 'WINDOW')
def U(): return ex().unit()        # Blender's widget unit (measured: not 20 * ui_scale)
def scope(): return wm.si_explorer_scope
def rows():
    with bpy.context.temp_override(window=win, area=S["area"], region=reg(S["area"])):
        return ex().rows()
def key(k, where="explorer", w=0.3):
    def go():
        a = S["area"] if where == "explorer" else S["view"]
        x, y = a.x + a.width - 40, a.y + 40
        win.event_simulate(type='MOUSEMOVE', value='NOTHING', x=x, y=y)
        win.event_simulate(type=k, value='PRESS', x=x, y=y)
        win.event_simulate(type=k, value='RELEASE', x=x, y=y)
    s(go, w)


def setup():
    a = views3d()[0]
    S["area"], S["view"] = a, views3d()[1]
    with bpy.context.temp_override(window=win, area=a, region=reg(a)):
        bpy.ops.si.explorer_show()
    with bpy.context.temp_override(window=win, area=S["view"], region=reg(S["view"])):
        bpy.ops.si.get_primitive(kind="CUBE")
        bpy.ops.si.create_pass(name="Beauty")
        bpy.ops.si.set_current_pass(name="Default_Pass")
    wm.si_explorer_scope = 'SCENE'
    a.tag_redraw()
s(setup, 0.6)

# C2 scope keys over the Explorer
for k, want in (('P', 'PASSES'), ('U', 'CURRENT_PASS'), ('E', 'SELECTION'), ('M', 'MATERIALS'), ('S', 'SCENE')):
    key(k)
    s(lambda want=want, k=k: check(scope() == want, "C2 %s over the Explorer: scope %s" % (k, scope())), 0.05)
# ... and not over a 3D view (there U keeps its own meaning)
def view_m():
    S["before"] = scope()
s(view_m, 0.05)
key('U', where="view")
s(lambda: check(scope() == S["before"], "C2 U over a 3D view changed the Explorer scope to %s" % scope()), 0.05)

# C1 the Scope menu item (runs the operator in the header) and the header label
def menu():
    a = S["area"]
    hdr = next(r for r in a.regions if r.type == 'HEADER')
    with bpy.context.temp_override(window=win, area=a, region=hdr):
        bpy.ops.si.explorer_scope('INVOKE_DEFAULT', scope='PASSES')
    check(scope() == 'PASSES', "C1 Scope > Passes: %s" % scope())
    a.tag_redraw()
s(menu, 0.4)

# C3 the current pass is bold and opened; C7 clicking Beauty makes it the window's view layer
def c3():
    rs = rows()
    bold = [r.label for r in rs if r.bold]
    check(bold == ["Default_Pass"], "C3 bold rows %r" % bold)
    check(any(r.depth == 1 and r.node and r.node[0] == "partition" for r in rs), "C3 current pass not opened")
    out = os.path.abspath(os.path.join(".dev", "shots", "explorer_scopes_passes.png"))
    if os.path.isdir(os.path.dirname(out)):
        with bpy.context.temp_override(window=win):
            bpy.ops.screen.screenshot(filepath=out)
    i = next((k for k, r in enumerate(rs) if r.node == ("pass", "Beauty")), None)
    check(i is not None, "C3 no Beauty row")
    if i is None:
        return
    r = reg(S["area"])
    y = r.view2d.view_to_region(0, -(4 + U() * i + U() / 2), clip=False)[1]
    S["at"] = (int(r.x + ex().name_x(rs[i]) + 12), int(r.y + y))
    win.event_simulate(type='MOUSEMOVE', value='NOTHING', x=5, y=5)
    win.event_simulate(type='MOUSEMOVE', value='NOTHING', x=S["at"][0], y=S["at"][1])
s(c3, 0.2)
def click():
    if "at" in S:
        x, y = S["at"]
        win.event_simulate(type='LEFTMOUSE', value='PRESS', x=x, y=y)
        win.event_simulate(type='LEFTMOUSE', value='RELEASE', x=x, y=y)
s(click, 0.4)
def c7():
    # Softimage (capture 2026-11-16) and the user: a click only highlights the pass
    check(win.view_layer.name == "Default_Pass", "C7 a click on Beauty changed the pass to %s" % win.view_layer.name)
    check(("pass", "Beauty") in ex().picked_nodes, "C7 Beauty not highlighted: %r" % ex().picked_nodes)
s(c7, 0.05)
def rclick():
    if "at" in S:
        x, y = S["at"]
        win.event_simulate(type='RIGHTMOUSE', value='PRESS', x=x, y=y)
        win.event_simulate(type='RIGHTMOUSE', value='RELEASE', x=x, y=y)
s(rclick, 0.5)
def menu_chk():
    check(ex().menu_target.get("node") == ("pass", "Beauty"), "C7 right-click menu target %r" % ex().menu_target)
    out = os.path.abspath(os.path.join(".dev", "shots", "explorer_pass_menu.png"))
    if os.path.isdir(os.path.dirname(out)):
        with bpy.context.temp_override(window=win):
            bpy.ops.screen.screenshot(filepath=out)
    win.event_simulate(type='ESC', value='PRESS', x=10, y=10)
    win.event_simulate(type='ESC', value='RELEASE', x=10, y=10)
s(menu_chk, 0.3)
def set_current():
    item = next(it for it in ex().PASS_MENU if it and it[0] == "Set as Current Pass")
    idname, props = item[1]("Beauty")
    a = S["area"]
    with bpy.context.temp_override(window=win, area=a, region=reg(a)):
        getattr(getattr(bpy.ops, idname.split(".")[0]), idname.split(".")[1])(**props)
    a.tag_redraw()
s(set_current, 0.4)
def c7_current():
    check(win.view_layer.name == "Beauty", "C7 Set as Current Pass: window shows %s" % win.view_layer.name)
    bold = [r.label for r in rows() if r.bold]
    check(bold == ["Beauty"], "C7 bold after Set as Current Pass: %r" % bold)
s(c7_current, 0.05)

# C8 an overridden partition: its Override row opens the page on a click; a middle click doesn't leave a modal pan
def c8_setup():
    P = importlib.import_module(K + ".ops.passes")
    sc = bpy.context.scene
    bg = P.background(sc, "Beauty", "OBJECT")
    P.partition_layer(sc, bg).holdout = True
    S["bg"] = bg.name
    wm.si_explorer_scope = 'PASSES'
    ex()._expanded.update({"pass:Beauty", "pass:Beauty/part:" + bg.name})
    ex().invalidate()
    S["area"].tag_redraw()
s(c8_setup, 0.4)
def c8_at():
    rs = rows()
    i = next((k for k, r in enumerate(rs) if r.key == "pass:Beauty/part:%s/ovr" % S["bg"]), None)
    check(i is not None, "C8 no Override row: %r" % [r.label for r in rs])
    if i is None:
        S.pop("at", None)
        return
    r = reg(S["area"])
    y = r.view2d.view_to_region(0, -(4 + U() * i + U() / 2), clip=False)[1]
    S["at"] = (int(r.x + ex().name_x(rs[i]) + 12), int(r.y + y))
    win.event_simulate(type='MOUSEMOVE', value='NOTHING', x=S["at"][0], y=S["at"][1])
s(c8_at, 0.2)
s(click, 0.5)
def c8_page():
    check(not ex().picked_nodes or ("override", S["bg"]) not in ex().picked_nodes, "C8 the override got picked")
    win.event_simulate(type='ESC', value='PRESS', x=10, y=10)
    win.event_simulate(type='ESC', value='RELEASE', x=10, y=10)
s(c8_page, 0.3)
def c8_middle():
    if "at" not in S:
        return
    x, y = S["at"]
    win.event_simulate(type='MOUSEMOVE', value='NOTHING', x=x, y=y)
    win.event_simulate(type='MIDDLEMOUSE', value='PRESS', x=x, y=y)
    win.event_simulate(type='MIDDLEMOUSE', value='RELEASE', x=x, y=y)
s(c8_middle, 0.3)
def c8_moves():
    if "at" not in S:
        return
    r = reg(S["area"])
    S["view_y"] = r.view2d.region_to_view(0, 0)[1]
    x, y = S["at"]
    for k in range(1, 6):
        win.event_simulate(type='MOUSEMOVE', value='NOTHING', x=x, y=y - 15 * k)
s(c8_moves, 0.3)
def c8_check():
    if "view_y" in S:
        r = reg(S["area"])
        check(abs(r.view2d.region_to_view(0, 0)[1] - S["view_y"]) < 1, "C8 the view pans after a middle click")
s(c8_check, 0.05)
bpy.app.timers.register(run, first_interval=0.8)
