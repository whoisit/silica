# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Alex Doss
"""Schematic relation links (milestone 4 of features/schematic/PLAN.md): drawing, the Show menu switches,
hit-testing and Delete.

The links come from `ops/schematic_links.collect()` (native Blender data, read-only), cached per canvas state
generation. Each link is a line between the two node centres with an arrowhead at its middle (pointing at the
target, as Softimage draws it) and a short label ("Pos") when zoomed in. Hierarchy lines are the canvas's.

Show menu switches (`SHOW`, Softimage's defaults from the capture) and what they mean in Blender:

- constraint (on): object and pose-bone constraints -> their targets.
- expression (on): drivers, the object a driver variable reads -> the driven object.
- scripted (on): Geometry Nodes modifier object inputs (user-built node operators: Blender's nearest thing to a
  Softimage scripted operator; Python drivers already count as expressions).
- operator (off): every other modifier pointing to an object (lattice, curve, hook, boolean...), curve bevel /
  taper / text-on-curve objects, and envelopes (Armature modifier or armature parent: the capture shows no
  envelope link with operator links off).
- associated_model (off): light linking (light -> receiver / blocker members), collection instance -> the roots of
  its collection ("Inst").
- shared_material (off): objects sharing a material, drawn as a star from its first user ("Mat"); a material on
  MATERIAL_STAR_MAX objects or more draws its star only from selected ends.
- selected_only (on): Links on Selected Nodes Only, only links touching a selected node are drawn.
The switches live for the session (Softimage keeps them in its preferences), not in the file.

Colours (`COLORS`, sRGB): constraint green (73, 131, 72) sampled from the capture; Softimage gives each link the
colour of its toolbar (Animate green, Model purple, Render blue), so expressions get a bluer green, operators purple,
scripted operators magenta, associated models orange (the docs' colour), shared materials blue.

Blender has no link selection: clicking a link selects its owner object (the constrained / driven / modified one)
and makes the constraint or modifier the active one in the Properties editor; the link is remembered (`picked`)
and drawn white, so Delete (`SI_OT_schematic_link_delete`) removes the constraint or the driver it stands for. A
link standing for several channels of one driver, or one target of a multi-target constraint, removes the whole
driver F-curve / constraint, like Softimage deletes the whole expression / constraint. Objects are never deleted.
"""

import time

import blf
import bpy
import gpu
from bpy.props import EnumProperty, IntProperty, StringProperty
from gpu_extras.batch import batch_for_shader

from ..ops import schematic_links as SL

SHOW = {"constraint": True, "expression": True, "scripted": True, "operator": False, "associated_model": False,
        "shared_material": False, "selected_only": True}
SHOW_ITEMS = (("constraint", "Constraint Links"), ("expression", "Expression Links"),
              ("scripted", "Scripted Operator Links"), ("operator", "Operator Links"),
              ("associated_model", "Associated Model Links"), ("shared_material", "Shared Material Links"),
              ("selected_only", "Links on Selected Nodes Only"))
CATEGORIES = ("constraint", "expression", "scripted", "operator", "associated_model", "shared_material")

COLORS = {"constraint": (73, 131, 72), "expression": (40, 165, 125), "scripted": (200, 80, 200),
          "operator": (130, 90, 205), "associated_model": (230, 130, 30), "shared_material": (60, 120, 230)}
PICKED = (255, 255, 255)
SHARED_MATERIAL = 'SHARED_MATERIAL'
INSTANCE = 'INSTANCE'

