# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Alex Doss
"""Explorer (spec explorer.spike-b: custom-drawn names over Blender layout icons).

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

Drawing (hybrid, spec section 2): the row list is built once and cached (`rows()`); the panel draws Blender
layout buttons (expand triangle, icon = property page) only for the rows in view, with one scaled empty label
above and below so the Properties editor's own scrolling covers every row; a POST_PIXEL handler draws the names
(Softimage colours, italic, white / grey selection boxes, H marks, the F2 rename field).
Input: name clicks, middle clicks and keys come from addon keymap items (View2D Buttons List), which pass through
in every other Properties editor.
"""

import os
import time

import blf
import bpy
import gpu
from bpy.app.handlers import persistent
from bpy.props import BoolProperty, EnumProperty, StringProperty
from gpu_extras.batch import batch_for_shader

from . import docks

_expanded = {"scene"}          # node keys that are open
drawn = []                     # every row of the tree (Row), refreshed with the cache; read by tests
hidden_picks = set()           # hidden objects picked in the Explorer (Blender can't select hidden objects); H unhides
branch_roots = set()           # objects picked with the middle button: their selected descendants get the grey box
anchor = {"obj": None, "key": None}   # Shift+click range anchor: the last plain or Ctrl click (object, row key)
picked_nodes = set()           # (kind, name) of passes / partitions / materials clicked in the Explorer: Softimage selects
                               # the node itself; Blender has no such selection, so the Explorer only highlights it
menu_target = {}               # the node under the last right-click (kind, name), read by the node menus
drag_state = {}                # during an Explorer drag: kind, sources, target row index; drawn by the overlay
renaming = {}                  # F2 inline rename in progress: obj, text, cursor, all (whole text selected)
timings = {"build": 0.0, "panel": 0.0, "overlay": 0.0}   # seconds, last run of each; read by tests


refused = set()                # picks Blender refused to select for a reason not on the object (its collections)


def unselectable(ob, vl):
    """Blender won't select it: hidden (H), not selectable, disabled in viewports, or Blender refused it (an
    unselectable collection: which ones count depends on the view layer, so the refusal itself is kept)."""
    return (ob.hide_get(view_layer=vl) or ob.hide_select or ob.hide_viewport or not ob.visible_get(view_layer=vl)
            or ob.name in refused)


def picked_hidden(context):
    """Objects picked in the Explorer that Blender can't select (hidden ones mostly), still there and still so."""
    vl = context.view_layer
    out = [vl.objects.get(n) for n in list(hidden_picks)]
    out = [o for o in out if o is not None and unselectable(o, vl)]
    hidden_picks.intersection_update(o.name for o in out)
    refused.intersection_update(hidden_picks)
    return out


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
# Scopes (spec explorer.scopes): the root of the tree. Keys S, P, U, E, M over the Explorer.
SCOPES = [('SCENE', "Scene Root", "The objects of the scene by hierarchy"),
          ('PASSES', "Passes", "Every pass with its camera and partitions"),
          ('CURRENT_PASS', "Current Pass", "The current pass with its camera and partitions"),
          ('SELECTION', "Selection", "The selected objects"),
          ('MATERIALS', "Materials", "The material library: every material and its users")]
SCOPE_KEYS = (('S', 'SCENE'), ('P', 'PASSES'), ('U', 'CURRENT_PASS'), ('E', 'SELECTION'), ('M', 'MATERIALS'))
LIBRARY = "Materials"            # the one material library (plan section 3: Blender has no library container)

# Softimage name colours (capture screens/explorer/explorer_expanded.png, sRGB 0-255)
COLORS = {"model": (0, 98, 0), "camera": (20, 40, 160), "light": (205, 75, 0)}
BOX_SELECTED = (255, 255, 255)
BOX_BRANCH = (214, 212, 210)     # descendants of a branch pick (Softimage: grey)
BOX_DROP = (170, 186, 240)       # the row under a drag (Softimage: pale blue, capture d05)
MARK_FULL = (255, 214, 0)        # H on the icon: hidden in view and render
MARK_HALF = (120, 120, 120)      # hidden in one of them


def is_explorer(context):
    sp = context.space_data
    return docks.role(context) == "EXPLORER" and getattr(sp, "context", 'TOOL') == 'TOOL'



def unit(context=None):
    """One row / icon: Blender's widget unit, including the user's and Windows' display scaling and the line width:
    round(18 * scale) + 2 * pixel size (C rounding), measured against the layout at 1.25 to 2.2 and Thick lines."""
    system = (context or bpy.context).preferences.system
    return int(18 * system.ui_scale + 0.5) + 2 * int(system.pixel_size)


# --- rows ----------------------------------------------------------------------------------------------

class Row:
    """One tree row. Unpacks / indexes as (depth, label, kind, selected) like spike A's rows: kind = "" for an
    object row, the property name for a property row, None for folders and Scene_Root; selected is live."""
    __slots__ = ("depth", "key", "label", "icon", "expandable", "obj", "prop", "folder_active", "color", "italic",
                 "ref", "bold", "node")

    def __init__(self, depth, key, label, icon, expandable, op=None, active=True, color=None, italic=False, ref=None,
                 bold=False, node=None):
        self.depth, self.key, self.label, self.icon, self.expandable = depth, key, label, icon, expandable
        self.obj, self.prop = op if op else (None, None)
        self.folder_active = active
        self.color, self.italic, self.bold = color, italic, bold
        self.node = node         # (kind, name) of a pass / partition / material / library row
        self.ref = ref           # the object itself: bpy.data.objects.get() scans every object (slow at 10k)

    @property
    def is_object(self):
        return self.obj is not None and self.prop == ""

    def object(self):
        if not self.obj:
            return None
        try:
            if self.ref is not None:
                if self.ref.name == self.obj:
                    return self.ref
                if self.obj not in bpy.data.objects:          # renamed outside the Explorer
                    old, self.obj = self.obj, self.ref.name
                    _renamed(old, self.obj)
                    return self.ref
        except ReferenceError:            # removed since the rows were built
            pass
        self.ref = bpy.data.objects.get(self.obj)
        return self.ref

    def selected(self):
        if self.node is not None:
            return self.node in picked_nodes
        if not self.is_object:
            return False
        ob = self.object()
        return ob is not None and _is_selected(ob, bpy.context.view_layer)

    def _tuple(self):
        return (self.depth, self.label, self.prop if self.obj else None, self.selected())

    def __iter__(self):
        return iter(self._tuple())

    def __getitem__(self, i):
        return self._tuple()[i]

    def __repr__(self):
        return "Row%r" % (self._tuple(),)


_cache = {}
_overrides = {}                # the last build's partition overrides: "all" {collection: entries}, "member" {name: partition}
_scroll_job = {}               # the one pending scroll (window / area pointers, object name, tries left)
_current = {}                  # scene pointer -> the pass last seen current (opened once when it becomes current)


@persistent
def invalidate(*_args):
    """Drop the cached rows (any scene change, undo, redo); the next draw rebuilds them."""
    _cache.clear()


def reset_state():
    """A new file or Softimage mode off: picks, open nodes and drags belong to the old file's objects."""
    global found, last_panel
    _expanded.clear()
    _expanded.add("scene")
    for st in (hidden_picks, refused, branch_roots, picked_nodes, menu_target, drag_state, renaming, _current):
        st.clear()
    anchor.update(obj=None, key=None)
    found = last_panel = None
    _scroll_job.clear()
    invalidate()


@persistent
def _on_load(*_args):
    reset_state()


@persistent
def _on_undo(*_args):
    """Undo / redo bring Blender's selection back, not the Explorer's own picks: drop those (hidden picks feed
    Delete and the menus) rather than act on a pick the user undid."""
    hidden_picks.clear()
    refused.clear()
    branch_roots.clear()
    picked_nodes.clear()
    invalidate()


def object_kind(ob):
    """Name colour key: model (collection instance, Softimage's model), camera, light, or None (text colour)."""
    if ob.type == 'CAMERA':
        return "camera"
    if ob.type == 'LIGHT':
        return "light"
    if ob.type == 'EMPTY' and ob.instance_type == 'COLLECTION' and ob.instance_collection is not None:
        return "model"
    return None


def current_scope(context=None):
    return (context or bpy.context).window_manager.si_explorer_scope


def rows(context=None):
    """The tree as a list of Row, cached until the scene, the expanded nodes, the filter or the scope change."""
    context = context or bpy.context
    scene = context.scene
    filt = context.window_manager.si_explorer_filter
    scope = current_scope(context)
    vl = context.view_layer
    per_layer = scope != 'MATERIALS'           # Scene Root shows the current pass's overrides on members
    sig = (scene.as_pointer(), filt, scope, vl.name if vl and per_layer else None, len(scene.view_layers))
    from ..ops import passes as P
    ovs = P.partition_overrides(scene)         # flags of non-current passes send no depsgraph update
    _overrides["all"] = ovs
    sig += tuple(sorted((c.name, tuple(a for a, _l in ov)) for c, ov in ovs.items()))
    if scope == 'SELECTION' and vl is not None:
        sig += tuple(sorted(o.name for o in vl.objects.selected))
    elif scope == 'MATERIALS':                 # unused materials aren't in the depsgraph: no update for them
        sig += tuple((m.name, m.use_fake_user) for m in bpy.data.materials)
    seen = (context.window.as_pointer() if context.window else 0, scene.as_pointer())
    if scope in ('PASSES', 'CURRENT_PASS') and vl is not None and _current.get(seen) != vl.name:
        _expanded.add("pass:" + vl.name)       # Softimage: the current pass is opened, however it became current
        _current[seen] = vl.name
    if _cache.get("sig") == sig and _cache.get("expanded") == _expanded:
        return _cache["rows"]
    t = time.perf_counter()
    show = filt == 'ALL'
    _overrides["member"] = {}
    if vl is not None and ovs:                 # members of the current pass's overridden partitions
        for c in ovs:
            if c.get("si_pass") == vl.name:
                for o in c.objects:
                    _overrides["member"].setdefault(o.name, c)
    if scope in ('PASSES', 'CURRENT_PASS'):
        out = _build_passes(scene, vl, show, scope == 'CURRENT_PASS')
    elif scope == 'SELECTION':
        out = _build_selection(vl, show)
    elif scope == 'MATERIALS':
        out = _build_materials(scene)
    else:
        out = _build(scene, show)
    _cache.update(sig=sig, expanded=set(_expanded), rows=out)
    drawn[:] = out
    timings["build"] = time.perf_counter() - t
    return out


def _children_map(scene):
    obs = list(scene.objects)
    names = {o.name for o in obs}
    kids = {}
    for o in obs:
        p = o.parent
        kids.setdefault(p.name if p is not None and p.name in names else None, []).append(o)
    for v in kids.values():
        v.sort(key=lambda o: o.name.lower())
    return kids


def _build(scene, show_props):
    out = [Row(0, "scene", "Scene_Root", 'SCENE_DATA', True, color="model")]
    if "scene" not in _expanded:
        return out
    kids = _children_map(scene)
    for ob in kids.get(None, ()):
        _add_object(out, ob, 1, kids, show_props)
    return out


