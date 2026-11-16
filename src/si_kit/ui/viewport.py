# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Alex Doss
"""Softimage viewport header strip and its view / display menus.

While the mode is on, VIEW3D_HT_header.draw is replaced by:  [A] [view menu] [overlays] ... [display menu] [max]
- View menu (Softimage's camera menu): Cameras >, Spot Lights > (look through a spot), User / Top / Front / Right,
  then other editors to show in this pane (Explorer = Outliner, Render Tree = Shader Editor, ICE Tree = Geometry
  Nodes, Animation Editor = Graph Editor, ...).
- Display menu: Softimage display modes on Blender shading. Realtime Shaders / High Quality use EEVEE.
The original header draw is put back on unregister.
"""

import math

import blf
import bpy
import gpu
from gpu_extras.batch import batch_for_shader
from bpy.props import EnumProperty, StringProperty
from mathutils import Euler, Quaternion

_orig = {}
_display = {}   # space pointer -> Softimage display mode label

AXES = {
    'TOP': Quaternion(),
    'FRONT': Euler((math.pi / 2, 0, 0)).to_quaternion(),
    'RIGHT': Euler((math.pi / 2, 0, math.pi / 2)).to_quaternion(),
    'BOTTOM': Euler((math.pi, 0, 0)).to_quaternion(),
    'BACK': Euler((math.pi / 2, 0, math.pi)).to_quaternion(),
    'LEFT': Euler((math.pi / 2, 0, -math.pi / 2)).to_quaternion(),
}
USER_ROT = Euler((math.radians(65), 0, math.radians(35))).to_quaternion()
DEFAULT_DIST = 30.0

# Softimage display mode -> (shading type, extra settings); None = not available yet (greyed)
DISPLAY = {
    "Bounding Box": None,
    "Wireframe": ('WIREFRAME', {}),
    "Depth Cue": None,
    "Hidden Line Removal": ('SOLID', {"light": 'FLAT', "color_type": 'SINGLE', "single_color": (1, 1, 1), "wire": True}),
    "Constant": ('SOLID', {"light": 'FLAT', "color_type": 'MATERIAL'}),
    "Shaded": ('SOLID', {"light": 'STUDIO', "color_type": 'MATERIAL'}),
    "Textured": ('SOLID', {"light": 'STUDIO', "color_type": 'TEXTURE'}),
    "Textured Decal": ('SOLID', {"light": 'FLAT', "color_type": 'TEXTURE'}),
    "High Quality": ('MATERIAL', {"scene_lights": False, "scene_world": False}),
    "OpenGL": ('MATERIAL', {"scene_lights": True, "scene_world": True}),
    "DirectX": None,
}
DISPLAY_ORDER = ("Bounding Box", "Wireframe", "Depth Cue", "Hidden Line Removal", "Constant", "Shaded", "Textured",
                 "Textured Decal", "High Quality")
SHADING_LABEL = {'WIREFRAME': "Wireframe", 'SOLID': "Shaded", 'MATERIAL': "Realtime Shaders", 'RENDERED': "Rendered"}

# Softimage editor name -> Blender area ui_type (None = greyed)
EDITORS = (
    ("Render Tree", 'ShaderNodeTree'), ("Explorer", 'EXPLORER'), ("Schematic", None), ("ICE Tree", 'GeometryNodeTree'),
    ("Object View", None), None,
    ("Animation Editor", 'FCURVES'), ("DopeSheet", 'DOPESHEET'), ("Animation Mixer", 'NLA_EDITOR'),
    ("Shape Manager", None), None,
    ("Text Editor", 'TEXT_EDITOR'), ("Image Clip Viewer", 'IMAGE_EDITOR'), None,
    ("Property Editor", 'PPG'), ("SpreadSheet", 'SPREADSHEET'), None,
    ("Fx Tree", 'CompositorNodeTree'),
)


def _is_pane(area):
    """A Softimage viewport pane: a 3D view, or a pane showing the Explorer / Property Editor."""
    if area.type == 'VIEW_3D':
        return True
    if area.type == 'PROPERTIES':
        from .docks import space_role, PANE_ROLES
        return space_role(area.spaces.active) in PANE_ROLES
    return False


def view_letter_any(context):
    """A, B, C, D: Softimage's viewport letters, top-left to bottom-right."""
    vs = sorted((a for a in context.screen.areas if _is_pane(a)), key=lambda a: (-a.y, a.x))
    try:
        return "ABCD"[vs.index(context.area)]
    except (ValueError, IndexError):
        return ""