# Softimage-like short names for Blender constraint types. "Pos" is captured (a position constraint), "Dir" and
# "UpVector" are from the docs, the rest follow Softimage's constraint names (Ori, Scl, Pose, Dist, Path, Crv, Srf)
# or abbreviate Blender's.
CONSTRAINT_LABEL = {
    'COPY_LOCATION': "Pos", 'COPY_ROTATION': "Ori", 'COPY_SCALE': "Scl", 'COPY_TRANSFORMS': "Pose",
    'CHILD_OF': "Pose", 'TRACK_TO': "Dir", 'DAMPED_TRACK': "Dir", 'LOCKED_TRACK': "Dir", 'STRETCH_TO': "Dir",
    'LIMIT_DISTANCE': "Dist", 'FOLLOW_PATH': "Path", 'CLAMP_TO': "Crv", 'SPLINE_IK': "Crv", 'SHRINKWRAP': "Srf",
    'GEOMETRY_ATTRIBUTE': "Attr", 'IK': "IK", 'ARMATURE': "Arm", 'ACTION': "Act", 'TRANSFORM': "Xfo",
    'FLOOR': "Floor", 'PIVOT': "Pivot", 'FOLLOW_TRACK': "Track", 'OBJECT_SOLVER': "Solve", 'CAMERA_SOLVER': "Solve",
}
# A constraint's secondary target properties get their own name: the IK pole is Softimage's up vector.
TARGET_PROP_LABEL = {"pole_target": "UpVector", "space_object": "Space"}
MODIFIER_LABEL = {'NODES': "Nodes", 'MESH_DEFORM': "Cage", 'SURFACE_DEFORM': "SrfDef", 'SHRINKWRAP': "Srf",
                  'DATA_TRANSFER': "Xfer", 'UV_PROJECT': "UV", 'PARTICLE_INSTANCE': "Inst", 'BOOLEAN': "Bool",
                  'SIMPLE_DEFORM': "Deform", 'LAPLACIANDEFORM': "Deform"}
LIGHT_LINK_LABEL = {'RECEIVER': "Incl", 'BLOCKER': "Excl"}

HIT_PX = 5.0            # click distance to a link line, in pixels at UI scale 1
LABEL_ZOOM = 34.0 / 82.0  # the canvas's node-text threshold (zoom * NODE_W > 34)

timings = {"links": 0.0}
picked = {}             # the link picked last: {"key": (...), "group": (category, source uid, target uid)}
_epoch = [0]            # bumped after a delete: the cache is rebuilt even if the canvas generation didn't move


def short_label(link):
    """Softimage-style short label for a schematic_links.Link (or a material / instance link of this module)."""
    kind = link.kind
    if kind == SL.CONSTRAINT:
        prop = link.detail.rsplit(" ", 1)[-1] if link.detail else ""
        if prop in TARGET_PROP_LABEL:
            return TARGET_PROP_LABEL[prop]
        return CONSTRAINT_LABEL.get(link.label, link.label.replace("_", " ").title()[:5])
    if kind == SL.EXPRESSION:
        return "Expr"
    if kind == SL.ENVELOPE:
        return "Env"
    if kind == SL.OPERATOR:
        lab = link.label
        if lab in MODIFIER_LABEL:
            return MODIFIER_LABEL[lab]
        return lab.replace("GREASE_PENCIL_", "").split("_")[0].title()   # LATTICE -> Lattice, BEVEL_OBJECT -> Bevel
    if kind == SL.ASSOCIATED_MODEL:
        return LIGHT_LINK_LABEL.get(link.label, link.label.title())
    if kind == SHARED_MATERIAL:
        return "Mat"
    if kind == INSTANCE:
        return "Inst"
    return link.label


def category(link):
    """The Show menu switch a link belongs to, or None (hierarchy: drawn by the canvas)."""
    kind = link.kind
    if kind == SL.CONSTRAINT:
        return "constraint"
    if kind == SL.EXPRESSION:
        return "expression"
    if kind == SL.OPERATOR:
        return "scripted" if link.label == 'NODES' else "operator"
    if kind == SL.ENVELOPE:
        return "operator"
    if kind in (SL.ASSOCIATED_MODEL, INSTANCE):
        return "associated_model"
    if kind == SHARED_MATERIAL:
        return "shared_material"
    return None


# --- the links, cached per canvas generation ----------------------------------------------------------------

class Group:
    """The links of one category between two nodes, drawn as one line (labels joined: "Pos,Ori")."""
    __slots__ = ("cat", "src", "tgt", "su", "tu", "links", "label", "slot", "slots", "busy")

    def __init__(self, cat, src, tgt, su, tu):
        self.cat, self.src, self.tgt, self.su, self.tu = cat, src, tgt, su, tu
        self.links, self.label, self.slot, self.slots, self.busy = [], "", 0, 1, False


