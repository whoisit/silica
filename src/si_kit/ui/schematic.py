# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Alex Doss
"""Schematic view (spec schematic.canvas; plan features/schematic/PLAN.md).

The pane is a Node Editor on Silica's own node tree type with **no tree assigned**: Blender's View2D gives pan,
zoom and the grid (measured: they work without a data block). Every object of the scene is drawn as a node by a
POST_PIXEL handler from a layout cached here, culled to the view, with parent / child lines, Softimage's colours
and state letters (capture 2026-11-16, reference/screens/schematic). Nothing is written to the file except the
position of a node moved by hand (Object["si_schematic_pos"], milestone 3).
"""

import time

import blf
import bpy
import gpu
from bpy.app.handlers import persistent
from bpy.props import BoolProperty, EnumProperty
from gpu_extras.batch import batch_for_shader

TREE = "SI_SchematicTree"
POS = "si_schematic_pos"

# Softimage's node sizes and spacing (SchematicNode.UIInfo on the capture scene)
NODE_W, NODE_H = 82.0, 22.0
MODEL_W, MODEL_H = 101.0, 27.0
GAP_X, GAP_Y = 20.0, 30.0

# Fill / outline colours sampled from the capture (sRGB 0-255)
KIND_COLOR = {"null": (0, 98, 0), "model": (0, 98, 0), "geometry": (0, 0, 0), "light": (205, 75, 0),
              "camera": (20, 40, 160), "chain_root": (0, 0, 224), "bone": (224, 224, 0), "effector": (224, 0, 224),
              "other": (0, 0, 0)}
HIDDEN_FILL = (161, 158, 156)
SELECTED = (255, 255, 255)
BRANCH = (198, 198, 198)
LETTER = (168, 11, 11)
LINE = (0, 0, 0)
GEOMETRY = {'MESH', 'CURVE', 'CURVES', 'SURFACE', 'META', 'FONT', 'POINTCLOUD', 'VOLUME', 'GREASEPENCIL'}

timings = {"build": 0.0, "draw": 0.0}
_state = {}          # (window pointer, scene pointer) -> {"sig", "nodes", "pos", "bounds"}
_settings = {"direction": 'VERTICAL', "sort": 'TYPE'}
_gen = [0]           # bumped by every scene change: the signature is only recomputed after one
_collapsed = {}      # scene pointer -> {uid}: branches collapsed with N (this session)
_tool = {"move": False}   # Edit > Pick and Move Tool (M): left-drag moves nodes instead of box selecting


def is_schematic(context):
    sp = getattr(context, "space_data", None)
    return sp is not None and sp.type == 'NODE_EDITOR' and getattr(sp, "tree_type", "") == TREE


class SI_SchematicTree(bpy.types.NodeTree):
    """Softimage's Schematic: the scene's objects as a tree (drawn by Silica, no nodes of its own)"""
    bl_idname = TREE
    bl_label = "Schematic"
    bl_icon = 'OUTLINER'


# --- the scene as nodes ------------------------------------------------------------------------------------

class Node:
    __slots__ = ("uid", "ob", "name", "kind", "parent", "w", "h", "hidden", "letters", "order")

    def __init__(self, ob, kind, parent, hidden, letters, order):
        self.uid, self.ob, self.name, self.kind, self.parent = ob.session_uid, ob, ob.name, kind, parent
        self.w, self.h = (MODEL_W, MODEL_H) if kind == "model" else (NODE_W, NODE_H)
        self.hidden, self.letters, self.order = hidden, letters, order


def node_kind(ob):
    if ob.type == 'EMPTY':
        if ob.instance_type == 'COLLECTION' and ob.instance_collection is not None:
            return "model"
        return "null"
    if ob.type == 'LIGHT':
        return "light"
    if ob.type == 'CAMERA':
        return "camera"
    if ob.type == 'ARMATURE':
        return "chain_root"
    if ob.type in GEOMETRY:
        return "geometry"
    return "other"


def _letters(ob, flags):
    """Softimage's red letters above a node: C constrained, E expression, A animated, V envelope."""
    if flags is not None:
        return flags.get(ob.session_uid, "")
    out = ""
    if ob.constraints:
        out += "C"
    ad = ob.animation_data
    if ad is not None and ad.drivers:
        out += "E"
    if ad is not None and ad.action is not None:
        out += "A"
    if any(m.type == 'ARMATURE' for m in getattr(ob, "modifiers", ())):
        out += "V"
    return out


_last = {}


def _collect(scene, vl=None):
    """The link extraction's letters and excluded objects (one pass; the result is kept for the link drawing)."""
    from ..ops import schematic_links
    sch = schematic_links.collect(scene, vl)
    _last["collect"] = sch
    letters = {ob.session_uid: "".join(c for c in "CEAV" if c in f) for ob, f in sch.flags.items()}
    return letters, {ob.session_uid for ob in sch.excluded}


def _flags(scene, vl=None):
    """{session_uid: letters} from ops.schematic_links (one pass over the scene: constraints on objects and pose
    bones, drivers on objects / data / shape keys, actions and NLA, armature deformation). Softimage shows C E A V;
    the extractor's I (collection instance) has no letter in Softimage's schematic."""
    from ..ops import schematic_links
    flags = schematic_links.collect(scene, vl).flags
    return {ob.session_uid: "".join(c for c in "CEAV" if c in f) for ob, f in flags.items()}


def signature(scene, vl):
    """What a relayout depends on: objects, their parents, kinds and visibility (cheap: one pass)."""
    return (scene.as_pointer(), len(scene.objects), _settings["direction"], _settings["sort"],
            frozenset(_collapsed.get(scene.as_pointer(), ())),
            hash(tuple((o.session_uid, o.parent.session_uid if o.parent else 0, o.type, tuple(o.get(POS, ())))
                       for o in scene.objects)))