def _build_passes(scene, vl, show_props, only_current):
    """Passes / Current Pass: pass > scene camera (italic) + partitions > Override (its entries) + members (italic)."""
    from ..ops import passes as P
    cur = vl.name if vl is not None else None
    ovs = _overrides.get("all", {})
    out = []
    for n in P.pass_names(scene):
        if only_current and n != cur:
            continue
        key = "pass:" + n
        out.append(Row(0, key, n, 'RENDERLAYERS', True, bold=n == cur, node=("pass", n)))
        if key not in _expanded:
            continue
        if scene.camera is not None:
            _add_object(out, scene.camera, 1, {}, show_props, prefix=key + "/", italic=True, part=None)
        for c in P.partitions(scene, n):
            pk = key + "/part:" + c.name
            light = c.get("si_partition") == "LIGHT"
            ov = ovs.get(c, ())
            out.append(Row(1, pk, c.get("si_name", c.name), 'COLLECTION_COLOR_03' if light else 'OUTLINER_COLLECTION',
                           len(c.objects) > 0 or bool(ov), node=("partition", c.name)))
            if pk in _expanded:
                if ov:                           # Softimage's override property on the partition, with its entries
                    ok = pk + "/ovr"
                    out.append(Row(2, ok, "Override", 'LIBRARY_DATA_OVERRIDE', True, color="model",
                                   node=("override", c.name)))
                    if ok in _expanded:
                        for attr, label in ov:
                            out.append(Row(3, ok + "/" + attr, label, 'DOT', False, node=("override", c.name)))
                for ob in sorted(c.objects, key=lambda o: o.name.lower()):
                    _add_object(out, ob, 2, {}, show_props, prefix=pk + "/", italic=True, part=c if ov else None)
    return out


def _build_selection(vl, show_props):
    out = []
    for ob in sorted(vl.objects.selected if vl is not None else (), key=lambda o: o.name.lower()):
        _add_object(out, ob, 0, {}, show_props, prefix="sel/")
    return out


def material_users(scene):
    """{material name: [objects of the scene with it in a slot]}."""
    users = {}
    for ob in scene.objects:
        seen = set()
        for slot in getattr(ob, "material_slots", ()):
            m = slot.material
            if m is not None and m.name not in seen:
                seen.add(m.name)
                users.setdefault(m.name, []).append(ob)
    return users


def _build_materials(scene):
    """Materials: the one library (bold, opened) > materials (<Not used>) > their users (italic)."""
    key = "lib:" + LIBRARY
    out = [Row(0, key, LIBRARY, 'FILE_FOLDER', True, bold=True, node=("library", LIBRARY))]
    if key not in _expanded:
        return out
    users = material_users(scene)
    for m in sorted(bpy.data.materials, key=lambda m: m.name.lower()):
        us = sorted(users.get(m.name, ()), key=lambda o: o.name.lower())
        used = bool(us)          # by objects of this scene (an orphan mesh still holding it doesn't count)
        mk = "mat:" + m.name
        out.append(Row(1, mk, m.name if used else m.name + "   <Not used>", 'MATERIAL', bool(us),
                       node=("material", m.name)))
        if mk in _expanded:
            for ob in us:
                _add_object(out, ob, 2, {}, False, prefix=mk + "/", italic=True)
    return out


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


def _add_primitive(out, ob, key, d):
    """Polygon Mesh > [Secondary Shape Modeling, Animation, Shape Modeling, Modeling] > primitive operator > Clusters."""
    dkey = key + "/data"
    prim, regions = _stack(ob)
    shape_keys = list(ob.data.shape_keys.key_blocks)[1:] if getattr(ob.data, "shape_keys", None) else []
    groups = list(getattr(ob, "vertex_groups", []))
    out.append(Row(d, dkey, DATA_LABEL[ob.type], DATA_ICON.get(ob.type, 'MESH_DATA'), True, (ob.name, "Primitive"),
                   ref=ob))
    if dkey not in _expanded:
        return
    for region, mods in regions.items():
        items = shape_keys if region == "Shape Modeling" else mods
        rkey = dkey + "/" + region
        out.append(Row(d + 1, rkey, region, 'MODIFIER_DATA' if items else 'DOT', bool(items), active=bool(items)))
        if rkey in _expanded:
            for it in items:
                icon = 'SHAPEKEY_DATA' if region == "Shape Modeling" else 'MODIFIER'
                out.append(Row(d + 2, rkey + "/" + it.name, it.name, icon, False, (ob.name, "Operator")))
    if prim is not None:
        out.append(Row(d + 1, dkey + "/prim", prim.name, 'GEOMETRY_NODES', False, (ob.name, "Primitive")))
    ckey = dkey + "/clusters"
    out.append(Row(d + 1, ckey, "Clusters", 'GROUP_VERTEX', bool(groups), active=bool(groups)))
    if ckey in _expanded:
        for g in groups:
            out.append(Row(d + 2, ckey + "/" + g.name, g.name, 'GROUP_VERTEX', False, (ob.name, "Cluster")))


_MEMBER = object()


def _add_object(out, ob, depth, kids, show_props, prefix="", italic=False, part=_MEMBER):
    """An object row and (expanded) its properties and children. prefix: where the row sits (its own expand key
    when the same object shows several times, e.g. in a partition of each pass); italic: a reference; part: the
    overridden partition to show "Override (<partition>)" for (default: its partition in the current pass)."""
    key = prefix + "ob:" + ob.name
    children = kids.get(ob.name, ())
    out.append(Row(depth, key, ob.name, OB_ICON.get(ob.type, 'OBJECT_DATA'), bool(children) or show_props,
                   (ob.name, ""), color=object_kind(ob), ref=ob, italic=italic))
    if key not in _expanded:
        return
    d = depth + 1
    if show_props:
        if ob.type in DATA_LABEL and ob.data is not None:
            _add_primitive(out, ob, key, d)
        kkey = key + "/kine"
        cons = list(ob.constraints)
        out.append(Row(d, kkey, "Kinematics", 'EMPTY_ARROWS', bool(cons), (ob.name, "Kinematics")))
        if kkey in _expanded:
            for c in cons:
                out.append(Row(d + 1, kkey + "/" + c.name, c.name, 'CONSTRAINT', False, (ob.name, "Constraint")))
        out.append(Row(d, key + "/vis", "Visibility", 'HIDE_OFF', False, (ob.name, "Visibility")))
        out.append(Row(d, key + "/disp", "Display", 'RESTRICT_VIEW_OFF', False, (ob.name, "Display")))
        for slot in getattr(ob, "material_slots", []):
            if slot.material:
                out.append(Row(d, key + "/mat/" + slot.material.name, slot.material.name, 'MATERIAL', False,
                               (ob.name, "Material")))
        p_coll = _overrides.get("member", {}).get(ob.name) if part is _MEMBER else part
        if p_coll is not None:                   # Softimage: an italic "Override (<partition>)" in the member's tree
            out.append(Row(d, key + "/ovr", "Override (%s)" % p_coll.get("si_name", p_coll.name),
                           'LIBRARY_DATA_OVERRIDE', False, italic=True, color="model", node=("override", p_coll.name)))
    for c in children:
        _add_object(out, c, d, kids, show_props)


def hidden_badge(ob, view_layer):
    """'full' (hidden in view and render), 'view' / 'render' (only one), or None."""
    v, r = ob.hide_get(view_layer=view_layer), ob.hide_render
    return "full" if v and r else "view" if v else "render" if r else None


def row_box(row, view_layer=None):
    """'selected' (white box), 'branch' (grey: a selected descendant of a branch pick) or None."""
    vl = view_layer or bpy.context.view_layer
    if row.node is not None:
        return "selected" if row.node in picked_nodes else None
    ob = row.object() if row.is_object else None
    if ob is None or not _is_selected(ob, vl):
        return None
    p = ob.parent
    while p is not None:
        if p.name in branch_roots and _is_selected(p, vl):
            return "branch"
        p = p.parent
    return "selected"


