# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Alex Doss
"""File > Import > Softimage Scene (.scn).

Reads the scene with si_kit.io_scn and creates one Blender object per Softimage object (same name, same
hierarchy, local transform as matrix_basis).

Axis conversion: Softimage is Y-up right-handed, Blender Z-up. Let C be the +90 degree rotation about X, which
maps Softimage (x, y, z) to Blender (x, -z, y). No extra root object is made. Instead every local transform M is
conjugated, C @ M @ C^-1, and mesh points are mapped with C. Conjugation is exact for whole hierarchies
(C M1 M2 C^-1 = (C M1 C^-1)(C M2 C^-1)), so child local transforms stay correct, scales are permuted with the
axes and polygon winding is kept (C is a rotation). Cameras and lights look down their local -Z in both
programs, so after the conjugation their object axes get one extra turn by C to keep looking the same way in
world space; their children are compensated so they are unaffected.
One Softimage unit = one Blender unit.
"""

import collections
from math import radians

import bpy
from bpy.props import StringProperty
from bpy_extras.io_utils import ImportHelper
from mathutils import Euler, Matrix, Quaternion, Vector

from ..io_scn import scene as scn

C = Matrix.Rotation(radians(90.0), 4, 'X')
C_INV = C.inverted()
FIXED_KINDS = ('camera', 'light')


def local_matrix(t):
    """Softimage Transform -> 4x4 in Softimage axes (translation, quaternion w x y z, scale)."""
    q = Quaternion(t.quat)
    if q.magnitude < 1e-9:  # no usable quaternion: fall back to the XYZ euler angles (degrees)
        q = Euler([radians(a) for a in t.rot], 'XYZ').to_quaternion()
    else:
        q.normalize()
    return Matrix.LocRotScale(Vector(t.pos), q, Vector(t.scl))


def blender_matrix(t, own_fix=False, parent_fix=False):
    """Conjugated local matrix. own_fix: camera/light axis turn; parent_fix: undo the parent's own_fix."""
    m = C @ local_matrix(t) @ C_INV
    if parent_fix:
        m = C_INV @ m
    if own_fix:
        m = m @ C
    return m


def convert_point(p):
    x, y, z = p
    return (x, -z, y)


# Softimage generator parameter -> socket of the kit's live primitive node group (ops/gn_primitives.py).
GN_SOCKETS = {"length": "Length", "radius": "Radius", "ulength": "Length U", "vlength": "Length V",
              "height": "Height", "sectionradius": "Section Radius", "subdivu": "Subdivisions U",
              "subdivv": "Subdivisions V", "subdivbase": "Subdivisions Base"}
FULL_V = {"sphere": 180.0, "torus": 360.0}


def shape_notes(gen):
    """Generator settings the kit's live primitive can't show (empty when it can)."""
    return generator_notes(dict(gen, ops=[]))


def exact_shape(gen):
    """(points, polygons) for a primitive whose settings the kit's live primitive can't show, when io_scn.rebuild
    builds it exactly (spheres with any U / V range); else None."""
    from ..io_scn import rebuild
    return rebuild.primitive_mesh(gen) if shape_notes(gen) else None


def generator_notes(gen):
    """What of a live primitive the rebuild can't reproduce yet (empty when the shape is exact)."""
    kind, p = gen["type"], gen["params"]
    notes = []
    if p.get("startuangle", 0.0) != 0.0 or p.get("enduangle", 360.0) != 360.0:
        notes.append("U angles %g-%g (rebuilt full)" % (p.get("startuangle", 0.0), p.get("enduangle", 360.0)))
    if kind in FULL_V and (p.get("startvangle", 0.0) != 0.0 or p.get("endvangle", FULL_V[kind]) != FULL_V[kind]):
        notes.append("V angles %g-%g (rebuilt full)" % (p.get("startvangle", 0.0), p.get("endvangle", FULL_V[kind])))
    if p.get("closevmin") is False or p.get("closevmax") is False or p.get("closebottom") is False:
        notes.append("open caps (rebuilt closed)")
    if p.get("freq", 1) != 1:
        notes.append("frequency %d (rebuilt 1)" % p["freq"])
    if p.get("method"):
        notes.append("subdivision method %r (not rebuilt)" % p["method"])
    if gen.get("ops"):
        notes.append("operators on top not rebuilt: %s" % ops_text(gen["ops"], gen.get("moves")))
    return notes


