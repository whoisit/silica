# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Alex Doss
"""High-level view of a Softimage .scn: objects, names, hierarchy, transforms, polygon meshes.

Classes and parameters are identified by GUID (stable across files); the per-file numeric ids are only
indices into the stream's GUID table. The GUIDs below were identified from scenes generated for this
purpose (tools/sicapture/softimage/gen_scn_corpus.py) by comparing them with Softimage's own answers.
"""
from . import cfb, records

# Class kinds, keyed by the GUID of the class's root parameter definition (Obj.pbase).
KIND = {
    "5fc0ccae-3dc8-11d0-9449-00aa006d3165": "x3d",          # X3DObject: name, child X3Ds, body
    "51bf4f41-6777-11d1-be9f-00a024ee478d": "body",         # primitive, visibility, kinematics
    "d557cf35-57e3-11d2-8b5a-00a024ee586f": "kinematics",   # refs: global state, local state
    "7abf1486-448d-11d0-be37-00a024ee478d": "kine_global",
    "77f74c81-7010-11d1-96f5-00a0243e3463": "kine_local",
    "11ebe301-a20c-11d0-8478-00a024c7919c": "visibility",
    "7dd91aa2-89d8-11d0-a75c-00aa00bb6238": "null",
    "400cce36-4400-11d0-bddd-00a0241981e2": "polymsh",
    "1152e9b1-545e-11d0-8466-00a024c7919c": "camera",
    "f3705c30-5204-11d0-8298-00a0243e366b": "light",
    "973e6f73-cd0f-11d3-a88b-00c04f8edf15": "CameraRoot",
    "9694b47e-c847-11d3-b7d4-0008c7a011a6": "CameraInterest",
    # Found in scenes saved by Softimage 6.x-2014 (names are the class names stored in those files).
    "28dec317-62b3-11d1-b79b-00a0243e3694": "crvlist",       # NURBS curve list
    "b4088ad0-531c-11d2-8bae-00aa00135f7b": "root",          # skeleton chain root
    "f718e610-06f5-11d1-84ec-00a0243e3543": "bone",
    "b4088ad1-531c-11d2-8bae-00aa00135f7b": "eff",           # chain effector
    "973e6f74-cd0f-11d3-a88b-00c04f8edf15": "SpotRoot",
    "49086e62-cd0b-11d3-a88b-00c04f8edf15": "SpotInterest",
    "6808c4b1-d608-11d0-8a20-080036f3cc02": "Texture Support",
    "2194ffe3-a0b2-4cab-a3e8-fc8edc9f159a": "pointcloud",
    "d5c3cdba-b361-4a11-9582-91dba0ecbb49": "hair",
    "74219011-7a20-11d0-b07a-00a024c79287": "lattice",
    "aab8567b-4e8c-474d-98aa-917d0db9ba94": "TransfoGroup",
    # Implicit shapes and curve generators: they label an object only when no geometry primitive is
    # found (a live curve's body holds both its crvlist and the generator).
    "7fa10ca1-79ed-11d0-9fa9-00aa00bb6238": "cube",
    "d75332c1-bffe-11d0-96c3-00a0243e3463": "sphere",
    "173856e8-5753-11d0-b2b3-00a024c79287": "grid",
    "948cc1d0-88da-11d0-a75c-00aa00bb6238": "cylinder",
    "5216d7c1-d6c0-11d0-91c3-00aa00629814": "disc",
    "173856e9-5753-11d0-b2b3-00a024c79287": "circle",
    "173856ea-5753-11d0-b2b3-00a024c79287": "arc",
    "173856eb-5753-11d0-b2b3-00a024c79287": "spiral",
    "7dd91aa1-89d8-11d0-a75c-00aa00bb6238": "square",
    "22a39982-4fb2-11d1-800d-00a0c955b335": "text",
    "cbeba471-7e96-11d0-9fa9-00aa00bb6238": "cone",
    "15511d41-4c5d-11d0-b2a9-00a024c79287": "torus",
    "cf1d60d4-9d74-11d1-8047-00a0c9067c03": "tetrahedron",
    "cf1d60d3-9d74-11d1-8047-00a0c9067c03": "octahedron",
    "cf1d60d2-9d74-11d1-8047-00a0c9067c03": "icosahedron",
    "677563ee-9d74-11d1-8047-00a0c9067c03": "dodecahedron",
}
PRIMITIVES = ("null", "polymsh", "camera", "light", "CameraRoot", "CameraInterest", "crvlist", "root", "bone",
              "eff", "SpotRoot", "SpotInterest", "Texture Support", "pointcloud", "hair", "lattice", "TransfoGroup")
