# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Alex Doss
"""Softimage tools: tap a key = sticky tool, hold it = "supra" tool (active while held, then back to the
previous sticky tool).

si.tool_key(tool=...) is bound to each tool key (keymap.py). One Softimage tool is active at a time; the
mouse cursor shows which. Mouse actions go to the 3D view under the cursor, so a sticky tool works in all views.

    S  navigation:  left = track (pan), middle = dolly, right = orbit
    Z  pan / zoom:  left = pan, middle / right = zoom
    O  orbit, P  dolly: any button
    V / C / X  translate / rotate / scale: drag anywhere = transform the selection, click = select
    Space / T / E / Y  select objects / points / edges / polygons (Blender's box select tool)
Esc ends the tool and goes back to selection.
"""

import time

import bpy
from bpy.props import BoolProperty, EnumProperty, StringProperty

HOLD = 0.25   # seconds: shorter press = tap (sticky), longer = hold (supra)

NAV = {
    'NAV': {'LEFTMOUSE': "view3d.move", 'MIDDLEMOUSE': "view3d.zoom", 'RIGHTMOUSE': "view3d.rotate"},
    'PANZOOM': {'LEFTMOUSE': "view3d.move", 'MIDDLEMOUSE': "view3d.zoom", 'RIGHTMOUSE': "view3d.zoom"},
    'ORBIT': {'LEFTMOUSE': "view3d.rotate", 'MIDDLEMOUSE': "view3d.rotate", 'RIGHTMOUSE': "view3d.rotate"},
    'DOLLY': {'LEFTMOUSE': "view3d.dolly", 'MIDDLEMOUSE': "view3d.dolly", 'RIGHTMOUSE': "view3d.dolly"},
}
XFORM = {'MOVE': ("transform.translate", "builtin.move"), 'ROTATE': ("transform.rotate", "builtin.rotate"),
         'SCALE': ("transform.resize", "builtin.scale")}
SELECT = {'SELECT': None, 'POINT': 'VERT', 'EDGE': 'EDGE', 'POLY': 'FACE'}
CURSOR = {'NAV': 'HAND', 'PANZOOM': 'ZOOM_IN', 'ORBIT': 'HAND_CLOSED', 'DOLLY': 'SCROLL_Y',
          'MOVE': 'SCROLL_XY', 'ROTATE': 'CROSSHAIR', 'SCALE': 'MOVE_X'}
LABEL = {
    'NAV': "Navigation   L: Track   M: Dolly   R: Orbit", 'PANZOOM': "Pan / Zoom   L: Pan   M/R: Zoom",
    'ORBIT': "Orbit", 'DOLLY': "Dolly",
    'MOVE': "Translate   drag: move the selection   click: select",
    'ROTATE': "Rotate   drag: rotate the selection   click: select",
    'SCALE': "Scale   drag: scale the selection   click: select",
}
# keys that start another Softimage tool: they end the running one
TOOL_KEYS = {'S', 'Z', 'O', 'P', 'V', 'C', 'X', 'SPACE', 'T', 'E', 'Y', 'U', 'I', 'Q'}
BUTTONS = {'LEFTMOUSE', 'MIDDLEMOUSE', 'RIGHTMOUSE'}

ITEMS = [(k, k.title(), "") for k in list(NAV) + list(XFORM) + list(SELECT)]

state = {"sticky": 'SELECT', "active": None}   # last sticky tool; running modal operator


def view_under_mouse(context, event):
    """(area, region) of the 3D view main region under the mouse, or (None, None)."""
    x, y = event.mouse_x, event.mouse_y
    for area in context.window.screen.areas:
        if area.type != 'VIEW_3D':
            continue
        for region in area.regions:
            if region.type == 'WINDOW' and region.x <= x < region.x + region.width \
                    and region.y <= y < region.y + region.height:
                return area, region
    return None, None


def _call(context, area, region, op, **kw):
    mod, name = op.split(".")
    with context.temp_override(window=context.window, area=area, region=region):
        return getattr(getattr(bpy.ops, mod), name)('INVOKE_DEFAULT', **kw)


def _set_tool(idname):
    try:
        bpy.ops.wm.tool_set_by_id(name=idname)
    except Exception as e:
        print("si_kit: tool", idname, e)


