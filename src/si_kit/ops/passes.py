# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Alex Doss
"""Passes and partitions (spec render.passes).

A pass is a view layer; its partitions are collections under `Passes/<pass>`. The file holds two spaces at once:
Blender space (the user's view layers and collections) and SI space (the pass view layers and the `Passes`
tree), each excluding the other's collections. Softimage mode on / off only switches each window's view layer
and the `use` flags (what F12 renders); nothing is converted. `sync` is the one rule that keeps membership right
(no handlers): run by every pass command and every switch into SI space.
"""

import bpy
from bpy.props import EnumProperty, StringProperty

ROOT_NAME = "Passes"
DEFAULT_PASS = "Default_Pass"
BACKGROUND = {"OBJECT": "Background_Objects_Partition", "LIGHT": "Background_Lights_Partition"}
GEOMETRY = {'MESH', 'CURVE', 'CURVES', 'SURFACE', 'META', 'FONT', 'POINTCLOUD', 'VOLUME', 'GREASEPENCIL'}


# --- lookups ---------------------------------------------------------------------------------------------

def kind(ob):
    """'LIGHT' (light partitions), 'OBJECT' (object partitions) or None (cameras, nulls...: in no partition)."""
    if ob.type == 'LIGHT':
        return "LIGHT"
    return "OBJECT" if ob.type in GEOMETRY else None


def root(scene):
    return next((c for c in scene.collection.children if c.get("si_passes_root")), None)


def in_passes(scene, coll):
    r = root(scene)
    return r is not None and (coll == r or coll in r.children_recursive)


def _pass_colls(scene):
    r = root(scene)
    return [c for c in r.children if c.get("si_pass") and "si_partition" not in c] if r else []


def pass_collection(scene, name):
    return next((c for c in _pass_colls(scene) if c["si_pass"] == name), None)


def pass_names(scene):
    out = []
    for c in _pass_colls(scene):                         # one name once (a pass collection copied in the Outliner)
        if c["si_pass"] in scene.view_layers and c["si_pass"] not in out:
            out.append(c["si_pass"])
    return out


def is_pass(scene, view_layer):
    return view_layer is not None and view_layer.name in pass_names(scene)


def partitions(scene, name):
    pc = pass_collection(scene, name)
    return [c for c in pc.children if "si_partition" in c] if pc else []


def find_partition(scene, pass_name, short):
    return next((c for c in partitions(scene, pass_name) if c.get("si_name") == short), None)


def background(scene, pass_name, k):
    return next((c for c in partitions(scene, pass_name) if c.get("si_background") and c["si_partition"] == k), None)


def _tree(view_layer):
    """The view layer's layer collection tree (Blender builds it lazily for a new view layer)."""
    if view_layer.layer_collection is None:
        view_layer.update()
    return view_layer.layer_collection


def _layer_collection(view_layer, coll):
    stack = [_tree(view_layer)]
    while stack:
        lc = stack.pop()
        if lc.collection == coll:
            return lc
        stack.extend(lc.children)
    return None


# --- building blocks -------------------------------------------------------------------------------------

def _ensure_root(scene):
    r = root(scene)
    if r is None:
        r = bpy.data.collections.new(ROOT_NAME)
        r["si_passes_root"] = True
        scene.collection.children.link(r)
    return r


def _new_partition(scene, pass_name, short, k, is_background=False):
    taken = {p.get("si_name") for p in partitions(scene, pass_name)}
    name, n = short, 0
    while name in taken:                                 # unique within the pass, like Softimage
        n += 1
        name = "%s.%03d" % (short, n)
    # the collection name is global: another scene's pass of the same name may hold it and Blender adds .001 then;
    # the short name (shown in the Explorer, used for lookups) stays the pass-local one
    c = bpy.data.collections.new("%s.%s" % (pass_name, name))
    c["si_pass"] = pass_name
    c["si_partition"] = k
    c["si_name"] = name
    if is_background:
        c["si_background"] = True
    pass_collection(scene, pass_name).children.link(c)
    return c


def _new_pass(scene, name):
    vl = scene.view_layers.new(name)                     # Blender makes the name unique
    vl["si_pass"] = vl.name                              # the view layer remembers its pass: renames follow
    pc = bpy.data.collections.new(vl.name)
    pc["si_pass"] = vl.name
    _ensure_root(scene).children.link(pc)
    for k, short in BACKGROUND.items():
        _new_partition(scene, vl.name, short, k, True)
    return vl


def _blender_collection(scene):
    """A collection of Blender space (not under Passes) to keep objects in; made if there is none."""
    target = next((c for c in scene.collection.children
                   if not c.get("si_passes_root") and c.library is None and c.override_library is None), None)
    if target is None:
        target = bpy.data.collections.new("Collection")
        scene.collection.children.link(target)
    return target


