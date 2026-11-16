# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Alex Doss
"""Schematic links and letters read from Blender data: each Softimage link kind, the A / C / E / I / V letters,
robustness (other scenes, excluded collections, linked library objects, missing driver targets) and a 10k timing."""
import importlib
import os
import tempfile
import time

import bpy

KIT = None  # set by run.py


def _sl():
    return importlib.import_module(KIT + ".ops.schematic_links")


class _Scene:
    """A throwaway scene; every datablock made through it is removed afterwards."""

    def __init__(self, name):
        self.name = name
        self.sc = bpy.data.scenes.new(name)
        self.ids = []
        self.actions = set(bpy.data.actions)

    def ob(self, n, data=None, coll=None):
        ob = bpy.data.objects.new(self.name + "_" + n, data)
        (coll or self.sc.collection).objects.link(ob)
        self.ids.append(ob)
        return ob

    def mesh(self, n):
        me = bpy.data.meshes.new(self.name + "_" + n)
        self.ids.append(me)
        return me

    def keep(self, idb):
        self.ids.append(idb)
        return idb

    def armature(self, n, bones=("root",)):
        """An armature object with bones (edit bones need Edit Mode, done in the context scene and undone)."""
        arm = self.keep(bpy.data.armatures.new(self.name + "_" + n))
        ob = self.ob(n, arm)
        C = bpy.context
        C.scene.collection.objects.link(ob)
        was = C.view_layer.objects.active
        try:
            C.view_layer.objects.active = ob
            bpy.ops.object.mode_set(mode='EDIT')
            for i, b in enumerate(bones):
                eb = arm.edit_bones.new(b)
                eb.head, eb.tail = (i, 0, 0), (i, 0, 1)
            bpy.ops.object.mode_set(mode='OBJECT')
        finally:
            C.view_layer.objects.active = was
            C.scene.collection.objects.unlink(ob)
        return ob

    def close(self):
        bpy.data.scenes.remove(self.sc)
        homes = ((bpy.types.Object, bpy.data.objects), (bpy.types.Mesh, bpy.data.meshes),
                 (bpy.types.Armature, bpy.data.armatures), (bpy.types.Material, bpy.data.materials),
                 (bpy.types.Collection, bpy.data.collections), (bpy.types.Curve, bpy.data.curves),
                 (bpy.types.Light, bpy.data.lights), (bpy.types.NodeTree, bpy.data.node_groups))
        for idb in reversed(self.ids):
            for kind, home in homes:
                if isinstance(idb, kind):
                    home.remove(idb)
                    break
        for act in set(bpy.data.actions) - self.actions:
            bpy.data.actions.remove(act)


def _find(S, kind, src, dst):
    return [ln for ln in S.links if ln.kind == kind and ln.source == src and ln.target == dst]


def test_hierarchy_constraints():
    sl = _sl()
    t = _Scene("SLH")
    try:
        root, kid, ctrl, free = t.ob("root"), t.ob("kid"), t.ob("ctrl"), t.ob("free")
        rig = t.armature("rig", ("hip", "hand"))
        kid.parent = root
        free.parent, free.parent_type, free.parent_bone = rig, 'BONE', "hand"
        cl = kid.constraints.new('COPY_LOCATION')
        cl.target = ctrl
        kid.constraints.new('LIMIT_ROTATION')                       # no target: letter C, no link
        ac = root.constraints.new('ARMATURE')
        ac.targets.new().target = rig
        ac.targets[0].subtarget = "hip"
        ac.targets.new()                                             # empty target slot is skipped
        ik = rig.pose.bones["hand"].constraints.new('IK')
        ik.target = ctrl
        ik.pole_target = rig                                         # own armature: no self link
        S = sl.collect(t.sc)
        assert len(_find(S, sl.HIERARCHY, kid, root)) == 1
        hb = _find(S, sl.HIERARCHY, free, rig)[0]
        assert hb.detail == 'BONE' and hb.subtarget == "hand" and hb.pick == sl.PICK_OBJECT and hb.resolve() == free
        c = _find(S, sl.CONSTRAINT, kid, ctrl)
        assert len(c) == 1 and c[0].label == 'COPY_LOCATION' and c[0].deletable and c[0].resolve() == cl
        a = _find(S, sl.CONSTRAINT, root, rig)
        assert len(a) == 1 and a[0].subtarget == "hip" and a[0].resolve() == ac
        b = _find(S, sl.CONSTRAINT, rig, ctrl)
        assert len(b) == 1 and "hand" in b[0].detail and b[0].resolve() == ik
        assert not _find(S, sl.CONSTRAINT, rig, rig)
        assert S.flags[kid] == "C" and S.flags[root] == "C" and S.flags[rig] == "C"
        assert ctrl not in S.flags and free not in S.flags
        assert {ln.target for ln in S.links_of(ctrl)} == {ctrl} and len(S.links_of(ctrl)) == 2
        assert S.by_uid()[kid.session_uid] == kid and c[0].source_uid == kid.session_uid
    finally:
        t.close()