IMPLICIT = ("cube", "sphere", "grid", "cylinder", "disc", "circle", "arc", "spiral", "square", "text", "cone", "torus",
            "tetrahedron", "octahedron", "icosahedron", "dodecahedron")

# Live polygon primitives. A live mesh stores no geometry: the body holds the implicit shape (sizes), and the
# polymsh refers to the generator operator (subdivisions, angles, caps) that turns the shape into polygons.
# Generator operator class (pbase GUID) -> primitive kind.
GENERATOR_OPS = {
    "afefa311-8380-11d0-9fad-00aa00bb6238": "cube",
    "aa35af50-51e8-11d0-b2aa-00a024c79287": "sphere",
    "173856e0-5753-11d0-b2b3-00a024c79287": "grid",
    "1952a000-88f9-11d0-a75c-00aa00bb6238": "cylinder",
    "afefa310-8380-11d0-9fad-00aa00bb6238": "cone",
    "f386c4a2-4e11-11d0-b2aa-00a024c79287": "torus",
    "30c4a3f2-d6c8-11d0-91c3-00aa00629814": "disc",
    "9f90e1e1-6cd9-454a-a859-32891f7466e6": "tetrahedron",
    "1caad8c5-1584-49e6-bf75-9f454d97bacc": "octahedron",
    "aa05000e-69a1-4309-93de-ee7296e62ca9": "icosahedron",
    "40e5a38a-dcfd-4fdc-9620-cfd6f7445c5f": "dodecahedron",
}
# What else a live polymsh refers to. These change nothing: the construction-mode markers and one object every
# polymsh has.
STACK_PASSIVE = {
    "60f7ada0-7e12-11d0-9960-00a0243f0e60",
    "9b82aced-9947-4fd0-87ae-4ac0a3d42bea", "b0a5373d-e8b3-4816-bc5a-a6a31e4b4158",   # the four markers
    "0d29533c-b095-48f8-88b9-bdf8419453e7", "dba00978-85be-4d94-aec5-422ecb4ee4bd",
    "7a75d26f-ec7a-494b-9f11-b5f76c6c5d0f", "b8ed9aa1-563c-4011-95cc-22ea7dca9f11",   # simulation markers
}
# Operators stacked on top of a generator, by class GUID -> Softimage operator type. Paired with Softimage's
# answers on the SItoA scenes (objects with exactly one unknown GUID and one operator, then by elimination).
OPERATOR_NAMES = {
    "19085f81-cdd6-471c-9ca1-7c7f4f2a0166": "ICETree",
    "08420bb0-f664-11d2-912f-00a0244eeb76": "center",
    "4fda26db-c702-11d0-b696-00aa003b3ea6": "bulgeop",
    "a1660900-1305-11d0-8d79-0020af9d8e1d": "bendop",
    "eb99f710-c92f-11cf-894b-00a02418cf4a": "twistop",
    "9756f025-e75b-11d0-b6b2-00aa003b3ea6": "pushop",
    "84c9e4b6-0827-42cf-9c84-e570da366263": "foldop",
    "389e27dd-5fb0-11d2-b11c-00a0c906811e": "movecomponentop",
    "6c8f2060-4849-11d4-a8b6-00c04f8edf15": "deletecompop",
    "2fb8a5db-3712-11d4-a8b0-00c04f8edf15": "subdividepolygonop",
    "0457342a-67ee-11d4-b490-009027bc38d5": "booleansrftopoop",
    "9afbf7f0-d74f-11d2-9c48-0060970a2bc8": "clustershapecombiner",
    "04433582-2ab0-11d4-b840-009027bc6587": "edge flags",   # MarkHardEdgeVertex / SetEdgeCreaseValue: only seen
    "9e7ee952-2d91-11d4-b841-009027bc6587": "edge flags",   # together, so not told apart yet
    # paired on the 30 real scenes (Softimage 6.x-2014 saves)
    "59d5c165-4bb1-11d4-a8b7-00c04f8edf15": "bevelop",
    "88ec8342-268e-11d4-97f3-0800360bff02": "collapseop",
    "0a9fc720-90c7-11d4-a9e3-009027bc65d7": "dissolvecompop",
    "9e734591-4b92-11d4-b7f3-0008c7a011a6": "extrudecompaxisop",
    "addbd2a0-85a4-11d4-8c31-009027bc3a0e": "invertpolygonop",
    "3aa9962e-7a18-4355-9a29-dabf736fb02b": "movecomponentproportional",
    "f7e84d13-964f-11d0-b085-00a024c79287": "randomizeop",
    "3d5d3350-46b7-11d4-8c28-009027bc3a0e": "splitedgeop",
    "0bd53677-359b-11d4-a8af-00c04f8edf15": "subdivideedgeop",
    "0deadac0-47ac-11d4-8c27-009027bc3a0e": "addedgeop",
    "4304302a-1a39-4a51-a5a5-ce210461728d": "weldpointsop",
    "470cf890-d3aa-11d0-996c-00a0243f0e60": "envelopop",
    "c4e3ea0e-e257-11d2-b19f-00a0c9ac02dc": "clsctr",
    "f8842ca2-78fd-11d4-b851-009027bc6587": "meshlocalsubdivisionop",
    "cbb627a6-84ec-42a3-894d-09f78fcf0293": "Evolve",        # ICE simulation step
    # on frozen meshes
    "25e2d19e-5e10-4006-aaa7-5a7ae842e120": "quadrangulateop",
    "8c01ea38-1b7a-431d-aeb2-e89cd69e2e8f": "symmetrizepolygonop",
    "386b0f00-65ce-11d1-84c6-00a0243e3543": "lattice",
    "72936430-9b0c-4167-8ca7-c30fc2188bb9": "KP_PointCache",
    "035efc10-3bb6-11d4-8c25-009027bc3a0e": "createpolygonop",   # by its GUID family (split / add edge); one case
    "937db3e4-1625-4b42-ad56-8f6d1059c913": "disconnectcompop",
    "d3cc1746-e647-40c3-a766-0c78bce1c34c": "BoxConnector",  # rig connectors (ICE_rig_FRank)
    "b513c094-8d5e-45ac-ba50-da4f301d9f33": "HeadConnector",
    "c29cdc6f-7f05-4940-a035-92696bf774e6": "LConnector",
    "d0bba6a4-be62-4791-b8f4-ae33be16b863": "TConnector",
}
OPERATOR_GROUPS = {"MarkHardEdgeVertex": "edge flags", "SetEdgeCreaseValue": "edge flags"}

