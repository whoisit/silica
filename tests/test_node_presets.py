# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Alex Doss
"""Render Tree preset panel logic (spec render.render-tree-presets): catalogue, search, favorites, adding nodes.
Written before the code (tests first)."""
import importlib
import os

import bpy

KIT = None  # set by run.py


def _m(name):
    return importlib.import_module(KIT + "." + name)


def _on():
    mode = _m("mode")
    if not mode.is_on():
        mode.enter_mode()


def _creatable_shader_nodes():
    """Ground truth, independent of the kit: every shader node type Blender lets us create in a material."""
    mat = bpy.data.materials.new("si_test_nodes")
    mat.use_nodes = True
    ok = set()
    for name in dir(bpy.types):
        cls = getattr(bpy.types, name)
        if not isinstance(cls, type) or not issubclass(cls, bpy.types.ShaderNode):
            continue
        idname = getattr(cls, "bl_idname", name)
        if idname in ("ShaderNodeGroup", "ShaderNodeCustomGroup") or not idname.startswith("ShaderNode"):
            continue
        try:
            n = mat.node_tree.nodes.new(idname)
            mat.node_tree.nodes.remove(n)
            ok.add(idname)
        except RuntimeError:
            pass
    bpy.data.materials.remove(mat)
    return ok


def test_every_node_in_exactly_one_category():
    _on()
    np_ = _m("ui.node_presets")
    cat = np_.catalog()
    real = [c for c in cat if c not in ("Favorites", "All Nodes")]
    assert not cat["Other"], "nodes with no Softimage category (fallback 'Other'): %s" % cat["Other"]
    seen = {}
    for c in real:
        for idname, _label in cat[c]:
            assert idname not in seen, "%s in %s and %s" % (idname, seen.get(idname), c)
            seen[idname] = c
    truth = _creatable_shader_nodes()
    missing = sorted(truth - set(seen))
    extra = sorted(set(seen) - truth)
    assert not missing, "shader nodes in no category: %s" % missing
    assert not extra, "catalogue lists nodes Blender can't create: %s" % extra
    assert sorted(i for i, _l in cat["All Nodes"]) == sorted(seen)


def test_softimage_category_names():
    _on()
    np_ = _m("ui.node_presets")
    names = list(np_.catalog())
    assert names[:2] == ["Favorites", "All Nodes"], names[:2]
    for want in ("Illumination", "Texture", "Mixers", "Conversion", "Math", "Image Processing", "Data", "Bump",
                 "Output"):
        assert want in names, want


def test_search():
    _on()
    np_ = _m("ui.node_presets")
    res = np_.search("bsdf")
    assert res and all("bsdf" in label.lower() for _i, label in res), res
    assert np_.search("zzzz-no-such-node") == []
    assert len(np_.search("")) == len(np_.catalog()["All Nodes"])


class _KeepFavorites:
    """Back up the favorites file and put it back afterwards, even when an assert fails."""
    def __init__(self, np_):
        self.np_, self.path = np_, np_.favorites_path()

    def __enter__(self):
        try:
            with open(self.path, "rb") as f:
                self.data = f.read()
        except OSError:
            self.data = None
        self.np_._cache.pop("fav", None)
        return self

    def __exit__(self, *exc):
        if self.data is None:
            if os.path.exists(self.path):
                os.remove(self.path)
        else:
            with open(self.path, "wb") as f:
                f.write(self.data)
        self.np_._cache.pop("fav", None)


def test_favorites_saved_in_user_folder():
    _on()
    np_ = _m("ui.node_presets")
    path = np_.favorites_path()
    assert os.path.dirname(path).startswith(bpy.utils.extension_path_user(np_.ADDON, create=True))
    with _KeepFavorites(np_):
        if "ShaderNodeTexNoise" in np_.favorites():
            np_.toggle_favorite("ShaderNodeTexNoise")
        assert np_.toggle_favorite("ShaderNodeTexNoise") is True
        assert "ShaderNodeTexNoise" in [i for i, _l in np_.catalog()["Favorites"]]
        with open(path, encoding="utf-8") as f:
            assert "ShaderNodeTexNoise" in f.read()
        assert np_.toggle_favorite("ShaderNodeTexNoise") is False
        assert "ShaderNodeTexNoise" not in np_.favorites()
        leftovers = [f for f in os.listdir(os.path.dirname(path)) if f.startswith("node_favorites") and f != "node_favorites.json"]
        assert not leftovers, "temporary files left: %s" % leftovers


def test_bad_favorites_file_is_ignored():
    """A damaged favorites file must not break the panel (an exception there swallowed every click)."""
    _on()
    np_ = _m("ui.node_presets")
    with _KeepFavorites(np_):
        for bad in ("null", "3", '[1, null, "ShaderNodeTexNoise"]', '{"a": 1}', "[", ""):
            with open(np_.favorites_path(), "w", encoding="utf-8") as f:
                f.write(bad)
            np_._cache.pop("fav", None)
            fav = np_.favorites()
            assert all(isinstance(i, str) for i in fav), (bad, fav)
            np_.catalog()


def test_add_node_at_location():
    _on()
    np_ = _m("ui.node_presets")
    mat = bpy.data.materials.new("si_test_add")
    mat.use_nodes = True
    n0 = len(mat.node_tree.nodes)
    node = np_.add_node(mat.node_tree, "ShaderNodeTexNoise", (120.0, -40.0))
    assert node.bl_idname == "ShaderNodeTexNoise" and len(mat.node_tree.nodes) == n0 + 1
    assert abs(node.location.x - 120.0) < 1e-3 and abs(node.location.y + 40.0) < 1e-3
    assert node.select and mat.node_tree.nodes.active == node
    bpy.data.materials.remove(mat)
