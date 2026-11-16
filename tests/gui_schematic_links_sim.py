# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Alex Doss
# WAIT: 45
"""Schematic links (milestone 4) in a window, once ui/schematic_linkdraw.py is wired into the canvas: L1 selecting
the constrained node draws its link ("Pos"), L2 a click on the link selects its owner and picks the link, L3 Delete
removes the constraint (no object deleted), L4 Show toggles, L5 10,000 nodes with ~300 links: links add under
3 ms (selected only) / 15 ms (all kinds, home view)."""
import bpy, importlib
K = "bl_ext.user_default.silica"
wm = bpy.context.window_manager
win = wm.windows[0]
from _gui import Run
R = Run("SCHEMATIC_LINKS", step=0.2)
s, check, errors, S, steps = R.s, R.check, R.errors, R.S, R.steps
def sch(): return importlib.import_module(K + ".ui.schematic")
def ld(): return importlib.import_module(K + ".ui.schematic_linkdraw")
def views3d(): return sorted((a for a in win.screen.areas if a.type == 'VIEW_3D'), key=lambda a: (-a.y, a.x))
def reg(a): return next(r for r in a.regions if r.type == 'WINDOW')
def ctx(): return bpy.context.temp_override(window=win, area=S["area"], region=reg(S["area"]))
def sel(): return sorted(o.name for o in bpy.context.view_layer.objects.selected)
def at(name, dx=0.5, dy=0.5):
    with ctx():
        st = sch().state(bpy.context)
    n = next(n for n in st["nodes"].values() if n.name == name)
    x, y = st["pos"][n.uid]
    r = reg(S["area"])
    rx, ry = sch().to_region(r.view2d, x + n.w * dx, y + n.h * dy)
    return int(r.x + rx), int(r.y + ry)
def segs():
    with ctx():
        st = sch().state(bpy.context)
        return ld().segments(bpy.context, st, reg(S["area"]).view2d, bpy.context.view_layer)
def link_point(owner):
    """A window point on the drawn link of `owner`, a quarter of the way along (off the arrowhead and label)."""
    for g, a, b in segs():
        if g.links[0].owner.name == owner:
            r = reg(S["area"])
            return int(r.x + a[0] + (b[0] - a[0]) * 0.25), int(r.y + a[1] + (b[1] - a[1]) * 0.25)
    return None
def click(p, button='LEFTMOUSE', **mods):
    win.event_simulate(type='MOUSEMOVE', value='NOTHING', x=p[0], y=p[1])
    win.event_simulate(type=button, value='PRESS', x=p[0], y=p[1], **mods)
    win.event_simulate(type=button, value='RELEASE', x=p[0], y=p[1], **mods)
def key(k, p):
    win.event_simulate(type='MOUSEMOVE', value='NOTHING', x=p[0], y=p[1])
    win.event_simulate(type=k, value='PRESS', x=p[0], y=p[1])
    win.event_simulate(type=k, value='RELEASE', x=p[0], y=p[1])


def setup():
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o)
    sc = bpy.context.scene
    def ob(name):
        o = bpy.data.objects.new(name, None)
        sc.collection.objects.link(o)
        return o
    target, box, cone = ob("lk_target"), ob("lk_box"), ob("lk_cone")
    cone.constraints.new('COPY_LOCATION').target = target
    a = views3d()[0]
    with bpy.context.temp_override(window=win, area=a, region=reg(a)):
        bpy.ops.si.schematic_show()
    S["area"] = a
    a.tag_redraw()
s(setup, 0.8)
def frame():
    with ctx():
        bpy.ops.si.schematic_frame(selected=False)
s(frame, 0.5)

s(lambda: check(segs() == [], "L1 links drawn with nothing selected: %r" % segs()), 0.05)
s(lambda: click(at("lk_cone")), 0.4)
def l1():
    g = [(g.cat, g.label) for g, _a, _b in segs()]
    check(g == [("constraint", "Pos")], "L1 selected cone draws %r" % g)
    check(ld().timings["links"] > 0, "L1 draw_links never ran (not wired into the canvas?)")
s(l1, 0.05)

s(lambda: click(at("lk_box")), 0.3)            # the link stays drawn only while an end is selected
s(lambda: check(segs() == [], "L1 box selected still draws %r" % segs()), 0.05)
s(lambda: click(at("lk_target")), 0.3)
def l2_click():
    p = link_point("lk_cone")
    check(p is not None, "L2 no link drawn for the selected target")
    if p:
        S["link_p"] = p
        click(p)
s(l2_click, 0.4)
def l2():
    check(sel() == ["lk_cone"], "L2 link click selected %r (want the owner lk_cone)" % sel())
    check(bool(ld().picked.get("key")), "L2 the link isn't picked: %r" % ld().picked)
s(l2, 0.05)

s(lambda: key('DEL', S.get("link_p") or at("lk_box")), 0.4)
def l3():
    cone = bpy.data.objects.get("lk_cone")
    check(cone is not None and not cone.constraints, "L3 Delete left %r" % (cone and list(cone.constraints)))
    check(sorted(o.name for o in bpy.data.objects) == ["lk_box", "lk_cone", "lk_target"],
          "L3 objects changed: %r" % sorted(o.name for o in bpy.data.objects))
s(l3, 0.05)

def l4():
    bpy.data.objects["lk_cone"].constraints.new('TRACK_TO').target = bpy.data.objects["lk_target"]
    with ctx():
        bpy.ops.si.schematic_show_toggle(item='constraint')
    S["area"].tag_redraw()
s(l4, 0.4)
def l4b():
    check(segs() == [], "L4 constraint links off still draws %r" % segs())
    with ctx():
        bpy.ops.si.schematic_show_toggle(item='constraint')
    check([g.label for g, _a, _b in segs()] == ["Dir"], "L4 back on: %r" % segs())
s(l4b, 0.2)

def l5_setup():
    sc = bpy.context.scene
    obs = [bpy.data.objects.new("lk_n%05d" % i, None) for i in range(10000)]
    for o in obs:
        sc.collection.objects.link(o)
    for i in range(0, 10000, 60):
        obs[i].constraints.new('COPY_LOCATION').target = obs[(i * 7 + 13) % 10000]
    for i in range(5, 10000, 80):
        obs[i].driver_add("location", 0).driver.variables.new().targets[0].id = obs[(i * 3 + 101) % 10000]
    for o in obs[:60]:
        o.select_set(True)
    S["area"].tag_redraw()
s(l5_setup, 2.0)
s(lambda: S["area"].tag_redraw(), 1.0)
def l5():
    t = ld().timings
    with ctx():
        bpy.ops.wm.redraw_timer(type='DRAW', iterations=3)
    on = t["links"]
    ld().SHOW.update(selected_only=False, operator=True, associated_model=True)
    with ctx():
        bpy.ops.wm.redraw_timer(type='DRAW', iterations=1)     # first draw after the switch: no cache cost here
        bpy.ops.wm.redraw_timer(type='DRAW', iterations=3)
    off = t["links"]
    ld().SHOW.update(selected_only=True, operator=False, associated_model=False)
    print("SHOT: SCHEMATIC_LINKS timings 10k: selected only %.2f ms, all kinds %.2f ms" % (on * 1000, off * 1000))
    check(on < 0.003, "L5 links selected only %.2f ms (want < 3)" % (on * 1000))
    check(off < 0.015, "L5 links all kinds %.2f ms (want < 15)" % (off * 1000))
s(l5, 0.2)
R.start(0.8)
