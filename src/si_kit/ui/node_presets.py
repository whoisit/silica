# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Alex Doss
"""Render Tree preset panel (spec render.render-tree-presets): search field + category column + node column,
custom-drawn over the left edge of the Shader Editor graph in the Softimage workspace.

Softimage behaviour (user 2026-11-01): click a category = list its nodes; click a node = select it (nothing added);
drag a node onto the graph = add it there. Right click a node = pin / unpin as a favorite (kit addition).
Mouse handling: the panel's own keymap items in the node editor (left / right button, wheel; any modifier, every
value) act inside the panel and pass everything else through to Blender, so nothing clicked on the panel reaches
the graph behind it. They belong to the panel, not to the "Softimage keys" preference. Any error in the panel
code passes the event through (never swallows clicks in the editor). This is the first custom-drawn UI of the kit
(technique for the Explorer).
"""

import json
import os

import blf
import bpy
import gpu
from bpy.props import EnumProperty
from gpu_extras.batch import batch_for_shader

ADDON = __package__.rsplit(".", 1)[0]

# Softimage Render Tree categories, in panel order
CATEGORIES = ["Favorites", "All Nodes", "Illumination", "Toon", "Texture", "Mixers", "Conversion", "Math",
              "Image Processing", "Bump", "Texture Space", "Data", "Light", "Volume", "Output", "Script", "Other"]
# category colour marks: Softimage Render Tree colours (capture 2026-11-01)
_GREEN, _ORANGE, _TEAL = (130, 159, 114), (212, 154, 96), (148, 182, 167)
CAT_COLOR = {"Illumination": _GREEN, "Toon": _GREEN, "Volume": _GREEN, "Output": _ORANGE, "Texture Space": _ORANGE,
             "Data": _ORANGE}

_RULES = (   # (category, test on the node type name without "ShaderNode")
    ("Output", lambda n: n.startswith("Output")),
    ("Toon", lambda n: n in ("BsdfToon",)),
    ("Volume", lambda n: n.startswith("Volume") and n != "VolumeInfo"),
    ("Mixers", lambda n: n in ("MixShader", "AddShader", "Mix", "MixRGB")),
    ("Texture Space", lambda n: n in ("TexCoord", "Mapping", "UVMap", "Tangent", "UVAlongStroke", "RadialTiling")),
    ("Texture", lambda n: n.startswith("Tex")),
    ("Illumination", lambda n: "Bsdf" in n or n in ("Emission", "Holdout", "SubsurfaceScattering", "Background",
                                                     "EeveeSpecular")),
    ("Bump", lambda n: n in ("Bump", "NormalMap", "Normal", "Displacement", "VectorDisplacement")),
    ("Math", lambda n: n in ("Math", "VectorMath", "MapRange", "Clamp", "FloatCurve", "VectorCurve", "Squeeze")),
    ("Image Processing", lambda n: n in ("HueSaturation", "BrightContrast", "Gamma", "Invert", "RGBCurve")),
    ("Conversion", lambda n: n in ("SeparateColor", "CombineColor", "SeparateXYZ", "CombineXYZ", "SeparateRGB",
                                   "CombineRGB", "SeparateHSV", "CombineHSV", "RGBToBW", "ValToRGB", "ShaderToRGB",
                                   "Wavelength", "Blackbody", "VectorRotate", "VectorTransform")),
    ("Light", lambda n: n in ("LightFalloff", "LightPath")),
    ("Script", lambda n: n == "Script"),
    ("Data", lambda n: n in ("Attribute", "NewGeometry", "ObjectInfo", "ParticleInfo", "PointInfo", "CameraData",
                             "Fresnel", "LayerWeight", "Wireframe", "AmbientOcclusion", "Bevel", "Value", "RGB",
                             "VertexColor", "HairInfo", "VolumeInfo", "Gaussian", "Raycast")),
)
# "Other" is only a fallback for nodes of a newer Blender; the test requires it empty for the supported version