def _extra_links(S, with_materials):
    """Links collect() keeps as groupings: instance -> its collection's roots, shared materials as a star."""
    out = []
    in_scene = set(S.objects)
    for ob, coll in S.instances.items():
        for t in coll.all_objects:
            if t is not ob and t in in_scene and (t.parent is None or t.parent not in in_scene):
                out.append(SL.Link(INSTANCE, ob, t, ob, ob, '', 'INSTANCE', 'instance of ' + coll.name, '', -1,
                                   SL.PICK_OBJECT, False))
    if with_materials:
        for mat, obs in S.materials.items():
            first = obs[0]
            for ob in obs[1:]:
                if ob is not first:
                    out.append(SL.Link(SHARED_MATERIAL, first, ob, ob, mat, '', 'MAT', mat.name, '', -1,
                                       SL.PICK_OBJECT, False))
    return out


MATERIAL_STAR_MAX = 64   # a material on more objects draws its star only from selected ends (3,000 lines: 18 ms)


def build(scene, with_materials=False, S=None):
    """Groups for every relation link of `scene` (hierarchy left out) and {Object: [Group]} for both ends. `S`: a
    collect() result to reuse (the canvas already made one for its letters)."""
    S = S if S is not None else SL.collect(scene)
    groups = {}
    for ln in S.links + _extra_links(S, with_materials):
        cat = category(ln)
        if cat is None or ln.source is ln.target:
            continue
        try:
            su, tu = ln.source.session_uid, ln.target.session_uid
        except ReferenceError:
            continue
        g = groups.get((cat, su, tu))
        if g is None:
            g = groups[(cat, su, tu)] = Group(cat, ln.source, ln.target, su, tu)
        g.links.append(ln)
    if with_materials:
        users = {}
        for g in groups.values():
            if g.cat == "shared_material":
                users[g.src] = users.get(g.src, 0) + 1
        for g in groups.values():
            if g.cat == "shared_material" and users[g.src] >= MATERIAL_STAR_MAX:
                g.busy = True
    pairs, adj = {}, {}
    for g in groups.values():
        labels = []
        for ln in g.links:
            lab = short_label(ln)
            if lab not in labels:
                labels.append(lab)
        g.label = ",".join(labels)
        pairs.setdefault((min(g.su, g.tu), max(g.su, g.tu)), []).append(g)
        adj.setdefault(g.src, []).append(g)
        adj.setdefault(g.tgt, []).append(g)
    for gs in pairs.values():             # several kinds between two nodes: side by side, not on top of each other
        if len(gs) > 1:
            gs.sort(key=lambda g: CATEGORIES.index(g.cat))
            for i, g in enumerate(gs):
                g.slot, g.slots = i, len(gs)
    every = list(groups.values())
    return {"all": every, "groups": [g for g in every if not g.busy], "adj": adj}


def links_cache(scene, st):
    """build() for this canvas state, recomputed only when its generation (or a Show switch it needs) changed."""
    key = (st.get("gen"), SHOW["shared_material"], _epoch[0], scene.as_pointer())
    c = st.get("_linkdraw")
    if c is None or c["key"] != key:
        c = build(scene, SHOW["shared_material"], st.get("collect"))
        c["key"] = key
        st["_linkdraw"] = c
    return c


def invalidate():
    """Rebuild the links at the next draw (after a delete; scene changes already move the canvas generation)."""
    _epoch[0] += 1


def _selected(vl):
    """The Softimage selection: Blender's selected objects plus the hidden objects picked in the Explorer."""
    out = set(vl.objects.selected)
    from . import explorer
    if explorer.hidden_picks:
        for n in list(explorer.hidden_picks):
            ob = vl.objects.get(n)
            if ob is not None and explorer._is_selected(ob, vl):
                out.add(ob)
    return out


def _touching(c, sel):
    """The groups with an end in `sel` (through the adjacency map for a small selection, else one scan)."""
    if len(sel) * 4 < len(c["all"]):
        seen, out = set(), []
        for ob in sel:
            for g in c["adj"].get(ob, ()):
                if id(g) not in seen:
                    seen.add(id(g))
                    out.append(g)
        return out
    return [g for g in c["all"] if g.src in sel or g.tgt in sel]


