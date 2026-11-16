# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Alex Doss
"""Small operators shared by menus and docks."""

import bpy
from bpy.props import StringProperty


class SI_OT_unmapped(bpy.types.Operator):
    """Placeholder for a Softimage menu item the kit doesn't do yet (always drawn greyed out)"""
    bl_idname = "si.unmapped"
    bl_label = "Not in the kit yet"

    path: StringProperty(options={'HIDDEN', 'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        return False

    @classmethod
    def description(cls, context, props):
        return "Not in Silica yet (%s)" % props.path.replace("/", " > ")

    def execute(self, context):
        return {'CANCELLED'}


class SI_OT_delete_all(bpy.types.Operator):
    """Delete every object in the scene (Softimage Edit > Delete All)"""
    bl_idname = "si.delete_all"
    bl_label = "Delete All"
    bl_options = {'REGISTER', 'UNDO'}

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        obs = list(context.scene.objects)
        bpy.data.batch_remove(obs)
        return {'FINISHED'}


class SI_OT_unhide_all(bpy.types.Operator):
    """Unhide All Objects (Softimage Shift+H): every hidden object of the view layer comes back, in the view and
    the render, like H brings one back"""
    bl_idname = "si.unhide_all"
    bl_label = "Unhide All Objects"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        vl = context.view_layer
        n = 0
        for o in vl.objects:
            if o.hide_get(view_layer=vl):
                o.hide_set(False, view_layer=vl)
                o.hide_render = False
                n += 1
        if not n:
            self.report({'INFO'}, "Nothing hidden")
        return {'FINISHED'}


class SI_OT_reset_transforms(bpy.types.Operator):
    """Reset All Transforms (Softimage Ctrl+Shift+R): position, rotation and scale of the selected objects back to
    their rest values (Blender's Clear Location / Rotation / Scale together)"""
    bl_idname = "si.reset_transforms"
    bl_label = "Reset All Transforms"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT' and bool(context.selected_editable_objects)

    def execute(self, context):
        bpy.ops.object.location_clear()
        bpy.ops.object.rotation_clear()
        bpy.ops.object.scale_clear()
        return {'FINISHED'}


classes = (SI_OT_unmapped, SI_OT_delete_all, SI_OT_unhide_all, SI_OT_reset_transforms)


def register():
    for c in classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
