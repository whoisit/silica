# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Alex Doss
"""Viewport maximize (full / horizontal / vertical) and memo cams. Specs: viewport.maximize, viewport.memo-cams.

Maximize moves the splitters between the four Softimage panes (toolbar, MCP and timeline keep their sizes, unlike
Blender's full-screen). The pane rectangles before maximizing are saved on the screen so restore is exact.
Blender header buttons only take left click (user decision 2026-11-01):
    maximize button: click = full, Shift+click = horizontal, Ctrl+click = vertical; F12 over a view = full.
    memo cams: click = recall, Shift+click = store, Ctrl+click = clear.
Right click on the maximize button adds Softimage's items to Blender's button menu.
"""

import bpy
from bpy.props import EnumProperty, IntProperty

MAX_KEY = "si_maximize"     # screen ID property: {"rects": [[x, y, w, h] x4 by pane index], "mode": ...}
MEMO_KEY = "si_memo_cams"   # screen ID property: {area index: {slot: view state}}


def panes(screen):
    from .viewport import _is_pane
    return sorted((a for a in screen.areas if _is_pane(a)), key=lambda a: (-a.y, a.x))


def _area_index(screen, area):
    for i, a in enumerate(screen.areas):
        if a == area:
            return i
    return -1


def _rects(screen):
    return [[a.x, a.y, a.width, a.height] for a in panes(screen)]


# Blender's screen.area_move only runs while the mouse is over no region (screen.active_region is NULL), so it
# fails from a header button or a key over a view. Each splitter move: warp the cursor onto the splitter, let
# Blender process it (one timer tick), move, then the next; finally the cursor goes back where it was.
_busy = []


def _warp(window, x, y):
    if getattr(bpy.app, "use_event_simulate", False):   # tests: real cursor moves are ignored when simulating
        window.event_simulate(type='MOUSEMOVE', value='NOTHING', x=int(x), y=int(y))
    else:
        window.cursor_warp(int(x), int(y))


def _run_moves(window, moves, cursor=None, done=None):
    """moves: callables returning (x, y, delta) in window pixels (computed when run), or None to skip."""
    seq = list(moves)
    state = {"warped": None}
    _busy.append(True)

    def step():
        try:
            if not seq:
                if cursor is not None:
                    _warp(window, cursor[0], cursor[1])
                if done is not None:
                    done()
                _busy.clear()
                return None
            xyd = seq[0]()
            if xyd is None or not xyd[2]:
                seq.pop(0)
                return 0.0
            x, y, d = (int(v) for v in xyd)
            if state["warped"] != (x, y):
                _warp(window, x, y)
                state["warped"] = (x, y)
                return 0.02
            with bpy.context.temp_override(window=window, screen=window.screen):
                if bpy.ops.screen.area_move.poll():
                    bpy.ops.screen.area_move(x=x, y=y, delta=d)
                else:
                    print("si_kit: maximize: Blender refused to move the splitter")
            seq.pop(0)
            state["warped"] = None
            return 0.02
        except Exception as e:                 # never leave a broken timer running
            print("si_kit: maximize:", e)
            _busy.clear()
            return None
    bpy.app.timers.register(step, first_interval=0.0)


def _splitters(screen):
    """Positions of the Softimage block's splitters: horizontal y, top-row x, bottom-row x (window pixels)."""
    p = panes(screen)
    if len(p) != 4:
        return None
    top, bottom = sorted(p[:2], key=lambda a: a.x), sorted(p[2:], key=lambda a: a.x)
    return {"y": bottom[0].y + bottom[0].height, "x_top": top[0].x + top[0].width,
            "x_bottom": bottom[0].x + bottom[0].width, "top": top, "bottom": bottom,
            "x0": min(a.x for a in p), "x1": max(a.x + a.width for a in p),
            "y0": min(a.y for a in p), "y1": max(a.y + a.height for a in p)}


def is_maximized(screen):
    return MAX_KEY in screen


