# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Alex Doss
# WAIT: 55
"""Property Editor through the real UI (simulated mouse), the criteria the audit found untested
(spec properties.ppg): C1 the Explorer icon opens the PPG without selecting, the name selects; C3 Ctrl+wheel on
Length / Subdivisions U changes the mesh live and one Ctrl+Z undoes one edit; C4 a divot click keys the value,
a second click unkeys it; C6 the docked pane's Revert point is renewed when the pane is opened again.
Fields are found by hovering points in the pane and asking Blender for the data path under the mouse
(technique from the auditor's probe)."""
import bpy, importlib
K = "bl_ext.user_default.silica"
ppg = importlib.import_module(K + ".ui.ppg")
docks = importlib.import_module(K + ".ui.docks")
win = bpy.context.window_manager.windows[0]
wm = bpy.context.window_manager
errors, steps, S = [], [], {}
def s(fn, w=0.25): steps.append((fn, w))
def check(c, m):
    if not c: errors.append(m)
def run():
    if not steps:
        print("SHOT: PPGUI", "PASS" if not errors else "FAIL " + " | ".join(errors))
        return None
    fn, w = steps.pop(0)
    try: fn()
    except Exception:
        import traceback; errors.append(traceback.format_exc()[-300:])
    return w
def views(): return sorted((a for a in win.screen.areas if a.type == 'VIEW_3D'), key=lambda a: (-a.y, a.x))
def reg(a, t='WINDOW'): return next(r for r in a.regions if r.type == t)
def role_area(role):
    return next(a for a in win.screen.areas if a.type == 'PROPERTIES' and docks.space_role(a.spaces.active) == role)
def mv(x, y): win.event_simulate(type='MOUSEMOVE', value='NOTHING', x=int(x), y=int(y))
def click(x, y):
    mv(x, y)
    win.event_simulate(type='LEFTMOUSE', value='PRESS', x=int(x), y=int(y))
    win.event_simulate(type='LEFTMOUSE', value='RELEASE', x=int(x), y=int(y))
def esc():
    mv(5, 5)
    win.event_simulate(type='ESC', value='PRESS', x=5, y=5)
    win.event_simulate(type='ESC', value='RELEASE', x=5, y=5)
def cube(): return bpy.data.objects.get("cube")
def mesh():
    dg = bpy.context.evaluated_depsgraph_get()
    e = cube().evaluated_get(dg)
    m = e.to_mesh()
    xs = [v.co.x for v in m.vertices]
    out = (round(max(xs) - min(xs), 3), len(m.vertices))
    e.to_mesh_clear()
    return out
def keys(ob):
    ad = ob.animation_data
    if not ad or not ad.action:
        return []
    out = []
    for layer in ad.action.layers:
        for strip in layer.strips:
            for cb in strip.channelbags:
                out += [(fc.data_path, len(fc.keyframe_points)) for fc in cb.fcurves if fc.keyframe_points]
    return out
def select_only(name):
    vl = bpy.context.view_layer
    for o in vl.objects: o.select_set(False)
    vl.objects[name].select_set(True); vl.objects.active = vl.objects[name]
def ctrl_z():
    r = reg(views()[-1])
    x, y = r.x + r.width // 2, r.y + r.height // 2
    mv(x, y)
    win.event_simulate(type='Z', value='PRESS', x=x, y=y, ctrl=True)
    win.event_simulate(type='Z', value='RELEASE', x=x, y=y, ctrl=True)


def setup():
    for o in list(bpy.data.objects): bpy.data.objects.remove(o)
    A, B = views()[0], views()[1]
    with bpy.context.temp_override(window=win, area=B, region=reg(B)):
        bpy.ops.si.get_primitive(kind="SPHERE")
        bpy.ops.si.get_primitive(kind="CUBE")
    with bpy.context.temp_override(window=win, area=A, region=reg(A)):
        bpy.ops.si.ppg_show()
    wm.si_ppg_tab = "Cube"
    bpy.ops.ed.undo_push(message="test setup")
s(setup, 1.0)


def scan(tag, match):
    """Hover points down the pane; remember the first whose button data path matches."""
    def start():
        r = reg(role_area("PPG"))
        S[tag] = None
        S[tag + "_pts"] = [(r.x + int(r.width * 0.6), r.y + r.height - 20 - 9 * i) for i in range(45)]
    s(start, 0.1)
    for i in range(46):
        def probe(i=i):
            pts = S[tag + "_pts"]
            if i > 0 and S[tag] is None:
                P = role_area("PPG")
                wm.clipboard = ""
                try:
                    with bpy.context.temp_override(window=win, area=P, region=reg(P)):
                        bpy.ops.ui.copy_data_path_button(full_path=False)
                except Exception:
                    pass
                if wm.clipboard and match(wm.clipboard):
                    S[tag] = pts[i - 1]
            if i < len(pts) and S[tag] is None:
                mv(*pts[i])
        s(probe, 0.06)
    s(lambda: check(S[tag] is not None, "could not find the %s field in the pane" % tag), 0.05)


def wheel(tag):
    def f():
        if S.get(tag):
            mv(*S[tag])
            win.event_simulate(type='WHEELUPMOUSE', value='PRESS', x=S[tag][0], y=S[tag][1], ctrl=True)
    return f


