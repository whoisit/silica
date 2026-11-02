# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Alex Doss
"""si.import_scn against the private scene corpus (skipped when it is absent)."""
import importlib
import os

import bpy
from mathutils import Vector

KIT = None  # set by run.py
CORPUS = os.path.abspath(os.environ.get("SI_SCN_CORPUS", os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "si-blender", "reference", "scn_project", "Scenes")))


def _m(name):
    return importlib.import_module(KIT + "." + name)


def _have(name):
    return os.path.isfile(os.path.join(CORPUS, name + ".scn"))


def _import(name):
    mode = _m("mode")
    if not mode.is_on():
        mode.enter_mode()
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o)
    r = bpy.ops.si.import_scn(filepath=os.path.join(CORPUS, name + ".scn"))
    assert r == {'FINISHED'}, r
    bpy.context.view_layer.update()
    return bpy.data.objects


def test_names_and_parents():
    if not _have("null_parented"):
        return
    obs = _import("null_parented")
    for n in ("Camera_Root", "Camera", "Camera_Interest", "light", "n1", "n2"):
        assert n in obs, (n, list(obs.keys()))
    assert obs["n2"].parent == obs["n1"]
    assert obs["n1"].parent is None and obs["Camera_Root"].parent is None  # Scene_Root model is not exposed
    assert obs["Camera"].parent == obs["Camera_Root"]
    assert obs["Camera"].type == 'CAMERA' and obs["light"].type == 'LIGHT'
    assert obs["n1"].type == 'EMPTY'


def test_translation_axis_conversion():
    if not _have("null_pos123"):
        return
    obs = _import("null_pos123")
    p = obs["n1"].matrix_world.translation
    # Softimage (1, 2, 3) -> Blender (x, -z, y) = (1, -3, 2)
    assert abs(p.x - 1) < 1e-5 and abs(p.y + 3) < 1e-5 and abs(p.z - 2) < 1e-5, tuple(p)


def test_camera_world_position_and_direction():
    if not _have("camera"):
        return
    obs = _import("camera")
    cam = obs["Camera"]
    p = cam.matrix_world.translation
    assert abs(p.x) < 1e-5 and abs(p.y + 20) < 1e-5 and abs(p.z - 2) < 1e-5, tuple(p)
    # the camera is aimed at the interest at the origin; Blender cameras look down their local -Z
    d = cam.matrix_world.to_quaternion() @ Vector((0, 0, -1))
    want = (-p).normalized()
    assert (d - want).length < 1e-4, (tuple(d), tuple(want))


def test_mesh_counts():
    for name, npts, npolys in (("cube_frozen", 8, 6), ("grid_3x2", 12, 6)):
        if not _have(name):
            continue
        meshes = [o for o in _import(name).values() if o.type == 'MESH']
        assert len(meshes) == 1, (name, meshes)
        me = meshes[0].data
        assert (len(me.vertices), len(me.polygons)) == (npts, npolys), (name, len(me.vertices), len(me.polygons))


def test_mesh_fan_matches_reader():
    if not _have("mesh_fan"):
        return
    sc = _m("io_scn.scene").read(os.path.join(CORPUS, "mesh_fan.scn"))
    want = [o for o in sc.objects if o.mesh is not None][0]
    got = [o for o in _import("mesh_fan").values() if o.type == 'MESH'][0]
    assert got.name == want.name
    assert len(got.data.vertices) == len(want.mesh.points)
    assert len(got.data.polygons) == len(want.mesh.polygons)
    assert sorted(len(p.vertices) for p in got.data.polygons) == sorted(len(f) for f in want.mesh.polygons)


# Live primitives whose shape Blender can build exactly (prim_<kind>.scn: <kind>_def has Softimage's defaults,
# <kind>_set distinctive values; see gen_scn_corpus.py).
EXACT = ("cube_def", "cube_set", "sphere_def", "sphere_set", "grid_def", "grid_set", "cylinder_def", "cone_def", "torus_def",
         "disc_def", "tetrahedron_def", "octahedron_def", "icosahedron_def", "dodecahedron_def", "dodecahedron_set")