def build_nodes(scene, vl):
    flags, excluded = _collect(scene, vl)
    obs = list(scene.objects)
    uids = {o.session_uid for o in obs}
    nodes = {}
    for i, ob in enumerate(sorted(obs, key=lambda o: o.session_uid)):     # session_uid: creation order
        p = ob.parent.session_uid if ob.parent is not None and ob.parent.session_uid in uids else None
        nodes[ob.session_uid] = Node(ob, node_kind(ob), p, ob.session_uid in excluded, _letters(ob, flags), i)
    return nodes


def layout(nodes, pinned=None, previous=None, collapsed=(), rearrange=None, out=None):
    """{uid: (x, y)} top-left corners in layout units (y down), from ui/schematic_layout.py (Softimage's spacing,
    roots in a row, incremental placement when `previous` is given: existing nodes keep their place). `out` gets
    the hidden (under a collapsed node) and shown-collapsed uids."""
    from . import schematic_layout as L
    items = [L.Node(n.uid, n.parent, n.w, n.h, kind=n.kind if n.kind in ("camera", "light") else "object",
                    order=n.order, label=n.name) for n in nodes.values()]
    flip = lambda d: {k: (x, -y) for k, (x, y) in (d or {}).items()}
    res = L.layout(items, direction=_settings["direction"], sort=_settings["sort"], pinned=flip(pinned),
                   previous=flip(previous) if previous else None, collapsed=set(collapsed) & set(nodes),
                   rearrange=set(rearrange) if rearrange else None)
    if out is not None:
        out["hidden"], out["collapsed"] = set(res.hidden), set(res.collapsed)
    return {k: (x, -y) for k, (x, y) in res.positions.items()}


def state(context):
    """The cached nodes and layout for this window and scene, rebuilt when the scene's structure changed."""
    scene, vl = context.scene, context.view_layer
    win = context.window.as_pointer() if context.window else 0
    key = (win, scene.as_pointer())
    st = _state.get(key)
    if st is not None and st["gen"] == _gen[0]:
        return st
    sig = signature(scene, vl)
    if st is not None and st["sig"] == sig:
        refresh(st, scene, vl)          # same structure: names, letters, excluded may still have changed
        st["gen"] = _gen[0]
        st["collect"] = _last.get("collect")
        return st
    if True:
        t = time.perf_counter()
        nodes = build_nodes(scene, vl)
        pinned = {n.uid: tuple(n.ob[POS]) for n in nodes.values() if POS in n.ob}
        previous = {k: v for k, v in st["pos"].items() if k in nodes} if st is not None else None
        extra = {}
        pos = layout(nodes, pinned, previous, _collapsed.get(scene.as_pointer(), ()), out=extra)
        xs = [p[0] for p in pos.values()] or [0.0]
        ys = [p[1] for p in pos.values()] or [0.0]
        st = _state[key] = {"sig": sig, "gen": _gen[0], "nodes": nodes, "pos": pos, "pinned": set(pinned),
                            "hidden": extra.get("hidden", set()), "collapsed": extra.get("collapsed", set()),
                            "bounds": (min(xs), min(ys), max(xs) + MODEL_W, max(ys) + MODEL_H)}
        st["collect"] = _last.get("collect")
        timings["build"] = time.perf_counter() - t
    return st


def refresh(st, scene, vl):
    """Labels, letters and excluded state of the cached nodes, without a relayout."""
    letters, excluded = _collect(scene, vl)
    for n in st["nodes"].values():
        try:
            n.name = n.ob.name
        except ReferenceError:
            continue
        n.letters = letters.get(n.uid, "")
        n.hidden = n.uid in excluded


@persistent
def _on_load(*_args):
    _state.clear()
    _gen[0] += 1


_STRUCT = (bpy.types.Object, bpy.types.Collection, bpy.types.Action, bpy.types.Armature)


@persistent
def _on_change(scene=None, depsgraph=None, *_args):
    """Scene changes: a new generation (the signature is checked again) unless the update touched no object,
    collection, action or armature (a selection change only updates the scene); every Schematic redraws."""
    updates = getattr(depsgraph, "updates", None) if depsgraph is not None else None
    if updates is None or any(isinstance(u.id, _STRUCT) for u in updates):
        _gen[0] += 1
    wm = bpy.context.window_manager
    for w in wm.windows if wm else []:
        for a in w.screen.areas:
            if a.type == 'NODE_EDITOR' and getattr(a.spaces.active, "tree_type", "") == TREE:
                a.tag_redraw()


# --- drawing -----------------------------------------------------------------------------------------------

def is_hidden(n, vl):
    """Drawn as an outline: excluded from this view layer (cached) or hidden in it (read now, nodes on screen only)."""
    try:
        return n.hidden or n.ob.hide_get(view_layer=vl)
    except (ReferenceError, RuntimeError):
        return True


def _rgb(c, a=1.0):
    return (c[0] / 255, c[1] / 255, c[2] / 255, a)


def to_region(v2d, x, y):
    """Layout (Softimage's: y down) -> region pixels."""
    return v2d.view_to_region(x, -y, clip=False)


def _selection_box(n, vl):
    """'selected', 'branch' (a selected descendant of a branch pick) or None: the Explorer's rules."""
    from . import explorer
    ob = n.ob
    try:
        if not explorer._is_selected(ob, vl):
            return None
    except ReferenceError:
        return None
    p = ob.parent
    while p is not None:
        if p.name in explorer.branch_roots and explorer._is_selected(p, vl):
            return "branch"
        p = p.parent
    return "selected"