def activate_select(context, kind):
    """Space / T / E / Y: object or component selection with Blender's box select tool."""
    ob = context.active_object
    comp = SELECT[kind]
    if comp:
        if ob is None or ob.type != 'MESH':
            return False
        from . import gn_primitives
        frozen = gn_primitives.freeze_for_edit(context, ob)
        if frozen:
            state["message"] = "%s frozen for component editing (undo to get the live primitive back)" % ob.name
        if context.mode != 'EDIT_MESH':
            bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_mode(type=comp)
    elif context.mode != 'OBJECT' and ob is not None:
        bpy.ops.object.mode_set(mode='OBJECT')
    _set_tool("builtin.select_box")
    return True


def restore_sticky(context):
    """Back to the last sticky tool after a held (supra) tool."""
    kind = state["sticky"]
    if kind in SELECT:
        _set_tool("builtin.select_box")
    else:
        bpy.ops.si.tool_key('INVOKE_DEFAULT', tool=kind, sticky_start=True)


def end_active(context):
    op = state.get("active")
    if op is not None:
        op.cleanup(context)


class SI_OT_tool_key(bpy.types.Operator):
    """Softimage tool: tap for a sticky tool, hold for a temporary one"""
    bl_idname = "si.tool_key"
    bl_label = "Softimage Tool"
    bl_options = {'INTERNAL'}

    tool: EnumProperty(items=ITEMS)
    key: StringProperty(options={'SKIP_SAVE'})
    sticky_start: BoolProperty(default=False, options={'SKIP_SAVE', 'HIDDEN'})

    @classmethod
    def poll(cls, context):
        return context.window is not None and context.area is not None and context.area.type == 'VIEW_3D'

    # --- lifecycle ---
    def invoke(self, context, event):
        end_active(context)
        self.t0 = time.monotonic()
        self.key_type = self.key or event.type
        self.sticky = self.sticky_start
        self.dead = False
        self.press = None           # LMB press position while waiting for a drag (transform tools)
        if self.tool in SELECT:
            if not activate_select(context, self.tool):
                self.report({'WARNING'}, "Select a polygon mesh first")
                return {'CANCELLED'}
            if state.pop("message", None):
                self.report({'INFO'}, "%s frozen for component editing (undo to get the live primitive back)"
                            % context.active_object.name)
            if self.sticky:
                state["sticky"] = self.tool
                return {'FINISHED'}
            self.running = False
            context.window_manager.modal_handler_add(self)   # only to tell tap from hold
            return {'RUNNING_MODAL'}
        if self.tool in XFORM:
            _set_tool(XFORM[self.tool][1])                    # its gizmo shows the transform space
        context.window.cursor_modal_set(CURSOR[self.tool])
        context.workspace.status_text_set(LABEL[self.tool] + ("   (sticky, Esc: end)" if self.sticky else ""))
        self.running = True
        state["active"] = self
        if self.sticky:
            state["sticky"] = self.tool
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def cleanup(self, context):
        if self.dead:
            return
        self.dead = True
        if self.running:
            try:
                context.window.cursor_modal_restore()
                context.workspace.status_text_set(None)
            except Exception:
                pass
        if state.get("active") is self:
            state["active"] = None

    # --- events ---
    def modal(self, context, event):
        if self.dead:
            return {'FINISHED', 'PASS_THROUGH'}
        held = time.monotonic() - self.t0 >= HOLD
        if not self.sticky and event.type == self.key_type:
            if event.value == 'PRESS':
                return {'RUNNING_MODAL'}           # key repeat while held
            if event.value == 'RELEASE':
                if held:                           # supra: back to the previous sticky tool
                    self.cleanup(context)
                    restore_sticky(context)
                    return {'FINISHED'}
                self.sticky = True                 # tap: stays
                state["sticky"] = self.tool
                if self.tool in SELECT:
                    return {'FINISHED'}
                context.workspace.status_text_set(LABEL[self.tool] + "   (sticky, Esc: end)")
                return {'RUNNING_MODAL'}
        if self.tool in SELECT:
            return {'PASS_THROUGH'}                # Blender's select tool works while the key is held
        if event.value == 'PRESS' and event.type in TOOL_KEYS:
            self.cleanup(context)
            return {'FINISHED', 'PASS_THROUGH'}    # the key starts the next tool
        if event.type == 'ESC' and event.value == 'PRESS':
            self.cleanup(context)
            state["sticky"] = 'SELECT'
            _set_tool("builtin.select_box")
            return {'FINISHED'}
        if event.type not in BUTTONS and event.type != 'MOUSEMOVE':
            return {'PASS_THROUGH'}
        area, region = view_under_mouse(context, event)
        if area is None:
            self.press = None
            return {'PASS_THROUGH'}                # menus, headers, other editors work as usual
        if self.tool in NAV:
            op = NAV[self.tool].get(event.type)
            if op and event.value == 'PRESS':
                try:
                    _call(context, area, region, op)
                except Exception as e:
                    print("si_kit: nav", op, e)
                return {'RUNNING_MODAL'}
            return {'RUNNING_MODAL'} if event.type in BUTTONS else {'PASS_THROUGH'}
        return self._xform_event(context, event, area, region)

    def _xform_event(self, context, event, area, region):
        """Press on a gizmo axis = locked to that axis; on its centre = free. Elsewhere the button picks the
        axis (left = X, middle = up / Blender Z, right = depth / Blender Y). A left click without dragging selects."""
        if event.type in BUTTONS and event.value == 'PRESS':
            local = (event.mouse_x - region.x, event.mouse_y - region.y)
            picked = gizmo_pick(context, area, region, local, self.tool)
            if picked is None:
                picked = BUTTON_AXIS[event.type]
            self.press = (event.mouse_x, event.mouse_y, event.type, picked)
            return {'RUNNING_MODAL'}
        if event.type == 'MOUSEMOVE' and self.press is not None:
            thr = context.preferences.inputs.drag_threshold_mouse
            if abs(event.mouse_x - self.press[0]) + abs(event.mouse_y - self.press[1]) > thr:
                button, axis = self.press[2], self.press[3]
                self.press = None
                start_transform(context, area, region, self.tool, axis, button)
            return {'RUNNING_MODAL'}
        if event.type in BUTTONS and event.value == 'RELEASE':
            press, self.press = self.press, None
            if press is not None and press[2] == 'LEFTMOUSE' and event.type == 'LEFTMOUSE':
                loc = (event.mouse_x - region.x, event.mouse_y - region.y)
                try:                                   # a click: select what is under the mouse
                    with context.temp_override(window=context.window, area=area, region=region):
                        bpy.ops.view3d.select(location=loc, deselect_all=True)
                except Exception as e:
                    print("si_kit: select", e)
            elif press is not None and press[2] == 'RIGHTMOUSE' and event.type == 'RIGHTMOUSE':
                with context.temp_override(window=context.window, area=area, region=region):
                    menu = "VIEW3D_MT_edit_mesh_context_menu" if context.mode == 'EDIT_MESH' \
                        else "VIEW3D_MT_object_context_menu"
                    bpy.ops.wm.call_menu(name=menu)
            return {'RUNNING_MODAL'}
        return {'PASS_THROUGH'}