def ops_text(ops, moves=None):
    """'movecomponentop x3 (on points, edges), bendop' from the reader's operator list."""
    out = []
    for name, n in sorted(collections.Counter(ops).items()):
        s = name if n == 1 else "%s x%d" % (name, n)
        if name == "movecomponentop" and moves:
            comps = sorted({{"pnt": "points", "edge": "edges", "poly": "polygons"}[m.component] for m in moves})
            s += " (on %s)" % ", ".join(comps)
        out.append(s)
    return ", ".join(out)


def replayed_moves(gen):
    """(points, polygons) of a live primitive whose only operators are point moves, replayed on Softimage's
    point order (io_scn.rebuild); None when that is not possible."""
    from ..io_scn import rebuild
    if not gen.get("ops") or set(gen["ops"]) != {"movecomponentop"} or not gen.get("moves"):
        return None
    return rebuild.with_moves(gen, gen["moves"])


def camera_data(name, c):
    """Blender camera from Softimage camera settings (io_scn.camlight): field of view on the axis Softimage
    measures it on, clipping, orthographic height. The aspect is the render's in Blender; kept as si_aspect."""
    cam = bpy.data.cameras.new(name)
    if c.get("proj", 1) == 0:
        cam.type = 'ORTHO'
        cam.sensor_fit = 'VERTICAL'
        if c.get("orthoheight"):
            cam.ortho_scale = c["orthoheight"]
    elif c.get("fov"):
        if c.get("fovtype", 1) == 0:
            cam.sensor_fit = 'VERTICAL'
            cam.angle_y = radians(c["fov"])
        else:
            cam.sensor_fit = 'HORIZONTAL'
            cam.angle_x = radians(c["fov"])
    if c.get("near"):
        cam.clip_start = c["near"]
    if c.get("far"):
        cam.clip_end = c["far"]
    if c.get("aspect"):
        cam["si_aspect"] = c["aspect"]
    return cam


LIGHT_TYPES = {0: 'POINT', 1: 'SUN', 2: 'SPOT'}


def light_data(name, lt):
    """(Blender light, notes) from Softimage light settings. Colour, intensity, shadows and spot spread come
    from Softimage's soft_light shader; power follows Get > Primitive (intensity 0.75 = the kit's default)."""
    from . import primitives
    kind = LIGHT_TYPES.get(lt.get("Type", 0), 'POINT')
    data = bpy.data.lights.new(name, kind)
    notes = []
    sl = lt.get("soft_light")
    intensity = 0.75
    if sl:
        data.color = (sl["red"], sl["green"], sl["blue"])
        intensity = sl["intensity"]
        data.use_shadow = bool(sl["shadow"])
    elif lt.get("shader"):
        notes.append("light shader %s not mapped (colour and intensity left at defaults)" % lt["shader"])
    data.energy = primitives.LIGHT_POWER[kind] * intensity / 0.75
    if kind == 'SPOT':
        cone = lt.get("LightCone", 60.0)
        data.spot_size = radians(cone)
        if sl and cone:
            data.spot_blend = max(0.0, min(1.0, sl["spread"] / cone))
    return data, notes


def mesh_object(name, points, polygons):
    me = bpy.data.meshes.new(name)
    me.from_pydata([convert_point(p) for p in points], [], [list(f) for f in polygons])
    me.update()
    return bpy.data.objects.new(name, me)


def live_primitive(so):
    """Object for a live Softimage primitive: the kit's live primitive (Geometry Nodes, editable like in
    Softimage) where there is one, otherwise a plain mesh from the Get > Primitive builders."""
    import bmesh
    from . import gn_primitives, primitives
    gen = so.generator
    kind, p = gen["type"], gen["params"]
    live = kind.upper()
    if live in gn_primitives.LIVE:
        ob = bpy.data.objects.new(so.name, bpy.data.meshes.new(so.name))
        mod = gn_primitives.add_modifier(ob, live)
        names = {n for n, *_ in gn_primitives.PARAMS[live]}
        for key, value in p.items():
            sock = GN_SOCKETS.get(key)
            if sock in names:
                gn_primitives.set_param(mod, sock, value)
        return ob
    r = p.get("radius", 4.0)
    bm = bmesh.new()
    if kind == "disc":
        primitives.build_disc(bm, radius=p.get("outerradius", 4.0), u=p.get("subdivu", 8), v=p.get("subdivv", 8),
                              inner=p.get("innerradius", 2.0))
    else:
        getattr(primitives, "build_" + kind)(bm, r)
    me = bpy.data.meshes.new(so.name)
    bm.to_mesh(me)
    bm.free()
    return bpy.data.objects.new(so.name, me)