def segments(context, st, v2d, vl):
    """[(Group, (ax, ay), (bx, by))] in region pixels: the enabled links between laid-out nodes, culled to the view
    (a link is kept when its box touches the view), offset sideways when several kinds join the same two nodes."""
    c = links_cache(context.scene, st)
    enabled = {k for k in CATEGORIES if SHOW[k]}
    if not enabled:
        return []
    if SHOW["selected_only"]:
        sel = _selected(vl)
        cand = _touching(c, sel) if sel else []
    else:
        cand = c["groups"]
        if len(cand) != len(c["all"]):          # busy material stars: from selected ends only
            cand = cand + [g for g in _touching(c, _selected(vl)) if g.busy]
    region = context.region
    x0, y0 = v2d.region_to_view(0, 0)
    x1, y1 = v2d.region_to_view(region.width, region.height)
    left, right, top, bottom = min(x0, x1), max(x0, x1), min(-y0, -y1), max(-y0, -y1)   # layout rect, y down
    pos, nodes = st["pos"], st["nodes"]
    gap = 4.0 * _ui(context)
    out = []
    for g in cand:
        if g.cat not in enabled:
            continue
        p, q = pos.get(g.su), pos.get(g.tu)
        if p is None or q is None:
            continue
        n, m = nodes.get(g.su), nodes.get(g.tu)
        if n is None or m is None:
            continue
        ax, ay = p[0] + n.w / 2, p[1] + n.h / 2
        bx, by = q[0] + m.w / 2, q[1] + m.h / 2
        if max(ax, bx) < left or min(ax, bx) > right or max(ay, by) < top or min(ay, by) > bottom:
            continue
        a = v2d.view_to_region(ax, -ay, clip=False)
        b = v2d.view_to_region(bx, -by, clip=False)
        if g.slots > 1:                    # sideways from the lower uid's end, so a -> b and b -> a part
            dx, dy = (b[0] - a[0], b[1] - a[1]) if g.su < g.tu else (a[0] - b[0], a[1] - b[1])
            d = (dx * dx + dy * dy) ** 0.5 or 1.0
            off = (g.slot - (g.slots - 1) / 2.0) * gap
            ox, oy = -dy / d * off, dx / d * off
            a, b = (a[0] + ox, a[1] + oy), (b[0] + ox, b[1] + oy)
        out.append((g, (a[0], a[1]), (b[0], b[1])))
    return out


# --- drawing -------------------------------------------------------------------------------------------------

def _ui(context):
    """UI scale (0 in background Blender, where it is never computed: 1 then)."""
    return context.preferences.system.ui_scale or 1.0


def _rgb(c, a=1.0):
    return (c[0] / 255, c[1] / 255, c[2] / 255, a)