def _restore_moves(screen, rects=None):
    """Moves putting the splitters at the positions of `rects` (pane rectangles) or the middle (reset)."""
    s = _splitters(screen)
    if rects:
        want_y = rects[2][1] + rects[2][3]                 # top edge of the bottom row
        want_xt = rects[0][0] + rects[0][2]
        want_xb = rects[2][0] + rects[2][2]
    else:
        want_y = (s["y0"] + s["y1"]) // 2
        want_xt = want_xb = (s["x0"] + s["x1"]) // 2

    def h():
        s = _splitters(screen)
        return s["top"][0].x + s["top"][0].width // 2, s["y"], want_y - s["y"]

    def vt():
        s = _splitters(screen)
        return s["x_top"], s["top"][0].y + s["top"][0].height // 2, want_xt - s["x_top"]

    def vb():
        s = _splitters(screen)
        return s["x_bottom"], s["bottom"][0].y + s["bottom"][0].height // 2, want_xb - s["x_bottom"]
    return [h, vt, vb]          # horizontal first, so both rows have room


def maximize(context, area, how, cursor=None):
    """how: 'FULL', 'HORIZONTAL' (the pane's row takes the full width), 'VERTICAL' (full height)."""
    screen, window = context.screen, context.window
    s = _splitters(screen)
    if s is None or area not in s["top"] + s["bottom"] or _busy:
        return False
    moves = []
    if is_maximized(screen):                               # another view was maximized: back to the saved sizes
        rects = [list(r) for r in screen[MAX_KEY]["rects"]]
        moves += _restore_moves(screen, rects)
    else:
        rects = _rects(screen)
    screen[MAX_KEY] = {"rects": rects, "mode": how, "area": _area_index(screen, area)}
    in_top = area in s["top"]
    left = area.x == min(a.x for a in (s["top"] if in_top else s["bottom"]))
    if how in ('FULL', 'HORIZONTAL'):
        def row_split():
            s = _splitters(screen)
            row = s["top"] if in_top else s["bottom"]
            split_x = s["x_top"] if in_top else s["x_bottom"]
            return split_x, row[0].y + row[0].height // 2, (s["x1"] if left else s["x0"]) - split_x
        moves.append(row_split)
    if how in ('FULL', 'VERTICAL'):
        def col_split():
            s = _splitters(screen)
            row = s["top"] if in_top else s["bottom"]
            pane = row[0] if left else row[1]
            return pane.x + pane.width // 2, s["y"], (s["y0"] if in_top else s["y1"]) - s["y"]
        moves.append(col_split)
    _run_moves(window, moves, cursor)
    return True


def restore(context, reset=False, cursor=None):
    """Put the four panes back to their saved sizes (reset: equal sizes)."""
    screen = context.screen
    if _splitters(screen) is None or _busy:
        return False
    saved = screen.get(MAX_KEY)
    rects = None if (reset or saved is None) else [list(r) for r in saved["rects"]]

    def done():
        if MAX_KEY in screen:
            del screen[MAX_KEY]
    _run_moves(context.window, _restore_moves(screen, rects), cursor, done)
    return True


