# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Alex Doss
"""Property Editor (PPG), first version. Spec: features/properties/ppg/spec.md.

Two forms (user decision 2026-11-01): a docked PPG pane (a viewport pane, Recycle = follows the selection, or Lock)
and a quick popup (Enter over a 3D view, the object icon in the Explorer, after Get > Primitive).
Content = property sets as tabs (Softimage names and groups, from the captures in reference/screens/ppg):
    live primitive: <Cube> (Name, Length ...), Polygon Mesh, Geometry (Subdivisions U / V / Base)
    light: Light; camera: Camera; every object: Kinematics (Scaling / Rotation + Order / Position),
    Visibility (General / Rendering), Display
Animation divots = Blender's keyframe decorators (right of the field until the PPG is custom-drawn).
Revert = every shown value back to what it was when this PPG (pane or popup) started showing the object.
Objects are tracked by reference (pointer properties) and session id, never by name.
"""

import bpy
from bpy.props import BoolProperty, PointerProperty, StringProperty

from . import docks

_snapshots = {}        # (where, object session_uid) -> {path: value}
draw_errors = []       # drawing problems (tests fail on any)
_pane_shows = [None]   # session_uid of the object the docked pane currently shows (its Revert point is renewed
                       # whenever the pane starts showing an object: pane opened, or Recycle switching objects)
drawn_rows = {}        # tab -> rows drawn last time (tests)


# --- property sets ------------------------------------------------------------------------------------------
# A row path: ("ob", attr) | ("data", attr) | ("mod", modifier name, socket name) | ("grey", label)
# ("rot",) = the object's rotation in its current rotation mode

def _row(path, label=None, **kw):
    return (path, label, kw)


def _rotation_attr(ob):
    return {'QUATERNION': "rotation_quaternion", 'AXIS_ANGLE': "rotation_axis_angle"}.get(ob.rotation_mode,
                                                                                          "rotation_euler")


def property_sets(ob):
    """[(tab, [(section, [row, ...]), ...]), ...] for this object, Softimage names (tabs keep their order)."""
    from ..ops import gn_primitives as gn
    tabs = []
    mod = gn.live_modifier(ob)
    name_row = ("", [_row(("ob", "name"), "Name")])
    if mod is not None:
        kind = mod.node_group.get("si_kit_kind")
        params = [p[0] for p in gn.PARAMS.get(kind, ())]
        main = [_row(("mod", mod.name, p), p) for p in params if not p.startswith("Subdivisions")]
        subd = [_row(("mod", mod.name, p), p.replace("Subdivisions ", "")) for p in params if p.startswith("Subdivisions")]
        tabs.append((mod.name, [name_row, (mod.name, main)]))
        tabs.append(("Polygon Mesh", [("Polygon Mesh", [_row(("grey", "Subdivision Rule: Catmull-Clark"))])]))
        tabs.append(("Geometry", [("Subdivisions", subd)]))
    elif ob.type == 'LIGHT':
        rows = [_row(("data", "type"), "Type"), _row(("data", "color"), "Color"), _row(("data", "energy"), "Intensity"),
                _row(("data", "use_shadow"), "Shadows")]
        if ob.data.type == 'SPOT':
            rows += [_row(("data", "spot_size"), "Cone Angle"), _row(("data", "spot_blend"), "Spread")]
        tabs.append(("Light", [name_row, ("Light", rows)]))
    elif ob.type == 'CAMERA':
        rows = [_row(("data", "type"), "Projection"), _row(("data", "angle"), "Field of View"),
                _row(("data", "sensor_fit"), "Field of View Type"), _row(("data", "clip_start"), "Near Plane"),
                _row(("data", "clip_end"), "Far Plane"), _row(("data", "ortho_scale"), "Ortho Height")]
        tabs.append(("Camera", [name_row, ("Camera", rows)]))
    else:
        tabs.append(("General", [name_row]))
    # Softimage Local Transform (capture: screens/ppg/cube_kine_local.png): Scaling, Rotation + Order, Position
    tabs.append(("Kinematics", [
        ("Scaling", [_row(("ob", "scale"), "")]),
        ("Rotation", [_row(("rot",), ""), _row(("ob", "rotation_mode"), "Order")]),
        ("Position", [_row(("ob", "location"), "")]),
    ]))
    # Softimage Visibility (capture: screens/ppg/cube_visibility.png): General group
    tabs.append(("Visibility", [
        ("General", [_row(("ob", "hide_viewport"), "View Visibility", invert_checkbox=True),
                     _row(("ob", "hide_render"), "Render Visibility", invert_checkbox=True),
                     _row(("ob", "hide_select"), "Selectability", invert_checkbox=True)]),
        ("Rendering", [_row(("ob", "visible_shadow"), "Cast Shadows")]),
    ]))
    tabs.append(("Display", [("Display", [
        _row(("ob", "display_type"), "Display Type"), _row(("ob", "show_wire"), "Wireframe on Shaded"),
        _row(("ob", "show_in_front"), "Draw in Front"), _row(("ob", "color"), "Wireframe Color"),
    ])]))
    return tabs


