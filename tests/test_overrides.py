# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Alex Doss
"""Partition overrides (spec render.overrides): a partition's visibility and override entries are Blender's own
per-view-layer flags of its layer collection, set in its pass only; the Explorer shows them as an Override node
under the partition and as "Override (<partition>)" in the members' trees."""
import importlib

import bpy

KIT = None  # set by run.py


def test_partition_overrides():
    mode = importlib.import_module(KIT + ".mode")
    if not mode.is_on():
        mode.enter_mode()
    P = importlib.import_module(KIT + ".ops.passes")
    ex = importlib.import_module(KIT + ".ui.explorer")
    sc = bpy.data.scenes.new("OV")
    obs = {}
    for n, data in (("cube", bpy.data.meshes.new("OVc")), ("ball", bpy.data.meshes.new("OVb")),
                    ("key", bpy.data.lights.new("OVk", 'POINT'))):
        o = bpy.data.objects.new("OV_" + n, data)
        sc.collection.objects.link(o)
        obs[n] = o
    pv = P.enter_si(sc)
    hero = P.create_partition(sc, "Default_Pass", "Hero", [obs["cube"]])
    with bpy.context.temp_override(scene=sc, view_layer=pv):
        assert bpy.ops.si.create_pass(name="Beauty") == {'FINISHED'}
    pv = sc.view_layers["Default_Pass"]
    bg_b = P.background(sc, "Beauty", "OBJECT")
    try:
        with bpy.context.temp_override(scene=sc, view_layer=pv):
            C = bpy.context
            # set from the current pass, on any pass: the flag lands on that partition's own pass only
            assert bpy.ops.si.partition_flag(partition=hero.name, flag='holdout') == {'FINISHED'}
            assert bpy.ops.si.partition_flag(partition=bg_b.name, flag='indirect_only') == {'FINISHED'}
            assert P.partition_layer(sc, hero).holdout and not P.partition_layer(sc, bg_b).holdout
            assert P.partition_layer(sc, bg_b).indirect_only
            assert not P._layer_collection(pv, P.background(sc, "Default_Pass", "OBJECT")).indirect_only
            ovs = P.partition_overrides(sc)
            assert [a for a, _l in ovs[hero]] == ['holdout'] and [a for a, _l in ovs[bg_b]] == ['indirect_only']
            assert bpy.ops.si.partition_flag(partition="nope", flag='holdout') == {'CANCELLED'}
            assert 'UNDO' in P.SI_OT_partition_flag.bl_options
            # Explorer, Passes scope: an Override node with its entries under the partition
            ex.set_scope(C, 'PASSES')
            pk = "pass:Default_Pass/part:" + hero.name
            ex._expanded.update({"pass:Default_Pass", pk, pk + "/ovr"})
            ex.invalidate()
            labels = [r.label for r in ex.rows(C)]
            i = labels.index("Override")
            assert labels[i + 1] == "Matte (Holdout)", labels
            # Scene Root: the member shows "Override (Hero)" in its own tree (current pass only)
            ex.set_scope(C, 'SCENE')
            ex._expanded.update({"scene", "ob:OV_cube", "ob:OV_ball"})
            ex.invalidate()
            rs = ex.rows(C)
            assert any(r.label == "Override (Hero)" and r.italic for r in rs)
            assert sum(1 for r in rs if r.label.startswith("Override (")) == 1        # not on OV_ball
            # Duplicate Pass keeps the overrides and the pass's own settings (Argon review)
            pv.use_pass_mist = True
            assert bpy.ops.si.duplicate_pass() == {'FINISHED'}
            dup = sc["si_last_pass"]
            assert P.partition_layer(sc, P.find_partition(sc, dup, "Hero")).holdout
            assert sc.view_layers[dup].use_pass_mist
            # Passes scope: a member listed under a partition shows that partition's override
            ex.set_scope(C, 'PASSES')
            ex._expanded.update({"pass:Default_Pass/part:%s/ob:OV_cube" % hero.name})
            ex.invalidate()
            rs = ex.rows(C)
            row = next(r for r in rs if r.key == "pass:Default_Pass/part:%s/ob:OV_cube/ovr" % hero.name)
            assert row.node == ("override", hero.name)
            # a click on an override row opens its page and hands back no modal state
            assert ex._click_row(C, rs.index(row), 'SET', branch=True) == {'CANCELLED'}
            # menus: the pages behind Properties...
            pm = dict((it[0], it[1]) for it in ex.PARTITION_MENU if it and len(it) > 1)
            assert pm["Properties..."]("X") == ("si.partition_properties", {"partition": "X"})
            pm = dict((it[0], it[1]) for it in ex.PASS_MENU if it and len(it) > 1)
            assert pm["Properties..."]("Beauty") == ("si.pass_properties", {"name": "Beauty"})
    finally:
        bpy.context.window_manager.si_explorer_scope = 'SCENE'
        ex.reset_state()
        bpy.data.scenes.remove(sc)