def build(context, sc, report=None):
    """Create the objects of scene `sc` in the active collection; returns {name: object}."""
    collection = context.collection
    made = {}

    def note(ob, what, notes):
        if notes:
            ob["si_import_notes"] = "; ".join(notes)
            if report:
                report({'WARNING'}, "%s (%s): %s" % (ob.name, what, "; ".join(notes)))
        return ob

    def make(so):
        if so.kind == 'polymsh' and so.mesh is not None:
            ob = mesh_object(so.name, so.mesh.points, so.mesh.polygons)
            ops = getattr(so, "ops", None)
            return note(ob, "mesh", ["operators on top not applied: %s" % ops_text(ops)] if ops else [])
        if so.kind == 'polymsh' and getattr(so, "generator", None) is not None:
            moved = replayed_moves(so.generator)
            if moved is not None:            # live primitive + point moves: replayed, as a plain mesh
                return mesh_object(so.name, *moved)
            gen = so.generator
            exact = exact_shape(gen)
            if exact is not None:            # e.g. a partial sphere: Softimage's mesh, as a plain mesh
                ops = gen.get("ops")
                return note(mesh_object(so.name, *exact), gen["type"],
                            ["operators on top not rebuilt: %s" % ops_text(ops, gen.get("moves"))] if ops else [])
            return note(live_primitive(so), gen["type"], generator_notes(gen))
        if so.kind == 'polymsh' and report:
            report({'WARNING'}, "%s: polygon mesh has no stored geometry and no known generator, imported as an "
                   "empty" % so.name)
        if so.kind == 'camera':
            c = getattr(so, "camera", None) or {}
            if c.get("animated"):         # the stored lens is only the base under the animation
                c = dict((k, v) for k, v in c.items() if k not in ("fov", "orthoheight"))
            ob = bpy.data.objects.new(so.name, camera_data(so.name, c))
            missing = c.get("fov") is None and c.get("proj", 1) != 0
            return note(ob, "camera", ["animated lens not imported yet: Blender's default lens"] if missing else [])
        if so.kind == 'light':
            data, notes = light_data(so.name, getattr(so, "light", None) or {})
            return note(bpy.data.objects.new(so.name, data), "light", notes)
        return bpy.data.objects.new(so.name, None)

    def walk(so, parent_so):
        ob = make(so)
        collection.objects.link(ob)
        if parent_so is not None:
            ob.parent = made[id(parent_so)]
        ob.matrix_basis = blender_matrix(so.local, own_fix=so.kind in FIXED_KINDS,
                                         parent_fix=parent_so is not None and parent_so.kind in FIXED_KINDS)
        made[id(so)] = ob
        for c in so.children:
            walk(c, so)

    for r in sc.roots:
        walk(r, None)
    from . import import_materials
    import_materials.apply(sc, made, report)
    return {so.name: made[id(so)] for so in sc.objects if id(so) in made}


class SI_OT_import_scn(bpy.types.Operator, ImportHelper):
    """Import a Softimage scene (.scn): hierarchy, transforms, polygon meshes, cameras, lights"""
    bl_idname = "si.import_scn"
    bl_label = "Softimage Scene (.scn)"
    bl_options = {'REGISTER', 'UNDO'}

    filename_ext = ".scn"
    filter_glob: StringProperty(default="*.scn", options={'HIDDEN'})

    def execute(self, context):
        try:
            sc = scn.read(self.filepath)
        except Exception as e:
            self.report({'ERROR'}, "Cannot read %s: %s" % (self.filepath, e))
            return {'CANCELLED'}
        for w in sc.warnings:
            self.report({'WARNING'}, str(w))
        for ob in context.selected_objects:
            ob.select_set(False)
        objs = build(context, sc, self.report)
        for ob in objs.values():
            ob.select_set(True)
        if objs:
            context.view_layer.objects.active = next(iter(objs.values()))
        self.report({'INFO'}, "Imported %d objects" % len(objs))
        return {'FINISHED'}


def _menu_func(self, context):
    self.layout.operator(SI_OT_import_scn.bl_idname, text="Softimage Scene (.scn)")


classes = (SI_OT_import_scn,)


def register():
    for c in classes:
        bpy.utils.register_class(c)
    bpy.types.TOPBAR_MT_file_import.append(_menu_func)


def unregister():
    bpy.types.TOPBAR_MT_file_import.remove(_menu_func)
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