def memberships(scene):
    """{object: set of the scene's collections holding it}. Object.users_collection scans every collection's
    objects (measured 2.7 ms per call at 10k objects), so the pass commands build this once instead."""
    out = {}
    for c in [scene.collection] + list(scene.collection.children_recursive):
        for o in c.objects:
            out.setdefault(o, set()).add(c)
    return out


def _remove_stale(scene):
    """Passes whose view layer was deleted or renamed with Blender's tools: their collections go, but objects
    that live only there (made in that pass) are first kept in the other passes, or in Blender space."""
    stale = [pc for pc in _pass_colls(scene) if pc["si_pass"] not in scene.view_layers]
    for pc in list(stale):                               # renamed with Blender's tools: the pass follows its layer
        old = pc["si_pass"]
        vl = next((v for v in scene.view_layers if v.get("si_pass") == old), None)
        if vl is not None and pass_collection(scene, vl.name) is None:
            for c in [pc] + list(pc.children):
                c["si_pass"] = vl.name
            vl["si_pass"] = vl.name
            if scene.get("si_last_pass") == old:
                scene["si_last_pass"] = vl.name
            stale.remove(pc)
    if not stale:
        return
    gone = set()
    for pc in stale:
        gone.add(pc)
        gone.update(pc.children_recursive)
    live = pass_names(scene)
    member = memberships(scene)
    for ob in list(scene.objects):
        users = member.get(ob, set())
        if users and users <= gone:
            home = None
            if live:
                k = kind(ob)
                home = (background(scene, live[0], k) if k else None) or pass_collection(scene, live[0])
            (home or _blender_collection(scene)).objects.link(ob)
    for pc in stale:
        for c in list(pc.children):
            bpy.data.collections.remove(c)
        bpy.data.collections.remove(pc)


def sync(scene):
    """Every object in every pass where it belongs, and each space's collections excluded in the other."""
    r = _ensure_root(scene)
    _remove_stale(scene)
    names = pass_names(scene)
    member = memberships(scene)
    obs = [(ob, kind(ob), member.get(ob, set())) for ob in scene.objects]
    for name in names:
        pc = pass_collection(scene, name)
        for k, short in BACKGROUND.items():
            if background(scene, name, k) is None:
                _new_partition(scene, name, short, k, True)
        parts = partitions(scene, name)
        bg = {k: background(scene, name, k) for k in BACKGROUND}
        for ob, k, users in obs:
            inside = [c for c in parts if c in users]
            if k is None:
                for c in inside:
                    c.objects.unlink(ob)
                if pc not in users:
                    pc.objects.link(ob)
                continue
            if pc in users:
                pc.objects.unlink(ob)
            right = sorted((c for c in inside if c["si_partition"] == k),     # a user partition wins over
                           key=lambda c: bool(c.get("si_background")))          # background if in both
            for c in inside:
                if c not in right[:1]:
                    c.objects.unlink(ob)
            if not right:
                bg[k].objects.link(ob)
    for vl in scene.view_layers:
        mine = vl.name in names
        if mine and vl.get("si_pass") != vl.name:
            vl["si_pass"] = vl.name
        for lc in _tree(vl).children:                    # flags written only when they change (each write re-syncs)
            if lc.collection == r:
                _exclude(lc, not mine)
                if mine:
                    for plc in lc.children:
                        _exclude(plc, plc.collection.get("si_pass") != vl.name)
            elif mine:
                _exclude(lc, True)


def _exclude(lc, on):
    if lc.exclude != on:
        lc.exclude = on


def carry_selection(old, new):
    """Softimage's selection is the same in every pass; Blender keeps one per view layer. Switching passes copies
    the selection and the active object over (review finding, Gemini 4 Carbon, 2026-11-16)."""
    if old is None or new is None or old == new:
        return
    new.update()                                         # objects sync just linked aren't in new.objects before this
    sel = list(old.objects.selected)
    names = {o.name for o in sel}
    for o in list(new.objects.selected):
        if o.name not in names:
            o.select_set(False, view_layer=new)
    for o in sel:
        try:
            o.select_set(True, view_layer=new)
        except RuntimeError:                             # not in that pass (excluded there)
            pass
    act = old.objects.active
    new.objects.active = act if act is not None and act.name in new.objects else None
    try:                                                 # the Explorer's picks of objects Blender can't select
        from ..ui import explorer
        for n in list(explorer.hidden_picks):
            o = new.objects.get(n)
            if o is not None:
                explorer._set_selected(o, new, True)
    except (ImportError, AttributeError):
        pass


def set_current(scene, name, window=None, carry_from=None):
    vl = scene.view_layers[name]
    old = carry_from or (window.view_layer if window is not None and window.scene == scene else None)
    last = scene.get("si_last_pass")
    if old is None and isinstance(last, str) and last in scene.view_layers:
        old = scene.view_layers[last]
    carry_selection(old, vl)
    scene["si_last_pass"] = name
    if window is not None:                               # Softimage has one current pass: every window on it
        for w in _windows() or [window]:
            if w.scene == scene:
                w.view_layer = vl
    lc = _layer_collection(vl, background(scene, name, "OBJECT"))
    if lc is not None:
        vl.active_layer_collection = lc
    return vl


