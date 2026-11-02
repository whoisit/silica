# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Alex Doss
"""Softimage keys, in Blender's add-on key configuration (never the user's keymap).

KEYS lists Softimage 2015's default single-key bindings (from its keymap, context "XSI") and the Blender action
for each. They are added to every 3D View / mode keymap so they take priority over Blender's defaults while the
mode is on, and removed again on unregister. Keys with modifiers stay Blender's unless listed.

NUMBER_KEYS (spec ui.view-keys) work wherever the mouse is: they are in the Window keymap, and also in the keymaps
whose own digit keys would otherwise win (3D View / modes, the Outliner's collection hide, the Node Editor's
Ctrl+digit viewer shortcuts).
"""

import bpy

KEYMAPS = ("3D View", "Object Mode", "Object Non-modal", "Mesh", "Curve", "Armature", "Pose")

# (key, ctrl, shift, alt, operator, properties, Softimage command name)
KEYS = (
    ('S', 0, 0, 0, "si.tool_key", {"tool": 'NAV', "key": 'S'}, "Navigation Tool"),
    ('Z', 0, 0, 0, "si.tool_key", {"tool": 'PANZOOM', "key": 'Z'}, "Pan and Zoom Tool"),
    ('O', 0, 0, 0, "si.tool_key", {"tool": 'ORBIT', "key": 'O'}, "Orbit Tool"),
    ('P', 0, 0, 0, "si.tool_key", {"tool": 'DOLLY', "key": 'P'}, "Dolly Tool"),
    ('V', 0, 0, 0, "si.tool_key", {"tool": 'MOVE', "key": 'V'}, "Translate Tool"),
    ('C', 0, 0, 0, "si.tool_key", {"tool": 'ROTATE', "key": 'C'}, "Rotation Tool"),
    ('X', 0, 0, 0, "si.tool_key", {"tool": 'SCALE', "key": 'X'}, "Scaling Tool"),
    ('SPACE', 0, 0, 0, "si.tool_key", {"tool": 'SELECT', "key": 'SPACE'}, "Selection Tool"),
    ('T', 0, 0, 0, "si.tool_key", {"tool": 'POINT', "key": 'T'}, "Point Select Tool"),
    ('E', 0, 0, 0, "si.tool_key", {"tool": 'EDGE', "key": 'E'}, "Edge Select Tool"),
    ('Y', 0, 0, 0, "si.tool_key", {"tool": 'POLY', "key": 'Y'}, "Polygon Select Tool"),
    ('U', 0, 0, 0, "si.tool_key", {"tool": 'POLY', "key": 'U'}, "Raycast Polygon Select Tool"),
    ('I', 0, 0, 0, "si.tool_key", {"tool": 'EDGE', "key": 'I'}, "Raycast Edge Select Tool"),
    ('A', 0, 0, 0, "si.frame", {"what": 'ALL'}, "Frame All"),
    ('F', 0, 0, 0, "si.frame", {"what": 'SELECTION'}, "Frame Selection"),
    ('R', 0, 0, 0, "si.frame", {"what": 'RESET'}, "Reset Camera"),
    ('H', 0, 0, 0, "si.hide_toggle", {}, "Hide/Unhide Selection"),
    ('G', 0, 0, 0, "si.grid_toggle", {}, "Show/Hide Grid"),
    ('Q', 0, 0, 0, "si.render_region", {}, "Render Region Tool"),
    ('K', 0, 0, 0, "anim.keyframe_insert", {}, "Save Key Hot Key"),
    ('D', 0, 0, 0, "object.duplicate_move", {}, "Duplicate Tool"),
    ('F12', 0, 0, 0, "si.view_maximize", {}, "Maximize / restore the view under the mouse"),
    ('RET', 0, 0, 0, "si.ppg_popup", {}, "Open the Property Editor of the selection"),
)
# Softimage 1-4 toolbars and 5-0 view shortcuts (floating windows, ui/view_windows.py)
NUMBER_KEYS = (
    ('ONE', 0, 0, 0, "si.switch_module", {"module": "Model"}, "Switch to Model Toolbar"),
    ('TWO', 0, 0, 0, "si.switch_module", {"module": "Animate"}, "Switch to Animate Toolbar"),
    ('THREE', 0, 0, 0, "si.switch_module", {"module": "Render"}, "Switch to Render Toolbar"),
    ('FOUR', 0, 0, 0, "si.switch_module", {"module": "ICE"}, "Switch to ICE Toolbar"),
    ('TWO', 1, 0, 0, "si.switch_module", {"module": "Hair"}, "Switch to Hair Toolbar"),
    ('FOUR', 1, 0, 0, "si.switch_module", {"module": "Simulate"}, "Switch to Simulate Toolbar"),
    ('FIVE', 0, 0, 0, "si.view_window", {"view": 'BROWSER'}, "Browser"),
    ('SIX', 0, 0, 0, "si.view_window", {"view": 'LAYERS'}, "Scene Layer Manager"),
    ('SEVEN', 0, 0, 0, "si.view_window", {"view": 'RENDER_TREE'}, "Render Tree"),
    ('EIGHT', 0, 0, 0, "si.view_window", {"view": 'EXPLORER'}, "Explorer"),
    ('NINE', 0, 0, 0, "si.view_window", {"view": 'SCHEMATIC'}, "Schematic"),
    ('ZERO', 0, 0, 0, "si.view_window", {"view": 'ANIMATION'}, "Animation Editor"),
)
NUMBER_KEYMAPS = KEYMAPS + ("Outliner", "Node Editor", "Window")
# Mode-specific: same key, different operator in edit mode
EDIT_MESH = (
    ('A', 1, 0, 0, "mesh.select_all", {"action": 'SELECT'}, "Select All"),
    ('D', 0, 0, 0, "mesh.duplicate_move", {}, "Duplicate Tool"),
)
OBJECT = (
    ('A', 1, 0, 0, "object.select_all", {"action": 'SELECT'}, "Select All"),
)
# Render Tree: Tab opens the node Add menu with search, like Softimage (user, 2026-11-01). Only in the Softimage
# workspace's Shader Editor (si.node_tab passes through elsewhere, so Blender's Tab = group edit stays in Geometry
# Nodes, the compositor and other workspaces). In the Render Tree, enter a group by double-clicking it, exit with
# Ctrl+Tab. The preset panel's mouse keys are bound by ui/node_presets.py itself.
NODE_KEYS = (
    ('TAB', 0, 0, 0, "si.node_tab", {}, "Add node (Softimage Tab)"),
)
WINDOW = (
    ('Y', 1, 0, 0, "ed.redo", {}, "Redo"),
)
# Explorer: F = Find Next Selected Node (si.explorer_find passes through in other Properties editors)
EXPLORER_KEYS = (
    ('F', 0, 0, 0, "si.explorer_find", {}, "Find Next Selected Node"),
)