view_letter = view_letter_any


def view_name(space):
    r3 = space.region_3d
    if r3 is None:
        return "User"
    if r3.view_perspective == 'CAMERA':
        cam = space.camera or bpy.context.scene.camera
        return cam.name if cam else "Camera"
    if r3.view_perspective == 'ORTHO' or r3.is_orthographic_side_view:
        for name, q in AXES.items():
            if q.rotation_difference(r3.view_rotation).angle < 1e-3:
                return name.title()
    return "User"


def display_name(space):
    return _display.get(space.as_pointer()) or SHADING_LABEL.get(space.shading.type, "Shaded")


def reset_view(area):
    space = area.spaces.active
    r3 = space.region_3d
    name = view_name(space).upper()
    if r3.view_perspective == 'CAMERA':
        return
    r3.view_location = (0, 0, 0)
    r3.view_distance = DEFAULT_DIST
    if name in AXES:
        r3.view_rotation = AXES[name]
    else:
        r3.view_rotation = USER_ROT
        r3.view_perspective = 'PERSP'


# --- clean Softimage views ---------------------------------------------------------------------------------

def si_screens():
    ws = bpy.data.workspaces.get("Softimage")
    return list(ws.screens) if ws else []


def clean_space(space):
    """Softimage views show only the scene: no navigation gizmo, no 3D cursor (preference), no text overlay."""
    from .. import prefs
    p = prefs.get()
    space.show_gizmo_navigate = False
    space.overlay.show_cursor = bool(p and p.show_3d_cursor)
    space.overlay.show_text = False


def clean_views():
    for scr in si_screens():
        for a in scr.areas:
            if a.type == 'VIEW_3D':
                clean_space(a.spaces.active)


_AXIS = (((1, 0, 0), (0.86, 0.2, 0.2), "X"), ((0, 1, 0), (0.3, 0.75, 0.3), "Y"), ((0, 0, 1), (0.3, 0.45, 0.9), "Z"))
_handle = []


def draw_axes():
    """Small axis indicator in the bottom-left corner of Softimage views (instead of Blender's gizmo)."""
    ctx = bpy.context
    if ctx.workspace is None or ctx.workspace.name != "Softimage":
        return
    r3 = ctx.region_data
    if r3 is None:
        return
    rot = r3.view_rotation.inverted()
    ox, oy, size = 26, 26, 16
    pts, cols, labels = [], [], []
    for vec, col, name in _AXIS:
        v = rot @ __import__("mathutils").Vector(vec)
        end = (ox + v.x * size, oy + v.y * size)
        pts += [(ox, oy), end]
        cols += [col + (1.0,), col + (1.0,)]
        labels.append((end, col, name, v.z))
    shader = gpu.shader.from_builtin('SMOOTH_COLOR')
    gpu.state.line_width_set(2.0)
    batch_for_shader(shader, 'LINES', {"pos": pts, "color": cols}).draw(shader)
    gpu.state.line_width_set(1.0)
    font = 0
    blf.size(font, 10)
    for (x, y), col, name, _z in sorted(labels, key=lambda l: l[3]):
        blf.color(font, col[0], col[1], col[2], 1.0)
        dx = 3 if x >= ox else -9
        blf.position(font, x + dx, y - 3, 0)
        blf.draw(font, name)


# --- operators -----------------------------------------------------------------------------------------

class SI_OT_view_set(bpy.types.Operator):
    """Show this view (Softimage camera menu)"""
    bl_idname = "si.view_set"
    bl_label = "Set View"
    bl_options = {'INTERNAL'}

    view: EnumProperty(items=[(k, k.title(), "") for k in ('USER', 'TOP', 'FRONT', 'RIGHT', 'BOTTOM', 'BACK',
                                                              'LEFT', 'OBJECT')])
    obj: StringProperty()

    @classmethod
    def poll(cls, context):
        return context.area is not None

    def execute(self, context):
        area = context.area
        if area.type != 'VIEW_3D':          # e.g. the Explorer shown in this pane: back to a 3D view
            area.type = 'VIEW_3D'
        space = area.spaces.active
        r3 = space.region_3d
        if self.view == 'OBJECT':
            ob = bpy.data.objects.get(self.obj)
            if ob is None:
                return {'CANCELLED'}
            # Like Softimage: this view looks through the object (any object, spot lights included) and
            # navigating the view moves it. Blender's own per-view camera + Lock Camera to View; the scene's
            # render camera is left alone.
            space.use_local_camera = True
            space.camera = ob
            space.lock_camera = True
            r3.view_perspective = 'CAMERA'
            return {'FINISHED'}
        space.lock_camera = False                 # leaving a camera / spot view: navigating moves the view again
        if self.view == 'USER':
            if r3.view_perspective != 'PERSP':
                r3.view_perspective = 'PERSP'
            if view_name(space) != "User":
                r3.view_rotation = USER_ROT
            return {'FINISHED'}
        r3.view_perspective = 'ORTHO'
        r3.view_rotation = AXES[self.view]
        return {'FINISHED'}


