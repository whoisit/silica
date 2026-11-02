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
}