def _blender_layer(scene):
    names = pass_names(scene)
    vl = scene.view_layers.get(scene.get("si_blender_layer", ""))
    if vl is None or vl.name in names:
        vl = next((v for v in scene.view_layers if v.name not in names), None)
    if vl is None:
        vl = scene.view_layers.new("ViewLayer")
    return vl


# --- the two spaces --------------------------------------------------------------------------------------

def enter_si(scene, window=None):
    """Into SI space: make Default_Pass the first time, sync, show the last pass. Returns its view layer."""
    if root(scene) is not None:
        _remove_stale(scene)                             # renamed / deleted pass layers first: they decide the rest
    if window is not None and window.scene == scene and not is_pass(scene, window.view_layer):
        scene["si_blender_layer"] = window.view_layer.name
    elif not scene.get("si_blender_layer"):
        scene["si_blender_layer"] = next((v.name for v in scene.view_layers if not is_pass(scene, v)), "")
    if scene.get("si_space") != "SI":                    # keep the Blender space's own `use` flags
        scene["si_blender_use"] = {v.name: v.use for v in scene.view_layers if not is_pass(scene, v)}
    if not pass_names(scene):
        _ensure_root(scene)
        _new_pass(scene, DEFAULT_PASS)
    sync(scene)
    names = pass_names(scene)
    for v in scene.view_layers:
        v.use = v.name in names
    scene["si_space"] = "SI"
    last = scene.get("si_last_pass")
    return set_current(scene, last if last in names else names[0], window)


def leave_si(scene, window=None):
    """Back to Blender space: the user's view layer and `use` flags. Returns that view layer."""
    if not pass_names(scene) and scene.get("si_space") != "SI":
        return None
    if window is not None and window.scene == scene and is_pass(scene, window.view_layer):
        scene["si_last_pass"] = window.view_layer.name
    bl = _blender_layer(scene)                           # first: sync then excludes Passes in a new one too
    sync(scene)
    _tree(bl)                                            # a new view layer has no active collection yet
    target = bl.active_layer_collection.collection if bl.active_layer_collection else scene.collection
    if target == scene.collection or in_passes(scene, target) or target.library is not None \
            or target.override_library is not None:
        target = _blender_collection(scene)
    r = root(scene)
    si_colls = ({r} | set(r.children_recursive)) if r is not None else set()
    blender = ({scene.collection} | set(scene.collection.children_recursive)) - si_colls
    member = memberships(scene)
    for ob in list(scene.objects):                       # made in SI space: show it in Blender space too
        if not any(c in blender for c in member.get(ob, ())):      # (groups outside the scene don't count)
            target.objects.link(ob)
    names = pass_names(scene)
    saved = scene.get("si_blender_use", {})
    for v in scene.view_layers:
        v.use = False if v.name in names else bool(saved.get(v.name, True))
    scene["si_space"] = "BLENDER"
    if window is not None and window.scene == scene:
        if is_pass(scene, window.view_layer):
            carry_selection(window.view_layer, bl)
        window.view_layer = bl
    return bl


# --- commands --------------------------------------------------------------------------------------------

def _movable(objects, k):
    return [o for o in objects if kind(o) == k]


def move_to_partition(scene, coll, objects):
    """MoveToPartition / AddToPartition: out of their partition in that pass, into `coll` (same kind only)."""
    parts = partitions(scene, coll["si_pass"])
    held = {c: set(c.objects) for c in parts}            # the pass's partitions only, once
    moved = _movable(objects, coll["si_partition"])
    for ob in moved:
        for c in parts:
            if c != coll and ob in held[c]:
                c.objects.unlink(ob)
        if ob not in held[coll]:
            coll.objects.link(ob)
    return moved


def create_partition(scene, pass_name, short, objects):
    lights = [o for o in objects if kind(o) == "LIGHT"]
    geo = [o for o in objects if kind(o) == "OBJECT"]
    c = _new_partition(scene, pass_name, short, "LIGHT" if lights and not geo else "OBJECT")
    move_to_partition(scene, c, objects)
    return c


def remove_from_partition(scene, pass_name, objects):
    for k in BACKGROUND:
        move_to_partition(scene, background(scene, pass_name, k), _movable(objects, k))


def copy_partition(scene, coll, target_pass):
    if coll.get("si_background"):
        return None
    c = _new_partition(scene, target_pass, coll["si_name"], coll["si_partition"])
    move_to_partition(scene, c, list(coll.objects))
    _copy_flags(scene, coll, c)
    return c


