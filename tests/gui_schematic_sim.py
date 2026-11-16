# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Alex Doss
# WAIT: 45
"""Schematic canvas (spec schematic.canvas) in a window: C1 every object a node, C3 Softimage's spacing (82 x 22,
siblings 102 apart, a child level 52 below), C4 A frames every node inside the view, C6 Silica's header, C7 A over
a shader editor stays Blender's, C5 10,000 objects redraw in under 30 ms, C8 mode off turns the pane back into a
3D view. Screenshot: .dev/shots/schematic.png."""
import bpy, importlib, os
K = "bl_ext.user_default.silica"
wm = bpy.context.window_manager
win = wm.windows[0]
from _gui import Run
R = Run("SCHEMATIC", step=0.2)
s, check, errors, S, steps = R.s, R.check, R.errors, R.S, R.steps
def sch(): return importlib.import_module(K + ".ui.schematic")
def views3d(): return sorted((a for a in win.screen.areas if a.type == 'VIEW_3D'), key=lambda a: (-a.y, a.x))
def reg(a): return next(r for r in a.regions if r.type == 'WINDOW')
def ctx(): return bpy.context.temp_override(window=win, area=S["area"], region=reg(S["area"]))
def key(k, area, **mods):
    x, y = area.x + area.width // 2, area.y + area.height // 2
    win.event_simulate(type='MOUSEMOVE', value='NOTHING', x=x, y=y)
    win.event_simulate(type=k, value='PRESS', x=x, y=y, **mods)
    win.event_simulate(type=k, value='RELEASE', x=x, y=y, **mods)


def setup():
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o)
    sc = bpy.context.scene
    def ob(name, data=None, parent=None):
        o = bpy.data.objects.new(name, data)
        sc.collection.objects.link(o)
        o.parent = parent
        return o
    root = ob("sch_root")
    for i in range(3):
        ob("sch_kid%d" % i, None, root)
    ob("sch_box", bpy.data.meshes.new("sch_m"))
    ob("sch_cam", bpy.data.cameras.new("sch_c"))
    ob("sch_key", bpy.data.lights.new("sch_l", 'POINT'))
    box = sc.objects["sch_box"]
    box.constraints.new('COPY_LOCATION').target = root           # C above the node
    hid = ob("sch_hidden", bpy.data.meshes.new("sch_h"))
    hid.hide_set(True)
    a = views3d()[0]
    with bpy.context.temp_override(window=win, area=a, region=reg(a)):
        bpy.ops.si.schematic_show()
    S["area"] = a
    a.tag_redraw()
s(setup, 0.8)

def c1_c3():
    with ctx():
        st = sch().state(bpy.context)
    nodes, pos = st["nodes"], st["pos"]
    check(len(nodes) == len(bpy.context.scene.objects), "C1 nodes %d, objects %d" % (len(nodes), len(bpy.context.scene.objects)))
    uid = {n.name: n.uid for n in nodes.values()}
    r, k0, k1 = pos[uid["sch_root"]], pos[uid["sch_kid0"]], pos[uid["sch_kid1"]]
    check(abs((k0[1] - r[1]) - 52) < 1e-6, "C3 child level %r below the parent" % (k0[1] - r[1]))
    check(abs((k1[0] - k0[0]) - 102) < 1e-6, "C3 siblings %r apart" % (k1[0] - k0[0]))
    n = nodes[uid["sch_box"]]
    check((n.w, n.h) == (82.0, 22.0), "C3 node size %r" % ((n.w, n.h),))
    check(sch().is_hidden(nodes[uid["sch_hidden"]], bpy.context.view_layer), "C2 hidden object not drawn hidden")
    check(nodes[uid["sch_box"]].letters == "C", "C2 letters on the constrained box: %r" % nodes[uid["sch_box"]].letters)
    check(bpy.types.NODE_HT_header.draw is sch().draw_header, "C6 the Node Editor header isn't Silica's")
s(c1_c3, 0.1)

s(lambda: key('A', S["area"]), 0.6)
def c4():
    a = S["area"]
    r = reg(a)
    with ctx():
        st = sch().state(bpy.context)
    v2d = r.view2d
    out = []
    for n in st["nodes"].values():
        x, y = st["pos"][n.uid]
        (ax, ay), (bx, by) = sch().to_region(v2d, x, y), sch().to_region(v2d, x + n.w, y + n.h)
        if not (0 <= ax and bx <= r.width and 0 <= by and ay <= r.height):
            out.append(n.name)
    check(not out, "C4 after A, nodes outside the view: %r" % out[:5])
    shot = os.path.abspath(os.path.join(".dev", "shots", "schematic.png"))
    if os.path.isdir(os.path.dirname(shot)):
        with bpy.context.temp_override(window=win):
            bpy.ops.screen.screenshot(filepath=shot)
s(c4, 0.2)

def c7_setup():
    b = views3d()[0]
    S["shader"] = b
    b.ui_type = 'ShaderNodeTree'
    S["view_before"] = tuple(reg(b).view2d.region_to_view(0, 0))
s(c7_setup, 0.4)
s(lambda: key('A', S["shader"]), 0.4)
def c7():
    after = tuple(reg(S["shader"]).view2d.region_to_view(0, 0))     # the Schematic's A would frame (move the view)
    check(after == S["view_before"], "C7 A over a shader editor moved its view: %r -> %r" % (S["view_before"], after))
    S["shader"].type = 'VIEW_3D'
s(c7, 0.3)

def c5_setup():
    sc = bpy.context.scene
    for i in range(10000):
        sc.collection.objects.link(bpy.data.objects.new("sch_n%05d" % i, None))
    S["area"].tag_redraw()
s(c5_setup, 1.5)
s(lambda: S["area"].tag_redraw(), 1.0)
def c5():
    t = sch().timings
    with ctx():
        bpy.ops.wm.redraw_timer(type='DRAW', iterations=3)
    check(t["draw"] < 0.030, "C5 draw %.1f ms at 10k (want < 30)" % (t["draw"] * 1000))
    print("SHOT: SCHEMATIC timings 10k: build %.0f ms, draw %.1f ms" % (t["build"] * 1000, t["draw"] * 1000))
s(c5, 0.2)

def c8():
    mode = importlib.import_module(K + ".mode")
    mode.exit_mode()
    a = S["area"]
    check(a.type == 'VIEW_3D', "C8 mode off left the pane as %s / %s" % (a.type, a.ui_type))
    mode.enter_mode()
s(c8, 0.5)
R.start(0.8)