# Parameter definition GUID -> Softimage script name, for the shapes and their generators. Some names have
# several definitions (e.g. subdivu: one for cube/cylinder/cone, another for sphere/grid/torus/disc).
GENERATOR_PARAMS = {
    # shape sizes
    "85dd0c76-89d6-11d0-a75c-00aa00bb6238": "length",          # cube
    "085cae71-89c6-11d0-a75c-00aa00bb6238": "radius",          # sphere
    "85dd0c72-89d6-11d0-a75c-00aa00bb6238": "ulength",         # grid
    "85dd0c73-89d6-11d0-a75c-00aa00bb6238": "vlength",
    "85dd0c70-89d6-11d0-a75c-00aa00bb6238": "radius",          # cylinder
    "85dd0c71-89d6-11d0-a75c-00aa00bb6238": "height",
    "75120f80-8074-11d0-9fad-00aa00bb6238": "radius",          # cone
    "75120f81-8074-11d0-9fad-00aa00bb6238": "height",
    "40337f81-795b-11d0-b07a-00a024c79287": "sectionradius",   # torus
    "40337f82-795b-11d0-b07a-00a024c79287": "radius",
    "5998c520-d6bd-11d0-91c3-00aa00629814": "innerradius",     # disc
    "5998c521-d6bd-11d0-91c3-00aa00629814": "outerradius",
    "cf1d60dd-9d74-11d1-8047-00a0c9067c03": "radius",          # tetrahedron
    "cf1d60dc-9d74-11d1-8047-00a0c9067c03": "radius",          # octahedron
    "cf1d60db-9d74-11d1-8047-00a0c9067c03": "radius",          # icosahedron
    "cf1d60da-9d74-11d1-8047-00a0c9067c03": "radius",          # dodecahedron
    # generator operators
    "5aa8da85-850a-11d0-9fae-00aa00bb6238": "subdivu",         # cube, cylinder, cone
    "5aa8da88-850a-11d0-9fae-00aa00bb6238": "subdivv",
    "5aa8da89-850a-11d0-9fae-00aa00bb6238": "subdivbase",
    "fefafd01-ae98-11d3-b456-0000f875e17b": "subdivu",         # sphere, grid, torus, disc
    "64d78e4e-2524-11d4-b490-009027bc38d5": "subdivv",
    "b5c950f1-116c-11d4-b49d-009027bc38d5": "startuangle",     # sphere, torus, disc
    "62bc5441-1569-11d4-b49d-009027bc38d5": "enduangle",
    "59eb2171-117b-11d4-b49d-009027bc38d5": "startuangle",     # cylinder, cone
    "62bc5442-1569-11d4-b49d-009027bc38d5": "enduangle",
    "241ffc01-16ff-11d4-b49d-009027bc38d5": "startvangle",     # sphere
    "241ffc02-16ff-11d4-b49d-009027bc38d5": "endvangle",
    "241ffc03-16ff-11d4-b49d-009027bc38d5": "startvangle",     # torus
    "241ffc04-16ff-11d4-b49d-009027bc38d5": "endvangle",
    "bc2a19b3-0b3e-11d4-b49d-009027bc38d5": "closevmin",       # cylinder
    "bc2a19b4-0b3e-11d4-b49d-009027bc38d5": "closevmax",
    "aebf31c1-0fdb-11d4-b49d-009027bc38d5": "closebottom",     # cone
    "9a01c2c4-9b31-11d5-aeef-0090275802c9": "freq",            # tetrahedron
    "9a01c2c5-9b31-11d5-aeef-0090275802c9": "method",
    "9a01c2c2-9b31-11d5-aeef-0090275802c9": "freq",            # octahedron
    "9a01c2c3-9b31-11d5-aeef-0090275802c9": "method",
    "9a01c2c0-9b31-11d5-aeef-0090275802c9": "freq",            # icosahedron
    "9a01c2c1-9b31-11d5-aeef-0090275802c9": "method",
}