def _copy_flags(scene, src, dst):
    """The override flags of one partition onto another (its own pass)."""
    a, b = partition_layer(scene, src), partition_layer(scene, dst)
    if a is not None and b is not None:
        for attr, _label in FLAGS:
            setattr(b, attr, getattr(a, attr))


def _copy_pass_settings(src, dst):
    """A pass's own settings (whole-pass overrides, render passes, the engines' passes) onto another view layer."""
    for attr in ("material_override", "world_override", "samples", "use_motion_blur"):
        setattr(dst, attr, getattr(src, attr))
    for owner_a, owner_b in ((src, dst), (getattr(src, "cycles", None), getattr(dst, "cycles", None)),
                             (getattr(src, "eevee", None), getattr(dst, "eevee", None))):
        if owner_a is None or owner_b is None:
            continue
        for p in owner_a.bl_rna.properties:
            if p.identifier.startswith("use_pass_") and not p.is_readonly:
                setattr(owner_b, p.identifier, getattr(owner_a, p.identifier))


def delete_partition(scene, coll):
    if coll.get("si_background"):
        return False
    bg = background(scene, coll["si_pass"], coll["si_partition"])
    move_to_partition(scene, bg, list(coll.objects))
    for vl in scene.view_layers:                         # never leave a removed collection active
        if vl.active_layer_collection is not None and vl.active_layer_collection.collection == coll:
            vl.active_layer_collection = _layer_collection(vl, bg) or _tree(vl)
    bpy.data.collections.remove(coll)
    return True


def delete_pass(scene, name, window=None):
    names = pass_names(scene)
    if name not in names or len(names) < 2:
        return False
    other = next((n for n in names if n != name), None)
    if other is None:
        return False
    vl = scene.view_layers[name]
    wins = bpy.context.window_manager.windows if bpy.context.window_manager else []
    for w in wins:
        if w.scene == scene and w.view_layer == vl:
            set_current(scene, other, w)
    if window is not None and window.scene == scene and window.view_layer == vl:
        set_current(scene, other, window)
    if scene.get("si_last_pass") == name and scene.get("si_last_pass") != other:
        set_current(scene, other, None, carry_from=vl)   # no window moves; the selection and new objects follow
    pc = pass_collection(scene, name)
    for c in list(pc.children):
        bpy.data.collections.remove(c)
    bpy.data.collections.remove(pc)
    scene.view_layers.remove(vl)
    return True


def duplicate_pass(scene, name):
    _remove_stale(scene)
    vl = _new_pass(scene, name)
    for c in partitions(scene, name):
        if not c.get("si_background"):
            copy_partition(scene, c, vl.name)
    sync(scene)
    for k in BACKGROUND:
        src, dst = background(scene, name, k), background(scene, vl.name, k)
        if src is not None and dst is not None:
            _copy_flags(scene, src, dst)
    _copy_pass_settings(scene.view_layers[name], vl)
    return vl


# --- operators -------------------------------------------------------------------------------------------

def _ready(context):
    """The scene's current pass name; SI space is made first if the scene has none."""
    scene = context.scene
    if root(scene) is not None:
        _remove_stale(scene)
    if not pass_names(scene):
        enter_si(scene, context.window)
    else:
        sync(scene)
    names = pass_names(scene)
    if context.view_layer is not None and context.view_layer.name in names:
        return context.view_layer.name
    last = scene.get("si_last_pass")
    return last if last in names else names[0]


def _selected(context):
    """The selection of the context's view layer, with the objects picked in the Explorer that Blender can't
    select (hidden ones): the Softimage selection."""
    vl = context.view_layer
    if vl is None:
        return []
    try:
        from ..ui import explorer
        return explorer.explorer_selection(context)
    except (ImportError, AttributeError):
        return list(vl.objects.selected)


def _done(context):
    try:
        from ..ui import explorer
        explorer.invalidate()
    except (ImportError, AttributeError):
        pass
    for w in (context.window_manager.windows if context.window_manager else []):
        for a in w.screen.areas:
            a.tag_redraw()
    return {'FINISHED'}


class SI_OT_create_pass(bpy.types.Operator):
    """Make a pass (a view layer) with its two background partitions, and make it current (Softimage CreatePass)"""
    bl_idname = "si.create_pass"
    bl_label = "New Pass"
    bl_options = {'REGISTER', 'UNDO'}

    name: StringProperty(name="Name", default="Pass", options={'SKIP_SAVE'})

    def execute(self, context):
        scene = context.scene
        if not pass_names(scene):
            enter_si(scene, context.window)
        _remove_stale(scene)                             # a deleted pass's name is free again, its collections gone
        vl = _new_pass(scene, self.name or "Pass")
        sync(scene)
        set_current(scene, vl.name, context.window)
        return _done(context)


