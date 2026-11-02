# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Alex Doss
"""GUI check (run via: python -I tools/dev.py shot OUT.png --mode on --script tests/gui_mode_keys.py).
Softimage keys and the viewport header are added in the mode and fully removed when it is switched off."""
import bpy, sys
K = "bl_ext.user_default.silica"
mode = sys.modules[K + ".mode"]
keymap = sys.modules[K + ".keymap"]
errors = []
kc = bpy.context.window_manager.keyconfigs.addon


def si_items():
    return sum(1 for km in kc.keymaps for kmi in km.keymap_items if kmi.idname.startswith("si.")
               or (kmi.idname in ("anim.keyframe_insert", "object.duplicate_move", "ed.redo") and kmi in
                   [i for _, i in keymap._items]))


if not mode.is_on():
    errors.append("mode not on")
n_on = si_items()
if n_on < 100:
    errors.append("too few Softimage keys: %d" % n_on)
s_key = [kmi for km in kc.keymaps if km.name == "3D View" for kmi in km.keymap_items
         if kmi.type == 'S' and kmi.idname == "si.tool_key"]
if not s_key:
    errors.append("S not bound in 3D View")
tab = [kmi for km in kc.keymaps if km.name == "Node Editor" for kmi in km.keymap_items
       if kmi.type == 'TAB' and kmi.idname == "si.node_tab"]      # Add menu in the Softimage Render Tree only
if not tab:
    errors.append("Tab not bound to the node Add menu (si.node_tab)")
viewport = sys.modules[K + ".ui.viewport"]
blender_draw = viewport._orig.get("draw")
if bpy.types.VIEW3D_HT_header.draw is not viewport.draw_header:
    errors.append("Softimage viewport header not active")
mode.exit_mode()
n_off = sum(1 for km in kc.keymaps for kmi in km.keymap_items if kmi.idname.startswith("si.")
            or (kmi.idname == "wm.call_menu" and kmi.type == 'TAB' and km.name == "Node Editor"))
if n_off:
    errors.append("%d si.* key items left after mode off" % n_off)
if bpy.types.VIEW3D_HT_header.draw is not blender_draw:
    errors.append("Blender header not restored")
mode.enter_mode()
if si_items() != n_on:
    errors.append("keys after re-enter: %d != %d" % (si_items(), n_on))
print("SHOT: GUI", "PASS" if not errors else "FAIL " + "; ".join(errors), "(keys: %d)" % n_on)
