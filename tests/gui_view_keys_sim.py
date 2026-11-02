# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Alex Doss
# WAIT: 40
"""Number keys (spec ui.view-keys), simulated input. Written before the code.
C1 1-4 / Ctrl+2 / Ctrl+4 switch the left toolbar over a 3D view, the left dock and a Render Tree; C2 in Object /
Edit Mode the digits don't hide collections or change select modes; C3 5-0 open one floating window each with the
right editor, main layout untouched; C4 same key closes, again opens; C5 a window closed by hand; C6 mode off."""
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
        print("SHOT: VIEWKEYS", "PASS" if not errors else "FAIL " + " | ".join(errors))
        return None
    fn, w = steps.pop(0)
    try: fn()
    except Exception:
        import traceback; tb = traceback.format_exc().strip().splitlines(); errors.append(" / ".join(tb[-3:]))
    return w
def mod(name): return importlib.import_module(K + "." + name)
def mv(x, y): win.event_simulate(type='MOUSEMOVE', value='NOTHING', x=int(x), y=int(y))
def key(t, **k):
    x, y = S["at"]
    win.event_simulate(type=t, value='PRESS', x=x, y=y, **k)
    win.event_simulate(type=t, value='RELEASE', x=x, y=y, **k)
def centre(a): return a.x + a.width // 2, a.y + a.height // 2
def views3d(): return sorted((a for a in win.screen.areas if a.type == 'VIEW_3D'), key=lambda a: (-a.y, a.x))
def dock(role):
    docks = mod("ui.docks")
    for a in win.screen.areas:
        if a.type == 'PROPERTIES' and docks.space_role(a.spaces.active) == role:
            return a
def main_layout(): return [(a.type, a.ui_type, a.x, a.y, a.width, a.height) for a in win.screen.areas]
def view_windows(): return {w.screen.get("si_view"): w for w in wm.windows if w.screen and w.screen.get("si_view")}
def at(area):
    S["at"] = centre(area)
    mv(*S["at"])


def setup():
    for o in list(bpy.data.objects): bpy.data.objects.remove(o)
    v = views3d()[1]
    with bpy.context.temp_override(window=win, area=v, region=next(r for r in v.regions if r.type == 'WINDOW')):
        bpy.ops.si.get_primitive(kind="CUBE")
    S["base_windows"] = len(wm.windows)
s(setup, 0.6)

# C1 toolbars over three kinds of pane
TOOLBAR = [('TWO', {}, "Animate"), ('THREE', {}, "Render"), ('FOUR', {}, "ICE"), ('TWO', {"ctrl": True}, "Hair"),
           ('FOUR', {"ctrl": True}, "Simulate"), ('ONE', {}, "Model")]
def pane_3d(): at(views3d()[0])
def pane_dock():
    a = dock("TOOLBAR")
    check(a is not None, "C1 no left dock found")
    if a: at(a)
def pane_tree():
    a = views3d()[2]
    a.ui_type = 'ShaderNodeTree'
    S["tree_area"] = a
    at(a)
for name, pane in (("3D view", pane_3d), ("left dock", pane_dock), ("Render Tree", pane_tree)):
    s(pane, 0.3)
    for t, k, want in TOOLBAR:
        s((lambda t, k: (lambda: key(t, **k)))(t, k), 0.15)
        s((lambda want, name, t, k: (lambda: check(wm.si_module == want, "C1 %s%s over the %s: toolbar %r, want %r"
                                                   % ("Ctrl+" if k else "", t, name, wm.si_module, want))))(want, name, t, k), 0.05)
def tree_back():
    S["tree_area"].ui_type = 'VIEW_3D'
s(tree_back, 0.3)

# C2 Object Mode: digits don't hide collections; Edit Mode: they don't change select modes
def c2_object():
    at(views3d()[1])
    S["hidden"] = [lc.hide_viewport for lc in bpy.context.view_layer.layer_collection.children]
    key('TWO')
s(c2_object, 0.3)
s(lambda: check([lc.hide_viewport for lc in bpy.context.view_layer.layer_collection.children] == S["hidden"]
                and wm.si_module == "Animate", "C2 Object Mode: 2 hid collections or missed the toolbar"), 0.05)
def c2_edit():
    v = views3d()[1]
    ob = bpy.data.objects["cube"]
    bpy.context.view_layer.objects.active = ob
    ob.select_set(True)
    with bpy.context.temp_override(window=win, area=v, region=next(r for r in v.regions if r.type == 'WINDOW')):
        bpy.ops.object.mode_set(mode='EDIT')
    bpy.context.tool_settings.mesh_select_mode = (True, False, False)
s(c2_edit, 0.4)
def c2_edit_key():
    at(views3d()[1])
    key('THREE')
