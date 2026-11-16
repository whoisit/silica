# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Alex Doss
"""Schematic link drawing (milestone 4): Show defaults, labels, the "links on selected only" filter, link_at
geometry on a hand-built canvas state, the delete operator (constraint, driver, objects untouched) and a 10k
timing of the drawing's CPU side (no GPU in background Blender)."""
import importlib
import time
from types import SimpleNamespace

import bpy

KIT = None  # set by run.py


def _ld():
    return importlib.import_module(KIT + ".ui.schematic_linkdraw")


def _sl():
    return importlib.import_module(KIT + ".ops.schematic_links")


class _V2D:
    """View2D stand-in: view = region / zoom + offset (Blender's view y is up; the layout's y is down)."""

    def __init__(self, zoom=1.0, ox=0.0, oy=0.0):
        self.z, self.ox, self.oy = zoom, ox, oy

    def view_to_region(self, x, y, clip=False):
        return ((x - self.ox) * self.z, (y - self.oy) * self.z)

    def region_to_view(self, x, y):
        return (x / self.z + self.ox, y / self.z + self.oy)


class _N:
    def __init__(self, w=82.0, h=22.0):
        self.w, self.h = w, h


def _ctx(sc, v2d, w=1000, h=600):
    return SimpleNamespace(scene=sc, region=SimpleNamespace(width=w, height=h, view2d=v2d),
                           preferences=bpy.context.preferences, view_layer=sc.view_layers[0])


class _Scene:
    def __init__(self, name):
        self.name = name
        self.sc = bpy.data.scenes.new(name)
        self.obs = []

    def ob(self, n, data=None):
        o = bpy.data.objects.new(self.name + "_" + n, data)
        self.sc.collection.objects.link(o)
        self.obs.append(o)
        return o

    def state(self, grid=None):
        """A canvas state: every object a node, in a row 102 apart at y = 0 (or at `grid` positions)."""
        nodes, pos = {}, {}
        for i, o in enumerate(self.obs):
            nodes[o.session_uid] = _N()
            pos[o.session_uid] = grid(i) if grid else (i * 102.0, 0.0)
        return {"gen": 1, "nodes": nodes, "pos": pos}

    def close(self):
        bpy.data.scenes.remove(self.sc)
        datas = [o.data for o in self.obs if o.data is not None]
        bpy.data.batch_remove(self.obs)
        for d in set(datas):
            (bpy.data.armatures if isinstance(d, bpy.types.Armature) else bpy.data.meshes).remove(d)


def _armature(t, n, bones=("hip", "hand")):
    """An armature object with bones in t's scene (edit bones need Edit Mode: done in the context scene)."""
    arm = bpy.data.armatures.new(t.name + "_" + n)
    ob = bpy.data.objects.new(t.name + "_" + n, arm)
    t.sc.collection.objects.link(ob)
    t.obs.append(ob)
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


def _select(vl, *obs):
    vl.update()
    for o in vl.objects:
        o.select_set(o in obs, view_layer=vl)


def test_show_defaults():
    ld = _ld()
    assert ld.SHOW == {"constraint": True, "expression": True, "scripted": True, "operator": False,
                       "associated_model": False, "shared_material": False, "selected_only": True}
    assert [k for k, _ in ld.SHOW_ITEMS] == list(ld.CATEGORIES) + ["selected_only"]
    assert set(ld.COLORS) == set(ld.CATEGORIES) and len(set(ld.COLORS.values())) == len(ld.COLORS)
    assert ld.COLORS["constraint"] == (73, 131, 72)                   # sampled from the capture