# --- transform tools: gizmo axis picking ---------------------------------------------------------------------

# Softimage: left = X, middle = Y (up), right = Z. Blender is Z-up: middle = Z, right = Y.
BUTTON_AXIS = {'LEFTMOUSE': 0, 'MIDDLEMOUSE': 2, 'RIGHTMOUSE': 1}
PICK_PX = 10      # how close to an axis counts as "on it"
CENTER_PX = 14


def _normal_matrix(context):
    """Orientation of the selected components (Blender's NORMAL): Z = average normal of the selection."""
    import bmesh
    from mathutils import Matrix, Vector
    ob = context.edit_object
    if ob is None or ob.type != 'MESH':
        return None
    bm = bmesh.from_edit_mesh(ob.data)
    nm = ob.matrix_world.to_3x3().inverted_safe().transposed()
    faces = [f for f in bm.faces if f.select]
    if faces:
        n = sum((f.normal for f in faces), Vector())
    else:
        n = sum((v.normal for v in bm.verts if v.select), Vector())
    if n.length < 1e-9:
        return None
    z = (nm @ n).normalized()
    edges = [e for e in bm.edges if e.select]
    if edges and not faces:
        e = edges[0]
        t = ob.matrix_world.to_3x3() @ (e.verts[1].co - e.verts[0].co)
    else:
        t = Vector((1, 0, 0)) if abs(z.x) < 0.9 else Vector((0, 1, 0))
    x = (t - z * t.dot(z))
    if x.length < 1e-9:
        x = z.orthogonal()
    x.normalize()
    y = z.cross(x)
    return Matrix((x, y, z)).transposed()