def _overlay():
    context = bpy.context
    if not is_schematic(context):
        return
    t0 = time.perf_counter()
    st = state(context)
    region = context.region
    v2d = region.view2d
    vl = context.view_layer
    x0, y0 = v2d.region_to_view(0, 0)
    x1, y1 = v2d.region_to_view(region.width, region.height)
    left, right, top, bottom = x0, x1, -y1, -y0              # visible layout rect (y down)
    zoom = (v2d.view_to_region(100, 0, clip=False)[0] - v2d.view_to_region(0, 0, clip=False)[0]) / 100.0
    nodes, pos = st["nodes"], st["pos"]
    if _drag_state.get("move"):                       # Pick and Move in progress: the dragged nodes, offset
        dx, dy = _drag_state.get("off", (0.0, 0.0))
        pos = dict(pos)
        for uid in _drag_state["move"]:
            if uid in pos:
                pos[uid] = (pos[uid][0] + dx, pos[uid][1] + dy)
    gone = st.get("hidden", ())
    visible = [n for n in nodes.values()
               if n.uid in pos and n.uid not in gone and pos[n.uid][0] <= right and pos[n.uid][0] + n.w >= left
               and pos[n.uid][1] <= bottom and pos[n.uid][1] + n.h >= top]
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    gpu.state.blend_set('ALPHA')
    # parent / child lines: from the parent's bottom centre to the child's top centre (vertical layout)
    lines, white = [], []
    vertical = _settings["direction"] == 'VERTICAL'
    under = []
    for n in visible:
        if n.uid in st.get("collapsed", ()):          # Softimage: lines along a collapsed node's bottom edge
            x, y = pos[n.uid]
            for k in (2, 4):
                under += [to_region(v2d, x + 2, y + n.h + k), to_region(v2d, x + n.w - 2, y + n.h + k)]
        if n.parent is None or n.parent not in pos:
            continue
        p = nodes[n.parent]
        px, py = pos[p.uid]
        cx, cy = pos[n.uid]
        if vertical:
            a, b = to_region(v2d, px + p.w / 2, py + p.h), to_region(v2d, cx + n.w / 2, cy)
        else:
            a, b = to_region(v2d, px + p.w, py + p.h / 2), to_region(v2d, cx, cy + n.h / 2)
        (white if _selection_box(n, vl) == "branch" else lines).extend((a, b))
    for pts, col in ((lines, LINE), (white, SELECTED), (under, LINE)):
        if pts:
            shader.uniform_float("color", _rgb(col))
            batch_for_shader(shader, 'LINES', {"pos": pts}).draw(shader)
    # nodes: one batch per colour
    fills, outlines, labels, letters = {}, {}, [], []
    show_text = zoom * NODE_W > 34
    for n in visible:
        x, y = pos[n.uid]
        (ax, ay), (bx, by) = to_region(v2d, x, y), to_region(v2d, x + n.w, y + n.h)
        box = _selection_box(n, vl)
        kind_col = KIND_COLOR.get(n.kind, KIND_COLOR["other"])
        hidden = is_hidden(n, vl)
        if box == "selected":
            fill, text = SELECTED, (0, 0, 0)
        elif box == "branch":
            fill, text = BRANCH, (0, 0, 0)
        elif hidden:
            fill, text = HIDDEN_FILL, (0, 0, 0)
            outlines.setdefault(kind_col, []).append((ax, ay, bx, by))
        else:
            fill, text = kind_col, (255, 255, 255) if sum(kind_col) < 400 else (0, 0, 0)
        if n.uid in st["pinned"]:
            outlines.setdefault((0, 0, 0), []).append((ax - 1, ay + 1, bx + 1, by - 1))
        fills.setdefault(fill, []).append((ax, ay, bx, by))
        if show_text:
            labels.append(((ax + bx) / 2, (ay + by) / 2, n.name, text, bx - ax))
            if n.letters:
                letters.append((ax, ay, n.letters))
    for col, rects in fills.items():
        tris, idx = [], []
        for ax, ay, bx, by in rects:
            b = len(tris)
            tris += [(ax, ay), (bx, ay), (bx, by), (ax, by)]
            idx += [(b, b + 1, b + 2), (b, b + 2, b + 3)]
        shader.uniform_float("color", _rgb(col))
        batch_for_shader(shader, 'TRIS', {"pos": tris}, indices=idx).draw(shader)
    for col, rects in outlines.items():
        pts = []
        for ax, ay, bx, by in rects:
            pts += [(ax, ay), (bx, ay), (bx, ay), (bx, by), (bx, by), (ax, by), (ax, by), (ax, ay)]
        shader.uniform_float("color", _rgb(col))
        batch_for_shader(shader, 'LINES', {"pos": pts}).draw(shader)
    if labels:
        size = max(6.0, 11.0 * zoom * context.preferences.system.ui_scale)
        blf.size(0, size)
        for cx, cy, name, col, w in labels:
            text = name
            tw = blf.dimensions(0, text)[0]
            while tw > w - 4 and len(text) > 1:          # Softimage cuts long names to the box
                text = text[:-1]
                tw = blf.dimensions(0, text)[0]
            blf.position(0, cx - tw / 2, cy - size * 0.35, 0)
            blf.color(0, *_rgb(col))
            blf.draw(0, text)
        blf.color(0, *_rgb(LETTER))
        for ax, ay, text in letters:
            blf.position(0, ax, ay + 3, 0)
            blf.draw(0, text)
    from . import schematic_linkdraw
    schematic_linkdraw.draw_links(context, st, v2d, vl)
    gpu.state.blend_set('ALPHA')
    if _drag_state.get("line"):
        a, b = _drag_state["line"]
        shader.uniform_float("color", _rgb(SELECTED))
        batch_for_shader(shader, 'LINES', {"pos": [a, b]}).draw(shader)
    if _box_state.get("a") and _box_state.get("b"):
        (ax, ay), (bx, by) = _box_state["a"], _box_state["b"]
        shader.uniform_float("color", (1, 1, 1, 1))
        batch_for_shader(shader, 'LINES', {"pos": [(ax, ay), (bx, ay), (bx, ay), (bx, by), (bx, by), (ax, by),
                                                   (ax, by), (ax, ay)]}).draw(shader)
    gpu.state.blend_set('NONE')
    timings["draw"] = time.perf_counter() - t0