def test_labels_categories():
    ld, sl = _ld(), _sl()
    L = lambda kind, label, detail="": SimpleNamespace(kind=kind, label=label, detail=detail)
    cases = [(L(sl.CONSTRAINT, 'COPY_LOCATION', "Copy Location target"), "Pos", "constraint"),
             (L(sl.CONSTRAINT, 'COPY_ROTATION', "Copy Rotation target"), "Ori", "constraint"),
             (L(sl.CONSTRAINT, 'TRACK_TO', "Track To target"), "Dir", "constraint"),
             (L(sl.CONSTRAINT, 'IK', "IK (bone hand) pole_target"), "UpVector", "constraint"),
             (L(sl.CONSTRAINT, 'CHILD_OF', "Child Of target"), "Pose", "constraint"),
             (L(sl.EXPRESSION, 'Expr', "location"), "Expr", "expression"),
             (L(sl.OPERATOR, 'NODES', "GN input Object"), "Nodes", "scripted"),
             (L(sl.OPERATOR, 'LATTICE', "Lattice object"), "Lattice", "operator"),
             (L(sl.OPERATOR, 'BEVEL_OBJECT', "data bevel_object"), "Bevel", "operator"),
             (L(sl.ENVELOPE, 'ARMATURE', "Armature"), "Env", "operator"),
             (L(sl.ASSOCIATED_MODEL, 'RECEIVER', "receiver"), "Incl", "associated_model"),
             (L(ld.INSTANCE, 'INSTANCE'), "Inst", "associated_model"),
             (L(ld.SHARED_MATERIAL, 'MAT'), "Mat", "shared_material")]
    for link, label, cat in cases:
        assert ld.short_label(link) == label, (link, ld.short_label(link))
        assert ld.category(link) == cat, (link, ld.category(link))
    assert ld.category(L(sl.HIERARCHY, 'PARENT')) is None
    every = [i.identifier for i in bpy.types.Constraint.bl_rna.properties['type'].enum_items]
    targeted = set(every) - {'LIMIT_LOCATION', 'LIMIT_ROTATION', 'LIMIT_SCALE', 'MAINTAIN_VOLUME', 'TRANSFORM_CACHE'}
    assert targeted <= set(ld.CONSTRAINT_LABEL), targeted - set(ld.CONSTRAINT_LABEL)


def _rig(t):
    """a -> b position constraint, c driven by d, e -> f track-to (and a second kind a -> b: an expression)."""
    a, b, c, d, e, f = (t.ob(n) for n in "abcdef")
    a.constraints.new('COPY_LOCATION').target = b
    a.constraints.new('COPY_ROTATION').target = b
    fc = c.driver_add("location", 1)
    fc.driver.variables.new().targets[0].id = d
    e.constraints.new('TRACK_TO').target = f
    fa = a.driver_add("scale", 0)
    fa.driver.variables.new().targets[0].id = b
    return a, b, c, d, e, f


def test_selected_only_filter():
    ld = _ld()
    t = _Scene("LDF")
    saved = dict(ld.SHOW)
    try:
        a, b, c, d, e, f = _rig(t)
        st = t.state()
        vl = t.sc.view_layers[0]
        ctx = _ctx(t.sc, _V2D(zoom=1.0, ox=-20, oy=-300))
        segs = lambda: sorted((g.cat, g.src.name[-1], g.tgt.name[-1], g.label)
                              for g, _a, _b in ld.segments(ctx, st, ctx.region.view2d, vl))
        _select(vl)
        assert segs() == []                                          # selected only, nothing selected
        _select(vl, b)                                               # the target end counts too
        assert segs() == [("constraint", "a", "b", "Pos,Ori"), ("expression", "b", "a", "Expr")], segs()
        _select(vl, c)
        assert segs() == [("expression", "d", "c", "Expr")], segs()
        ld.SHOW["selected_only"] = False
        assert len(segs()) == 4
        ld.SHOW["expression"] = False
        assert {s[0] for s in segs()} == {"constraint"} and len(segs()) == 2
        # two kinds between a and b are drawn side by side
        ld.SHOW["expression"] = True
        ab = [(g, p, q) for g, p, q in ld.segments(ctx, st, ctx.region.view2d, vl) if {g.src, g.tgt} == {a, b}]
        assert len(ab) == 2 and abs(ab[0][1][1] - ab[1][1][1]) > 3, ab
        # culling: a view far away draws nothing
        far = _ctx(t.sc, _V2D(zoom=1.0, ox=5000, oy=5000))
        assert ld.segments(far, st, far.region.view2d, vl) == []
        # the collect() result is cached per canvas generation
        c1 = ld.links_cache(t.sc, st)
        assert ld.links_cache(t.sc, st) is c1
        st["gen"] = 2
        assert ld.links_cache(t.sc, st) is not c1
    finally:
        ld.SHOW.clear()
        ld.SHOW.update(saved)
        t.close()


