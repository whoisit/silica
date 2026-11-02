# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Alex Doss
"""The Softimage workspace.

The layout is a workspace saved in layout/softimage_layout.blend (built by tools/make_layout.py in a GUI Blender,
because area splitting/closing needs a real window). Entering the mode appends that workspace to the open file
(if it isn't there yet) and switches every window to it; leaving switches back to the previous workspace and
removes the appended one. Scenes and objects are never touched.
"""

import os

import bpy

WORKSPACE = "Softimage"
BLEND = os.path.join(os.path.dirname(__file__), "layout", "softimage_layout.blend")
PREV = "si_prev_workspace"


def _append():
    ws = bpy.data.workspaces.get(WORKSPACE)
    if ws is not None:
        return ws
    if not os.path.exists(BLEND):
        print("si_kit: layout file missing:", BLEND)
        return None
    with bpy.data.libraries.load(BLEND, link=False) as (src, dst):
        dst.workspaces = [n for n in src.workspaces if n == WORKSPACE]
    return bpy.data.workspaces.get(WORKSPACE)


def enter(*_args):
    ws = _append()
    if ws is None:
        return
    wm = bpy.context.window_manager
    prev = dict(wm.get(PREV, {}))
    for i, win in enumerate(wm.windows):
        if win.workspace != ws:
            prev[str(i)] = win.workspace.name
            win.workspace = ws
    wm[PREV] = prev
    from .ui import viewport
    viewport.clean_views()


def leave():
    wm = bpy.context.window_manager
    ws = bpy.data.workspaces.get(WORKSPACE)
    prev_names = dict(wm.get(PREV, {}))
    for i, win in enumerate(wm.windows):
        prev = bpy.data.workspaces.get(prev_names.get(str(i), "")) or bpy.data.workspaces.get("Layout") or next(
            (w for w in bpy.data.workspaces if w != ws), None)
        if prev is not None and win.workspace == ws:
            win.workspace = prev
    if PREV in wm:
        del wm[PREV]
    if ws is not None:
        def remove():
            w = bpy.data.workspaces.get(WORKSPACE)
            if w is not None and not any(win.workspace == w for win in bpy.context.window_manager.windows):
                try:
                    bpy.data.batch_remove([w])
                except Exception as e:
                    print("si_kit: could not remove workspace:", e)
            return None
        bpy.app.timers.register(remove, first_interval=0.1)


@bpy.app.handlers.persistent
def _on_load(*_args):
    bpy.app.timers.register(lambda: enter() and None, first_interval=0.05)


def register():
    if bpy.context.window_manager is not None:
        enter()
    bpy.app.handlers.load_post.append(_on_load)


def unregister():
    if _on_load in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_load)
    leave()
