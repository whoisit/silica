# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Alex Doss
"""Softimage mode on/off.

Entering registers MODE_MODULES in order; leaving unregisters them in reverse, and each module's unregister
puts back what it changed (theme restored from its backup, top bar draw function restored, built-in panel
polls restored, Softimage workspace removed). Nothing else of Blender's is modified.
"""

import bpy

_active = []     # modules registered by enter_mode, in order


def _mode_modules():
    from . import theme, keymap, layout
    from .ops import primitives, misc, tools, render_region, import_scn
    from .menus import build as menus
    from .ui import topbar, docks, viewport, viewport_tools, explorer, ppg, node_presets, view_windows
    return (theme, misc, primitives, tools, render_region, import_scn, menus, docks, ppg, explorer, topbar,
            viewport_tools, viewport, node_presets, view_windows, layout, keymap)


def is_on():
    return bool(_active)


def enter_mode():
    if _active:
        return
    for m in _mode_modules():
        m.register()
        _active.append(m)
    p = _prefs()
    if p and not p.mode_on:
        p.mode_on = True


def exit_mode(keep_flag=False):
    while _active:
        m = _active.pop()
        try:
            m.unregister()
        except Exception as e:  # never leave Blender half-switched
            print("si_kit: unregister failed for", m.__name__, e)
    if not keep_flag:
        p = _prefs()
        if p and p.mode_on:
            p.mode_on = False


def _prefs():
    from . import prefs
    return prefs.get()


class SI_OT_toggle_mode(bpy.types.Operator):
    bl_idname = "si.toggle_mode"
    bl_label = "Softimage Mode"
    bl_description = "Switch between the Softimage layout/menus/theme and plain Blender"

    def execute(self, context):
        if is_on():
            exit_mode()
            self.report({'INFO'}, "Softimage mode off")
        else:
            enter_mode()
            self.report({'INFO'}, "Softimage mode on")
        for w in context.window_manager.windows:
            for a in w.screen.areas:
                a.tag_redraw()
        return {'FINISHED'}


def _topbar_switch(self, context):
    """Always-visible switch at the right end of Blender's top bar."""
    if context.region is not None and context.region.alignment != 'RIGHT':
        return
    self.layout.operator("si.toggle_mode", text="SI", depress=is_on())


def restore_on_startup():
    def later():
        p = _prefs()
        if p and p.mode_on and not is_on():
            enter_mode()
        return None
    bpy.app.timers.register(later, first_interval=0.2)


def register():
    bpy.utils.register_class(SI_OT_toggle_mode)
    bpy.types.TOPBAR_HT_upper_bar.append(_topbar_switch)


def unregister():
    bpy.types.TOPBAR_HT_upper_bar.remove(_topbar_switch)
    bpy.utils.unregister_class(SI_OT_toggle_mode)