class SI_OT_set_current_pass(bpy.types.Operator):
    """Show this pass in the window (Softimage SetCurrentPass)"""
    bl_idname = "si.set_current_pass"
    bl_label = "Set Current Pass"
    bl_options = {'REGISTER', 'UNDO'}

    name: StringProperty(name="Pass")

    def execute(self, context):
        scene = context.scene
        _ready(context)
        if self.name not in pass_names(scene):
            self.report({'WARNING'}, "No pass named %r" % self.name)
            return {'CANCELLED'}
        set_current(scene, self.name, context.window)
        return _done(context)


class SI_OT_delete_pass(bpy.types.Operator):
    """Delete the current pass: its view layer and partitions, never objects (Softimage Delete Current Pass)"""
    bl_idname = "si.delete_pass"
    bl_label = "Delete Current Pass"
    bl_options = {'REGISTER', 'UNDO'}

    name: StringProperty(name="Pass", description="Empty: the current pass", options={'SKIP_SAVE'})

    def execute(self, context):
        cur = _ready(context)
        if not delete_pass(context.scene, self.name or cur, context.window):
            self.report({'WARNING'}, "A scene always keeps one pass")
            return {'CANCELLED'}
        return _done(context)


class SI_OT_duplicate_pass(bpy.types.Operator):
    """Copy the current pass with its partitions and their members, and make the copy current"""
    bl_idname = "si.duplicate_pass"
    bl_label = "Duplicate Current Pass"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        cur = _ready(context)
        vl = duplicate_pass(context.scene, cur)
        set_current(context.scene, vl.name, context.window)
        return _done(context)


class SI_OT_create_partition(bpy.types.Operator):
    """Move the selected objects into a new partition of the current pass (a light partition when only lights
    are selected) (Softimage CreatePartition)"""
    bl_idname = "si.create_partition"
    bl_label = "New Partition"
    bl_options = {'REGISTER', 'UNDO'}

    name: StringProperty(name="Name", default="Partition", options={'SKIP_SAVE'})

    def execute(self, context):
        cur = _ready(context)
        create_partition(context.scene, cur, self.name or "Partition", _selected(context))
        return _done(context)


_items = []          # Blender needs the enum strings kept alive


def _partition_items(self, context):
    global _items
    _items = []                                          # a new list each call: the old strings stay alive
    if context is None:
        _items.append(("NONE", "(no partition)", ""))
        return _items
    scene = context.scene
    names = pass_names(scene)
    cur = context.view_layer.name if context.view_layer and context.view_layer.name in names else \
        scene.get("si_last_pass")
    for c in partitions(scene, cur) if cur in names else []:
        _items.append((c.name, c.get("si_name", c.name), "%s partition" % c["si_partition"].lower()))
    if not _items:
        _items.append(("NONE", "(no partition)", ""))
    return _items


