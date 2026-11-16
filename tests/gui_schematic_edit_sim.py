# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Alex Doss
# WAIT: 30
"""Schematic editing (spec schematic.editing) with simulated input: C1 Alt+drag parents (world position kept),
C2 Pick and Move (M) moves the selection with the dragged node and keeps the positions on the objects
through a rearrange, C3 Reset All User
Positions, C4 N collapses / expands, C5 Alt+right-click opens the Schematic node menu."""
import bpy, importlib
from mathutils import Vector
K = "bl_ext.user_default.silica"
wm = bpy.context.window_manager
win = wm.windows[0]
from _gui import Run
R = Run("SCHEMATIC_EDIT", step=0.2)
s, check, errors, S, steps = R.s, R.check, R.errors, R.S, R.steps
def sch(): return importlib.import_module(K + ".ui.schematic")
def ex(): return importlib.import_module(K + ".ui.explorer")
def views3d(): return sorted((a for a in win.screen.areas if a.type == 'VIEW_3D'), key=lambda a: (-a.y, a.x))
def reg(a): return next(r for r in a.regions if r.type == 'WINDOW')
def ctx(): return bpy.context.temp_override(window=win, area=S["area"], region=reg(S["area"]))
def st():
    with ctx():
        return sch().state(bpy.context)
def node(name):
    t = st()
    return next(n for n in t["nodes"].values() if n.name == name), t
def at(name):
    n, t = node(name)
    x, y = t["pos"][n.uid]
    r = reg(S["area"])
    rx, ry = sch().to_region(r.view2d, x + n.w / 2, y + n.h / 2)
    return int(r.x + rx), int(r.y + ry)
def drag(a, b, **mods):
    win.event_simulate(type='MOUSEMOVE', value='NOTHING', x=a[0], y=a[1], **mods)
    win.event_simulate(type='LEFTMOUSE', value='PRESS', x=a[0], y=a[1], **mods)
    for k in range(1, 9):
        win.event_simulate(type='MOUSEMOVE', value='NOTHING', x=a[0] + (b[0] - a[0]) * k // 8,
                           y=a[1] + (b[1] - a[1]) * k // 8, **mods)
    win.event_simulate(type='LEFTMOUSE', value='RELEASE', x=b[0], y=b[1], **mods)
def key(k, p, **mods):
    win.event_simulate(type='MOUSEMOVE', value='NOTHING', x=p[0], y=p[1])
    win.event_simulate(type=k, value='PRESS', x=p[0], y=p[1], **mods)
    win.event_simulate(type=k, value='RELEASE', x=p[0], y=p[1], **mods)


def setup():
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o)
    sc = bpy.context.scene
    def ob(name, parent=None, loc=(0, 0, 0)):
        o = bpy.data.objects.new(name, None)
        sc.collection.objects.link(o)
        o.parent = parent
        o.location = loc
        return o
    p = ob("se_parent", loc=(5, 0, 0))
    ob("se_kid", p)
    ob("se_mover", loc=(1, 2, 3))
    ob("se_target", loc=(-4, 0, 0))
    a = views3d()[0]
    with bpy.context.temp_override(window=win, area=a, region=reg(a)):
        bpy.ops.si.schematic_show()
    S["area"] = a
    bpy.context.view_layer.update()
s(setup, 0.8)
def frame():
    with ctx():
        bpy.ops.si.schematic_frame(selected=False)
s(frame, 0.5)

def c1():
    S["world"] = bpy.data.objects["se_mover"].matrix_world.translation.copy()
    drag(at("se_mover"), at("se_target"), alt=True)
s(c1, 0.5)
def c1_check():
    o = bpy.data.objects["se_mover"]
    bpy.context.view_layer.update()
    check(o.parent == bpy.data.objects["se_target"], "C1 Alt+drag: parent %r" % o.parent)
    check((o.matrix_world.translation - S["world"]).length < 1e-4, "C1 the object moved in the world")
s(c1_check, 0.1)

