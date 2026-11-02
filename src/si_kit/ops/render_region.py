# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Alex Doss
"""Softimage render region (Q): drag a rectangle in any view and that part renders live.

Per-view render border + Rendered shading, set directly (no Blender operators, so it can be undone anywhere,
including on unregister). In camera view Blender uses the *scene's* render border: the user's own scene border is
saved and put back. Everything the region changes is saved before and restored when the region goes away
(Q + click, the header button, a display-mode change from the header, Softimage mode off):
view shading, floor / ortho grid, text overlay, view and scene borders, and the scene's render engine (restored
when its last region goes). The saved state lives in an ID property on the screen, keyed by area index, so it
survives saving and reopening the file.
Engine: kit preference "Render Region Engine" (Cycles default; EEVEE; or the scene's own).
"""

import bpy
import gpu
from bpy.props import BoolProperty
from bpy_extras.view3d_utils import location_3d_to_region_2d
from gpu_extras.batch import batch_for_shader

MIN_PX = 6
KEY = "si_render_regions"             # screen ID property: {area index: saved state}
ENGINE_KEY = "si_region_prev_engine"  # scene ID property: engine before the first region
BORDER_KEY = "si_region_prev_border"  # scene ID property: the user's scene border before the first camera region
_running = []                         # the Q operator while it waits for a drag (cleanup on unregister)


# --- saved state --------------------------------------------------------------------------------------------

def _states(screen):
    v = screen.get(KEY)
    return v.to_dict() if v is not None and hasattr(v, "to_dict") else dict(v or {})


def _area_key(screen, area):
    for i, a in enumerate(screen.areas):
        if a == area:
            return str(i)
    return None


def has_region(screen, area):
    k = _area_key(screen, area)
    return k is not None and k in _states(screen)


def _any_region(scene):
    return any(v.get("scene") == scene.name for scr in bpy.data.screens for v in _states(scr).values())


def _any_camera_region(scene):
    return any(v.get("scene") == scene.name and v.get("camera")
               for scr in bpy.data.screens for v in _states(scr).values())


def _save_scene_border(scene):
    if BORDER_KEY not in scene:
        r = scene.render
        scene[BORDER_KEY] = [float(r.use_border), r.border_min_x, r.border_max_x, r.border_min_y, r.border_max_y]


def _restore_scene_border(scene):
    """Put the user's scene border back once no camera region uses it any more (any screen, any view)."""
    if BORDER_KEY in scene and not _any_camera_region(scene):
        sb = list(scene[BORDER_KEY])
        r = scene.render
        r.use_border = bool(sb[0])
        r.border_min_x, r.border_max_x, r.border_min_y, r.border_max_y = sb[1:]
        del scene[BORDER_KEY]


def _engine(scene):
    from .. import prefs
    p = prefs.get()
    want = p.region_engine if p else 'CYCLES'
    if want == 'SCENE':
        return
    if ENGINE_KEY not in scene:
        scene[ENGINE_KEY] = scene.render.engine
    eng = {'CYCLES': 'CYCLES', 'EEVEE': 'BLENDER_EEVEE'}[want]
    if scene.render.engine != eng:
        try:
            scene.render.engine = eng
        except TypeError:           # Cycles disabled
            scene.render.engine = 'BLENDER_EEVEE'


def _restore_engine(scene):
    if ENGINE_KEY in scene and not _any_region(scene):
        try:
            scene.render.engine = scene[ENGINE_KEY]
        except TypeError:
            pass
        del scene[ENGINE_KEY]


# --- geometry ------------------------------------------------------------------------------------------------

def _camera_frame(scene, region, rv3d):
    """Screen bounds of the camera frame in camera view (min_x, min_y, max_x, max_y) or None."""
    cam = scene.camera
    if cam is None or cam.type != 'CAMERA':
        return None
    pts = [location_3d_to_region_2d(region, rv3d, cam.matrix_world @ v) for v in cam.data.view_frame(scene=scene)]
    pts = [p for p in pts if p is not None]
    if len(pts) < 4:
        return None
    return min(p.x for p in pts), min(p.y for p in pts), max(p.x for p in pts), max(p.y for p in pts)


def _norm(v, lo, hi):
    return max(0.0, min(1.0, (v - lo) / max(hi - lo, 1e-6)))


# --- set / clear ---------------------------------------------------------------------------------------------

