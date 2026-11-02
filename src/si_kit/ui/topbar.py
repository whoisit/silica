# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Alex Doss
"""Softimage main menu bar in Blender's top bar.

While Softimage mode is on, TOPBAR_HT_upper_bar.draw_left draws the Softimage menus (File ... Window | Model ...
Hair) instead of Blender's. The original draw_left is put back on unregister.
"""

import bpy

_orig = {}

GROUP_1 = ("File", "Edit", "View", "Display", "Window")
GROUP_2 = ("Model", "Animate", "Render", "ICE", "Simulate", "Hair")


class SI_MT_main_menus(bpy.types.Menu):
    """Drawn through draw_collapsible, like Blender's own header menus, so the titles are flat."""
    bl_idname = "SI_MT_main_menus"
    bl_label = ""

    def draw(self, context):
        from ..menus import build
        layout = self.layout
        for title in GROUP_1:
            layout.menu(build.TOP_IDS[title], text=title)
        layout.menu("TOPBAR_MT_help", text="Help")
        layout.separator(type='LINE')
        for title in GROUP_2:
            layout.menu(build.TOP_IDS[title], text=title)


def draw_left(self, context):
    SI_MT_main_menus.draw_collapsible(context, self.layout)


def register():
    bpy.utils.register_class(SI_MT_main_menus)
    cls = bpy.types.TOPBAR_HT_upper_bar
    _orig["draw_left"] = cls.draw_left
    cls.draw_left = draw_left


def unregister():
    cls = bpy.types.TOPBAR_HT_upper_bar
    if "draw_left" in _orig:
        cls.draw_left = _orig.pop("draw_left")
    bpy.utils.unregister_class(SI_MT_main_menus)