# The panel's mouse keys (Node Editor keymap, any modifier): (type, value, operator, properties).
# PRESS / DOUBLE_CLICK act; the other values swallow the rest of a click on the panel (release, click, click-drag)
# so Blender's node select / group enter / links cut never see it. One item per value: never depends on item order.
_REST = ('RELEASE', 'CLICK', 'CLICK_DRAG')
PANEL_KEYS = (
    ('LEFTMOUSE', 'PRESS', "si.node_panel_press", {}),
    ('LEFTMOUSE', 'DOUBLE_CLICK', "si.node_panel_press", {}),
    *(('LEFTMOUSE', v, "si.node_panel_swallow", {}) for v in _REST),
    ('RIGHTMOUSE', 'PRESS', "si.node_panel_rmb", {}),
    *(('RIGHTMOUSE', v, "si.node_panel_swallow", {}) for v in _REST + ('DOUBLE_CLICK',)),
    ('WHEELUPMOUSE', 'PRESS', "si.node_panel_wheel", {"direction": 'UP'}),
    ('WHEELDOWNMOUSE', 'PRESS', "si.node_panel_wheel", {"direction": 'DOWN'}),
)
MAX_ERRORS = 20

state = {"category": "Illumination", "selected": None, "scroll": 0, "search": "", "editing": False, "drag": None}
draw_count = {}        # area pointer -> times drawn (tests)
draw_errors = []
handles = []
_items = []            # (keymap, item) of PANEL_KEYS
_cache = {}


def _error(e):
    if len(draw_errors) < MAX_ERRORS:
        draw_errors.append(repr(e))


# --- catalogue ------------------------------------------------------------------------------------------------

def _creatable():
    """Every shader node type Blender lets us create (tried once in a temporary material, then removed)."""
    if "types" in _cache:
        return _cache["types"]
    mat = bpy.data.materials.new("si_kit_node_catalogue")
    mat.use_nodes = True
    found = []
    try:
        for name in dir(bpy.types):
            cls = getattr(bpy.types, name)
            if not isinstance(cls, type) or not issubclass(cls, bpy.types.ShaderNode):
                continue
            idname = getattr(cls, "bl_idname", name)
            if idname in ("ShaderNodeGroup", "ShaderNodeCustomGroup") or not idname.startswith("ShaderNode"):
                continue
            try:
                n = mat.node_tree.nodes.new(idname)
                found.append((idname, n.bl_rna.name or n.name))
                mat.node_tree.nodes.remove(n)
            except RuntimeError:
                pass
    finally:
        bpy.data.materials.remove(mat)
    _cache["types"] = sorted(found, key=lambda t: t[1].lower())
    return _cache["types"]


def category_of(idname):
    n = idname[len("ShaderNode"):]
    for cat, test in _RULES:
        if test(n):
            return cat
    return "Other"


def catalog():
    """{category: [(idname, label)]} in panel order (Favorites, All Nodes first)."""
    types = _creatable()
    out = {c: [] for c in CATEGORIES}
    labels = dict(types)
    out["Favorites"] = [(i, labels[i]) for i in favorites() if i in labels]
    out["All Nodes"] = list(types)
    for idname, label in types:
        out[category_of(idname)].append((idname, label))
    return out


def search(text):
    t = text.strip().lower()
    return [(i, l) for i, l in _creatable() if t in l.lower()] if t else list(_creatable())


def add_node(tree, idname, location):
    for n in tree.nodes:
        n.select = False
    node = tree.nodes.new(idname)
    node.location = location
    node.select = True
    tree.nodes.active = node
    return node


# --- favorites ------------------------------------------------------------------------------------------------

def favorites_path():
    return os.path.join(bpy.utils.extension_path_user(ADDON, create=True), "node_favorites.json")


def favorites():
    """Pinned node types. A missing or damaged file reads as no favorites (never an error)."""
    if "fav" not in _cache:
        try:
            with open(favorites_path(), encoding="utf-8") as f:
                data = json.load(f)
            _cache["fav"] = [i for i in data if isinstance(i, str)] if isinstance(data, list) else []
        except Exception:
            _cache["fav"] = []
    return list(_cache["fav"])


def toggle_favorite(idname):
    """Pin / unpin; returns True if it is now a favorite. The file is replaced atomically (a crash mid-write
    never empties it); on a write error nothing changes and OSError is raised."""
    old = favorites()
    on = idname not in old
    fav = old + [idname] if on else [i for i in old if i != idname]
    path = favorites_path()
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(fav, f)
        os.replace(tmp, path)
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
    _cache["fav"] = fav
    return on


