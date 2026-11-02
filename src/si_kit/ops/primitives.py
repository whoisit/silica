# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Alex Doss
"""Get > Primitive with Softimage defaults.

Sizes and subdivisions match Softimage 2015 (captured): cube length 8; sphere radius 4, 8x8; grid 8x8 units, 8x8;
cylinder radius 1 height 4 (8 around, 2 high, 2 cap rings); cone radius 1 height 4 (base at -h/3); torus 4 outer /
1 tube, 8x8; disc radius 4, 8x8; platonic solids radius 4. Softimage is Y-up, Blender Z-up: Softimage "up" is
Blender Z, so the grid and disc lie on the floor (XY) and cylinders/cones stand along Z.
Objects are created at the world origin, selected and made active, named like Softimage (cube, cube1, cube2...).
One Softimage unit = one Blender unit (see MVP open question on scale).
"""

import math

import bmesh
import bpy
from bpy.props import EnumProperty, StringProperty
from mathutils import Matrix, Vector

MESH_KINDS = ("CUBE", "SPHERE", "GRID", "CYLINDER", "CONE", "TORUS", "DISC", "DODECAHEDRON", "ICOSAHEDRON",
              "OCTAHEDRON", "TETRAHEDRON", "EMPTY_MESH")
KINDS = MESH_KINDS + ("NULL", "LIGHT_POINT", "LIGHT_SPOT", "LIGHT_INFINITE", "CAMERA", "CAMERA_TELEPHOTO",
                      "CAMERA_WIDE", "CAMERA_ORTHO", "CURVE_CIRCLE",
                      "IMPLICIT_CUBE", "IMPLICIT_SPHERE", "IMPLICIT_CIRCLE", "IMPLICIT_CONE")
NAMES = {"CUBE": "cube", "SPHERE": "sphere", "GRID": "grid", "CYLINDER": "cylinder", "CONE": "cone",
         "TORUS": "torus", "DISC": "disc", "DODECAHEDRON": "dodecahedron", "ICOSAHEDRON": "icosahedron",
         "OCTAHEDRON": "octahedron", "TETRAHEDRON": "tetrahedron", "EMPTY_MESH": "polymsh", "NULL": "null",
         "LIGHT_POINT": "light", "LIGHT_SPOT": "Spot", "LIGHT_INFINITE": "infinite", "CAMERA": "Camera",
         "CAMERA_TELEPHOTO": "Telephoto", "CAMERA_WIDE": "WideAngle", "CAMERA_ORTHO": "Ortho",
         "CURVE_CIRCLE": "circle", "IMPLICIT_CUBE": "cube", "IMPLICIT_SPHERE": "sphere",
         "IMPLICIT_CIRCLE": "circle", "IMPLICIT_CONE": "cone"}
LIGHT_POWER = {'POINT': 1000.0, 'SPOT': 2000.0, 'SUN': 3.0}
# horizontal field of view in degrees (Softimage fovtype 1 = horizontal)
CAMERA_FOV = {"CAMERA": 53.638, "CAMERA_TELEPHOTO": 6.662, "CAMERA_WIDE": 115.62, "CAMERA_ORTHO": 53.638}


def si_name(base):
    """Softimage naming: base, base1, base2... (Blender would make base.001)."""
    if base not in bpy.data.objects:
        return base
    i = 1
    while "%s%d" % (base, i) in bpy.data.objects:
        i += 1
    return "%s%d" % (base, i)


# --- mesh builders (bmesh, Blender Z-up) ----------------------------------------------------------------------

def _ring(bm, radius, z, n, start=0.0):
    return [bm.verts.new((radius * math.cos(start + 2 * math.pi * i / n), radius * math.sin(start + 2 * math.pi * i / n), z))
            for i in range(n)]


def _bridge(bm, a, b):
    n = len(a)
    for i in range(n):
        bm.faces.new((a[i], a[(i + 1) % n], b[(i + 1) % n], b[i]))


def _cap(bm, ring, center_z, rings, radius, up):
    """Close a ring with `rings` concentric rings (Softimage subdivbase) and a centre fan."""
    n = len(ring)
    prev = ring
    for k in range(rings - 1, 0, -1):
        r = radius * k / rings
        cur = _ring(bm, r, center_z, n)
        if up:
            _bridge(bm, prev, cur)
        else:
            _bridge(bm, cur, prev)
        prev = cur
    c = bm.verts.new((0, 0, center_z))
    for i in range(n):
        f = (prev[i], prev[(i + 1) % n], c) if up else (prev[(i + 1) % n], prev[i], c)
        bm.faces.new(f)