class SI_OT_display_mode(bpy.types.Operator):
    """Softimage display mode for this view"""
    bl_idname = "si.display_mode"
    bl_label = "Display Mode"
    bl_options = {'INTERNAL'}

    mode: StringProperty()

    @classmethod
    def poll(cls, context):
        return context.space_data is not None and context.space_data.type == 'VIEW_3D'

    def execute(self, context):
        spec = DISPLAY.get(self.mode)
        if spec is None:
            return {'CANCELLED'}
        space = context.space_data
        stype, opt = spec
        sh = space.shading
        from ..ops import render_region
        # a render region in this view ends here: put back its grid / text / borders / engine
        render_region.clear_region(context, area=context.area, restore_shading=False)
        sh.type = stype
        if stype == 'SOLID':
            sh.light = opt.get("light", 'STUDIO')
            sh.color_type = opt.get("color_type", 'MATERIAL')
            if "single_color" in opt:
                sh.single_color = opt["single_color"]
            space.overlay.show_wireframes = opt.get("wire", False)
        elif stype == 'MATERIAL':
            sh.use_scene_lights = opt["scene_lights"]
            sh.use_scene_world = opt["scene_world"]
        _display[space.as_pointer()] = "Realtime Shaders" if self.mode == "OpenGL" else self.mode
        return {'FINISHED'}


class SI_OT_area_editor(bpy.types.Operator):
    """Show another editor in this pane (switch back with the editor-type menu at its top left)"""
    bl_idname = "si.area_editor"
    bl_label = "Show Editor"
    bl_options = {'INTERNAL'}

    ui_type: StringProperty()

    def execute(self, context):
        try:
            context.area.ui_type = self.ui_type
        except TypeError:
            return {'CANCELLED'}
        return {'FINISHED'}


class SI_OT_maximize(bpy.types.Operator):
    """Maximize this view / restore the layout"""
    bl_idname = "si.maximize"
    bl_label = "Maximize"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        bpy.ops.screen.screen_full_area()
        return {'FINISHED'}


# --- menus ---------------------------------------------------------------------------------------------

class SI_MT_view_cameras(bpy.types.Menu):
    bl_idname = "SI_MT_view_cameras"
    bl_label = "Cameras"

    def draw(self, context):
        cams = [o for o in context.scene.objects if o.type == 'CAMERA']
        for o in cams:
            op = self.layout.operator("si.view_set", text=o.name)
            op.view = 'OBJECT'
            op.obj = o.name
        if not cams:
            self.layout.label(text="No Cameras")


class SI_MT_view_spots(bpy.types.Menu):
    bl_idname = "SI_MT_view_spots"
    bl_label = "Spot Lights"

    def draw(self, context):
        spots = [o for o in context.scene.objects if o.type == 'LIGHT' and o.data.type == 'SPOT']
        for o in spots:
            op = self.layout.operator("si.view_set", text=o.name)
            op.view = 'OBJECT'
            op.obj = o.name
        if not spots:
            self.layout.label(text="No Spot")


class SI_MT_view_menu(bpy.types.Menu):
    bl_idname = "SI_MT_view_menu"
    bl_label = "View"

    def draw(self, context):
        layout = self.layout
        layout.menu("SI_MT_view_cameras")
        layout.menu("SI_MT_view_spots")
        layout.separator()
        for v in ('USER', 'TOP', 'FRONT', 'RIGHT'):
            layout.operator("si.view_set", text=v.title()).view = v
        layout.separator()
        for v in ('BOTTOM', 'BACK', 'LEFT'):
            layout.operator("si.view_set", text=v.title()).view = v
        for e in EDITORS:
            if e is None:
                layout.separator()
                continue
            label, ui = e
            if ui == 'EXPLORER':
                layout.operator("si.explorer_show", text=label)
            elif ui == 'PPG':
                layout.operator("si.ppg_show", text=label)
            elif ui is None:
                row = layout.row()
                row.enabled = False
                row.operator("si.unmapped", text=label).path = "Viewport/" + label
            else:
                layout.operator("si.area_editor", text=label).ui_type = ui