# --- geometry (shared by drawing and hit testing) -------------------------------------------------------------

def _scale():
    return bpy.context.preferences.system.ui_scale or 1.0


def current_list():
    if state["search"]:
        return search(state["search"])
    return catalog().get(state["category"], [])


def geometry(region):
    """Rectangles (x, y, w, h) in region pixels: panel, search, cats [(name, rect)], nodes [(idname, label, rect)]."""
    us = _scale()
    row = int(18 * us)
    pw = int(270 * us)
    cw = int(112 * us)
    h = region.height
    sh = int(24 * us)
    top = h - sh - int(6 * us)
    g = {"panel": (0, 0, pw, h), "search": (int(4 * us), h - sh - int(3 * us), pw - int(8 * us), sh), "row": row,
         "cats": [], "nodes": []}
    for i, c in enumerate(CATEGORIES):
        y = top - (i + 1) * row
        if y < 0:
            break
        g["cats"].append((c, (0, y, cw, row)))
    items = current_list()
    scroll = max(0, min(state["scroll"], max(0, len(items) - 1)))
    state["scroll"] = scroll
    for i, (idname, label) in enumerate(items[scroll:]):
        y = top - (i + 1) * row
        if y < 0:
            break
        g["nodes"].append((idname, label, (cw, y, pw - cw, row)))
    return g


def _inside(rect, x, y):
    rx, ry, rw, rh = rect
    return rx <= x < rx + rw and ry <= y < ry + rh


def is_active(context):
    area = context.area
    return (area is not None and area.type == 'NODE_EDITOR' and getattr(area, "ui_type", "") == 'ShaderNodeTree'
            and context.workspace is not None and context.workspace.name == "Softimage")


# --- drawing --------------------------------------------------------------------------------------------------

def _rect(shader, x, y, w, h, rgba):
    shader.uniform_float("color", rgba)
    batch_for_shader(shader, 'TRI_FAN', {"pos": ((x, y), (x + w, y), (x + w, y + h), (x, y + h))}).draw(shader)


def _c(rgb, a=1.0):
    return (rgb[0] / 255, rgb[1] / 255, rgb[2] / 255, a)


def _text(x, y, s, rgb=(0, 0, 0), size=11):
    blf.size(0, int(size * _scale()))
    blf.color(0, rgb[0] / 255, rgb[1] / 255, rgb[2] / 255, 1.0)
    blf.position(0, x, y, 0)
    blf.draw(0, s)


def draw():
    ctx = bpy.context
    if not is_active(ctx):
        return
    try:
        region = ctx.region
        g = geometry(region)
        key = ctx.area.as_pointer()
        draw_count[key] = draw_count.get(key, 0) + 1
        us = _scale()
        sh = gpu.shader.from_builtin('UNIFORM_COLOR')
        gpu.state.blend_set('ALPHA')
        px, py, pw, ph = g["panel"]
        _rect(sh, px, py, pw, ph, _c((171, 168, 166)))
        _rect(sh, pw - 1, py, 1, ph, _c((110, 108, 106)))
        cw = g["cats"][0][1][2] if g["cats"] else 0
        _rect(sh, cw, py, 1, ph - g["search"][3] - int(6 * us), _c((140, 138, 136)))
        x, y, w, h = g["search"]
        _rect(sh, x, y, w, h, _c((54, 51, 51)))
        txt = state["search"] + ("|" if state["editing"] else "")
        _text(x + int(6 * us), y + int(6 * us), txt or "Search", (255, 255, 255) if txt else (150, 150, 150))
        pad = int(6 * us)
        for c, (x, y, w, h) in g["cats"]:
            sel = c == state["category"] and not state["search"]
            if sel:
                _rect(sh, x, y, w, h, _c((50, 50, 126)))
            if c in CAT_COLOR or c not in ("Favorites", "All Nodes"):
                _rect(sh, x + pad, y + h // 2 - int(3 * us), int(6 * us), int(6 * us),
                      _c(CAT_COLOR.get(c, _TEAL)))
            _text(x + pad + int(10 * us), y + int(4 * us), c, (255, 255, 255) if sel else (0, 0, 0))
        fav = set(favorites())
        for idname, label, (x, y, w, h) in g["nodes"]:
            sel = idname == state["selected"]
            if sel:
                _rect(sh, x + 1, y, w - 2, h, _c((219, 255, 255)))
            _rect(sh, x + pad, y + h // 2 - int(3 * us), int(6 * us), int(6 * us),
                  _c(CAT_COLOR.get(category_of(idname), _TEAL)))
            _text(x + pad + int(10 * us), y + int(4 * us), label + ("  *" if idname in fav else ""))
        if not g["nodes"]:
            _text(g["nodes"] and 0 or cw + pad, g["search"][1] - g["row"], "No nodes", (90, 90, 90))
        d = state["drag"]
        if d and d.get("dragging"):
            mx, my = d["pos"]
            label = dict(current_list()).get(d["idname"], d["idname"])
            blf.size(0, int(11 * us))
            tw, _th = blf.dimensions(0, label)
            _rect(sh, mx + 12, my - 4, tw + 12, int(18 * us), _c(CAT_COLOR.get(category_of(d["idname"]), _TEAL), 0.9))
            _text(mx + 18, my, label)
        gpu.state.blend_set('NONE')
    except Exception as e:
        _error(e)


