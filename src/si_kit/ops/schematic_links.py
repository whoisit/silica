# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Alex Doss
"""Schematic links and node letters, read from native Blender data (read-only, nothing is written).

`collect(scene)` walks the scene once and returns a `Schematic`: the links between objects, Softimage-style, and the
red letters per object. Softimage link kinds map onto Blender like this:

- HIERARCHY: child -> parent (`Object.parent`; parent type and bone in `detail` / `subtarget`).
- CONSTRAINT: owner -> each constraint target (object and pose-bone constraints, Armature constraint `targets`).
- EXPRESSION: object read by a driver variable -> driven object (drivers on the object, its data or its shape keys).
- OPERATOR: modifier owner -> each object a modifier points to (found generically), Geometry Nodes object inputs,
  curve bevel / taper / text-on-curve objects. Armature modifiers are envelopes, not operators.
- ENVELOPE: deformed object -> armature (Armature modifier, or armature parent).
- ASSOCIATED_MODEL: light (any light-linking emitter) -> each object in its receiver / blocker collection.
- Shared material: a grouping per material (`Schematic.materials`, built on first use), not pairs of links.

Letters (`Schematic.flags`): A animated (action or NLA with keys, or animated shape keys), C constrained,
E driven by drivers, I collection instance (Softimage model instance), V enveloped by an armature.

Records hold Objects (never names); `session_uid` is exposed for callers that need a plain key. Do not keep a
`Schematic` across undo or file loads: collect again (one pass over the scene, about 25 ms at 10,000 objects).
"""

import bpy

HIERARCHY = 'HIERARCHY'
CONSTRAINT = 'CONSTRAINT'
EXPRESSION = 'EXPRESSION'
OPERATOR = 'OPERATOR'
ENVELOPE = 'ENVELOPE'
ASSOCIATED_MODEL = 'ASSOCIATED_MODEL'
KINDS = (HIERARCHY, CONSTRAINT, EXPRESSION, OPERATOR, ENVELOPE, ASSOCIATED_MODEL)

# What clicking a link picks: the owner object itself, or the item (constraint / modifier / driver / light linking).
PICK_OBJECT = 'OBJECT'
PICK_ITEM = 'ITEM'

# bpy.types lookups cost about a microsecond each: done once here, not per object.
_Object = bpy.types.Object
_Armature = bpy.types.Armature
# Object data types that never carry modifiers: their objects skip the modifier read (empties have no data).
_NO_MODIFIERS = {getattr(bpy.types, n) for n in ('Armature', 'Camera', 'Light', 'Image', 'Speaker', 'LightProbe')
                 if hasattr(bpy.types, n)}
_ARMATURE_MODS = {'ARMATURE', 'GREASE_PENCIL_ARMATURE'}
_SUBTARGETS = {'target': 'subtarget', 'pole_target': 'pole_subtarget', 'space_object': 'space_subtarget'}
_obj_props_cache = {}
_data_info_cache = {}


def _object_props(rna_type):
    """Names of the properties of an RNA type that point to an Object (cached per type)."""
    props = _obj_props_cache.get(rna_type)
    if props is None:
        props = tuple(p.identifier for p in rna_type.bl_rna.properties
                      if p.type == 'POINTER' and p.fixed_type.identifier == 'Object')
        _obj_props_cache[rna_type] = props
    return props


def _data_info(rna_type):
    """(object pointer properties, has animation data) for an object-data type, cached."""
    info = _data_info_cache.get(rna_type)
    if info is None:
        info = (_object_props(rna_type), 'animation_data' in rna_type.bl_rna.properties)
        _data_info_cache[rna_type] = info
    return info