# --- operators ---------------------------------------------------------------------------------------------

class SI_OT_schematic_show(bpy.types.Operator):
    """Show the Schematic in this pane"""
    bl_idname = "si.schematic_show"
    bl_label = "Schematic"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        if context.area is None:
            return {'CANCELLED'}
        context.area.ui_type = TREE
        setup_space(context.area.spaces.active)
        return {'FINISHED'}


def setup_space(sp):
    """Our pane shows no Node Editor sidebar (Active Tool) or toolbar: they cover the canvas."""
    for attr in ("show_region_ui", "show_region_toolbar"):
        if hasattr(sp, attr):
            setattr(sp, attr, False)


def frame(context, only_selected=False):
    """Fit the view to every node (A) or the selected ones (F), with Blender's zoom_border."""
    st = state(context)
    vl = context.view_layer
    from . import explorer
    keys = [n for n in st["nodes"].values()
            if not only_selected or explorer._is_selected(n.ob, vl)]
    if not keys:
        return False
    xs = [st["pos"][n.uid][0] for n in keys] + [st["pos"][n.uid][0] + n.w for n in keys]
    ys = [st["pos"][n.uid][1] for n in keys] + [st["pos"][n.uid][1] + n.h for n in keys]
    pad = 30.0
    region = context.region
    v2d = region.view2d
    for _ in range(3):                   # zoom_border fits a rect given in region pixels: repeat while far off
        (ax, ay), (bx, by) = to_region(v2d, min(xs) - pad, min(ys) - pad), to_region(v2d, max(xs) + pad,
                                                                                    max(ys) + pad)
        bpy.ops.view2d.zoom_border(xmin=int(ax), xmax=int(bx), ymin=int(by), ymax=int(ay), wait_for_input=False)
    region.tag_redraw()
    return True


class SI_OT_schematic_frame(bpy.types.Operator):
    """Frame All (A) / Frame Selection (F) in the Schematic"""
    bl_idname = "si.schematic_frame"
    bl_label = "Frame"
    bl_options = {'INTERNAL'}

    selected: BoolProperty(options={'SKIP_SAVE'})

    def invoke(self, context, event):
        if not is_schematic(context):
            return {'PASS_THROUGH'}
        return self.execute(context)

    def execute(self, context):
        if not is_schematic(context) or context.region is None:
            return {'CANCELLED'}
        frame(context, self.selected)
        return {'FINISHED'}


class SI_OT_schematic_rearrange(bpy.types.Operator):
    """Rearrange All (Ctrl+R): lay the tree out again; nodes moved by hand keep their place"""
    bl_idname = "si.schematic_rearrange"
    bl_label = "Rearrange All"
    bl_options = {'INTERNAL'}

    def invoke(self, context, event):
        if not is_schematic(context):
            return {'PASS_THROUGH'}
        return self.execute(context)

    def execute(self, context):
        _state.clear()
        _redraw(context)
        return {'FINISHED'}


class SI_OT_schematic_setting(bpy.types.Operator):
    """Schematic View menu settings: layout direction and overall sort"""
    bl_idname = "si.schematic_setting"
    bl_label = "Schematic Setting"
    bl_options = {'INTERNAL'}

    direction: EnumProperty(items=[('', "", ""), ('VERTICAL', "Vertical Layout", ""),
                                   ('HORIZONTAL', "Horizontal Layout", "")], options={'SKIP_SAVE'})
    sort: EnumProperty(items=[('', "", ""), ('CREATION', "None (creation)", ""), ('TYPE', "by Type", ""),
                              ('HEIGHT_WIDTH', "by Height/Width", ""), ('WIDTH_HEIGHT', "by Width/Height", "")],
                       options={'SKIP_SAVE'})

    def execute(self, context):
        if self.direction:
            _settings["direction"] = self.direction
        if self.sort:
            _settings["sort"] = self.sort
        _state.clear()
        _redraw(context)
        return {'FINISHED'}


def _redraw(context):
    for w in context.window_manager.windows:
        for a in w.screen.areas:
            if a.type == 'NODE_EDITOR':
                a.tag_redraw()


# --- selection (spec schematic.selection; capture: reference/capture/schematic/clicks.json) -----------------

def node_at(context, x, y):
    """The node under region point (x, y), or None."""
    st = state(context)
    vx, vy = context.region.view2d.region_to_view(x, y)
    ly = -vy
    hit = None
    for n in st["nodes"].values():
        p = st["pos"].get(n.uid)
        if p is not None and p[0] <= vx <= p[0] + n.w and p[1] <= ly <= p[1] + n.h:
            hit = n
    return hit


def _mode(event):
    """Softimage's Schematic: Shift adds, Ctrl toggles, Ctrl+Shift removes (capture clicks.json)."""
    if event.ctrl and event.shift:
        return 'DESELECT'
    if event.ctrl:
        return 'TOGGLE'
    if event.shift:
        return 'ADD'
    return 'SET'


def pick(context, n, mode, how="node"):
    """Select a node like Softimage: 'node' (left), 'branch' (middle: it and its descendants), 'tree' (right: the
    topmost ancestor's branch), through the Explorer's selection rules (hidden picks, Edit Mode, branch boxes)."""
    from . import explorer
    ob = n.ob
    if how == "tree":
        while ob.parent is not None:
            ob = ob.parent
    ok = explorer.select(context, ob.name, mode, branch=how in ("branch", "tree"), obj=ob)
    explorer._redraw_explorers(context)
    return ok


