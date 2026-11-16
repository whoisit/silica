# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Alex Doss
"""Passes and partitions (spec render.passes): passes = view layers, partitions = collections under `Passes`,
both spaces (Blender / SI) live in the file and the mode switch only switches between them.
Background Blender has no windows: the space switch is tested through its functions."""
import importlib

import bpy

KIT = None  # set by run.py


def _p():
    return importlib.import_module(KIT + ".ops.passes")


def _mode_on():
    mode = importlib.import_module(KIT + ".mode")
    if not mode.is_on():
        mode.enter_mode()


def _scene(name):
    """A fresh scene: user collection Props with two meshes, a light, a camera and a null."""
    sc = bpy.data.scenes.new(name)
    props = bpy.data.collections.new(name + "_Props")
    sc.collection.children.link(props)
    obs = {}
    for n, data in (("cube", bpy.data.meshes.new(name + "c")), ("sphere", bpy.data.meshes.new(name + "s")),
                    ("key", bpy.data.lights.new(name + "k", 'POINT')), ("cam", bpy.data.cameras.new(name + "m")),
                    ("null", None)):
        ob = bpy.data.objects.new(name + "_" + n, data)
        props.objects.link(ob)
        obs[n] = ob
    return sc, props, obs


def _names(coll):
    return {o.name.split("_", 1)[1] for o in coll.objects}


def _lc(vl, coll):
    def walk(lc):
        if lc.collection == coll:
            return lc
        for c in lc.children:
            r = walk(c)
            if r:
                return r
    return walk(vl.layer_collection)


def _exclusive(sc):
    """Every geometry object and light is in exactly one partition of every pass."""
    P = _p()
    for name in P.pass_names(sc):
        parts = P.partitions(sc, name)
        for ob in sc.objects:
            if P.kind(ob) in ("OBJECT", "LIGHT"):
                n = [c.name for c in parts if ob.name in c.objects]
                assert len(n) == 1, (name, ob.name, n)


def _sel(vl, *obs):
    for o in vl.objects:
        o.select_set(False, view_layer=vl)
    for o in obs:
        o.select_set(True, view_layer=vl)


def test_spaces_switch_without_conversion():
    """C1, C2, C8: SI space made once, the user's view layer and collections kept; switching only switches."""
    _mode_on()
    P = _p()
    sc, props, o = _scene("PS1")
    user_vl = sc.view_layers[0]
    user_name = user_vl.name
    user_vl.use = True
    pv = P.enter_si(sc)
    assert pv.name == "Default_Pass" and user_vl.name == user_name and len(sc.view_layers) == 2
    assert _names(P.background(sc, "Default_Pass", "OBJECT")) == {"cube", "sphere"}
    assert _names(P.background(sc, "Default_Pass", "LIGHT")) == {"key"}
    assert _names(P.pass_collection(sc, "Default_Pass")) == {"cam", "null"}
    bg = P.background(sc, "Default_Pass", "OBJECT")      # names are global: another scene's may hold the plain one
    assert bg.name.startswith("Default_Pass.Background_Objects_Partition")
    assert bg["si_name"] == "Background_Objects_Partition"       # pass-local short name, whatever Blender added
    root = P.root(sc)
    assert _lc(pv, props).exclude and not _lc(pv, root).exclude
    assert _lc(user_vl, root).exclude and not _lc(user_vl, props).exclude
    assert pv.use and not user_vl.use
    _exclusive(sc)

    back = P.leave_si(sc)
    assert back == user_vl and user_vl.use and not pv.use

    late = bpy.data.objects.new("PS1_late", bpy.data.meshes.new("PS1late"))      # made in Blender space
    props.objects.link(late)
    again = P.enter_si(sc)
    assert again == pv and len(P.pass_names(sc)) == 1
    assert "late" in _names(P.background(sc, "Default_Pass", "OBJECT"))

    si_ob = bpy.data.objects.new("PS1_si", bpy.data.meshes.new("PS1si"))         # made in SI space
    P.background(sc, "Default_Pass", "OBJECT").objects.link(si_ob)
    P.leave_si(sc)
    assert any(not P.in_passes(sc, c) for c in si_ob.users_collection), si_ob.users_collection
    user_vl.update()
    assert si_ob.name in user_vl.objects
    bpy.data.scenes.remove(sc)