def _evaluated(ob):
    deps = bpy.context.evaluated_depsgraph_get()
    me = ob.evaluated_get(deps).to_mesh()
    pts = sorted(tuple(round(c, 3) + 0.0 for c in v.co) for v in me.vertices)
    n = len(me.polygons)
    ob.evaluated_get(deps).to_mesh_clear()
    return pts, n


def test_live_primitives_rebuilt():
    """A live primitive comes back as a mesh with Softimage's shape: same points (in Blender axes) and polygon
    count. What Blender can't build yet stays the live primitive with its values, plus a note on the object."""
    kinds = sorted({n.split("_")[0] for n in EXACT} | {"disc"})
    for kind in kinds:
        case = "prim_" + kind
        if not _have(case):
            continue
        import json
        truth = {o["name"]: o for o in json.load(open(os.path.join(CORPUS, case + ".json")))["objects"]}
        obs = _import(case)
        for name in (kind + "_def", kind + "_set"):
            ob = obs[name]
            assert ob.type == 'MESH', (name, ob.type)
            if name not in EXACT:
                assert ob.get("si_import_notes"), (name, "a shape we can't build yet needs a note")
                continue
            t = truth[name]["mesh"]
            want = sorted(tuple(round(c, 3) + 0.0 for c in (x, -z, y)) for x, y, z in t["points"])
            got, npolys = _evaluated(ob)
            assert (len(got), npolys) == (len(want), len(t["polygons"])), (name, len(got), npolys, len(want),
                                                                         len(t["polygons"]))
            worst = max(max(abs(a - b) for a, b in zip(p, q)) for p, q in zip(got, want))
            assert worst < 2e-3, (name, "points differ by", worst)
    if _have("prim_cube"):           # live primitive = the kit's Geometry Nodes primitive with the scene's values
        ob = _import("prim_cube")["cube_set"]
        gn = _m("ops.gn_primitives")
        mod = gn.live_modifier(ob)
        assert mod is not None
        assert abs(gn.get_param(mod, "Length") - 3.25) < 1e-6
        assert [gn.get_param(mod, "Subdivisions " + k) for k in ("U", "V", "Base")] == [2, 3, 4]
    if _have("prim_cylinder"):       # what can't be rebuilt yet is named on the object
        ob = _import("prim_cylinder")["cylinder_set"]
        assert "angle" in ob["si_import_notes"], ob["si_import_notes"]


# ---------------------------------------------------------------- materials, UVs, images -----------------
# Spec io.scn-materials, criteria 3-10. Truth: <case>.mat.json next to the corpus scenes and the Softimage dumps
# of the SItoA / real scenes (tools/sicapture/softimage/dump_materials_truth.py).
REF = os.path.dirname(os.path.dirname(CORPUS))
SITOA = os.path.join(REF, "sitoa", "testsuite", "XSIProject", "Scenes")
def _real_dir():
    """Private real-world scenes: $SI_SCN_REAL, else the path in reference/real_scenes_path.txt (git-ignored)."""
    if os.environ.get("SI_SCN_REAL"):
        return os.environ["SI_SCN_REAL"]
    p = os.path.join(REF, "real_scenes_path.txt")
    return open(p, encoding="utf-8").readline().strip() if os.path.isfile(p) else ""


REAL = _real_dir()
DUMPS = {"sitoa": os.path.join(REF, "sitoa_truth_mat"), "real": os.path.join(REF, "xsi_rd_truth_mat")}


def _clean():
    for coll in (bpy.data.objects, bpy.data.meshes, bpy.data.materials, bpy.data.images):
        for x in list(coll):
            coll.remove(x)


