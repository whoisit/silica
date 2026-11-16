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


def test_delete_selection():
    """Delete over the Explorer (user request 2026-11-11): Blender's own delete of the selection, one undo step."""
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o)
    keep = bpy.data.objects.new("keep", None)
    gone = bpy.data.objects.new("gone", None)
    for o in (keep, gone):
        bpy.context.scene.collection.objects.link(o)
    gone.select_set(True)
    ex = importlib.import_module(KIT + ".ui.explorer")
    assert 'UNDO' in ex.SI_OT_explorer_delete.bl_options
    assert ex.delete_selected(bpy.context) == 1
    assert "gone" not in bpy.data.objects and "keep" in bpy.data.objects


def test_hidden_objects_come_back():
    """User report 2026-11-11: a hidden object could not be brought back (not selectable, PPG box on another flag).
    Pick it in the Explorer, press H: it is visible and selected again; the PPG's View Visibility uses the same flag."""
    mode = importlib.import_module(KIT + ".mode")
    if not mode.is_on():
        mode.enter_mode()
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o)
    a = bpy.data.objects.new("a", None)
    b = bpy.data.objects.new("b", None)
    for o in (a, b):
        bpy.context.scene.collection.objects.link(o)
    tools = importlib.import_module(KIT + ".ops.tools")
    ex = importlib.import_module(KIT + ".ui.explorer")
    a.select_set(True)
    # Softimage's H hides from view AND render (checked in Softimage 2026-11-11), H again brings both back
    assert tools.hide_toggle(bpy.context) == "hid" and a.hide_get() and a.hide_render
    assert ex.hidden_badge(a, bpy.context.view_layer) == "full"
    assert bpy.ops.si.explorer_click(obj="a") == {'FINISHED'}      # picking a hidden object in the Explorer
    assert tools.hide_toggle(bpy.context) == "unhid"
    assert not a.hide_get() and not a.hide_render and a.select_get() and not b.hide_get()
    b.hide_render = True
    assert ex.hidden_badge(b, bpy.context.view_layer) == "render" and ex.hidden_badge(a, bpy.context.view_layer) is None
    a.hide_set(True)
    assert bpy.ops.si.ppg_eye(name="a") == {'FINISHED'} and not a.hide_get()


def _mode_on():
    mode = importlib.import_module(KIT + ".mode")
    if not mode.is_on():
        mode.enter_mode()
    return mode


def _sel():
    return sorted(o.name for o in bpy.context.view_layer.objects if o.select_get())


def test_selection_rules():
    """Spike B C4, C5 (spec explorer.spike-b): Shift range over visible object rows only, Ctrl toggle,
    Ctrl+Shift deselect, middle button = branch (object + descendants, grey box under the pick)."""
    _mode_on()
    ex = importlib.import_module(KIT + ".ui.explorer")
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o)
    sc = bpy.context.scene

    def new(name, parent=None):
        o = bpy.data.objects.new(name, None)
        sc.collection.objects.link(o)
        o.parent = parent
        return o
    new("a1")
    par = new("b_par")
    kid = new("b_kid", par)
    new("b_kid_g", kid)
    new("c1")
    bpy.context.view_layer.update()
    ex._expanded.clear()
    ex._expanded.update({"scene", "ob:a1"})          # a1's property rows lie inside the range: skipped
    bpy.context.window_manager.si_explorer_filter = 'ALL'
    ex.invalidate()
    ex.anchor["obj"] = None
    C = bpy.context
    assert ex.select(C, "a1"), [o.name for o in C.view_layer.objects]
    assert _sel() == ["a1"] and C.view_layer.objects.active.name == "a1", (_sel(), C.view_layer.objects.active)
    ex.select(C, "c1", 'RANGE')
    assert _sel() == ["a1", "b_par", "c1"], _sel()                  # b_par's children are folded away
    ex.select(C, "b_par", 'TOGGLE')
    assert _sel() == ["a1", "c1"], _sel()
    ex.select(C, "c1", 'DESELECT')
    assert _sel() == ["a1"], _sel()
    ex._expanded.add("ob:b_par")
    ex.select(C, "a1")
    ex.select(C, "c1", 'RANGE')
    assert _sel() == ["a1", "b_kid", "b_par", "c1"], _sel()         # b_kid_g: under the folded b_kid
    ex.select(C, "b_par", branch=True)
    assert _sel() == ["b_kid", "b_kid_g", "b_par"] and C.view_layer.objects.active.name == "b_par", _sel()
    rows = {r.obj: r for r in ex.rows(C) if r.is_object}
    assert ex.row_box(rows["b_par"]) == "selected" and ex.row_box(rows["b_kid"]) == "branch"
    ex.select(C, "a1", 'RANGE', branch=True)                         # Shift + middle adds a branch
    assert _sel() == ["a1", "b_kid", "b_kid_g", "b_par"], _sel()
    ex.select(C, "b_par", 'TOGGLE', branch=True)
    assert _sel() == ["a1"], _sel()
    assert 'UNDO' in ex.SI_OT_explorer_click.bl_options and 'UNDO' in ex.SI_OT_explorer_rename.bl_options


