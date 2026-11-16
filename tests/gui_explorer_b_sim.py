# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Alex Doss
# WAIT: 120
"""Explorer spike B (spec explorer.spike-b), simulated input with real Shift / Ctrl. Written before the tests ran.
C3 colours by type, fonts; C4 click / Ctrl / Shift range / Ctrl+Shift; C5 middle button branch pick (+ Shift / Ctrl /
Ctrl+Shift), middle drag scrolls; C6 arrows and NumPad; C7 F2 inline rename (Enter, undo, Esc); C8 hidden mark;
C9 the triangle still expands; C2 10,000 objects: no cap, last row reachable, cached redraw time.
Merged in 2026-11-16 (test audit): spike A's own checks (spec explorer.explorer: the tree, Kinematics opens the
transform settings, the Objects filter, F reveals the selected objects, view menu > Top gives the 3D view back;
its click / Shift / Ctrl checks were C4 here already) and the row pitch at three UI scales.
Rows are found by position: one row per UI unit from the top of the pane (explorer.row_at / name_x)."""
import bpy, importlib, time
K = "bl_ext.user_default.silica"
wm = bpy.context.window_manager
win = wm.windows[0]
from _gui import Run
R = Run("EXPLORER_B", step=0.2)
s, check, errors, S, steps = R.s, R.check, R.errors, R.S, R.steps
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

# ---- from spike A (merged 2026-11-16, test audit): the tree, Kinematics, filter, F --------------------------
def drawn_index(label, depth=None):
    for i, (d, l, _k, _s) in enumerate(ex().drawn):
        if l == label and (depth is None or d == depth):
            return i
    return None
