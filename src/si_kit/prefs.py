# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Alex Doss
"""Add-on preferences: the Softimage mode switch and options."""

import bpy
from bpy.props import BoolProperty, EnumProperty


def _clean_views():
    from . import mode
    if mode.is_on():
        from .ui import viewport
        viewport.clean_views()


def get():
    addon = bpy.context.preferences.addons.get(__package__)
    return addon.preferences if addon else None


class SI_Preferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    mode_on: BoolProperty(
        name="Softimage Mode",
        description="Softimage layout, theme, menus and tools. Off = plain Blender",
        default=False,
    )
    apply_theme: BoolProperty(
        name="Softimage Theme",
        description="Apply the Softimage colours while Softimage mode is on (your theme is backed up and restored)",
        default=True,
    )

    region_engine: EnumProperty(
        name="Render Region Engine",
        description="Renderer used by the Softimage render region (Q)",
        items=[('CYCLES', "Cycles", "Path-traced, like a final render"),
               ('EEVEE', "EEVEE", "Real-time"),
               ('SCENE', "Scene Setting", "Use the scene's render engine")],
        default='CYCLES',
    )
    show_3d_cursor: BoolProperty(
        name="Show 3D Cursor",
        description="Show Blender's 3D cursor in the Softimage views (Softimage has none)",
        default=False,
        update=lambda self, ctx: _clean_views(),
    )
    ppg_on_create: BoolProperty(
        name="Popup Property Editors on Node Creation",
        description="Open the new object's Property Editor after Get > Primitive (Softimage preference)",
        default=True,
    )
    softimage_keys: BoolProperty(
        name="Softimage Keys",
        description="Softimage hotkeys and navigation in the 3D views while Softimage mode is on",
        default=True,
    )

    def draw(self, context):
        col = self.layout.column()
        col.prop(self, "region_engine")
        col.prop(self, "softimage_keys")
        col.prop(self, "show_3d_cursor")
        col.prop(self, "ppg_on_create")
        row = col.row()
        row.scale_y = 1.4
        row.operator("si.toggle_mode", text="Turn Softimage Mode Off" if self.mode_on else "Turn Softimage Mode On",
                     depress=self.mode_on)
        col.prop(self, "apply_theme")
        col.separator()
        col.label(text="Independent project: not affiliated with, endorsed or supported by Autodesk, Inc.")
        col.label(text="Softimage and XSI are trademarks of Autodesk, Inc., used only to describe the workflow.")


def register():
    bpy.utils.register_class(SI_Preferences)


def unregister():
    bpy.utils.unregister_class(SI_Preferences)