def test_handlers_go_with_the_mode():
    """Spike B C10: switching Softimage mode off removes the draw handler, the cache handlers and the keys."""
    mode = _mode_on()
    ex = importlib.import_module(KIT + ".ui.explorer")
    assert ex.invalidate in bpy.app.handlers.depsgraph_update_post and ex._handles
    mode.exit_mode()
    try:
        for name in ex.HANDLER_LISTS:
            assert ex.invalidate not in getattr(bpy.app.handlers, name), name
        assert not ex._handles and not ex._items
    finally:
        mode.enter_mode()


def test_scopes():
    """explorer.scopes C3-C8: Passes / Current Pass / Selection / Materials rows, container clicks."""
    _mode_on()
    ex = importlib.import_module(KIT + ".ui.explorer")
    P = importlib.import_module(KIT + ".ops.passes")
    wm = bpy.context.window_manager
    sc = bpy.data.scenes.new("SC_scopes")
    props = bpy.data.collections.new("SC_props")
    sc.collection.children.link(props)
    obs = {}
    for n, data in (("cube", bpy.data.meshes.new("SCc")), ("ball", bpy.data.meshes.new("SCb")),
                    ("key", bpy.data.lights.new("SCk", 'POINT')), ("cam", bpy.data.cameras.new("SCm"))):
        o = bpy.data.objects.new("SC_" + n, data)
        props.objects.link(o)
        obs[n] = o
    sc.camera = obs["cam"]
    red = bpy.data.materials.new("SC_red")
    bpy.data.materials.new("SC_unused")
    obs["cube"].data.materials.append(red)
    pv = P.enter_si(sc)
    ex._expanded.clear()                      # other tests' open nodes would show here too

    def ctx(vl):
        return bpy.context.temp_override(scene=sc, view_layer=vl)

    def labels(vl):
        with ctx(vl):
            ex.invalidate()
            return [(r.depth, r.label) for r in ex.rows()]
    try:
        with ctx(pv):
            for o in sc.view_layers[pv.name].objects:
                o.select_set(o in (obs["cube"],), view_layer=pv)
            ex.select_objects(bpy.context, [obs["cube"]])
            assert bpy.ops.si.create_partition(name="Hero") == {'FINISHED'}
            assert bpy.ops.si.create_pass(name="Beauty") == {'FINISHED'}
        bv = sc.view_layers["Beauty"]
        # C3 Passes: both passes, the current one (Beauty) bold and opened with camera + partitions
        with ctx(bv):
            ex.set_scope(bpy.context, 'PASSES')
        got = labels(bv)
        assert (0, "Default_Pass") in got and (0, "Beauty") in got, got
        with ctx(bv):
            rs = ex.rows()
        bold = [r.label for r in rs if r.bold]
        assert bold == ["Beauty"], bold
        under = [r for r in rs if r.depth == 1]
        assert under[0].obj == "SC_cam" and under[0].italic and under[0].color == "camera", under[0]
        parts = {r.label: r.icon for r in under if r.node and r.node[0] == "partition"}
        assert parts == {"Background_Objects_Partition": 'OUTLINER_COLLECTION',
                         "Background_Lights_Partition": 'COLLECTION_COLOR_03'}, parts
        assert not any(r.depth == 1 and r.label == "Hero" for r in rs)       # Hero: Default_Pass only, folded
        # C8 a member row has its own expand key; C3 members italic
        bg = next(r for r in under if r.label == "Background_Objects_Partition")
        ex._expanded.add(bg.key)
        with ctx(bv):
            ex.invalidate()
            rs = ex.rows()
        members = [r for r in rs if r.depth == 2 and r.is_object]
        assert sorted(r.obj for r in members) == ["SC_ball", "SC_cube"] and all(r.italic for r in members), members
        assert members[0].key.startswith(bg.key + "/ob:")
        # C4 Current Pass: only Beauty
        with ctx(bv):
            ex.set_scope(bpy.context, 'CURRENT_PASS')
        assert [l for d, l in labels(bv) if d == 0] == ["Beauty"]
        # C7 (user decision 2026-11-16, Softimage capture): a click on a partition / pass only highlights the node;
        # the members aren't selected and the pass doesn't become current. Their menus do that.
        with ctx(bv):
            ex.set_scope(bpy.context, 'PASSES')
            ex.invalidate()
            rs = ex.rows()
            ex.select_objects(bpy.context, [obs["key"]])
            i = next(k for k, r in enumerate(rs) if r.node == ("partition", bg.node[1]))
            assert ex._click_row(bpy.context, i, 'SET') == {'FINISHED'}
            assert not bv.objects.selected and ex.row_box(rs[i]) == "selected"      # the click replaced the selection
            j = next(k for k, r in enumerate(rs) if r.node == ("pass", "Default_Pass"))
            ex._click_row(bpy.context, j, 'TOGGLE')
            assert sc["si_last_pass"] == "Beauty" and {r.node for r in rs if r.selected()} == {bg.node, rs[j].node}
            k = next(k for k, r in enumerate(rs) if r.obj == "SC_cube")
            ex._click_row(bpy.context, k, 'SET')                               # an object click clears the nodes
            assert not ex.picked_nodes and [o.name for o in bv.objects.selected] == ["SC_cube"]
            # the menus: Select Members, Set as Current Pass
            assert bpy.ops.si.explorer_select_members(kind="partition", name=bg.node[1]) == {'FINISHED'}
            assert sorted(o.name for o in bv.objects.selected) == ["SC_ball", "SC_cube"]
            menu = {it[0]: it[1]("Default_Pass") for it in ex.PASS_MENU if it and len(it) > 1}
            assert menu["Set as Current Pass"] == ("si.set_current_pass", {"name": "Default_Pass"})
            assert bpy.ops.si.set_current_pass(**menu["Set as Current Pass"][1]) == {'FINISHED'}
            assert sc["si_last_pass"] == "Default_Pass"
        # C5 Selection scope follows the selection
        with ctx(pv):
            ex.set_scope(bpy.context, 'SELECTION')
            ex.select_objects(bpy.context, [obs["key"], obs["ball"]])
            assert [r.obj for r in ex.rows() if r.depth == 0] == ["SC_ball", "SC_key"]
            ex.select_objects(bpy.context, [obs["cube"]])
            assert [r.obj for r in ex.rows() if r.depth == 0] == ["SC_cube"]        # no invalidate: the key changed
        # C6 Materials: one bold library, <Not used>, users italic; click = select the users
        with ctx(pv):
            ex.set_scope(bpy.context, 'MATERIALS')
            ex._expanded.add("mat:SC_red")
            ex.invalidate()
            rs = ex.rows()
            assert rs[0].label == "Materials" and rs[0].bold and rs[0].depth == 0
            mats = {r.label: r for r in rs if r.node and r.node[0] == "material"}
            assert "SC_red" in mats and "SC_unused   <Not used>" in mats, list(mats)
            users = [r for r in rs if r.depth == 2]
            assert [r.obj for r in users] == ["SC_cube"] and users[0].italic
            ex.select_objects(bpy.context, [], 'SET')
            assert bpy.ops.si.explorer_select_members(kind="material", name="SC_red") == {'FINISHED'}
            assert [o.name for o in pv.objects.selected] == ["SC_cube"]
    finally:
        wm.si_explorer_scope = 'SCENE'
        ex.invalidate()
        bpy.data.scenes.remove(sc)