def _light(c):
    """A label colour readable on Blender's dark node-editor background: the link colour mixed with white."""
    return tuple((v + 255) // 2 for v in c)


def geometry(context, st, v2d, vl):
    """What draw_links draws: ({colour: line points}, {colour: arrow triangles}, [(x, y, text, colour)], zoom).

    Split from the GPU calls so the cost can be measured without a GPU (background tests)."""
    segs = segments(context, st, v2d, vl)
    ui = _ui(context)
    zoom = (v2d.view_to_region(100, 0, clip=False)[0] - v2d.view_to_region(0, 0, clip=False)[0]) / 100.0
    show_labels = zoom > LABEL_ZOOM
    alen, ahw = 9.0 * ui, 4.0 * ui
    group = picked.get("group")
    lines, tris, labels = {}, {}, []
    for g, a, b in segs:
        col = PICKED if group is not None and (g.cat, g.su, g.tu) == group else COLORS[g.cat]
        pts = lines.get(col)
        if pts is None:
            pts = lines[col] = []
        pts.append(a)
        pts.append(b)
        dx, dy = b[0] - a[0], b[1] - a[1]
        d = (dx * dx + dy * dy) ** 0.5
        if d < 1.0:
            continue
        ux, uy = dx / d, dy / d
        mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
        if d > alen * 2.5:
            tx, ty = mx + ux * alen / 2, my + uy * alen / 2
            bx, by = mx - ux * alen / 2, my - uy * alen / 2
            tl = tris.get(col)
            if tl is None:
                tl = tris[col] = []
            tl.extend(((tx, ty), (bx - uy * ahw, by + ux * ahw), (bx + uy * ahw, by - ux * ahw)))
        if show_labels and g.label:
            px, py = (-uy, ux) if ux >= 0 else (uy, -ux)       # the side above the line
            labels.append((mx + px * 6 * ui + 2 * ui, my + py * 6 * ui, g.label, _light(col)))
    return lines, tris, labels, zoom


def draw_links(context, st, v2d, vl):
    """Draw the enabled relation links (call from the canvas's POST_PIXEL handler, after the nodes)."""
    t0 = time.perf_counter()
    lines, tris, labels, zoom = geometry(context, st, v2d, vl)
    if lines:
        shader = gpu.shader.from_builtin('UNIFORM_COLOR')
        gpu.state.blend_set('ALPHA')
        for col, pts in lines.items():
            shader.uniform_float("color", _rgb(col))
            batch_for_shader(shader, 'LINES', {"pos": pts}).draw(shader)
        for col, pts in tris.items():
            shader.uniform_float("color", _rgb(col))
            batch_for_shader(shader, 'TRIS', {"pos": pts}).draw(shader)
        if labels:
            size = max(7.0, 10.0 * zoom * _ui(context))
            blf.size(0, size)
            for x, y, text, col in labels:
                blf.position(0, x, y, 0)
                blf.color(0, *_rgb(col))
                blf.draw(0, text)
        gpu.state.blend_set('NONE')
    timings["links"] = time.perf_counter() - t0


# --- hit-testing, picking, delete ---------------------------------------------------------------------------

def _dist2(px, py, a, b):
    """Squared distance from a point to segment a-b."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    L = dx * dx + dy * dy
    t = 0.0 if L == 0 else max(0.0, min(1.0, ((px - a[0]) * dx + (py - a[1]) * dy) / L))
    qx, qy = a[0] + t * dx - px, a[1] + t * dy - py
    return qx * qx + qy * qy


def group_at(context, st, x, y, vl):
    """The drawn link group nearest to region point (x, y) within HIT_PX pixels, or None."""
    v2d = context.region.view2d
    r = HIT_PX * _ui(context)
    best, bd = None, r * r
    for g, a, b in segments(context, st, v2d, vl):
        if min(a[0], b[0]) - r <= x <= max(a[0], b[0]) + r and min(a[1], b[1]) - r <= y <= max(a[1], b[1]) + r:
            d = _dist2(x, y, a, b)
            if d <= bd:
                best, bd = g, d
    return best


def link_at(context, st, x, y, vl):
    """The schematic_links.Link under region point (x, y), or None: a drawn link line within a few pixels (the
    first link of the line when it stands for several, e.g. "Pos,Ori")."""
    g = group_at(context, st, x, y, vl)
    return g.links[0] if g is not None else None


def _holder_kind(link):
    if link.holder is link.owner:
        return 'OBJECT'
    if link.holder is getattr(link.owner, "data", None):
        return 'DATA'
    return 'KEY'


def link_key(link):
    """A name-based key for a link (stays valid across undo, unlike the Link's Object references)."""
    return (link.kind, link.owner.name, _holder_kind(link), link.path, link.index)


def _resolve(key):
    """(owner Object, holder ID, live item) for a link key, or None when it no longer exists."""
    kind, owner, holder_kind, path, index = key
    ob = bpy.data.objects.get(owner)
    if ob is None:
        return None
    holder = ob if holder_kind == 'OBJECT' else ob.data if holder_kind == 'DATA' else \
        getattr(ob.data, "shape_keys", None)
    if holder is None or not path:
        return None
    try:
        if kind == SL.EXPRESSION:
            ad = holder.animation_data
            item = ad.drivers.find(path, index=index) if ad is not None else None
        else:
            item = holder.path_resolve(path)
    except (ValueError, AttributeError, ReferenceError):
        return None
    return (ob, holder, item) if item is not None else None


def _container(holder, path, coll):
    """The struct owning the collection `coll` ("constraints" / "modifiers") at the end of `path`."""
    i = path.rfind(coll + "[")
    prefix = path[:i].rstrip(".") if i > 0 else ""
    return holder.path_resolve(prefix) if prefix else holder


def select_link(context, link):
    """Click on a link: Blender has no link selection, so the owner object is selected and made active, the
    constraint / modifier becomes the active one (Properties editor), and the link is remembered for Delete.
    Softimage: only one link at a time, Shift does not add."""
    from . import explorer
    ob = link.owner
    if not explorer.select(context, ob.name, 'SET'):
        return False
    item = link.resolve()
    try:
        if isinstance(item, bpy.types.Constraint):
            _container(link.holder, link.path, "constraints").constraints.active = item
        elif isinstance(item, bpy.types.Modifier):
            ob.modifiers.active = item
        elif isinstance(item, bpy.types.FCurve):
            item.select = True
    except (AttributeError, ValueError, ReferenceError, TypeError):
        pass
    picked.clear()
    picked.update(key=link_key(link), group=(category(link), link.source.session_uid, link.target.session_uid),
                  deletable=link.deletable)
    explorer._redraw_explorers(context)
    return True


def clear_pick():
    """Forget the picked link (the canvas calls this on node clicks, so Delete then means the nodes again)."""
    picked.clear()


def delete_key(key):
    """Remove the constraint or driver a link key stands for. Returns a message, or None if nothing was removed."""
    kind = key[0]
    if kind not in (SL.CONSTRAINT, SL.EXPRESSION):
        return None
    res = _resolve(key)
    if res is None:
        return None
    ob, holder, item = res
    if kind == SL.CONSTRAINT:
        name = item.name
        _container(holder, key[3], "constraints").constraints.remove(item)
        return "Removed constraint %s from %s" % (name, ob.name)
    path = item.data_path
    holder.animation_data.drivers.remove(item)
    return "Removed driver %s on %s" % (path, holder.name)


def _redraw(context):
    for w in context.window_manager.windows:
        for a in w.screen.areas:
            if a.type == 'NODE_EDITOR':
                a.tag_redraw()


class SI_OT_schematic_link_delete(bpy.types.Operator):
    """Delete the picked Schematic link: removes the constraint or driver it stands for (objects stay)"""
    bl_idname = "si.schematic_link_delete"
    bl_label = "Delete Link"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    kind: EnumProperty(items=[(SL.CONSTRAINT, "Constraint", ""), (SL.EXPRESSION, "Expression", "")],
                       options={'SKIP_SAVE'})
    owner: StringProperty(options={'SKIP_SAVE'})
    holder: EnumProperty(items=[('OBJECT', "Object", ""), ('DATA', "Data", ""), ('KEY', "Shape Keys", "")],
                         options={'SKIP_SAVE'})
    path: StringProperty(options={'SKIP_SAVE'})
    index: IntProperty(default=-1, options={'SKIP_SAVE'})

    def _key(self):
        if self.owner:
            return (self.kind, self.owner, self.holder, self.path, self.index)
        return picked.get("key")

    def invoke(self, context, event):
        key = self._key()
        if key is None or key[0] not in (SL.CONSTRAINT, SL.EXPRESSION):
            return {'PASS_THROUGH'}        # no deletable link picked: Delete keeps its usual meaning
        if not self.owner:
            act = context.view_layer.objects.active
            if act is None or act.name != key[1]:
                picked.clear()             # the selection moved on since the link was picked: a stale pick
                return {'PASS_THROUGH'}
        return self.execute(context)

    def execute(self, context):
        key = self._key()
        msg = delete_key(key) if key is not None else None
        if msg is None:
            self.report({'WARNING'}, "No constraint or driver to delete for this link")
            return {'CANCELLED'}
        if not self.owner or picked.get("key") == key:
            picked.clear()
        invalidate()
        _redraw(context)
        self.report({'INFO'}, msg)
        return {'FINISHED'}


class SI_OT_schematic_show_toggle(bpy.types.Operator):
    """Toggle a Schematic Show menu link switch"""
    bl_idname = "si.schematic_show_toggle"
    bl_label = "Show Links"
    bl_options = {'INTERNAL'}

    item: EnumProperty(items=[(k, label, "") for k, label in SHOW_ITEMS])

    def execute(self, context):
        SHOW[self.item] = not SHOW[self.item]
        _redraw(context)
        return {'FINISHED'}


def draw_show_menu(layout):
    """The link part of the Show menu: one check item per switch, Softimage's order."""
    for k, label in SHOW_ITEMS:
        if k == "selected_only":
            layout.separator()
        layout.operator("si.schematic_show_toggle", text=label,
                        icon='CHECKBOX_HLT' if SHOW[k] else 'CHECKBOX_DEHLT').item = k


classes = (SI_OT_schematic_link_delete, SI_OT_schematic_show_toggle)


def register():
    for c in classes:
        bpy.utils.register_class(c)


def unregister():
    picked.clear()
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