class SI_OT_schematic_click(bpy.types.Operator):
    """Click in the Schematic: left selects the node, right the tree (Shift adds, Ctrl toggles, Ctrl+Shift
    removes); Alt+right opens the node menu"""
    bl_idname = "si.schematic_click"
    bl_label = "Schematic Select"
    bl_options = {'INTERNAL', 'UNDO'}

    how: EnumProperty(items=[('node', "Node", ""), ('tree', "Tree", ""), ('menu', "Menu", "")], options={'SKIP_SAVE'})

    def invoke(self, context, event):
        if not is_schematic(context) or context.region is None or context.region.type != 'WINDOW':
            return {'PASS_THROUGH'}
        n = node_at(context, event.mouse_region_x, event.mouse_region_y)
        if self.how == 'menu':
            from . import explorer
            explorer.menu_target.clear()
            if n is None:
                bpy.ops.wm.call_menu(name="SI_MT_schematic_view")
            else:
                explorer.menu_target.update(node=("object", n.name), key="")
                bpy.ops.wm.call_menu(name="SI_MT_schematic_node")
            return {'CANCELLED'}
        if n is None:
            return {'CANCELLED'}           # Softimage: a click on empty space keeps the selection
        pick(context, n, _mode(event), self.how)
        context.area.tag_redraw()
        return {'FINISHED'}


class SI_OT_schematic_branch(bpy.types.Operator):
    """Middle button in the Schematic: click = branch select, drag = pan (like the Explorer)"""
    bl_idname = "si.schematic_branch"
    bl_label = "Schematic Branch Pick"
    bl_options = {'INTERNAL', 'UNDO'}

    def invoke(self, context, event):
        if not is_schematic(context) or context.region is None or context.region.type != 'WINDOW':
            return {'PASS_THROUGH'}
        self.start = (event.mouse_region_x, event.mouse_region_y)
        self.last = self.start
        self.mode = _mode(event)
        self.panned = False
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if event.type == 'MOUSEMOVE':
            x, y = event.mouse_region_x, event.mouse_region_y
            if not self.panned and abs(x - self.start[0]) + abs(y - self.start[1]) > \
                    context.preferences.inputs.drag_threshold_mouse:
                self.panned = True
            if self.panned:
                bpy.ops.view2d.pan(deltax=int(self.last[0] - x), deltay=int(self.last[1] - y))
                self.last = (x, y)
            return {'RUNNING_MODAL'}
        if event.type == 'MIDDLEMOUSE' and event.value == 'RELEASE':
            if self.panned:
                return {'CANCELLED'}
            n = node_at(context, *self.start)
            if n is None:
                return {'CANCELLED'}
            pick(context, n, self.mode, "branch")
            context.area.tag_redraw()
            return {'FINISHED'}
        if event.type == 'ESC':
            return {'CANCELLED'}
        return {'RUNNING_MODAL'}


_box_state = {}
_drag_state = {}


def drop_parent(context, node, target):
    """Alt+drag onto a node: parent to it, keeping world positions (the Explorer's drop rules: the selection goes
    when the dragged node is selected, a branch pick moves as a whole, never under its own descendants). Onto
    empty space: nothing (capture: Softimage doesn't unparent there)."""
    from . import explorer
    if node is None or target is None or target.uid == node.uid:
        return None
    vl = context.view_layer
    sources = explorer.explorer_selection(context) if explorer._is_selected(node.ob, vl) else [node.ob]
    row = explorer.Row(0, "ob:" + target.name, target.name, 'OBJECT_DATA', False, (target.name, ""), ref=target.ob)
    done = explorer.drop(context, "objects", sources or [node.ob], row)
    _gen[0] += 1
    return done


def moved_with(context, node):
    """The nodes a Pick and Move drag takes along: the whole selection when the dragged node is selected (shown
    nodes only), else the node alone."""
    from . import explorer
    vl = context.view_layer
    if not explorer._is_selected(node.ob, vl):
        return [node]
    st = state(context)
    gone = st.get("hidden", ())
    return [n for n in st["nodes"].values()
            if n.uid in st["pos"] and n.uid not in gone and explorer._is_selected(n.ob, vl)] or [node]


def move_nodes(context, nodes, a, b):
    """Pick and Move: the nodes move by the drag; their positions are kept on the objects (saved with the file,
    undoable) and they stay put in every layout (Softimage's position lock)."""
    st = state(context)
    v2d = context.region.view2d
    (ax, ay), (bx, by) = v2d.region_to_view(*a), v2d.region_to_view(*b)
    dx, dy = bx - ax, -(by - ay)
    for n in nodes:
        x, y = st["pos"][n.uid]
        n.ob[POS] = (x + dx, y + dy)
    _gen[0] += 1


def rearrange_branches(context, obs):
    """Rearrange Selection: the selected branches laid out again under their top nodes, which stay where they
    are. Positions moved by hand inside those branches are cleared (asking to rearrange a branch means tidying
    it; Rearrange All keeps hand-moved nodes, as Softimage does). Returns True when something was rearranged."""
    st = state(context)
    nodes = st["nodes"]
    sel = {ob.session_uid for ob in obs if ob.session_uid in nodes}
    tops = {u for u in sel if nodes[u].parent not in sel}
    if not tops:
        return False
    kids = {}
    for n in nodes.values():
        kids.setdefault(n.parent, []).append(n.uid)
    sub, todo = set(), list(tops)
    while todo:
        u = todo.pop()
        sub.add(u)
        todo.extend(kids.get(u, ()))
    inner = sub - tops
    for u in inner:
        ob = nodes[u].ob
        if POS in ob:
            del ob[POS]
    keep = {k: v for k, v in st["pos"].items() if k not in inner}
    pinned = {n.uid: tuple(n.ob[POS]) for n in nodes.values() if POS in n.ob}
    extra = {}
    st["pos"] = layout(nodes, pinned, keep, _collapsed.get(context.scene.as_pointer(), ()), rearrange=tops,
                       out=extra)
    st.update(extra)
    st["pinned"] = set(pinned)
    st["sig"] = signature(context.scene, context.view_layer)     # the cleared positions are part of it
    return True


