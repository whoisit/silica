# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Alex Doss
"""Materials, UV maps and image textures for File > Import > Softimage Scene (spec io.scn-materials).

`apply(sc, made, report)` runs after the objects exist: one Blender material per Softimage material that a mesh
uses (shared like in Softimage), cluster materials in further slots, UV maps from the texture projections, and an
Image Texture where an image feeds the main colour. Everything not carried over is named in the report and in the
material's `si_import_notes`.
"""
import os
import re

import bpy

from ..io_scn import materials as scn_materials

COLOUR_INPUT = {   # surface ProgID family -> its main colour parameter
    "phong": "diffuse", "blinn": "diffuse", "lambert": "diffuse", "architectural": "diffuse",
    "standard": "Kd_color", "standard_surface": "base_color",
}
IMAGE_NODES = ("Softimage.txt2d-image-explicit.1.0", "ArnoldCoreShaders.image.1.0", "Arnold.image.1.0")


def family(progid):
    """'phong', 'blinn', 'lambert', 'constant', 'architectural', 'incandescent', 'standard', 'standard_surface'
    or None (not supported)."""
    p = (progid or "").lower()
    for key, fam in (("material-phong", "phong"), ("material-blinn", "blinn"), ("material-lambert", "lambert"),
                     ("material-constant", "constant"), ("redshift.material-architectural", "architectural"),
                     ("redshift.material-incandescent", "incandescent"), ("arnold.standard_surface", "standard_surface"),
                     ("softimage.standard.", "standard"), ("arnoldcoreshaders.standard.", "standard"),
                     ("arnold.standard.", "standard")):
        if key in p:
            return fam
    return None


# ---------------------------------------------------------------- values ---------------------------------
def _num(params, name, default=None):
    v = params.get(name, default)
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else default


def _rgb(params, name):
    v = params.get(name)
    if isinstance(v, dict) and all(k in v for k in ("red", "green", "blue")):
        return (float(v["red"]), float(v["green"]), float(v["blue"]))
    return None


def _flag(params, name, default=False):
    v = params.get(name, default)
    return bool(v) if isinstance(v, (bool, int)) else default


def _scaled(c, k):
    return None if c is None or k is None else tuple(x * k for x in c)


def principled_values(fam, p):
    """{Principled BSDF input: value} for a supported surface shader (spec section 2)."""
    out = {}
    if fam in ("phong", "blinn", "lambert"):
        out["Base Color"] = _rgb(p, "diffuse") if _flag(p, "diffuse_inuse", True) else (0.0, 0.0, 0.0)
        if fam == "lambert" or not _flag(p, "specular_inuse", True):
            out["Specular IOR Level"] = 0.0
        else:
            out["Specular Tint"] = _rgb(p, "specular")
            out["Specular IOR Level"] = 0.5
            shiny = _num(p, "shiny")
            out["Roughness"] = (2.0 / (shiny + 2.0)) ** 0.5 if fam == "phong" and shiny is not None and shiny > -2 \
                else _num(p, "roughness")
        refl = _rgb(p, "reflectivity")
        if _flag(p, "reflect_inuse") and refl and max(refl) > 0:
            out["Coat Weight"] = max(refl)
            out["Coat Roughness"] = _num(p, "reflect_glossy")
        trans = _rgb(p, "transparency")
        if _flag(p, "refract_inuse") and trans and max(trans) > 0:
            out["Transmission Weight"] = max(trans)
            out["IOR"] = _num(p, "index_of_refraction")
        if _flag(p, "incand_inuse"):
            inc, k = _rgb(p, "incandescence"), _num(p, "inc_inten", 0.0)
            if inc and k:
                out["Emission Color"] = inc
                out["Emission Strength"] = k
    elif fam == "architectural":
        out["Base Color"] = _scaled(_rgb(p, "diffuse"), _num(p, "diffuse_weight", 1.0))
        out["Specular Tint"] = _rgb(p, "refl_color")
        refl = _num(p, "reflectivity")
        out["Specular IOR Level"] = None if refl is None else 0.5 * refl
        gloss = _num(p, "refl_gloss")
        out["Roughness"] = None if gloss is None else 1.0 - gloss
        out["Metallic"] = 1.0 if _flag(p, "refl_is_metal") else 0.0
        out["Transmission Weight"] = _num(p, "transparency")
        out["IOR"] = _num(p, "refr_ior")
        out["Alpha"] = _num(p, "cutout_opacity")
        base = _num(p, "refl_base")
        if base:
            out["Coat Weight"] = base
            bg = _num(p, "refl_base_gloss")
            out["Coat Roughness"] = None if bg is None else 1.0 - bg
            out["Coat Tint"] = _rgb(p, "refl_base_color")
        add = _rgb(p, "additional_color")
        if add and max(add) > 0:
            out["Emission Color"] = add
            out["Emission Strength"] = 1.0
    elif fam == "standard":
        out["Base Color"] = _scaled(_rgb(p, "Kd_color"), _num(p, "Kd"))
        out["Specular Tint"] = _rgb(p, "Ks_color")
        ks = _num(p, "Ks")
        out["Specular IOR Level"] = None if ks is None else 0.5 * ks
        out["Roughness"] = _num(p, "specular_roughness")
        out["Coat Weight"] = _num(p, "Kr")
        out["Transmission Weight"] = _num(p, "Kt")
        out["IOR"] = _num(p, "IOR")
        em = _num(p, "emission")
        if em:
            out["Emission Color"] = _rgb(p, "emission_color")
            out["Emission Strength"] = em
        op = _rgb(p, "opacity")
        out["Alpha"] = None if op is None else sum(op) / 3.0
    elif fam == "standard_surface":
        out["Base Color"] = _scaled(_rgb(p, "base_color"), _num(p, "base"))
        out["Metallic"] = _num(p, "metalness")
        out["Specular Tint"] = _rgb(p, "specular_color")
        sp = _num(p, "specular")
        out["Specular IOR Level"] = None if sp is None else 0.5 * sp
        out["Roughness"] = _num(p, "specular_roughness")
        out["IOR"] = _num(p, "specular_IOR")
        out["Transmission Weight"] = _num(p, "transmission")
        out["Coat Weight"] = _num(p, "coat")
        out["Coat Roughness"] = _num(p, "coat_roughness")
        out["Subsurface Weight"] = _num(p, "subsurface")
        em = _num(p, "emission")
        if em:
            out["Emission Color"] = _rgb(p, "emission_color")
            out["Emission Strength"] = em
        op = _rgb(p, "opacity")
        out["Alpha"] = None if op is None else sum(op) / 3.0
    return {k: v for k, v in out.items() if v is not None}