def c2():
    with ctx():                                    # a selection of two: dragging one moves both (user report)
        ex().select(bpy.context, "se_parent", 'SET')
        ex().select(bpy.context, "se_target", 'ADD')
    p = at("se_parent")
    key('M', p)
    n, t = node("se_parent")
    S["before"] = t["pos"][n.uid]
    m, t = node("se_target")
    S["before_t"] = t["pos"][m.uid]
    drag(p, (p[0] + 60, p[1] - 40))
    key('SPACE', p)
s(c2, 0.5)
def c2_check():
    o = bpy.data.objects["se_parent"]
    check("si_schematic_pos" in o, "C2 no saved position on the moved object")
    n, t = node("se_parent")
    check(t["pos"][n.uid] != S["before"], "C2 the node didn't move")
    m, t = node("se_target")
    d1 = (t["pos"][n.uid][0] - S["before"][0], t["pos"][n.uid][1] - S["before"][1])
    d2 = (t["pos"][m.uid][0] - S["before_t"][0], t["pos"][m.uid][1] - S["before_t"][1])
    check(abs(d1[0] - d2[0]) < 1e-3 and abs(d1[1] - d2[1]) < 1e-3 and "si_schematic_pos" in bpy.data.objects["se_target"],
          "C2 the other selected node didn't move with it: %r vs %r" % (d1, d2))
    with ctx():
        bpy.ops.si.schematic_rearrange()
    n, t = node("se_parent")
    check(tuple(t["pos"][n.uid]) == tuple(o["si_schematic_pos"]), "C2 the moved node lost its place in a rearrange")
s(c2_check, 0.2)

def c3():
    with ctx():
        bpy.ops.si.schematic_edit(action='RESET_ALL')
    check("si_schematic_pos" not in bpy.data.objects["se_parent"], "C3 Reset All left the position")
s(c3, 0.3)

def c4():
    with ctx():
        ex().select(bpy.context, "se_parent", 'SET')
    key('N', at("se_target"))
s(c4, 0.4)
def c4_check():
    n, t = node("se_kid")
    p, _t = node("se_parent")
    check(n.uid in t["hidden"] and p.uid in t["collapsed"], "C4 N didn't collapse se_parent")
    key('N', at("se_target"))
s(c4_check, 0.4)
def c4_back():
    n, t = node("se_kid")
    check(n.uid not in t["hidden"], "C4 N again didn't expand")
s(c4_back, 0.1)

# C6 (user report): a branch rearranged with Shift+R is tidied, even where nodes were moved by hand
def c6_move():
    with ctx():
        ex().select(bpy.context, "se_kid", 'SET')
    p = at("se_kid")
    key('M', p)
    drag(p, (p[0] + 90, p[1] + 50))
    key('SPACE', p)
s(c6_move, 0.5)
def c6_rearrange():
    check("si_schematic_pos" in bpy.data.objects["se_kid"], "C6 setup: se_kid wasn't moved by hand")
    with ctx():
        ex().select(bpy.context, "se_parent", 'SET', branch=True)
    key('R', at("se_target"), shift=True)
s(c6_rearrange, 0.5)
def c6_check():
    k, t = node("se_kid")
    p, _t = node("se_parent")
    kx, ky = t["pos"][k.uid]
    px, py = t["pos"][p.uid]
    check("si_schematic_pos" not in bpy.data.objects["se_kid"], "C6 the hand-moved position is still there")
    check(abs((ky - py) - 52) < 1e-3 and abs((kx + k.w / 2) - (px + p.w / 2)) < 1e-3,
          "C6 se_kid not back under se_parent after Shift+R: kid %r parent %r" % ((kx, ky), (px, py)))
s(c6_check, 0.1)

s(lambda: key('RIGHTMOUSE', at("se_target"), alt=True), 0.5)
def c5():
    check(ex().menu_target.get("node") == ("object", "se_target"), "C5 node menu target %r" % ex().menu_target)
    win.event_simulate(type='ESC', value='PRESS', x=10, y=10)
    win.event_simulate(type='ESC', value='RELEASE', x=10, y=10)
s(c5, 0.3)
R.start(0.8)