class SI_MT_display_menu(bpy.types.Menu):
    bl_idname = "SI_MT_display_menu"
    bl_label = "Display"

    def draw(self, context):
        layout = self.layout
        space = context.space_data
        layout.prop(space.overlay, "show_wireframes", text="Wireframe On Shaded")
        layout.prop(space.shading, "show_xray", text="XRay")
        layout.separator()
        cur = display_name(space)
        for name in DISPLAY_ORDER:
            if DISPLAY[name] is None:
                row = layout.row()
                row.enabled = False
                row.operator("si.unmapped", text=name).path = "Viewport Display/" + name
            else:
                layout.operator("si.display_mode", text=name, icon='DOT' if cur == name else 'NONE').mode = name
        layout.menu("SI_MT_display_realtime", text="Realtime Shaders")


class SI_MT_display_realtime(bpy.types.Menu):
    bl_idname = "SI_MT_display_realtime"
    bl_label = "Realtime Shaders"

    def draw(self, context):
        self.layout.operator("si.display_mode", text="OpenGL").mode = "OpenGL"
        row = self.layout.row()
        row.enabled = False
        row.operator("si.unmapped", text="DirectX").path = "Viewport Display/Realtime Shaders/DirectX"


# --- Show menu (the eye icon): what this viewport shows -------------------------------------------------------
# Softimage item (capture: menus.json "viewport_visibility") -> Blender's own per-view settings it switches
# ("space" = the 3D view, "overlay", "shading"), or None = no Blender equivalent (greyed). Order and separators as
# captured: viewport aids, objects, components / attributes.
_GEOM = [("space", "show_object_viewport_" + k) for k in ("mesh", "surf", "meta", "font", "volume")]
SHOW_MENU = [
    ("Manipulate Tool", [("space", "show_gizmo")]),
    ("Grid", [("overlay", "show_floor"), ("overlay", "show_axis_x"), ("overlay", "show_axis_y")]),
    ("Frame Rate", None),
    ("Selection Info", [("overlay", "show_stats")]),
    None,
    ("Lights", [("space", "show_object_viewport_light"), ("space", "show_object_viewport_light_probe")]),
    ("Cameras", [("space", "show_object_viewport_camera")]),
    ("3D Geometry", _GEOM),
    ("Implicit Geometry", None),
    ("Curves", [("space", "show_object_viewport_curve")]),
    ("Point Clouds", [("space", "show_object_viewport_pointcloud")]),
    ("Hair", [("space", "show_object_viewport_curves")]),
    ("Nulls", [("space", "show_object_viewport_empty")]),
    ("Transform Groups", None),
    ("Chains", [("space", "show_object_viewport_armature")]),
    ("Lattices", [("space", "show_object_viewport_lattice")]),
    ("Texture Controls", None),
    ("Control Objects", None),
    ("Instances", None),
    ("Annotation Objects", [("overlay", "show_annotation"), ("space", "show_object_viewport_grease_pencil")]),
    ("Environment", None),
    "objects",
    None,
    ("Invisible Components", None),
    ("Name", None),
    ("Attachments (Annotation and Synoptic)", None),
    ("User Keywords", None),
    ("Unselected Clusters (except Sample)", None),
    ("PolyMesh Boundaries and Hard Edges", [("overlay", "show_edge_sharp")]),
    ("PolyMesh Hulls", None),
    ("PolyMesh Internal Edges", None),
    ("Subdivision Surfaces", None),
    ("NURBS Boundaries", None),
    ("NURBS Hulls", None),
    ("Points", None),
    ("Knots", None),
    ("Sampled Points", None),
    ("Centers", [("overlay", "show_object_origins")]),
    ("Normals", [("overlay", "show_vertex_normals")]),
    ("Polygon Normals", [("overlay", "show_face_normals")]),
    ("Cones", None),
    ("Relations", [("overlay", "show_relationship_lines")]),
    ("Animation Cues", [("overlay", "show_motion_paths")]),
    ("Weight Points", None),
    ("Weight Maps", [("overlay", "show_weight")]),
    ("Unselected Tag Points", None),
    ("Distance to Output Camera", None),
    ("Display/ICE Attributes", None),
    ("XRay Surfaces", [("shading", "show_xray")]),
    "components",
]
_SHOW_OBJECTS = {"Lights", "Cameras", "3D Geometry", "Curves", "Point Clouds", "Hair", "Nulls", "Chains", "Lattices",
                 "Annotation Objects"}