# --- input ----------------------------------------------------------------------------------------------------

def _hit(context, event):
    """What the mouse is over: None (not the panel: pass the event on) or (kind, value). Never raises."""
    try:
        return _hit_test(context, event)
    except Exception as e:
        _error(e)
        return None, None


def _hit_test(context, event):
    if not is_active(context) or context.region is None or context.region.type != 'WINDOW':
        return None, None
    x, y = event.mouse_region_x, event.mouse_region_y
    us = _scale()
    if not _inside((0, 0, int(270 * us), context.region.height), x, y):     # cheap test first (= geometry panel)
        return None, None
    g = geometry(context.region)
    if not _inside(g["panel"], x, y):
        return None, g
    if _inside(g["search"], x, y):
        return ("search", None), g
    for c, r in g["cats"]:
        if _inside(r, x, y):
            return ("cat", c), g
    for idname, _l, r in g["nodes"]:
        if _inside(r, x, y):
            return ("node", idname), g
    return ("panel", None), g


class SI_OT_node_panel_press(bpy.types.Operator):
    """Render Tree preset panel: click a category, select a node, drag it onto the graph"""
    bl_idname = "si.node_panel_press"
    bl_label = "Preset Panel"
    bl_options = {'INTERNAL'}

    def invoke(self, context, event):
        hit, g = _hit(context, event)
        if hit is None:
            if state["editing"]:
                state["editing"] = False
                context.area.tag_redraw()
            return {'PASS_THROUGH'}
        kind, val = hit
        area = context.area
        if kind == "search":
            state["editing"] = True
            context.window_manager.modal_handler_add(self)
            self.mode = "search"
            area.tag_redraw()
            return {'RUNNING_MODAL'}
        state["editing"] = False
        if kind == "cat":
            state["category"] = val
            state["search"] = ""
            state["scroll"] = 0
            area.tag_redraw()
            return {'FINISHED'}
        if kind == "node":
            state["selected"] = val
            state["drag"] = {"idname": val, "start": (event.mouse_region_x, event.mouse_region_y),
                             "pos": (event.mouse_region_x, event.mouse_region_y), "dragging": False}
            self.mode = "drag"
            self.region = context.region
            context.window_manager.modal_handler_add(self)
            area.tag_redraw()
            return {'RUNNING_MODAL'}
        return {'FINISHED'}                      # click on the panel background: swallow it

    def modal(self, context, event):
        return self._search(context, event) if self.mode == "search" else self._drag(context, event)

    _MODIFIER_KEYS = {'LEFT_SHIFT', 'RIGHT_SHIFT', 'LEFT_CTRL', 'RIGHT_CTRL', 'LEFT_ALT', 'RIGHT_ALT', 'OSKEY',
                      'APP', 'HYPER'}

    def _search(self, context, event):
        """Only plain typing goes to the field (characters, Backspace, Enter, Esc). Any other press (a mouse
        button anywhere, Ctrl / Alt shortcuts, F keys, arrows...) ends editing and goes on to Blender as usual."""
        area = context.area
        if event.value != 'PRESS' or event.type in self._MODIFIER_KEYS:
            return {'PASS_THROUGH'}
        plain = not (event.ctrl or event.alt or event.oskey)
        if event.type in {'RET', 'NUMPAD_ENTER', 'ESC'}:
            state["editing"] = False
            if event.type == 'ESC':
                state["search"] = ""
            area.tag_redraw()
            return {'FINISHED'}
        if plain and event.type == 'BACK_SPACE':
            state["search"] = state["search"][:-1]
            state["scroll"] = 0
            area.tag_redraw()
            return {'RUNNING_MODAL'}
        if plain and event.unicode and event.unicode.isprintable():
            state["search"] += event.unicode
            state["scroll"] = 0
            area.tag_redraw()
            return {'RUNNING_MODAL'}
        state["editing"] = False
        area.tag_redraw()
        return {'FINISHED', 'PASS_THROUGH'}

    def _drag(self, context, event):
        d = state["drag"]
        r = self.region
        x, y = event.mouse_x - r.x, event.mouse_y - r.y
        if event.type in {'ESC', 'RIGHTMOUSE'} and event.value == 'PRESS':
            state["drag"] = None
            context.area.tag_redraw()
            return {'CANCELLED'}
        if event.type == 'MOUSEMOVE':
            d["pos"] = (x, y)
            if abs(x - d["start"][0]) + abs(y - d["start"][1]) > context.preferences.inputs.drag_threshold_mouse:
                d["dragging"] = True
            context.area.tag_redraw()
            return {'RUNNING_MODAL'}
        if event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
            state["drag"] = None
            context.area.tag_redraw()
            g = geometry(r)
            covered = any(o.type in {'UI', 'TOOLS', 'HEADER', 'TOOL_HEADER'} and o.width > 1 and o.height > 1
                          and _inside((o.x, o.y, o.width, o.height), event.mouse_x, event.mouse_y)
                          for o in context.area.regions)        # Blender's sidebar / toolbar over the graph
            if (d["dragging"] and 0 <= x < r.width and 0 <= y < r.height and not covered
                    and not _inside(g["panel"], x, y)):
                space = context.space_data
                tree = space.edit_tree if space is not None and space.type == 'NODE_EDITOR' else None
                if tree is None:
                    self.report({'WARNING'}, "No material to add the node to")
                    return {'CANCELLED'}
                if not tree.is_editable:
                    self.report({'WARNING'}, "This node tree can't be edited (linked data)")
                    return {'CANCELLED'}
                # node locations are View2D units / UI scale; let Blender convert, as its own Add menu does
                space.cursor_location_from_region(x, y)
                try:
                    add_node(tree, d["idname"], tuple(space.cursor_location))
                except RuntimeError as e:
                    self.report({'WARNING'}, "Could not add %s: %s" % (d["idname"], e))
                    return {'CANCELLED'}
                bpy.ops.ed.undo_push(message="Add %s" % d["idname"])
            return {'FINISHED'}
        return {'RUNNING_MODAL'}


