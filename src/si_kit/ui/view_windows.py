# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Alex Doss
"""Softimage view shortcuts 5-0 as floating windows (spec ui.view-keys).

5 Browser, 6 Scene Layer Manager, 7 Render Tree, 8 Explorer, 9 Schematic, 0 Animation Editor. Each opens a small
temporary Blender window (screen.info_log_show, then its single area is turned into the view's editor); the same
key again closes it. The kit's view windows carry an ID property on their screen ("si_view"), so they are found
again after being closed by hand or after a file saved with them open is loaded.
"""

import bpy
from bpy.props import EnumProperty

MARK = "si_view"
VIEWS = (   # (id, label, key)
    ('BROWSER', "Browser", 'FIVE'),
    ('LAYERS', "Scene Layer Manager", 'SIX'),
    ('RENDER_TREE', "Render Tree", 'SEVEN'),
    ('EXPLORER', "Explorer", 'EIGHT'),
    ('SCHEMATIC', "Schematic", 'NINE'),
    ('ANIMATION', "Animation Editor", 'ZERO'),
)


def view_windows():
    """{view id: window} of the kit's open view windows."""
    out = {}
    for w in bpy.context.window_manager.windows:
        scr = w.screen
        v = scr.get(MARK) if scr is not None else None
        if v:
            out[v] = w
    return out


def _setup(view, window, area):
    """Turn the new window's single area into the view's editor."""
    if view == 'BROWSER':
        area.ui_type = 'FILES'
    elif view == 'LAYERS':                 # Softimage layers ~ Blender collections, with their toggles
        area.type = 'OUTLINER'
        sp = area.spaces.active
        sp.display_mode = 'VIEW_LAYER'
        sp.use_filter_object = False
        sp.show_restrict_column_viewport = True
        sp.show_restrict_column_select = True
        sp.show_restrict_column_render = True
    elif view == 'SCHEMATIC':              # stand-in: objects as a parent / child hierarchy
        area.type = 'OUTLINER'
        sp = area.spaces.active
        sp.display_mode = 'VIEW_LAYER'
        sp.use_filter_object = True
        sp.use_filter_children = True
        sp.use_filter_collection = False
    elif view == 'RENDER_TREE':
        area.ui_type = 'ShaderNodeTree'
    elif view == 'ANIMATION':
        area.ui_type = 'FCURVES'
    elif view == 'EXPLORER':
        with bpy.context.temp_override(window=window, screen=window.screen, area=area):
            bpy.ops.si.explorer_show()


def close(window):
    with bpy.context.temp_override(window=window):
        bpy.ops.wm.window_close()


def open_view(context, view):
    """Open the view's floating window; returns it (None if Blender didn't open one)."""
    wm = context.window_manager
    before = {w.as_pointer() for w in wm.windows}
    with context.temp_override(window=context.window):
        bpy.ops.screen.info_log_show()
    new = [w for w in wm.windows if w.as_pointer() not in before]
    if not new and context.area is not None:           # Info log window already open (reused): duplicate an area
        with context.temp_override(window=context.window, area=context.area):
            bpy.ops.screen.area_dupli('INVOKE_DEFAULT')
        new = [w for w in wm.windows if w.as_pointer() not in before]
    if not new:
        return None
    w = new[0]
    w.screen[MARK] = view
    _setup(view, w, w.screen.areas[0])
    return w


class SI_OT_view_window(bpy.types.Operator):
    """Softimage view shortcut: open the view in a floating window (the same key again closes it)"""
    bl_idname = "si.view_window"
    bl_label = "View Shortcut"
    bl_options = {'INTERNAL'}

    view: EnumProperty(items=[(v, label, "") for v, label, _k in VIEWS])

    def execute(self, context):
        w = view_windows().get(self.view)
        if w is not None:
            close(w)
            return {'FINISHED'}
        if open_view(context, self.view) is None:
            self.report({'WARNING'}, "Blender did not open a window")
            return {'CANCELLED'}
        return {'FINISHED'}


classes = (SI_OT_view_window,)


def register():
    for c in classes:
        bpy.utils.register_class(c)


def unregister():
    for w in list(view_windows().values()):
        try:
            close(w)
        except (RuntimeError, ReferenceError):
            pass
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