def reset_positions(obs):
    for ob in obs:
        if POS in ob:
            del ob[POS]
    _gen[0] += 1


class SI_OT_schematic_press(bpy.types.Operator):
    """Left button in the Schematic: a click selects the node (Shift adds, Ctrl toggles, Ctrl+Shift removes; on
    empty space the selection stays), a drag selects the nodes in its rectangle. The press itself is taken here so
    Blender's Node Editor tools (select box, tweak) never start on our canvas."""
    bl_idname = "si.schematic_press"
    bl_label = "Schematic Select"
    bl_options = {'INTERNAL', 'UNDO'}

    def invoke(self, context, event):
        if not is_schematic(context) or context.region is None or context.region.type != 'WINDOW':
            return {'PASS_THROUGH'}
        self.a = self.b = (event.mouse_region_x, event.mouse_region_y)
        self.mode = _mode(event)
        self.dragging = False
        self.node = node_at(context, *self.a)
        # Softimage: Alt while dragging a node onto another parents it; the Pick and Move tool (M) moves nodes
        self.kind = "parent" if event.alt and self.node is not None else \
            "move" if _tool["move"] and self.node is not None else "box"
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if event.type in ('MOUSEMOVE', 'INBETWEEN_MOUSEMOVE'):
            self.b = (event.mouse_region_x, event.mouse_region_y)
            if not self.dragging and abs(self.b[0] - self.a[0]) + abs(self.b[1] - self.a[1]) > \
                    context.preferences.inputs.drag_threshold_mouse:
                self.dragging = True
            if self.dragging:
                if self.kind == "box":
                    _box_state.update(a=self.a, b=self.b)
                elif self.kind == "move":            # the moved nodes follow the mouse while dragging
                    if "move" not in _drag_state:
                        _drag_state["move"] = {n.uid for n in moved_with(context, self.node)}
                    v2d = context.region.view2d
                    (ax, ay), (bx, by) = v2d.region_to_view(*self.a), v2d.region_to_view(*self.b)
                    _drag_state["off"] = (bx - ax, -(by - ay))
                else:
                    _drag_state["line"] = (self.a, self.b)
                context.area.tag_redraw()
            return {'RUNNING_MODAL'}
        if event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
            _box_state.clear()
            _drag_state.clear()
            if self.dragging and self.kind == "parent":
                done = drop_parent(context, self.node, node_at(context, *self.b))
                context.area.tag_redraw()
                return {'FINISHED'} if done else {'CANCELLED'}
            if self.dragging and self.kind == "move":
                move_nodes(context, moved_with(context, self.node), self.a, self.b)
                context.area.tag_redraw()
                return {'FINISHED'}
            if self.dragging:
                self.box_select(context)
            else:
                from . import schematic_linkdraw as LD
                n = node_at(context, *self.a)
                if n is None:
                    ln = LD.link_at(context, state(context), self.a[0], self.a[1], context.view_layer)
                    if ln is None:            # Softimage: a click on empty space keeps the selection
                        context.area.tag_redraw()
                        return {'CANCELLED'}
                    LD.select_link(context, ln)
                    context.area.tag_redraw()
                    return {'FINISHED'}
                LD.clear_pick()
                pick(context, n, self.mode, "node")
            context.area.tag_redraw()
            return {'FINISHED'}
        if event.type in ('ESC', 'RIGHTMOUSE') and event.value == 'PRESS':
            _box_state.clear()
            _drag_state.clear()
            context.area.tag_redraw()
            return {'CANCELLED'}
        return {'RUNNING_MODAL'}

    def cancel(self, context):
        _box_state.clear()
        _drag_state.clear()

    def box_select(self, context):
        from . import explorer
        st = state(context)
        v2d = context.region.view2d
        (ax, ay), (bx, by) = v2d.region_to_view(*self.a), v2d.region_to_view(*self.b)
        lx0, lx1 = min(ax, bx), max(ax, bx)
        ly0, ly1 = -max(ay, by), -min(ay, by)
        inside = [n.ob for n in st["nodes"].values() if n.uid in st["pos"]
                  and lx0 <= st["pos"][n.uid][0] + n.w / 2 <= lx1 and ly0 <= st["pos"][n.uid][1] + n.h / 2 <= ly1]
        explorer.select_objects(context, inside, self.mode)
        explorer._redraw_explorers(context)


class SI_OT_schematic_edit(bpy.types.Operator):
    """Schematic editing: Collapse/Expand (N), Pick and Move Tool (M), Rearrange Selection (Shift+R), Reset User
    Position(s), Rename (F2: Blender's rename popup), Properties (Enter)"""
    bl_idname = "si.schematic_edit"
    bl_label = "Schematic Edit"
    bl_options = {'INTERNAL', 'UNDO'}

    action: EnumProperty(items=[('COLLAPSE', "Collapse/Expand Nodes", ""), ('MOVE_TOOL', "Pick and Move Tool", ""),
                                ('SELECT_TOOL', "Select Tool", ""), ('REARRANGE_SEL', "Rearrange Selection", ""),
                                ('RESET', "Reset User Position(s)", ""), ('RESET_ALL', "Reset All User Positions", ""),
                                ('RENAME', "Rename", ""), ('PROPERTIES', "Properties", "")], options={'SKIP_SAVE'})
    obj: bpy.props.StringProperty(options={'SKIP_SAVE'})

    def invoke(self, context, event):
        if not is_schematic(context):
            return {'PASS_THROUGH'}
        return self.execute(context)

    def _targets(self, context):
        from . import explorer
        if self.obj:
            from .explorer import node_targets
            return node_targets(context, self.obj)
        return explorer.explorer_selection(context)

    def execute(self, context):
        from . import explorer
        a = self.action
        scene = context.scene
        if a == 'MOVE_TOOL':
            _tool["move"] = True
            return {'CANCELLED'}
        if a == 'SELECT_TOOL':
            _tool["move"] = False
            return {'CANCELLED'}
        obs = self._targets(context)
        if a == 'COLLAPSE':
            col = _collapsed.setdefault(scene.as_pointer(), set())
            for ob in obs:
                col.symmetric_difference_update({ob.session_uid})
            _gen[0] += 1
            _redraw(context)
            return {'CANCELLED'}           # view state only: no undo step
        if a == 'REARRANGE_SEL':
            done = rearrange_branches(context, obs)
            _redraw(context)
            return {'FINISHED'} if done else {'CANCELLED'}
        if a in ('RESET', 'RESET_ALL'):
            reset_positions(list(scene.objects) if a == 'RESET_ALL' else obs)
            _state.clear()
            _redraw(context)
            return {'FINISHED'}
        if a == 'RENAME':
            ob = bpy.data.objects.get(self.obj) if self.obj else context.view_layer.objects.active
            if ob is None:
                return {'CANCELLED'}
            explorer.select(context, ob.name, 'SET')
            bpy.ops.wm.call_panel(name="TOPBAR_PT_name", keep_open=False)
            return {'CANCELLED'}
        if a == 'PROPERTIES':
            ob = bpy.data.objects.get(self.obj) if self.obj else context.view_layer.objects.active
            bpy.ops.si.ppg_popup('INVOKE_DEFAULT', obj=ob.name if ob else "")
            return {'CANCELLED'}
        return {'CANCELLED'}


