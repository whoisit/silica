# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Alex Doss
# WAIT: 40
"""Explorer drag and drop (spec explorer.drag-drop) with simulated mouse drags in a window: C1 a drag onto an
object parents (the drop row highlighted while dragging), C2 Ctrl pressed during the drag drops a copy, C3 Esc
cancels, C4 a drag onto Scene_Root unparents, C5 right-click opens the object / background menus, C6 a
material row dragged onto an object assigns it. Rows are found by position (explorer.name_x, one row per UI unit)."""
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
        print("SHOT: DRAG", "PASS" if not errors else "FAIL " + " | ".join(errors))
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
def rows():
    with bpy.context.temp_override(window=win, area=S["area"], region=reg(S["area"])):
        return ex().rows()
def at(pred):
    rs = rows()
    i = next((k for k, r in enumerate(rs) if pred(r)), None)
    check(i is not None, "row not found")
    if i is None:
        return (5, 5)
    r = reg(S["area"])
    y = r.view2d.view_to_region(0, -(4 + U() * i + U() / 2), clip=False)[1]
    return int(r.x + ex().name_x(rs[i]) + 12), int(r.y + y)
def ev(t, v, p, **kw): win.event_simulate(type=t, value=v, x=p[0], y=p[1], **kw)
def mv(p, **kw): win.event_simulate(type='MOUSEMOVE', value='NOTHING', x=p[0], y=p[1], **kw)