def build_cylinder(bm, radius=1.0, height=4.0, u=8, v=2, base=2):
    rings = [_ring(bm, radius, -height / 2 + height * k / v, u) for k in range(v + 1)]
    for a, b in zip(rings, rings[1:]):
        _bridge(bm, a, b)
    _cap(bm, rings[-1], height / 2, base, radius, up=True)
    _cap(bm, rings[0], -height / 2, base, radius, up=False)


def build_cone(bm, radius=1.0, height=4.0, u=8, v=2, base=2):
    z0 = -height / 3.0
    rings = [_ring(bm, radius * (1 - k / v), z0 + height * k / v, u) for k in range(v)]
    for a, b in zip(rings, rings[1:]):
        _bridge(bm, a, b)
    apex = bm.verts.new((0, 0, z0 + height))
    top = rings[-1]
    for i in range(u):
        bm.faces.new((top[i], top[(i + 1) % u], apex))
    _cap(bm, rings[0], z0, base, radius, up=False)


def build_torus(bm, outer=4.0, tube=1.0, u=8, v=8):
    major = outer - tube
    grid = []
    for i in range(u):
        a = 2 * math.pi * i / u
        ca, sa = math.cos(a), math.sin(a)
        ring = []
        for j in range(v):
            b = 2 * math.pi * j / v
            r = major + tube * math.cos(b)
            ring.append(bm.verts.new((r * ca, r * sa, tube * math.sin(b))))
        grid.append(ring)
    for i in range(u):
        a, b = grid[i], grid[(i + 1) % u]
        for j in range(v):
            bm.faces.new((a[j], b[j], b[(j + 1) % v], a[(j + 1) % v]))


def build_disc(bm, radius=4.0, u=8, v=8, inner=2.0):
    """Softimage's disc: an annulus from `inner` to `radius`, u columns of v+1 points (inner to outer), the
    first column on -X, then counter-clockwise seen from above; same point and polygon order as Softimage."""
    cols = []
    for c in range(u):
        a = 2.0 * math.pi * c / u
        dx, dy = -math.cos(a), -math.sin(a)          # Softimage (-cos a, 0, sin a) in Blender axes
        cols.append([bm.verts.new((dx * r, dy * r, 0.0))
                     for r in (inner + (radius - inner) * k / v for k in range(v + 1))])
    for c in range(u):
        a, b = cols[c], cols[(c + 1) % u]
        for k in range(v):
            bm.faces.new((a[k], a[k + 1], b[k + 1], b[k]))


def _solid(bm, verts, faces, radius):
    vs = [Vector(v) for v in verts]
    s = radius / max(v.length for v in vs)
    bv = [bm.verts.new(v * s) for v in vs]
    for f in faces:
        bm.faces.new([bv[i] for i in f])
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])


def build_octahedron(bm, r=4.0):
    _solid(bm, [(1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1)],
           [(0, 2, 4), (2, 1, 4), (1, 3, 4), (3, 0, 4), (2, 0, 5), (1, 2, 5), (3, 1, 5), (0, 3, 5)], r)


