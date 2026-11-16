# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Alex Doss
# WAIT: 60
"""Explorer spike B (spec explorer.spike-b), simulated input with real Shift / Ctrl. Written before the tests ran.
C3 colours by type, fonts; C4 click / Ctrl / Shift range / Ctrl+Shift; C5 middle button branch pick (+ Shift / Ctrl /
Ctrl+Shift), middle drag scrolls; C6 arrows and NumPad; C7 F2 inline rename (Enter, undo, Esc); C8 hidden mark;
C9 the triangle still expands; C2 10,000 objects: no cap, last row reachable, cached redraw time.
Rows are found by position: one row per UI unit from the top of the pane (explorer.row_at / name_x)."""
import bpy, importlib, time
K = "bl_ext.user_default.silica"
wm = bpy.context.window_manager
win = wm.windows[0]
errors, steps, S = [], [], {}
def s(fn, w=0.2): steps.append((fn, w))
def check(c, m):
    if not c: errors.append(m)
def run():
    if not steps:
        wm.si_explorer_filter = 'ALL'
        print("SHOT: EXPLORER_B", "PASS" if not errors else "FAIL " + " | ".join(errors))
        return None
    fn, w = steps.pop(0)
    try: fn()
    except Exception:
        import traceback; tb = traceback.format_exc().strip().splitlines(); errors.append(" / ".join(tb[-3:]))
    return w
def ex(): return importlib.import_module(K + ".ui.explorer")
def docks(): return importlib.import_module(K + ".ui.docks")
def views3d(): return sorted((a for a in win.screen.areas if a.type == 'VIEW_3D'), key=lambda a: (-a.y, a.x))
def reg(a): return next(r for r in a.regions if r.type == 'WINDOW')
def U(): return ex().unit()        # Blender's widget unit (measured: not 20 * ui_scale)
def selected(): return sorted(o.name for o in bpy.context.view_layer.objects if o.select_get())
def active(): return getattr(bpy.context.view_layer.objects.active, "name", None)
def redraw(): S["area"].tag_redraw()
def rows():
    with bpy.context.temp_override(window=win, area=S["area"], region=reg(S["area"])):
        return ex().rows()
def row_of(name):
    return next((i for i, r in enumerate(rows()) if r.is_object and r.obj == name), None)
def point(name, part="name"):
    """Window x, y on an object row's name (or its triangle); None if the row isn't drawn."""
    i = row_of(name)
    check(i is not None, "row %r not in the tree" % name)
    if i is None:
        return None
    r, row, u = reg(S["area"]), rows()[i], U()
    y = r.view2d.view_to_region(0, -(4 + u * i + u / 2), clip=False)[1]
    x = ex().name_x(row) + 12 if part == "name" else u * 0.5 + row.depth * u + u / 2
    return int(r.x + x), int(r.y + y)
def mv(p):
    win.event_simulate(type='MOUSEMOVE', value='NOTHING', x=5, y=5)
    win.event_simulate(type='MOUSEMOVE', value='NOTHING', x=p[0], y=p[1])
def hover(name, part="name"):
    ex()._scroll_to(win, S["area"], name)               # rows below the pane: scroll them into view first
    S["at"] = point(name, part)
    if S["at"]:
        mv(S["at"])
def press(button='LEFTMOUSE', **mods):
    if S.get("at"):
        x, y = S["at"]
        win.event_simulate(type=button, value='PRESS', x=x, y=y, **mods)
        win.event_simulate(type=button, value='RELEASE', x=x, y=y, **mods)
def click(name, button='LEFTMOUSE', part="name", w=0.25, **mods):
    s(lambda: hover(name, part), 0.15)
    s(lambda: press(button, **mods), w)
def key(k, unicode=None, w=0.25, **mods):
    def go():
        a = S["area"]
        x, y = a.x + a.width - 40, a.y + 40          # over the pane, right of the names
        win.event_simulate(type='MOUSEMOVE', value='NOTHING', x=x, y=y)
        kw = {"unicode": unicode} if unicode else {}
        win.event_simulate(type=k, value='PRESS', x=x, y=y, **kw, **mods)
        win.event_simulate(type=k, value='RELEASE', x=x, y=y, **mods)
    s(go, w)