def hover_drawn(label, depth=None):
    """Move onto a drawn row's name (any row, not only objects); the click comes in the next step."""
    i = drawn_index(label, depth)
    check(i is not None, "row %r not drawn" % label)
    S.pop("at", None)
    if i is None:
        return
    d = ex().drawn[i][0]
    r, u = reg(S["area"]), U()
    _x, ry = r.view2d.view_to_region(0, -(u // 2 + 4 + u * i), clip=False)     # follows the pane's scrolling
    S["at"] = (int(r.x + u // 2 + (d + 2) * u + 10), int(r.y + ry))
    mv(S["at"])
def click_drawn(label, depth=None, w=0.3):
    s(lambda: hover_drawn(label, depth), 0.2)
    s(press, w)
def drawn(): return [(d, label) for d, label, _k, _sel in ex().drawn]


def a_setup():
    for o in list(bpy.data.objects): bpy.data.objects.remove(o)
    v = views3d()[0]
    with bpy.context.temp_override(window=win, area=v, region=reg(v)):
        bpy.ops.si.get_primitive(kind="CUBE")
        bpy.ops.si.get_primitive(kind="SPHERE")
    cube, sphere = bpy.data.objects["cube"], bpy.data.objects["sphere"]
    sphere.parent = cube
    cube.modifiers.new("Smooth It", 'SUBSURF')
    cube.modifiers.new("Bones", 'ARMATURE')
    cube.shape_key_add(name="Basis")
    cube.shape_key_add(name="Smile")
    cube.vertex_groups.new(name="grp")
    cube.constraints.new('COPY_LOCATION').name = "Follow"
    cube.data.materials.append(bpy.data.materials.new("xb_red"))
    lamp = bpy.data.objects.new("light", bpy.data.lights.new("light", 'POINT'))
    bpy.context.scene.collection.objects.link(lamp)
    S["prim"] = ex()._stack(cube)[0]
    wm.si_explorer_filter = 'ALL'
    e = ex()._expanded
    e.clear()
    e.update({"scene", "ob:cube", "ob:cube/data", "ob:cube/kine", "ob:cube/data/clusters"}
             | {"ob:cube/data/" + r for r in ("Secondary Shape Modeling", "Animation", "Shape Modeling", "Modeling")})
    ex().invalidate()
    redraw()
s(a_setup, 0.6)

# A-C2 the tree: operator stack, Kinematics with constraints, Visibility, Display, material, children
def a_tree():
    got = drawn()
    prim = S["prim"]
    check(prim is not None, "A-C2 the cube has no live primitive operator")
    want_stack = [(2, "Polygon Mesh"), (3, "Secondary Shape Modeling"), (3, "Animation"), (4, "Bones"),
                  (3, "Shape Modeling"), (4, "Smile"), (3, "Modeling"), (4, "Smooth It"),
                  (3, prim.name if prim else "?"), (3, "Clusters"), (4, "grp")]
    i = got.index((2, "Polygon Mesh")) if (2, "Polygon Mesh") in got else None
    check(i is not None and got[i:i + len(want_stack)] == want_stack,
          "A-C2 operator stack: %r" % (got[i:i + len(want_stack)] if i is not None else got[:20]))
    for want in [(0, "Scene_Root"), (1, "cube"), (2, "Kinematics"), (3, "Follow"), (2, "Visibility"),
                 (2, "Display"), (2, "xb_red"), (2, "sphere"), (1, "light")]:
        check(want in got, "A-C2 row %r missing" % (want,))
    if (1, "cube") in got and (2, "sphere") in got:
        check(got.index((1, "cube")) < got.index((2, "sphere")), "A-C2 child drawn before its parent")
    ex().last_panel = None
s(a_tree, 0.05)

# A-C4 Kinematics opens the object's transform settings
click_drawn("Kinematics", 2, 0.4)
def a_kine():
    check(ex().last_panel == "OBJECT_PT_transform", "A-C4 Kinematics opened %r" % ex().last_panel)
    win.event_simulate(type='ESC', value='PRESS', x=10, y=10)
    win.event_simulate(type='ESC', value='RELEASE', x=10, y=10)
    wm.si_explorer_filter = 'OBJECTS'
    redraw()
s(a_kine, 0.3)

# A-C5 filter Objects hides the property rows
def a_filter():
    labels = [l for _d, l in drawn()]
    check("cube" in labels and "sphere" in labels and "light" in labels, "A-C5 objects missing: %r" % labels)
    left = [l for l in labels if l in ("Kinematics", "Visibility", "Display", "Polygon Mesh", "xb_red")]
    check(not left, "A-C5 filter Objects still shows %r" % left)
    wm.si_explorer_filter = 'ALL'
s(a_filter, 0.05)

# A-C7 F finds the selected objects: a deep one below 40 others is revealed and scrolled to
def a_f_setup():
    scene = bpy.context.scene
    for i in range(40):
        scene.collection.objects.link(bpy.data.objects.new("a%02d" % i, None))
    parent = None
    for name in ("z_deep1", "z_deep2", "z_deep3", "z_target"):
        o = bpy.data.objects.new(name, None)
        scene.collection.objects.link(o)
        o.parent = parent
        parent = o
    bpy.context.view_layer.update()
    for o in bpy.context.view_layer.objects:
        o.select_set(o.name in ("a05", "z_target"))
    ex()._expanded.clear()
    ex()._expanded.add("scene")
    ex().found = None
    redraw()
s(a_f_setup, 0.4)
key('F', w=0.5)
s(lambda: check(ex().found == "a05", "A-C7 first F found %r, want a05 (first selected in tree order)" % ex().found),
  0.05)
key('F', w=0.8)
def a_f_check():
    e = ex()._expanded
    check(e.issuperset({"ob:z_deep1", "ob:z_deep2", "ob:z_deep3"}) and "ob:z_target" not in e,
          "A-C7 parents not opened, or the object itself expanded: %r" % sorted(k for k in e if "z_" in k))
    check(ex().found == "z_target", "A-C7 second F found %r" % ex().found)
    r = reg(S["area"])
    i = drawn_index("z_target", 4)
    check(i is not None, "A-C7 z_target row not drawn")
    if i is not None:
        _x, ry = r.view2d.view_to_region(0, -(U() // 2 + 4 + U() * i), clip=False)
        check(0 < ry < r.height, "A-C7 z_target row not scrolled into view (row %d at %d, pane %d high)"
              % (i, ry, r.height))
s(a_f_check, 0.05)

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
    check(t < 0.3, "C2 building the rows took %.0f ms" % (t * 1000))   # ~4x the worst measured (82 ms, 2026-11-16)
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

# Row pitch (council review 2026-11-16, was gui_explorer_pitch_sim.py): names, boxes and clicks use explorer.unit();
# it must equal the row height of Blender's own layout at any UI scale and line width, or rows drift apart over a
# long list. Measured on the 10,000 rows above, scrolled to the end, at three settings.
prefs = bpy.context.preferences
S["prefs"] = (prefs.view.ui_scale, prefs.view.ui_line_width)
def pitch_apply(scale, lw):
    def go():
        prefs.view.ui_scale = scale
        prefs.view.ui_line_width = lw
        wm.si_explorer_scope = 'SCENE'
        wm.si_explorer_filter = 'OBJECTS'
        ex()._expanded.add("scene")
        redraw()
    return go
def pitch_pan():
    r = reg(S["area"])
    with bpy.context.temp_override(window=win, area=S["area"], region=r):
        for _ in range(60):
            bpy.ops.view2d.pan(deltax=0, deltay=-100000)
    redraw()
def pitch_measure(scale, lw):
    def go():
        _x, bot = reg(S["area"]).view2d.region_to_view(0, 0)
        n = len(rows())
        true_u = (-bot - 4) / n
        check(abs(true_u - U()) <= 0.01, "pitch at scale %s %s: layout row %.3f, unit() %.3f" % (scale, lw, true_u, U()))
    return go
for sc_, lw in [(1.0, 'AUTO'), (1.5, 'AUTO'), (1.25, 'THICK')]:
    s(pitch_apply(sc_, lw), 1.0)
    s(pitch_pan, 0.6)
    s(pitch_pan, 0.6)
    s(pitch_measure(sc_, lw), 0.1)
def pitch_restore():
    prefs.view.ui_scale, prefs.view.ui_line_width = S["prefs"]
    wm.si_explorer_filter = 'ALL'
    redraw()
s(pitch_restore, 0.5)

# A-C1 view menu > Top: the Explorer pane is a 3D view again
def back():
    a = S["area"]
    with bpy.context.temp_override(window=win, area=a, region=reg(a)):
        bpy.ops.si.view_set(view='TOP')
    check(a.type == 'VIEW_3D', "A-C1 view menu > Top left the pane as %s" % a.type)
s(back, 0.3)
R.start(0.8)
