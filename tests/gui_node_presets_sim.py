# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Alex Doss
# WAIT: 45
"""Render Tree preset panel, simulated input (spec render.render-tree-presets). Written before the code.
C1 panel drawn on the left of the graph; C3 category click lists its nodes, search filters; C4 a node click only
selects; C5 drag onto the graph adds the node at the drop point (one Ctrl+Z removes it), release over the panel adds
nothing; C6 right click pins / unpins; C7 Shift+A untouched; C8 wheel decision + bindings; C9 mode off.
Audit 2026-11-01 fixes: clicks over the panel (Shift / Ctrl / double / the click after the press) never reach the
graph behind it; drop point right at UI scale 1.5; search field lets go of the mouse; wheel operator invoked; panel
keys bound even with Softimage keys off; Tab only in the Softimage Render Tree."""
import bpy, importlib
K = "bl_ext.user_default.silica"
win = bpy.context.window_manager.windows[0]
errors, steps, S = [], [], {}
def s(fn, w=0.2): steps.append((fn, w))
def check(c, m):
    if not c: errors.append(m)
def run():
    if not steps:
        bpy.context.preferences.view.ui_scale = S.get("scale0", 1.0)
        print("SHOT: PRESETS", "PASS" if not errors else "FAIL " + " | ".join(errors))
        return None
    fn, w = steps.pop(0)
    try: fn()
    except Exception:
        import traceback; tb = traceback.format_exc().strip().splitlines(); errors.append(" / ".join(tb[-3:]))
    return w
def np_(): return importlib.import_module(K + ".ui.node_presets")
def views(): return sorted((a for a in win.screen.areas if a.type in ('VIEW_3D', 'NODE_EDITOR')), key=lambda a: (-a.y, a.x))
def area(): return S["area"]
def reg(): return next(r for r in area().regions if r.type == 'WINDOW')
def to_win(rect):
    r = reg()
    x, y, w, h = rect
    return r.x + x + w // 2, r.y + y + h // 2
def mv(x, y): win.event_simulate(type='MOUSEMOVE', value='NOTHING', x=int(x), y=int(y))
def press(t, x, y, **k):
    win.event_simulate(type=t, value='PRESS', x=int(x), y=int(y), **k)
def release(t, x, y, **k):
    win.event_simulate(type=t, value='RELEASE', x=int(x), y=int(y), **k)
def click(x, y, t='LEFTMOUSE'):
    mv(x, y); press(t, x, y); release(t, x, y)
def tree(): return bpy.data.objects["cube"].active_material.node_tree
def geo(): return np_().geometry(reg())
def us(): return bpy.context.preferences.system.ui_scale
def drawn_at_drop(node, drop):
    """Where Blender draws the node (location x UI scale, in View2D units) vs the drop point."""
    r = reg()
    want = r.view2d.region_to_view(drop[0] - r.x, drop[1] - r.y)
    have = (node.location.x * us(), node.location.y * us())
    return ((have[0] - want[0]) ** 2 + (have[1] - want[1]) ** 2) ** 0.5, have, want


def setup():
    for o in list(bpy.data.objects): bpy.data.objects.remove(o)
    B = sorted((a for a in win.screen.areas if a.type == 'VIEW_3D'), key=lambda a: (-a.y, a.x))[1]
    rb = next(r for r in B.regions if r.type == 'WINDOW')
    with bpy.context.temp_override(window=win, area=B, region=rb):
        bpy.ops.si.get_primitive(kind="CUBE")
    ob = bpy.data.objects["cube"]
    mat = bpy.data.materials.new("Material")
    mat.use_nodes = True
    ob.data.materials.append(mat)
    B.ui_type = 'ShaderNodeTree'
    B.spaces.active.show_region_ui = False       # Blender's sidebar (N) would sit over the graph's drop points
    S["area"] = B
    bpy.ops.ed.undo_push(message="test setup")