def row_at(region, y, context=None):
    """Index of the row under region y, or None."""
    u = unit(context)
    _x, vy = region.view2d.region_to_view(0, y)
    i = int((-vy - 4) // u)
    rs = rows(context)
    return i if 0 <= i < len(rs) else None


def visible_range(region, n, context=None):
    u = unit(context)
    _x, top = region.view2d.region_to_view(0, region.height)
    _x, bot = region.view2d.region_to_view(0, 0)
    last = max(0, min(n, int((-bot - 4) // u) + 2))
    first = int((-top - 4) // u) - 1
    if -bot > 4 + n * u:                    # past the end: View2D clamps to the last screenful after this draw
        first = n - int(region.height // u) - 3
    return max(0, min(last, first)), last


def _row_y(region, i, context=None):
    """Region y of the middle of row i."""
    u = unit(context)
    return region.view2d.view_to_region(0, -(4 + u * i + u / 2), clip=False)[1]


def name_x(row, context=None):
    """Region x where a row's name starts: indent, triangle, icon."""
    u = unit(context)
    return int(u * 0.5 + (row.depth + 2) * u + 4)


def object_row(rs, name):
    return next((i for i, r in enumerate(rs) if r.is_object and r.obj == name), None)


def _redraw_explorers(context=None):
    wm = (context or bpy.context).window_manager
    for w in wm.windows if wm else []:
        for area in w.screen.areas:
            if area.type == 'PROPERTIES':
                area.tag_redraw()


def _find_area(win_ptr, area_ptr):
    """The window and area again by pointer, or (None, None) when either was closed (never touch freed ones)."""
    for w in bpy.context.window_manager.windows:
        if w.as_pointer() == win_ptr:
            for a in w.screen.areas:
                if a.as_pointer() == area_ptr:
                    return w, a
    return None, None


# --- selection -------------------------------------------------------------------------------------------

def _set_selected(ob, vl, on):
    try:
        if not on:
            hidden_picks.discard(ob.name)
            refused.discard(ob.name)
            ob.select_set(False, view_layer=vl)
        elif unselectable(ob, vl):
            # Softimage lets the Explorer select hidden and unselectable objects (then H brings hidden ones back).
            # Blender can't, so the Explorer remembers the pick (hidden_picks), makes it active and draws it selected.
            hidden_picks.add(ob.name)
        else:
            ob.select_set(True, view_layer=vl)
            if ob.select_get(view_layer=vl):
                hidden_picks.discard(ob.name)
                refused.discard(ob.name)
            else:                                 # refused for a reason not listed above: picked all the same
                hidden_picks.add(ob.name)
                refused.add(ob.name)
    except RuntimeError:          # not in this view layer (its collection is excluded)
        pass


def _is_selected(ob, vl):
    """Selected in Blender, or picked in the Explorer while Blender can't select it (a pick made selectable
    elsewhere no longer counts)."""
    if ob.select_get(view_layer=vl):
        return True
    return ob.name in hidden_picks and unselectable(ob, vl)


def explorer_selection(context):
    """The Softimage selection: the view layer's selected objects and the hidden objects picked in the Explorer."""
    out = list(context.view_layer.objects.selected)
    have = set(out)
    return out + [o for o in picked_hidden(context) if o not in have]


def descendants(scene, obs):
    """obs and everything below them, obs first (one walk over the scene, not one per object)."""
    kids = _children_map(scene)
    out, seen = [], set()
    todo = list(obs)
    while todo:
        o = todo.pop(0)
        if o.name in seen:
            continue
        seen.add(o.name)
        out.append(o)
        todo.extend(kids.get(o.name, ()))
    return out


def _object_mode(context):
    """A pick in the Explorer while an object is in Edit / Pose / Sculpt mode: back to Object Mode first (user
    decision 2026-11-16), so the selection never changes behind an object that stays in its mode."""
    act = context.view_layer.objects.active
    if act is not None and act.mode != 'OBJECT':       # the object's own mode (context.mode follows the window)
        try:
            with context.temp_override(active_object=act, object=act):
                bpy.ops.object.mode_set(mode='OBJECT')
        except RuntimeError as e:
            print("si_kit: explorer object mode", e)


def select_objects(context, obs, mode='SET'):
    """Select a group of objects (a partition's members, a material's users): SET / ADD / RANGE (= add) /
    TOGGLE (all on unless all are selected) / DESELECT. The first one becomes active when they are selected."""
    _object_mode(context)
    vl = context.view_layer
    obs = [o for o in obs if o is not None]
    if mode == 'SET':
        hidden_picks.clear()
        branch_roots.clear()
        picked_nodes.clear()
        for o in list(vl.objects.selected):
            o.select_set(False, view_layer=vl)
    if mode == 'SET' and not obs:
        vl.objects.active = None
    on = {'SET': True, 'ADD': True, 'RANGE': True, 'DESELECT': False,
          'TOGGLE': not obs or not all(_is_selected(o, vl) for o in obs)}[mode]
    for o in obs:
        _set_selected(o, vl, on)
    if on and obs:
        try:
            vl.objects.active = obs[0]
        except RuntimeError:
            pass
    return bool(obs)


def pick_node(context, node, mode='SET'):
    """Click on a pass / partition / material (capture 2026-11-16, plan 7a): Softimage selects the node only, the
    members are not selected and a pass doesn't become current. A plain click replaces the selection (objects
    too); Ctrl toggles, Shift adds, Ctrl+Shift removes."""
    _object_mode(context)
    if mode == 'SET':
        vl = context.view_layer
        picked_nodes.clear()
        hidden_picks.clear()
        branch_roots.clear()
        for o in list(vl.objects.selected):
            o.select_set(False, view_layer=vl)
        vl.objects.active = None                # nothing for F2 / the menus to act on behind the node's back
    if mode == 'DESELECT' or (mode == 'TOGGLE' and node in picked_nodes):
        picked_nodes.discard(node)
    else:
        picked_nodes.add(node)


def node_objects(context, kind, name):
    """What a node holds: a partition's members, the objects using a material."""
    if kind == "partition":
        coll = bpy.data.collections.get(name)
        return list(coll.objects) if coll is not None else []
    if kind == "material":
        return material_users(context.scene).get(name, [])
    return []


def select(context, name, mode='SET', branch=False, index=None):
    """Explorer selection on object `name` (spec 1.4-1.7): mode SET / ADD / RANGE / TOGGLE / DESELECT; branch =
    the object and all its descendants (middle button); index = the clicked row (the object may show several
    times). Returns False if the object isn't in the view layer."""
    vl = context.view_layer
    ob = vl.objects.get(name)
    if ob is None:
        return False
    _object_mode(context)
    targets = [ob] + (list(ob.children_recursive) if branch else [])
    if mode == 'RANGE' and not branch:
        rs = rows(context)
        a = next((k for k, r in enumerate(rs) if r.key == anchor["key"]), None) if anchor["key"] else None
        if a is None or rs[a].obj != anchor["obj"]:
            a = object_row(rs, anchor["obj"]) if anchor["obj"] else None
        b = index if index is not None and index < len(rs) and rs[index].obj == name else object_row(rs, name)
        if a is not None and b is not None:
            lo, hi = min(a, b), max(a, b)
            targets = [t for t in (r.object() for r in rs[lo:hi + 1] if r.is_object) if t is not None]
        mode = 'ADD'
    elif mode == 'RANGE':
        mode = 'ADD'            # Shift + middle button adds a branch (docs 1.8)
    if mode == 'SET':
        hidden_picks.clear()
        branch_roots.clear()
        picked_nodes.clear()
        for o in list(vl.objects.selected):
            o.select_set(False, view_layer=vl)
    on = {'SET': True, 'ADD': True, 'DESELECT': False, 'TOGGLE': not _is_selected(ob, vl)}[mode]
    for t in targets:
        _set_selected(t, vl, on)
    if branch:
        (branch_roots.add if on else branch_roots.discard)(ob.name)
    else:
        branch_roots.discard(ob.name)
    if on:
        vl.objects.active = ob
    if mode in ('SET', 'TOGGLE') or anchor["obj"] is None:
        anchor["obj"] = ob.name
        rs = _cache.get("rows") or []
        anchor["key"] = rs[index].key if index is not None and index < len(rs) and rs[index].obj == name else None
    return True


def click_mode(event):
    """Softimage modifiers: Shift = range (left) / add (middle), Ctrl = toggle, Ctrl+Shift = deselect."""
    if event.ctrl and event.shift:
        return 'DESELECT'
    if event.ctrl:
        return 'TOGGLE'
    if event.shift:
        return 'RANGE'
    return 'SET'


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
    kids = _children_map(scene)
    out = []

    def walk(name):
        for c in kids.get(name, ()):
            out.append(c)
            walk(c.name)
    walk(None)
    return out


def _scroll_to(window, area, name):
    """Scroll the pane so the object's row is visible (centred if it wasn't). False while the redraw that shows the
    revealed row hasn't happened yet."""
    if area.type != 'PROPERTIES' or docks.space_role(area.spaces.active) != "EXPLORER":
        return True                         # the pane changed meanwhile: nothing to scroll
    region = next((r for r in area.regions if r.type == 'WINDOW'), None)
    if region is None:
        return False
    with bpy.context.temp_override(window=window, area=area, region=region):
        rs = rows()
        i = None
        if anchor["obj"] == name and anchor["key"]:
            i = next((k for k, r in enumerate(rs) if r.key == anchor["key"]), None)
        if i is None:
            i = object_row(rs, name)
        if i is None:
            return False
        u = unit()
        for _ in range(4):                  # one pan can stop short on a long list: repeat while it still moves
            y = _row_y(region, i)
            if 0.4 * u <= y <= region.height - 0.4 * u:
                return True
            bpy.ops.view2d.pan(deltax=0, deltay=int(y - region.height / 2))
            if _row_y(region, i) == y:
                break                       # held by the old bounds: try again after the redraw
        return 0.4 * u <= _row_y(region, i) <= region.height - 0.4 * u




def _scroll_tick():
    job = _scroll_job
    if not job:
        return None
    job["tries"] -= 1
    window, area = _find_area(job["win"], job["area"])
    try:
        done = window is None or _scroll_to(window, area, job["name"])
    except Exception as e:                  # the pane or the mode went away meanwhile
        print("si_kit: explorer scroll", e)
        done = True
    if done or job["tries"] <= 0:
        job.clear()
        return None
    return 0.05


def _scroll_later(window, area, name):
    """Scroll to the row after the next redraw. A newer request (held arrow key) replaces the pending one."""
    _scroll_job.update(win=window.as_pointer(), area=area.as_pointer(), name=name, tries=10)
    if not bpy.app.timers.is_registered(_scroll_tick):
        bpy.app.timers.register(_scroll_tick, first_interval=0.05)


def _reveal(ob, context=None):
    """Open what holds ob in the current scope (not ob itself): its parents (Scene Root), the passes and partitions
    it is in (Passes, Current Pass), the materials it uses (Materials)."""
    context = context or bpy.context
    scope = current_scope(context)
    if scope in ('PASSES', 'CURRENT_PASS'):
        from ..ops import passes as P
        scene, vl = context.scene, context.view_layer
        for n in P.pass_names(scene):
            if scope == 'CURRENT_PASS' and (vl is None or n != vl.name):
                continue
            if ob == scene.camera:
                _expanded.add("pass:" + n)
            for c in P.partitions(scene, n):
                if ob.name in c.objects:         # name lookup (users_collection scans every collection)
                    _expanded.update(("pass:" + n, "pass:%s/part:%s" % (n, c.name)))
        return
    if scope == 'MATERIALS':
        _expanded.add("lib:" + LIBRARY)
        for slot in getattr(ob, "material_slots", ()):
            if slot.material is not None:
                _expanded.add("mat:" + slot.material.name)
        return
    if scope == 'SELECTION':
        return
    _expanded.add("scene")
    p = ob.parent
    while p is not None:
        _expanded.add("ob:" + p.name)
        p = p.parent


def _in_scope(context, ob):
    """Whether the current scope shows ob at all (Find skips the others)."""
    scope = current_scope(context)
    if scope in ('PASSES', 'CURRENT_PASS'):
        from ..ops import passes as P
        return P.kind(ob) is not None or ob == context.scene.camera
    if scope == 'MATERIALS':
        return any(s.material for s in getattr(ob, "material_slots", ()))
    return True


def _subtree(rs, key):
    """The rows below row `key` (deeper, up to the next row at its depth or above)."""
    i = next((k for k, r in enumerate(rs) if r.key == key), None)
    if i is None:
        return []
    j = i + 1
    while j < len(rs) and rs[j].depth > rs[i].depth:
        j += 1
    return rs[i + 1:j]


def _subtrees(rs, keys):
    """The rows below any of `keys` (one walk over the rows)."""
    keys = set(keys)
    out, depth = [], None
    for r in rs:
        if depth is not None and r.depth > depth:
            out.append(r)
            continue
        depth = r.depth if r.key in keys else None
    return out


def expand_below(context, key):
    """Open rows and everything below them, in any scope (Expand All from Here, Shift+triangle, NumPad *,
    Expand Selected): one round per level over all of them."""
    keys = [key] if isinstance(key, str) else list(key)
    _expanded.update(keys)
    for _ in range(256):                    # rows appear as their parents open: one round per level
        new = [r.key for r in _subtrees(rows(context), keys) if r.expandable and r.key not in _expanded]
        if not new:
            break
        _expanded.update(new)


def collapse_below(context, keys):
    """Close rows and everything below them, also nodes opened under a closed one (Collapse All from Here)."""
    rs = rows(context)
    asked = set(keys)
    gone = set(asked)
    gone.update(r.key for r in _subtrees(rs, keys))
    roots = [r for r in rs if r.key in asked and (r.key == "scene" or (r.is_object and "/" not in r.key))]
    if roots and current_scope(context) == 'SCENE':     # Scene Root keys aren't nested: walk the hierarchy
        scene = context.scene
        tops = list(scene.objects) if any(r.key == "scene" for r in roots) else \
            [r.object() for r in roots if r.object() is not None]
        gone.update("ob:" + o.name for o in descendants(scene, tops))
    for k in list(_expanded):
        parts = k.split("/")
        if any("/".join(parts[:n]) in gone for n in range(1, len(parts) + 1)):
            _expanded.discard(k)


class SI_OT_explorer_find(bpy.types.Operator):
    """Find Next Selected Node (F over the Explorer): reveal the next selected object in the tree"""
    bl_idname = "si.explorer_find"
    bl_label = "Find Next Selected"
    bl_options = {'INTERNAL'}

    def invoke(self, context, event):
        if not is_explorer(context):
            return {'PASS_THROUGH'}             # F in any other Properties editor stays Blender's
        return self.execute(context)

    def execute(self, context):
        global found
        vl = context.view_layer
        sel = [o for o in _tree_objects(context.scene) if _is_selected(o, vl) and _in_scope(context, o)]
        if not sel:
            self.report({'INFO'}, "Nothing selected")
            return {'CANCELLED'}
        names = [o.name for o in sel]
        ob = sel[(names.index(found) + 1) % len(sel)] if found in names else sel[0]
        found = ob.name
        _reveal(ob, context)                    # what holds it; the object itself stays as it is
        area, window = context.area, context.window
        if area is not None:
            area.tag_redraw()
            _scroll_later(window, area, ob.name)
        return {'FINISHED'}


def delete_selected(context, only=None):
    """Delete the selected objects (or `only`) with Blender's own Delete (one undo step via the calling operator).
    Returns how many were deleted."""
    sel = list(only) if only is not None else explorer_selection(context)
    if not sel:
        return 0
    names = [o.name for o in sel]
    with context.temp_override(selected_objects=sel, selected_editable_objects=sel,
                               active_object=context.view_layer.objects.active or sel[0]):
        if not bpy.ops.object.delete.poll():
            return -1                           # Edit Mode and the like: Blender's Delete needs Object Mode
        bpy.ops.object.delete(use_global=False, confirm=False)
    hidden_picks.difference_update(names)
    branch_roots.difference_update(names)
    return len(sel)


class SI_OT_explorer_delete(bpy.types.Operator):
    """Delete Selection (Delete over the Explorer), like Softimage. Undo brings it back"""
    bl_idname = "si.explorer_delete"
    bl_label = "Delete Selection"
    bl_options = {'REGISTER', 'UNDO'}

    def invoke(self, context, event):
        if not is_explorer(context):
            return {'PASS_THROUGH'}             # Delete in any other Properties editor stays Blender's
        return self.execute(context)

    def execute(self, context):
        n = delete_selected(context)
        if n <= 0:
            self.report({'INFO'}, "Delete works in Object Mode" if n < 0 else "Nothing selected")
            return {'CANCELLED'}
        _redraw_explorers(context)
        return {'FINISHED'}


class SI_OT_explorer_hide(bpy.types.Operator):
    """Hide/Unhide Selection (H over the Explorer), like H in a 3D view: picked hidden objects come back"""
    bl_idname = "si.explorer_hide"
    bl_label = "Hide/Unhide Selection"
    bl_options = {'REGISTER', 'UNDO'}

    def invoke(self, context, event):
        if not is_explorer(context):
            return {'PASS_THROUGH'}             # H in any other Properties editor stays Blender's
        return self.execute(context)

    def execute(self, context):
        from ..ops import tools
        tools.hide_toggle(context)
        _redraw_explorers(context)
        return {'FINISHED'}


def set_scope(context, scope):
    """Switch the Explorer scope; open what Softimage opens (the current pass, the library)."""
    context.window_manager.si_explorer_scope = scope
    vl = context.view_layer
    if scope in ('PASSES', 'CURRENT_PASS') and vl is not None:
        from ..ops import passes as P
        if P.root(context.scene) is not None:
            P.sync(context.scene)              # objects made since the last pass command reach their partitions
        _expanded.add("pass:" + vl.name)
    elif scope == 'MATERIALS':
        _expanded.add("lib:" + LIBRARY)
    elif scope == 'SCENE':
        _expanded.add("scene")


class SI_OT_explorer_scope(bpy.types.Operator):
    """Explorer scope: what the tree shows (S Scene Root, P Passes, U Current Pass, E Selection, M Materials)"""
    bl_idname = "si.explorer_scope"
    bl_label = "Explorer Scope"
    bl_options = {'INTERNAL'}

    scope: EnumProperty(items=SCOPES)

    def invoke(self, context, event):
        if not is_explorer(context):
            return {'PASS_THROUGH'}             # the scope keys stay Blender's / Silica's elsewhere
        return self.execute(context)

    def execute(self, context):
        set_scope(context, self.scope)
        _redraw_explorers(context)
        return {'FINISHED'}


class SI_OT_explorer_select_members(bpy.types.Operator):
    """Select Members (partition) / Select Objects with this Material: the objects the node holds"""
    bl_idname = "si.explorer_select_members"
    bl_label = "Select Members"
    bl_options = {'REGISTER', 'UNDO'}

    kind: StringProperty()
    name: StringProperty()

    def execute(self, context):
        obs = node_objects(context, self.kind, self.name)
        picked_nodes.clear()
        select_objects(context, obs, 'SET')
        if not obs:
            self.report({'INFO'}, "Nothing to select")
        _redraw_explorers(context)
        return {'FINISHED'}


class SI_OT_explorer_expand_all(bpy.types.Operator):
    """Expand / Collapse All from Here"""
    bl_idname = "si.explorer_expand_all"
    bl_label = "Expand All from Here"
    bl_options = {'INTERNAL'}

    key: StringProperty()
    collapse: BoolProperty(options={'SKIP_SAVE'})

    def execute(self, context):
        if self.collapse:
            collapse_below(context, [self.key])
        else:
            expand_below(context, self.key)
        _redraw_explorers(context)
        return {'FINISHED'}


def _grey(layout, label):
    row = layout.row()
    row.enabled = False
    row.operator("si.unmapped", text=label).path = "Explorer/" + label


# Right-click menus per node kind, items as captured (reference: explorer_rclick_*, 2026-11-11). Mapped items run
# Blender / Silica operators; the rest are drawn greyed, as everywhere in Silica.
def _draw_node_menu(layout, items):
    layout.operator_context = 'INVOKE_REGION_WIN'
    kind, name = menu_target.get("node", (None, None))
    for it in items:
        if it is None:
            layout.separator()
            continue
        label, op = it[0], it[1] if len(it) > 1 else None
        if op is None:
            _grey(layout, label)
            continue
        if isinstance(op, str):                 # a submenu
            layout.menu(op, text=label)
            continue
        idname, props = op(name) if callable(op) else op
        if idname is None:
            _grey(layout, label)
            continue
        o = layout.operator(idname, text=label)
        for k, v in props.items():
            setattr(o, k, v)


def node_targets(context, name):
    """Docs notes 1.12: a node that isn't selected is acted on alone; a selected one acts on the whole selection."""
    ob = bpy.data.objects.get(name)
    if ob is None:
        return []
    if _is_selected(ob, context.view_layer):
        return explorer_selection(context) or [ob]
    return [ob]


OBJECT_ACTIONS = [('DELETE', "Delete", ""), ('SELECT_TREE', "Select Tree", ""), ('DUPLICATE', "Duplicate", ""),
                  ('CLONE', "Clone", ""), ('GROUP', "Create Group", ""),
                  ('CONSTRAINING', "Select Constraining Objects", ""), ('CONSTRAINED', "Select Objects Constrained", ""),
                  ('RENAME', "Rename", "")]


def constraint_targets(ob):
    out = []
    for c in ob.constraints:
        t = getattr(c, "target", None)
        if t is not None and t not in out:
            out.append(t)
    return out


class SI_OT_explorer_object_action(bpy.types.Operator):
    """An object's right-click menu item (on the selection when the object is selected, else on it alone)"""
    bl_idname = "si.explorer_object_action"
    bl_label = "Explorer Object Action"
    bl_options = {'REGISTER', 'UNDO'}

    action: EnumProperty(items=OBJECT_ACTIONS)
    obj: StringProperty()

    def invoke(self, context, event):
        return self.execute(context)

    def execute(self, context):
        vl = context.view_layer
        obs = node_targets(context, self.obj)
        if not obs:
            return {'CANCELLED'}
        a = self.action
        if a == 'RENAME':
            bpy.ops.si.explorer_rename('INVOKE_DEFAULT', obj=self.obj)
            return {'CANCELLED'}              # the rename is its own undo step when it ends
        if a == 'DELETE':
            if delete_selected(context, obs) < 0:
                self.report({'INFO'}, "Delete works in Object Mode")
                return {'CANCELLED'}
        elif a == 'SELECT_TREE':
            select_objects(context, descendants(context.scene, obs))
        elif a in ('DUPLICATE', 'CLONE'):
            copies = copy_objects(obs, data=a == 'DUPLICATE')   # Clone: Blender's linked duplicate (shared data)
            vl.update()
            select_objects(context, copies)  # Softimage selects the copies
        elif a == 'GROUP':
            if context.mode != 'OBJECT':
                self.report({'INFO'}, "Create Group works in Object Mode")
                return {'CANCELLED'}
            select_objects(context, obs)
            with context.temp_override(selected_objects=obs, selected_editable_objects=obs):
                bpy.ops.collection.create()   # Edit > Create Group in Silica's menus (hidden picks too)
        elif a == 'CONSTRAINING':
            select_objects(context, [t for o in obs for t in constraint_targets(o)])
        elif a == 'CONSTRAINED':
            have = set(obs)
            select_objects(context, [o for o in context.scene.objects
                                     if any(t in have for t in constraint_targets(o))])
        _redraw_explorers(context)
        return {'FINISHED'}


def _obj_action(action):
    return lambda n: ("si.explorer_object_action", {"action": action, "obj": n})


def _ppg(prop=""):
    return lambda n: ("si.ppg_popup", {"obj": n, "prop": prop})


def _current_pass_name():
    vl = bpy.context.view_layer
    return vl.name if vl is not None else None


def _expand_item(name, collapse=False):
    return ("si.explorer_expand_all", {"key": menu_target.get("key", ""), "collapse": collapse})


PASS_MENU = [
    ("Expand All from Here", lambda n: _expand_item(n)), ("Collapse All from Here", lambda n: _expand_item(n, True)),
    None, ("Rename",), ("Delete", lambda n: ("si.delete_pass", {"name": n})),
    None, ("Set as Current Pass", lambda n: ("si.set_current_pass", {"name": n})),
    ("Create New Partition", lambda n: ("si.create_partition", {}) if n == _current_pass_name() else (None, {})),
    ("Render", lambda n: ("si.render_pass", {"name": n})),
    None, ("New Pass", lambda n: ("si.create_pass", {})), ("Delete Current Pass", lambda n: ("si.delete_pass", {})),
    None, ("Properties...", lambda n: ("si.pass_properties", {"name": n})), None, ("Folder",),
    ("Remove From Folder",), ("Add to Folder",), None, ("Locks",),
    None, ("Set Thumbnail...",), ("Set Thumbnail From Region",), ("Clear Thumbnail",), None, ("Set User Keyword(s)...",),
]
PARTITION_MENU = [
    ("Expand All from Here", lambda n: _expand_item(n)), ("Collapse All from Here", lambda n: _expand_item(n, True)),
    None, ("Rename",), ("Delete", lambda n: ("si.delete_partition", {"partition": n})),
    None, ("Add Selected Objects", lambda n: ("si.add_to_partition", {"partition": n})),
    None, ("Select Members", lambda n: ("si.explorer_select_members", {"kind": "partition", "name": n})),
    ("Select Materials used by",),
    None, ("Info Selection...",), ("Explore...",),
    ("Properties...", lambda n: ("si.partition_properties", {"partition": n})), None, ("Folder",),
    ("Remove From Folder",), ("Add to Folder",), None, ("Locks",), None, ("Set Thumbnail...",),
    ("Set Thumbnail From Region",), ("Clear Thumbnail",), None, ("Set User Keyword(s)...",),
]
MATERIAL_MENU = [
    ("Expand All from Here", lambda n: _expand_item(n)), ("Collapse All from Here", lambda n: _expand_item(n, True)),
    None, ("Rename",), ("Delete",),
    None, ("Duplicate Material",), ("Assign to Selection",),
    ("Select Objects with this Material", lambda n: ("si.explorer_select_members", {"kind": "material", "name": n})),
    None, ("Properties...",), None, ("Locks",), None, ("Set Thumbnail...",), ("Set Thumbnail From Region",),
    ("Clear Thumbnail",), None, ("Set User Keyword(s)...",),
]
PROPERTIES_SUB = [("General...", _ppg()), ("Modeling...",), ("Animation...",), ("Rendering...",), ("Simulation...",),
                  ("Viewing...",), ("Custom...",), None, ("All Properties...", _ppg())]
OBJECT_MENU = [
    ("Expand All from Here", lambda n: _expand_item(n)), ("Collapse All from Here", lambda n: _expand_item(n, True)),
    None, ("Rename", _obj_action('RENAME')), ("Delete", _obj_action('DELETE')),
    None, ("Select Tree", _obj_action('SELECT_TREE')), ("Model",), ("Select Materials used by",),
    None, ("Duplicate", _obj_action('DUPLICATE')), ("Clone", _obj_action('CLONE')), ("Instantiate (Models only)",),
    None, ("Create Group", _obj_action('GROUP')), ("Add to Group",), ("Remove from Group",),
    None, ("Info Selection...",), ("Explore...",), ("Open Attachment... (Annotation / Synoptic)",),
    ("Kinematics...", _ppg("Kinematics")), ("Inspect Material...", _ppg("Material")),
    ("Last Operator in Stack...", _ppg("Operator")), ("Properties", "SI_MT_explorer_object_properties"),
    None, ("Select Constraining Objects", _obj_action('CONSTRAINING')),
    ("Select Objects Constrained", _obj_action('CONSTRAINED')),
    None, ("Folder",), ("Remove From Folder",), ("Add to Folder",), None, ("Copy All Animation",),
    ("Paste All Animation",), None, ("Locks",), None, ("Set Thumbnail...",), ("Set Thumbnail From Region",),
    ("Clear Thumbnail",), None, ("Set User Keyword(s)...",),
]
SCENE_ROOT_MENU = [
    ("Expand All from Here", lambda n: _expand_item(n)), ("Collapse All from Here", lambda n: _expand_item(n, True)),
    None, ("Rename",), ("Delete",), None, ("Export Model",), ("Convert to Reference",),
    None, ("Select Tree", lambda n: ("si.explorer_view_action", {"action": 'SELECT_ALL'})), ("Model",),
    ("Select Materials used by",), None, ("Duplicate",), ("Clone",), ("Instantiate (Models only)",),
    None, ("Info Selection...",), ("Explore...",), ("Open Attachment... (Annotation / Synoptic)",), ("Kinematics...",),
    ("Inspect Material...",), ("Properties",), None, ("Copy All Animation",), ("Paste All Animation",), None,
    ("Locks",), None, ("Set User Keyword(s)...",),
]
VIEW_ACTIONS = [('EXPAND_SELECTED', "Expand Selected", ""), ('COLLAPSE_SELECTED', "Collapse Selected", ""),
                ('RESET', "Reset", ""), ('SELECT_ALL', "Select Tree", "")]
# Right-click on empty space = the header's View menu (both captured with the same items)
BACKGROUND_MENU = [
    ("Expand Selected", lambda n: ("si.explorer_view_action", {"action": 'EXPAND_SELECTED'})),
    ("Collapse Selected", lambda n: ("si.explorer_view_action", {"action": 'COLLAPSE_SELECTED'})),
    ("Reset", lambda n: ("si.explorer_view_action", {"action": 'RESET'})),
    None, ("Track Selection",), ("Find Next Selected Node", lambda n: ("si.explorer_find", {})),
    None, ("General Sort",), ("Parameter Sort",), ("Reorder Tool",), None, ("Use Wire Colors",),
    ("Use Script Names",), ("Parameter",), None, ("Local Properties",), ("Applied Properties",), None,
    ("Flatten None",), ("Flatten Parameter Hierarchy",), ("Flatten All",), ("Decompose Branch Selection",),
    None, ("Preferences...",),
]
NODE_MENUS = {"pass": PASS_MENU, "partition": PARTITION_MENU, "material": MATERIAL_MENU, "object": OBJECT_MENU,
              "scene": SCENE_ROOT_MENU, "background": BACKGROUND_MENU}


class SI_OT_explorer_view_action(bpy.types.Operator):
    """Explorer View: Expand / Collapse Selected (NumPad * and /), Reset (everything closed), Select Tree"""
    bl_idname = "si.explorer_view_action"
    bl_label = "Explorer View"
    bl_options = {'REGISTER', 'UNDO'}

    action: EnumProperty(items=VIEW_ACTIONS)

    def invoke(self, context, event):
        if not is_explorer(context):
            return {'PASS_THROUGH'}             # NumPad / stays Blender's elsewhere
        return self.execute(context)

    def execute(self, context):
        vl = context.view_layer
        sel = explorer_selection(context)
        names = {o.name for o in sel}
        if self.action == 'EXPAND_SELECTED':
            for o in sel:
                _reveal(o, context)
            expand_below(context, [r.key for r in rows(context) if r.is_object and r.obj in names])
        elif self.action == 'COLLAPSE_SELECTED':
            collapse_below(context, [r.key for r in rows(context) if r.is_object and r.obj in names])
        elif self.action == 'RESET':
            _expanded.clear()
            _expanded.add("scene")
        elif self.action == 'SELECT_ALL':
            select_objects(context, list(vl.objects))
        _redraw_explorers(context)
        return {'FINISHED'} if self.action == 'SELECT_ALL' else {'CANCELLED'}   # open / close: no undo step


class SI_MT_explorer_pass(bpy.types.Menu):
    bl_label = "Pass"

    def draw(self, context):
        _draw_node_menu(self.layout, PASS_MENU)


class SI_MT_explorer_partition(bpy.types.Menu):
    bl_label = "Partition"

    def draw(self, context):
        _draw_node_menu(self.layout, PARTITION_MENU)


class SI_MT_explorer_material(bpy.types.Menu):
    bl_label = "Material"

    def draw(self, context):
        _draw_node_menu(self.layout, MATERIAL_MENU)


class SI_MT_explorer_object(bpy.types.Menu):
    bl_label = "Object"

    def draw(self, context):
        _draw_node_menu(self.layout, OBJECT_MENU)


class SI_MT_explorer_object_properties(bpy.types.Menu):
    bl_label = "Properties"

    def draw(self, context):
        _draw_node_menu(self.layout, PROPERTIES_SUB)


class SI_MT_explorer_scene_root(bpy.types.Menu):
    bl_label = "Scene_Root"

    def draw(self, context):
        _draw_node_menu(self.layout, SCENE_ROOT_MENU)


class SI_MT_explorer_background(bpy.types.Menu):
    bl_label = "Explorer"

    def draw(self, context):
        _draw_node_menu(self.layout, BACKGROUND_MENU)


NODE_MENU_IDS = {"pass": "SI_MT_explorer_pass", "partition": "SI_MT_explorer_partition",
                 "material": "SI_MT_explorer_material", "object": "SI_MT_explorer_object",
                 "scene": "SI_MT_explorer_scene_root", "background": "SI_MT_explorer_background"}


class SI_OT_explorer_context(bpy.types.Operator):
    """Right-click in the Explorer: the menu of the node under the mouse (passes, partitions, materials)"""
    bl_idname = "si.explorer_context"
    bl_label = "Explorer Context Menu"
    bl_options = {'INTERNAL'}

    def invoke(self, context, event):
        if not is_explorer(context) or context.region is None or context.region.type != 'WINDOW':
            return {'PASS_THROUGH'}
        i = row_at(context.region, event.mouse_region_y, context)
        r = rows(context)[i] if i is not None else None
        if r is None:
            node = ("background", "")
        elif r.node is not None:
            node = r.node
        elif r.is_object:
            node = ("object", r.obj)              # lights too: their own menu wasn't captured (plan 7)
        elif r.key == "scene":
            node = ("scene", "Scene_Root")
        else:
            return {'PASS_THROUGH'}             # property rows: their menus come later
        if node[0] not in NODE_MENU_IDS:
            return {'PASS_THROUGH'}
        menu_target.clear()
        menu_target.update(node=node, key=r.key if r is not None else "")
        bpy.ops.wm.call_menu(name=NODE_MENU_IDS[node[0]])
        return {'FINISHED'}


# --- drag and drop (capture 2026-11-16, plan section 7a) -----------------------------------------------------

def _ancestors(ob):
    out = set()
    while ob is not None:
        out.add(ob)
        ob = ob.parent
    return out


def copy_objects(objects, data=True):
    """Copies in the same collections (so in the same partitions of every pass), their data copied too unless
    `data` is False (a clone); a copied child of a copied parent goes under the parent's copy."""
    from ..ops import passes as P
    member = P.memberships(bpy.context.scene)
    made, datas = {}, {}
    for ob in objects:
        c = ob.copy()
        if data and ob.data is not None:
            if ob.data not in datas:                 # objects sharing one mesh share its copy
                datas[ob.data] = ob.data.copy()
            c.data = datas[ob.data]
        for coll in member.get(ob, ()):
            coll.objects.link(c)
        made[ob] = c
    for ob, c in made.items():
        if ob.parent in made:
            c.parent = made[ob.parent]           # the parent inverse came with the copy: same place
        for m in c.modifiers:                    # a copied rig drives the copied mesh (Blender's Duplicate does this)
            if getattr(m, "object", None) in made:
                m.object = made[m.object]
        for con in c.constraints:
            if getattr(con, "target", None) in made:
                con.target = made[con.target]
    return list(made.values())


def _duplicate(objects):
    """Ctrl during the drag: copies; the originals stay selected (capture d18)."""
    return copy_objects(objects)


def _tops(objects):
    """The dragged objects that get the new parent: all of them (Softimage parents every selected object,
    capture d21), except the inside of a branch pick (middle button), which moves with its root."""
    have = set(objects)
    out = []
    for ob in objects:
        p = ob.parent
        while p is not None and not (p in have and p.name in branch_roots):
            p = p.parent
        if p is None and ob.library is None:
            out.append(ob)
    return out


def _copy_tops(objects, copies):
    """Copies that get the new parent: those whose original's parent wasn't copied with them."""
    have = set(objects)
    return [c for o, c in zip(objects, copies) if o.parent not in have]


def _parent(objects, target):
    """Parent keeping each object where it is (Softimage), whatever its old parent: the parent inverse takes up
    the difference, the object's own transform values stay."""
    inv = target.matrix_world.inverted_safe()
    for ob in objects:
        mw = ob.matrix_world.copy()
        ob.parent = target
        ob.parent_type = 'OBJECT'
        ob.matrix_parent_inverse = inv @ mw @ ob.matrix_basis.inverted_safe()


def _unparent(objects):
    """Clear Parent and Keep Transformation."""
    for ob in objects:
        mw = ob.matrix_world.copy()
        ob.parent = None
        ob.matrix_world = mw


def takes_material(ob):
    """Objects with material slots of their own (not empties, cameras, lights; not data linked from a library)."""
    data = ob.data
    return data is not None and hasattr(data, "materials") and data.library is None


def assign_material(ob, mat):
    """Material dropped on an object: Blender's own drop on an object (the active slot, a new slot if it has none).
    False for objects that take no material (empties, cameras, lights)."""
    data = ob.data
    if not takes_material(ob):
        return False
    if not ob.material_slots:
        data.materials.append(mat)
    else:
        ob.material_slots[ob.active_material_index].material = mat
    return True


def drop(context, kind, sources, row, duplicate=False):
    """Drop dragged `sources` (kind 'objects': objects; 'partition': a collection) on `row`. Returns what happened
    ('parent', 'unparent', 'partition', 'new_partition', 'copy_partition') or None when the drop is refused:
    - objects on an object: parented (all of them; Ctrl during the drag: copies parented instead)
    - objects on Scene_Root: unparented (or copies, with Ctrl)
    - objects on a partition: moved into it in that pass (wrong kind ignored)
    - objects on a pass: a new partition there holding them, highlighted
    - a partition on another pass: copied there with its members
    Empty space, property rows and the rest: nothing."""
    from ..ops import passes as P
    scene = context.scene
    if row is None:
        return None
    if kind == "objects":
        obs = [o for o in sources if o is not None and (o.library is None or not duplicate)]
        if row.is_object:
            target = row.object()
            above = _ancestors(target)               # never under itself or its own descendants
            obs = [o for o in obs if target is not None and o not in above]
            if not obs:
                return None
            if duplicate:
                obs = _copy_tops(obs, _duplicate(obs))
            else:
                obs = _tops([o for o in obs if o.parent != target])
            if not obs:
                return None
            _parent(obs, target)
            return "parent"
        if row.key == "scene":
            if duplicate:
                obs = _copy_tops(obs, _duplicate(obs))
            else:
                obs = _tops([o for o in obs if o.parent is not None])
            if not obs:
                return None
            _unparent(obs)
            return "unparent"
        if row.node and row.node[0] in ("partition", "pass") and P.root(scene) is not None:
            P.sync(scene)                        # objects made since the last pass command are in their partitions
        if row.node and row.node[0] == "partition":
            coll = bpy.data.collections.get(row.node[1])
            if coll is None or not P.in_passes(scene, coll):
                return None
            return "partition" if P.move_to_partition(scene, coll, obs) else None
        if row.node and row.node[0] == "pass":
            if row.node[1] not in P.pass_names(scene) or not any(P.kind(o) for o in obs):
                return None
            c = P.create_partition(scene, row.node[1], "Partition", obs)
            pick_node(context, ("partition", c.name))
            _expanded.add(row.key)
            return "new_partition"
        return None
    if kind == "material":
        target = row.object() if row.is_object else None
        if target is None or sources is None or not takes_material(target):
            return None                      # partitions: per-pass materials come later (plan section 3)
        assign_material(target, sources.copy() if duplicate else sources)
        return "material"
    if kind == "partition":
        coll = sources
        if row.node and row.node[0] == "pass" and coll is not None and row.node[1] != coll.get("si_pass") \
                and row.node[1] in P.pass_names(scene) and not coll.get("si_background"):
            P.copy_partition(scene, coll, row.node[1])
            _expanded.add(row.key)
            return "copy_partition"
    return None


class SI_OT_explorer_drag(bpy.types.Operator):
    """Drag in the Explorer: objects onto an object (parent), Scene_Root (unparent), a partition (move) or a pass
    (new partition); a partition onto another pass (copy). Ctrl during the drag duplicates"""
    bl_idname = "si.explorer_drag"
    bl_label = "Explorer Drop"
    bl_options = {'REGISTER', 'UNDO'}

    def invoke(self, context, event):
        region = context.region
        if not is_explorer(context) or region is None or region.type != 'WINDOW':
            return {'PASS_THROUGH'}
        px, py = event.mouse_prev_press_x - region.x, event.mouse_prev_press_y - region.y
        i = row_at(region, py, context)
        rs = rows(context)
        if i is None or px < name_x(rs[i], context) - 4:
            return {'PASS_THROUGH'}
        r = rs[i]
        vl = context.view_layer
        self.pressed = False
        if event.ctrl and (r.is_object or (r.node and r.node[0] in ("pass", "partition", "material"))):
            # Ctrl held from the press is Ctrl+click in Softimage (capture d16): toggle, no drag
            if r.is_object:
                select(context, r.obj, 'TOGGLE', index=i)
            else:
                pick_node(context, r.node, 'TOGGLE')
            _redraw_explorers(context)
            return {'FINISHED'}
        if r.is_object:
            ob = r.object()
            if ob is None:
                return {'CANCELLED'}
            if not _is_selected(ob, vl):
                # Softimage selects what the press lands on; not in this view layer: it is dragged alone
                self.pressed = select(context, ob.name, 'SET', index=i)
                if not self.pressed:
                    self.kind, self.sources = "objects", [ob]
            if self.pressed or _is_selected(ob, vl):
                self.kind, self.sources = "objects", explorer_selection(context) or [ob]
        elif r.node and r.node[0] == "partition":
            pick_node(context, r.node)
            self.pressed = True
            self.kind, self.sources = "partition", bpy.data.collections.get(r.node[1])
        elif (r.node and r.node[0] == "material") or r.prop == "Material":
            mat = bpy.data.materials.get(r.node[1] if r.node else r.label)
            if mat is None:
                return {'CANCELLED'}
            self.kind, self.sources = "material", mat
        else:
            return {'PASS_THROUGH'}
        drag_state.clear()
        drag_state.update(kind=self.kind, source=i, target=None, ctrl=False)
        context.window_manager.modal_handler_add(self)
        _redraw_explorers(context)
        return {'RUNNING_MODAL'}

    def _end(self, context):
        drag_state.clear()
        invalidate()                             # other passes' collections send no depsgraph update
        _redraw_explorers(context)

    def cancel(self, context):
        self._end(context)

    @staticmethod
    def _row_under(context, event):
        reg = context.region
        inside = 0 <= event.mouse_region_x < reg.width and 0 <= event.mouse_region_y < reg.height
        return row_at(reg, event.mouse_region_y, context) if inside else None

    def modal(self, context, event):
        if event.type in ('MOUSEMOVE', 'INBETWEEN_MOUSEMOVE', 'LEFT_CTRL', 'RIGHT_CTRL'):
            drag_state["target"] = self._row_under(context, event)
            drag_state["ctrl"] = event.ctrl
            context.region.tag_redraw()
            return {'RUNNING_MODAL'}
        if event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
            i = self._row_under(context, event)
            row = rows(context)[i] if i is not None else None
            try:
                done = drop(context, self.kind, self.sources, row, duplicate=event.ctrl)
            except (RuntimeError, AttributeError, ValueError) as e:     # linked data and the like
                self.report({'WARNING'}, "Drop: %s" % e)
                done = "failed"                  # some of it may have happened: an undo step to take it back
            finally:
                self._end(context)
            # a refused drop still keeps the selection the press made: an undo step for that
            return {'FINISHED'} if done or self.pressed else {'CANCELLED'}
        if event.type in ('ESC', 'RIGHTMOUSE') and event.value == 'PRESS':
            self._end(context)
            return {'FINISHED'} if self.pressed else {'CANCELLED'}
        return {'RUNNING_MODAL'}


class SI_OT_explorer_expand(bpy.types.Operator):
    """Expand / collapse (Shift: everything below too)"""
    bl_idname = "si.explorer_expand"
    bl_label = "Expand"
    bl_options = {'INTERNAL'}

    key: StringProperty()

    def invoke(self, context, event):
        if self.key in _expanded:
            if event.shift:
                collapse_below(context, [self.key])
            _expanded.discard(self.key)
        elif event.shift:
            expand_below(context, self.key)
        else:
            _expanded.add(self.key)
        _redraw_explorers(context)
        return {'FINISHED'}


class SI_OT_explorer_click(bpy.types.Operator):
    """Click: select (Shift: range, Ctrl: toggle, Ctrl+Shift: deselect; middle button: branch).
    Property nodes open their settings"""
    bl_idname = "si.explorer_click"
    bl_label = "Select"
    bl_options = {'REGISTER', 'UNDO'}

    obj: StringProperty()
    prop: StringProperty()
    extend: BoolProperty(name="Extend", description="Add to the selection", options={'SKIP_SAVE'})
    toggle: BoolProperty(name="Toggle", description="Toggle the selection (Ctrl)", options={'SKIP_SAVE'})
    range: BoolProperty(name="Range", description="Add the range from the anchor (Shift)", options={'SKIP_SAVE'})
    deselect: BoolProperty(name="Deselect", description="Deselect (Ctrl+Shift)", options={'SKIP_SAVE'})
    branch: BoolProperty(name="Branch", description="The object and everything below it (middle button)",
                         options={'SKIP_SAVE'})
    node: StringProperty(name="Node", description="pass / partition / material: act on what it holds",
                         options={'SKIP_SAVE'})
    index: bpy.props.IntProperty(default=-1, options={'SKIP_SAVE', 'HIDDEN'})

    def _mode(self):
        return ('DESELECT' if self.deselect else 'TOGGLE' if self.toggle else 'RANGE' if self.range
                else 'ADD' if self.extend else 'SET')

    def _node(self, context):
        """A pass / partition / material is highlighted only, like Softimage selecting the node (user decision
        2026-11-16): its right-click menu makes a pass current or selects a partition's members."""
        if self.node not in ("pass", "partition", "material"):
            return {'CANCELLED'}
        pick_node(context, (self.node, self.obj), self._mode())
        _redraw_explorers(context)
        return {'FINISHED'}

    def execute(self, context):
        global last_panel
        if self.node:
            return self._node(context)
        ob = bpy.data.objects.get(self.obj)
        if ob is None:
            return {'CANCELLED'}
        vl = context.view_layer
        if self.prop:
            if not select(context, ob.name, 'ADD' if self.extend else 'SET'):
                self.report({'INFO'}, "%s isn't in this view layer" % ob.name)
                return {'CANCELLED'}
            _redraw_explorers(context)
            panel = PROP_PANEL.get(self.prop)
            if panel:
                last_panel = panel
                try:
                    bpy.ops.wm.call_panel(name=panel, keep_open=True)
                except RuntimeError as e:
                    self.report({'INFO'}, str(e))
            return {'FINISHED'}
        if not select(context, ob.name, self._mode(), self.branch, self.index if self.index >= 0 else None):
            return {'CANCELLED'}
        _redraw_explorers(context)
        return {'FINISHED'}


def _click_row(context, i, mode, branch=False):
    """Act on row i like a click on its name. Returns an operator result set."""
    r = rows(context)[i]
    flags = {"range": mode == 'RANGE', "toggle": mode == 'TOGGLE', "deselect": mode == 'DESELECT'}
    if r.node is not None:
        if r.node[0] == "library":
            return {'CANCELLED'}
        if r.node[0] == "override":
            if not branch and mode == 'SET':
                bpy.ops.si.partition_properties('INVOKE_DEFAULT', partition=r.node[1])
            return {'CANCELLED'}                 # the page is its own popup; nothing to select or undo
        return bpy.ops.si.explorer_click('EXEC_DEFAULT', obj=r.node[1], node=r.node[0], **flags)
    if r.obj is None:
        return {'CANCELLED'}
    kw = {"obj": r.obj, "prop": r.prop, "branch": branch, "index": i}
    if r.is_object:
        kw.update(flags)
    return bpy.ops.si.explorer_click('EXEC_DEFAULT', **kw)


class SI_OT_explorer_pick(bpy.types.Operator):
    """Click on a name in the Explorer (keymap: left button). Passes through in other editors"""
    bl_idname = "si.explorer_pick"
    bl_label = "Explorer Pick"
    bl_options = {'INTERNAL', 'UNDO'}

    def invoke(self, context, event):
        if not is_explorer(context) or context.region is None or context.region.type != 'WINDOW':
            return {'PASS_THROUGH'}
        i = row_at(context.region, event.mouse_region_y, context)
        if i is None or event.mouse_region_x < name_x(rows(context)[i], context) - 4:
            return {'PASS_THROUGH'}
        return _click_row(context, i, click_mode(event))


class SI_OT_explorer_branch(bpy.types.Operator):
    """Middle button in the Explorer: click = branch select, drag = scroll the list"""
    bl_idname = "si.explorer_branch"
    bl_label = "Explorer Branch Pick"
    bl_options = {'INTERNAL', 'UNDO'}

    def invoke(self, context, event):
        if not is_explorer(context) or context.region is None or context.region.type != 'WINDOW':
            return {'PASS_THROUGH'}
        self.start = self.last = event.mouse_region_y
        self.x0 = event.mouse_region_x
        self.mode = click_mode(event)
        self.panned = False
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if event.type == 'MOUSEMOVE':
            y = event.mouse_region_y
            if not self.panned and abs(y - self.start) + abs(event.mouse_region_x - self.x0) > \
                    context.preferences.inputs.drag_threshold_mouse:
                self.panned = True
            if self.panned and y != self.last:
                bpy.ops.view2d.pan(deltax=0, deltay=int(self.last - y))
                self.last = y
            return {'RUNNING_MODAL'}
        if event.type == 'MIDDLEMOUSE' and event.value == 'RELEASE':
            if self.panned:
                return {'CANCELLED'}
            i = row_at(context.region, self.start, context)
            if i is not None and (rows(context)[i].is_object or rows(context)[i].node is not None):
                return _click_row(context, i, self.mode, branch=True)
            return {'CANCELLED'}
        if event.type == 'ESC':
            return {'CANCELLED'}
        return {'RUNNING_MODAL'}


KEY_ACTIONS = [('UP', "Up", ""), ('DOWN', "Down", ""), ('LEFT', "Left", ""), ('RIGHT', "Right", ""),
               ('EXPAND', "Expand", ""), ('COLLAPSE', "Collapse", ""), ('EXPAND_ALL', "Expand All Below", "")]


def key_action(context, action):
    """Arrow / NumPad keys on the active object's row (spec 1.9). Returns the object to scroll to, or None."""
    rs = rows(context)
    vl = context.view_layer
    act = vl.objects.active
    i = None
    if act is not None and anchor["key"] and anchor["obj"] == act.name:
        i = next((k for k, r in enumerate(rs) if r.key == anchor["key"]), None)
    if i is None and act is not None:
        i = object_row(rs, act.name)
    obj_rows = [k for k, r in enumerate(rs) if r.is_object and r.obj in vl.objects]
    if not obj_rows:
        return None, False
    if i is None or i not in obj_rows:
        i = obj_rows[0] if action != 'UP' else obj_rows[-1]
        return rs[i].obj, select(context, rs[i].obj, index=i)
    r = rs[i]
    target = tindex = None
    if action in ('UP', 'DOWN'):
        pos = obj_rows.index(i)
        pos = max(0, pos - 1) if action == 'UP' else min(len(obj_rows) - 1, pos + 1)
        tindex = obj_rows[pos]
        target = rs[tindex].obj
    elif action == 'RIGHT':
        if r.expandable and r.key not in _expanded:
            _expanded.add(r.key)
        else:
            for k in range(i + 1, len(rs)):
                if rs[k].depth <= r.depth:
                    break
                if rs[k].is_object:
                    target, tindex = rs[k].obj, k
                    break
    elif action == 'LEFT':
        if r.expandable and r.key in _expanded:
            _expanded.discard(r.key)
        elif current_scope(context) == 'SCENE' and act.parent is not None \
                and object_row(rs, act.parent.name) is not None:
            target = act.parent.name
    elif action == 'EXPAND':
        if r.expandable:
            _expanded.add(r.key)
    elif action == 'COLLAPSE':
        _expanded.discard(r.key)
    elif action == 'EXPAND_ALL':
        expand_below(context, r.key)
    ok = target is not None and select(context, target, index=tindex)
    return target or act.name, ok


class SI_OT_explorer_key(bpy.types.Operator):
    """Explorer keys: arrows walk the tree, NumPad + / - / * expand and collapse"""
    bl_idname = "si.explorer_key"
    bl_label = "Explorer Key"
    bl_options = {'REGISTER', 'UNDO'}

    action: EnumProperty(items=KEY_ACTIONS)

    def invoke(self, context, event):
        if not is_explorer(context):
            return {'PASS_THROUGH'}
        res = self.execute(context)
        return {'CANCELLED'} if event.is_repeat else res      # held key: the first press holds the undo step

    def execute(self, context):
        name, selected = key_action(context, self.action) or (None, False)
        _redraw_explorers(context)
        if name and context.area is not None:
            _scroll_later(context.window, context.area, name)
        return {'FINISHED'} if selected else {'CANCELLED'}   # open / close only: no undo step


def _renamed(old, new):
    """An object renamed in the Explorer keeps its open nodes, picks and anchor."""
    global found
    seg_old, seg_new = "ob:" + old, "ob:" + new
    for k in list(_expanded):
        parts = k.split("/")
        if seg_old in parts:
            _expanded.discard(k)
            _expanded.add("/".join(seg_new if x == seg_old else x for x in parts))
    for st in (hidden_picks, branch_roots):
        if old in st:
            st.discard(old)
            st.add(new)
    if anchor["obj"] == old:
        anchor.update(obj=new, key=None)
    if found == old:
        found = new
    invalidate()


class SI_OT_explorer_rename(bpy.types.Operator):
    """Rename the active object inline (F2 over the Explorer)"""
    bl_idname = "si.explorer_rename"
    bl_label = "Rename"
    bl_options = {'REGISTER', 'UNDO'}

    obj: StringProperty(options={'SKIP_SAVE'})

    def invoke(self, context, event):
        if not is_explorer(context):
            return {'PASS_THROUGH'}
        vl = context.view_layer
        if self.obj:
            ob = bpy.data.objects.get(self.obj)
        else:
            act = vl.objects.active
            sel = explorer_selection(context)
            ob = act if act is not None and act in sel else (sel[0] if sel else None)
        if ob is None:
            self.report({'INFO'}, "Nothing selected to rename")
            return {'CANCELLED'}
        if ob.library is not None:
            self.report({'INFO'}, "%s is linked from another file: its name can't change here" % ob.name)
            return {'CANCELLED'}
        _reveal(ob, context)
        if object_row(rows(context), ob.name) is None:
            self.report({'INFO'}, "%s isn't shown in this scope" % ob.name)
            return {'CANCELLED'}
        renaming.clear()
        renaming.update(obj=ob.name, text=ob.name, cursor=len(ob.name), all=True)
        _scroll_later(context.window, context.area, ob.name)
        context.window_manager.modal_handler_add(self)
        _redraw_explorers(context)
        return {'RUNNING_MODAL'}

    def cancel(self, context):
        self._finish(False)

    def _finish(self, apply):
        ob = bpy.data.objects.get(renaming.get("obj", ""))
        text = renaming.get("text", "")
        renaming.clear()
        _redraw_explorers()
        if apply and ob is not None and text and text != ob.name:
            old = ob.name
            try:
                ob.name = text
            except (AttributeError, RuntimeError) as e:
                print("si_kit: explorer rename", e)
                return False
            _renamed(old, ob.name)
            return True
        return False

    def modal(self, context, event):
        if not renaming:
            return {'CANCELLED'}
        t, c = renaming["text"], renaming["cursor"]
        if event.value != 'PRESS':
            # key releases stay here; mouse moves, timers (playback, reports), trackpad events go on
            if event.value in ('RELEASE', 'CLICK', 'DOUBLE_CLICK', 'CLICK_DRAG') and not event.type.endswith("MOUSE"):
                return {'RUNNING_MODAL'}
            return {'PASS_THROUGH'}
        if event.type == 'ESC':
            self._finish(False)
            return {'CANCELLED'}
        if event.type in ('RET', 'NUMPAD_ENTER'):
            return {'FINISHED'} if self._finish(True) else {'CANCELLED'}
        if event.type in ('LEFTMOUSE', 'RIGHTMOUSE', 'MIDDLEMOUSE'):
            done = self._finish(True)
            return {'FINISHED', 'PASS_THROUGH'} if done else {'CANCELLED', 'PASS_THROUGH'}
        if event.type in ('WHEELUPMOUSE', 'WHEELDOWNMOUSE', 'TRACKPADPAN'):
            return {'PASS_THROUGH'}
        whole = renaming["all"]          # the whole name is selected: typing or deleting replaces it
        if event.type == 'A' and event.ctrl:
            whole = True
        elif event.type in ('BACK_SPACE', 'DEL'):
            if whole:
                t, c = "", 0
            elif event.type == 'BACK_SPACE' and c > 0:
                t, c = t[:c - 1] + t[c:], c - 1
            elif event.type == 'DEL':
                t = t[:c] + t[c + 1:]
            whole = False
        elif event.type in ('LEFT_ARROW', 'RIGHT_ARROW', 'HOME', 'END'):
            if whole:
                c = 0 if event.type in ('LEFT_ARROW', 'HOME') else len(t)
            else:
                c = {'LEFT_ARROW': max(0, c - 1), 'RIGHT_ARROW': min(len(t), c + 1), 'HOME': 0, 'END': len(t)}[
                    event.type]
            whole = False
        elif event.unicode and event.unicode.isprintable() and not event.oskey \
                and (not (event.ctrl or event.alt) or (event.ctrl and event.alt)):     # Ctrl+Alt = AltGr
            if whole:
                t, c = "", 0
            t, c = t[:c] + event.unicode + t[c:], c + len(event.unicode)
            whole = False
        else:
            return {'RUNNING_MODAL'}
        renaming.update(text=t, cursor=c, all=whole)
        _redraw_explorers(context)
        return {'RUNNING_MODAL'}


# --- drawing -------------------------------------------------------------------------------------------

def _spacer(col, n):
    sp = col.column(align=True)
    sp.scale_y = n
    sp.label(text="")


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
        t = time.perf_counter()
        rs = rows(context)
        region = context.region
        first, last = visible_range(region, len(rs), context)
        vl = context.view_layer
        col = self.layout.column(align=True)
        if first > 0:
            _spacer(col, first)
        for i in range(first, last):
            r = rs[i]
            row = col.row(align=True)
            row.alignment = 'LEFT'        # natural widths, left to right: indent, triangle, icon (name: drawn by GPU)
            if r.is_object:
                ob = r.object()
                row.active = ob is not None and ob.visible_get(view_layer=vl)
            else:
                row.active = r.folder_active
            for _ in range(r.depth):
                row.label(text="", icon='BLANK1')
            if r.expandable:
                row.operator("si.explorer_expand", text="", emboss=False,
                             icon='DISCLOSURE_TRI_DOWN' if r.key in _expanded else 'DISCLOSURE_TRI_RIGHT').key = r.key
            else:
                row.label(text="", icon='BLANK1')
            if r.obj is None:
                row.label(text="", icon=r.icon)
            else:
                # the icon opens the Property Editor (without selecting), the name selects (Softimage)
                pp = row.operator("si.ppg_popup", text="", icon=r.icon, emboss=False)
                pp.obj, pp.prop = r.obj, r.prop
        if len(rs) - last > 0:
            _spacer(col, len(rs) - last)
        timings["panel"] = time.perf_counter() - t


_fonts = {}
_handles = []


def font(style):
    """blf font id for 'italic' / 'bold' (Inter, shipped in fonts/), 0 = Blender's UI font."""
    if style not in _fonts:
        fn = {"italic": "Inter-Italic.woff2", "bold": "Inter-SemiBold.woff2"}.get(style)
        fid = -1
        if fn:
            fid = blf.load(os.path.join(os.path.dirname(os.path.dirname(__file__)), "fonts", fn))
        _fonts[style] = fid if fid != -1 else 0
    return _fonts[style]


def _rgb(c, a=1.0):
    return (c[0] / 255, c[1] / 255, c[2] / 255, a)


def _box(shader, x0, y0, x1, y1, color):
    b = batch_for_shader(shader, 'TRIS', {"pos": [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]},
                         indices=[(0, 1, 2), (0, 2, 3)])
    shader.uniform_float("color", color)
    b.draw(shader)


def _overlay():
    context = bpy.context
    if not is_explorer(context):
        return
    t = time.perf_counter()
    region = context.region
    rs = rows(context)
    first, last = visible_range(region, len(rs), context)
    u = unit(context)
    scale = context.preferences.system.ui_scale
    size = context.preferences.ui_styles[0].widget.points * scale
    theme = context.preferences.themes[0].user_interface.wcol_regular
    text_col = tuple(theme.text) + (1.0,)
    vl = context.view_layer
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    gpu.state.blend_set('ALPHA')
    right = region.width - u * 0.6
    for i in range(first, last):
        r = rs[i]
        x, y = name_x(r, context), _row_y(region, i, context)
        fid = font("italic") if r.italic else font("bold") if r.bold else 0
        blf.size(fid, size)
        blf.enable(fid, blf.CLIPPING)
        blf.clipping(fid, 0, 0, right, region.height)
        ob = r.object() if r.is_object else None
        if renaming and r.is_object and r.obj == renaming.get("obj"):
            _draw_rename(shader, fid, x, y, u, scale, right)
            blf.disable(fid, blf.CLIPPING)
            continue
        box = row_box(r, vl) if (ob is not None or r.node is not None) else None
        if drag_state.get("target") == i and i != drag_state.get("source"):
            box = "drop"
        dim = (ob is not None and not ob.visible_get(view_layer=vl)) or (r.obj is None and not r.folder_active)
        if box and x - 2 * scale >= right:
            box = None
        if box:
            w = blf.dimensions(fid, r.label)[0]
            _box(shader, x - 2 * scale, y - u / 2 + scale, min(x + w + 3 * scale, right), y + u / 2 - scale,
                 _rgb({"selected": BOX_SELECTED, "branch": BOX_BRANCH, "drop": BOX_DROP}[box]))
            col = (0.0, 0.0, 0.0, 1.0)
        elif r.color:
            col = _rgb(COLORS[r.color])
        else:
            col = text_col
        if dim and not box:
            col = col[:3] + (0.5,)
        blf.position(fid, x, y - size * 0.36, 0)
        blf.color(fid, *col)
        blf.draw(fid, r.label)
        blf.disable(fid, blf.CLIPPING)
        if ob is not None:
            badge = hidden_badge(ob, vl)
            if badge:                 # Softimage's H on the icon: yellow = view and render, grey = one of them
                hx, hy = x - u * 0.55, y - u * 0.45
                blf.size(0, size * 0.75)
                blf.position(0, hx, hy, 0)
                blf.color(0, *_rgb(MARK_FULL if badge == "full" else MARK_HALF))
                blf.draw(0, "H")
    gpu.state.blend_set('NONE')
    timings["overlay"] = time.perf_counter() - t


def _draw_rename(shader, fid, x, y, u, scale, right):
    t, c = renaming["text"], renaming["cursor"]
    w = max(blf.dimensions(fid, t)[0] + 12 * scale, 8 * u)
    _box(shader, x - 3 * scale, y - u / 2 + scale, min(x + w, right), y + u / 2 - scale, (1, 1, 1, 1))
    if renaming.get("all") and t:
        _box(shader, x, y - u / 2 + 3 * scale, x + blf.dimensions(fid, t)[0], y + u / 2 - 3 * scale,
             (0.55, 0.7, 0.95, 1))
    size = bpy.context.preferences.ui_styles[0].widget.points * scale
    blf.position(fid, x, y - size * 0.36, 0)
    blf.color(fid, 0, 0, 0, 1)
    blf.draw(fid, t)
    cx = x + blf.dimensions(fid, t[:c])[0]
    _box(shader, cx, y - u / 2 + 3 * scale, cx + max(1, scale), y + u / 2 - 3 * scale, (0, 0, 0, 1))


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
    scope = dict((k, n) for k, n, _d in SCOPES).get(context.window_manager.si_explorer_scope, "Scene Root")
    for title, label in (("Explorer Scope", scope), ("Explorer View", "View")):
        mid = build.EXTRA_IDS.get(title)
        if mid:
            layout.menu(mid, text=label)
    layout.prop(context.window_manager, "si_explorer_filter", text="")


# --- keys ----------------------------------------------------------------------------------------------

# View2D Buttons List runs before the Property Editor keymap (probe 2026-11-16): the mouse items and the keys
# Blender's View2D would take (NumPad zoom) go there. The arrows go in Frames, which runs before both (arrows step
# frames / keyframes). Every item passes through outside the Explorer.
MOUSE_KEYS = (
    ('LEFTMOUSE', 'CLICK', "si.explorer_pick", {}),
    ('LEFTMOUSE', 'CLICK_DRAG', "si.explorer_drag", {}),
    ('MIDDLEMOUSE', 'PRESS', "si.explorer_branch", {}),
    ('RIGHTMOUSE', 'PRESS', "si.explorer_context", {}),
)
TREE_KEYS = (
    ('UP_ARROW', "UP"), ('DOWN_ARROW', "DOWN"), ('LEFT_ARROW', "LEFT"), ('RIGHT_ARROW', "RIGHT"),
    ('NUMPAD_PLUS', "EXPAND"), ('NUMPAD_MINUS', "COLLAPSE"), ('NUMPAD_ASTERIX', "EXPAND_ALL"),
)
_items = []


def _bind_keys():
    wm = bpy.context.window_manager
    kc = wm.keyconfigs.addon
    if kc is None:          # background mode
        return
    km = kc.keymaps.new(name="View2D Buttons List", space_type='EMPTY', region_type='WINDOW')
    for key, value, op, props in MOUSE_KEYS:
        _items.append((km, km.keymap_items.new(op, key, value, any=True)))
    frames = kc.keymaps.new(name="Frames", space_type='EMPTY', region_type='WINDOW')
    for key, action in TREE_KEYS:
        k = frames if key.endswith("_ARROW") else km
        kmi = k.keymap_items.new("si.explorer_key", key, 'PRESS', repeat=True)
        kmi.properties.action = action
        _items.append((k, kmi))
    _items.append((km, km.keymap_items.new("si.explorer_rename", 'F2', 'PRESS')))
    kmi = km.keymap_items.new("si.explorer_view_action", 'NUMPAD_SLASH', 'PRESS')   # Collapse Selected (Num /)
    kmi.properties.action = 'COLLAPSE_SELECTED'
    _items.append((km, kmi))
    for key, scope in SCOPE_KEYS:
        kmi = km.keymap_items.new("si.explorer_scope", key, 'PRESS')
        kmi.properties.scope = scope
        _items.append((km, kmi))


classes = (SI_OT_explorer_show, SI_OT_explorer_find, SI_OT_explorer_delete, SI_OT_explorer_hide, SI_OT_explorer_expand,
           SI_OT_explorer_click, SI_OT_explorer_pick, SI_OT_explorer_branch, SI_OT_explorer_key,
           SI_OT_explorer_rename, SI_OT_explorer_scope, SI_OT_explorer_select_members, SI_OT_explorer_expand_all,
           SI_MT_explorer_pass, SI_MT_explorer_partition, SI_MT_explorer_material, SI_OT_explorer_context,
           SI_OT_explorer_drag, SI_OT_explorer_object_action, SI_OT_explorer_view_action, SI_MT_explorer_object,
           SI_MT_explorer_object_properties, SI_MT_explorer_scene_root, SI_MT_explorer_background,
           SI_PT_explorer)
HANDLER_LISTS = ("depsgraph_update_post", "undo_post", "redo_post")


def register():
    bpy.types.WindowManager.si_explorer_filter = EnumProperty(name="Filter", items=FILTERS, default='ALL')
    bpy.types.WindowManager.si_explorer_scope = EnumProperty(name="Scope", items=SCOPES, default='SCENE')
    for c in classes:
        bpy.utils.register_class(c)
    cls = bpy.types.PROPERTIES_HT_header
    _orig["draw"] = cls.draw
    cls.draw = draw_header
    _handles.append(bpy.types.SpaceProperties.draw_handler_add(_overlay, (), 'WINDOW', 'POST_PIXEL'))
    for name in HANDLER_LISTS:
        getattr(bpy.app.handlers, name).append(invalidate)
    bpy.app.handlers.load_post.append(_on_load)
    for lst in (bpy.app.handlers.undo_post, bpy.app.handlers.redo_post):
        lst.append(_on_undo)
    _bind_keys()
    invalidate()


def unregister():
    for km, kmi in _items:
        try:
            km.keymap_items.remove(kmi)
        except (ReferenceError, RuntimeError):
            pass
    _items.clear()
    for name in HANDLER_LISTS:
        lst = getattr(bpy.app.handlers, name)
        while invalidate in lst:
            lst.remove(invalidate)
    while _on_load in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_load)
    for lst in (bpy.app.handlers.undo_post, bpy.app.handlers.redo_post):
        while _on_undo in lst:
            lst.remove(_on_undo)
    if bpy.app.timers.is_registered(_scroll_tick):
        bpy.app.timers.unregister(_scroll_tick)
    while _handles:
        bpy.types.SpaceProperties.draw_handler_remove(_handles.pop(), 'WINDOW')
    for style, fid in list(_fonts.items()):
        if fid:
            try:
                blf.unload(os.path.join(os.path.dirname(os.path.dirname(__file__)), "fonts",
                                        {"italic": "Inter-Italic.woff2", "bold": "Inter-SemiBold.woff2"}[style]))
            except Exception:
                pass
    _fonts.clear()
    reset_state()
    drawn.clear()
    cls = bpy.types.PROPERTIES_HT_header
    if "draw" in _orig:
        cls.draw = _orig.pop("draw")
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
    del bpy.types.WindowManager.si_explorer_filter
    del bpy.types.WindowManager.si_explorer_scope