s(c2_edit_key, 0.3)
def c2_edit_check():
    check(tuple(bpy.context.tool_settings.mesh_select_mode) == (True, False, False) and wm.si_module == "Render",
          "C2 Edit Mode: 3 changed the select mode %r / toolbar %r" % (tuple(bpy.context.tool_settings.mesh_select_mode), wm.si_module))
    v = views3d()[1]
    with bpy.context.temp_override(window=win, area=v, region=next(r for r in v.regions if r.type == 'WINDOW')):
        bpy.ops.object.mode_set(mode='OBJECT')
    key('ONE')
s(c2_edit_check, 0.3)

# C3 / C4 floating views
VIEWS = [('FIVE', "BROWSER"), ('SIX', "LAYERS"), ('SEVEN', "RENDER_TREE"), ('EIGHT', "EXPLORER"), ('NINE', "SCHEMATIC"),
         ('ZERO', "ANIMATION")]
def editor_ok(view, w):
    areas = list(w.screen.areas)
    if len(areas) != 1:
        return "has %d areas" % len(areas)
    a = areas[0]
    sp = a.spaces.active
    if view == "BROWSER":
        return None if a.type == 'FILE_BROWSER' and a.ui_type == 'FILES' else "is %s/%s" % (a.type, a.ui_type)
    if view == "LAYERS":
        return None if a.type == 'OUTLINER' and sp.display_mode == 'VIEW_LAYER' and not sp.use_filter_object else \
            "is %s / %s / objects %r" % (a.type, getattr(sp, "display_mode", "?"), getattr(sp, "use_filter_object", "?"))
    if view == "RENDER_TREE":
        return None if a.ui_type == 'ShaderNodeTree' else "is %s" % a.ui_type
    if view == "EXPLORER":
        return None if a.type == 'PROPERTIES' and mod("ui.docks").space_role(sp) == "EXPLORER" else "is %s" % a.type
    if view == "SCHEMATIC":
        return None if a.type == 'OUTLINER' and sp.use_filter_object and sp.use_filter_children and \
            not sp.use_filter_collection else "is %s (not an object hierarchy)" % a.type
    if view == "ANIMATION":
        return None if a.ui_type == 'FCURVES' else "is %s" % a.ui_type
for t, view in VIEWS:
    def open_(t=t):
        at(views3d()[0])
        S["layout"] = main_layout()
        S["n"] = len(wm.windows)
        key(t)
    s(open_, 0.6)
    def c3(t=t, view=view):
        w = view_windows().get(view)
        check(len(wm.windows) == S["n"] + 1 and w is not None, "C3 %s did not open one %s window (%d -> %d)"
              % (t, view, S["n"], len(wm.windows)))
        if w is not None:
            bad = editor_ok(view, w)
            check(bad is None, "C3 %s window %s" % (view, bad))
        check(main_layout() == S["layout"], "C3 %s changed the main layout" % t)
    s(c3, 0.1)
    s((lambda t: (lambda: key(t)))(t), 0.5)
    s((lambda t, view: (lambda: check(len(wm.windows) == S["n"] and view not in view_windows(),
                                      "C4 %s again did not close the window" % t)))(t, view), 0.1)
s(lambda: key('EIGHT'), 0.5)
s(lambda: key('EIGHT'), 0.5)
s(lambda: (key('EIGHT')), 0.5)
s(lambda: check(len(view_windows()) == 1 and "EXPLORER" in view_windows(), "C4 third press: %r" % list(view_windows())), 0.1)

# C5 closed by hand
def close_by_hand():
    w = view_windows()["EXPLORER"]
    with bpy.context.temp_override(window=w):
        bpy.ops.wm.window_close()
s(close_by_hand, 0.5)
s(lambda: check(not view_windows(), "C5 window not closed"), 0.05)
s(lambda: key('EIGHT'), 0.5)
s(lambda: check("EXPLORER" in view_windows(), "C5 after closing by hand, 8 did not open a new Explorer"), 0.05)

# C6 mode off
s(lambda: key('NINE'), 0.5)
def c6():
    mode = mod("mode")
    mode.exit_mode()
    check(not view_windows() and len(wm.windows) == S["base_windows"], "C6 view windows left after mode off: %r"
          % list(view_windows()))
    digits = {'ONE', 'TWO', 'THREE', 'FOUR', 'FIVE', 'SIX', 'SEVEN', 'EIGHT', 'NINE', 'ZERO'}
    left = [kmi.idname for km in wm.keyconfigs.addon.keymaps for kmi in km.keymap_items
            if kmi.type in digits and kmi.idname.startswith("si.")]
    check(not left, "C6 digit keys left: %r" % left[:5])
    mode.enter_mode()
s(c6, 0.6)
bpy.app.timers.register(run, first_interval=0.8)
