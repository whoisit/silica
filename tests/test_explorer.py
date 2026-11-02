# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Alex Doss
"""Explorer operator stack regions by position (spec explorer.explorer, known issue fixed 2026-11-02).
Bug: grouping by modifier type put Subdivision under Modeling, below the Armature, although it evaluates after it.
Fallback rule (spec model.construction-mode): from the first deformer upwards = Animation, below it = Modeling."""
import importlib

import bpy

KIT = None  # set by run.py


def _stack(*mods):
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o)
    ob = bpy.data.objects.new("stack", bpy.data.meshes.new("stack"))
    bpy.context.scene.collection.objects.link(ob)
    for name, kind in mods:
        ob.modifiers.new(name, kind)
    _prim, regions = importlib.import_module(KIT + ".ui.explorer")._stack(ob)
    return {r: [m.name for m in ms] for r, ms in regions.items() if ms}


def test_regions_follow_stack_position():
    # Blender order, bottom first: Mirror -> Armature -> Subdivision. Explorer lists top first.
    got = _stack(("Mirror", 'MIRROR'), ("Armature", 'ARMATURE'), ("Subdivision", 'SUBSURF'))
    assert got == {"Animation": ["Subdivision", "Armature"], "Modeling": ["Mirror"]}, got


def test_ambiguous_modifiers_go_by_position():
    # Smooth / Displace are modeling below the first deformer, animation above it
    got = _stack(("Smooth", 'SMOOTH'), ("Lattice", 'LATTICE'), ("Displace", 'DISPLACE'))
    assert got == {"Animation": ["Displace", "Lattice"], "Modeling": ["Smooth"]}, got
    got = _stack(("Bevel", 'BEVEL'), ("Smooth", 'SMOOTH'))
    assert got == {"Modeling": ["Smooth", "Bevel"]}, got