def _show_owner(space, owner):
    return {"space": space, "overlay": space.overlay, "shading": space.shading}[owner]


def show_state(space, name):
    """True / False for a mapped Show-menu item (on when its first Blender setting is on), None when unmapped."""
    item = next((i for i in SHOW_MENU if isinstance(i, tuple) and i[0] == name), None)
    if item is None or item[1] is None:
        return None
    owner, attr = item[1][0]
    return bool(getattr(_show_owner(space, owner), attr))


def set_show(space, name, on):
    item = next(i for i in SHOW_MENU if isinstance(i, tuple) and i[0] == name)
    for owner, attr in item[1] or ():
        setattr(_show_owner(space, owner), attr, on)


class SI_OT_show_toggle(bpy.types.Operator):
    """Show or hide this kind of element in this viewport (Softimage eye menu)"""
    bl_idname = "si.show_toggle"
    bl_label = "Show"
    bl_options = {'INTERNAL'}

    # SKIP_SAVE: Blender must not remember these between calls, or a single item click after Check None would
    # re-run Check None (bug report 2026-11-11)
    item: StringProperty(options={'SKIP_SAVE'})
    group: StringProperty(options={'SKIP_SAVE'})   # "objects" / "components": Check All / Check None of that group
    on: bpy.props.BoolProperty(options={'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        return context.space_data is not None and context.space_data.type == 'VIEW_3D'

    def execute(self, context):
        space = context.space_data
        if self.group:
            names = []
            for i in SHOW_MENU:
                if i is None:
                    continue
                if isinstance(i, str):
                    if i == self.group:
                        break
                    names = []
                    continue
                names.append(i[0])
            for n in names:
                if self.group != "objects" or n in _SHOW_OBJECTS:
                    set_show(space, n, self.on)
        else:
            set_show(space, self.item, not show_state(space, self.item))
        return {'FINISHED'}


class SI_MT_show_menu(bpy.types.Menu):
    bl_idname = "SI_MT_show_menu"
    bl_label = "Show"

    def draw(self, context):
        layout = self.layout
        space = context.space_data
        for i in SHOW_MENU:
            if i is None:
                layout.separator()
            elif isinstance(i, str):
                op = layout.operator("si.show_toggle", text="Check All")
                op.group, op.on = i, True
                op = layout.operator("si.show_toggle", text="Check None")
                op.group, op.on = i, False
            elif i[1] is None:
                row = layout.row()
                row.enabled = False
                row.operator("si.unmapped", text=i[0]).path = "Viewport Show/" + i[0]
            else:
                on = show_state(space, i[0])
                layout.operator("si.show_toggle", text=i[0], icon='CHECKBOX_HLT' if on else 'CHECKBOX_DEHLT').item = i[0]


def draw_header(self, context):
    layout = self.layout
    space = context.space_data
    row = layout.row(align=True)
    row.label(text=view_letter(context))
    row.menu("SI_MT_view_menu", text=view_name(space))
    row.menu("SI_MT_show_menu", text="", icon='HIDE_OFF')       # Softimage's eye: what this viewport shows
    from . import viewport_tools
    viewport_tools.draw_memo_buttons(layout, context)
    layout.popover("VIEW3D_PT_overlay", text="", icon='OVERLAY')
    from ..ops import render_region
    if render_region.has_region(context.screen, context.area):
        layout.operator("si.render_region", text="Render Region", icon='X').clear = True
    layout.separator_spacer()
    layout.menu("SI_MT_display_menu", text=display_name(space))
    from . import viewport_tools
    viewport_tools.draw_maximize_button(layout, context)


classes = (SI_OT_view_set, SI_OT_display_mode, SI_OT_area_editor, SI_OT_maximize, SI_MT_view_cameras,
           SI_MT_view_spots, SI_MT_view_menu, SI_MT_display_menu, SI_MT_display_realtime, SI_OT_show_toggle,
           SI_MT_show_menu)


def register():
    for c in classes:
        bpy.utils.register_class(c)
    cls = bpy.types.VIEW3D_HT_header
    _orig["draw"] = cls.draw
    cls.draw = draw_header
    _handle.append(bpy.types.SpaceView3D.draw_handler_add(draw_axes, (), 'WINDOW', 'POST_PIXEL'))


def unregister():
    while _handle:
        bpy.types.SpaceView3D.draw_handler_remove(_handle.pop(), 'WINDOW')
    cls = bpy.types.VIEW3D_HT_header
    if "draw" in _orig:
        cls.draw = _orig.pop("draw")
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
    _display.clear()