def _set(node, name, value):
    sock = node.inputs.get(name)
    if sock is None:
        return
    if isinstance(value, tuple) and hasattr(sock.default_value, "__len__"):
        n = len(sock.default_value)
        sock.default_value = (tuple(value) + (1.0,))[:n] if n == 4 else tuple(value)[:n]
    else:
        sock.default_value = value


# ---------------------------------------------------------------- images ---------------------------------
def project_folder(scene_path):
    """The Softimage project of a scene: the folder above its `Scenes` folder (or the scene's folder)."""
    d = os.path.dirname(os.path.abspath(scene_path))
    cur = d
    while True:
        if os.path.basename(cur).lower() == "scenes":
            return os.path.dirname(cur)
        parent = os.path.dirname(cur)
        if parent == cur:
            return d
        cur = parent


def resolve_image(paths, scene_path):
    """(existing file or None, the path to show when missing). Stored paths first: `[Project Path]` and
    relative paths are taken from the project; a missing file is also looked for in <project>/Pictures."""
    proj = project_folder(scene_path)
    tried = []
    for p in paths:
        q = re.sub(r"(?i)\[project path\]", lambda _m: proj, p)
        if "$" in q or ("[" in q and "]" in q):
            tried.append(p)
            continue
        if not os.path.isabs(q):
            q = os.path.join(proj, q)
        tried.append(q)
        if os.path.isfile(q):
            return q, q
    for p in paths:
        q = os.path.join(proj, "Pictures", re.split(r"[\\/]", p)[-1])
        if os.path.isfile(q):
            return q, q
    return None, (tried[0] if tried else "")


# ---------------------------------------------------------------- materials ------------------------------
def _connected_nodes(shader, seen=None):
    """ProgIDs of every node connected (directly or not) to shader's parameters."""
    seen = set() if seen is None else seen
    out = []

    def walk(v):
        if isinstance(v, scn_materials.Link):
            s = v.shader
            if id(s) not in seen:
                seen.add(id(s))
                out.append(s)
                for x in s.params.values():
                    walk(x)
        elif isinstance(v, dict):
            for x in v.values():
                walk(x)
    for x in shader.params.values():
        walk(x)
    return out