def test_partition_commands():
    """C3-C7, C9, C10 through the operators."""
    _mode_on()
    P = _p()
    sc, props, o = _scene("PS2")
    pv = P.enter_si(sc)

    def op(opname, vl=None, **kw):
        with bpy.context.temp_override(scene=sc, view_layer=vl or sc.view_layers[sc["si_last_pass"]]):
            return getattr(bpy.ops.si, opname)(**kw)

    if "Default_Pass.Hero" not in bpy.data.collections:      # another scene's pass already holds the global name
        bpy.data.collections.new("Default_Pass.Hero")
    _sel(pv, o["cube"], o["key"])
    assert op("create_partition", name="Hero") == {'FINISHED'}
    hero = P.find_partition(sc, "Default_Pass", "Hero")
    assert _names(hero) == {"cube"} and hero["si_partition"] == "OBJECT"     # the light stays in background
    assert hero.name != "Default_Pass.Hero" and hero["si_name"] == "Hero"     # short name stays pass-local
    _sel(pv, o["key"])
    op("create_partition", name="Keys")
    keys = P.find_partition(sc, "Default_Pass", "Keys")
    assert _names(keys) == {"key"} and keys["si_partition"] == "LIGHT"
    _exclusive(sc)

    _sel(pv, o["sphere"], o["key"])
    op("add_to_partition", partition=hero.name)
    assert _names(hero) == {"cube", "sphere"} and _names(keys) == {"key"}
    _sel(pv, o["sphere"])
    op("remove_from_partition")
    assert _names(hero) == {"cube"} and "sphere" in _names(P.background(sc, "Default_Pass", "OBJECT"))
    _exclusive(sc)

    op("create_pass", name="Beauty")
    assert sc["si_last_pass"] == "Beauty" and "Beauty" in sc.view_layers
    assert _names(P.background(sc, "Beauty", "OBJECT")) == {"cube", "sphere"}
    assert _names(P.background(sc, "Beauty", "LIGHT")) == {"key"}
    bv = sc.view_layers["Beauty"]
    assert _lc(bv, P.pass_collection(sc, "Default_Pass")).exclude
    assert _lc(pv, P.pass_collection(sc, "Beauty")).exclude

    op("copy_partition", partition=hero.name, target_pass="Beauty")
    hero_b = P.find_partition(sc, "Beauty", "Hero")
    assert hero_b is not None and hero_b != hero and _names(hero_b) == {"cube"}
    assert _names(P.background(sc, "Beauty", "OBJECT")) == {"sphere"} and _names(hero) == {"cube"}
    _exclusive(sc)

    op("set_current_pass", vl=bv, name="Default_Pass")
    assert sc["si_last_pass"] == "Default_Pass"
    op("delete_partition", partition=hero.name)
    assert P.find_partition(sc, "Default_Pass", "Hero") is None
    assert "cube" in _names(P.background(sc, "Default_Pass", "OBJECT"))
    _exclusive(sc)

    op("set_current_pass", name="Beauty")
    op("duplicate_pass")
    dup = sc["si_last_pass"]
    assert dup not in ("Beauty", "Default_Pass") and dup in sc.view_layers
    assert _names(P.find_partition(sc, dup, "Hero")) == {"cube"}
    _exclusive(sc)

    # delete by name from another pass's context: background Blender has no window to move off the deleted
    # view layer, and a context override still holding it crashes the depsgraph update after the operator
    n_obs = len(sc.objects)
    op("delete_pass", vl=bv, name=dup)
    assert dup not in sc.view_layers and P.pass_collection(sc, dup) is None and len(sc.objects) == n_obs
    op("delete_pass", vl=pv, name="Beauty")
    assert P.pass_names(sc) == ["Default_Pass"] and sc["si_last_pass"] == "Default_Pass"
    assert op("delete_pass", vl=pv) == {'CANCELLED'} and P.pass_names(sc) == ["Default_Pass"]   # never the last
    assert len(sc.objects) == n_obs

    # Render Pass would hold the temporary Render Single Layer; the property pages' edits are Blender's own steps
    no_undo = (P.SI_OT_render_pass, P.SI_OT_partition_properties, P.SI_OT_pass_properties)
    for cls in P.CLASSES:
        assert ('UNDO' in cls.bl_options) != (cls in no_undo), cls.bl_idname
    bpy.data.scenes.remove(sc)