def _orientation(context, rv3d):
    """(orientation type passed to Blender's transform, 3x3 matrix used to find the gizmo axes on screen).
    Softimage semantics: in component mode "Local" is the component's own frame = Blender's NORMAL."""
    from mathutils import Matrix
    slot_obj = context.scene.transform_orientation_slots[0]
    slot = slot_obj.type
    ob = context.active_object
    if slot == 'LOCAL' and context.mode == 'EDIT_MESH':
        slot = 'NORMAL'
    if slot == 'NORMAL' and context.mode == 'EDIT_MESH':
        m = _normal_matrix(context)
        if m is not None:
            return slot, m
    if slot in ('LOCAL', 'NORMAL', 'GIMBAL', 'PARENT') and ob is not None:
        mw = ob.matrix_world.to_3x3().normalized()
        if slot == 'PARENT' and ob.parent is not None:
            mw = ob.parent.matrix_world.to_3x3().normalized()
        return slot, mw
    if slot == 'VIEW':
        return slot, rv3d.view_rotation.to_matrix()
    if slot == 'CURSOR':
        return slot, context.scene.cursor.matrix.to_3x3().normalized()
    if slot not in ('GLOBAL',) and getattr(slot_obj, "custom_orientation", None) is not None:
        return slot, slot_obj.custom_orientation.matrix.to_3x3().normalized()     # a custom orientation
    return slot, Matrix.Identity(3)


def _pivot(context):
    from mathutils import Vector
    if context.mode == 'EDIT_MESH':
        import bmesh
        ob = context.edit_object
        bm = bmesh.from_edit_mesh(ob.data)
        pts = [ob.matrix_world @ v.co for v in bm.verts if v.select]
    else:
        pts = [o.matrix_world.translation for o in context.selected_objects]
    if not pts:
        return None
    return sum(pts, Vector()) / len(pts)


def _seg_dist(p, a, b):
    ab = b - a
    t = max(0.0, min(1.0, (p - a).dot(ab) / max(ab.length_squared, 1e-9)))
    return (a + ab * t - p).length


def gizmo_pick(context, area, region, mouse, tool):
    """Which axis of the transform gizmo is under the mouse: 0/1/2, 'CENTER', or None (not on the gizmo).
    Mirrors Blender's gizmo: screen-constant size (Preferences > Viewport > Gizmo Size) at the pivot."""
    import math
    from bpy_extras.view3d_utils import location_3d_to_region_2d
    from mathutils import Vector
    rv3d = area.spaces.active.region_3d
    pivot = _pivot(context)
    if pivot is None or rv3d is None:
        return None
    p2 = location_3d_to_region_2d(region, rv3d, pivot)
    if p2 is None:
        return None
    m = Vector(mouse)
    if (m - p2).length < CENTER_PX:
        return 'CENTER'
    right = rv3d.view_rotation @ Vector((1, 0, 0))
    q2 = location_3d_to_region_2d(region, rv3d, pivot + right)
    if q2 is None:
        return None
    px_per_unit = max((q2 - p2).length, 1e-6)
    size = context.preferences.view.gizmo_size * context.preferences.system.ui_scale
    length = size / px_per_unit
    _slot, mat = _orientation(context, rv3d)
    best, best_d = None, PICK_PX
    for i in range(3):
        axis = mat.col[i].normalized()
        if tool == 'ROTATE':
            # ring around the axis, radius ~ gizmo size
            u = axis.orthogonal().normalized()
            v = axis.cross(u)
            ring = [location_3d_to_region_2d(region, rv3d, pivot + (u * math.cos(a) + v * math.sin(a)) * length * 0.9)
                    for a in [2 * math.pi * k / 48 for k in range(49)]]
            ring = [r for r in ring if r is not None]
            d = min((_seg_dist(m, a, b) for a, b in zip(ring, ring[1:])), default=1e9)
        else:
            e2 = location_3d_to_region_2d(region, rv3d, pivot + axis * length)
            if e2 is None:
                continue
            d = _seg_dist(m, p2 + (e2 - p2) * 0.15, e2)
        if d < best_d:
            best, best_d = i, d
    return best