s(setup, 0.6)
s(lambda: mv(reg().x + reg().width // 2, reg().y + reg().height // 2), 0.4)

# C1
def c1():
    m = np_()
    g = geo()
    px, py, pw, ph = g["panel"]
    check(m.draw_count.get(area().as_pointer(), 0) > 0, "C1 panel never drawn")
    check(px == 0 and pw > 150 and ph > 200, "C1 panel not on the left: %r" % (g["panel"],))
    check(g["cats"] and g["nodes"] is not None, "C1 no category column")
    check(not m.draw_errors, "C1 draw errors: %s" % m.draw_errors[:2])
s(c1, 0.1)

# C3 category click
def click_texture():
    rect = next(r for c, r in geo()["cats"] if c == "Texture")
    click(*to_win(rect))
s(click_texture, 0.4)
def c3():
    m = np_()
    check(m.state["category"] == "Texture", "C3 category is %r" % m.state["category"])
    ids = [i for i, _l, _r in geo()["nodes"]]
    check(ids and all(i.startswith("ShaderNodeTex") for i in ids), "C3 Texture column shows %r" % ids[:5])
s(c3, 0.1)

# C4 click a node: selected, nothing added
def click_node():
    S["n0"] = len(tree().nodes)
    i, _l, rect = geo()["nodes"][0]
    S["first"] = i
    click(*to_win(rect))
s(click_node, 0.4)
s(lambda: check(np_().state["selected"] == S["first"] and len(tree().nodes) == S["n0"],
                "C4 click: selected %r, nodes %d -> %d" % (np_().state["selected"], S["n0"], len(tree().nodes))), 0.1)

# C5 drag onto the graph
def drag_start():
    i, _l, rect = geo()["nodes"][0]
    S["drag_id"] = i
    S["from"] = to_win(rect)
    r = reg()
    S["to"] = (r.x + int(r.width * 0.7), r.y + int(r.height * 0.5))
    mv(*S["from"]); press('LEFTMOUSE', *S["from"])
s(drag_start, 0.15)
for k in range(1, 9):
    s((lambda k: (lambda: mv(S["from"][0] + (S["to"][0] - S["from"][0]) * k / 8,
                             S["from"][1] + (S["to"][1] - S["from"][1]) * k / 8)))(k), 0.04)
s(lambda: release('LEFTMOUSE', *S["to"]), 0.5)
def c5():
    t = tree()
    check(len(t.nodes) == S["n0"] + 1, "C5 drag did not add one node (%d -> %d)" % (S["n0"], len(t.nodes)))
    new = t.nodes.active
    check(new is not None and new.bl_idname == S["drag_id"], "C5 added %r, want %s" % (new and new.bl_idname, S["drag_id"]))
    if new is not None:
        d, have, want = drawn_at_drop(new, S["to"])
        check(d < 60, "C5 node drawn at %r, drop point %r" % (have, want))
s(c5, 0.1)
def ctrl_z():
    r = reg()
    x, y = r.x + int(r.width * 0.7), r.y + int(r.height * 0.3)
    mv(x, y)
    press('Z', x, y, ctrl=True); release('Z', x, y, ctrl=True)
s(ctrl_z, 0.8)
s(lambda: check(len(tree().nodes) == S["n0"], "C5 one Ctrl+Z did not remove the dropped node"), 0.1)

# C5 at UI scale 1.5 (HiDPI / Windows scaling): the node must be drawn where it was dropped
def scale_up():
    S["scale0"] = bpy.context.preferences.view.ui_scale
    bpy.context.preferences.view.ui_scale = 1.5

s(scale_up, 0.6)
def drag_scaled():
    i, _l, rect = geo()["nodes"][0]
    S["drag_id"], S["from"] = i, to_win(rect)
    r = reg()
    S["to"] = (r.x + int(r.width * 0.75), r.y + int(r.height * 0.3))
    S["n2"] = len(tree().nodes)
    mv(*S["from"]); press('LEFTMOUSE', *S["from"])
s(drag_scaled, 0.15)
for k in range(1, 9):
    s((lambda k: (lambda: mv(S["from"][0] + (S["to"][0] - S["from"][0]) * k / 8,
                             S["from"][1] + (S["to"][1] - S["from"][1]) * k / 8)))(k), 0.04)
s(lambda: release('LEFTMOUSE', *S["to"]), 0.5)
def c5_scaled():
    t = tree()
    check(len(t.nodes) == S["n2"] + 1, "C5 scale 1.5: drag did not add one node (from %r to %r, panel %r, region %r, errors %r)"
          % (S["from"], S["to"], geo()["panel"], [(r.type, r.x, r.y, r.width, r.height) for r in area().regions if r.width > 1], np_().draw_errors[:2]))
    new = t.nodes.active
    if new is not None and len(t.nodes) == S["n2"] + 1:
        d, have, want = drawn_at_drop(new, S["to"])
        check(d < 60 * us(), "C5 scale 1.5: node drawn at %r, drop point %r" % (have, want))
        t.nodes.remove(new)
    bpy.context.preferences.view.ui_scale = S["scale0"]
s(c5_scaled, 0.6)

# C5 a drop on Blender's sidebar (N, drawn over the graph) adds nothing
def sidebar_drag():
    area().spaces.active.show_region_ui = True
s(sidebar_drag, 0.5)
def drag_to_sidebar():
    ui = next(r for r in area().regions if r.type == 'UI')
    i, _l, rect = geo()["nodes"][0]
    S["from"] = to_win(rect)
    S["to"] = (ui.x + ui.width // 2, ui.y + ui.height // 2)
    S["n4"] = len(tree().nodes)
    mv(*S["from"]); press('LEFTMOUSE', *S["from"])
s(drag_to_sidebar, 0.15)
for k in range(1, 9):
    s((lambda k: (lambda: mv(S["from"][0] + (S["to"][0] - S["from"][0]) * k / 8,
                             S["from"][1] + (S["to"][1] - S["from"][1]) * k / 8)))(k), 0.04)
s(lambda: release('LEFTMOUSE', *S["to"]), 0.4)
def c5_sidebar():
    check(len(tree().nodes) == S["n4"], "C5 a drop on Blender's sidebar added a node")
    area().spaces.active.show_region_ui = False
s(c5_sidebar, 0.4)

# C5 release over the panel: nothing added
def drag_back():
    i, _l, rect = geo()["nodes"][0]
    S["from"] = to_win(rect)
    S["to"] = to_win(geo()["nodes"][-1][2])
    S["n1"] = len(tree().nodes)
    mv(*S["from"]); press('LEFTMOUSE', *S["from"])
s(drag_back, 0.1)
s(lambda: mv(S["from"][0] + 30, S["from"][1] - 40), 0.05)
s(lambda: (mv(*S["to"]), release('LEFTMOUSE', *S["to"])), 0.4)
s(lambda: check(len(tree().nodes) == S["n1"], "C5 release over the panel added a node"), 0.1)

# C4 / C1: clicks on the panel never reach a graph node hidden behind it (plain, Shift, Ctrl, double click)
def leak_setup():
    t = tree()
    r = reg()
    _i, _l, rect = geo()["nodes"][2]
    cx, cy = rect[0] + rect[2] // 2, rect[1] + rect[3] // 2
    vx, vy = r.view2d.region_to_view(cx, cy)
    n = t.nodes.new("ShaderNodeValue")
    n.name = "si_leak"
    n.location = (vx / us() - 30, vy / us() + 20)          # node body covers the row centre
    for m in t.nodes:
        m.select = False
    keep = next(m for m in t.nodes if m.name != "si_leak")
    keep.select = True
    t.nodes.active = keep
    S["keep"] = keep.name
    S["leak_xy"] = (r.x + cx, r.y + cy)
    S["n3"] = len(t.nodes)
s(leak_setup, 0.4)
def leak_check(what):
    t = tree()
    sel = sorted(m.name for m in t.nodes if m.select)
    act = t.nodes.active and t.nodes.active.name
    check(sel == [S["keep"]] and act == S["keep"] and len(t.nodes) == S["n3"],
          "C4 %s on the panel reached the graph: selected %r, active %r, nodes %d" % (what, sel, act, len(t.nodes)))
s(lambda: click(*S["leak_xy"]), 0.3)
s(lambda: leak_check("click"), 0.05)
def mod_click(**k):
    x, y = S["leak_xy"]
    mv(x, y); press('LEFTMOUSE', x, y, **k); release('LEFTMOUSE', x, y, **k)
s(lambda: mod_click(shift=True), 0.3)
s(lambda: leak_check("Shift+click"), 0.05)
s(lambda: mod_click(ctrl=True), 0.3)
s(lambda: leak_check("Ctrl+click"), 0.05)
def dbl():
    x, y = S["leak_xy"]
    mv(x, y)
    for _k in range(2):        # two quick clicks: Blender turns the second press into a DOUBLE_CLICK itself
        press('LEFTMOUSE', x, y); release('LEFTMOUSE', x, y)
s(dbl, 0.4)
s(lambda: leak_check("double click"), 0.05)
def leak_done():
    t = tree()
    n = t.nodes.get("si_leak")
    if n:
        t.nodes.remove(n)
s(leak_done, 0.1)

# C3 search
s(lambda: click(*to_win(geo()["search"])), 0.3)
s(lambda: check(np_().state["editing"], "C3 search field did not start editing"), 0.05)
def type_noise():
    x, y = to_win(geo()["search"])
    for ch in "noise":
        win.event_simulate(type=ch.upper(), value='PRESS', x=x, y=y, unicode=ch)
        win.event_simulate(type=ch.upper(), value='RELEASE', x=x, y=y)
    press('RET', x, y); release('RET', x, y)
s(type_noise, 0.4)
def c3_search():
    m = np_()
    labels = [l for _i, l, _r in geo()["nodes"]]
    check(m.state["search"] == "noise" and not m.state["editing"], "C3 search text %r" % m.state["search"])
    check(labels and all("noise" in l.lower() for l in labels), "C3 search shows %r" % labels[:5])
s(c3_search, 0.1)
# the search field lets go of the mouse: a middle press over the graph ends editing (and pans as usual)
s(lambda: click(*to_win(geo()["search"])), 0.3)
s(lambda: check(np_().state["editing"], "C3 search field did not start editing (2)"), 0.05)
def mmb_graph():
    r = reg()
    x, y = r.x + int(r.width * 0.7), r.y + int(r.height * 0.5)
    mv(x, y); press('MIDDLEMOUSE', x, y); release('MIDDLEMOUSE', x, y)
s(mmb_graph, 0.3)
s(lambda: check(not np_().state["editing"] and np_().state["search"] == "noise",
                "C3 middle click outside did not end editing (editing %r, text %r)"
                % (np_().state["editing"], np_().state["search"])), 0.05)

# C6 favorites: right click pins, again unpins
def rclick_first():
    i, _l, rect = geo()["nodes"][0]
    S["fav"] = i
    S["fav_before"] = i in np_().favorites()
    click(*to_win(rect), t='RIGHTMOUSE')
s(rclick_first, 0.3)
s(lambda: check((S["fav"] in np_().favorites()) != S["fav_before"], "C6 right click did not pin / unpin"), 0.05)
def rclick_again():
    rect = next(r for i, _l, r in geo()["nodes"] if i == S["fav"])
    click(*to_win(rect), t='RIGHTMOUSE')
s(rclick_again, 0.3)
s(lambda: check((S["fav"] in np_().favorites()) == S["fav_before"], "C6 second right click did not undo the pin"), 0.05)

# C8 wheel. Blender's event simulation doesn't deliver wheel events to keymaps (not even its own view zoom) and a
# real OS wheel would go to whatever window is under the cursor, so: the decision function + the key bindings here,
# the wheel in hand by the user (spec).
def c8():
    m = np_()
    m.state.update(search="", category="All Nodes", scroll=0)
    r = reg()
    px, py, pw, ph = geo()["panel"]
    check(m.scroll_at(r, px + pw // 2, py + ph // 2, 'DOWN') and m.state["scroll"] == 3, "C8 wheel over the panel did not scroll")
    check(m.scroll_at(r, px + pw // 2, py + ph // 2, 'UP') and m.state["scroll"] == 0, "C8 wheel up did not scroll back")
    check(not m.scroll_at(r, pw + 50, py + ph // 2, 'DOWN') and m.state["scroll"] == 0, "C8 wheel over the graph was taken")
    kc = bpy.context.window_manager.keyconfigs.addon
    bound = {(kmi.type, kmi.properties.direction) for km in kc.keymaps if km.name == "Node Editor"
             for kmi in km.keymap_items if kmi.idname == "si.node_panel_wheel"}
    check(bound == {('WHEELUPMOUSE', 'UP'), ('WHEELDOWNMOUSE', 'DOWN')}, "C8 wheel keys not bound: %r" % (bound,))
    items = [kmi for km in kc.keymaps if km.name == "Node Editor" for kmi in km.keymap_items
             if kmi.idname.startswith("si.node_panel")]
    check(items and all(kmi.any for kmi in items), "panel keys must match any modifier")
    pairs = {(kmi.type, kmi.value) for kmi in items}
    for want in [(b, v) for b in ('LEFTMOUSE', 'RIGHTMOUSE')
                 for v in ('PRESS', 'DOUBLE_CLICK', 'RELEASE', 'CLICK', 'CLICK_DRAG')]:
        check(want in pairs, "panel key %r not bound" % (want,))
s(c8, 0.1)
# C8 the wheel operator itself (event simulation can't send wheels, but INVOKE_DEFAULT reads the mouse position)
def mouse_on_panel():
    px, py, pw, ph = geo()["panel"]
    mv(reg().x + pw // 2, reg().y + ph // 2)
s(mouse_on_panel, 0.2)
def wheel_op(where):
    m = np_()
    m.state["scroll"] = 0
    with bpy.context.temp_override(window=win, area=area(), region=reg()):
        res = bpy.ops.si.node_panel_wheel('INVOKE_DEFAULT', direction='DOWN')
    if where == "panel":
        check(res == {'FINISHED'} and m.state["scroll"] == 3,
              "C8 wheel operator over the panel: %r scroll %d" % (res, m.state["scroll"]))
    else:
        check(res == {'PASS_THROUGH'} and m.state["scroll"] == 0, "C8 wheel operator over the graph: %r" % (res,))
s(lambda: wheel_op("panel"), 0.1)
s(lambda: mv(reg().x + int(reg().width * 0.7), reg().y + reg().height // 2), 0.2)
s(lambda: wheel_op("graph"), 0.1)

# Tab: Add menu only in the Softimage Render Tree; Blender's Tab (group edit) everywhere else
def tab_elsewhere():
    kc = bpy.context.window_manager.keyconfigs.addon
    tabs = [kmi for km in kc.keymaps if km.name == "Node Editor" for kmi in km.keymap_items if kmi.type == 'TAB']
    check(len(tabs) == 1 and tabs[0].idname == "si.node_tab", "Tab binding: %r" % [k.idname for k in tabs])
    a = area()
    a.ui_type = 'GeometryNodeTree'
    try:
        with bpy.context.temp_override(window=win, area=a, region=reg()):
            res = bpy.ops.si.node_tab('INVOKE_DEFAULT')
        check(res == {'PASS_THROUGH'}, "Tab in a Geometry Nodes editor was taken: %r" % (res,))
    finally:
        a.ui_type = 'ShaderNodeTree'
s(tab_elsewhere, 0.3)

# C7 Shift+A untouched
def c7():
    kc = bpy.context.window_manager.keyconfigs.addon
    ours = [kmi for km in kc.keymaps if km.name == "Node Editor" for kmi in km.keymap_items
            if kmi.type == 'A' and kmi.shift]
    check(not ours, "C7 the kit binds Shift+A in the node editor")
s(c7, 0.05)

# C9 mode off
def c9():
    m = np_()
    mode = importlib.import_module(K + ".mode")
    mode.exit_mode()
    check(not m.handles, "C9 draw handler left after mode off")
    kc = bpy.context.window_manager.keyconfigs.addon
    left = [kmi for km in kc.keymaps for kmi in km.keymap_items if kmi.idname.startswith("si.node_panel")]
    check(not left, "C9 %d panel key items left" % len(left))
    # the panel's mouse keys are part of the panel, not of the "Softimage keys" preference
    p = bpy.context.preferences.addons[K].preferences
    S["keys0"] = p.softimage_keys
    p.softimage_keys = False
    try:
        mode.enter_mode()
        on = [kmi for km in kc.keymaps for kmi in km.keymap_items if kmi.idname.startswith("si.node_panel")]
        check(on, "panel keys missing with Softimage keys off")
        mode.exit_mode()
    finally:
        p.softimage_keys = S["keys0"]
    mode.enter_mode()
s(c9, 0.5)
bpy.app.timers.register(run, first_interval=0.8)
