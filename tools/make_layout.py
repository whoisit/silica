# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Alex Doss
"""Build src/si_kit/layout/softimage_layout.blend: the Softimage workspace.

    python -I tools/make_layout.py      # opens Blender (factory settings, 1600x900) for a few seconds

Area operations (split/close/move) only work in a GUI Blender, so this re-runs itself inside one.
Result (window 1600x900, UI scale 1):
    [Module toolbar] [ Top | Camera ] [ MCP ]
                     [ Front | Right ]
    [            Timeline            ]
"""
import os, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "src", "si_kit", "layout", "softimage_layout.blend")

INSIDE = r'''
import bpy, math, sys, traceback
from mathutils import Euler, Quaternion

OUT = %(out)r
TOOLBAR_PX = 112
MCP_PX = 150
ROLE_FLAGS = {"TOOLBAR": "show_properties_physics", "MCP": "show_properties_effects"}
VIEWS = {  # role: (perspective, rotation, distance)
    "Top": ('ORTHO', Quaternion(), 30.0),
    "Camera": ('PERSP', Euler((math.radians(65), 0, math.radians(35))).to_quaternion(), 40.0),
    "Front": ('ORTHO', Euler((math.pi / 2, 0, 0)).to_quaternion(), 30.0),
    "Right": ('ORTHO', Euler((math.pi / 2, 0, math.pi / 2)).to_quaternion(), 30.0),
}

def log(*a):
    print("LAYOUT:", *a, flush=True)

def win():
    return bpy.context.window_manager.windows[0]

def areas(t=None):
    return [a for a in win().screen.areas if t is None or a.type == t]

def ov(area):
    region = next(r for r in area.regions if r.type == 'WINDOW')
    return bpy.context.temp_override(window=win(), screen=win().screen, area=area, region=region)

BASE_FLAGS = ("show_properties_strip", "show_properties_strip_modifier")   # = ui/docks.py


def mark(space, role):
    for k, f in ROLE_FLAGS.items():
        setattr(space, f, k != role)
    for f in BASE_FLAGS:
        setattr(space, f, False)

steps = []

def step(fn):
    steps.append(fn)
    return fn

@step
def s_close_outliner():
    for a in areas('OUTLINER'):
        with ov(a):
            bpy.ops.screen.area_close()
    log("areas", [(a.type, a.x, a.y, a.width, a.height) for a in areas()])

@step
def s_mcp():
    p = max(areas('PROPERTIES'), key=lambda a: a.x)
    sp = p.spaces.active
    sp.context = 'TOOL'
    mark(sp, "MCP")
    sp.show_region_header = False
    for r in p.regions:
        if r.type == 'NAVIGATION_BAR':
            with ov(p):
                bpy.ops.screen.region_toggle(region_type='NAVIGATION_BAR')
    # MCP width: move its left edge
    delta = p.width - MCP_PX
    with ov(p):
        bpy.ops.screen.area_move(x=p.x, y=p.y + p.height // 2, delta=delta)

@step
def s_split_toolbar():
    v = max(areas('VIEW_3D'), key=lambda a: a.width * a.height)
    with ov(v):
        bpy.ops.screen.area_split(direction='VERTICAL', factor=TOOLBAR_PX / v.width)

@step
def s_toolbar():
    v = min(areas('VIEW_3D'), key=lambda a: a.x)
    v.type = 'PROPERTIES'
    sp = v.spaces.active
    sp.context = 'TOOL'
    mark(sp, "TOOLBAR")
    sp.show_region_header = False

@step
def s_toolbar_nav():
    t = min(areas('PROPERTIES'), key=lambda a: a.x)
    for r in t.regions:
        if r.type == 'NAVIGATION_BAR' and r.width > 1:
            with ov(t):
                bpy.ops.screen.region_toggle(region_type='NAVIGATION_BAR')
    log("toolbar", t.x, t.width)

@step
def s_split_h():
    v = areas('VIEW_3D')[0]
    with ov(v):
        bpy.ops.screen.area_split(direction='HORIZONTAL', factor=0.5)

@step
def s_split_v():
    for v in list(areas('VIEW_3D')):
        with ov(v):
            bpy.ops.screen.area_split(direction='VERTICAL', factor=0.5)

@step
def s_views():
    vs = areas('VIEW_3D')
    if len(vs) != 4:
        log("ERROR expected 4 views, got", len(vs))
    top_y = max(a.y for a in vs)
    left_x = min(a.x for a in vs)
    for a in vs:
        top = a.y == top_y
        left = a.x == left_x
        role = ("Top" if left else "Camera") if top else ("Front" if left else "Right")
        sp = a.spaces.active
        persp, rot, dist = VIEWS[role]
        r3 = sp.region_3d
        if role == "Camera":
            r3.view_perspective = persp
            r3.view_rotation = rot
        else:
            region = next(r for r in a.regions if r.type == 'WINDOW')
            with bpy.context.temp_override(window=win(), screen=win().screen, area=a, region=region):
                bpy.ops.view3d.view_axis(type={"Top": 'TOP', "Front": 'FRONT', "Right": 'RIGHT'}[role])
        r3.view_distance = dist
        r3.view_location = (0, 0, 0)
        sp.show_region_toolbar = False
        sp.show_region_ui = False
        sp.show_region_tool_header = False
        sp.overlay.show_floor = True
        sp.overlay.show_axis_x = True
        sp.overlay.show_axis_y = True
        sp.shading.type = 'WIREFRAME' if role != "Camera" else 'SOLID'
        sp.lens = 50
        sp.clip_end = 10000
    log("views", [(a.x, a.y, a.width, a.height) for a in vs])

@step
def s_save():
    ws = win().workspace
    ws.name = "Softimage"
    win().screen.name = "Softimage"
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o)
    # Write only the workspace (and its screen), not the whole file: a full save also stores the window manager,
    # which carries the file browser's last folder (the user's home path). layout.py appends only the workspace.
    bpy.data.libraries.write(OUT, {ws}, path_remap='NONE', fake_user=True, compress=True)
    log("saved", OUT, [(a.type, a.x, a.y, a.width, a.height) for a in areas()])

def run():
    try:
        if steps:
            fn = steps.pop(0)
            log("step", fn.__name__)
            fn()
            return 0.4
    except Exception:
        log("ERROR", traceback.format_exc())
    bpy.ops.wm.quit_blender()
    return None

bpy.app.timers.register(run, first_interval=1.5)
'''


def main():
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from dev import BLENDER as blender  # $SI_BLENDER, .dev/blender_path.txt or `blender` on PATH
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    tmp = os.path.join(ROOT, ".dev", "tmp", "make_layout_inside.py")
    os.makedirs(os.path.dirname(tmp), exist_ok=True)
    open(tmp, "w", encoding="utf-8").write(INSIDE % {"out": OUT})
    env = dict(os.environ, BLENDER_USER_RESOURCES=os.path.join(ROOT, ".dev", "layout_user"))
    p = subprocess.run([blender, "--factory-startup", "--window-geometry", "0", "0", "1600", "900",
                        "--python", tmp], env=env, capture_output=True, text=True, timeout=180)
    print("\n".join(l for l in (p.stdout + p.stderr).splitlines() if l.startswith("LAYOUT") or "Error" in l))


if __name__ == "__main__":
    main()
