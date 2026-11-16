# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Alex Doss
"""Softimage menu item -> Blender action.

Key = label path through the menu data, with the section header included where a menu has headers:
"Model/Get/Primitive/Polygon Mesh/Cube". Values:

- ("op", "idname", {props}): draw that operator (its poll greys the item where Blender can't run it);
- ("menu", "BLENDER_MT_idname"): use a Blender menu as the submenu;
- ("prim", "KIND"): Get > Primitive with Softimage defaults (si.get_primitive).

Everything not listed is drawn greyed out with "Not in the kit yet".
"""


def _prim(kind):
    return ("prim", kind)


PRIM = "Model/Get/Primitive"

MAP = {
    # File
    "File/New Scene": ("op", "wm.read_homefile", {"use_empty": False}),
    "File/Open...": ("op", "wm.open_mainfile", {}),
    "File/Merge...": ("op", "wm.append", {}),
    "File/Save": ("op", "wm.save_mainfile", {}),
    "File/Save As...": ("op", "wm.save_as_mainfile", {}),
    "File/Save Backup": ("op", "wm.save_as_mainfile", {"copy": True}),
    "File/External Files...": ("menu", "TOPBAR_MT_file_external_data"),
    "File/Import": ("menu", "TOPBAR_MT_file_import"),
    "File/Export": ("menu", "TOPBAR_MT_file_export"),
    "File/Plug-in Manager...": ("op", "screen.userpref_show", {"section": 'ADDONS'}),
    "File/Preferences...": ("op", "screen.userpref_show", {}),
    "File/Keyboard Mapping...": ("op", "screen.userpref_show", {"section": 'KEYMAP'}),
    "File/Recent Scenes": ("menu", "TOPBAR_MT_file_open_recent"),
    "File/Exit": ("op", "wm.quit_blender", {}),
    # Edit
    "Edit/Undo": ("op", "ed.undo", {}),
    "Edit/Redo": ("op", "ed.redo", {}),
    "Edit/Repeat Get value": ("op", "screen.repeat_last", {}),
    "Edit/Copy": ("op", "view3d.copybuffer", {}),
    "Edit/Paste": ("op", "view3d.pastebuffer", {}),
    "Edit/Select All": ("op", "object.select_all", {"action": 'SELECT'}),
    "Edit/Create Group": ("op", "collection.create", {}),
    "Edit/Delete Selected": ("op", "object.delete", {"use_global": False}),
    "Edit/Delete All": ("op", "si.delete_all", {}),
    # Display
    "Display/Hide/Unhide Selection": ("op", "object.hide_view_set", {"unselected": False}),
    "Display/Unhide All Objects": ("op", "object.hide_view_clear", {}),
    "Display/Hide Unselected Objects/Polygons": ("op", "object.hide_view_set", {"unselected": True}),
    "Display/Frame Selection (All 3D Views)": ("op", "view3d.view_selected", {"use_all_regions": True}),
    "Display/Frame All (All 3D Views)": ("op", "view3d.view_all", {"use_all_regions": True}),
    # Get > Primitive
    PRIM + "/Null": _prim("NULL"),
    PRIM + "/Curve/Circle": _prim("CURVE_CIRCLE"),
    PRIM + "/Polygon Mesh/Cone": _prim("CONE"),
    PRIM + "/Polygon Mesh/Cube": _prim("CUBE"),
    PRIM + "/Polygon Mesh/Cylinder": _prim("CYLINDER"),
    PRIM + "/Polygon Mesh/Disc": _prim("DISC"),
    PRIM + "/Polygon Mesh/Grid": _prim("GRID"),
    PRIM + "/Polygon Mesh/Sphere": _prim("SPHERE"),
    PRIM + "/Polygon Mesh/Torus": _prim("TORUS"),
    PRIM + "/Polygon Mesh/Dodecahedron": _prim("DODECAHEDRON"),
    PRIM + "/Polygon Mesh/Icosahedron": _prim("ICOSAHEDRON"),
    PRIM + "/Polygon Mesh/Octahedron": _prim("OCTAHEDRON"),
    PRIM + "/Polygon Mesh/Tetrahedron": _prim("TETRAHEDRON"),
    PRIM + "/Polygon Mesh/Empty": _prim("EMPTY_MESH"),
    PRIM + "/Implicit/Circle": _prim("IMPLICIT_CIRCLE"),
    PRIM + "/Implicit/Cone": _prim("IMPLICIT_CONE"),
    PRIM + "/Implicit/Cube": _prim("IMPLICIT_CUBE"),
    PRIM + "/Implicit/Sphere": _prim("IMPLICIT_SPHERE"),
    PRIM + "/Camera/Perspective": _prim("CAMERA"),
    PRIM + "/Camera/Telephoto": _prim("CAMERA_TELEPHOTO"),
    PRIM + "/Camera/Wide Angle": _prim("CAMERA_WIDE"),
    PRIM + "/Camera/Orthographic": _prim("CAMERA_ORTHO"),
    PRIM + "/Light/Point": _prim("LIGHT_POINT"),
    PRIM + "/Light/Spot": _prim("LIGHT_SPOT"),
    PRIM + "/Light/Infinite": _prim("LIGHT_INFINITE"),
    PRIM + "/Light/Light Box": _prim("LIGHT_BOX"),
    PRIM + "/Light/Neon": _prim("LIGHT_NEON"),
    # Render > Pass (spec render.passes)
    "Render/Pass/Edit/New Pass/Empty": ("op", "si.create_pass", {}),
    # pass presets mapped onto Blender's render passes (spec render.pass-presets)
    "Render/Pass/Edit/New Pass/RGBA Matte": ("op", "si.create_pass_preset", {"preset": "RGBA_Matte"}),
    "Render/Pass/Edit/New Pass/White Matte": ("op", "si.create_pass_preset", {"preset": "White_Matte"}),
    "Render/Pass/Edit/New Pass/Isolate Matte": ("op", "si.create_pass_preset", {"preset": "Isolate_Matte"}),
    "Render/Pass/Edit/New Pass/Depth": ("op", "si.create_pass_preset", {"preset": "Depth"}),
    "Render/Pass/Edit/New Pass/Shadow": ("op", "si.create_pass_preset", {"preset": "Shadow"}),
    "Render/Pass/Edit/New Pass/Reflection": ("op", "si.create_pass_preset", {"preset": "Reflection"}),
    "Render/Pass/Edit/New Pass/Refraction": ("op", "si.create_pass_preset", {"preset": "Refraction"}),
    "Render/Pass/Edit/New Pass/Ambient": ("op", "si.create_pass_preset", {"preset": "Ambient"}),
    "Render/Pass/Edit/New Pass/Ambient/Diffuse": ("op", "si.create_pass_preset", {"preset": "Ambient_Diffuse"}),
    "Render/Pass/Edit/New Pass/Diffuse": ("op", "si.create_pass_preset", {"preset": "Diffuse"}),
    "Render/Pass/Edit/New Pass/Highlight": ("op", "si.create_pass_preset", {"preset": "Highlight"}),
    "Render/Pass/Edit/New Pass/Global Illumination": ("op", "si.create_pass_preset", {"preset": "Global_Illumination"}),
    "Render/Pass/Edit/New Pass/Glow": ("op", "si.create_pass_preset", {"preset": "Glow"}),
    "Render/Pass/Edit/New Pass/Lens Flare": ("op", "si.create_pass_preset", {"preset": "Lens_Flare"}),
    "Render/Pass/Edit/New Pass/Volumic": ("op", "si.create_pass_preset", {"preset": "Volumic"}),
    "Render/Pass/Edit/Duplicate Current Pass": ("op", "si.duplicate_pass", {}),
    "Render/Pass/Edit/Delete Current Pass": ("op", "si.delete_pass", {}),
    "Render/Pass/Partition/New Partition": ("op", "si.create_partition", {}),
    "Render/Pass/Partition/Add to Partition": ("op", "si.add_to_partition", {}),
    "Render/Pass/Partition/Remove from Partition": ("op", "si.remove_from_partition", {}),
    # Explorer header > Scope (spec explorer.scopes); Layers / Current Layer / Custom: milestones 6 and 4
    "Explorer Scope/Scene Root": ("op", "si.explorer_scope", {"scope": "SCENE"}),
    "Explorer Scope/Passes": ("op", "si.explorer_scope", {"scope": "PASSES"}),
    "Explorer Scope/Current Pass": ("op", "si.explorer_scope", {"scope": "CURRENT_PASS"}),
    "Explorer Scope/Selection": ("op", "si.explorer_scope", {"scope": "SELECTION"}),
    "Explorer Scope/Materials": ("op", "si.explorer_scope", {"scope": "MATERIALS"}),
    # Explorer header > View (the same items as a right-click on empty space in the Explorer)
    "Explorer View/Expand Selected": ("op", "si.explorer_view_action", {"action": "EXPAND_SELECTED"}),
    "Explorer View/Collapse Selected": ("op", "si.explorer_view_action", {"action": "COLLAPSE_SELECTED"}),
    "Explorer View/Reset": ("op", "si.explorer_view_action", {"action": "RESET"}),
    "Explorer View/Find Next Selected Node": ("op", "si.explorer_find", {}),
}