P_NAME = "2b91c031-677a-11d1-b0cf-00a024c79287"


def _g(prefix, *lows):
    return tuple("%s%s" % (prefix, low) for low in lows)


# Kinematics parameters by definition GUID. Global and local states use different definitions.
KINE_GLOBAL = {
    "pos": ("4ee72a10-c55d-11d0-84db-00a0243e3543", "87b376a0-c562-11d0-84db-00a0243e3543",
            "9e2e32c0-c562-11d0-84db-00a0243e3543"),
    "rot": ("a35c9180-c562-11d0-84db-00a0243e3543", "a7c449e0-c562-11d0-84db-00a0243e3543",
            "b3a52900-c562-11d0-84db-00a0243e3543"),
    "quat": ("9a30bef3-5ae8-11d1-be9a-00a024ee478d", "9a30bef4-5ae8-11d1-be9a-00a024ee478d",
             "9a30bef5-5ae8-11d1-be9a-00a024ee478d", "9a30bef6-5ae8-11d1-be9a-00a024ee478d"),
    "scl": ("ba0216e0-c562-11d0-84db-00a0243e3543", "c0514410-c562-11d0-84db-00a0243e3543",
            "c903ac40-c562-11d0-84db-00a0243e3543"),
}
_L = "-b94b-11d2-b87f-00a0c92469be"
KINE_LOCAL = {
    "pos": ("06294283" + _L, "06294285" + _L, "06294286" + _L),
    "rot": ("06294289" + _L, "0629428a" + _L, "0629428b" + _L),           # degrees, XYZ
    "quat": ("0629428c" + _L, "0629428d" + _L, "0629428e" + _L, "0629428f" + _L),  # w x y z
    "scl": ("06294290" + _L, "06294291" + _L, "06294292" + _L),
}


class Transform:
    __slots__ = ("pos", "rot", "quat", "scl")

    def __init__(self):
        self.pos = [0.0, 0.0, 0.0]
        self.rot = [0.0, 0.0, 0.0]
        self.quat = [1.0, 0.0, 0.0, 0.0]
        self.scl = [1.0, 1.0, 1.0]

    def __repr__(self):
        return "Transform(pos=%s, rot=%s, scl=%s)" % (self.pos, self.rot, self.scl)