def _build(path):
    """Import with the importer's build() directly, collecting its report lines."""
    mode = _m("mode")
    if not mode.is_on():
        mode.enter_mode()
    _clean()
    reports = []
    sc = _m("io_scn.scene").read(path)
    objs = _m("ops.import_scn").build(bpy.context, sc, lambda kind, msg: reports.append(msg))
    bpy.context.view_layer.update()
    return objs, reports


def _truth(case):
    import json
    return json.load(open(os.path.join(CORPUS, case + ".mat.json")))


def _mat(key):
    """Blender material imported for Softimage material '<Library>.<Name>'."""
    lib, name = key.split(".", 1)
    for m in bpy.data.materials:
        if m.get("si_library") == lib and (m.name == name or m.name.rsplit(".", 1)[0] == name):
            return m
    raise AssertionError("no material for %s (have %s)" % (
        key, [(m.name, m.get("si_library")) for m in bpy.data.materials]))


def _bsdf(m):
    nodes = [n for n in m.node_tree.nodes if n.bl_idname == 'ShaderNodeBsdfPrincipled']
    assert len(nodes) == 1, (m.name, [n.bl_idname for n in m.node_tree.nodes])
    return nodes[0]


def _in(node, name):
    v = node.inputs[name].default_value
    return tuple(v) if hasattr(v, "__len__") else v


def _near(a, b, eps=1e-4):
    if isinstance(a, tuple) or isinstance(b, (tuple, list)):
        return all(abs(x - y) <= eps for x, y in zip(a, b))
    return abs(a - b) <= eps


def test_materials_shared_inherited_default_unused():
    """C3, C4: one Blender material per used Softimage material, shared like in Softimage; inherited and default
    materials assigned directly; unused library materials not imported."""
    if not _have("mat_shared"):
        return
    objs, _ = _build(os.path.join(CORPUS, "mat_shared.scn"))
    a, b, d = objs["cubeA"], objs["cubeB"], objs["cubeDefault"]
    assert a.material_slots[0].material is b.material_slots[0].material is _mat("DefaultLib.SharedMat")
    assert d.material_slots[0].material is _mat("DefaultLib.Scene_Material")
    used = {o.get("material") for o in _truth("mat_shared")["objects"] if o["type"] == "polymsh"}
    assert len(bpy.data.materials) == len(used), ([m.name for m in bpy.data.materials], used)
    if _have("mat_inherit"):
        objs, _ = _build(os.path.join(CORPUS, "mat_inherit.scn"))
        assert objs["child1"].material_slots[0].material is _mat("DefaultLib.BranchMat")
    if _have("mat_two_libs"):
        _build(os.path.join(CORPUS, "mat_two_libs.scn"))
        libs = sorted(m.get("si_library") for m in bpy.data.materials if m.name.startswith("Material"))
        assert libs == ["DefaultLib", "SecondLib"], libs


def test_cluster_materials():
    """C4: object material in slot 1, a polygon cluster's material in another slot on exactly its polygons."""
    if not _have("mat_cluster"):
        return
    t = [o for o in _truth("mat_cluster")["objects"] if o["type"] == "polymsh"][0]
    objs, _ = _build(os.path.join(CORPUS, "mat_cluster.scn"))
    ob = objs[t["full"]]
    assert ob.material_slots[0].material is _mat(t["material"])
    c = t["poly_materials"][0]
    idx = [i for i, s in enumerate(ob.material_slots) if s.material is _mat(c["material"])]
    assert len(idx) == 1, [s.material for s in ob.material_slots]
    got = sorted(p.index for p in ob.data.polygons if p.material_index == idx[0])
    assert got == sorted(c["elements"]), (got, c["elements"])