class Link:
    """One schematic link. `source` -> `target` follows the Softimage arrow; `owner` is the object holding the item.

    `holder` (the ID owning the item: the owner, its data or its shape keys) with `path` / `index` locates the
    constraint, modifier or driver: see `resolve()`. `pick` says what a click selects, `deletable` whether
    Softimage's Delete removes the relationship (constraints and expressions).
    """
    __slots__ = ('kind', 'source', 'target', 'owner', 'holder', 'path', 'index', 'label', '_detail', '_subtarget',
                 'pick', 'deletable', 'source_outside', 'target_outside')

    def __init__(self, kind, source, target, owner, holder, path, label, detail, subtarget, index, pick, deletable):
        self.kind = kind
        self.source = source
        self.target = target
        self.owner = owner
        self.holder = holder
        self.path = path
        self.index = index
        self.label = label
        self._detail = detail
        self._subtarget = subtarget
        self.pick = pick
        self.deletable = deletable
        self.source_outside = False
        self.target_outside = False

    @property
    def detail(self):
        """Readable description: constraint / modifier name and property, driver path, light-link role."""
        if self._detail is None:          # hierarchy: read on demand (an enum read per child is costly at 10k)
            self._detail = self.owner.parent_type
        return self._detail

    @property
    def subtarget(self):
        """Bone or vertex group name the link aims at, or ''."""
        if self._subtarget is None:
            self._subtarget = self.owner.parent_bone if self.detail == 'BONE' else ''
        return self._subtarget

    @property
    def source_uid(self):
        return self.source.session_uid

    @property
    def target_uid(self):
        return self.target.session_uid

    def resolve(self):
        """The live item this link stands for (constraint, modifier, driver F-curve, or the owner), or None."""
        try:
            if self.kind == HIERARCHY or not self.path or self.path in ('parent', 'light_linking'):
                return self.owner
            if self.kind == EXPRESSION:
                ad = self.holder.animation_data
                return ad.drivers.find(self.path, index=self.index) if ad else None
            return self.holder.path_resolve(self.path)
        except (ReferenceError, ValueError, AttributeError):
            return None

    def __repr__(self):
        return "<Link %s %s -> %s %s>" % (self.kind, self.source.name, self.target.name, self.detail)


class Schematic:
    """Result of `collect()`: links, letters per object, instances and shared-material groups for one scene."""

    def __init__(self, scene):
        self.scene = scene
        self.objects = []        # scene objects, scene order
        self.links = []          # Link records
        self.flags = {}          # Object -> letters, e.g. "ACV" (only objects with at least one letter)
        self.instances = {}      # instancer Object -> Collection it instances
        self.outside = set()     # objects at a link end that are not in the scene
        self.excluded = set()    # scene objects the given view layer leaves out (excluded collections)
        self._in_scene = set()
        self._data_users = {}
        self._materials = None
        self._by_object = None

    @property
    def materials(self):
        """Material -> [scene objects using it], only materials shared by two or more objects (built on first use)."""
        if self._materials is None:
            self._materials = _shared_materials(self._data_users, self._in_scene)
        return self._materials

    def links_of(self, ob):
        """Links that start or end at `ob` (map built on first call)."""
        if self._by_object is None:
            m = {}
            for ln in self.links:
                m.setdefault(ln.source, []).append(ln)
                if ln.target is not ln.source:
                    m.setdefault(ln.target, []).append(ln)
            self._by_object = m
        return self._by_object.get(ob, [])

    def by_uid(self):
        """session_uid -> Object for the scene objects."""
        return {ob.session_uid: ob for ob in self.objects}


def _has_keys(ad):
    """True when the animation data plays keys: assigned action slot with F-curves, or NLA strips with actions."""
    if ad is None:
        return False
    act, slot = ad.action, ad.action_slot
    if act is not None and slot is not None:
        for layer in act.layers:
            for strip in layer.strips:
                cb = strip.channelbag(slot)
                if cb is not None and len(cb.fcurves):
                    return True
    for track in ad.nla_tracks:
        if track.mute:
            continue
        for strip in track.strips:
            if strip.action is not None and not strip.action.is_empty:
                return True
    return False


def _light_members(coll, state, out, seen):
    """(object, link state) for every object in a light-linking collection, nested collections included.

    `collection_objects` / `collection_children` run parallel to `objects` / `children` and carry the state."""
    if coll in seen:
        return
    seen.add(coll)
    for ob, co in zip(coll.objects, coll.collection_objects):
        out.append((ob, co.light_linking.link_state if state is None else state))
    for child, cc in zip(coll.children, coll.collection_children):
        _light_members(child, cc.light_linking.link_state if state is None else state, out, seen)


def _shared_materials(data_users, in_scene):
    """Material -> scene objects for materials used by two or more objects (data slots and object-linked slots)."""
    data_mats, slot_objects = {}, set()
    for mat, users in bpy.data.user_map(subset=bpy.data.materials).items():
        for u in users:
            if isinstance(u, _Object):
                if u in in_scene:
                    slot_objects.add(u)   # object-linked slots: read below, they can override the data's material
            elif u in data_users:
                data_mats.setdefault(u, []).append(mat)
    groups = {}
    for d, mats in data_mats.items():
        for ob in data_users[d]:
            if ob not in slot_objects:
                for mat in mats:
                    groups.setdefault(mat, []).append(ob)
    for ob in slot_objects:
        for mat in {s.material for s in ob.material_slots if s.material is not None}:
            groups.setdefault(mat, []).append(ob)
    return {mat: obs for mat, obs in groups.items() if len(obs) > 1}