class SI_MT_schematic_node(bpy.types.Menu):
    """A node's Alt+right-click menu: the Schematic items, then the Explorer's object menu (capture)"""
    bl_label = "Schematic Node"

    def draw(self, context):
        from . import explorer
        lay = self.layout
        lay.operator_context = 'INVOKE_REGION_WIN'
        name = explorer.menu_target.get("node", (None, ""))[1]
        uid = bpy.data.objects[name].session_uid if name in bpy.data.objects else None
        collapsed = uid in _collapsed.get(context.scene.as_pointer(), ())
        o = lay.operator("si.schematic_edit", text="Expand Node" if collapsed else "Collapse Node")
        o.action, o.obj = 'COLLAPSE', name
        lay.separator()
        o = lay.operator("si.schematic_edit", text="Rearrange")
        o.action, o.obj = 'REARRANGE_SEL', name
        o = lay.operator("si.schematic_edit", text="Reset User Position(s)")
        o.action, o.obj = 'RESET', name
        _grey(lay, "Freeze Child Ordering")
        lay.separator()
        explorer._draw_node_menu(lay, explorer.OBJECT_MENU[3:])      # Rename, Delete, ... as in the Explorer


# --- header ------------------------------------------------------------------------------------------------

def _grey(layout, text):
    row = layout.row()
    row.enabled = False
    row.label(text=text)


class SI_MT_schematic_scope(bpy.types.Menu):
    bl_label = "Scope"

    def draw(self, context):
        self.layout.label(text="Scene", icon='RADIOBUT_ON')
        _grey(self.layout, "Current Layer")
        _grey(self.layout, "Selection")


class SI_MT_schematic_edit(bpy.types.Menu):
    bl_label = "Edit"

    def draw(self, context):
        lay = self.layout
        lay.operator_context = 'INVOKE_REGION_WIN'
        lay.operator("si.schematic_edit", text="Select Tool",
                     icon='RADIOBUT_OFF' if _tool["move"] else 'RADIOBUT_ON').action = 'SELECT_TOOL'
        lay.operator("si.schematic_edit", text="Pick and Move Tool",
                     icon='RADIOBUT_ON' if _tool["move"] else 'RADIOBUT_OFF').action = 'MOVE_TOOL'
        for t in ("Translate Tool", "Reorder Nodes Tool", "Navigation Tool", "Pan and Zoom Tool",
                  "Rectangular Zoom Tool"):
            _grey(lay, t)
        lay.separator()
        lay.operator("si.schematic_edit", text="Collapse/Expand Nodes").action = 'COLLAPSE'


class SI_MT_schematic_show(bpy.types.Menu):
    bl_label = "Show"

    def draw(self, context):
        from . import schematic_linkdraw
        for t in ("Lights", "Cameras", "3D Geometry", "Curves", "Nulls", "Chains", "Texture Controls",
                  "Control Objects", None, "Models", "Materials"):
            if t is None:
                self.layout.separator()
            else:
                _grey(self.layout, t)
        self.layout.separator()
        schematic_linkdraw.draw_show_menu(self.layout)


class SI_MT_schematic_view(bpy.types.Menu):
    bl_label = "View"

    def draw(self, context):
        lay = self.layout
        lay.operator_context = 'INVOKE_REGION_WIN'
        lay.operator("si.schematic_frame", text="Frame Selection").selected = True
        lay.operator("si.schematic_frame", text="Frame All").selected = False
        _grey(lay, "Reset Zoom")
        lay.separator()
        for d, label in (('VERTICAL', "Vertical Layout"), ('HORIZONTAL', "Horizontal Layout")):
            lay.operator("si.schematic_setting", text=label,
                         icon='RADIOBUT_ON' if _settings["direction"] == d else 'RADIOBUT_OFF').direction = d
        lay.separator()
        lay.operator("si.schematic_rearrange", text="Rearrange All")
        lay.operator("si.schematic_edit", text="Rearrange Selection").action = 'REARRANGE_SEL'
        lay.menu("SI_MT_schematic_sort", text="Overall Sort")
        lay.separator()
        lay.operator("si.schematic_edit", text="Reset All User Positions").action = 'RESET_ALL'
        for t in ("Freeze Root Node Ordering", None, "Parallel Links", None,
                  "Show Icons", "Show Grid", None, "Clean Hierarchy Upon Structure Change",
                  "Clean All Upon Show Mode Change", None, "Use Standard Colors", "Use Wire Colors",
                  "Use Diffuse Colors"):
            if t is None:
                lay.separator()
            else:
                _grey(lay, t)