def test_link_at_geometry():
    ld = _ld()
    t = _Scene("LDG")
    saved = dict(ld.SHOW)
    try:
        a, b, c, d, e, f = _rig(t)
        ld.SHOW["selected_only"] = False
        st = t.state()
        vl = t.sc.view_layers[0]
        v2d = _V2D(zoom=1.0, ox=-20, oy=-300)
        ctx = _ctx(t.sc, v2d)
        # e (index 4) -> f (index 5): centres at x = 4*102+41 and 5*102+41, y = 11 (layout, y down)
        ex, fx, y = 4 * 102 + 41, 5 * 102 + 41, 11
        (rx, ry), (sx, _sy) = v2d.view_to_region(ex, -y), v2d.view_to_region(fx, -y)
        mid = (rx + sx) / 2
        ln = ld.link_at(ctx, st, mid, ry, vl)
        assert ln is not None and ln.owner == e and ln.target == f and ld.short_label(ln) == "Dir", ln
        assert ld.link_at(ctx, st, mid, ry + 3, vl) is not None      # within a few pixels
        assert ld.link_at(ctx, st, mid, ry + 12, vl) is None         # too far
        assert ld.link_at(ctx, st, sx + 30, ry, vl) is None          # beyond the segment's end
        ld.SHOW["constraint"] = False
        assert ld.link_at(ctx, st, mid, ry, vl) is None              # a hidden kind isn't hit
    finally:
        ld.SHOW.clear()
        ld.SHOW.update(saved)
        t.close()


def test_delete_operator():
    ld, sl = _ld(), _sl()
    registered = hasattr(bpy.types, "SI_OT_schematic_link_delete")
    if not registered:
        ld.register()
    t = _Scene("LDD")
    try:
        a, b, c, d, e, f = _rig(t)
        rig = _armature(t, "rig")
        ik = rig.pose.bones["hand"].constraints.new('IK')
        ik.target = f
        rig.pose.bones["hand"].constraints.new('COPY_SCALE').target = e
        n_obs = len(bpy.data.objects)
        S = sl.collect(t.sc)
        con = next(ln for ln in S.links if ln.kind == sl.CONSTRAINT and ln.owner == a and ln.label == 'COPY_LOCATION')
        # explicit link key (a menu or another caller)
        k = ld.link_key(con)
        r = bpy.ops.si.schematic_link_delete(kind=k[0], owner=k[1], holder=k[2], path=k[3], index=k[4])
        assert r == {'FINISHED'} and [x.type for x in a.constraints] == ['COPY_ROTATION'], list(a.constraints)
        assert bpy.ops.si.schematic_link_delete(kind=k[0], owner=k[1], holder=k[2], path=k[3],
                                                index=k[4]) == {'CANCELLED'}      # already gone
        # the picked link (a click): a driver
        drv = next(ln for ln in S.links if ln.kind == sl.EXPRESSION and ln.owner == c)
        ld.picked.update(key=ld.link_key(drv), group=None)
        assert bpy.ops.si.schematic_link_delete('EXEC_DEFAULT') == {'FINISHED'}
        assert not c.animation_data.drivers and not ld.picked
        assert len(a.animation_data.drivers) == 1                   # other drivers stay
        # a key that resolves to nothing is refused
        assert bpy.ops.si.schematic_link_delete(owner=a.name, path="constraints[\"nope\"]") == {'CANCELLED'}
        # a pose-bone constraint is removed from its bone
        bone = next(ln for ln in S.links if ln.kind == sl.CONSTRAINT and ln.owner == rig and ln.target == f)
        assert ld.delete_key(ld.link_key(bone)) is not None
        assert [x.type for x in rig.pose.bones["hand"].constraints] == ['COPY_SCALE']
        # non-deletable links are never removed; objects never are
        S2 = sl.collect(t.sc)
        assert all(ld.delete_key(ld.link_key(ln)) is None for ln in S2.links if not ln.deletable)
        assert len(bpy.data.objects) == n_obs and all(o.name in bpy.data.objects for o in t.obs)
    finally:
        ld.picked.clear()
        t.close()
        if not registered:
            ld.unregister()