def _layer_objects(view_layer):
    """Objects the view layer keeps, read from its layer collections (`ViewLayer.objects` can lag behind an
    exclude change until the layer is synced)."""
    root = view_layer.layer_collection
    if root is None:
        return set(view_layer.objects)
    kept = set()
    stack = [root]
    while stack:
        lc = stack.pop()
        if lc.exclude:
            continue
        kept.update(lc.collection.objects)
        stack.extend(lc.children)
    return kept


def collect(scene, view_layer=None):
    """Links and letters for `scene` (objects of other scenes appear only as outside link ends).

    With a `view_layer`, `Schematic.excluded` lists the scene objects that layer leaves out (excluded collections).
    """
    S = Schematic(scene)
    objects = list(scene.objects)
    in_scene = set(objects)
    S.objects, S._in_scene = objects, in_scene
    links = S.links
    flags = {}

    def flag(ob, letter):
        f = flags.get(ob, '')
        if letter not in f:
            flags[ob] = f + letter

    data_users = {}   # object data ID -> [scene objects]
    S._data_users = data_users
    with_cons, with_mods, with_anim, armatures, hierarchy = [], [], [], set(), []

    # One pass over the objects; everything else uses the maps built here.
    for ob in objects:
        d = ob.data
        if d is not None:
            lst = data_users.get(d)
            if lst is None:
                data_users[d] = [ob]
            else:
                lst.append(ob)
            dt = type(d)
            if dt is _Armature:
                armatures.add(ob)
            if dt not in _NO_MODIFIERS and ob.modifiers:
                with_mods.append(ob)
        p = ob.parent
        if p is not None:
            ln = Link(HIERARCHY, ob, p, ob, ob, '', 'PARENT', None, None, -1, PICK_OBJECT, False)
            links.append(ln)
            hierarchy.append(ln)
        if ob.constraints:
            with_cons.append(ob)
        if ob.animation_data is not None:
            with_anim.append(ob)

    # Armature parents are envelopes too (parent type is read only where the parent is an armature).
    for ln in hierarchy:
        p = ln.target
        if (p in armatures or (p not in in_scene and isinstance(p.data, _Armature))) and ln.detail == 'ARMATURE':
            links.append(Link(ENVELOPE, ln.owner, ln.target, ln.owner, ln.owner, 'parent', 'ARMATURE',
                              'armature parent', '', -1, PICK_OBJECT, False))
            flag(ln.owner, 'V')

    # Constraints, object level and pose bones.
    def add_constraints(ob, cons, bone):
        for c in cons:
            flag(ob, 'C')
            targets = []
            for prop in _object_props(type(c)):
                t = getattr(c, prop)
                if t is not None:
                    subprop = _SUBTARGETS.get(prop)
                    targets.append((t, prop, getattr(c, subprop) if subprop else ''))
            if hasattr(c, 'targets'):
                for i, ct in enumerate(c.targets):
                    if ct.target is not None:
                        targets.append((ct.target, 'targets[%d]' % i, ct.subtarget))
            cpath = None
            for t, prop, sub in targets:
                if t is ob:
                    continue   # bone to bone inside one armature, or the owner itself: no link between nodes
                if cpath is None:
                    cpath = c.path_from_id()
                detail = c.name + (' (bone %s)' % bone if bone else '') + ' ' + prop
                links.append(Link(CONSTRAINT, ob, t, ob, ob, cpath, c.type, detail, sub, -1, PICK_ITEM, True))

    for ob in with_cons:
        add_constraints(ob, ob.constraints, '')
    for ob in armatures:
        pose = ob.pose
        if pose is not None:
            for pb in pose.bones:
                if pb.constraints:
                    add_constraints(ob, pb.constraints, pb.name)

    # Modifiers: armature -> envelope, any other object pointer -> operator.
    for ob in with_mods:
        for m in ob.modifiers:
            mpath = m.path_from_id()
            if m.type in _ARMATURE_MODS:
                if m.object is not None:
                    links.append(Link(ENVELOPE, ob, m.object, ob, ob, mpath, m.type, m.name, '', -1, PICK_ITEM,
                                      False))
                    flag(ob, 'V')
                continue
            for prop in _object_props(type(m)):
                t = getattr(m, prop)
                if t is not None and t is not ob:
                    links.append(Link(OPERATOR, ob, t, ob, ob, mpath, m.type, m.name + ' ' + prop, '', -1,
                                      PICK_ITEM, False))
            if m.type == 'NODES' and m.node_group is not None:
                names = None
                inputs = m.properties.inputs   # Blender 5.2: one struct per input socket, its value in `.value`
                for p in inputs.bl_rna.properties:
                    if p.type != 'POINTER' or p.identifier == 'rna_type':
                        continue
                    t = getattr(getattr(inputs, p.identifier), 'value', None)
                    if isinstance(t, _Object) and t is not ob:
                        if names is None:
                            names = {it.identifier: it.name for it in m.node_group.interface.items_tree
                                     if it.item_type == 'SOCKET'}
                        detail = '%s input %s' % (m.name, names.get(p.identifier, p.identifier))
                        links.append(Link(OPERATOR, ob, t, ob, ob, mpath, m.type, detail, '', -1, PICK_ITEM, False))

    # Shape keys: Key -> objects (through its mesh / curve / lattice).
    key_users = {}
    for key in bpy.data.shape_keys:
        users = data_users.get(key.user)
        if users:
            key_users[key] = users

    def id_objects(idb):
        """Scene objects behind a driver target ID: the object itself, or the objects using that data / key."""
        if isinstance(idb, _Object):
            return (idb,)
        return data_users.get(idb) or key_users.get(idb) or ()

    def add_drivers(holder, ad, driven):
        drivers = ad.drivers
        if not drivers:
            return
        for fc in drivers:
            seen = set()
            for var in fc.driver.variables:
                for t in var.targets:
                    idb = t.id
                    if idb is None:
                        continue
                    for src in id_objects(idb):
                        if src in seen:
                            continue
                        seen.add(src)
                        for ob in driven:
                            if src is not ob:
                                detail = fc.data_path + ('[%d]' % fc.array_index if fc.array_index else '')
                                links.append(Link(EXPRESSION, src, ob, ob, holder, fc.data_path, 'Expr', detail, '',
                                                  fc.array_index, PICK_ITEM, True))
        for ob in driven:
            flag(ob, 'E')

    for ob in with_anim:
        ad = ob.animation_data
        if _has_keys(ad):
            flag(ob, 'A')
        add_drivers(ob, ad, (ob,))

    # Object data: pointers to objects (curve bevel / taper, text on curve) and drivers on the data.
    for d, users in data_users.items():
        props, animatable = _data_info_cache.get(type(d)) or _data_info(type(d))
        for prop in props:
            t = getattr(d, prop)
            if t is not None:
                for ob in users:
                    if t is not ob:
                        links.append(Link(OPERATOR, ob, t, ob, d, prop, prop.upper(), 'data ' + prop, '', -1,
                                          PICK_ITEM, False))
        if animatable:
            ad = d.animation_data
            if ad is not None:
                add_drivers(d, ad, users)
    for key, users in key_users.items():
        ad = key.animation_data
        if ad is not None:
            add_drivers(key, ad, users)
            if _has_keys(ad):
                for ob in users:
                    flag(ob, 'A')

    # Collections: light linking (associated model) and collection instances, from one user map of object users.
    referrers = set()
    for users in bpy.data.user_map(subset=bpy.data.collections, value_types={'OBJECT'}).values():
        referrers.update(users)
    referrers &= in_scene
    for ob in referrers:
        ic = ob.instance_collection
        if ic is not None and ob.instance_type == 'COLLECTION':
            S.instances[ob] = ic
            flag(ob, 'I')
        ll = ob.light_linking
        for role, coll in (('receiver', ll.receiver_collection), ('blocker', ll.blocker_collection)):
            if coll is None:
                continue
            members = []
            _light_members(coll, None, members, set())
            for t, state in members:
                if t is not ob:
                    links.append(Link(ASSOCIATED_MODEL, ob, t, ob, ob, 'light_linking', role.upper(),
                                      '%s %s %s' % (role, coll.name, state), '', -1, PICK_ITEM, False))

    for ln in links:
        if ln.target not in in_scene:
            ln.target_outside = True
            S.outside.add(ln.target)
        if ln.source is not ln.owner and ln.source not in in_scene:   # owners are always scene objects
            ln.source_outside = True
            S.outside.add(ln.source)
    S.flags = {ob: ''.join(sorted(f)) for ob, f in flags.items()}
    if view_layer is not None:
        S.excluded = in_scene.difference(_layer_objects(view_layer))
    return S