class SI_MT_schematic_sort(bpy.types.Menu):
    bl_label = "Overall Sort"

    def draw(self, context):
        for s, label in (('CREATION', "None (creation)"), ('TYPE', "by Type"), ('HEIGHT_WIDTH', "by Height/Width"),
                         ('WIDTH_HEIGHT', "by Width/Height")):
            self.layout.operator("si.schematic_setting", text=label,
                                 icon='RADIOBUT_ON' if _settings["sort"] == s else 'RADIOBUT_OFF').sort = s


_orig = {}


def draw_header(self, context):
    if not is_schematic(context):
        return _orig["draw"](self, context)
    layout = self.layout
    layout.template_header()
    row = layout.row(align=True)
    row.menu("SI_MT_schematic_scope", text="Scene")
    row.menu("SI_MT_schematic_edit", text="Edit")
    row.menu("SI_MT_schematic_show", text="Show")
    row.menu("SI_MT_schematic_view", text="View")


# --- keys --------------------------------------------------------------------------------------------------

# View2D runs before every Node Editor keymap (probe 2026-11-16); all items pass through outside the Schematic.
KEYS = (('LEFTMOUSE', 'PRESS', {"any": True}, "si.schematic_press", {}),
        ('RIGHTMOUSE', 'PRESS', {}, "si.schematic_click", {"how": 'tree'}),
        ('RIGHTMOUSE', 'PRESS', {"shift": True}, "si.schematic_click", {"how": 'tree'}),
        ('RIGHTMOUSE', 'PRESS', {"ctrl": True}, "si.schematic_click", {"how": 'tree'}),
        ('RIGHTMOUSE', 'PRESS', {"alt": True}, "si.schematic_click", {"how": 'menu'}),
        ('MIDDLEMOUSE', 'PRESS', {"any": True}, "si.schematic_branch", {}),
        ('A', 'PRESS', {}, "si.schematic_frame", {"selected": False}),
        ('DEL', 'PRESS', {}, "si.schematic_link_delete", {}),
        ('X', 'PRESS', {}, "si.schematic_link_delete", {}),
        ('N', 'PRESS', {}, "si.schematic_edit", {"action": 'COLLAPSE'}),
        ('M', 'PRESS', {}, "si.schematic_edit", {"action": 'MOVE_TOOL'}),
        ('SPACE', 'PRESS', {}, "si.schematic_edit", {"action": 'SELECT_TOOL'}),
        ('R', 'PRESS', {"shift": True}, "si.schematic_edit", {"action": 'REARRANGE_SEL'}),
        ('F2', 'PRESS', {}, "si.schematic_edit", {"action": 'RENAME'}),
        ('RET', 'PRESS', {}, "si.schematic_edit", {"action": 'PROPERTIES'}),
        ('F', 'PRESS', {}, "si.schematic_frame", {"selected": True}),
        ('R', 'PRESS', {"ctrl": True}, "si.schematic_rearrange", {}))
_items = []
_handles = []


def _bind_keys():
    kc = bpy.context.window_manager.keyconfigs.addon
    if kc is None:
        return
    km = kc.keymaps.new(name="View2D", space_type='EMPTY', region_type='WINDOW')
    for key, value, mods, op, props in KEYS:
        kmi = km.keymap_items.new(op, key, value, **mods)
        for k, v in props.items():
            setattr(kmi.properties, k, v)
        _items.append((km, kmi))


def restore_panes():
    """Mode off: Schematic panes (any screen) become 3D views again."""
    for scr in bpy.data.screens:
        for area in scr.areas:
            if area.type == 'NODE_EDITOR' and getattr(area.spaces.active, "tree_type", "") == TREE:
                try:
                    area.type = 'VIEW_3D'
                except Exception as e:
                    print("si_kit: could not restore schematic pane:", e)


classes = (SI_SchematicTree, SI_OT_schematic_show, SI_OT_schematic_click, SI_OT_schematic_branch,
           SI_OT_schematic_press, SI_OT_schematic_edit, SI_MT_schematic_node, SI_OT_schematic_frame, SI_OT_schematic_rearrange,
           SI_OT_schematic_setting, SI_MT_schematic_scope, SI_MT_schematic_edit, SI_MT_schematic_show,
           SI_MT_schematic_view, SI_MT_schematic_sort)


def register():
    from . import schematic_linkdraw
    for c in classes:
        bpy.utils.register_class(c)
    schematic_linkdraw.register()
    cls = bpy.types.NODE_HT_header
    _orig["draw"] = cls.draw
    cls.draw = draw_header
    _handles.append(bpy.types.SpaceNodeEditor.draw_handler_add(_overlay, (), 'WINDOW', 'POST_PIXEL'))
    bpy.app.handlers.load_post.append(_on_load)
    for lst in (bpy.app.handlers.depsgraph_update_post, bpy.app.handlers.undo_post, bpy.app.handlers.redo_post):
        lst.append(_on_change)
    _bind_keys()


def unregister():
    restore_panes()
    for km, kmi in _items:
        try:
            km.keymap_items.remove(kmi)
        except (ReferenceError, RuntimeError):
            pass
    _items.clear()
    while _handles:
        bpy.types.SpaceNodeEditor.draw_handler_remove(_handles.pop(), 'WINDOW')
    while _on_load in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_load)
    for lst in (bpy.app.handlers.depsgraph_update_post, bpy.app.handlers.undo_post, bpy.app.handlers.redo_post):
        while _on_change in lst:
            lst.remove(_on_change)
    if "draw" in _orig:
        bpy.types.NODE_HT_header.draw = _orig.pop("draw")
    _state.clear()
    from . import schematic_linkdraw
    schematic_linkdraw.unregister()
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
