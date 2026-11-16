# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Alex Doss
"""Pass presets (spec render.pass-presets): each Render > Pass > Edit > New Pass preset makes a current pass with
Blender's matching render passes on, the selection in the preset's partition and the preset's per-pass flags."""
import importlib

import bpy

KIT = None  # set by run.py


def test_pass_presets():
    mode = importlib.import_module(KIT + ".mode")
    if not mode.is_on():
        mode.enter_mode()
    P = importlib.import_module(KIT + ".ops.passes")
    PP = importlib.import_module(KIT + ".ops.pass_presets")
    sc = bpy.data.scenes.new("PP")
    cube = bpy.data.objects.new("PP_cube", bpy.data.meshes.new("PPc"))
    key = bpy.data.objects.new("PP_key", bpy.data.lights.new("PPk", 'POINT'))
    for o in (cube, key):
        sc.collection.objects.link(o)
    P.enter_si(sc)
    try:
        for preset, spec in PP.PRESETS.items():
            cur = sc.view_layers[sc["si_last_pass"]]
            for o in cur.objects:
                o.select_set(o in (cube, key), view_layer=cur)
            with bpy.context.temp_override(scene=sc, view_layer=cur):
                assert bpy.ops.si.create_pass_preset(preset=preset) == {'FINISHED'}, preset
            vl = sc.view_layers[sc["si_last_pass"]]
            assert vl.name.startswith(preset + "_Pass") and vl.name in P.pass_names(sc), (preset, vl.name)
            for attr in spec.get("aovs", ()):
                owner, a = (getattr(vl, attr.split(".")[0], None), attr.split(".")[1]) if "." in attr else (vl, attr)
                if owner is not None and hasattr(owner, a):
                    assert getattr(owner, a), (preset, attr)
            if spec.get("motion_blur"):
                assert vl.use_motion_blur, preset
            flag = spec.get("background")
            bg = P.partition_layer(sc, P.background(sc, vl.name, "OBJECT"))
            if flag:
                want = {"ISOLATE": "indirect_only" if sc.render.engine == 'CYCLES' else "holdout"}.get(flag, flag)
                assert getattr(bg, want), (preset, want)
            else:
                assert not (bg.holdout or bg.indirect_only), preset
            part = spec.get("partition")
            if part:
                name, kind = part
                c = P.find_partition(sc, vl.name, name)
                assert c is not None and c["si_partition"] == kind, (preset, name)
                want = {"PP_key"} if kind == "LIGHT" else {"PP_cube"}            # the selection, of its kind
                assert {o.name for o in c.objects} == want, (preset, [o.name for o in c.objects])
            assert len(P.partitions(sc, vl.name)) == 2 + bool(part), preset
        # other passes untouched: Default_Pass keeps its plain background
        bg = P.partition_layer(sc, P.background(sc, "Default_Pass", "OBJECT"))
        assert not (bg.holdout or bg.indirect_only)
        # menu: every mapped label runs its preset; the unmapped ones stay greyed (not in the map)
        menus = importlib.import_module(KIT + ".menus.map").MAP
        for label, preset in PP.MENU.items():
            assert menus["Render/Pass/Edit/New Pass/" + label] == ("op", "si.create_pass_preset", {"preset": preset})
        for label in ("Caustics", "Toon", "Image Based Lighting"):
            assert "Render/Pass/Edit/New Pass/" + label not in menus
        assert 'UNDO' in PP.SI_OT_create_pass_preset.bl_options
    finally:
        bpy.data.scenes.remove(sc)
