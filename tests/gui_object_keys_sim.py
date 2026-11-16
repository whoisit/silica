# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Alex Doss
# WAIT: 20
"""Softimage's object keys (user request 2026-11-16, keymap capture context "XSI"), pressed over a 3D view:
Ctrl+D duplicate, Ctrl+I instantiate (linked duplicate), Ctrl+/ cut hierarchical link, Alt+Up / Alt+Down select
parent / first child, Ctrl+T select tree, Ctrl+G create group, Shift+H unhide all, Ctrl+Shift+R reset transforms."""
import bpy
wm = bpy.context.window_manager
win = wm.windows[0]
from _gui import Run
R = Run("OBJECT_KEYS", step=0.3)
s, check, errors, S, steps = R.s, R.check, R.errors, R.S, R.steps
def view():
    return sorted((a for a in win.screen.areas if a.type == 'VIEW_3D'), key=lambda a: (-a.y, a.x))[0]
def key(k, **mods):
    a = view()
    x, y = a.x + a.width // 2, a.y + a.height // 2
    win.event_simulate(type='MOUSEMOVE', value='NOTHING', x=x, y=y)
    win.event_simulate(type=k, value='PRESS', x=x, y=y, **mods)
    win.event_simulate(type=k, value='RELEASE', x=x, y=y, **mods)
def only(*obs):
    vl = bpy.context.view_layer
    for o in vl.objects:
        o.select_set(o in obs)
    vl.objects.active = obs[0] if obs else None
def names():
    return sorted(o.name for o in bpy.context.view_layer.objects.selected)


def setup():
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o)
    sc = bpy.context.scene
    me = bpy.data.meshes.new("ok_m")
    S["p"] = p = bpy.data.objects.new("ok_parent", me)
    S["c"] = c = bpy.data.objects.new("ok_child", me)
    S["g"] = g = bpy.data.objects.new("ok_grand", None)
    for o in (p, c, g):
        sc.collection.objects.link(o)
    c.parent, g.parent = p, c
    p.location = (3, 0, 0)
    bpy.context.view_layer.update()
    only(p)
s(setup, 0.5)

s(lambda: (S.update(n=len(bpy.data.objects)), key('D', ctrl=True)))
def c_dup():
    new = [o for o in bpy.data.objects if o.name.startswith("ok_parent.")]
    check(len(bpy.data.objects) == S["n"] + 1 and new and new[0].data is not S["p"].data, "Ctrl+D: %r" % new)
    check(new and (new[0].location - S["p"].location).length < 1e-6, "Ctrl+D moved the copy")
    for o in new:
        bpy.data.objects.remove(o)
    only(S["p"])
s(c_dup)
s(lambda: (S.update(n=len(bpy.data.objects)), key('I', ctrl=True)))
def c_inst():
    new = [o for o in bpy.data.objects if o.name.startswith("ok_parent.")]
    check(new and new[0].data is S["p"].data, "Ctrl+I: not a linked duplicate %r" % new)
    for o in new:
        bpy.data.objects.remove(o)
    only(S["c"])
s(c_inst)
s(lambda: key('UP_ARROW', alt=True))
s(lambda: (check(names() == ["ok_parent"], "Alt+Up: %r" % names()), key('DOWN_ARROW', alt=True)))
s(lambda: (check(names() == ["ok_child"], "Alt+Down: %r" % names()), only(S["p"]), key('T', ctrl=True)))
s(lambda: (check(names() == ["ok_child", "ok_grand", "ok_parent"], "Ctrl+T: %r" % names()), only(S["c"])))
def c_cut():
    S["w"] = S["c"].matrix_world.translation.copy()
    key('SLASH', ctrl=True)
s(c_cut)
def c_cut_check():
    bpy.context.view_layer.update()
    check(S["c"].parent is None and (S["c"].matrix_world.translation - S["w"]).length < 1e-5,
          "Ctrl+/: parent %r" % S["c"].parent)
    S["groups"] = len(bpy.data.collections)
    only(S["p"], S["c"])
    key('G', ctrl=True)
s(c_cut_check)
def c_group():
    check(len(bpy.data.collections) == S["groups"] + 1, "Ctrl+G made no group")
    vl = bpy.context.view_layer
    for o in (S["p"], S["c"]):
        o.hide_set(True, view_layer=vl)
        o.hide_render = True
    only()
    key('H', shift=True)
s(c_group)
def c_unhide():
    vl = bpy.context.view_layer
    check(not S["p"].hide_get(view_layer=vl) and not S["c"].hide_render, "Shift+H left objects hidden")
    S["p"].location = (1, 2, 3)
    S["p"].scale = (2, 2, 2)
    only(S["p"])
    key('R', ctrl=True, shift=True)
s(c_unhide)
s(lambda: check(tuple(S["p"].location) == (0, 0, 0) and tuple(S["p"].scale) == (1, 1, 1),
                "Ctrl+Shift+R: %r %r" % (tuple(S["p"].location), tuple(S["p"].scale))), 0.1)
R.start(0.8)