def test_scope_menu_entries():
    """explorer.scopes C1: the Scope menu items run si.explorer_scope; the rest stay greyed."""
    _mode_on()
    menus = importlib.import_module(KIT + ".menus.map").MAP
    want = {"Explorer Scope/Scene Root": 'SCENE', "Explorer Scope/Passes": 'PASSES',
            "Explorer Scope/Current Pass": 'CURRENT_PASS', "Explorer Scope/Selection": 'SELECTION',
            "Explorer Scope/Materials": 'MATERIALS'}
    for path, scope in want.items():
        assert menus.get(path) == ("op", "si.explorer_scope", {"scope": scope}), (path, menus.get(path))
    for path in ("Explorer Scope/Layers", "Explorer Scope/Current Layer", "Explorer Scope/Custom"):
        assert path not in menus, path


def test_drop_rules():
    """explorer.drag-drop (Softimage capture 2026-11-16, plan 7a): parent / unparent / Ctrl duplicate / move into a
    partition / new partition on a pass / copy a partition onto another pass / refused drops."""
    _mode_on()
    ex = importlib.import_module(KIT + ".ui.explorer")
    P = importlib.import_module(KIT + ".ops.passes")
    sc = bpy.data.scenes.new("SC_drop")
    obs = {}
    for n, data in (("box", bpy.data.meshes.new("SDb")), ("prop", bpy.data.meshes.new("SDp")),
                    ("cone", bpy.data.meshes.new("SDc")), ("key", bpy.data.lights.new("SDk", 'POINT'))):
        o = bpy.data.objects.new("SD_" + n, data)
        sc.collection.objects.link(o)
        obs[n] = o
    obs["box"].location = (3, 0, 0)
    obs["prop"].location = (1, 2, 3)
    pv = P.enter_si(sc)
    with bpy.context.temp_override(scene=sc, view_layer=pv):
        assert bpy.ops.si.create_pass(name="Other") == {'FINISHED'}
    pv = sc.view_layers["Default_Pass"]
    try:
        with bpy.context.temp_override(scene=sc, view_layer=pv):
            C = bpy.context
            wm = C.window_manager
            ex.set_scope(C, 'SCENE')
            ex._expanded.add("scene")
            ex.invalidate()

            def row(pred):
                ex.invalidate()
                return next(r for r in ex.rows(C) if pred(r))
            # object onto object: parented, stays where it was; both selected objects go (capture d12, d21)
            pv.update()
            before = obs["prop"].matrix_world.translation.copy()
            assert ex.drop(C, "objects", [obs["prop"], obs["cone"]], row(lambda r: r.obj == "SD_box")) == "parent"
            pv.update()
            assert obs["prop"].parent == obs["box"] and obs["cone"].parent == obs["box"]
            assert (obs["prop"].matrix_world.translation - before).length < 1e-5
            # no cycles: a parent onto its child is refused
            ex._expanded.add("ob:SD_box")
            assert ex.drop(C, "objects", [obs["box"]], row(lambda r: r.obj == "SD_prop")) is None
            # onto Scene_Root: unparented, in place (d15)
            assert ex.drop(C, "objects", [obs["prop"]], row(lambda r: r.key == "scene")) == "unparent"
            pv.update()
            assert obs["prop"].parent is None and (obs["prop"].matrix_world.translation - before).length < 1e-5
            # Ctrl during the drag: a copy is parented, the original stays (d18)
            n = len(sc.objects)
            assert ex.drop(C, "objects", [obs["prop"]], row(lambda r: r.obj == "SD_box"), duplicate=True) == "parent"
            assert len(sc.objects) == n + 1 and obs["prop"].parent is None
            copy = next(o for o in sc.objects if o.name.startswith("SD_prop.") and o.parent == obs["box"])
            assert copy.data != obs["prop"].data
            assert any(c.get("si_partition") for c in copy.users_collection)       # in the partitions too
            # Passes scope: onto a partition (d06), a light onto an object partition refused (d05)
            ex.set_scope(C, 'PASSES')
            ex._expanded.add("pass:Default_Pass")
            hero = P.create_partition(sc, "Default_Pass", "Hero", [obs["cone"]])
            prow = row(lambda r: r.node == ("partition", hero.name))
            assert ex.drop(C, "objects", [obs["box"]], prow) == "partition" and obs["box"].name in hero.objects
            assert ex.drop(C, "objects", [obs["key"]], prow) is None and obs["key"].name not in hero.objects
            # onto another pass: a new partition there, highlighted (d09)
            orow = row(lambda r: r.node == ("pass", "Other"))
            assert ex.drop(C, "objects", [obs["prop"]], orow) == "new_partition"
            new = P.find_partition(sc, "Other", "Partition")
            assert new is not None and [o.name for o in new.objects] == ["SD_prop"]
            assert ex.picked_nodes == {("partition", new.name)}
            assert obs["prop"].name not in P.background(sc, "Other", "OBJECT").objects
            # a partition onto another pass: copied with its members (d07); onto its own pass: nothing
            assert ex.drop(C, "partition", hero, row(lambda r: r.node == ("pass", "Other"))) == "copy_partition"
            hero_o = P.find_partition(sc, "Other", "Hero")
            assert hero_o is not None and sorted(o.name for o in hero_o.objects) == ["SD_box", "SD_cone"]
            assert ex.drop(C, "partition", hero, row(lambda r: r.node == ("pass", "Default_Pass"))) is None
            # empty space / no row: nothing
            assert ex.drop(C, "objects", [obs["box"]], None) is None
            assert 'UNDO' in ex.SI_OT_explorer_drag.bl_options
    finally:
        bpy.context.window_manager.si_explorer_scope = 'SCENE'
        ex.picked_nodes.clear()
        ex._expanded.clear()
        ex._expanded.add("scene")
        ex.invalidate()
        bpy.data.scenes.remove(sc)