class Builder:
    def __init__(self, sc, report):
        self.sc = sc
        self.report = report
        self.made = {}             # material key -> bpy material
        self.tree_notes = 0        # materials with render tree nodes not converted
        self.uv_of = {}            # material key -> UV map name wanted by its image node

    def material(self, key):
        if key in self.made:
            return self.made[key]
        lib, _, name = key.partition(".")
        mat = bpy.data.materials.new(name or key)
        mat["si_library"] = lib
        mat.use_nodes = True
        nt = mat.node_tree
        for n in list(nt.nodes):
            nt.nodes.remove(n)
        out = nt.nodes.new("ShaderNodeOutputMaterial")
        out.location = (400, 0)
        notes = []
        m = self.sc.materials.get(key)
        surf = m.ports.get("surface") if m is not None else None
        fam = family(surf.progid) if surf is not None else None
        if m is None:
            notes.append("material not found in the scene's libraries")
        elif surf is None:
            notes.append("no surface shader")
        if surf is not None:
            mat["si_shader"] = surf.progid
        if fam in ("constant", "incandescent"):
            em = nt.nodes.new("ShaderNodeEmission")
            p = surf.params
            if fam == "constant":
                _set(em, "Color", _rgb(p, "color") or (0.8, 0.8, 0.8))
                _set(em, "Strength", 1.0)
            else:
                _set(em, "Color", _rgb(p, "color") or (1.0, 1.0, 1.0))
                _set(em, "Strength", _num(p, "intensity", 1.0))
            nt.links.new(em.outputs[0], out.inputs["Surface"])
            mat.diffuse_color = tuple(em.inputs["Color"].default_value)
        else:
            bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
            nt.links.new(bsdf.outputs[0], out.inputs["Surface"])
            if fam is not None:
                for k, v in principled_values(fam, surf.params).items():
                    _set(bsdf, k, v)
                mat.diffuse_color = tuple(bsdf.inputs["Base Color"].default_value)
                self._image(mat, bsdf, surf, fam, notes)
            elif surf is not None:
                notes.append("surface shader %s not supported" % surf.progid)
                self.report({'WARNING'}, "Material %s: surface shader %s is not supported (imported as a plain "
                                         "material)" % (mat.name, surf.progid))
        if surf is not None and fam is not None:
            other = [s for s in _connected_nodes(surf) if s.progid not in IMAGE_NODES or not self._is_main_image(surf, fam, s)]
            if other:
                notes.append("render tree nodes not converted: %s" % ", ".join(sorted({s.progid for s in other})))
                self.tree_notes += 1
        if notes:
            mat["si_import_notes"] = "; ".join(notes)
        self.made[key] = mat
        return mat

    def _main_link(self, surf, fam):
        v = surf.params.get(COLOUR_INPUT.get(fam, ""))
        return v if isinstance(v, scn_materials.Link) else None

    def _is_main_image(self, surf, fam, s):
        link = self._main_link(surf, fam)
        return link is not None and link.shader is s

    def _image(self, mat, bsdf, surf, fam, notes):
        link = self._main_link(surf, fam)
        if link is None or link.shader.progid not in IMAGE_NODES:
            return
        img_shader = link.shader
        nt = mat.node_tree
        tex = nt.nodes.new("ShaderNodeTexImage")
        tex.location = (-400, 0)
        nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
        name, paths = (None, [])
        if img_shader.clip is not None:
            name, paths = scn_materials.clip_paths(self.sc.cfb, img_shader.clip)
        found, shown = resolve_image(paths, self.sc.path)
        if found:
            tex.image = bpy.data.images.load(found, check_existing=True)
        else:
            img = bpy.data.images.new(name or "missing", 8, 8)
            img.source = 'FILE'
            img.filepath = shown
            tex.image = img
            notes.append("image file missing: %s" % shown)
            self.report({'WARNING'}, "Material %s: image file missing: %s" % (mat.name, shown))
        uvn = nt.nodes.new("ShaderNodeUVMap")
        uvn.location = (-650, 0)
        tspace = img_shader.params.get("tspace_id")
        uvn.uv_map = tspace if isinstance(tspace, str) else ""
        nt.links.new(uvn.outputs["UV"], tex.inputs["Vector"])

    def assign(self, so, ob):
        if ob.type != 'MESH' or not so.material:
            return
        me = ob.data
        keys = [so.material] + [c.material for c in so.cluster_materials]
        slot = {}
        for k in keys:
            if k not in slot:
                me.materials.append(self.material(k))
                slot[k] = len(me.materials) - 1
        npolys = len(me.polygons)
        for c in so.cluster_materials:
            for i in c.polygons:
                if 0 <= i < npolys:
                    me.polygons[i].material_index = slot[c.material]


def add_uvs(so, ob):
    """UV maps from the texture projections of a frozen mesh (corner order = Mesh.polygons order)."""
    sets = getattr(so, "uvs", None)
    if not sets or ob.type != 'MESH' or so.mesh is None:
        return
    me = ob.data
    nloops = len(me.loops)
    for u in sets:
        if len(u.corners) != nloops:
            continue
        lay = me.uv_layers.new(name=u.name)
        flat = [c for uv in u.corners for c in uv]
        lay.data.foreach_set("uv", flat)
    if me.uv_layers:
        me.uv_layers.active_index = 0


def apply(sc, made, report):
    """Materials, UVs and image textures for the objects just built (made: {id(SceneObject): bpy object})."""
    rep = report or (lambda kind, msg: None)
    b = Builder(sc, rep)
    for so in sc.objects:
        ob = made.get(id(so))
        if ob is None or so.kind != "polymsh":
            continue
        add_uvs(so, ob)
        b.assign(so, ob)
    if b.tree_notes:
        rep({'WARNING'}, "%d material(s) have render tree nodes that were not converted (see each material's "
                         "si_import_notes)" % b.tree_notes)
    return b.made
