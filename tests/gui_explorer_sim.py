# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Alex Doss
# WAIT: 30
"""Explorer spike A (spec explorer.explorer), simulated input. Written before the code was finished.
C1 view menu > Explorer turns a pane into the Explorer, view menu > Top back; C2 the tree (hierarchy, primitive >
regions with operators > live primitive > Clusters, Kinematics with constraints, Visibility, Display, material,
children); C3 click / Shift / Ctrl selection on the rows; C4 Kinematics opens the object's transform settings;
C5 filter Objects hides property nodes; C6 selected rows are highlighted; C7 F over the Explorer reveals the next
selected object (parents opened, row scrolled into view), F again the next one.
Rows are clicked by position: one row per UI unit from the top of the pane."""
import bpy, importlib
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
        print("SHOT: EXPLORER", "PASS" if not errors else "FAIL " + " | ".join(errors))
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
def U(): return round(20 * bpy.context.preferences.system.ui_scale)
def rows(): return [(d, label) for d, label, _k, _sel in ex().drawn]
def row_index(label, depth=None):
    for i, (d, l, _k, _s) in enumerate(ex().drawn):
        if l == label and (depth is None or d == depth):
            return i
    return None
def hover_row(label, depth=None):
    """Move onto the row's name (after its indent, triangle and icon); the click comes in the next step."""
    i = row_index(label, depth)
    check(i is not None, "row %r not drawn" % label)
    S.pop("at", None)
    if i is None:
        return
    d = ex().drawn[i][0]
    r = reg(S["area"])
    u = U()
    _x, ry = r.view2d.view_to_region(0, -(u // 2 + 4 + u * i), clip=False)     # follows the pane's scrolling
    S["at"] = (r.x + u // 2 + (d + 2) * u + 10, r.y + ry)
    win.event_simulate(type='MOUSEMOVE', value='NOTHING', x=5, y=5)
    win.event_simulate(type='MOUSEMOVE', value='NOTHING', x=S["at"][0], y=S["at"][1])
def press():
    if "at" in S:
        x, y = S["at"]
        win.event_simulate(type='LEFTMOUSE', value='PRESS', x=x, y=y)
        win.event_simulate(type='LEFTMOUSE', value='RELEASE', x=x, y=y)
def click_row(label, depth=None, w=0.3):
    s(lambda: hover_row(label, depth), 0.2)
    s(press, w)
def op_click(name, **kw):
    """Shift / Ctrl clicks: Blender doesn't pass simulated modifier keys to UI buttons, so these call the row's
    operator with the flags a Shift / Ctrl click sets."""
    a = S["area"]
    with bpy.context.temp_override(window=win, area=a, region=reg(a)):
        bpy.ops.si.explorer_click(obj=name, **kw)
def selected(): return sorted(o.name for o in bpy.context.selected_objects)
def redraw():
    S["area"].tag_redraw()


def setup():
    for o in list(bpy.data.objects): bpy.data.objects.remove(o)
    v = views3d()[1]
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
    cube.data.materials.append(bpy.data.materials.new("red"))
    lamp = bpy.data.objects.new("light", bpy.data.lights.new("light", 'POINT'))
    bpy.context.scene.collection.objects.link(lamp)
    S["prim"] = ex()._stack(cube)[0]
    # C1 view menu > Explorer (the menu item runs si.explorer_show in the pane)
    a = views3d()[0]
    S["area"] = a
    with bpy.context.temp_override(window=win, area=a, region=reg(a)):
        bpy.ops.si.explorer_show()
    check(a.type == 'PROPERTIES' and docks().space_role(a.spaces.active) == "EXPLORER",
          "C1 view menu > Explorer did not turn the pane into the Explorer (%s)" % a.type)
    e = ex()._expanded
    e.update({"scene", "ob:cube", "ob:cube/data", "ob:cube/kine", "ob:cube/data/clusters"}
             | {"ob:cube/data/" + r for r in ("Secondary Shape Modeling", "Animation", "Shape Modeling", "Modeling")})
    redraw()
s(setup, 0.6)

# C2 the tree
def c2():
    got = rows()
    prim = S["prim"]
    check(prim is not None, "C2 the cube has no live primitive operator")
    want_stack = [(2, "Polygon Mesh"), (3, "Secondary Shape Modeling"), (3, "Animation"), (4, "Bones"),
                  (3, "Shape Modeling"), (4, "Smile"), (3, "Modeling"), (4, "Smooth It"),
                  (3, prim.name if prim else "?"), (3, "Clusters"), (4, "grp")]
    i = got.index((2, "Polygon Mesh")) if (2, "Polygon Mesh") in got else None
    check(i is not None and got[i:i + len(want_stack)] == want_stack,
          "C2 operator stack: %r" % (got[i:i + len(want_stack)] if i is not None else got[:20]))
    for want in [(0, "Scene_Root"), (1, "cube"), (2, "Kinematics"), (3, "Follow"), (2, "Visibility"),
                 (2, "Display"), (2, "red"), (2, "sphere"), (1, "light")]:
        check(want in got, "C2 row %r missing" % (want,))
    if (1, "cube") in got and (2, "sphere") in got:
        check(got.index((1, "cube")) < got.index((2, "sphere")), "C2 child drawn before its parent")
s(c2, 0.05)

# C3 click / Shift / Ctrl, C6 highlight (cube collapsed so every object row fits in the pane)
def collapse():
    ex()._expanded.discard("ob:cube")
    redraw()
s(collapse, 0.3)
click_row("light", 1)
s(lambda: check(selected() == ["light"] and bpy.context.view_layer.objects.active.name == "light",
                "C3 click: selection %r" % selected()), 0.05)
click_row("cube", 1)
s(lambda: check(selected() == ["cube"], "C3 click after click: selection %r" % selected()), 0.05)
s(lambda: op_click("light", extend=True), 0.2)
s(lambda: check(selected() == ["cube", "light"], "C3 Shift+click: selection %r" % selected()), 0.05)
s(lambda: op_click("light", toggle=True), 0.2)
s(lambda: check(selected() == ["cube"], "C3 Ctrl+click: selection %r" % selected()), 0.05)
def c6():
    sel = {l: on for d, l, _k, on in ex().drawn if d == 1}
    check(sel.get("cube") is True and sel.get("light") is False, "C6 highlight: %r" % sel)
s(c6, 0.05)

# C4 Kinematics opens the object's transform settings
def expand_cube():
    ex()._expanded.add("ob:cube")
    redraw()
s(expand_cube, 0.3)
def c4():
    ex().last_panel = None
s(c4, 0.05)
click_row("Kinematics", 2, 0.4)
def c4_check():
    check(ex().last_panel == "OBJECT_PT_transform", "C4 Kinematics opened %r" % ex().last_panel)
    win.event_simulate(type='ESC', value='PRESS', x=10, y=10)
    win.event_simulate(type='ESC', value='RELEASE', x=10, y=10)
s(c4_check, 0.3)

# C5 filter Objects
def c5():
    wm.si_explorer_filter = 'OBJECTS'
    redraw()
s(c5, 0.3)
def c5_check():
    labels = [l for _d, l in rows()]
    check("cube" in labels and "sphere" in labels and "light" in labels, "C5 objects missing: %r" % labels)
    left = [l for l in labels if l in ("Kinematics", "Visibility", "Display", "Polygon Mesh", "red")]
    check(not left, "C5 filter Objects still shows %r" % left)
    wm.si_explorer_filter = 'ALL'
s(c5_check, 0.05)

# C7 F finds the selected objects: a deep one below 40 others is revealed and scrolled to
def c7_setup():
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
s(c7_setup, 0.4)
def f_key():
    a = S["area"]
    x, y = a.x + a.width // 2, a.y + a.height // 2
    win.event_simulate(type='MOUSEMOVE', value='NOTHING', x=x, y=y)
    win.event_simulate(type='F', value='PRESS', x=x, y=y)
    win.event_simulate(type='F', value='RELEASE', x=x, y=y)
s(f_key, 0.5)
s(lambda: check(ex().found == "a05", "C7 first F found %r, want a05 (first selected in tree order)" % ex().found), 0.05)
s(f_key, 0.8)
def c7_check():
    e = ex()._expanded
    check(e.issuperset({"ob:z_deep1", "ob:z_deep2", "ob:z_deep3"}) and "ob:z_target" not in e,
          "C7 parents not opened, or the object itself expanded: %r" % sorted(k for k in e if "z_" in k))
    check(ex().found == "z_target", "C7 second F found %r" % ex().found)
    r = reg(S["area"])
    i = row_index("z_target", 4)
    check(i is not None, "C7 z_target row not drawn")
    if i is not None:
        _x, ry = r.view2d.view_to_region(0, -(U() // 2 + 4 + U() * i), clip=False)
        check(0 < ry < r.height, "C7 z_target row not scrolled into view (row %d at %d, pane %d high)" % (i, ry, r.height))
s(c7_check, 0.05)
click_row("z_target", 4)          # the row is where it is drawn: clicking it selects only z_target
s(lambda: check(selected() == ["z_target"], "C7 click on the revealed row: selection %r" % selected()), 0.05)
s(f_key, 0.5)
s(lambda: check(ex().found == "z_target", "C7 F with one selected object found %r" % ex().found), 0.05)

# C1 view menu > Top: back to a 3D view
def back():
    a = S["area"]
    with bpy.context.temp_override(window=win, area=a, region=reg(a)):
        bpy.ops.si.view_set(view='TOP')
    check(a.type == 'VIEW_3D', "C1 view menu > Top left the pane as %s" % a.type)
s(back, 0.3)
bpy.app.timers.register(run, first_interval=0.8)
