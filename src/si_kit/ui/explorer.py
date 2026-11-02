# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Alex Doss
"""Explorer, first version (spike A: drawn with Blender's own layout rows).

Opens in any view pane (Softimage view menu > Explorer), or in a floating window with key 8 (ui/view_windows.py).
The pane is a Properties editor on the Tool tab marked with the EXPLORER role (see docks.py), with a Softimage
header: [letter] [view menu] [Scope] [View] [Filter].

Tree, like Softimage's:
    Scene_Root
      object                       (parent hierarchy)
        Polygon Mesh / Light / Camera ...   (the primitive; its operators = modifiers, Clusters = vertex groups)
        Kinematics                 (constraints under it)
        Visibility, Display
        Material(s)
        child objects
Click selects (Shift adds, Ctrl toggles); clicking a property node opens its settings in a popup.

Known limits of this approach (reasons for the custom-drawn version): no per-name colours or italics, no
drag-and-drop parenting, every row is redrawn (slow beyond a few thousand rows; capped at MAX_ROWS).
"""

import bpy
from bpy.props import BoolProperty, EnumProperty, StringProperty

from . import docks

MAX_ROWS = 2500
_expanded = {"scene"}          # node keys that are open
drawn = []                     # rows of the last draw: (depth, label, node kind, selected); read by tests
last_panel = None              # Blender panel opened by the last property-node click (popups can't be queried)
found = None                   # object revealed by the last F (Find Next Selected Node)

DATA_LABEL = {'MESH': "Polygon Mesh", 'CURVE': "Curve", 'SURFACE': "Surface", 'META': "Implicit",
              'FONT': "Text", 'LIGHT': "Light", 'CAMERA': "Camera", 'ARMATURE': "Skeleton",
              'LATTICE': "Lattice", 'POINTCLOUD': "Point Cloud", 'CURVES': "Hair", 'GREASEPENCIL': "Grease Pencil",
              'VOLUME': "Volume"}
OB_ICON = {'MESH': 'OUTLINER_OB_MESH', 'CURVE': 'OUTLINER_OB_CURVE', 'LIGHT': 'OUTLINER_OB_LIGHT',
           'CAMERA': 'OUTLINER_OB_CAMERA', 'EMPTY': 'OUTLINER_OB_EMPTY', 'ARMATURE': 'OUTLINER_OB_ARMATURE',
           'LATTICE': 'OUTLINER_OB_LATTICE', 'SURFACE': 'OUTLINER_OB_SURFACE', 'FONT': 'OUTLINER_OB_FONT',
           'META': 'OUTLINER_OB_META', 'POINTCLOUD': 'OUTLINER_OB_POINTCLOUD', 'VOLUME': 'OUTLINER_OB_VOLUME'}
DATA_ICON = {'MESH': 'MESH_DATA', 'CURVE': 'CURVE_DATA', 'LIGHT': 'LIGHT_DATA', 'CAMERA': 'CAMERA_DATA',
             'ARMATURE': 'ARMATURE_DATA', 'LATTICE': 'LATTICE_DATA', 'SURFACE': 'SURFACE_DATA'}
# property node -> Blender panel shown when it is clicked
PROP_PANEL = {"Kinematics": "OBJECT_PT_transform", "Visibility": "OBJECT_PT_visibility",
              "Display": "OBJECT_PT_display"}
FILTERS = [('ALL', "All Except Params", "Objects and their properties"),
           ('OBJECTS', "Objects", "Objects only")]


def is_explorer(context):
    return docks.role(context) == "EXPLORER"


# --- operators -----------------------------------------------------------------------------------------

class SI_OT_explorer_show(bpy.types.Operator):
    """Show the Explorer in this pane"""
    bl_idname = "si.explorer_show"
    bl_label = "Explorer"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        area = context.area
        if area is None:
            return {'CANCELLED'}
        if area.type == 'PROPERTIES' and is_explorer(context):
            return {'FINISHED'}
        area.type = 'PROPERTIES'
        sp = area.spaces.active
        sp.context = 'TOOL'
        docks.mark(sp, "EXPLORER")
        sp.show_region_header = True
        for r in area.regions:
            if r.type == 'NAVIGATION_BAR' and r.width > 1:
                with context.temp_override(area=area, region=r):
                    bpy.ops.screen.region_toggle(region_type='NAVIGATION_BAR')
        return {'FINISHED'}


