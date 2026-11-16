# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Alex Doss
"""Pass presets (spec render.pass-presets): Softimage's New Pass presets mapped onto the render passes (AOVs)
Blender already has, plus the isolating partition of the selection and its per-pass flags (render.overrides).
User decision 2026-11-11: map onto Blender's passes, don't recreate mental ray's presets."""

import bpy
from bpy.props import StringProperty

from . import passes as P

_DIFFUSE = ("use_pass_diffuse_direct", "use_pass_diffuse_indirect", "use_pass_diffuse_color")
_GLOSSY = ("use_pass_glossy_direct", "use_pass_glossy_indirect", "use_pass_glossy_color")
_TRANSMISSION = ("use_pass_transmission_direct", "use_pass_transmission_indirect", "use_pass_transmission_color")

# preset: aovs = view layer passes ("cycles." / "eevee." for the engines' own), background = flag on the
# background objects partition, partition = (name, kind) of the selection's partition, motion_blur
PRESETS = {
    "Ambient": dict(aovs=("use_pass_ambient_occlusion",)),
    "Diffuse": dict(aovs=_DIFFUSE),
    "Ambient_Diffuse": dict(aovs=_DIFFUSE + ("use_pass_ambient_occlusion",), motion_blur=True),
    "Highlight": dict(aovs=_GLOSSY),
    "Reflection": dict(aovs=("use_pass_glossy_indirect",), background="indirect_only",
                       partition=("Partition_Reflective", "OBJECT")),
    "Refraction": dict(aovs=_TRANSMISSION, background="indirect_only", partition=("Partition_Refractive", "OBJECT")),
    "Global_Illumination": dict(aovs=("use_pass_diffuse_indirect", "use_pass_glossy_indirect")),
    "Shadow": dict(aovs=("use_pass_shadow", "cycles.use_pass_shadow_catcher")),
    "Selective_Shadow": dict(aovs=("use_pass_shadow", "cycles.use_pass_shadow_catcher"), background="indirect_only",
                             partition=("Partition_Shadow_Receivers", "OBJECT")),
    "Depth": dict(aovs=("use_pass_z", "use_pass_mist")),
    "Isolate_Matte": dict(aovs=("use_pass_cryptomatte_object",), background="ISOLATE",
                          partition=("Partition_Matte", "OBJECT")),
    "RGBA_Matte": dict(aovs=("use_pass_cryptomatte_object",), background="holdout",
                       partition=("Partition_Matte", "OBJECT")),
    "White_Matte": dict(aovs=("use_pass_cryptomatte_object",), background="holdout",
                        partition=("Partition_Matte", "OBJECT")),      # the white material: per-partition materials
    "Volumic": dict(aovs=("eevee.use_pass_volume_direct", "cycles.use_pass_volume_direct",
                          "cycles.use_pass_volume_indirect")),
    "Glow": dict(partition=("Partition_Glow", "OBJECT")),
    "Lens_Flare": dict(partition=("Partition_Lens_Flare", "LIGHT")),
}
# Render > Pass > Edit > New Pass items (captured labels) -> preset. Caustics, Toon, Image Based Lighting, Based on
# Layers and More... have no mapping and stay greyed.
MENU = {"RGBA Matte": "RGBA_Matte", "White Matte": "White_Matte", "Isolate Matte": "Isolate_Matte",
        "Depth": "Depth", "Shadow": "Shadow", "Reflection": "Reflection", "Refraction": "Refraction",
        "Ambient": "Ambient", "Ambient/Diffuse": "Ambient_Diffuse", "Diffuse": "Diffuse", "Highlight": "Highlight",
        "Global Illumination": "Global_Illumination", "Glow": "Glow", "Lens Flare": "Lens_Flare",
        "Volumic": "Volumic"}


def _set_aov(vl, attr):
    owner = vl
    if "." in attr:
        engine, attr = attr.split(".", 1)
        owner = getattr(vl, engine, None)         # the engine's own settings (Cycles may be disabled)
    if owner is not None and hasattr(owner, attr):
        setattr(owner, attr, True)


def make_pass(context, preset):
    """The preset's pass, current; returns its view layer. The selected objects of the partition's kind go into
    the preset's partition (Softimage rule 8: presets isolate the selection)."""
    spec = PRESETS[preset]
    scene = context.scene
    selection = P._selected(context)            # before anything switches the window's view layer
    if P.root(scene) is not None:
        P._remove_stale(scene)
    old = context.view_layer if P.is_pass(scene, context.view_layer) else None
    if not P.pass_names(scene):
        P.enter_si(scene, context.window)
    vl = P._new_pass(scene, preset + "_Pass")
    P.sync(scene)
    for attr in spec.get("aovs", ()):
        _set_aov(vl, attr)
    if spec.get("motion_blur"):
        vl.use_motion_blur = True
    flag = spec.get("background")
    if flag:
        if flag == "ISOLATE":                     # Cycles: unseen by the camera; EEVEE has no such flag: matte
            flag = "indirect_only" if scene.render.engine == 'CYCLES' else "holdout"
        lc = P._layer_collection(vl, P.background(scene, vl.name, "OBJECT"))
        if lc is not None:
            setattr(lc, flag, True)
    part = spec.get("partition")
    if part:
        name, kind = part
        c = P._new_partition(scene, vl.name, name, kind)
        P.move_to_partition(scene, c, selection)
    P.set_current(scene, vl.name, context.window, carry_from=old)
    return vl


class SI_OT_create_pass_preset(bpy.types.Operator):
    """New pass from a Softimage preset, mapped onto Blender's render passes; presets that isolate something put
    the selected objects in a partition of their own"""
    bl_idname = "si.create_pass_preset"
    bl_label = "New Pass from Preset"
    bl_options = {'REGISTER', 'UNDO'}

    preset: StringProperty(name="Preset", options={'SKIP_SAVE'})

    def execute(self, context):
        if self.preset not in PRESETS:
            self.report({'WARNING'}, "No preset %r" % self.preset)
            return {'CANCELLED'}
        make_pass(context, self.preset)
        return P._done(context)


CLASSES = (SI_OT_create_pass_preset,)


def register():
    for c in CLASSES:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(CLASSES):
        bpy.utils.unregister_class(c)