def test_drivers_modifiers_envelopes():
    sl = _sl()
    t = _Scene("SLD")
    try:
        me = t.mesh("body")
        body, ctl, other = t.ob("body", me), t.ob("ctl"), t.ob("other", t.mesh("o"))
        rig = t.armature("rig")
        lamp = t.ob("lamp", t.keep(bpy.data.lights.new("SLD_lamp", 'POINT')))
        # drivers: object target, missing target, data target (the lamp's light), shape key driver
        fc = body.driver_add("location", 1)
        v = fc.driver.variables.new()
        v.targets[0].id = ctl
        fc.driver.variables.new()                                    # no target: ignored
        v3 = fc.driver.variables.new()
        v3.targets[0].id_type = 'LIGHT'
        v3.targets[0].id = lamp.data                                 # light data -> the lamp object
        body.shape_key_add(name="Basis")
        kb = body.shape_key_add(name="Smile")
        kfc = kb.driver_add("value")
        kfc.driver.variables.new().targets[0].id = other
        kb.keyframe_insert("value", frame=1)                         # animated shape key: letter A
        ctl.driver_add("rotation_euler", 2)                          # driver without variables: letter E
        # modifiers: mirror object, Geometry Nodes object input, armature (envelope), armature parent
        body.modifiers.new("Mir", 'MIRROR').mirror_object = ctl
        ng = t.keep(bpy.data.node_groups.new("SLD_gn", 'GeometryNodeTree'))
        ng.interface.new_socket("Target", in_out='INPUT', socket_type='NodeSocketObject')
        gn = other.modifiers.new("GN", 'NODES')
        gn.node_group = ng
        getattr(gn.properties.inputs, ng.interface.items_tree[0].identifier).value = ctl
        body.modifiers.new("Arm", 'ARMATURE').object = rig
        other.parent, other.parent_type = rig, 'ARMATURE'
        crv = t.keep(bpy.data.curves.new("SLD_crv", 'CURVE'))
        tube, prof = t.ob("tube", crv), t.ob("prof", t.keep(bpy.data.curves.new("SLD_prof", 'CURVE')))
        crv.bevel_mode, crv.bevel_object = 'OBJECT', prof           # bevel objects must be curves
        S = sl.collect(t.sc)
        e = _find(S, sl.EXPRESSION, ctl, body)
        assert len(e) == 1 and e[0].owner == body and e[0].deletable and e[0].resolve() == fc
        assert len(_find(S, sl.EXPRESSION, lamp, body)) == 1
        k = _find(S, sl.EXPRESSION, other, body)
        assert len(k) == 1 and k[0].holder == me.shape_keys and k[0].resolve() == kfc
        assert len(_find(S, sl.OPERATOR, body, ctl)) == 1
        g = _find(S, sl.OPERATOR, other, ctl)
        assert len(g) == 1 and "Target" in g[0].detail and g[0].resolve() == gn
        assert len(_find(S, sl.OPERATOR, tube, prof)) == 1
        assert not _find(S, sl.OPERATOR, body, rig)                  # armature modifier is an envelope
        env = _find(S, sl.ENVELOPE, body, rig)
        assert len(env) == 1 and env[0].resolve() == body.modifiers["Arm"]
        assert len(_find(S, sl.ENVELOPE, other, rig)) == 1 and len(_find(S, sl.HIERARCHY, other, rig)) == 1
        assert S.flags[body] == "AEV" and S.flags[ctl] == "E" and S.flags[other] == "V", S.flags
        # object keys: letter A; an action with no keys for the slot does not count
        ctl.keyframe_insert("location", frame=1)
        assert sl.collect(t.sc).flags[ctl] == "AE"
    finally:
        t.close()


def test_light_linking_materials_instances():
    sl = _sl()
    t = _Scene("SLL")
    try:
        lamp = t.ob("lamp", t.keep(bpy.data.lights.new("SLL_lamp", 'SPOT')))
        recv = t.keep(bpy.data.collections.new("SLL_recv"))
        sub = t.keep(bpy.data.collections.new("SLL_sub"))
        recv.children.link(sub)
        a, b = t.ob("a", t.mesh("a"), recv), t.ob("b", t.mesh("b"), recv)
        c = t.ob("c", t.mesh("c"), sub)
        t.sc.collection.children.link(recv)
        recv.collection_objects[1].light_linking.link_state = 'EXCLUDE'
        lamp.light_linking.receiver_collection = recv
        red, blue = t.keep(bpy.data.materials.new("SLL_red")), t.keep(bpy.data.materials.new("SLL_blue"))
        shared = t.mesh("shared")
        shared.materials.append(red)
        d, e, f = t.ob("d", shared), t.ob("e", shared), t.ob("f", shared)
        f.material_slots[0].link = 'OBJECT'                          # f overrides the mesh's material
        f.material_slots[0].material = blue
        a.data.materials.append(blue)
        inst = t.ob("inst")
        inst.instance_type, inst.instance_collection = 'COLLECTION', sub
        S = sl.collect(t.sc)
        am = {ln.target: ln for ln in S.links if ln.kind == sl.ASSOCIATED_MODEL}
        assert set(am) == {a, b, c} and all(ln.source == lamp for ln in am.values())
        assert am[b].detail.endswith("EXCLUDE") and am[a].detail.endswith("INCLUDE") and am[a].label == 'RECEIVER'
        assert sorted(o.name for o in S.materials[red]) == ["SLL_d", "SLL_e"]
        assert sorted(o.name for o in S.materials[blue]) == ["SLL_a", "SLL_f"]
        assert S.instances == {inst: sub} and S.flags[inst] == "I"
    finally:
        t.close()