def test_render_pass_menu_entries():
    """C11: the Render > Pass menu items run the pass operators."""
    _mode_on()
    menus = importlib.import_module(KIT + ".menus.map").MAP
    build = importlib.import_module(KIT + ".menus.build")
    want = {
        "Render/Pass/Edit/New Pass/Empty": "si.create_pass",
        "Render/Pass/Edit/Duplicate Current Pass": "si.duplicate_pass",
        "Render/Pass/Edit/Delete Current Pass": "si.delete_pass",
        "Render/Pass/Partition/New Partition": "si.create_partition",
        "Render/Pass/Partition/Add to Partition": "si.add_to_partition",
        "Render/Pass/Partition/Remove from Partition": "si.remove_from_partition",
    }
    for path, idname in want.items():
        assert path in build.ALL_PATHS, path
        assert menus.get(path, (None, None))[:2] == ("op", idname), (path, menus.get(path))
        mod, fn = idname.split(".")
        assert hasattr(getattr(bpy.ops, mod), fn), idname


def test_selection_follows_pass_switch():
    """Softimage's selection is one for every pass; Blender keeps one per view layer: switching passes carries the
    selection and the active object over (review finding 2026-11-16)."""
    _mode_on()
    P = _p()
    sc, props, o = _scene("PS3")
    pv = P.enter_si(sc)
    with bpy.context.temp_override(scene=sc, view_layer=pv):
        assert bpy.ops.si.create_pass(name="Beauty") == {'FINISHED'}
    bv = sc.view_layers["Beauty"]
    _sel(bv, o["sphere"], o["key"])
    bv.objects.active = o["key"]
    P.set_current(sc, "Default_Pass", carry_from=bv)
    assert sorted(x.name for x in pv.objects.selected) == ["PS3_key", "PS3_sphere"]
    assert pv.objects.active == o["key"]
    _sel(pv, o["cube"])
    P.set_current(sc, "Beauty")                       # no window: from the last pass
    assert [x.name for x in bv.objects.selected] == ["PS3_cube"]
    bpy.data.scenes.remove(sc)