def _tree_objects(scene):
    """Scene objects in the order the tree draws them (parent hierarchy, names sorted)."""
    names = set(o.name for o in scene.objects)
    out = []

    def walk(ob):
        out.append(ob)
        for c in _object_children(ob, names):
            walk(c)
    for ob in sorted((o for o in scene.objects if o.parent is None), key=lambda o: o.name.lower()):
        walk(ob)
    return out


def _scroll_to(window, area, name):
    """Scroll the pane so the object's row is visible (centred if it wasn't). False while the redraw that shows the
    revealed row hasn't happened yet."""
    region = next((r for r in area.regions if r.type == 'WINDOW'), None)
    i = next((n for n, (_d, label, kind, _s) in enumerate(drawn) if label == name and kind == ""), None)
    if region is None or i is None:
        return False
    u = 20 * bpy.context.preferences.system.ui_scale
    _x, y = region.view2d.view_to_region(0, -(4 + u * i + u / 2), clip=False)
    if not u < y < region.height - u:
        with bpy.context.temp_override(window=window, area=area, region=region):
            bpy.ops.view2d.pan(deltax=0, deltay=int(y - region.height / 2))
    return True


def _scroll_later(window, area, name):
    tries = [10]

    def tick():
        tries[0] -= 1
        try:
            done = _scroll_to(window, area, name)
        except (ReferenceError, RuntimeError) as e:     # the pane was closed or changed meanwhile
            print("si_kit: explorer scroll", e)
            return None
        return None if done or tries[0] <= 0 else 0.05
    bpy.app.timers.register(tick, first_interval=0.05)


class SI_OT_explorer_find(bpy.types.Operator):
    """Find Next Selected Node (F over the Explorer): reveal the next selected object in the tree"""
    bl_idname = "si.explorer_find"
    bl_label = "Find Next Selected"
    bl_options = {'INTERNAL'}

    def invoke(self, context, event):
        global found
        if not is_explorer(context):
            return {'PASS_THROUGH'}             # F in any other Properties editor stays Blender's
        sel = [o for o in _tree_objects(context.scene) if o.select_get()]
        if not sel:
            self.report({'INFO'}, "Nothing selected")
            return {'CANCELLED'}
        names = [o.name for o in sel]
        ob = sel[(names.index(found) + 1) % len(sel)] if found in names else sel[0]
        found = ob.name
        _expanded.add("scene")
        p = ob.parent
        while p is not None:                    # open the parents only; the object itself stays as it is
            _expanded.add("ob:" + p.name)
            p = p.parent
        area, window = context.area, context.window
        area.tag_redraw()
        _scroll_later(window, area, ob.name)
        return {'FINISHED'}


class SI_OT_explorer_expand(bpy.types.Operator):
    """Expand / collapse (Shift: everything below too)"""
    bl_idname = "si.explorer_expand"
    bl_label = "Expand"
    bl_options = {'INTERNAL'}

    key: StringProperty()

    def invoke(self, context, event):
        if self.key in _expanded:
            _expanded.discard(self.key)
            if event.shift:
                for k in [k for k in _expanded if k.startswith(self.key + "/")]:
                    _expanded.discard(k)
        else:
            _expanded.add(self.key)
            if event.shift and self.key.startswith("ob:"):
                ob = bpy.data.objects.get(self.key.split("/")[0][3:])
                if ob:
                    for c in [ob] + list(ob.children_recursive):
                        _expanded.add("ob:" + c.name)
        context.area.tag_redraw()
        return {'FINISHED'}


class SI_OT_explorer_click(bpy.types.Operator):
    """Click: select (Shift: add, Ctrl: toggle). Property nodes open their settings"""
    bl_idname = "si.explorer_click"
    bl_label = "Select"
    bl_options = {'REGISTER', 'UNDO'}

    obj: StringProperty()
    prop: StringProperty()
    extend: BoolProperty(name="Extend", description="Add to the selection (Shift)", options={'SKIP_SAVE'})
    toggle: BoolProperty(name="Toggle", description="Toggle the selection (Ctrl)", options={'SKIP_SAVE'})

    def invoke(self, context, event):
        self.extend = self.extend or event.shift
        self.toggle = self.toggle or event.ctrl
        return self.execute(context)

    def execute(self, context):
        global last_panel
        ob = bpy.data.objects.get(self.obj)
        if ob is None:
            return {'CANCELLED'}
        vl = context.view_layer
        if self.prop:
            for o in vl.objects:
                if o != ob and o.select_get() and not self.extend:
                    o.select_set(False)
            ob.select_set(True)
            vl.objects.active = ob
            panel = PROP_PANEL.get(self.prop)
            if panel:
                last_panel = panel
                try:
                    bpy.ops.wm.call_panel(name=panel, keep_open=True)
                except RuntimeError as e:
                    self.report({'INFO'}, str(e))
            return {'FINISHED'}
        if ob.name not in vl.objects:
            return {'CANCELLED'}
        if self.toggle:
            ob.select_set(not ob.select_get())
        elif self.extend:
            ob.select_set(True)
        else:
            for o in vl.objects:
                if o.select_get():
                    o.select_set(False)
            ob.select_set(True)
        if ob.select_get():
            vl.objects.active = ob
        return {'FINISHED'}