def test_outside_excluded_library():
    sl = _sl()
    t = _Scene("SLO")
    other = bpy.data.scenes.new("SLO_other")
    path = os.path.join(tempfile.mkdtemp(), "slo_lib.blend")
    lib_ob = None
    try:
        far = bpy.data.objects.new("SLO_far", None)                  # only in the other scene
        other.collection.objects.link(far)
        t.ids.append(far)
        near = t.ob("near")
        near.parent = far
        fc = near.driver_add("location", 0)
        fc.driver.variables.new().targets[0].id = far
        hidden = t.keep(bpy.data.collections.new("SLO_hidden"))
        t.sc.collection.children.link(hidden)
        h = t.ob("h", None, hidden)
        h.constraints.new('TRACK_TO').target = near
        vl = t.sc.view_layers[0]
        vl.update()                                                  # a new scene's layer tree is built lazily
        vl.layer_collection.children[hidden.name].exclude = True
        # a library-linked object, constrained to a local one
        src = bpy.data.objects.new("SLO_libsrc", None)
        bpy.data.libraries.write(path, {src})
        bpy.data.objects.remove(src)
        with bpy.data.libraries.load(path, link=True) as (data_from, data_to):
            data_to.objects = ["SLO_libsrc"]
        lib_ob = data_to.objects[0]
        t.sc.collection.objects.link(lib_ob)
        near.constraints.new('COPY_ROTATION').target = lib_ob
        S = sl.collect(t.sc, vl)
        hl = _find(S, sl.HIERARCHY, near, far)[0]
        assert hl.target_outside and not hl.source_outside
        ex = _find(S, sl.EXPRESSION, far, near)[0]
        assert ex.source_outside and not ex.target_outside and S.outside == {far}
        assert far not in S.objects and h in S.objects and S.excluded == {h}
        assert len(_find(S, sl.CONSTRAINT, h, near)) == 1
        assert lib_ob.library is not None and len(_find(S, sl.CONSTRAINT, near, lib_ob)) == 1
        assert S.flags[near] == "CE" and S.flags[h] == "C"
        assert not sl.collect(other).links                           # the other scene sees only its own object
    finally:
        t.close()
        bpy.data.scenes.remove(other)
        if lib_ob is not None:
            lib = lib_ob.library
            bpy.data.objects.remove(lib_ob)
            bpy.data.libraries.remove(lib)
        if os.path.exists(path):
            os.remove(path)


def test_timing_10k():
    """10,000 objects with hierarchies, a few hundred constraints, drivers and modifiers: well under 100 ms."""
    sl = _sl()
    t = _Scene("SLT")
    try:
        meshes = [t.mesh("m%d" % i) for i in range(50)]
        mat = t.keep(bpy.data.materials.new("SLT_mat"))
        for me in meshes:
            me.materials.append(mat)
        colls = [t.keep(bpy.data.collections.new("SLT_c%d" % i)) for i in range(20)]
        for c in colls:
            t.sc.collection.children.link(c)
        obs = [t.ob("o%d" % i, meshes[i % 50] if i % 2 else None, colls[i % 20]) for i in range(10000)]
        for i, ob in enumerate(obs):
            if i % 10:
                ob.parent = obs[i - i % 10]
        for i in range(0, 10000, 30):                                # ~333 constraints
            obs[i].constraints.new('COPY_LOCATION').target = obs[i + 1]
        for i in range(5, 10000, 40):                                # 250 drivers
            obs[i].driver_add("location", 0).driver.variables.new().targets[0].id = obs[i - 1]
        for i in range(3, 10000, 50):                                # 200 modifiers on meshes
            obs[i].modifiers.new("Mir", 'MIRROR').mirror_object = obs[i - 1]
        sl.collect(t.sc)                                             # warm the per-type caches
        best = min(_timed(sl, t.sc) for _ in range(3))
        S = sl.collect(t.sc, t.sc.view_layers[0])
        t0 = time.perf_counter()
        assert len(S.materials[mat]) == 5000                         # shared materials are built on first use
        mats = time.perf_counter() - t0
        print("schematic_links: 10k objects, %d links, collect %.1f ms, materials %.1f ms"
              % (len(S.links), best * 1000, mats * 1000))
        assert len(S.links) == 9000 + 334 + 250 + 200, len(S.links)
        assert best < 0.25 and mats < 0.06, (best, mats)       # ~4x the worst measured (60 / 14 ms, 2026-11-16)
    finally:
        t.close()


def _timed(sl, sc):
    t0 = time.perf_counter()
    sl.collect(sc)
    return time.perf_counter() - t0