class SI_OT_node_panel_rmb(bpy.types.Operator):
    """Render Tree preset panel: right click a node to pin / unpin it as a favorite"""
    bl_idname = "si.node_panel_rmb"
    bl_label = "Pin Node"
    bl_options = {'INTERNAL'}

    def invoke(self, context, event):
        hit, _g = _hit(context, event)
        if hit is None:
            return {'PASS_THROUGH'}
        if hit[0] == "node":
            try:
                toggle_favorite(hit[1])
            except OSError as e:
                self.report({'WARNING'}, "Favorites not saved: %s" % e)
            context.area.tag_redraw()
        return {'FINISHED'}


class SI_OT_node_panel_swallow(bpy.types.Operator):
    """Render Tree preset panel: the rest of a click on the panel (release, click, drag, any modifier) stays there"""
    bl_idname = "si.node_panel_swallow"
    bl_label = "Preset Panel Event"
    bl_options = {'INTERNAL'}

    def invoke(self, context, event):
        hit, _g = _hit(context, event)
        return {'PASS_THROUGH'} if hit is None else {'FINISHED'}


class SI_OT_node_tab(bpy.types.Operator):
    """Softimage Tab in the Render Tree: the Add menu (Blender's Tab, group edit, everywhere else)"""
    bl_idname = "si.node_tab"
    bl_label = "Add Node (Tab)"
    bl_options = {'INTERNAL'}

    def invoke(self, context, event):
        if not is_active(context):
            return {'PASS_THROUGH'}
        bpy.ops.wm.call_menu('INVOKE_DEFAULT', name="NODE_MT_add")
        return {'FINISHED'}