# C3: Length
scan("length", lambda c: "inputs" in c)
s(lambda: S.__setitem__("m0", mesh()), 0.05)
s(wheel("length"), 0.6)
s(lambda: check(mesh()[0] != S["m0"][0], "C3 Ctrl+wheel on Length did not change the mesh: %r" % (mesh(),)), 0.05)
s(lambda: S.__setitem__("m0_edit", mesh()), 0.05)
s(ctrl_z, 0.8)
s(lambda: check(mesh() == S["m0"], "C3 one Ctrl+Z did not undo the Length edit: %r vs %r" % (mesh(), S["m0"])), 0.05)
# redo brings the edit back: proves the edit was its own undo step (not 0 steps)
def ctrl_shift_z():
    r = reg(views()[-1])
    x, y = r.x + r.width // 2, r.y + r.height // 2
    mv(x, y)
    win.event_simulate(type='Z', value='PRESS', x=x, y=y, ctrl=True, shift=True)
    win.event_simulate(type='Z', value='RELEASE', x=x, y=y, ctrl=True, shift=True)
s(ctrl_shift_z, 0.8)
s(lambda: check(mesh() == S["m0_edit"], "C3 redo did not bring the Length edit back (no undo step?): %r" % (mesh(),)), 0.05)
s(ctrl_z, 0.8)

# C3: Subdivisions U (Geometry tab)
s(lambda: (wm.__setattr__("si_ppg_tab", "Geometry"), role_area("PPG").tag_redraw()), 0.4)
scan("subd", lambda c: "inputs" in c)
s(lambda: S.__setitem__("m1", mesh()), 0.05)
s(wheel("subd"), 0.6)
s(lambda: check(mesh()[1] > S["m1"][1], "C3 Ctrl+wheel on Subdivisions U: vertices %d -> %d" % (S["m1"][1], mesh()[1])), 0.05)
s(ctrl_z, 0.8)
s(lambda: check(mesh() == S["m1"], "C3 one Ctrl+Z did not undo the subdivision edit"), 0.05)

# C4: divot on Length (Cube tab): find the spot right of the field that keys it, then click again to unkey
s(lambda: (wm.__setattr__("si_ppg_tab", "Cube"), role_area("PPG").tag_redraw()), 0.4)
for dx in (20, 26, 14, 32, 10, 38):
    def try_divot(dx=dx):
        if S.get("divot") or not S.get("length"):
            return
        r = reg(role_area("PPG"))
        S["divot_try"] = (r.x + r.width - dx, S["length"][1])
        click(*S["divot_try"])
    def chk():
        if S.get("divot") or not S.get("length"):
            return
        if keys(cube()):
            S["divot"] = S["divot_try"]
        else:
            esc()
    s(try_divot, 0.4)
    s(chk, 0.3)
s(lambda: check(bool(S.get("divot")) and any("inputs" in p for p, _n in keys(cube())),
                "C4 divot click did not key Length: %r" % (keys(cube()),)), 0.05)
s(lambda: click(*S["divot"]) if S.get("divot") else None, 0.5)
s(lambda: check(not keys(cube()), "C4 second divot click did not unkey: %r" % (keys(cube()),)), 0.05)

# C6: close the pane, move the cube, open the pane again: Revert must not jump back to the old position
def close_pane():
    P = role_area("PPG")
    with bpy.context.temp_override(window=win, area=P, region=reg(P)):
        bpy.ops.si.view_set(view='TOP')
s(close_pane, 0.3)
s(lambda: setattr(cube(), "location", (7.0, 0.0, 0.0)), 0.1)
def reopen():
    select_only("cube")
    A = views()[0]
    with bpy.context.temp_override(window=win, area=A, region=reg(A)):
        bpy.ops.si.ppg_show()
s(reopen, 0.4)
def revert():
    P = role_area("PPG")
    with bpy.context.temp_override(window=win, area=P, region=reg(P)):
        bpy.ops.si.ppg_revert(where="pane")
s(revert, 0.3)
s(lambda: check(abs(cube().location.x - 7.0) < 1e-6, "C6 Revert used a stale point: x=%.2f (want 7)" % cube().location.x))
# ... and the reopened pane really has a Revert point: move again, Revert, back at 7 (fails if Revert does nothing)
s(lambda: setattr(cube(), "location", (9.0, 0.0, 0.0)), 0.1)
s(revert, 0.3)
s(lambda: check(abs(cube().location.x - 7.0) < 1e-6, "C6 Revert did nothing: x=%.2f (want 7)" % cube().location.x))

# C1: Explorer icon opens the PPG without selecting; the name selects
def explorer():
    P = role_area("PPG")
    with bpy.context.temp_override(window=win, area=P, region=reg(P)):
        bpy.ops.si.view_set(view='TOP')
    A = views()[0]
    with bpy.context.temp_override(window=win, area=A, region=reg(A)):
        bpy.ops.si.explorer_show()
    select_only("sphere")
    wm.si_ppg_popup_target = None
s(explorer, 0.5)
for row in range(6):
    def icon_click(row=row):
        if S.get("icon_ok"):
            return
        E = role_area("EXPLORER"); r = reg(E)
        S["before"] = sorted(o.name for o in bpy.context.selected_objects)
        wm.si_ppg_popup_target = None
        S["icon_xy"] = (r.x + 50, r.y + r.height - 14 - 20 * row)
        click(*S["icon_xy"])
    def icon_chk():
        if S.get("icon_ok"):
            return
        t = wm.si_ppg_popup_target
        after = sorted(o.name for o in bpy.context.selected_objects)
        if t is not None and t.name == "cube":
            S["icon_ok"] = True
            check(after == S["before"], "C1 the Explorer icon changed the selection: %r -> %r" % (S["before"], after))
        esc()
    s(icon_click, 0.3)
    s(icon_chk, 0.25)
s(lambda: check(S.get("icon_ok"), "C1 clicking the cube's icon in the Explorer did not open its PPG"), 0.05)

bpy.app.timers.register(run, first_interval=0.8)