def expand(*keys, collapse=()):
    def go():
        ex()._expanded.update(keys)
        for k in collapse:
            ex()._expanded.discard(k)
        redraw()
    s(go, 0.3)


def setup():
    for o in list(bpy.data.objects): bpy.data.objects.remove(o)
    sc = bpy.context.scene
    def new(name, data=None, parent=None):
        o = bpy.data.objects.new(name, data)
        sc.collection.objects.link(o)
        o.parent = parent
        return o
    me = bpy.data.meshes.new("xb")
    new("a_cam", bpy.data.cameras.new("xb_cam"))
    new("b_lamp", bpy.data.lights.new("xb_lamp", 'POINT'))
    inst = new("c_inst")
    inst.instance_type = 'COLLECTION'
    inst.instance_collection = bpy.data.collections.new("xb_model")
    par = new("d_par")
    k1 = new("d_kid1", me, par)
    new("d_kid2", me, par)
    new("d_kid1_g", me, k1)
    for n in ("e_m1", "e_m2", "e_m3"):
        new(n, me)
    for n in range(60):                                   # enough rows to scroll
        new("z_%02d" % n)
    bpy.context.view_layer.update()
    a = views3d()[0]
    S["area"] = a
    with bpy.context.temp_override(window=win, area=a, region=reg(a)):
        bpy.ops.si.explorer_show()
    check(a.type == 'PROPERTIES' and docks().space_role(a.spaces.active) == "EXPLORER", "explorer pane not made")
    ex()._expanded.clear()
    ex()._expanded.update({"scene", "ob:e_m1"})
    wm.si_explorer_filter = 'ALL'
    redraw()
s(setup, 0.6)

# C3 colours and fonts
def c3():
    rs = rows()
    col = {r.label: r.color for r in rs if r.depth <= 1}
    want = {"Scene_Root": "model", "a_cam": "camera", "b_lamp": "light", "c_inst": "model", "e_m1": None}
    for n, c in want.items():
        check(col.get(n, "?") == c, "C3 %s colour %r, want %r" % (n, col.get(n, "?"), c))
    check(ex().font("italic") > 0 and ex().font("bold") > 0, "C3 fonts: italic %r bold %r"
          % (ex().font("italic"), ex().font("bold")))
s(c3, 0.05)

# C4 click, Ctrl, Shift range (skips e_m1's property rows and collapsed d_par's children), Ctrl+Shift
click("e_m1")
s(lambda: check(selected() == ["e_m1"] and active() == "e_m1", "C4 click: %r active %r" % (selected(), active())), 0.05)
click("e_m3", ctrl=True)
s(lambda: check(selected() == ["e_m1", "e_m3"], "C4 Ctrl+click adds: %r" % selected()), 0.05)
click("e_m1", ctrl=True)
s(lambda: check(selected() == ["e_m3"], "C4 Ctrl+click toggles off: %r" % selected()), 0.05)
click("b_lamp")
click("e_m2", shift=True)
s(lambda: check(selected() == ["b_lamp", "c_inst", "d_par", "e_m1", "e_m2"],
                "C4 Shift range b_lamp..e_m2: %r" % selected()), 0.05)
click("c_inst", ctrl=True, shift=True)
s(lambda: check(selected() == ["b_lamp", "d_par", "e_m1", "e_m2"], "C4 Ctrl+Shift deselects: %r" % selected()), 0.05)

# C5 middle button: branch pick, grey boxes, Shift / Ctrl / Ctrl+Shift, drag scrolls
expand("ob:d_par", "ob:d_kid1")
click("d_par", 'MIDDLEMOUSE')
def c5():
    want = ["d_kid1", "d_kid1_g", "d_kid2", "d_par"]
    check(selected() == want and active() == "d_par", "C5 branch pick: %r active %r" % (selected(), active()))
    rs = rows()
    box = {r.obj: ex().row_box(r) for r in rs if r.is_object and r.obj.startswith("d_")}
    check(box == {"d_par": "selected", "d_kid1": "branch", "d_kid2": "branch", "d_kid1_g": "branch"},
          "C5 boxes: %r" % box)
