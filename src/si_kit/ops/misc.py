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


classes = (SI_OT_unmapped, SI_OT_delete_all)


def register():
    for c in classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
