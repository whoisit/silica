# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Alex Doss
"""Schematic state (spec schematic.canvas): the real bugs found while it was built (2026-11-16), each kept as its
test. A click on a library-linked node picked the local object of the same name; renames and new letters didn't
reach the cached nodes; the change check had to stay structural (cheap at 10k objects)."""
import importlib
import os
import tempfile

import bpy

KIT = None  # set by run.py


def _S():
    return importlib.import_module(KIT + ".ui.schematic")


def _alive(idb):
    try:
        idb.name
        return True
    except ReferenceError:
        return False


class _Scene:
    """A throwaway scene; every datablock made through it is removed afterwards."""

    def __init__(self, name):
        self.name = name
        self.sc = bpy.data.scenes.new(name)
        self.ids = []
        self.actions = set(bpy.data.actions)

    def vl(self):
        vl = self.sc.view_layers[0]
        vl.update()                      # a new scene's layer tree is built lazily
        return vl

    def ob(self, n, data=None, coll=None):
        ob = bpy.data.objects.new(self.name + "_" + n, data)
        (coll or self.sc.collection).objects.link(ob)
        self.ids.append(ob)
        return ob

    def keep(self, idb):
        self.ids.append(idb)
        return idb

    def close(self):
        bpy.data.scenes.remove(self.sc)
        bpy.data.batch_remove([i for i in self.ids if _alive(i)])
        for act in set(bpy.data.actions) - self.actions:
            bpy.data.actions.remove(act)


def test_pick_linked_duplicate_name():
    """Bug 2026-11-16: a pick on a library-linked node selected the local object with the same name."""
    S = _S()
    t = _Scene("SSE")
    path = os.path.join(tempfile.mkdtemp(), "sse_lib.blend")
    lib_obs = []
    try:
        src = bpy.data.objects.new("SSE_dup", None)
        bpy.data.libraries.write(path, {src})
        bpy.data.objects.remove(src)
        dup = t.ob("dup")
        with bpy.data.libraries.load(path, link=True) as (data_from, data_to):
            data_to.objects = ["SSE_dup"]
        lib_obs = list(data_to.objects)
        lib_dup = lib_obs[0]
        t.sc.collection.objects.link(lib_dup)
        vl = t.vl()
        assert lib_dup.name == dup.name and lib_dup.library is not None and dup.library is None
        by_ob = {n.ob: n for n in S.build_nodes(t.sc, vl).values()}
        assert by_ob[lib_dup].uid != by_ob[dup].uid
        with bpy.context.temp_override(scene=t.sc, view_layer=vl):
            S.pick(bpy.context, by_ob[lib_dup], 'SET', 'node')
            got = (lib_dup.select_get(view_layer=vl), dup.select_get(view_layer=vl))
        assert got == (True, False), "a click on the linked node selected (linked, local) = %s" % (got,)
    finally:
        try:
            t.close()
        finally:
            libs = {o.library for o in lib_obs if _alive(o)}
            bpy.data.batch_remove([o for o in lib_obs if _alive(o)] + [lb for lb in libs if lb is not None])
            if os.path.exists(path):
                os.remove(path)


def test_state_refreshes_names_and_letters():
    """Bug 2026-11-16: state() keeps its layout while the signature is unchanged; but a rename or a new letter (an
    armature modifier, an action on an object that already had drivers) must still reach the cached nodes, which
    the labels, the letters and the node menu (explorer.menu_target by n.name) read."""
    S = _S()
    t = _Scene("SSN")
    try:
        body = t.ob("body", t.keep(bpy.data.meshes.new("SSN_body")))
        rig = t.ob("rig", t.keep(bpy.data.armatures.new("SSN_rig")))
        ctl = t.ob("ctl")
        ctl.driver_add("location", 0)                                      # animation_data exists already
        vl = t.vl()
        problems = []
        with bpy.context.temp_override(scene=t.sc, view_layer=vl):
            S._state.clear()
            st = S.state(bpy.context)
            pos = dict(st["pos"])
            assert st["nodes"][ctl.session_uid].letters == "E"
            body.name = "SSN_body_renamed"
            body.modifiers.new("Arm", 'ARMATURE').object = rig
            ctl.keyframe_insert("rotation_euler", frame=1)
            vl.update()
            S._gen[0] += 1                                                  # what depsgraph_update_post does
            st2 = S.state(bpy.context)
            n_body, n_ctl = st2["nodes"][body.session_uid], st2["nodes"][ctl.session_uid]
            assert st2["pos"] == pos                                        # nothing moved
            if n_body.name != body.name:
                problems.append("label still %r after renaming to %r" % (n_body.name, body.name))
            if n_body.letters != "V":
                problems.append("armature modifier added: letters %r, expected 'V'" % n_body.letters)
            if n_ctl.letters != "EA":
                problems.append("keys added to a driven object: letters %r, expected 'EA'" % n_ctl.letters)
            S._state.clear()
        assert not problems, "state() returned stale nodes: " + "; ".join(problems)
    finally:
        S._state.clear()
        t.close()


def test_signature_structural_only():
    """Bug 2026-11-16 (the change check was too slow at 10k objects): the relayout signature changes on structure
    (add, remove, reparent) and not on a move, a selection, a hide or a constraint; hiding is read when drawing,
    letters are refreshed without a relayout."""
    S = _S()
    t = _Scene("SSG")
    try:
        a, b, c = t.ob("a"), t.ob("b"), t.ob("c")
        vl = t.vl()
        sig = S.signature(t.sc, vl)
        a.location.x = 5.0
        a.select_set(True, view_layer=vl)
        assert S.signature(t.sc, vl) == sig, "a move / selection changed the signature"
        steps = []
        b.parent = a
        steps.append(("reparent", S.signature(t.sc, vl)))
        before = S.signature(t.sc, vl)
        c.hide_set(True, view_layer=vl)
        c.constraints.new('COPY_ROTATION')
        assert S.signature(t.sc, vl) == before, "a hide / constraint changed the layout signature"
        d = t.ob("d")
        vl.update()
        steps.append(("add", S.signature(t.sc, vl)))
        t.ids.remove(d)
        bpy.data.objects.remove(d)
        vl.update()
        steps.append(("remove", S.signature(t.sc, vl)))
        prev = sig
        for what, s in steps:
            assert s != prev, ("signature unchanged after", what)
            prev = s
    finally:
        t.close()