def scroll_at(region, x, y, direction):
    """Wheel at region point (x, y): scroll the node column if over the panel. Returns True if it scrolled
    (the operator then swallows the wheel), False if the wheel belongs to the graph (zoom)."""
    if not _inside(geometry(region)["panel"], x, y):
        return False
    state["scroll"] = max(0, state["scroll"] + (3 if direction == 'DOWN' else -3))
    return True


class SI_OT_node_panel_wheel(bpy.types.Operator):
    """Render Tree preset panel: scroll the node column"""
    bl_idname = "si.node_panel_wheel"
    bl_label = "Scroll Presets"
    bl_options = {'INTERNAL'}

    direction: EnumProperty(items=[('UP', "Up", ""), ('DOWN', "Down", "")])

    def invoke(self, context, event):
        try:
            if not is_active(context) or context.region is None or context.region.type != 'WINDOW':
                return {'PASS_THROUGH'}
            if not scroll_at(context.region, event.mouse_region_x, event.mouse_region_y, self.direction):
                return {'PASS_THROUGH'}
        except Exception as e:
            _error(e)
            return {'PASS_THROUGH'}
        context.area.tag_redraw()
        return {'FINISHED'}


classes = (SI_OT_node_panel_press, SI_OT_node_panel_rmb, SI_OT_node_panel_swallow, SI_OT_node_panel_wheel,
           SI_OT_node_tab)


def _warm_catalogue():
    """Build the node catalogue once after mode entry, outside drawing (it creates a temporary material)."""
    if handles:
        try:
            _creatable()
        except Exception as e:
            _error(e)
    return None


def _bind_keys():
    """PANEL_KEYS in the Node Editor keymap and in every node tool keymap: the active tool's keymap (Tweak,
    Select Box, Links Cut...) runs before the editor keymap and would select / cut behind the panel."""
    wm = bpy.context.window_manager
    kc = wm.keyconfigs.addon
    if kc is None:          # background mode
        return
    for default in wm.keyconfigs.default.keymaps:
        tool = default.name.startswith("Node Tool:")
        if default.name != "Node Editor" and not tool:
            continue
        km = kc.keymaps.new(name=default.name, space_type=default.space_type, region_type=default.region_type,
                            tool=tool)
        for key, value, op, props in PANEL_KEYS:
            if tool and not key.endswith("MOUSE"):
                continue
            if tool and key.startswith("WHEEL"):
                continue
            kmi = km.keymap_items.new(op, key, value, any=True)
            for k, v in props.items():
                setattr(kmi.properties, k, v)
            _items.append((km, kmi))


def register():
    for c in classes:
        bpy.utils.register_class(c)
    handles.append(bpy.types.SpaceNodeEditor.draw_handler_add(draw, (), 'WINDOW', 'POST_PIXEL'))
    _bind_keys()
    bpy.app.timers.register(_warm_catalogue, first_interval=0.5)


def unregister():
    for km, kmi in _items:
        try:
            km.keymap_items.remove(kmi)
        except (ReferenceError, RuntimeError):
            pass
    _items.clear()
    if bpy.app.timers.is_registered(_warm_catalogue):
        bpy.app.timers.unregister(_warm_catalogue)
    while handles:
        bpy.types.SpaceNodeEditor.draw_handler_remove(handles.pop(), 'WINDOW')
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
    state.update(drag=None, editing=False)
    draw_count.clear()
    draw_errors.clear()
    _cache.pop("fav", None)