def set_region(context, x0, y0, x1, y1, area=None, region=None, screen=None):
    """Turn the rectangle (region pixels) of this view into a render region."""
    area = area or context.area
    region = region or next(r for r in area.regions if r.type == 'WINDOW')
    screen = screen or context.screen
    space = area.spaces.active
    rv3d = space.region_3d
    scene = context.scene
    xa, xb, ya, yb = min(x0, x1), max(x0, x1), min(y0, y1), max(y0, y1)
    states = _states(screen)
    k = _area_key(screen, area)
    camera = rv3d.view_perspective == 'CAMERA'
    if k not in states:
        r = scene.render
        states[k] = {
            "scene": scene.name,
            "shading": space.shading.type if space.shading.type != 'RENDERED' else 'SOLID',
            "floor": space.overlay.show_floor, "ortho": space.overlay.show_ortho_grid,
            "text": space.overlay.show_text,
            "view_border": [float(space.use_render_border), space.render_border_min_x, space.render_border_max_x,
                            space.render_border_min_y, space.render_border_max_y],
        }
    states[k]["camera"] = camera
    screen[KEY] = states
    _engine(scene)
    if camera:
        _save_scene_border(scene)        # once per scene: other camera regions may already have changed it
        frame = _camera_frame(scene, region, rv3d) or (0, 0, region.width, region.height)
        r = scene.render
        r.border_min_x, r.border_max_x = _norm(xa, frame[0], frame[2]), _norm(xb, frame[0], frame[2])
        r.border_min_y, r.border_max_y = _norm(ya, frame[1], frame[3]), _norm(yb, frame[1], frame[3])
        r.use_border = True
    else:
        space.render_border_min_x, space.render_border_max_x = xa / region.width, xb / region.width
        space.render_border_min_y, space.render_border_max_y = ya / region.height, yb / region.height
        space.use_render_border = True
    space.overlay.show_floor = False        # the grid would draw over the render (Cycles gives no depth)
    space.overlay.show_ortho_grid = False
    space.overlay.show_text = True          # render progress
    space.shading.type = 'RENDERED'


def clear_region(context, area=None, screen=None, restore_shading=True):
    """Remove this view's render region and put back what it changed. No-op if the kit set no region here."""
    screen = screen or context.screen
    area = area or context.area
    states = _states(screen)
    k = _area_key(screen, area)
    st = states.pop(k, None) if k is not None else None
    if st is None:
        return False
    if states:
        screen[KEY] = states
    elif KEY in screen:
        del screen[KEY]
    space = area.spaces.active
    vb = list(st["view_border"])
    space.use_render_border = bool(vb[0])
    (space.render_border_min_x, space.render_border_max_x,
     space.render_border_min_y, space.render_border_max_y) = vb[1:]
    scene = bpy.data.scenes.get(st.get("scene", "")) or context.scene
    _restore_scene_border(scene)
    space.overlay.show_floor = bool(st["floor"])
    space.overlay.show_ortho_grid = bool(st["ortho"])
    space.overlay.show_text = bool(st["text"])
    if restore_shading and space.shading.type == 'RENDERED':
        space.shading.type = st["shading"]
    _restore_engine(scene)
    area.tag_redraw()
    return True


def clear_all():
    """Remove every render region in every screen (Softimage mode off)."""
    ctx = bpy.context
    for scr in bpy.data.screens:
        for k in list(_states(scr).keys()):
            try:
                area = scr.areas[int(k)]
            except (IndexError, ValueError):
                area = None
            if area is not None and area.type == 'VIEW_3D':
                clear_region(ctx, area=area, screen=scr)
            else:                                    # area gone or changed type: drop the entry
                st = _states(scr)
                st.pop(k, None)
                if st:
                    scr[KEY] = st
                elif KEY in scr:
                    del scr[KEY]
    for scene in bpy.data.scenes:
        _restore_scene_border(scene)
        _restore_engine(scene)


# --- operator ------------------------------------------------------------------------------------------------

def _window_region(area):
    return next((r for r in area.regions if r.type == 'WINDOW'), None)