def resolve(ob, path):
    """(struct, property name) for a row path, or (None, None)."""
    kind = path[0]
    if kind == "ob":
        return ob, path[1]
    if kind == "rot":
        return ob, _rotation_attr(ob)
    if kind == "data":
        return (ob.data, path[1]) if ob.data is not None and hasattr(ob.data, path[1]) else (None, None)
    if kind == "mod":
        from ..ops import gn_primitives as gn
        mod = ob.modifiers.get(path[1])
        if mod is None or mod.node_group is None:
            return None, None
        try:
            sid = gn.socket_id(mod.node_group, path[2])
        except KeyError:
            return None, None
        return getattr(mod.properties.inputs, sid), "value"
    return None, None


def _value(struct, prop):
    v = getattr(struct, prop)
    if isinstance(v, str):            # enums / strings: a str is iterable, never turn it into a tuple
        return v
    try:
        return tuple(v)
    except TypeError:
        return v


def _key(where, ob):
    return (where, ob.session_uid)


def snapshot(ob, where="pane"):
    vals = {}
    for _tab, sections in property_sets(ob):
        for _title, rows in sections:
            for path, _label, _kw in rows:
                if path[0] == "grey" or path == ("ob", "name"):
                    continue
                st, prop = resolve(ob, path)
                if st is not None:
                    vals[(path, prop)] = _value(st, prop)
    _snapshots[_key(where, ob)] = vals


def has_snapshot(ob, where="pane"):
    return _key(where, ob) in _snapshots


def revert(ob, where="pane"):
    """Put every value back to this PPG's snapshot. Returns the number of values written."""
    vals = _snapshots.get(_key(where, ob))
    if not vals:
        return 0
    n = 0
    # rotation mode first, so the rotation values land in the right property
    for (path, prop), v in sorted(vals.items(), key=lambda kv: kv[0][1] != "rotation_mode"):
        if path[0] == "rot":                       # the rotation property that was shown (mode restored first)
            st, cur_prop = ob, prop
        else:
            st, cur_prop = resolve(ob, path)
        if st is None:
            continue
        if _value(st, cur_prop) != v:
            try:
                setattr(st, cur_prop, v)
                n += 1
            except (AttributeError, TypeError, ValueError):
                pass
    if n:
        ob.update_tag()
    return n


# --- target -------------------------------------------------------------------------------------------------

def selection_target(context):
    """'The selection': the active object only if it is selected, else the first selected object, else None."""
    ob = context.active_object
    if ob is not None and ob.select_get():
        return ob
    sel = context.selected_objects
    return sel[0] if sel else None


def pane_target(context):
    wm = context.window_manager
    if wm.si_ppg_lock:
        return wm.si_ppg_target
    return selection_target(context)


# --- drawing ------------------------------------------------------------------------------------------------

def draw_ppg(layout, context, ob, where):
    wm = context.window_manager
    if ob is None:
        layout.label(text="Nothing selected")
        return
    if where == "pane" and _pane_shows[0] != ob.session_uid:
        _pane_shows[0] = ob.session_uid
        snapshot(ob, "pane")                      # the pane starts showing this object now
    elif not has_snapshot(ob, where):
        snapshot(ob, where)
    tabs = property_sets(ob)
    names = [t for t, _ in tabs]
    tab_prop = "si_ppg_popup_tab" if where == "popup" else "si_ppg_tab"   # pane and popup keep their own tab
    current = getattr(wm, tab_prop) if getattr(wm, tab_prop) in names else names[0]
    row = layout.row(align=True)
    for t in names:
        op = row.operator("si.ppg_tab", text=t, depress=(t == current))
        op.tab, op.where = t, where
    layout.separator(factor=0.5)
    col = layout.column()
    col.use_property_split = True
    col.use_property_decorate = True              # the animation divots
    sections = next(secs for t, secs in tabs if t == current)
    n = 0
    for i, (title, rows) in enumerate(sections):
        if title:
            header, body = col.panel("si_ppg_%s_%d" % (current.replace(" ", "_"), i), default_closed=False)
            header.label(text=title)
            if body is None:
                continue
        else:
            body = col
        for path, label, kw in rows:
            if path[0] == "grey":
                r = body.row()
                r.active = False
                r.label(text=path[1] + "  (not in Blender)")
                continue
            st, prop = resolve(ob, path)
            if st is None:
                continue
            try:
                body.prop(st, prop, text=label or "", **kw)
                n += 1
            except Exception as e:                # never let one row stop the whole PPG
                draw_errors.append("%s / %s / %s: %s" % (ob.name, current, label or prop, e))
                body.label(text="(%s)" % (label or prop), icon='ERROR')
    drawn_rows[current] = n