# --- drawing -------------------------------------------------------------------------------------------

class _Rows:
    def __init__(self, layout):
        self.col = layout.column(align=True)
        self.n = 0
        self.full = False

    def add(self, depth, key, label, icon, expandable, op=None, selected=False, active=True):
        if self.n >= MAX_ROWS:
            if not self.full:
                self.col.label(text="... more (first version shows %d rows)" % MAX_ROWS)
                self.full = True
            return False
        self.n += 1
        drawn.append((depth, label, op[1] if op else None, selected))
        r = self.col.row(align=True)
        r.alignment = 'LEFT'           # natural widths, left to right: indent, triangle, icon + name
        r.active = active
        for _ in range(depth):
            r.label(text="", icon='BLANK1')
        if expandable:
            r.operator("si.explorer_expand", text="", emboss=False,
                       icon='DISCLOSURE_TRI_DOWN' if key in _expanded else 'DISCLOSURE_TRI_RIGHT').key = key
        else:
            r.label(text="", icon='BLANK1')
        if op is None:
            r.label(text=label, icon=icon)
        else:
            # the icon opens the Property Editor (without selecting), the name selects (Softimage)
            pp = r.operator("si.ppg_popup", text="", icon=icon, emboss=False)
            pp.obj, pp.prop = op[0], op[1]
            b = r.operator("si.explorer_click", text=label, emboss=selected, depress=selected)
            b.obj, b.prop = op
        return True


# Softimage's operator stack under the primitive, top to bottom (user + docs: operator stack regions).
# Regions by position (fallback rule of spec model.construction-mode, until regions are stored): from the first
# of these deformers upwards = Animation, below it = Modeling. Smooth, Displace, Shrinkwrap... go by position.
DEFORMERS = {'ARMATURE', 'LATTICE', 'MESH_DEFORM', 'HOOK', 'SURFACE_DEFORM', 'CURVE'}


def _stack(ob):
    """(primitive operator or None, {region: [modifiers, stack top first]})."""
    from ..ops import gn_primitives
    prim = gn_primitives.live_modifier(ob)
    regions = {"Secondary Shape Modeling": [], "Animation": [], "Shape Modeling": [], "Modeling": []}
    region = "Modeling"
    for m in ob.modifiers:                       # Blender's order: bottom of the stack first
        if m == prim:
            continue
        if m.type in DEFORMERS:
            region = "Animation"
        regions[region].append(m)
    for mods in regions.values():
        mods.reverse()                           # Softimage shows the top of the stack first
    return prim, regions


def _draw_primitive(rows, ob, key, d):
    """Polygon Mesh > [Secondary Shape Modeling, Animation, Shape Modeling, Modeling] > primitive operator > Clusters."""
    dkey = key + "/data"
    prim, regions = _stack(ob)
    shape_keys = list(ob.data.shape_keys.key_blocks)[1:] if getattr(ob.data, "shape_keys", None) else []
    groups = list(getattr(ob, "vertex_groups", []))
    rows.add(d, dkey, DATA_LABEL[ob.type], DATA_ICON.get(ob.type, 'MESH_DATA'), True, (ob.name, "Primitive"))
    if dkey not in _expanded:
        return
    for region, mods in regions.items():
        items = shape_keys if region == "Shape Modeling" else mods
        rkey = dkey + "/" + region
        rows.add(d + 1, rkey, region, 'MODIFIER_DATA' if items else 'DOT', bool(items), active=bool(items))
        if rkey in _expanded:
            for it in items:
                icon = 'SHAPEKEY_DATA' if region == "Shape Modeling" else 'MODIFIER'
                rows.add(d + 2, rkey + "/" + it.name, it.name, icon, False, (ob.name, "Operator"))
    if prim is not None:
        rows.add(d + 1, dkey + "/prim", prim.name, 'GEOMETRY_NODES', False, (ob.name, "Primitive"))
    ckey = dkey + "/clusters"
    rows.add(d + 1, ckey, "Clusters", 'GROUP_VERTEX', bool(groups), active=bool(groups))
    if ckey in _expanded:
        for g in groups:
            rows.add(d + 2, ckey + "/" + g.name, g.name, 'GROUP_VERTEX', False, (ob.name, "Cluster"))