def test_softimage_shader_values():
    """C5: Phong / Lambert / Blinn / Constant values (corpus cases with distinctive values)."""
    if _have("mat_phong"):
        _build(os.path.join(CORPUS, "mat_phong.scn"))
        n = _bsdf(_mat("DefaultLib.Material"))
        assert _near(_in(n, "Base Color")[:3], (0.2, 0.4, 0.6))
        assert _near(_in(n, "Specular Tint")[:3], (0.9, 0.8, 0.7))
        assert _near(_in(n, "Specular IOR Level"), 0.5)
        assert _near(_in(n, "Roughness"), (2.0 / (33.0 + 2.0)) ** 0.5)
        assert _near(_in(n, "Coat Weight"), 0.25) and _near(_in(n, "Coat Roughness"), 0.3)
        assert _near(_in(n, "Transmission Weight"), 0.3) and _near(_in(n, "IOR"), 1.33)
        assert _near(_in(n, "Emission Color")[:3], (0.1, 0.05, 0.0)) and _near(_in(n, "Emission Strength"), 2.0)
    if _have("mat_lambert"):
        _build(os.path.join(CORPUS, "mat_lambert.scn"))
        n = _bsdf(_mat("DefaultLib.Material"))
        assert _near(_in(n, "Base Color")[:3], (0.7, 0.3, 0.1)) and _near(_in(n, "Specular IOR Level"), 0.0)
    if _have("mat_blinn"):
        _build(os.path.join(CORPUS, "mat_blinn.scn"))
        n = _bsdf(_mat("DefaultLib.Material"))
        assert _near(_in(n, "Base Color")[:3], (0.1, 0.6, 0.2))
        assert _near(_in(n, "Specular Tint")[:3], (0.5, 0.5, 0.9))
    if _have("mat_constant"):
        _build(os.path.join(CORPUS, "mat_constant.scn"))
        m = _mat("DefaultLib.Material")
        em = [x for x in m.node_tree.nodes if x.bl_idname == 'ShaderNodeEmission']
        assert len(em) == 1 and _near(_in(em[0], "Color")[:3], (0.9, 0.2, 0.3)) and _near(_in(em[0], "Strength"), 1.0)


def _dump_files():
    import glob
    out = []
    for which, folder in DUMPS.items():
        for f in sorted(glob.glob(os.path.join(folder, "*.json"))):
            tag = os.path.basename(f)[:-5]
            scn = (os.path.join(SITOA, tag, "data", "test.scn") if which == "sitoa"
                   else os.path.join(REAL, tag + ".scn"))
            if os.path.exists(scn):
                out.append((os.path.getsize(scn), scn, f))
    return [(s, f) for _, s, f in sorted(out)]   # smallest scenes first


def _find(pred):
    """First (scene, truth, material key, surface shader record) in the dumps where pred(shader, truth) holds,
    for a material used by a mesh; smallest scene first."""
    import json
    for scn, f in _dump_files():
        t = json.load(open(f))
        mats = {m["key"]: m for m in t["materials"]}
        for key in [o.get("material") for o in t["objects"] if o["type"] == "polymsh"]:
            s = mats.get(key, {}).get("ports", {}).get("surface")
            if s and pred(t["shaders"][s], t):
                return scn, t, key, t["shaders"][s]
    return None


def _v(p, k):
    """Plain value of a truth parameter (None when it is connected)."""
    x = p[k]
    return None if isinstance(x, dict) and "from" in x else x


def _rgb(p, k):
    x = _v(p, k)
    return None if x is None else (x["red"], x["green"], x["blue"])