s(c5, 0.05)
click("e_m1", 'MIDDLEMOUSE', shift=True)
s(lambda: check(selected() == ["d_kid1", "d_kid1_g", "d_kid2", "d_par", "e_m1"], "C5 Shift+middle adds: %r"
                % selected()), 0.05)
click("d_par", 'MIDDLEMOUSE', ctrl=True)
s(lambda: check(selected() == ["e_m1"], "C5 Ctrl+middle toggles the branch off: %r" % selected()), 0.05)
click("d_par", 'MIDDLEMOUSE', ctrl=True)
click("d_kid1", 'MIDDLEMOUSE', ctrl=True, shift=True)
s(lambda: check(selected() == ["d_kid2", "d_par", "e_m1"], "C5 Ctrl+Shift+middle deselects a branch: %r"
                % selected()), 0.05)
def mdrag():
    S["sel"] = selected()
    r = reg(S["area"])
    S["top"] = r.view2d.region_to_view(0, r.height)[1]
    p = point("d_par")
    win.event_simulate(type='MOUSEMOVE', value='NOTHING', x=p[0], y=p[1])
    win.event_simulate(type='MIDDLEMOUSE', value='PRESS', x=p[0], y=p[1])
    for k in range(1, 9):
        win.event_simulate(type='MOUSEMOVE', value='NOTHING', x=p[0], y=p[1] + 15 * k)
    win.event_simulate(type='MIDDLEMOUSE', value='RELEASE', x=p[0], y=p[1] + 120)
s(mdrag, 0.4)
def mdrag_chk():
    r = reg(S["area"])
    top = r.view2d.region_to_view(0, r.height)[1]
    check(abs(top - S["top"]) > 50, "C5 middle drag did not scroll: view top %.0f -> %.0f" % (S["top"], top))
    check(selected() == S["sel"], "C5 middle drag changed the selection: %r" % selected())
    with bpy.context.temp_override(window=win, area=S["area"], region=r):
        bpy.ops.view2d.scroll_up(page=True)
        bpy.ops.view2d.scroll_up(page=True)
        bpy.ops.view2d.scroll_up(page=True)
s(mdrag_chk, 0.3)

# C6 keys on the active object
click("e_m1")
key('DOWN_ARROW')
s(lambda: check(selected() == ["e_m2"] and active() == "e_m2", "C6 Down: %r" % selected()), 0.05)
key('UP_ARROW')
s(lambda: check(selected() == ["e_m1"], "C6 Up: %r" % selected()), 0.05)
expand(collapse=("ob:d_par", "ob:d_kid1"))
click("d_par")
key('RIGHT_ARROW')
s(lambda: check("ob:d_par" in ex()._expanded, "C6 Right did not expand d_par"), 0.05)
key('RIGHT_ARROW')
s(lambda: check(selected() == ["d_kid1"], "C6 Right on an open node: %r, want its first child" % selected()), 0.05)
key('LEFT_ARROW')
s(lambda: check(selected() == ["d_par"], "C6 Left on a closed node: %r, want its parent" % selected()), 0.05)
key('LEFT_ARROW')
s(lambda: check("ob:d_par" not in ex()._expanded, "C6 Left did not collapse d_par"), 0.05)
key('NUMPAD_ASTERIX')
s(lambda: check({"ob:d_par", "ob:d_kid1", "ob:d_kid2", "ob:d_kid1_g"} <= ex()._expanded,
                "C6 NumPad * did not expand everything below"), 0.05)
key('NUMPAD_MINUS')
s(lambda: check("ob:d_par" not in ex()._expanded, "C6 NumPad - did not collapse"), 0.05)
key('NUMPAD_PLUS')
s(lambda: check("ob:d_par" in ex()._expanded, "C6 NumPad + did not expand"), 0.05)