# Softimage's own platonic solids at radius 1 (Softimage axes, Y up), with its point and polygon order:
# measured from Softimage 2015 (gen_scn_corpus.py prim_* cases), so a rebuilt solid is the same mesh.
SOLIDS = {
    "tetrahedron": (
        [(0.471404, -0.333333, 0.816496), (0.471404, -0.333333, -0.816496), (0, 1, 0), (-0.942809, -0.333333, 0)],
        [(3, 2, 1), (2, 3, 0), (1, 0, 3), (0, 1, 2)]),
    "icosahedron": (
        [(0.850667, 0.447222, 0.276399), (-0.850667, 0.447222, 0.276399), (0.850667, -0.447222, -0.276399),
         (-0.850667, -0.447222, -0.276399), (0.525741, -0.447222, 0.723621), (0.525741, 0.447222, -0.723621),
         (-0.525741, -0.447222, 0.723621), (-0.525741, 0.447222, -0.723621), (0, 0.447222, 0.894445),
         (0, -1.00002, 0), (0, 1.00002, 0), (0, -0.447222, -0.894445)],
        [(0, 8, 4), (0, 5, 10), (2, 4, 9), (2, 11, 5), (1, 6, 8), (1, 10, 7), (3, 9, 6), (3, 7, 11), (0, 10, 8),
         (1, 8, 10), (2, 9, 11), (3, 11, 9), (4, 2, 0), (5, 0, 2), (6, 1, 3), (7, 3, 1), (8, 6, 4), (9, 4, 6),
         (10, 5, 7), (11, 7, 5)]),
    "dodecahedron": (
        [(0, -0.794655, 0.607062), (0, -0.187593, 0.982247), (0, 0.187593, -0.982247), (0, 0.794655, -0.607062),
         (0.356822, 0.794654, 0.491124), (-0.356822, 0.794654, 0.491124), (0.356822, -0.794654, -0.491124),
         (-0.356822, -0.794654, -0.491124), (0.934172, -0.187593, 0.303531), (0.934172, 0.187593, -0.303531),
         (-0.934172, -0.187593, 0.303531), (-0.934172, 0.187593, -0.303531), (0.57735, 0.187592, 0.794655),
         (-0.57735, 0.187592, 0.794655), (0.57735, -0.794655, 0.187592), (-0.57735, -0.794655, 0.187592),
         (0.57735, 0.794655, -0.187592), (-0.57735, 0.794655, -0.187592), (0.57735, -0.187592, -0.794655),
         (-0.57735, -0.187592, -0.794655)],
        [(0, 14, 8, 12, 1), (0, 1, 13, 10, 15), (4, 5, 13, 1, 12), (6, 14, 0, 15, 7), (18, 9, 8, 14, 6),
         (9, 16, 4, 12, 8), (19, 7, 15, 10, 11), (17, 11, 10, 13, 5), (2, 3, 16, 9, 18), (3, 17, 5, 4, 16),
         (2, 19, 11, 17, 3), (2, 18, 6, 7, 19)]),
}


def _softimage_solid(bm, kind, r):
    pts, faces = SOLIDS[kind]
    bv = [bm.verts.new((x * r, -z * r, y * r)) for x, y, z in pts]   # Softimage (x, y, z) -> Blender (x, -z, y)
    for f in faces:
        bm.faces.new([bv[i] for i in f])


def build_tetrahedron(bm, r=4.0):
    _softimage_solid(bm, "tetrahedron", r)


def build_icosahedron(bm, r=4.0):
    _softimage_solid(bm, "icosahedron", r)


def build_dodecahedron(bm, r=4.0):
    _softimage_solid(bm, "dodecahedron", r)


def build_mesh(kind):
    bm = bmesh.new()
    if kind == "CUBE":
        bmesh.ops.create_cube(bm, size=8.0)
    elif kind == "SPHERE":
        bmesh.ops.create_uvsphere(bm, u_segments=8, v_segments=8, radius=4.0)
    elif kind == "GRID":
        bmesh.ops.create_grid(bm, x_segments=8, y_segments=8, size=4.0)
    elif kind == "CYLINDER":
        build_cylinder(bm)
    elif kind == "CONE":
        build_cone(bm)
    elif kind == "TORUS":
        build_torus(bm)
    elif kind == "DISC":
        build_disc(bm)
    elif kind == "ICOSAHEDRON":
        build_icosahedron(bm)
    elif kind == "OCTAHEDRON":
        build_octahedron(bm)
    elif kind == "TETRAHEDRON":
        build_tetrahedron(bm)
    elif kind == "DODECAHEDRON":
        build_dodecahedron(bm)
    me = bpy.data.meshes.new(NAMES[kind])
    bm.to_mesh(me)
    bm.free()
    return me


# --- object creation --------------------------------------------------------------------------------------

def _link(context, ob):
    coll = context.collection or context.scene.collection
    coll.objects.link(ob)
    return ob


def _select_only(context, obs, active):
    for o in context.view_layer.objects:
        if o.select_get():
            o.select_set(False)
    for o in obs:
        o.select_set(True)
    context.view_layer.objects.active = active


def _empty(context, name, display='PLAIN_AXES', size=1.0, parent=None, loc=(0, 0, 0)):
    ob = bpy.data.objects.new(si_name(name), None)
    ob.empty_display_type = display
    ob.empty_display_size = size
    ob.location = loc
    if parent:
        ob.parent = parent
    return _link(context, ob)


def _track(ob, target):
    c = ob.constraints.new('TRACK_TO')
    c.target = target
    c.track_axis = 'TRACK_NEGATIVE_Z'
    c.up_axis = 'UP_Y'
    return c