class SI_OT_view_maximize(bpy.types.Operator):
    """Maximize this view (Shift: horizontally, Ctrl: vertically); again to restore the four views"""
    bl_idname = "si.view_maximize"
    bl_label = "Maximize"
    bl_options = {'INTERNAL'}

    how: EnumProperty(items=[('AUTO', "Auto", ""), ('FULL', "Maximize", ""), ('HORIZONTAL', "Horizontal", ""),
                             ('VERTICAL', "Vertical", ""), ('RESTORE', "Restore", ""), ('RESET', "Reset Size", "")],
                      default='AUTO', options={'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        return context.area is not None and context.screen is not None and context.window is not None

    def invoke(self, context, event):
        if self.how == 'AUTO':
            self.how = 'HORIZONTAL' if event.shift else 'VERTICAL' if event.ctrl else 'FULL'
            if is_maximized(context.screen):
                self.how = 'RESTORE'
        return self._do(context, (event.mouse_x, event.mouse_y))

    def execute(self, context):
        return self._do(context, None)

    def _do(self, context, cursor):
        if self.how == 'RESTORE':
            restore(context, cursor=cursor)
        elif self.how == 'RESET':
            restore(context, reset=True, cursor=cursor)
        elif not maximize(context, context.area, 'FULL' if self.how == 'AUTO' else self.how, cursor):
            self.report({'INFO'}, "Maximize works on the four Softimage views")
            return {'CANCELLED'}
        return {'FINISHED'}


def _button_menu(self, context):
    """Softimage's right-click menu on the maximize button, added to Blender's button menu."""
    op = getattr(context, "button_operator", None)
    if op is None or getattr(op, "bl_rna", None) is None or op.bl_rna.identifier != "SI_OT_view_maximize":
        return
    layout = self.layout
    layout.separator()
    for how, label in (('FULL', "Maximize"), ('HORIZONTAL', "Horizontal"), ('VERTICAL', "Vertical"),
                       ('RESTORE', "Restore"), ('RESET', "Reset Size")):
        layout.operator("si.view_maximize", text=label).how = how


# --- memo cams ---------------------------------------------------------------------------------------------

def _memo(screen):
    v = screen.get(MEMO_KEY)
    return v.to_dict() if v is not None and hasattr(v, "to_dict") else dict(v or {})


def memo_slot(screen, area, slot):
    return _memo(screen).get(str(_area_index(screen, area)), {}).get(str(slot))


def _view_state(context, space):
    r3 = space.region_3d
    cam = context.scene.camera
    return {"loc": list(r3.view_location), "rot": list(r3.view_rotation), "dist": r3.view_distance,
            "persp": r3.view_perspective, "camera": cam.name if (cam and r3.view_perspective == 'CAMERA') else "",
            "zoom": r3.view_camera_zoom, "offset": list(r3.view_camera_offset)}


def _apply_state(context, space, st):
    r3 = space.region_3d
    persp = st.get("persp", 'PERSP')
    if persp == 'CAMERA':
        cam = bpy.data.objects.get(st.get("camera", ""))
        if cam is not None:
            context.scene.camera = cam
            r3.view_perspective = 'CAMERA'
            r3.view_camera_zoom = st.get("zoom", 0.0)
            r3.view_camera_offset = st.get("offset", (0.0, 0.0))
            return
        persp = 'PERSP'                    # camera gone: fall back to the stored free view
    r3.view_perspective = persp
    r3.view_location = st["loc"]
    r3.view_rotation = st["rot"]
    r3.view_distance = st["dist"]


class SI_OT_memo_cam(bpy.types.Operator):
    """Memo cam: click = recall, Shift+click = store the current view, Ctrl+click = clear"""
    bl_idname = "si.memo_cam"
    bl_label = "Memo Cam"
    bl_options = {'INTERNAL'}

    slot: IntProperty(min=0, max=3)
    action: EnumProperty(items=[('AUTO', "Auto", ""), ('RECALL', "Recall", ""), ('STORE', "Store", ""),
                                ('CLEAR', "Clear", "")], default='AUTO', options={'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        return context.space_data is not None and context.space_data.type == 'VIEW_3D'

    def invoke(self, context, event):
        if self.action == 'AUTO':
            self.action = 'STORE' if event.shift else 'CLEAR' if event.ctrl else 'RECALL'
        return self.execute(context)

    def execute(self, context):
        screen, area, space = context.screen, context.area, context.space_data
        memo = _memo(screen)
        key = str(_area_index(screen, area))
        slots = memo.get(key, {})
        if self.action == 'STORE':
            slots[str(self.slot)] = _view_state(context, space)
        elif self.action == 'CLEAR':
            slots.pop(str(self.slot), None)
        else:
            st = slots.get(str(self.slot))
            if st is None:
                return {'CANCELLED'}          # empty slot: nothing to recall
            _apply_state(context, space, st)
            area.tag_redraw()
            return {'FINISHED'}
        if slots:
            memo[key] = slots
        else:
            memo.pop(key, None)
        screen[MEMO_KEY] = memo
        area.tag_redraw()
        return {'FINISHED'}


def draw_memo_buttons(layout, context):
    row = layout.row(align=True)
    for i in range(4):
        stored = memo_slot(context.screen, context.area, i) is not None
        row.operator("si.memo_cam", text="", icon='CHECKBOX_HLT' if stored else 'CHECKBOX_DEHLT',
                     depress=stored).slot = i


def draw_maximize_button(layout, context):
    on = is_maximized(context.screen)
    layout.operator("si.view_maximize", text="", icon='FULLSCREEN_EXIT' if on else 'FULLSCREEN_ENTER',
                    emboss=False)


classes = (SI_OT_view_maximize, SI_OT_memo_cam)


def register():
    for c in classes:
        bpy.utils.register_class(c)
    bpy.types.UI_MT_button_context_menu.append(_button_menu)


def unregister():
    bpy.types.UI_MT_button_context_menu.remove(_button_menu)
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