# C7 F2 rename: typed text + Enter, undo, Esc
click("e_m2")
key('F2', w=0.3)
s(lambda: check(ex().renaming.get("obj") == "e_m2", "C7 F2 did not start renaming: %r" % ex().renaming), 0.05)
for ch in "hero":
    key(ch.upper(), unicode=ch, w=0.05)
key('RET', w=0.3)
s(lambda: check("hero" in bpy.data.objects and "e_m2" not in bpy.data.objects and not ex().renaming,
                "C7 Enter: names %r" % sorted(o.name for o in bpy.data.objects if o.name.startswith(("e_", "h")))), 0.05)
key('Z', ctrl=True, w=0.5)
s(lambda: check("e_m2" in bpy.data.objects and "hero" not in bpy.data.objects, "C7 undo did not bring e_m2 back"), 0.05)
click("e_m3")
key('F2', w=0.3)
key('X', unicode="x", w=0.05)
key('ESC', w=0.3)
s(lambda: check("e_m3" in bpy.data.objects and "x" not in bpy.data.objects and not ex().renaming,
                "C7 Esc renamed anyway"), 0.05)

# C8 hidden mark (drawn; H mark seen in the screenshot) and dimmed name
def c8():
    o = bpy.data.objects["e_m3"]
    o.hide_set(True)
    o.hide_render = True
    redraw()
s(c8, 0.3)
def c8_chk():
    vl = bpy.context.view_layer
    check(ex().hidden_badge(bpy.data.objects["e_m3"], vl) == "full", "C8 badge")
    check(ex().timings["overlay"] > 0, "C8 the overlay did not draw")
    import os
    shots = os.path.join(".dev", "shots")          # the dev folder when run from the repo (kept after Blender quits)
    out = os.path.abspath(os.path.join(shots if os.path.isdir(shots) else bpy.app.tempdir, "explorer_b_c8.png"))
    with bpy.context.temp_override(window=win):
        bpy.ops.screen.screenshot(filepath=out)
    print("SHOT: EXPLORER_B screenshot", out)
s(c8_chk, 0.05)

# C9 the triangle still expands (and collapses)
expand(collapse=("ob:d_par",))
click("d_par", part="tri", w=0.3)
s(lambda: check("ob:d_par" in ex()._expanded, "C9 triangle click did not expand d_par"), 0.05)

# C2 10,000 objects: every row, last row reachable, cached redraw time
def big():
    sc = bpy.context.scene
    for n in range(10000):
        o = bpy.data.objects.new("zz_%05d" % n, None)
        sc.collection.objects.link(o)
    bpy.context.view_layer.update()
    ex().invalidate()
    wm.si_explorer_filter = 'OBJECTS'
    redraw()
s(big, 1.5)
def big_build():
    t = ex().timings["build"]
    n = len(rows())
    check(n >= 10000, "C2 rows %d" % n)
    check(t < 0.1, "C2 building the rows took %.0f ms" % (t * 1000))
    S["build_ms"] = t * 1000
    redraw()
s(big_build, 0.4)
def big_scroll():
    a = S["area"]
    ex()._scroll_to(win, a, "zz_09999")
    redraw()
s(big_scroll, 0.5)
def big_chk():
    tm = ex().timings
    ms = (tm["panel"] + tm["overlay"]) * 1000
    check(ms < 10, "C2 cached redraw %.1f ms" % ms)
    r = reg(S["area"])
    i = row_of("zz_09999")
    y = r.view2d.view_to_region(0, -(4 + U() * i + U() / 2), clip=False)[1]
    check(0 < y < r.height, "C2 last row %d not in view (y %d)" % (i, y))
    print("SHOT: EXPLORER_B timings build %.1f ms, cached panel %.2f ms, overlay %.2f ms"
          % (S.get("build_ms", -1), tm["panel"] * 1000, tm["overlay"] * 1000))
s(big_chk, 0.05)
bpy.app.timers.register(run, first_interval=0.8)