def test_timing_10k():
    """10,000 nodes, ~300 links: the drawing's CPU side (segments, arrows, labels) within budget; a material
    shared by 3,000 objects (a star drawn from selected ends only) stays within it too."""
    ld = _ld()
    t = _Scene("LDT")
    saved = dict(ld.SHOW)
    mat = bpy.data.materials.new("LDT_mat")
    try:
        me = bpy.data.meshes.new("LDT_me")
        me.materials.append(mat)
        obs = [t.ob("o%d" % i, me if i < 3000 else None) for i in range(10000)]
        for i in range(0, 10000, 60):                                # 167 constraints
            obs[i].constraints.new('COPY_LOCATION').target = obs[(i * 7 + 13) % 10000]
        for i in range(5, 10000, 80):                                # 125 drivers
            obs[i].driver_add("location", 0).driver.variables.new().targets[0].id = obs[(i * 3 + 101) % 10000]
        st = t.state(lambda i: ((i % 100) * 102.0, (i // 100) * 52.0))
        vl = t.sc.view_layers[0]
        _select(vl, *obs[:60])
        home = _ctx(t.sc, _V2D(zoom=1.0, ox=-20, oy=-1200), 1600, 900)
        t0 = time.perf_counter()
        ld.links_cache(t.sc, st)
        build = time.perf_counter() - t0

        def timed(ctx):
            best = 1e9
            for _ in range(5):
                t0 = time.perf_counter()
                ld.geometry(ctx, st, ctx.region.view2d, vl)
                best = min(best, time.perf_counter() - t0)
            return best
        sel_on = timed(home)
        ld.SHOW.update(selected_only=False, operator=True, associated_model=True)
        all_home = timed(home)
        out = _ctx(t.sc, _V2D(zoom=0.1, ox=-500, oy=-6000), 1600, 900)   # everything in view
        all_out = timed(out)
        n = len(ld.segments(out, st, out.region.view2d, vl))
        ld.SHOW.update(shared_material=True)
        _select(vl, *obs[1:61])                                      # not the star's centre (obs[0])
        t0 = time.perf_counter()
        ld.links_cache(t.sc, st)
        build_mat = time.perf_counter() - t0
        mats = timed(out)
        n_mat = len(ld.segments(out, st, out.region.view2d, vl))
        print("schematic_linkdraw: 10k nodes, %d links: build %.1f ms, selected only %.2f ms, all kinds %.2f ms "
              "(home) / %.2f ms (all in view); with shared materials (%d drawn) build %.1f ms, draw %.2f ms"
              % (n, build * 1000, sel_on * 1000, all_home * 1000, all_out * 1000, n_mat, build_mat * 1000,
                 mats * 1000))
        assert n == 167 + 125, n
        assert n_mat == n + 60, n_mat                                # obs 1..60 selected: their links to obs[0]
        assert sel_on < 0.003 and all_home < 0.015 and all_out < 0.015 and mats < 0.015, \
            (sel_on, all_home, all_out, mats)
    finally:
        ld.SHOW.clear()
        ld.SHOW.update(saved)
        t.close()
        bpy.data.materials.remove(mat)