_items = []   # (keymap, item)


def _km(kc, name):
    default = bpy.context.window_manager.keyconfigs.default.keymaps.get(name)
    if default is None:
        return None
    return kc.keymaps.new(name=name, space_type=default.space_type, region_type=default.region_type)


def _add(km, key, ctrl, shift, alt, op, props):
    kmi = km.keymap_items.new(op, key, 'PRESS', ctrl=bool(ctrl), shift=bool(shift), alt=bool(alt))
    for k, v in props.items():
        setattr(kmi.properties, k, v)
    _items.append((km, kmi))


def register():
    from . import prefs
    p = prefs.get()
    if p is not None and not p.softimage_keys:
        return
    kc = bpy.context.window_manager.keyconfigs.addon
    if kc is None:          # background mode
        return
    for name in KEYMAPS:
        km = _km(kc, name)
        if km is None:
            continue
        for key, c, s, a, op, props, _si in KEYS:
            if name == "Mesh" and any(k[0] == key and not k[1] for k in EDIT_MESH):
                continue
            _add(km, key, c, s, a, op, props)
        extra = EDIT_MESH if name == "Mesh" else OBJECT if name == "Object Mode" else ()
        for key, c, s, a, op, props, _si in extra:
            _add(km, key, c, s, a, op, props)
    for name in NUMBER_KEYMAPS:
        km = _km(kc, name)
        if km is None:
            continue
        for key, c, s_, a, op, props, _si in NUMBER_KEYS:
            _add(km, key, c, s_, a, op, props)
    km = _km(kc, "Node Editor")
    if km is not None:
        for key, c, s_, a, op, props, _si in NODE_KEYS:
            _add(km, key, c, s_, a, op, props)
    km = _km(kc, "Property Editor")
    if km is not None:
        for key, c, s_, a, op, props, _si in EXPLORER_KEYS:
            _add(km, key, c, s_, a, op, props)
    km = _km(kc, "Screen")
    if km is not None:
        for key, c, s, a, op, props, _si in WINDOW:
            _add(km, key, c, s, a, op, props)


def unregister():
    for km, kmi in _items:
        try:
            km.keymap_items.remove(kmi)
        except (ReferenceError, RuntimeError):
            pass
    _items.clear()
