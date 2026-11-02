# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Alex Doss
"""Render region (spec render.render-region), simulated input. Every acceptance criterion + reviewer findings.
Run: python -I tools/dev.py guitest   (or shot ... --simulate 1 --script tests/gui_render_region_sim.py)"""
# WAIT: 25
import bpy, sys
K = "bl_ext.user_default.silica"
rr = sys.modules[K + ".ops.render_region"]
mode = sys.modules[K + ".mode"]
win = bpy.context.window_manager.windows[0]
scene = bpy.context.scene
errors, steps = [], []


def views():
    return sorted((a for a in win.screen.areas if a.type == 'VIEW_3D'), key=lambda a: (-a.y, a.x))


def B():
    return views()[1]


def reg(area, t='WINDOW'):
    return next(r for r in area.regions if r.type == t)


def ev(t, v, x, y):
    win.event_simulate(type=t, value=v, x=int(x), y=int(y))


def s(fn, wait=0.12):
    steps.append((fn, wait))


def check(cond, msg):
    if not cond:
        errors.append(msg)


def run():
    if not steps:
        print("SHOT: REGION", "PASS" if not errors else "FAIL " + " | ".join(errors))
        return None
    fn, wait = steps.pop(0)
    try:
        fn()
    except Exception:
        import traceback
        errors.append(traceback.format_exc()[-400:])
    return wait


def center():
    r = reg(B())
    return r.x + r.width // 2, r.y + r.height // 2


def q_drag(dx0, dy0, dx1, dy1, n=6):
    def press_q():
        cx, cy = center()
        ev('MOUSEMOVE', 'NOTHING', cx + dx0, cy + dy0)
        ev('Q', 'PRESS', cx + dx0, cy + dy0)
    s(press_q, 0.05)
    s(lambda: ev('Q', 'RELEASE', center()[0] + dx0, center()[1] + dy0), 0.15)
    s(lambda: ev('LEFTMOUSE', 'PRESS', center()[0] + dx0, center()[1] + dy0), 0.08)
    for i in range(1, n + 1):
        s((lambda k: (lambda: ev('MOUSEMOVE', 'NOTHING', center()[0] + dx0 + (dx1 - dx0) * k / n,
                                 center()[1] + dy0 + (dy1 - dy0) * k / n)))(i), 0.03)
    s(lambda: ev('LEFTMOUSE', 'RELEASE', center()[0] + dx1, center()[1] + dy1), 0.3)


def q_click():
    q_drag(0, 0, 0, 0, n=1)


def snapshot():
    sp = B().spaces.active
    return dict(shading=sp.shading.type, floor=sp.overlay.show_floor, ortho=sp.overlay.show_ortho_grid,
                text=sp.overlay.show_text, vborder=sp.use_render_border, engine=scene.render.engine,
                vcoords=tuple(round(v, 3) for v in (sp.render_border_min_x, sp.render_border_max_x,
                                                    sp.render_border_min_y, sp.render_border_max_y)),
                sborder=(scene.render.use_border, round(scene.render.border_min_x, 3),
                         round(scene.render.border_max_x, 3)))


def setup():
    global before
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o)
    with bpy.context.temp_override(window=win, area=B(), region=reg(B())):
        bpy.ops.si.get_primitive(kind="CUBE")
        bpy.ops.si.get_primitive(kind="CAMERA")
    scene.camera = bpy.context.view_layer.objects.active
    scene.render.engine = 'BLENDER_EEVEE'
    scene.render.use_border = True                      # the user's own scene border, must survive
    scene.render.border_min_x, scene.render.border_max_x = 0.2, 0.4
    sp = B().spaces.active
    sp.shading.type = 'SOLID'
    sp.overlay.show_floor = True
    sp.overlay.show_text = False
    sp.use_render_border = False                         # a user's own (inactive) view border, must survive
    sp.render_border_min_x, sp.render_border_max_x = 0.11, 0.33
    sp.region_3d.view_perspective = 'PERSP'
    before = snapshot()
s(setup, 0.4)