def test_redshift_and_arnold_values():
    """C5: one material of each Redshift / Arnold family from the dumps; values follow the spec's table."""
    def check(progid, fn):
        hit = _find(lambda s, t: s["progid"] == progid)
        if hit is None:
            return
        scn, t, key, s = hit
        _build(scn)
        fn(_mat(key), s["params"])

    def arch(m, p):
        n = _bsdf(m)
        if _rgb(p, "diffuse") and _v(p, "diffuse_weight") is not None:
            assert _near(_in(n, "Base Color")[:3], tuple(c * p["diffuse_weight"] for c in _rgb(p, "diffuse")))
        assert _near(_in(n, "Transmission Weight"), p["transparency"]) and _near(_in(n, "IOR"), p["refr_ior"])
        assert _near(_in(n, "Alpha"), p["cutout_opacity"]) and _near(_in(n, "Roughness"), 1.0 - p["refl_gloss"])
        assert _near(_in(n, "Metallic"), 1.0 if p["refl_is_metal"] else 0.0)

    def incand(m, p):
        em = [x for x in m.node_tree.nodes if x.bl_idname == 'ShaderNodeEmission']
        assert len(em) == 1
        if _rgb(p, "color"):
            assert _near(_in(em[0], "Color")[:3], _rgb(p, "color"))
        assert _near(_in(em[0], "Strength"), p["intensity"])

    def std(m, p):
        n = _bsdf(m)
        if _rgb(p, "Kd_color") and _v(p, "Kd") is not None:
            assert _near(_in(n, "Base Color")[:3], tuple(c * p["Kd"] for c in _rgb(p, "Kd_color")))
        assert _near(_in(n, "Roughness"), p["specular_roughness"]) and _near(_in(n, "Transmission Weight"), p["Kt"])
        assert _near(_in(n, "IOR"), p["IOR"])

    def surf(m, p):
        n = _bsdf(m)
        if _rgb(p, "base_color") and _v(p, "base") is not None:
            assert _near(_in(n, "Base Color")[:3], tuple(c * p["base"] for c in _rgb(p, "base_color")))
        assert _near(_in(n, "Metallic"), p["metalness"]) and _near(_in(n, "Roughness"), p["specular_roughness"])
        assert _near(_in(n, "Transmission Weight"), p["transmission"]) and _near(_in(n, "IOR"), p["specular_IOR"])
        assert _near(_in(n, "Coat Weight"), p["coat"])

    check("Redshift.material-architectural.1.0", arch)
    check("Redshift.material-incandescent.1.0", incand)
    check("Softimage.standard.1.0", std)
    check("ArnoldCoreShaders.standard.1.0", std)
    check("Arnold.standard_surface.1.0", surf)


def test_unsupported_surface_reported():
    """C6: an unsupported surface shader gives a named material, a report line naming material and shader, and
    a si_import_notes entry."""
    hit = _find(lambda s, t: s["progid"] == "Arnold.utility.1.0")
    if hit is None:
        return
    scn, t, key, s = hit
    _, reports = _build(scn)
    m = _mat(key)
    assert "Arnold.utility" in m.get("si_import_notes", ""), dict(m)
    assert any(m.name in r and "Arnold.utility" in r for r in reports), reports


def test_uv_maps():
    """C7: every texture projection becomes a UV map of the same name with Softimage's per-corner values."""
    for case in ("mat_uv", "mat_uv2"):
        if not _have(case):
            continue
        t = [o for o in _truth(case)["objects"] if o["type"] == "polymsh"][0]
        objs, _ = _build(os.path.join(CORPUS, case + ".scn"))
        me = objs[t["full"]].data
        want = [s for s in t["samples"] if s["type"] == "uvspace"]
        assert [u.name for u in me.uv_layers] == [s["name"] for s in want], ([u.name for u in me.uv_layers], want)
        for s in want:
            lay = me.uv_layers[s["name"]]
            i = 0
            for poly, pw in zip(me.polygons, t["polygons"]):
                w = dict(zip(pw, s["corners"][i:i + len(pw)]))
                for li in poly.loop_indices:
                    uv = lay.data[li].uv
                    u0, v0 = w[me.loops[li].vertex_index]
                    assert abs(uv[0] - u0) < 1e-5 and abs(uv[1] - v0) < 1e-5, (case, s["name"], tuple(uv), (u0, v0))
                i += len(pw)


MAIN_COLOUR = (("material-phong", "diffuse"), ("material-lambert", "diffuse"), ("material-blinn", "diffuse"),
               ("material-architectural", "diffuse"), ("Softimage.standard.", "Kd_color"),
               ("ArnoldCoreShaders.standard.", "Kd_color"), ("standard_surface", "base_color"))