def title(context, ob):
    if ob is None:
        return "Property Editor"
    owner = ob.parent.name if ob.parent else "Scene_Root"
    return "%s : %s" % (owner, ob.name)


class SI_PT_ppg_pane(bpy.types.Panel):
    bl_space_type = 'VIEW_3D'          # Properties Tool tab draws 3D View "Tool" panels (docks.py)
    bl_region_type = 'UI'
    bl_category = "Tool"
    bl_label = "Property Editor"
    bl_options = {'HIDE_HEADER'}
    bl_order = -300

    @classmethod
    def poll(cls, context):
        return docks.role(context) == "PPG"

    def draw(self, context):
        draw_ppg(self.layout, context, pane_target(context), "pane")


class SI_PT_ppg_popup(bpy.types.Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'WINDOW'
    bl_label = "Property Editor"
    bl_options = {'INSTANCED'}
    bl_ui_units_x = 18

    def draw(self, context):
        ob = context.window_manager.si_ppg_popup_target
        self.layout.label(text=title(context, ob))
        draw_ppg(self.layout, context, ob, "popup")
        if ob is not None:
            op = self.layout.operator("si.ppg_revert", text="Revert")
            op.where = "popup"


# --- header for the docked pane -------------------------------------------------------------------------------

def draw_pane_header(layout, context):
    from . import viewport
    wm = context.window_manager
    ob = pane_target(context)
    row = layout.row(align=True)
    row.label(text=viewport.view_letter_any(context))
    row.menu("SI_MT_view_menu", text="Property Editor")
    layout.separator()
    layout.label(text=title(context, ob))
    layout.separator_spacer()
    layout.operator("si.ppg_lock", text="", icon='LOCKED' if wm.si_ppg_lock else 'UNLOCKED', depress=wm.si_ppg_lock)
    layout.operator("si.ppg_revert", text="", icon='LOOP_BACK').where = "pane"


# --- operators ----------------------------------------------------------------------------------------------

class SI_OT_ppg_tab(bpy.types.Operator):
    """Show this property set"""
    bl_idname = "si.ppg_tab"
    bl_label = "PPG Tab"
    bl_options = {'INTERNAL'}

    tab: StringProperty()
    where: StringProperty(default="pane")

    def execute(self, context):
        setattr(context.window_manager, "si_ppg_popup_tab" if self.where == "popup" else "si_ppg_tab", self.tab)
        for a in context.screen.areas:
            a.tag_redraw()
        return {'FINISHED'}


class SI_OT_ppg_lock(bpy.types.Operator):
    """Lock the Property Editor on this object (off = Recycle: follows the selection)"""
    bl_idname = "si.ppg_lock"
    bl_label = "Lock"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        wm = context.window_manager
        if wm.si_ppg_lock:
            wm.si_ppg_lock = False
            wm.si_ppg_target = None
        else:
            ob = selection_target(context)
            if ob is None:
                return {'CANCELLED'}
            wm.si_ppg_target = ob
            wm.si_ppg_lock = True
        return {'FINISHED'}


class SI_OT_ppg_revert(bpy.types.Operator):
    """Revert: every value back to what it was when this Property Editor started showing the object"""
    bl_idname = "si.ppg_revert"
    bl_label = "Revert"
    bl_options = {'REGISTER', 'UNDO'}

    where: StringProperty(default="pane")

    def execute(self, context):
        wm = context.window_manager
        ob = wm.si_ppg_popup_target if self.where == "popup" else pane_target(context)
        if ob is None:
            return {'CANCELLED'}
        n = revert(ob, self.where)
        self.report({'INFO'}, "Reverted %d value%s" % (n, "" if n == 1 else "s"))
        return {'FINISHED'}


# Explorer property rows -> PPG tab
TAB_FOR = {"Kinematics": "Kinematics", "Visibility": "Visibility", "Display": "Display", "Constraint": "Kinematics"}


class SI_OT_ppg_popup(bpy.types.Operator):
    """Open the Property Editor of this object (Softimage Enter)"""
    bl_idname = "si.ppg_popup"
    bl_label = "Property Editor"
    bl_options = {'INTERNAL'}

    obj: StringProperty(options={'SKIP_SAVE'})
    prop: StringProperty(options={'SKIP_SAVE'})

    def execute(self, context):
        ob = bpy.data.objects.get(self.obj) if self.obj else selection_target(context)
        if ob is None:
            self.report({'INFO'}, "Select an object first")
            return {'CANCELLED'}
        wm = context.window_manager
        wm.si_ppg_popup_target = ob
        _snapshots.pop(_key("popup", ob), None)        # a new popup: a new Revert point
        if self.prop:
            names = [t for t, _ in property_sets(ob)]
            tab = TAB_FOR.get(self.prop) or (names[0] if self.prop in ("Primitive", "Operator") else None)
            if tab in names:
                wm.si_ppg_popup_tab = tab
        bpy.ops.wm.call_panel(name="SI_PT_ppg_popup", keep_open=True)
        return {'FINISHED'}


class SI_OT_ppg_show(bpy.types.Operator):
    """Show the Property Editor in this pane (follows the selection; lock it from its header)"""
    bl_idname = "si.ppg_show"
    bl_label = "Property Editor"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        area = context.area
        if area is None or docks.role(context) in ("TOOLBAR", "MCP"):
            return {'CANCELLED'}
        area.type = 'PROPERTIES'
        sp = area.spaces.active
        sp.context = 'TOOL'
        docks.mark(sp, "PPG")
        _pane_shows[0] = None                     # a newly shown pane: a new Revert point
        for k in [k for k in _snapshots if k[0] == "pane"]:
            del _snapshots[k]
        sp.show_region_header = True
        for r in area.regions:
            if r.type == 'NAVIGATION_BAR' and r.width > 1:
                with context.temp_override(area=area, region=r):
                    bpy.ops.screen.region_toggle(region_type='NAVIGATION_BAR')
        return {'FINISHED'}


def pane_follows_selection(context):
    for a in context.screen.areas:
        if a.type == 'PROPERTIES' and docks.space_role(a.spaces.active) == "PPG":
            return not context.window_manager.si_ppg_lock
    return False


def open_after_create(context, ob, invert=False):
    """Softimage 'Popup Property Editors on Node Creation': open the PPG of a new primitive (unless a docked PPG
    pane already follows the selection). Ctrl while choosing the command inverts the preference once."""
    from .. import prefs
    p = prefs.get()
    want = p.ppg_on_create if p is not None else True
    if invert:
        want = not want
    if not want or pane_follows_selection(context):
        return
    win = context.window
    name = ob.name

    def later():
        try:
            area = max((a for a in win.screen.areas if a.type == 'VIEW_3D'), key=lambda a: a.width * a.height)
            region = next(r for r in area.regions if r.type == 'WINDOW')
            with bpy.context.temp_override(window=win, area=area, region=region):
                bpy.ops.si.ppg_popup(obj=name)
        except Exception as e:
            print("si_kit: ppg popup:", e)
        return None
    bpy.app.timers.register(later, first_interval=0.05)


@bpy.app.handlers.persistent
def _on_load(*_args):
    _snapshots.clear()
    _pane_shows[0] = None


classes = (SI_OT_ppg_tab, SI_OT_ppg_lock, SI_OT_ppg_revert, SI_OT_ppg_popup, SI_OT_ppg_show, SI_PT_ppg_pane,
           SI_PT_ppg_popup)


def register():
    wm = bpy.types.WindowManager
    wm.si_ppg_tab = StringProperty(name="PPG Tab")
    wm.si_ppg_popup_tab = StringProperty(name="PPG Popup Tab")
    wm.si_ppg_lock = BoolProperty(name="Lock", default=False)
    wm.si_ppg_target = PointerProperty(name="Locked object", type=bpy.types.Object)
    wm.si_ppg_popup_target = PointerProperty(name="Popup object", type=bpy.types.Object)
    for c in classes:
        bpy.utils.register_class(c)
    bpy.app.handlers.load_post.append(_on_load)


def unregister():
    if _on_load in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_load)
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
    wm = bpy.types.WindowManager
    for p in ("si_ppg_tab", "si_ppg_popup_tab", "si_ppg_lock", "si_ppg_target", "si_ppg_popup_target"):
        if hasattr(wm, p):
            delattr(wm, p)
    _snapshots.clear()
    _pane_shows[0] = None
    draw_errors.clear()
    drawn_rows.clear()