# C1 + C2 + C3: drag sets the rectangle, Rendered, Cycles, grid hidden, text on
q_drag(-100, -60, 100, 60)
def c1():
    sp, r = B().spaces.active, reg(B())
    check(sp.use_render_border and sp.shading.type == 'RENDERED', "C1 no region")
    check(abs(sp.render_border_min_x - (r.width // 2 - 100) / r.width) < 0.02, "C1 min_x %.3f" % sp.render_border_min_x)
    check(abs(sp.render_border_max_y - (r.height // 2 + 60) / r.height) < 0.02, "C1 max_y %.3f" % sp.render_border_max_y)
    check(scene.render.engine == 'CYCLES', "C2 engine %s" % scene.render.engine)
    check(not sp.overlay.show_floor and sp.overlay.show_text, "C3 grid/text while on")
    check(scene.render.use_border and abs(scene.render.border_min_x - 0.2) < 1e-6, "scene border touched in free view")
    # C6: the header remove button is usable (poll in the header region)
    with bpy.context.temp_override(window=win, area=B(), region=reg(B(), 'HEADER')):
        check(bpy.ops.si.render_region.poll(), "C6 header button greyed")
    check(rr.has_region(win.screen, B()), "C6 has_region false")
s(c1)

# C4: Q + click removes, everything back
q_click()
s(lambda: check(snapshot() == before, "C4 not restored: %r != %r" % (snapshot(), before)))

# C5: Esc / right click while drawing: no change
def esc_test(key):
    s(lambda: (ev('Q', 'PRESS', *center()), ev('Q', 'RELEASE', *center())), 0.15)
    s(lambda: check(bool(rr._running), "C5 Q did not start the tool"))
    s(lambda: ev('LEFTMOUSE', 'PRESS', *center()), 0.05)
    s(lambda: ev('MOUSEMOVE', 'NOTHING', center()[0] + 80, center()[1] + 50), 0.05)
    s(lambda: (ev(key, 'PRESS', center()[0] + 80, center()[1] + 50), ev(key, 'RELEASE', center()[0] + 80, center()[1] + 50)), 0.1)
    s(lambda: ev('LEFTMOUSE', 'RELEASE', center()[0] + 80, center()[1] + 50), 0.2)
    s(lambda: check(snapshot() == before and not rr._running, "C5 %s changed something / tool still running" % key))
esc_test('ESC')
esc_test('RIGHTMOUSE')

# display mode switch from the header ends the region cleanly (grid / engine back)
q_drag(-100, -60, 100, 60)
def switch():
    with bpy.context.temp_override(window=win, area=B(), region=reg(B())):
        bpy.ops.si.display_mode(mode="Shaded")
    sp = B().spaces.active
    check(sp.overlay.show_floor and not sp.overlay.show_text and not sp.use_render_border, "display switch: grid/text/border")
    check(scene.render.engine == 'BLENDER_EEVEE', "display switch: engine not restored")
    check(not rr.has_region(win.screen, B()), "display switch: still a region")
s(switch)

# camera view: the scene border is used and the user's border comes back
def to_camera():
    B().spaces.active.region_3d.view_perspective = 'CAMERA'
s(to_camera, 0.3)
q_drag(-60, -40, 60, 40)
s(lambda: check(scene.render.use_border and abs(scene.render.border_min_x - 0.2) > 0.01, "camera: scene border not set"))
q_click()
s(lambda: check(scene.render.use_border and abs(scene.render.border_min_x - 0.2) < 1e-6
                and abs(scene.render.border_max_x - 0.4) < 1e-6, "camera: user's scene border lost %r" % (snapshot()["sborder"],)))
# C8 with two camera views (auditor's repro): set B then D, clear B first, then D -> user's border back
def D():
    return views()[3]
def d_center():
    r = reg(D())
    return r.x + r.width // 2, r.y + r.height // 2
def d_to_camera():
    D().spaces.active.region_3d.view_perspective = 'CAMERA'
s(d_to_camera, 0.3)
q_drag(-60, -40, 60, 40)                                   # region in B (camera)
def region_in_d():
    cx, cy = d_center()
    with bpy.context.temp_override(window=win, area=D(), region=reg(D())):
        rr.set_region(bpy.context, reg(D()).width // 2 - 50, reg(D()).height // 2 - 30,
                      reg(D()).width // 2 + 50, reg(D()).height // 2 + 30, area=D(), region=reg(D()))
s(region_in_d, 0.3)
q_click()                                                  # clear B first
s(lambda: check(scene.render.use_border and abs(scene.render.border_min_x - 0.2) > 0.01,
                "C8 two cams: border dropped while D still has a region"))
def clear_d():
    with bpy.context.temp_override(window=win, area=D(), region=reg(D())):
        rr.clear_region(bpy.context, area=D())
    D().spaces.active.region_3d.view_perspective = 'PERSP'
s(clear_d, 0.3)
s(lambda: check(scene.render.use_border and abs(scene.render.border_min_x - 0.2) < 1e-6
                and abs(scene.render.border_max_x - 0.4) < 1e-6, "C8 two cams: user's border lost %r" % (snapshot()["sborder"],)))
def to_persp():
    B().spaces.active.region_3d.view_perspective = 'PERSP'
s(to_persp, 0.3)

# thin drag keeps an existing region; a click in another view ends the tool without change
q_drag(-100, -60, 100, 60)
s(lambda: globals().__setitem__("thin_before", snapshot()["vcoords"]), 0.05)
q_drag(-100, 0, 100, 2)
s(lambda: check(rr.has_region(win.screen, B()) and snapshot()["vcoords"] == thin_before, "C9 thin drag changed the region"))
def click_other_view():
    a = views()[0]
    r = reg(a)
    ev('Q', 'PRESS', *center()); ev('Q', 'RELEASE', *center())
s(click_other_view, 0.15)
s(lambda: check(bool(rr._running), "C10 Q did not start the tool"))
def press_in_a():
    a = views()[0]
    r = reg(a)
    ev('MOUSEMOVE', 'NOTHING', r.x + 50, r.y + 50)
    ev('LEFTMOUSE', 'PRESS', r.x + 50, r.y + 50)
s(press_in_a, 0.05)
s(lambda: ev('LEFTMOUSE', 'RELEASE', reg(views()[0]).x + 50, reg(views()[0]).y + 50), 0.2)
s(lambda: check(not rr._running and rr.has_region(win.screen, B()), "click in another view: tool still running or region lost"))

# C11: mode off with a free-view region (B) AND a camera region (D) on: all restored
s(d_to_camera, 0.3)
s(region_in_d, 0.3)
s(lambda: check(abs(scene.render.border_min_x - 0.2) > 0.01, "C11 setup: camera region not on"))
def off():
    mode.exit_mode()
s(off, 0.3)
def after_off():
    # the Softimage workspace is gone; the restore happened on its screen before it was removed
    check(scene.render.engine == 'BLENDER_EEVEE', "mode off: engine %s" % scene.render.engine)
    check(scene.render.use_border and abs(scene.render.border_min_x - 0.2) < 1e-6, "mode off: scene border")
    check(not any(rr.KEY in scr for scr in bpy.data.screens), "mode off: saved region state left behind")
s(after_off)
s(lambda: mode.enter_mode(), 0.5)

bpy.app.timers.register(run, first_interval=0.5)