def _image_on_colour(s, t):
    """A supported surface shader whose main colour is fed straight by an image node."""
    for fam, k in MAIN_COLOUR:
        x = s["params"].get(k)
        if fam in s["progid"] and isinstance(x, dict) and "from" in x \
                and "image-explicit" in t["shaders"][x["from"]]["progid"]:
            return True
    return False


def test_image_texture():
    """C8: an image on the main colour becomes an Image Texture on Base Color with a UV Map node; relative /
    Pictures paths resolve; a missing file is reported by material and path."""
    if _have("mat_image"):
        _build(os.path.join(CORPUS, "mat_image.scn"))
        m = _mat("DefaultLib.Material")
        tex = [n for n in m.node_tree.nodes if n.bl_idname == 'ShaderNodeTexImage']
        assert len(tex) == 1 and tex[0].image is not None
        assert os.path.normcase(os.path.abspath(bpy.path.abspath(tex[0].image.filepath))) == os.path.normcase(
            os.path.join(os.path.dirname(CORPUS), "Pictures", "mat_tex.png")), tex[0].image.filepath
        assert any(lk.to_node.bl_idname == 'ShaderNodeBsdfPrincipled' and lk.to_socket.name == "Base Color"
                   for lk in tex[0].outputs["Color"].links)
        uvn = [lk.from_node for lk in tex[0].inputs["Vector"].links]
        assert uvn and uvn[0].bl_idname == 'ShaderNodeUVMap' and uvn[0].uv_map == "Texture_Projection"
    # SItoA scenes store "[project path]\Pictures\..." (and an absolute path from the machine that saved them);
    # none of them feeds an image straight into a main colour, so resolve their image clips directly.
    scn = os.path.join(SITOA, "test_0049", "data", "test.scn")
    if os.path.exists(scn):
        sc = _m("io_scn.scene").read(scn)
        mats, imp = _m("io_scn.materials"), _m("ops.import_materials")
        clips = [s.clip for s in sc.shaders.values() if s.clip is not None]
        assert clips
        for h in clips:
            _name, paths = mats.clip_paths(sc.cfb, h)
            found, _shown = imp.resolve_image(paths, scn)
            assert found and os.path.isfile(found) and "XSIProject" in found, (paths, found)
    hit = _find(lambda s, t: _image_on_colour(s, t) and "XSI_RD" in t["scene"])
    if hit:   # the user's scenes mostly point at files that are not on this machine
        _, reports = _build(hit[0])
        m = _mat(hit[2])
        tex = [n for n in m.node_tree.nodes if n.bl_idname == 'ShaderNodeTexImage']
        assert tex
        if not os.path.exists(bpy.path.abspath(tex[0].image.filepath)):
            assert any(m.name in r and "missing" in r.lower() for r in reports), reports


def test_render_tree_nodes_noted():
    """C9: render tree nodes that are not converted are named in the summary report and the material notes."""
    def other_nodes(s, t):
        return any(isinstance(x, dict) and "from" in x and "image-explicit" not in t["shaders"][x["from"]]["progid"]
                   for x in s["params"].values())
    hit = _find(lambda s, t: s["progid"] in ("Softimage.material-phong.1.0", "Softimage.standard.1.0",
                                             "Redshift.material-architectural.1.0") and other_nodes(s, t))
    if hit is None:
        return
    scn, t, key, s = hit
    _, reports = _build(scn)
    notes = _mat(key).get("si_import_notes", "")
    srcs = {t["shaders"][x["from"]]["progid"] for x in s["params"].values() if isinstance(x, dict) and "from" in x}
    assert any(p in notes for p in srcs), (notes, srcs)
    assert any("render tree" in r.lower() for r in reports), reports


def test_import_is_one_undo_step():
    """C10: the importer stays a single undoable operator."""
    assert 'UNDO' in _m("ops.import_scn").SI_OT_import_scn.bl_options