def test_object_menu_and_material_drop():
    """explorer.context-menus (object, Scene_Root, background menus) and explorer.drag-drop (materials): actions on
    the clicked object alone or on the selection when it is selected (docs 1.12); a material dropped on an object;
    <Not used> from the scene's objects; Passes scope syncs new objects into their partitions."""
    _mode_on()
    ex = importlib.import_module(KIT + ".ui.explorer")
    P = importlib.import_module(KIT + ".ops.passes")
    sc = bpy.data.scenes.new("SC_menu")
    obs = {}
    for n, data in (("a", bpy.data.meshes.new("SMa")), ("b", bpy.data.meshes.new("SMb")),
                    ("c", bpy.data.meshes.new("SMc")), ("t", None)):
        o = bpy.data.objects.new("SM_" + n, data)
        sc.collection.objects.link(o)
        obs[n] = o
    obs["c"].parent = obs["a"]
    obs["b"].constraints.new('COPY_LOCATION').target = obs["t"]
    vl = sc.view_layers[0]
    try:
        with bpy.context.temp_override(scene=sc, view_layer=vl):
            C = bpy.context
            vl.update()

            def act(action, name):
                return bpy.ops.si.explorer_object_action(action=action, obj=name)
            # not selected: acts on that object alone
            ex.select_objects(C, [obs["b"]])
            act('SELECT_TREE', "SM_a")
            assert sorted(o.name for o in vl.objects.selected) == ["SM_a", "SM_c"]
            act('CONSTRAINING', "SM_b")
            assert [o.name for o in vl.objects.selected] == ["SM_t"]
            act('CONSTRAINED', "SM_t")
            assert [o.name for o in vl.objects.selected] == ["SM_b"]
            # Duplicate: a full copy, selected; Clone: shares the data
            n = len(sc.objects)
            act('DUPLICATE', "SM_b")
            dup = [o for o in vl.objects.selected]
            assert len(sc.objects) == n + 1 and len(dup) == 1 and dup[0].data != obs["b"].data
            act('CLONE', "SM_b")
            clone = vl.objects.selected[0]
            assert clone.data == obs["b"].data
            # selected: Delete acts on the whole selection
            ex.select_objects(C, [dup[0], clone])
            assert act('DELETE', dup[0].name) == {'FINISHED'}
            assert len(sc.objects) == n
            # menu tables: the captured order, mapped items
            labels = [it[0] for it in ex.OBJECT_MENU if it]
            assert labels[:5] == ["Expand All from Here", "Collapse All from Here", "Rename", "Delete", "Select Tree"]
            assert dict((it[0], it[1]) for it in ex.OBJECT_MENU if it and len(it) > 1)["Properties"] == \
                "SI_MT_explorer_object_properties"
            # View: Reset closes everything
            ex._expanded.update({"ob:SM_a", "ob:SM_b"})
            bpy.ops.si.explorer_view_action(action='RESET')
            assert ex._expanded == {"scene"}
            # material dropped on an object: Blender's drop (active slot, a slot made when there is none)
            red = bpy.data.materials.new("SM_red")
            ex.set_scope(C, 'SCENE')
            ex.invalidate()
            row_a = next(r for r in ex.rows(C) if r.obj == "SM_a")
            assert ex.drop(C, "material", red, row_a) == "material" and obs["a"].material_slots[0].material == red
            assert ex.drop(C, "material", red, row_a, duplicate=True) == "material"
            copy = obs["a"].material_slots[0].material
            assert copy != red and copy.name.startswith("SM_red.")
            row_t = next(r for r in ex.rows(C) if r.obj == "SM_t")
            assert ex.drop(C, "material", red, row_t) is None              # an empty takes no material
            # <Not used>: from the scene's objects (an orphan mesh holding it doesn't count)
            ex.set_scope(C, 'MATERIALS')
            ex.invalidate()
            labels = [r.label for r in ex.rows(C) if r.node and r.node[0] == "material"]
            assert "SM_red   <Not used>" in labels and copy.name in labels, labels
    finally:
        bpy.context.window_manager.si_explorer_scope = 'SCENE'
        ex.invalidate()
        bpy.data.scenes.remove(sc)


