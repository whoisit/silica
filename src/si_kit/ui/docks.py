# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Alex Doss
"""Fixed Softimage panels (module toolbar on the left, MCP on the right).

Each dock is a Properties editor on the Tool tab with its header and tab column hidden. Its role is marked by
one hidden tab-visibility flag (the tab column is hidden, so the flag has no visible effect), which survives
saving the file:
    TOOLBAR: show_properties_physics = False
    MCP:     show_properties_effects = False
Blender's own Tool-tab panels are hidden inside these docks only (their poll is wrapped while the mode is on and
restored afterwards).
"""

import bpy
from bpy.props import EnumProperty

ROLE_FLAGS = {"TOOLBAR": "show_properties_physics", "MCP": "show_properties_effects",
              "EXPLORER": "show_properties_particles", "PPG": "show_properties_material"}
PANE_ROLES = ("EXPLORER", "PPG")      # roles shown in a viewport pane (count for the A-D letters)


# Every kit pane also hides the two Sequencer strip tabs (never shown in a 3D workflow), so a normal Properties
# editor where the user hid one tab is never taken for a kit pane (bug review 2026-11-01).
BASE_FLAGS = ("show_properties_strip", "show_properties_strip_modifier")


def space_role(space):
    """The kit role of a Properties space from its hidden tab flags, or None."""
    if any(getattr(space, f, False) for f in BASE_FLAGS):
        return None
    for r, flag in ROLE_FLAGS.items():
        if not getattr(space, flag, True) and all(getattr(space, f, True) for k, f in ROLE_FLAGS.items() if k != r):
            return r
    return None


def unmark(space):
    for f in list(ROLE_FLAGS.values()) + list(BASE_FLAGS):
        setattr(space, f, True)


def restore_panes():
    """Mode off: Explorer / PPG panes opened anywhere (any workspace) become 3D views again, flags cleared."""
    for scr in bpy.data.screens:
        for area in scr.areas:
            if area.type == 'PROPERTIES' and space_role(area.spaces.active) in PANE_ROLES:
                unmark(area.spaces.active)
                try:
                    area.type = 'VIEW_3D'
                except Exception as e:
                    print("si_kit: could not restore pane:", e)
MODULES = (("Model", "Model", ""), ("Animate", "Animate", ""), ("Render", "Render", ""),
           ("Simulate", "Simulate", ""), ("Hair", "Hair", ""), ("ICE", "ICE", ""))


def role(context):
    area = context.area
    if area is None or area.type != 'PROPERTIES':
        return None
    return space_role(area.spaces.active)


def mark(space, r):
    for k, f in ROLE_FLAGS.items():
        setattr(space, f, k != r)
    for f in BASE_FLAGS:
        setattr(space, f, False)


# --- hide Blender's Tool-tab panels inside the docks --------------------------------------------------------

_wrapped = {}    # class -> original poll (or None)


def _tool_tab_panels():
    for cls in bpy.types.Panel.__subclasses__():
        if cls.__module__.startswith(__package__.rsplit(".", 1)[0]):
            continue
        st = getattr(cls, "bl_space_type", "")
        if (st == 'VIEW_3D' and getattr(cls, "bl_region_type", "") == 'UI' and getattr(cls, "bl_category", "") == 'Tool') \
                or (st == 'PROPERTIES' and getattr(cls, "bl_context", "") in ("tool", ".workspace", "workspace")):
            yield cls


def _with_children(targets):
    """targets + every panel whose bl_parent_id chain leads to one of them, ordered parents first."""
    by_id = {getattr(c, "bl_idname", c.__name__): c for c in bpy.types.Panel.__subclasses__()}
    names = {getattr(c, "bl_idname", c.__name__) for c in targets}
    changed = True
    while changed:
        changed = False
        for n, c in by_id.items():
            if n not in names and getattr(c, "bl_parent_id", "") in names:
                names.add(n)
                changed = True

    def depth(n):
        d, c = 0, by_id.get(n)
        while c is not None and getattr(c, "bl_parent_id", ""):
            d += 1
            c = by_id.get(c.bl_parent_id)
        return d
    return [by_id[n] for n in sorted(names, key=depth) if n in by_id]