def test_cameras_and_lights():
    """Camera and light settings from the scene (corpus cam_* / light_*: one distinctive value per setting).
    Light power follows Get > Primitive: Softimage's default intensity 0.75 = the kit's default power."""
    from math import radians
    near = lambda a, b, eps=1e-4: abs(a - b) < eps  # noqa: E731
    if _have("cam_set"):
        cam = _import("cam_set")["cam1"].data
        assert cam.type == 'PERSP' and cam.sensor_fit == 'VERTICAL', (cam.type, cam.sensor_fit)
        assert near(cam.angle_y, radians(41.25)), cam.angle_y
        assert near(cam.clip_start, 0.375) and near(cam.clip_end, 512.5), (cam.clip_start, cam.clip_end)
    if _have("cam_ortho"):
        import json
        want = [o for o in json.load(open(os.path.join(CORPUS, "cam_ortho.json")))["objects"]
                if o["name"] == "cam1"][0]["prim_params"]["orthoheight"]     # Softimage's own value
        cam = _import("cam_ortho")["cam1"].data
        assert cam.type == 'ORTHO' and near(cam.ortho_scale, want), (cam.type, cam.ortho_scale, want)
    power = _m("ops.primitives").LIGHT_POWER
    if _have("light_point_set"):
        lt = _import("light_point_set")["lp"].data
        assert lt.type == 'POINT' and lt.use_shadow
        assert all(near(a, b) for a, b in zip(lt.color, (0.9, 0.45, 0.2))), tuple(lt.color)
        assert near(lt.energy, power['POINT'] * 1.625 / 0.75, 1e-2), lt.energy
    if _have("light_spot_set"):
        obs = _import("light_spot_set")
        ob = obs["ls"]
        lt = ob.data
        assert lt.type == 'SPOT' and near(lt.spot_size, radians(45.5)), (lt.type, lt.spot_size)
        assert near(lt.spot_blend, 7.5 / 45.5, 1e-3), lt.spot_blend
        assert near(lt.energy, power['SPOT'] * 2.25 / 0.75, 1e-2), lt.energy
        d = ob.matrix_world.to_quaternion() @ Vector((0, 0, -1))          # lights shine down local -Z
        want = (obs["ls_Interest"].matrix_world.translation - ob.matrix_world.translation).normalized()
        assert (d - want).length < 1e-3, (tuple(d), tuple(want))
    if _have("light_inf_set"):
        assert _import("light_inf_set")["li"].data.type == 'SUN'


def test_operators_on_meshes():
    """Point moves on a live primitive are replayed (a plain mesh in Softimage's point order with Softimage's
    final points); what can't be replayed or applied is named in the object's note."""
    import json
    if _have("mc_cube_two"):
        ob = _import("mc_cube_two")["cube1"]
        gn = _m("ops.gn_primitives")
        assert ob.type == 'MESH' and gn.live_modifier(ob) is None, "moved primitive should be a plain mesh"
        t = [o for o in json.load(open(os.path.join(CORPUS, "mc_cube_two.json")))["objects"] if o["name"] == "cube1"][0]
        want = [(x, -z, y) for x, y, z in t["mesh"]["points"]]
        got = [tuple(v.co) for v in ob.data.vertices]
        assert len(got) == len(want) and all((Vector(a) - Vector(b)).length < 1e-5 for a, b in zip(got, want)), got
        assert not ob.get("si_import_notes"), ob.get("si_import_notes")
    if _have("mc_grid_edge"):
        ob = _import("mc_grid_edge")["grid1"]
        assert "edge" in ob.get("si_import_notes", ""), ob.get("si_import_notes")
    if _have("ops_frozen_bend"):
        ob = _import("ops_frozen_bend")["grid1"]
        assert ob.type == 'MESH' and len(ob.data.vertices) == 25
        assert "bendop" in ob.get("si_import_notes", ""), ob.get("si_import_notes")