def test_council_fixes():
    """Council review 2026-11-16 (Hydrogen, Fable): parenting keeps an already-parented object in place, a zero-scale
    target doesn't fail, copies of a parent and child stay a hierarchy, a Ctrl material drop on an empty leaves no
    copy, Expand / Collapse All from Scene_Root reach every level, hidden picks are part of the selection for menus
    and Delete (and stop counting once unhidden elsewhere), a rename keeps the open nodes, a new file starts clean."""
    _mode_on()
    ex = importlib.import_module(KIT + ".ui.explorer")
    sc = bpy.data.scenes.new("SC_council")
    obs = {}
    for n, data in (("a", None), ("b", None), ("kid", bpy.data.meshes.new("SCk")), ("flat", None),
                    ("g", bpy.data.meshes.new("SCg")), ("h", bpy.data.meshes.new("SCh"))):
        o = bpy.data.objects.new("SC_" + n, data)
        sc.collection.objects.link(o)
        obs[n] = o
    obs["a"].location = (10, 0, 0)
    obs["kid"].parent = obs["a"]                       # parent inverse left as identity: world (11, 0, 0)
    obs["kid"].location = (1, 0, 0)
    obs["flat"].scale = (0, 1, 1)
    obs["h"].parent = obs["g"]
    vl = sc.view_layers[0]
    try:
        with bpy.context.temp_override(scene=sc, view_layer=vl):
            C = bpy.context
            vl.update()
            ex.set_scope(C, 'SCENE')
            ex._expanded.update({"scene", "ob:SC_a"})
            ex.invalidate()

            def row(name):
                ex.invalidate()
                return next(r for r in ex.rows(C) if r.obj == name and r.is_object)
            before = obs["kid"].matrix_world.translation.copy()
            assert ex.drop(C, "objects", [obs["kid"]], row("SC_b")) == "parent"
            vl.update()
            assert obs["kid"].parent == obs["b"] and (obs["kid"].matrix_world.translation - before).length < 1e-5
            assert ex.drop(C, "objects", [obs["kid"]], row("SC_flat")) == "parent"      # zero scale: no error
            # Duplicate of a parent and its child: the child's copy goes under the parent's copy
            obs["h"].constraints.new('COPY_LOCATION').target = obs["g"]
            copies = ex.copy_objects([obs["g"], obs["h"]])
            assert copies[1].parent == copies[0]
            assert copies[1].constraints[0].target == copies[0]       # copies point at each other (round 2)
            twin = bpy.data.objects.new("SC_twin", obs["g"].data)
            sc.collection.objects.link(twin)
            pair = ex.copy_objects([obs["g"], twin])
            assert pair[0].data == pair[1].data != obs["g"].data       # a shared mesh stays shared in the copies
            # a dragged branch pick (middle button) moves as a whole: the child keeps its parent
            ex.branch_roots.add("SC_g")
            assert ex.drop(C, "objects", [obs["g"], obs["h"]], row("SC_b")) == "parent"
            assert obs["g"].parent == obs["b"] and obs["h"].parent == obs["g"]
            # a Ctrl material drop on an empty is refused without making a copy
            red = bpy.data.materials.new("SCC_red")
            n = len(bpy.data.materials)
            assert ex.drop(C, "material", red, row("SC_a"), duplicate=True) is None and len(bpy.data.materials) == n
            # Expand All from Here on Scene_Root opens nested objects; Collapse All closes them again
            ex._expanded.clear()
            ex._expanded.add("scene")
            bpy.context.window_manager.si_explorer_filter = 'OBJECTS'
            bpy.ops.si.explorer_expand_all(key="scene")
            ex.invalidate()
            assert {"ob:SC_g", "ob:SC_flat"} <= ex._expanded and any(r.obj == "SC_h" for r in ex.rows(C))
            bpy.ops.si.explorer_expand_all(key="scene", collapse=True)
            assert not any(k.startswith("ob:") for k in ex._expanded) and "scene" not in ex._expanded
            # hidden picks: in the selection for the menus and Delete; unhidden elsewhere, no longer selected
            ex._expanded.add("scene")
            ex.select_objects(C, [obs["a"]])
            obs["g"].hide_set(True)
            ex.select(C, "SC_g", 'ADD')
            assert sorted(o.name for o in ex.node_targets(C, "SC_g")) == ["SC_a", "SC_g"]
            obs["h"].hide_set(True)
            ex.select(C, "SC_h", 'ADD')
            obs["h"].hide_set(False)
            assert not ex._is_selected(obs["h"], vl)
            ex._on_undo()                                              # undo: the Explorer's own picks go
            assert not ex.hidden_picks and not ex.branch_roots
            # objects Blender won't select (not selectable) are picked like hidden ones
            obs["flat"].hide_select = True
            ex.select(C, "SC_flat")
            assert [o.name for o in ex.explorer_selection(C)] == ["SC_flat"]
            # a renamed object keeps its open node
            ex._expanded.add("ob:SC_b")
            obs["b"].name = "SC_bee"
            ex._renamed("SC_b", "SC_bee")
            assert "ob:SC_bee" in ex._expanded and "ob:SC_b" not in ex._expanded
            # a pick while an object is in Edit Mode: back to Object Mode first (user decision)
            vl.objects.active = obs["kid"]
            with C.temp_override(active_object=obs["kid"], object=obs["kid"]):
                bpy.ops.object.mode_set(mode='EDIT')
            assert obs["kid"].mode == 'EDIT'
            ex.select(C, "SC_a")
            assert obs["kid"].mode == 'OBJECT' and vl.objects.active == obs["a"]
            # a new file: the old file's picks and open nodes go
            ex.picked_nodes.add(("pass", "Default_Pass"))
            ex._on_load()
            assert not ex.hidden_picks and not ex.picked_nodes and ex._expanded == {"scene"}
            assert ex.delete_selected(C, [obs["g"]]) == 1 and "SC_g" not in bpy.data.objects
    finally:
        bpy.context.window_manager.si_explorer_filter = 'ALL'
        bpy.context.window_manager.si_explorer_scope = 'SCENE'
        ex.reset_state()
        if "SCC_red" in bpy.data.materials:
            bpy.data.materials.remove(bpy.data.materials["SCC_red"])
        bpy.data.scenes.remove(sc)