def _reregister(classes, mutate):
    """Blender keeps pointers to a registered panel's functions: changing poll in place crashes. Unregister
    (children first), change, register again (parents first)."""
    for c in reversed(classes):
        if getattr(c, "is_registered", False):
            bpy.utils.unregister_class(c)
    for c in classes:
        mutate(c)
    for c in classes:
        try:
            bpy.utils.register_class(c)
        except Exception as e:
            print("si_kit: could not re-register", c.__name__, e)


def _wrap(c):
    orig = c.__dict__.get("poll")
    func = orig.__func__ if isinstance(orig, classmethod) else None
    inherited = None
    if orig is None:
        for base in c.__mro__[1:]:
            if "poll" in base.__dict__ and base is not bpy.types.Panel:
                b = base.__dict__["poll"]
                inherited = b.__func__ if isinstance(b, classmethod) else None
                break

    _wrapped[c] = orig
    c.poll = classmethod(_make_poll(func or inherited))


def _make_poll(func):
    # exactly (cls, context): Blender checks the argument count when registering
    def poll(cls, context):
        if role(context) is not None:
            return False
        return func(cls, context) if func is not None else True
    return poll


_NONE = object()


def _unwrap(c):
    orig = _wrapped.pop(c, _NONE)
    if orig is _NONE:          # a child panel we only re-registered: leave it alone
        return
    if orig is None:
        if "poll" in c.__dict__:
            del c.poll
    else:
        c.poll = orig


def _wrap_polls():
    direct = list(_tool_tab_panels())
    direct_set = set(direct)
    _reregister(_with_children(direct), lambda c: _wrap(c) if c in direct_set else None)


def _unwrap_polls():
    _reregister(_with_children(list(_wrapped)), _unwrap)
    _wrapped.clear()


# --- module toolbar ----------------------------------------------------------------------------------------

def _draw_module(layout, title):
    from ..menus import build, data
    col = layout.column(align=True)
    header = None
    for it in data.MENUS[title]:
        if it[0] == "header":
            header = it[1]
            col.separator()
            box = col.box()
            box.label(text=header)
        elif it[0] == "menu":
            path = "/".join(x for x in (title, header, it[1]) if x)
            if it[2]:
                col.menu(build.idname(path), text=it[1])
            else:
                r = col.row()
                r.enabled = False
                r.label(text=it[1])
        elif it[0] == "item":
            path = "/".join(x for x in (title, header, it[1]) if x)
            r = col.row()
            r.enabled = False
            r.operator("si.unmapped", text=it[1]).path = path


class SI_PT_module_toolbar(bpy.types.Panel):
    # The Properties Tool tab draws 3D View sidebar panels of the "Tool" category
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Tool"
    bl_label = "Module"
    bl_options = {'HIDE_HEADER'}
    bl_order = -100

    @classmethod
    def poll(cls, context):
        return role(context) == "TOOLBAR"

    def draw(self, context):
        layout = self.layout
        layout.prop(context.window_manager, "si_module", text="")
        _draw_module(layout, context.window_manager.si_module)


# --- MCP ---------------------------------------------------------------------------------------------------

class _MCP:
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Tool"

    @classmethod
    def poll(cls, context):
        return role(context) == "MCP"


class SI_PT_mcp_select(_MCP, bpy.types.Panel):
    bl_label = "Select"
    bl_order = -50

    def draw(self, context):
        layout = self.layout
        col = layout.column(align=True)
        g = col.grid_flow(columns=2, align=True)
        in_edit = context.mode == 'EDIT_MESH'
        sel = context.tool_settings.mesh_select_mode if in_edit else (False, False, False)
        g.operator("si.select_filter", text="Object", depress=not in_edit).mode = 'OBJECT'
        g.operator("si.select_filter", text="Point", depress=in_edit and sel[0]).mode = 'VERT'
        g.operator("si.select_filter", text="Edge", depress=in_edit and sel[1]).mode = 'EDGE'
        g.operator("si.select_filter", text="Polygon", depress=in_edit and sel[2]).mode = 'FACE'
        col.separator()
        g = col.grid_flow(columns=2, align=True)
        from ..menus import build
        mcp = build.EXTRA_IDS.get("MCP")
        if mcp:
            g.menu(mcp, text="Explore")
        else:
            g.label(text="Explore")
        g.operator("si.unmapped", text="Scene").path = "MCP/Scene"
        g.operator("si.unmapped", text="Selection").path = "MCP/Selection"
        g.operator("si.unmapped", text="Clusters").path = "MCP/Clusters"
        ob = context.active_object
        col.separator()
        col.label(text=ob.name if ob else "")