def create(context, kind):
    """Create a Softimage primitive; returns (objects created, object to select)."""
    from . import gn_primitives
    if kind in gn_primitives.LIVE:
        # live primitive: empty mesh + Geometry Nodes operator (Softimage parameters stay editable until Freeze)
        ob = _link(context, bpy.data.objects.new(si_name(NAMES[kind]), bpy.data.meshes.new(NAMES[kind])))
        gn_primitives.add_modifier(ob, kind)
        return [ob], ob
    if kind in MESH_KINDS:
        me = bpy.data.meshes.new(NAMES[kind]) if kind == "EMPTY_MESH" else build_mesh(kind)
        ob = _link(context, bpy.data.objects.new(si_name(NAMES[kind]), me))
        return [ob], ob
    if kind == "NULL":
        ob = _empty(context, "null")
        return [ob], ob
    if kind.startswith("IMPLICIT_"):
        disp = {"IMPLICIT_CUBE": 'CUBE', "IMPLICIT_SPHERE": 'SPHERE', "IMPLICIT_CIRCLE": 'CIRCLE',
                "IMPLICIT_CONE": 'CONE'}[kind]
        ob = _empty(context, NAMES[kind], disp, 4.0)
        return [ob], ob
    if kind.startswith("LIGHT_"):
        ltype = {"LIGHT_POINT": 'POINT', "LIGHT_SPOT": 'SPOT', "LIGHT_INFINITE": 'SUN'}[kind]
        name = NAMES[kind]
        data = bpy.data.lights.new(name, ltype)
        # Softimage lights have no falloff by default; Blender's are physical. These powers light an
        # 8-unit Softimage-sized scene from ~10 units away.
        data.energy = LIGHT_POWER[ltype]
        if ltype == 'SPOT':
            data.spot_size = math.radians(60.0)      # Softimage LightCone 60
            root = _empty(context, name + "_Root")
            ob = bpy.data.objects.new(si_name(name), data)
            ob.parent = root
            ob.location = (0.0, -8.0, 8.0)
            _link(context, ob)
            interest = _empty(context, name + "_Interest", 'PLAIN_AXES', 0.5, parent=root)
            _track(ob, interest)
            return [root, ob, interest], ob
        ob = bpy.data.objects.new(si_name(name), data)
        if ltype == 'SUN':
            ob.rotation_euler = (math.radians(45), 0, math.radians(45))
        _link(context, ob)
        return [ob], ob
    if kind.startswith("CAMERA"):
        root = _empty(context, "Camera_Root")
        data = bpy.data.cameras.new("Camera")
        data.sensor_fit = 'HORIZONTAL'
        data.angle = math.radians(CAMERA_FOV[kind])
        data.clip_start = 0.1
        data.clip_end = 32768.0
        if kind == "CAMERA_ORTHO":
            data.type = 'ORTHO'
            data.ortho_scale = 16.0
        ob = bpy.data.objects.new(si_name(NAMES[kind]), data)
        ob.parent = root
        ob.location = (0.0, -20.0, 4.0)
        _link(context, ob)
        interest = _empty(context, NAMES[kind] + "_Interest", 'PLAIN_AXES', 0.5, parent=root)
        _track(ob, interest)
        return [root, ob, interest], ob
    if kind == "CURVE_CIRCLE":
        cu = bpy.data.curves.new("circle", 'CURVE')
        cu.dimensions = '3D'
        sp = cu.splines.new('NURBS')
        n = 8
        sp.points.add(n - 1)
        for i, p in enumerate(sp.points):
            a = 2 * math.pi * i / n
            p.co = (4.0 * math.cos(a), 4.0 * math.sin(a), 0.0, 1.0)
        sp.use_cyclic_u = True
        sp.order_u = 4
        ob = _link(context, bpy.data.objects.new(si_name("circle"), cu))
        return [ob], ob
    raise ValueError(kind)


class SI_OT_get_primitive(bpy.types.Operator):
    bl_idname = "si.get_primitive"
    bl_label = "Get Primitive"
    bl_description = "Create a primitive with Softimage's default size, at the origin"
    bl_options = {'REGISTER', 'UNDO'}

    kind: EnumProperty(items=[(k, k.replace("_", " ").title(), "") for k in KINDS])

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT'

    def invoke(self, context, event):
        # Softimage: Ctrl while choosing the command inverts "Popup Property Editors on Node Creation" once
        self._invert_popup = bool(event.ctrl)
        return self.execute(context)

    def execute(self, context):
        obs, active = create(context, self.kind)
        _select_only(context, obs[-1:] if active is None else [active], active)
        if context.window is not None and active is not None and not self.options.is_repeat:
            from ..ui import ppg
            ppg.open_after_create(context, active, invert=getattr(self, "_invert_popup", False))
        return {'FINISHED'}


def register():
    bpy.utils.register_class(SI_OT_get_primitive)


def unregister():
    bpy.utils.unregister_class(SI_OT_get_primitive)