class SceneObject:
    def __init__(self, name):
        self.name = name
        self.kind = None          # 'null', 'polymsh', 'camera', 'light', ... or None if unknown
        self.parent = None
        self.children = []
        self.local = Transform()
        self.glob = Transform()
        self.primitive = None     # records.Obj of the primitive
        self.mesh = None          # mesh.Mesh for frozen polygon meshes, when decoded
        # Live primitive (no stored geometry): {"type": "sphere", "params": {"radius": 4.0, "subdivu": 8, ...}}
        # with Softimage's parameter script names.
        self.generator = None
        # Polygon meshes: Softimage operator types still live on top of the stored mesh or of the generator
        # (e.g. ["quadrangulateop"]); their effect is not in `mesh` / `generator`. 'unknown <guid>' when unnamed.
        self.ops = []
        # Cameras / lights: their settings by Softimage script name (io_scn/camlight.py), e.g. {"fov": 53.6, ...}
        self.camera = None
        self.light = None
        self.handle = None
        self.model = None         # owning model's SceneObject (None = Scene_Root)

    @property
    def full_name(self):
        """Softimage-style name: objects inside a model are prefixed with the model's name."""
        if self.model is not None:
            return self.model.full_name + "." + self.name
        return self.name

    def walk(self):
        yield self
        for c in self.children:
            yield from c.walk()

    def __repr__(self):
        return "<SceneObject %s %s pos=%s>" % (self.name, self.kind, self.local.pos)