class SI_OT_render_region(bpy.types.Operator):
    """Softimage render region: drag a rectangle to render that part of the view live (click to remove)"""
    bl_idname = "si.render_region"
    bl_label = "Render Region"
    bl_options = {'REGISTER'}

    clear: BoolProperty(default=False, options={'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        # any region of a 3D view: the remove button lives in the header
        return context.area is not None and context.area.type == 'VIEW_3D'

    def execute(self, context):
        if self.clear:
            clear_region(context)
        return {'FINISHED'}

    def invoke(self, context, event):
        if self.clear:
            return self.execute(context)
        self.area = context.area
        self.region = context.region if context.region and context.region.type == 'WINDOW' \
            else _window_region(context.area)
        self.start = None
        self.end = None
        self.done = False
        self.handle = bpy.types.SpaceView3D.draw_handler_add(self._draw, (), 'WINDOW', 'POST_PIXEL')
        context.window.cursor_modal_set('CROSSHAIR')
        context.workspace.status_text_set("Render Region   drag: draw the region   click: remove it   Esc: cancel")
        _running.append(self)
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def _draw(self):
        if self.done or self.start is None or self.end is None or bpy.context.region != self.region:
            return
        (x0, y0), (x1, y1) = self.start, self.end
        shader = gpu.shader.from_builtin('UNIFORM_COLOR')
        gpu.state.line_width_set(2.0)
        batch = batch_for_shader(shader, 'LINE_LOOP', {"pos": ((x0, y0), (x1, y0), (x1, y1), (x0, y1))})
        shader.uniform_float("color", (0.85, 0.1, 0.1, 1.0))
        batch.draw(shader)
        gpu.state.line_width_set(1.0)

    def finish(self, context):
        if self.done:
            return
        self.done = True
        try:
            bpy.types.SpaceView3D.draw_handler_remove(self.handle, 'WINDOW')
        except (ValueError, RuntimeError):
            pass
        try:
            context.window.cursor_modal_restore()
            context.workspace.status_text_set(None)
        except Exception:
            pass
        if self in _running:
            _running.remove(self)
        try:
            self.area.tag_redraw()
        except Exception:
            pass

    def cancel(self, context):
        self.finish(context)

    def _inside(self, event):
        r = self.region
        return r is not None and r.x <= event.mouse_x < r.x + r.width and r.y <= event.mouse_y < r.y + r.height

    def modal(self, context, event):
        if self.done:
            return {'CANCELLED', 'PASS_THROUGH'}
        if event.type in {'ESC', 'RIGHTMOUSE'} and event.value == 'PRESS':
            self.finish(context)
            return {'CANCELLED'}
        if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            if not self._inside(event):            # clicked elsewhere: end the tool, let the click through
                self.finish(context)
                return {'CANCELLED', 'PASS_THROUGH'}
            self.start = (event.mouse_x - self.region.x, event.mouse_y - self.region.y)
            self.end = self.start
            return {'RUNNING_MODAL'}
        if event.type == 'MOUSEMOVE':
            if self.start is not None:
                self.end = (max(0, min(self.region.width, event.mouse_x - self.region.x)),
                            max(0, min(self.region.height, event.mouse_y - self.region.y)))
                self.area.tag_redraw()
            return {'RUNNING_MODAL'}
        if event.type == 'LEFTMOUSE' and event.value == 'RELEASE' and self.start is not None:
            (x0, y0), (x1, y1) = self.start, self.end
            self.finish(context)
            dx, dy = abs(x1 - x0), abs(y1 - y0)
            if dx < MIN_PX and dy < MIN_PX:         # a click: remove the region
                clear_region(context, area=self.area)
            elif dx >= MIN_PX and dy >= MIN_PX:
                set_region(context, x0, y0, x1, y1, area=self.area, region=self.region)
            # a long thin drag: ignored
            return {'FINISHED'}
        if event.type in {'MIDDLEMOUSE', 'WHEELUPMOUSE', 'WHEELDOWNMOUSE', 'TRACKPADPAN', 'TRACKPADZOOM'}:
            return {'PASS_THROUGH'}
        if event.value == 'PRESS' and event.type not in {'LEFTMOUSE', 'MOUSEMOVE'}:
            self.finish(context)                   # another key: end the tool, the key does its own thing
            return {'CANCELLED', 'PASS_THROUGH'}
        return {'RUNNING_MODAL'}


classes = (SI_OT_render_region,)


@bpy.app.handlers.persistent
def _on_load_pre(*_args):
    _running.clear()


def register():
    for c in classes:
        bpy.utils.register_class(c)
    bpy.app.handlers.load_pre.append(_on_load_pre)


def unregister():
    if _on_load_pre in bpy.app.handlers.load_pre:
        bpy.app.handlers.load_pre.remove(_on_load_pre)
    for op in list(_running):
        try:
            op.finish(bpy.context)
        except Exception:
            pass
    _running.clear()
    try:
        clear_all()
    except Exception as e:
        print("si_kit: render region restore failed:", e)
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