def drag_start(src, dst):
    """Press on src and move most of the way to dst (the drag runs, not released yet)."""
    def go():
        a, b = at(src), at(dst)
        S["a"], S["b"] = a, b
        mv((5, 5))
        mv(a)
        ev('LEFTMOUSE', 'PRESS', a)
        for k in range(1, 9):
            mv((a[0] + (b[0] - a[0]) * k // 8, a[1] + (b[1] - a[1]) * k // 8))
    return go


def setup():
    for o in list(bpy.data.objects): bpy.data.objects.remove(o)
    sc = bpy.context.scene
    me = bpy.data.meshes.new("dr")
    for n in ("a_par", "b_kid", "c_dup"):
        sc.collection.objects.link(bpy.data.objects.new(n, me))
    bpy.data.objects["b_kid"].location = (2, 1, 0)
    bpy.context.view_layer.update()
    a = views3d()[0]
    S["area"] = a
    with bpy.context.temp_override(window=win, area=a, region=reg(a)):
        bpy.ops.si.explorer_show()
    wm.si_explorer_scope = 'SCENE'
    wm.si_explorer_filter = 'OBJECTS'
    ex()._expanded.update({"scene", "ob:a_par"})
    a.tag_redraw()
s(setup, 0.6)

# C1 drag b_kid onto a_par: highlighted while dragging, parented on release, stays in place
s(drag_start(lambda r: r.obj == "b_kid", lambda r: r.obj == "a_par"), 0.3)
def c1_mid():
    st = ex().drag_state
    tgt = st.get("target")
    check(st.get("kind") == "objects" and tgt is not None and rows()[tgt].obj == "a_par",
          "C1 drag state while dragging: %r" % st)
    S["where"] = bpy.data.objects["b_kid"].matrix_world.translation.copy()
    ev('LEFTMOUSE', 'RELEASE', S["b"])
s(c1_mid, 0.4)
def c1():
    k = bpy.data.objects["b_kid"]
    bpy.context.view_layer.update()
    check(k.parent == bpy.data.objects["a_par"], "C1 b_kid parent %r" % k.parent)
    check((k.matrix_world.translation - S["where"]).length < 1e-4, "C1 b_kid moved when parented")
    check(not ex().drag_state, "C1 drag state left over")
s(c1, 0.1)

# C2 Ctrl pressed during the drag: a copy of c_dup goes under a_par, the original stays
s(drag_start(lambda r: r.obj == "c_dup", lambda r: r.obj == "a_par"), 0.3)
def c2_ctrl():
    ev('LEFT_CTRL', 'PRESS', S["b"])
    mv(S["b"], ctrl=True)
s(c2_ctrl, 0.2)
s(lambda: ev('LEFTMOUSE', 'RELEASE', S["b"], ctrl=True), 0.2)
def c2():
    ev('LEFT_CTRL', 'RELEASE', S["b"])
    kids = sorted(o.name for o in bpy.data.objects["a_par"].children)
    check(any(n.startswith("c_dup.") for n in kids) and bpy.data.objects["c_dup"].parent is None,
          "C2 Ctrl drag: a_par children %r, c_dup parent %r" % (kids, bpy.data.objects["c_dup"].parent))
    check(bpy.data.objects["c_dup"].select_get(), "C2 the original is not selected any more")
s(c2, 0.2)

# C3 Esc cancels
def c3_start():
    S["n"] = len(bpy.data.objects)
    S["parent"] = bpy.data.objects["c_dup"].parent
s(c3_start, 0.05)
s(drag_start(lambda r: r.obj == "c_dup", lambda r: r.obj == "a_par"), 0.3)
s(lambda: ev('ESC', 'PRESS', S["b"]), 0.1)
s(lambda: (ev('ESC', 'RELEASE', S["b"]), ev('LEFTMOUSE', 'RELEASE', S["b"])), 0.3)
s(lambda: check(bpy.data.objects["c_dup"].parent == S["parent"] and len(bpy.data.objects) == S["n"]
                and not ex().drag_state, "C3 Esc did not cancel"), 0.05)

# C4 b_kid onto Scene_Root: unparented
s(drag_start(lambda r: r.obj == "b_kid", lambda r: r.key == "scene"), 0.3)
s(lambda: ev('LEFTMOUSE', 'RELEASE', S["b"]), 0.4)
s(lambda: check(bpy.data.objects["b_kid"].parent is None, "C4 Scene_Root drop: parent %r"
                % bpy.data.objects["b_kid"].parent), 0.05)
# C5 right-click: an object row opens the object menu, empty space the background (View) menu
def rclick(pred):
    def go():
        p = at(pred) if pred else (S["area"].x + 200, S["area"].y + 30)
        S["rc"] = p
        mv(p)
        ev('RIGHTMOUSE', 'PRESS', p)
        ev('RIGHTMOUSE', 'RELEASE', p)
    return go
def esc():
    ev('ESC', 'PRESS', (10, 10))
    ev('ESC', 'RELEASE', (10, 10))
s(rclick(lambda r: r.obj == "a_par"), 0.4)
def c5a():
    check(ex().menu_target.get("node") == ("object", "a_par"), "C5 object menu target %r" % ex().menu_target)
    esc()
s(c5a, 0.3)
s(rclick(None), 0.4)
def c5b():
    check(ex().menu_target.get("node") == ("background", ""), "C5 background menu target %r" % ex().menu_target)
    esc()
s(c5b, 0.3)

# C6 drag an object's material row onto another object: assigned there
def mat_setup():
    red = bpy.data.materials.new("dr_red")
    bpy.data.objects["a_par"].data.materials.append(red)     # the mesh is shared: c_dup has it too
    S["c_mesh"] = bpy.data.meshes.new("dr_c")
    bpy.data.objects["c_dup"].data = S["c_mesh"]
    wm.si_explorer_filter = 'ALL'
    ex()._expanded.add("ob:a_par")
    S["area"].tag_redraw()
s(mat_setup, 0.4)
s(drag_start(lambda r: r.prop == "Material" and r.label == "dr_red", lambda r: r.obj == "c_dup"), 0.3)
s(lambda: ev('LEFTMOUSE', 'RELEASE', S["b"]), 0.4)
def c6():
    slots = [sl.material.name for sl in bpy.data.objects["c_dup"].material_slots if sl.material]
    check(slots == ["dr_red"], "C6 material drop: c_dup materials %r" % slots)
s(c6, 0.05)

def back():
    wm.si_explorer_filter = 'ALL'
s(back, 0.05)
bpy.app.timers.register(run, first_interval=0.8)