def start_transform(context, area, region, tool, axis, button):
    """Run Blender's transform modally, locked to `axis` (0/1/2) or free ('CENTER')."""
    rv3d = area.spaces.active.region_3d
    slot, _mat = _orientation(context, rv3d)
    op = XFORM[tool][0]
    kw = {"release_confirm": True}
    if axis == 'CENTER':
        if tool == 'ROTATE':
            op = "transform.trackball"
    else:
        lock = tuple(i == axis for i in range(3))
        kw.update(constraint_axis=lock, orient_type=slot)
        if tool == 'ROTATE':
            kw["orient_axis"] = "XYZ"[axis]
    try:
        _call(context, area, region, op, **kw)
    except Exception as e:
        print("si_kit: transform", op, e)


class SI_OT_frame(bpy.types.Operator):
    """Softimage A / F / R: frame all, frame selection, reset camera (view under the mouse)"""
    bl_idname = "si.frame"
    bl_label = "Frame"
    bl_options = {'INTERNAL'}

    what: EnumProperty(items=[('ALL', "Frame All", ""), ('SELECTION', "Frame Selection", ""),
                              ('RESET', "Reset Camera", "")])

    @classmethod
    def poll(cls, context):
        return context.area is not None and context.area.type == 'VIEW_3D'

    def execute(self, context):
        if self.what == 'ALL':
            bpy.ops.view3d.view_all(center=False)
        elif self.what == 'SELECTION':
            bpy.ops.view3d.view_selected()
        else:
            from ..ui import viewport
            viewport.reset_view(context.area)
        return {'FINISHED'}


class SI_OT_hide_toggle(bpy.types.Operator):
    """Softimage H: hide the selection, or unhide everything when nothing is selected"""
    bl_idname = "si.hide_toggle"
    bl_label = "Hide/Unhide Selection"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        if context.mode == 'EDIT_MESH':
            bpy.ops.mesh.hide(unselected=False)
            return {'FINISHED'}
        if context.selected_objects:
            bpy.ops.object.hide_view_set(unselected=False)
        else:
            bpy.ops.object.hide_view_clear()
        return {'FINISHED'}


class SI_OT_grid_toggle(bpy.types.Operator):
    """Softimage G: show / hide the grid in the view under the mouse"""
    bl_idname = "si.grid_toggle"
    bl_label = "Show/Hide Grid"
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, context):
        return context.space_data is not None and context.space_data.type == 'VIEW_3D'

    def execute(self, context):
        ov = context.space_data.overlay
        on = not (ov.show_floor or ov.show_ortho_grid)
        ov.show_floor = on
        ov.show_ortho_grid = on
        return {'FINISHED'}


class SI_OT_switch_module(bpy.types.Operator):
    """Softimage 1-4 (Ctrl+2 Hair, Ctrl+4 Simulate): switch the module toolbar"""
    bl_idname = "si.switch_module"
    bl_label = "Switch Toolbar"
    bl_options = {'INTERNAL'}

    module: StringProperty()

    def invoke(self, context, event):
        # Ctrl+digit in a node editor outside the Render Tree stays Blender's viewer shortcut
        area = context.area
        if event.ctrl and area is not None and area.type == 'NODE_EDITOR':
            from ..ui import node_presets
            if not node_presets.is_active(context):
                return {'PASS_THROUGH'}
        return self.execute(context)

    def execute(self, context):
        context.window_manager.si_module = self.module
        for w in context.window_manager.windows:      # the left dock may be in another window than the key
            for a in w.screen.areas:
                a.tag_redraw()
        return {'FINISHED'}


classes = (SI_OT_tool_key, SI_OT_frame, SI_OT_hide_toggle, SI_OT_grid_toggle, SI_OT_switch_module)


def register():
    state["sticky"] = 'SELECT'
    state["active"] = None
    for c in classes:
        bpy.utils.register_class(c)


def unregister():
    try:
        end_active(bpy.context)
    except Exception:
        pass
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