class SI_PT_mcp_transform(_MCP, bpy.types.Panel):
    bl_label = "Transform"
    bl_order = -40

    def draw(self, context):
        layout = self.layout
        ob = context.active_object
        col = layout.column(align=True)
        for label, attr in (("S", "scale"), ("R", "rotation_euler"), ("T", "location")):
            box = col.column(align=True)
            for i, ax in enumerate("xyz"):
                row = box.row(align=True)
                if ob:
                    row.prop(ob, attr, index=i, text=ax)
                else:
                    row.enabled = False
                    row.label(text=ax)
                row.label(text=label if i == 0 else "")
            col.separator(factor=0.5)
        orient = context.scene.transform_orientation_slots[0]
        layout.prop(orient, "type", expand=True)


class SI_PT_mcp_snap(_MCP, bpy.types.Panel):
    bl_label = "Snap"
    bl_order = -30

    def draw(self, context):
        ts = context.tool_settings
        row = self.layout.row(align=True)
        row.prop(ts, "use_snap", text="ON", toggle=True)
        row.prop(ts, "snap_elements", text="", icon_only=True)


class SI_PT_mcp_constrain(_MCP, bpy.types.Panel):
    bl_label = "Constrain"
    bl_order = -20

    def draw(self, context):
        g = self.layout.grid_flow(columns=2, align=True)
        g.operator("object.parent_set", text="Parent")
        g.operator("object.parent_clear", text="Cut").type = 'CLEAR_KEEP_TRANSFORM'


class SI_PT_mcp_edit(_MCP, bpy.types.Panel):
    bl_label = "Edit"
    bl_order = -10

    def draw(self, context):
        g = self.layout.grid_flow(columns=2, align=True)
        g.operator("object.convert", text="Freeze").target = 'MESH'
        g.operator("collection.create", text="Group")
        g.operator("si.unmapped", text="Freeze M").path = "MCP/Edit/Freeze M"
        g.operator("si.unmapped", text="Immed").path = "MCP/Edit/Immed"


class SI_OT_select_filter(bpy.types.Operator):
    """Softimage selection filter: object or point / edge / polygon components"""
    bl_idname = "si.select_filter"
    bl_label = "Selection Filter"
    bl_options = {'REGISTER', 'UNDO'}

    mode: EnumProperty(items=[('OBJECT', "Object", ""), ('VERT', "Point", ""), ('EDGE', "Edge", ""),
                              ('FACE', "Polygon", "")])

    def execute(self, context):
        ob = context.active_object
        if self.mode == 'OBJECT':
            if context.mode != 'OBJECT':
                bpy.ops.object.mode_set(mode='OBJECT')
            return {'FINISHED'}
        if ob is None or ob.type != 'MESH':
            self.report({'WARNING'}, "Select a polygon mesh first")
            return {'CANCELLED'}
        from ..ops import gn_primitives
        if gn_primitives.freeze_for_edit(context, ob):
            self.report({'INFO'}, "%s frozen for component editing (undo to get the live primitive back)" % ob.name)
        if context.mode != 'EDIT_MESH':
            bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_mode(type=self.mode)
        return {'FINISHED'}


classes = (SI_OT_select_filter, SI_PT_module_toolbar, SI_PT_mcp_select, SI_PT_mcp_transform, SI_PT_mcp_snap,
           SI_PT_mcp_constrain, SI_PT_mcp_edit)


def register():
    bpy.types.WindowManager.si_module = EnumProperty(name="Module", items=MODULES, default="Model")
    for c in classes:
        bpy.utils.register_class(c)
    _wrap_polls()


def unregister():
    restore_panes()
    _unwrap_polls()
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
    del bpy.types.WindowManager.si_module