class Scene:
    """Scene.objects lists every X3D object found; Scene.roots are the top-level ones."""

    def __init__(self, path):
        self.path = path
        self.cfb = cfb.CompoundFile(path)
        self.models = {}
        self.objects = []
        self.roots = []
        self.warnings = []
        self._models_by_storage = {}
        for storage in self._model_storages():
            self._read_model(storage)
        from . import materials
        materials.attach(self)

    def _model_storages(self):
        out = []
        for s in self.cfb.storages():
            if s.startswith("TLShell/Objects/") and self.cfb.exists(s + "/Objects"):
                out.append(s)
        return sorted(out, key=len)

    def _read_model(self, storage):
        data = self.cfb.read(storage + "/Objects")
        guids = records.guid_table(self.cfb.read(storage + "/GUIDS")) if self.cfb.exists(storage + "/GUIDS") else {}
        st = records.ObjectStream(data, guids)
        self.models[storage] = st
        inv = {g: i for i, g in guids.items()}
        ctx = {
            "st": st,
            "name": inv.get(P_NAME),
            "kine_local": {k: [inv.get(g) for g in gs] for k, gs in KINE_LOCAL.items()},
            "kine_global": {k: [inv.get(g) for g in gs] for k, gs in KINE_GLOBAL.items()},
        }
        made = {}
        for o in st.objects:
            if self._kind(st, o) == "x3d":
                so = SceneObject(o.params.get(ctx["name"], "?"))
                so.handle = o.handle
                made[o.handle] = so
        for o in st.objects:
            so = made.get(o.handle)
            if so is None:
                continue
            for h, _cls, _pos in o.refs:
                ref = st.by_handle.get(h)
                if ref is None:
                    continue
                k = self._kind(st, ref)
                if k == "x3d" and h in made:
                    child = made[h]
                    child.parent = so
                    so.children.append(child)
                elif k == "body":
                    self._read_body(ctx, ref, so)
        model = self._model_object(storage, st, ctx, made)
        for so in made.values():
            so.model = model
            if so.parent is None and model is not None:
                so.parent = model
                model.children.append(so)
        if model is not None:
            made[None] = model
        for so in made.values():
            self.objects.append(so)
            if so.parent is None:
                self.roots.append(so)

    def _model_object(self, storage, st, ctx, made):
        """Models other than Scene_Root live in their own storage (.../Scene.Models/InternalModelN). The
        stream's root block is the model: its name is a root parameter, and its own body is the one
        body in the stream that no object references. Its X3D objects are the stream's parentless ones.
        Returns None for Scene_Root (top-level objects stay roots)."""
        if "/Scene.Models/" not in storage:
            return None
        so = SceneObject(st.root_params.get(ctx["name"], storage.rsplit("/", 1)[-1]))
        so.kind = "model"
        so.handle = None
        referenced = {h for o in st.objects for h, _c, _p in o.refs}
        for o in st.objects:
            if o.parent is None and o.handle not in referenced and self._kind(st, o) == "body":
                self._read_body(ctx, o, so)
                break
        so.kind = "model"
        parent = self._models_by_storage.get(storage.rsplit("/Scene.Models/", 1)[0])
        if parent is not None:
            so.parent = parent
            parent.children.append(so)
            so.model = parent
        self._models_by_storage[storage] = so
        return so

    @staticmethod
    def _kind(st, o):
        return KIND.get(st.guid(o.pbase))

    def _read_body(self, ctx, body, so):
        st = ctx["st"]
        so.body = (st, body)      # materials.attach() follows the body to the material
        shape = None
        mesh_error = None
        for h, _c, _p in body.refs:
            ref = st.by_handle.get(h)
            if ref is None:
                continue
            k = self._kind(st, ref)
            if k in IMPLICIT:
                shape = ref
                if so.primitive is None:
                    so.kind = k
            elif k in PRIMITIVES:
                so.kind = k
                so.primitive = ref
                if k == "polymsh":
                    from . import mesh
                    try:
                        so.mesh = mesh.read_polymsh(st.data, ref)
                        if so.mesh.edges_ok is False:
                            self.warnings.append("%s: mesh topology does not match its edge table "
                                                 "(probably damaged index data)" % so.name)
                    except mesh.MeshError as e:
                        mesh_error = e
            elif k == "kinematics":
                for h2, _c2, _p2 in ref.refs:
                    state = st.by_handle.get(h2)
                    if state is None:
                        continue
                    ks = self._kind(st, state)
                    if ks == "kine_local":
                        self._fill(state, so.local, ctx["kine_local"])
                    elif ks == "kine_global":
                        self._fill(state, so.glob, ctx["kine_global"])
        if so.kind in ("camera", "light") and so.primitive is not None:
            from . import camlight
            if so.kind == "camera":
                so.camera = camlight.read_camera(st, so.primitive)
            else:
                so.light = camlight.read_light(st, so.primitive)
        if so.kind == "polymsh":
            so.ops = self._stack_ops(st, so.primitive)
            if so.mesh is None:
                so.generator = self._generator(st, so.primitive, shape)
                if so.generator is None and mesh_error is not None:
                    self.warnings.append("%s: mesh not decoded (%s)" % (so.name, mesh_error))

    @staticmethod
    def _stack_ops(st, polymsh):
        """Types of the operators the polymsh refers to, other than its generator and the passive markers."""
        ops = []
        for h, _c, _p in polymsh.refs:
            op = st.by_handle.get(h)
            if op is None:
                continue
            g = st.guid(op.pbase)
            if g not in GENERATOR_OPS and g not in STACK_PASSIVE:
                ops.append(OPERATOR_NAMES.get(g, "unknown %s" % g))
        return ops

    @classmethod
    def _generator(cls, st, polymsh, shape):
        """Live primitive: the generator operator the polymsh refers to, with its shape's sizes, and the names of
        the operators stacked on top (`ops`; 'unknown <guid>' for classes not identified yet)."""
        gen = None
        for h, _c, _p in polymsh.refs:
            op = st.by_handle.get(h)
            if op is None:
                continue
            kind = GENERATOR_OPS.get(st.guid(op.pbase))
            if kind is None or gen is not None:
                continue
            params = {}
            for src in (shape, op):
                if src is None:
                    continue
                for pid, v in src.params.items():
                    name = GENERATOR_PARAMS.get(st.guid(pid))
                    if name is not None:
                        params[name] = v
            gen = {"type": kind, "params": params}
        if gen is not None:
            gen["ops"] = cls._stack_ops(st, polymsh)
            if "movecomponentop" in gen["ops"]:
                from . import movecomponent
                # [movecomponent.Move], bottom of the stack first; None when one could not be decoded
                gen["moves"] = movecomponent.read_moves(st, polymsh)
        return gen

    @staticmethod
    def _fill(state, tr, ids):
        p = state.params
        for key, idl in ids.items():
            cur = getattr(tr, key)
            setattr(tr, key, [p.get(i, cur[n]) if i is not None else cur[n] for n, i in enumerate(idl)])

    def find(self, name):
        for o in self.objects:
            if o.name == name:
                return o
        return None


def read(path):
    return Scene(path)