def _object_children(ob, scene_obs):
    return sorted((c for c in ob.children if c.name in scene_obs), key=lambda o: o.name.lower())


def _draw_object(rows, ob, depth, scene_obs, show_props):
    key = "ob:" + ob.name
    kids = _object_children(ob, scene_obs)
    expandable = bool(kids) or show_props
    if not rows.add(depth, key, ob.name, OB_ICON.get(ob.type, 'OBJECT_DATA'), expandable, (ob.name, ""),
                    selected=ob.select_get(), active=ob.visible_get()):
        return
    if key not in _expanded:
        return
    d = depth + 1
    if show_props:
        if ob.type in DATA_LABEL and ob.data is not None:
            _draw_primitive(rows, ob, key, d)
        kkey = key + "/kine"
        cons = list(ob.constraints)
        rows.add(d, kkey, "Kinematics", 'EMPTY_ARROWS', bool(cons), (ob.name, "Kinematics"))
        if kkey in _expanded:
            for c in cons:
                rows.add(d + 1, kkey + "/" + c.name, c.name, 'CONSTRAINT', False, (ob.name, "Constraint"))
        rows.add(d, key + "/vis", "Visibility", 'HIDE_OFF', False, (ob.name, "Visibility"))
        rows.add(d, key + "/disp", "Display", 'RESTRICT_VIEW_OFF', False, (ob.name, "Display"))
        for slot in getattr(ob, "material_slots", []):
            if slot.material:
                rows.add(d, key + "/mat/" + slot.material.name, slot.material.name, 'MATERIAL', False,
                         (ob.name, "Material"))
    for c in kids:
        _draw_object(rows, c, d, scene_obs, show_props)


class SI_PT_explorer(bpy.types.Panel):
    bl_space_type = 'VIEW_3D'          # the Properties Tool tab draws 3D View "Tool" panels
    bl_region_type = 'UI'
    bl_category = "Tool"
    bl_label = "Explorer"
    bl_options = {'HIDE_HEADER'}
    bl_order = -200

    @classmethod
    def poll(cls, context):
        return is_explorer(context)

    def draw(self, context):
        scene = context.scene
        wm = context.window_manager
        show_props = wm.si_explorer_filter == 'ALL'
        drawn.clear()
        rows = _Rows(self.layout)
        scene_obs = set(o.name for o in scene.objects)
        rows.add(0, "scene", "Scene_Root", 'SCENE_DATA', True)
        if "scene" not in _expanded:
            return
        tops = sorted((o for o in scene.objects if o.parent is None), key=lambda o: o.name.lower())
        for ob in tops:
            _draw_object(rows, ob, 1, scene_obs, show_props)


# --- header --------------------------------------------------------------------------------------------

_orig = {}


def draw_header(self, context):
    if docks.role(context) == "PPG":
        from . import ppg
        return ppg.draw_pane_header(self.layout, context)
    if not is_explorer(context):
        return _orig["draw"](self, context)
    from . import viewport
    from ..menus import build
    layout = self.layout
    row = layout.row(align=True)
    row.label(text=viewport.view_letter_any(context))
    row.menu("SI_MT_view_menu", text="Explorer")
    layout.separator()
    for title, label in (("Explorer Scope", "Scene Root"), ("Explorer View", "View")):
        mid = build.EXTRA_IDS.get(title)
        if mid:
            layout.menu(mid, text=label)
    layout.prop(context.window_manager, "si_explorer_filter", text="")


classes = (SI_OT_explorer_show, SI_OT_explorer_find, SI_OT_explorer_expand, SI_OT_explorer_click, SI_PT_explorer)


def register():
    bpy.types.WindowManager.si_explorer_filter = EnumProperty(name="Filter", items=FILTERS, default='ALL')
    for c in classes:
        bpy.utils.register_class(c)
    cls = bpy.types.PROPERTIES_HT_header
    _orig["draw"] = cls.draw
    cls.draw = draw_header


def unregister():
    cls = bpy.types.PROPERTIES_HT_header
    if "draw" in _orig:
        cls.draw = _orig.pop("draw")
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
    del bpy.types.WindowManager.si_explorer_filter