class SI_OT_add_to_partition(bpy.types.Operator):
    """Move the selected objects into a partition of the current pass, out of their old one; only objects of the
    partition's kind move (Softimage AddToPartition / MoveToPartition)"""
    bl_idname = "si.add_to_partition"
    bl_label = "Add to Partition"
    bl_options = {'REGISTER', 'UNDO'}
    bl_property = "target"

    partition: StringProperty(name="Partition", description="Collection name", options={'SKIP_SAVE'})
    target: EnumProperty(name="Partition", items=_partition_items, options={'SKIP_SAVE'})

    def invoke(self, context, event):
        if self.partition:
            return self.execute(context)
        if not pass_names(context.scene):
            _ready(context)                              # a scene without passes: make Default_Pass to list
        context.window_manager.invoke_search_popup(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        cur = _ready(context)
        scene = context.scene
        coll = bpy.data.collections.get(self.partition or self.target)
        ok = coll is not None and "si_partition" in coll and in_passes(scene, coll)
        if ok and not self.partition:
            ok = coll.get("si_pass") == cur              # the menu's search lists the current pass's partitions
        if not ok:
            self.report({'WARNING'}, "Pick a partition of the current pass")
            return {'CANCELLED'}
        moved = move_to_partition(context.scene, coll, _selected(context))
        skipped = len([o for o in _selected(context) if kind(o)]) - len(moved)
        if skipped:
            self.report({'INFO'}, "%d object(s) of the other kind stay where they are" % skipped)
        return _done(context)


class SI_OT_remove_from_partition(bpy.types.Operator):
    """Send the selected objects back to the background partition of the current pass (Softimage
    RemoveFromPartition)"""
    bl_idname = "si.remove_from_partition"
    bl_label = "Remove from Partition"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        cur = _ready(context)
        remove_from_partition(context.scene, cur, _selected(context))
        return _done(context)


class SI_OT_copy_partition(bpy.types.Operator):
    """Copy a partition and its members into another pass (Softimage CopyPartition)"""
    bl_idname = "si.copy_partition"
    bl_label = "Copy Partition"
    bl_options = {'REGISTER', 'UNDO'}

    partition: StringProperty(name="Partition", description="Collection name")
    target_pass: StringProperty(name="Pass")

    def execute(self, context):
        _ready(context)
        scene = context.scene
        coll = bpy.data.collections.get(self.partition)
        if coll is None or "si_partition" not in coll or not in_passes(scene, coll) \
                or self.target_pass not in pass_names(scene) or self.target_pass == coll.get("si_pass") \
                or coll.get("si_background"):
            self.report({'WARNING'}, "Needs a partition and another pass")
            return {'CANCELLED'}
        copy_partition(scene, coll, self.target_pass)
        return _done(context)


class SI_OT_delete_partition(bpy.types.Operator):
    """Delete a partition; its members go back to the background partition (background partitions stay)"""
    bl_idname = "si.delete_partition"
    bl_label = "Delete Partition"
    bl_options = {'REGISTER', 'UNDO'}

    partition: StringProperty(name="Partition", description="Collection name")

    def execute(self, context):
        _ready(context)
        coll = bpy.data.collections.get(self.partition)
        if coll is None or "si_partition" not in coll or not in_passes(context.scene, coll) \
                or not delete_partition(context.scene, coll):
            self.report({'WARNING'}, "Not a partition that can be deleted")
            return {'CANCELLED'}
        return _done(context)


# --- partition overrides (spec render.overrides) -----------------------------------------------------------

# Softimage partition parameters and override entries that Blender keeps per view layer, on the partition's layer
# collection: (attribute, label of the set state). Everything else stays greyed (spec decisions 1-3).
FLAGS = (("hide_viewport", "View Visibility: Off"), ("exclude", "Render Visibility: Off"),
         ("holdout", "Matte (Holdout)"), ("indirect_only", "Primary Rays: Off (Indirect Only)"))
GREYED_PARTITION = ("Selectability", "View Playback Visibility", "Animation Ghosting")
GREYED_OVERRIDE = ("Secondary Rays", "Diffuse", "Specular", "Global Illumination", "Caustics")


def partition_layer(scene, coll):
    """The partition's layer collection in its own pass (where its flags live), or None."""
    name = coll.get("si_pass")
    vl = scene.view_layers.get(name) if name else None
    return _layer_collection(vl, coll) if vl is not None else None


def partition_overrides(scene):
    """{partition collection: [(attribute, label)]} for the flags set on it in its pass. A view of Blender's own
    per-view-layer flags: Silica stores no override data."""
    out = {}
    if root(scene) is None:
        return out
    for n in pass_names(scene):
        plc = _layer_collection(scene.view_layers[n], pass_collection(scene, n))
        for lc in plc.children if plc is not None else ():
            if "si_partition" in lc.collection:
                ov = [(a, label) for a, label in FLAGS if getattr(lc, a)]
                if ov:
                    out[lc.collection] = ov
    return out


class SI_OT_partition_flag(bpy.types.Operator):
    """Set a partition's per-pass flag: view / render visibility, matte, primary rays (Softimage partition
    parameters and override entries)"""
    bl_idname = "si.partition_flag"
    bl_label = "Partition Override"
    bl_options = {'REGISTER', 'UNDO'}

    partition: StringProperty(name="Partition", description="Collection name", options={'SKIP_SAVE'})
    flag: EnumProperty(items=[(a, label, "") for a, label in FLAGS])
    value: bpy.props.BoolProperty(default=True, options={'SKIP_SAVE'})

    def execute(self, context):
        scene = context.scene
        if root(scene) is not None:
            _remove_stale(scene)                         # a pass renamed with Blender's tools
        coll = bpy.data.collections.get(self.partition)
        lc = partition_layer(scene, coll) if coll is not None and in_passes(scene, coll) else None
        if lc is None or "si_partition" not in coll:
            self.report({'WARNING'}, "Not a partition of this scene")
            return {'CANCELLED'}
        setattr(lc, self.flag, self.value)
        return _done(context)


def _greyed(layout, labels):
    col = layout.column(align=True)
    col.enabled = False
    for label in labels:
        col.label(text=label + " (no per-pass setting in Blender)")


class SI_OT_partition_properties(bpy.types.Operator):
    """The partition's property page: its visibility in this pass and its override entries, as Blender's own
    per-view-layer settings of the partition"""
    bl_idname = "si.partition_properties"
    bl_label = "Partition Properties"
    bl_options = {'REGISTER'}           # edits on the page are Blender property edits, each its own undo step

    partition: StringProperty(name="Partition", description="Collection name", options={'SKIP_SAVE'})

    def _coll(self, context):
        coll = bpy.data.collections.get(self.partition)
        ok = coll is not None and "si_partition" in coll and in_passes(context.scene, coll)
        return coll if ok else None

    def invoke(self, context, event):
        if root(context.scene) is not None:
            _remove_stale(context.scene)
        coll = self._coll(context)
        if coll is None or partition_layer(context.scene, coll) is None:
            self.report({'WARNING'}, "Not a partition of this scene")
            return {'CANCELLED'}
        return context.window_manager.invoke_popup(self, width=360)

    def draw(self, context):
        coll = self._coll(context)
        lc = partition_layer(context.scene, coll) if coll is not None else None
        layout = self.layout
        if lc is None:
            layout.label(text="The partition is gone")
            return
        layout.label(text="%s  (%s)" % (coll.get("si_name", coll.name), coll["si_pass"]), icon='OUTLINER_COLLECTION')
        col = layout.column(align=True)
        col.prop(lc, "hide_viewport", text="View Visibility", invert_checkbox=True)
        col.prop(lc, "exclude", text="Render Visibility", invert_checkbox=True)
        hint = col.row()
        hint.enabled = False
        hint.label(text="Off also hides the members in this pass's viewport")
        _greyed(layout, GREYED_PARTITION)
        layout.separator()
        layout.label(text="Override", icon='LIBRARY_DATA_OVERRIDE')
        col = layout.column(align=True)
        col.prop(lc, "holdout", text="Matte (Holdout)")
        col.prop(lc, "indirect_only", text="No Primary Rays (Indirect Only)")
        if context.scene.render.engine != 'CYCLES':
            hint = col.row()
            hint.enabled = False
            hint.label(text="Indirect Only works in Cycles")
        _greyed(layout, GREYED_OVERRIDE)

    def execute(self, context):
        return {'FINISHED'}


AOV_PROPS = (("use_pass_z", "Z"), ("use_pass_mist", "Mist"), ("use_pass_ambient_occlusion", "Ambient Occlusion"),
             ("use_pass_diffuse_direct", "Diffuse Direct"), ("use_pass_diffuse_indirect", "Diffuse Indirect"),
             ("use_pass_diffuse_color", "Diffuse Color"), ("use_pass_glossy_direct", "Glossy Direct"),
             ("use_pass_glossy_indirect", "Glossy Indirect"), ("use_pass_glossy_color", "Glossy Color"),
             ("use_pass_transmission_direct", "Transmission Direct"),
             ("use_pass_transmission_indirect", "Transmission Indirect"),
             ("use_pass_transmission_color", "Transmission Color"), ("use_pass_shadow", "Shadow"),
             ("use_pass_cryptomatte_object", "Cryptomatte Object"))


class SI_OT_pass_properties(bpy.types.Operator):
    """The pass's property page: its whole-pass overrides (material, world, samples, motion blur) and render
    passes, as Blender's own settings of the pass's view layer"""
    bl_idname = "si.pass_properties"
    bl_label = "Pass Properties"
    bl_options = {'REGISTER'}

    name: StringProperty(name="Pass", options={'SKIP_SAVE'})

    def invoke(self, context, event):
        if root(context.scene) is not None:
            _remove_stale(context.scene)
        if self.name not in pass_names(context.scene):
            self.report({'WARNING'}, "No pass named %r" % self.name)
            return {'CANCELLED'}
        return context.window_manager.invoke_popup(self, width=360)

    def draw(self, context):
        vl = context.scene.view_layers.get(self.name)
        layout = self.layout
        if vl is None:
            layout.label(text="The pass is gone")
            return
        layout.label(text=vl.name, icon='RENDERLAYERS')
        col = layout.column(align=True)
        col.prop(vl, "material_override", text="Material")
        col.prop(vl, "world_override", text="World")
        col.prop(vl, "samples", text="Samples")
        col.prop(vl, "use_motion_blur", text="Motion Blur")
        layout.separator()
        layout.label(text="Render Passes")
        grid = layout.grid_flow(columns=2, align=True)
        for attr, label in AOV_PROPS:
            grid.prop(vl, attr, text=label)

    def execute(self, context):
        return {'FINISHED'}


_render_restore = {}


def _render_restore_now():
    """Render Single Layer back to what the user had (main thread)."""
    if bpy.app.is_job_running('RENDER'):
        return 0.5                                       # still rendering: look again
    for sc_name, single in list(_render_restore.items()):
        sc = bpy.data.scenes.get(sc_name)
        if sc is not None and sc.render.use_single_layer != single:
            sc.render.use_single_layer = single
    _render_restore.clear()
    return None


@bpy.app.handlers.persistent
def _render_done(*_args):
    """render_complete / render_cancel: only schedules the restore (handlers may run off the main thread, and
    this list is being walked by Blender right now)."""
    if _render_restore and not bpy.app.timers.is_registered(_render_restore_now):
        bpy.app.timers.register(_render_restore_now, first_interval=0.1)


class SI_OT_render_pass(bpy.types.Operator):
    """Render this pass (the pass's right-click Render): it becomes current and renders alone, with Blender's
    Render Single Layer for the time of the render"""
    bl_idname = "si.render_pass"
    bl_label = "Render Pass"
    bl_options = {'REGISTER'}           # no undo step: it would hold the temporary Render Single Layer

    name: StringProperty(name="Pass", options={'SKIP_SAVE'})

    def execute(self, context):
        scene = context.scene
        _ready(context)
        if self.name not in pass_names(scene):
            self.report({'WARNING'}, "No pass named %r" % self.name)
            return {'CANCELLED'}
        if bpy.app.is_job_running('RENDER'):
            self.report({'INFO'}, "A render is already running")
            return {'CANCELLED'}
        set_current(scene, self.name, context.window)
        if scene.name not in _render_restore:
            _render_restore[scene.name] = scene.render.use_single_layer
        scene.render.use_single_layer = True
        try:
            res = bpy.ops.render.render('INVOKE_DEFAULT')
        except RuntimeError as e:                        # no camera and the like
            self.report({'WARNING'}, str(e))
            res = {'CANCELLED'}
        if 'CANCELLED' in res:
            _render_restore_now()
            return {'CANCELLED'}
        return {'FINISHED'}


CLASSES = (SI_OT_create_pass, SI_OT_set_current_pass, SI_OT_delete_pass, SI_OT_duplicate_pass,
           SI_OT_create_partition, SI_OT_add_to_partition, SI_OT_remove_from_partition, SI_OT_copy_partition,
           SI_OT_delete_partition, SI_OT_render_pass, SI_OT_partition_flag, SI_OT_partition_properties,
           SI_OT_pass_properties)


# --- mode switch -----------------------------------------------------------------------------------------

def _windows():
    try:
        wm = bpy.context.window_manager
    except AttributeError:
        return []
    return list(wm.windows) if wm else []


def _switch(enter):
    """Mode on: every scene shown in a window into SI space. Mode off: every scene in SI space back, shown or not.
    Each scene is switched once; other windows on the same scene follow its view layer."""
    by_scene = {}
    for w in _windows():
        by_scene.setdefault(w.scene, []).append(w)
    if not enter:
        for sc in bpy.data.scenes:
            if sc.get("si_space") == "SI":
                by_scene.setdefault(sc, [])
    for sc, wins in by_scene.items():
        try:
            vl = (enter_si if enter else leave_si)(sc, wins[0] if wins else None)
            for w in wins[1:]:
                if vl is not None:
                    w.view_layer = vl
        except Exception as e:                           # never block the mode switch
            print("si_kit: passes:", e)
    for w in _windows():
        for a in w.screen.areas:
            a.tag_redraw()


_state = {"on": False}


@bpy.app.handlers.persistent
def _after_undo(*_args):
    """Undo / redo don't touch windows: a window left on a view layer the undo removed (New Pass undone) shows
    Blender's fallback layer, outside SI space. Put it back on the scene's current pass."""
    if _render_restore:
        _render_restore_now()
    for w in _windows():
        sc = w.scene
        try:
            if _state["on"] and sc.get("si_space") != "SI":
                enter_si(sc, w)                          # undone past the mode switch
                continue
            if sc.get("si_space") == "SI":
                names = pass_names(sc)
                if names:
                    last = sc.get("si_last_pass")
                    target = sc.view_layers[last if last in names else names[0]]
                    if w.view_layer != target:       # undo of Set Current Pass / Delete Pass, redo of New Pass
                        w.view_layer = target
        except Exception as e:
            print("si_kit: passes after undo:", e)


def _load_tick():
    if _state["on"]:                                     # mode turned off since the file loaded: nothing to do
        _switch(True)
    return None


@bpy.app.handlers.persistent
def _on_load(*_args):
    _render_restore.clear()                              # the old file's scenes
    if not bpy.app.timers.is_registered(_load_tick):
        bpy.app.timers.register(_load_tick, first_interval=0.05)


def register():
    for c in CLASSES:
        bpy.utils.register_class(c)
    _state["on"] = True
    _switch(True)
    bpy.app.handlers.load_post.append(_on_load)
    for lst in (bpy.app.handlers.undo_post, bpy.app.handlers.redo_post):
        lst.append(_after_undo)
    for lst in (bpy.app.handlers.render_complete, bpy.app.handlers.render_cancel):
        lst.append(_render_done)


def unregister():
    _state["on"] = False
    if _on_load in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_load)
    for lst in (bpy.app.handlers.undo_post, bpy.app.handlers.redo_post):
        while _after_undo in lst:
            lst.remove(_after_undo)
    for lst in (bpy.app.handlers.render_complete, bpy.app.handlers.render_cancel):
        while _render_done in lst:
            lst.remove(_render_done)
    if _render_restore:
        if bpy.app.timers.is_registered(_render_restore_now):
            bpy.app.timers.unregister(_render_restore_now)
        _render_restore_now()
    if bpy.app.timers.is_registered(_load_tick):
        bpy.app.timers.unregister(_load_tick)
    _switch(False)
    for c in reversed(CLASSES):
        bpy.utils.unregister_class(c)
