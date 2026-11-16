# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Alex Doss
"""Softimage envelopes (skinning) on imported meshes: one hidden armature per enveloped mesh, one bone per deformer.

Softimage lets any object deform a skin (chain bones, effectors, nulls, curves, meshes); Blender only bones. So
the Softimage objects stay as they are and each bone follows its deformer: a Child Of constraint on the deformer
with the setup pose S as inverse matrix. The bone's final matrix is then G S^-1 R (G = deformer now, R = bone
rest), the Armature modifier deforms by that times R^-1, i.e. G S^-1, which is Softimage's deformation exactly,
also for mirrored or scaled setup poses (a Blender bone's rest can't be either). Animating the Softimage objects
moves the skin, like in Softimage. Spec: features/io/scn-envelopes/spec.md.
"""
import bpy
from mathutils import Matrix

from ..io_scn import movecomponent


def _si_matrix(srt):
    """(scale, rotation XYZ radians, translation) -> mathutils Matrix, Softimage axes."""
    return Matrix(movecomponent._matrix(*srt))


def _rest(m):
    """A rotation + translation for the bone's rest (any works, it cancels): m without scale or mirror."""
    loc, rot, _scl = m.decompose()
    return Matrix.LocRotScale(loc, rot, None)


def _unique(names, name):
    base, i = name, 1
    while name in names:
        name = "%s.%03d" % (base, i)
        i += 1
    names.add(name)
    return name


def apply(context, sc, made, report=None):
    """Rig every imported mesh that has a decoded envelope. made: {id(SceneObject): Blender object}.
    Returns the armature objects made."""
    from .import_scn import C, C_INV
    rigs = []
    todo = [so for so in sc.objects if getattr(so, "envelopes", None) and id(so) in made]
    if not todo:
        return rigs
    context.view_layer.update()
    for so in todo:
        ob = made[id(so)]
        notes = list(getattr(so, "envelope_notes", []))
        for k, env in enumerate(so.envelopes):
            name = "%s_Envelope" % ob.name if k == 0 else "%s_Envelope%d" % (ob.name, k)
            arm = bpy.data.armatures.new(name)
            rig = bpy.data.objects.new(name, arm)
            (ob.users_collection[0] if ob.users_collection else context.collection).objects.link(rig)
            rig["si_envelope_of"] = ob.name
            bone_names, used = [], set()
            for i, d in enumerate(env.deformers):
                bone_names.append(_unique(used, d.name if d is not None else "deformer_%d" % i))
            # bones (edit mode needs the rig active)
            prev_active = context.view_layer.objects.active
            prev_mode = context.object.mode if context.object else 'OBJECT'
            if prev_mode != 'OBJECT':
                bpy.ops.object.mode_set(mode='OBJECT')
            context.view_layer.objects.active = rig
            bpy.ops.object.mode_set(mode='EDIT')
            setups = []
            for bn, srt in zip(bone_names, env.poses):
                s = C @ _si_matrix(srt) @ C_INV
                setups.append(s)
                eb = arm.edit_bones.new(bn)
                eb.head, eb.tail = (0.0, 0.0, 0.0), (0.0, 1.0, 0.0)
                eb.matrix = _rest(s)
                eb.use_deform = True
            bpy.ops.object.mode_set(mode='OBJECT')
            context.view_layer.objects.active = prev_active
            # each bone follows its deformer
            for bn, d, s in zip(bone_names, env.deformers, setups):
                target = made.get(id(d)) if d is not None else None
                if target is None:
                    continue
                con = rig.pose.bones[bn].constraints.new('CHILD_OF')
                con.target = target
                con.set_inverse_pending = False
                con.inverse_matrix = s.inverted()
            # weights + modifier
            for bn, w in zip(bone_names, env.weights):
                vg = ob.vertex_groups.get(bn) or ob.vertex_groups.new(name=bn)
                by_value = {}
                for i, v in w.items():
                    by_value.setdefault(v, []).append(i)
                for v, idx in by_value.items():
                    vg.add(idx, v / 100.0, 'REPLACE')
            mod = ob.modifiers.new(name, 'ARMATURE')
            mod.object = rig
            mod.use_vertex_groups = True
            mod.use_bone_envelopes = False
            ob.modifiers.move(len(ob.modifiers) - 1, k)   # envelopes first, like in Softimage's stack
            rig.hide_render = True
            rig.hide_set(True)
            rigs.append(rig)
        if notes and report:
            report({'WARNING'}, "%s (envelope): %s" % (ob.name, "; ".join(notes)))
    return rigs