def test_council_fixes():
    """Council review 2026-11-16 (Hydrogen, Fable): a pass deleted with Blender's tools keeps its objects; the
    selection carried to a pass includes objects sync just placed there; Add Selected Objects on another pass's
    partition (Explorer menu); a partition never copied onto its own pass."""
    _mode_on()
    P = _p()
    sc, props, o = _scene("PS4")
    pv = P.enter_si(sc)
    with bpy.context.temp_override(scene=sc, view_layer=pv):
        assert bpy.ops.si.create_pass(name="Shot") == {'FINISHED'}
    sv = sc.view_layers["Shot"]
    made = bpy.data.objects.new("PS4_made", bpy.data.meshes.new("PS4md"))
    P.background(sc, "Shot", "OBJECT").objects.link(made)        # made in the Shot pass: lives only there
    sc.view_layers.remove(sv)                                     # deleted with Blender's View Layer tools
    P.sync(sc)
    assert "PS4_made" in sc.objects and "PS4_made" in P.background(sc, "Default_Pass", "OBJECT").objects
    _exclusive(sc)
    # a new object reaches the new pass by sync and arrives selected
    new = bpy.data.objects.new("PS4_new", bpy.data.meshes.new("PS4nw"))
    P.background(sc, "Default_Pass", "OBJECT").objects.link(new)
    pv.update()
    _sel(pv, new)
    with bpy.context.temp_override(scene=sc, view_layer=pv):
        assert bpy.ops.si.create_pass(name="Beauty") == {'FINISHED'}
    bv = sc.view_layers["Beauty"]
    assert [x.name for x in bv.objects.selected] == ["PS4_new"]
    # the Explorer's Add Selected Objects names a partition of any pass
    hero = P.create_partition(sc, "Default_Pass", "Hero", [])
    _sel(bv, o["cube"])
    with bpy.context.temp_override(scene=sc, view_layer=bv):
        assert bpy.ops.si.add_to_partition(partition=hero.name) == {'FINISHED'}
        assert o["cube"].name in hero.objects
        assert bpy.ops.si.copy_partition(partition=hero.name, target_pass="Default_Pass") == {'CANCELLED'}
        bg = P.background(sc, "Default_Pass", "OBJECT")
        assert bpy.ops.si.copy_partition(partition=bg.name, target_pass="Beauty") == {'CANCELLED'}   # background
    # a deleted pass's name taken by a new pass: two background partitions, the old ones gone
    with bpy.context.temp_override(scene=sc, view_layer=bv):
        assert bpy.ops.si.create_pass(name="Gone") == {'FINISHED'}
    sc.view_layers.remove(sc.view_layers["Gone"])
    with bpy.context.temp_override(scene=sc, view_layer=bv):
        assert bpy.ops.si.create_pass(name="Gone") == {'FINISHED'}
    assert len(P.partitions(sc, "Gone")) == 2 and len([c for c in P._pass_colls(sc) if c["si_pass"] == "Gone"]) == 1
    # the only pass renamed: followed before the pass commands look for passes (Argon round 2)
    solo, _p2, _o2 = _scene("PS6")
    P.enter_si(solo)
    solo.view_layers["Default_Pass"].name = "Main"
    with bpy.context.temp_override(scene=solo, view_layer=solo.view_layers["Main"]):
        assert bpy.ops.si.create_pass(name="Extra") == {'FINISHED'}
    assert sorted(P.pass_names(solo)) == ["Extra", "Main"] and len(P.partitions(solo, "Main")) == 2
    assert "Default_Pass" not in solo.view_layers
    bpy.data.scenes.remove(solo)
    # a pass's view layer renamed with Blender's tools: the pass and its partitions follow
    bv.name = "Beauty2"
    P.sync(sc)
    assert "Beauty2" in P.pass_names(sc) and P.background(sc, "Beauty2", "OBJECT") is not None
    assert P.pass_collection(sc, "Beauty") is None
    _exclusive(sc)
    # made in SI space and put in a group (a collection outside the scene): still in Blender space on mode off
    grouped = bpy.data.objects.new("PS4_grouped", bpy.data.meshes.new("PS4gr"))
    P.background(sc, "Default_Pass", "OBJECT").objects.link(grouped)
    group = bpy.data.collections.new("PS4_group")
    group.objects.link(grouped)
    bl = P.leave_si(sc)
    bl.update()
    assert "PS4_grouped" in bl.objects
    bpy.data.collections.remove(group)
    bpy.data.scenes.remove(sc)


def test_sync_at_10k():
    """Council round 2 (Fable): sync at 10,000 objects with two passes stays well under a second (Object.users_collection
    costs 2.7 ms per call there: sync must not call it per object)."""
    import time
    _mode_on()
    P = _p()
    sc, props, o = _scene("PS5")
    me = bpy.data.meshes.new("PS5m")
    for i in range(10000):
        props.objects.link(bpy.data.objects.new("PS5_%05d" % i, me))
    P.enter_si(sc)
    with bpy.context.temp_override(scene=sc, view_layer=sc.view_layers["Default_Pass"]):
        assert bpy.ops.si.create_pass(name="Beauty") == {'FINISHED'}
    t = time.perf_counter()
    P.sync(sc)
    took = time.perf_counter() - t
    assert took < 1.0, "sync took %.2f s" % took
    _exclusive(sc)
    obs = list(sc.objects)
    bpy.data.scenes.remove(sc)
    for ob in obs:
        bpy.data.objects.remove(ob)
