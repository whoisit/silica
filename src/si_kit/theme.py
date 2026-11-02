# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Alex Doss
"""Softimage colours as a Blender theme.

register(): back up the current theme (every writable value of preferences.themes[0]) to a JSON file in the
extension's user folder, then apply the Softimage colours. unregister(): write the backup back and delete it.
If Blender quits while the mode is on, the backup stays on disk and is restored on the next exit.
Colours sampled from Softimage 2015 screenshots (sRGB, 0-255).
"""

import json
import os

import bpy

BACKUP = "theme_backup.json"

UI_GREY = (171, 168, 166)       # window / panel background
UI_DARK_FIELD = (54, 51, 51)    # MCP numeric fields
TEXT = (0, 0, 0)
TEXT_HI = (255, 255, 255)
MENU_BG = (224, 224, 224)
MENU_HI = (50, 50, 126)         # hovered menu item (navy)
PURPLE = (160, 139, 163)        # Softimage accent: camera pill, menu section headers
BUTTON = (199, 196, 193)
OUTLINE = (110, 108, 106)
VIEWPORT = (108, 108, 108)
GRID = (127, 127, 127)
TIMELINE = (140, 140, 140)
SELECT_OBJ = (255, 255, 255)    # Softimage selected objects draw white
# Render Tree (capture 2026-11-01: reference/screens/views/render_tree_nodes.png): Softimage colours three kinds of
# node: shaders green, the Material node and projection / lookup nodes orange, textures and all utility nodes teal.
# Wires: colour connections red, texture-space connections blue (Blender's wire colour is one theme value: red).
SI_SHADER = (130, 159, 114)
SI_MATERIAL = (212, 154, 96)
SI_TEXTURE = (148, 182, 167)
NODE_BODY = (205, 202, 199)
NODE_WIRE = (196, 96, 95)
NODE_COLORS = {
    "shader_node": SI_SHADER,          # BSDFs = Softimage shaders (Phong, Lambert ...)
    "output_node": SI_MATERIAL,        # Material Output = Softimage Material node
    "input_node": SI_MATERIAL,         # Texture Coordinate / UV Map ... = Softimage projection / lookup nodes
    "texture_node": SI_TEXTURE,
    "color_node": SI_TEXTURE,
    "vector_node": SI_TEXTURE,
    "converter_node": SI_TEXTURE,
    "script_node": SI_TEXTURE,
    "attribute_node": SI_TEXTURE,
    "group_node": SI_TEXTURE,
    "geometry_node": SI_TEXTURE,
}
ACTIVE_OBJ = (255, 255, 255)


def c3(rgb):
    return tuple(v / 255.0 for v in rgb)


def c4(rgb, a=255):
    return tuple(v / 255.0 for v in rgb) + (a / 255.0,)


def _set(struct, name, value):
    if not hasattr(struct, name):
        return
    cur = getattr(struct, name)
    try:
        n = len(cur)
    except TypeError:
        n = None
    if n == 4 and len(value) == 3:
        value = tuple(value) + (cur[3],)
    elif n == 3 and len(value) == 4:
        value = tuple(value[:3])
    try:
        setattr(struct, name, value)
    except (AttributeError, TypeError, ValueError):
        pass


def _widget(w, inner, text, inner_sel=None, text_sel=None, outline=OUTLINE, item=None):
    _set(w, "inner", c4(inner))
    _set(w, "text", c3(text))
    _set(w, "outline", c4(outline))
    _set(w, "inner_sel", c4(inner_sel or MENU_HI))
    _set(w, "text_sel", c3(text_sel or TEXT_HI))
    if item:
        _set(w, "item", c4(item))
    _set(w, "shadetop", 0)
    _set(w, "shadedown", 0)
    _set(w, "roundness", 0.15)


def _space(sp, back=UI_GREY, text=TEXT, header=UI_GREY):
    g = getattr(sp, "space", sp)
    _set(g, "back", c4(back))
    _set(g, "header", c4(header))
    _set(g, "header_text", c3(text))
    _set(g, "header_text_hi", c3(TEXT_HI))
    _set(g, "text", c3(text))
    _set(g, "text_hi", c3(TEXT_HI))
    _set(g, "title", c3(text))
    _set(g, "button", c4(UI_GREY))
    _set(g, "button_text", c3(text))
    _set(g, "button_title", c3(text))
    _set(g, "tab_active", c4(BUTTON))
    _set(g, "tab_inactive", c4(UI_GREY))
    _set(g, "tab_back", c4(UI_GREY))
    _set(g, "navigation_bar", c4(UI_GREY))
    _set(g, "execution_buts", c4(UI_GREY))
    pc = getattr(g, "panelcolors", None)
    if pc:
        _set(pc, "header", c4(UI_GREY))
        _set(pc, "back", c4(UI_GREY))
        _set(pc, "sub_back", c4((0, 0, 0), 15))


def apply(theme):
    ui = theme.user_interface
    _widget(ui.wcol_regular, BUTTON, TEXT)
    _widget(ui.wcol_tool, BUTTON, TEXT)
    _widget(ui.wcol_toolbar_item, BUTTON, TEXT)
    _widget(ui.wcol_radio, BUTTON, TEXT, inner_sel=PURPLE, text_sel=TEXT)
    _widget(ui.wcol_toggle, BUTTON, TEXT, inner_sel=PURPLE, text_sel=TEXT)
    _widget(ui.wcol_option, BUTTON, TEXT, inner_sel=BUTTON, item=TEXT)
    _widget(ui.wcol_menu, BUTTON, TEXT, inner_sel=BUTTON, text_sel=TEXT, item=TEXT)
    _widget(ui.wcol_pulldown, UI_GREY, TEXT, inner_sel=MENU_HI)
    _set(ui.wcol_pulldown, "inner", c4(UI_GREY, 0))       # flat menu bar titles, like Softimage
    _set(ui.wcol_pulldown, "outline", c4(UI_GREY, 0))
    _widget(ui.wcol_menu_back, MENU_BG, TEXT, outline=(0, 0, 0))
    _widget(ui.wcol_pie_menu, MENU_BG, TEXT)
    _widget(ui.wcol_menu_item, MENU_BG, TEXT, inner_sel=MENU_HI, text_sel=TEXT_HI)
    _set(ui.wcol_menu_item, "inner", c4(MENU_BG, 0))      # Softimage menu rows: no box, only the highlight
    _set(ui.wcol_menu_item, "outline", c4(MENU_BG, 0))
    _set(ui.wcol_menu_back, "roundness", 0.0)
    _widget(ui.wcol_tooltip, (255, 255, 225), TEXT, outline=(0, 0, 0))
    _widget(ui.wcol_text, UI_DARK_FIELD, TEXT_HI, inner_sel=(90, 90, 90))
    _widget(ui.wcol_num, UI_DARK_FIELD, TEXT_HI, inner_sel=(90, 90, 90), item=(120, 120, 120))
    _widget(ui.wcol_numslider, BUTTON, TEXT, inner_sel=(220, 220, 220), item=(140, 140, 140))
    _widget(ui.wcol_box, UI_GREY, TEXT)
    _widget(ui.wcol_scroll, UI_GREY, TEXT, item=(140, 138, 136))
    _widget(ui.wcol_progress, BUTTON, TEXT, item=PURPLE)
    _widget(ui.wcol_list_item, UI_GREY, TEXT, inner_sel=(219, 255, 255), text_sel=TEXT)
    _widget(ui.wcol_tab, UI_GREY, TEXT, inner_sel=BUTTON, text_sel=TEXT)
    # Blender 5.2: panel colours live in user_interface, some region colours in theme.regions
    _set(ui, "panel_back", c4(UI_GREY))
    _set(ui, "panel_sub_back", c4((0, 0, 0), 15))
    _set(ui, "panel_header", c4((160, 157, 155)))
    _set(ui, "panel_title", c3(TEXT))
    _set(ui, "panel_text", c3(TEXT))
    _set(ui, "panel_outline", c4((120, 118, 116)))
    _set(ui, "panel_active", c4((90, 90, 90)))
    _set(ui, "panel_roundness", 0.1)
    rg = getattr(theme, "regions", None)
    if rg is not None:
        _set(rg.scrubbing, "back", c4(TIMELINE))
        _set(rg.scrubbing, "text", c3(TEXT))
        _set(rg.channels, "back", c3(UI_GREY))
        _set(rg.channels, "text", c3(TEXT))
        _set(rg.sidebars, "back", c4(UI_GREY, 255))
        _set(rg.sidebars, "tab_back", c4(UI_GREY, 255))
    _set(ui, "menu_shadow_fac", 0.2)
    _set(ui, "editor_border", c3((60, 60, 60)))
    _set(ui, "editor_outline", c4((90, 90, 90)))

    for name in ("properties", "topbar", "statusbar", "outliner", "text_editor", "preferences", "info",
                 "file_browser", "console", "node_editor", "image_editor", "sequence_editor", "dopesheet_editor",
                 "graph_editor", "nla_editor", "clip_editor", "spreadsheet"):
        sp = getattr(theme, name, None)
        if sp is not None:
            _space(sp)

    v3 = theme.view_3d
    _space(v3, back=VIEWPORT, header=(155, 154, 154))
    gr = getattr(v3.space, "gradients", None)
    if gr is not None:
        _set(gr, "background_type", 'SINGLE_COLOR')
        _set(gr, "high_gradient", c3(VIEWPORT))
        _set(gr, "gradient", c3(VIEWPORT))
    _set(v3, "grid", c4(GRID, 255))
    _set(v3, "object_selected", c3(SELECT_OBJ))
    _set(v3, "object_active", c3(ACTIVE_OBJ))
    _set(v3, "wire", c3((0, 0, 0)))
    _set(v3, "wire_edit", c3((0, 0, 0)))

    tl = theme.dopesheet_editor
    _space(tl, back=TIMELINE)

    # Render Tree / node editors (spec ui.node-colors): readable light bodies, Softimage colours by node kind
    ne = theme.node_editor
    _space(ne, back=UI_GREY)
    for name, rgb in NODE_COLORS.items():
        _set(ne, name, c4(rgb) if len(getattr(ne, name, ())) == 4 else c3(rgb))
    _set(ne, "node_backdrop", c4(NODE_BODY))
    _set(ne, "grid", c4((158, 155, 153)))
    _set(ne, "wire", c4(NODE_WIRE))
    _set(ne, "wire_inner", c4((120, 118, 116)))
    _set(ne, "wire_select", c4((255, 255, 255)))
    _set(ne, "node_selected", c3((255, 255, 255)))
    _set(ne, "node_active", c3((255, 255, 255)))
    _set(ne, "node_outline", c4((60, 60, 60)))


# --- backup / restore ---------------------------------------------------------------------------------------

def _dump(struct, depth=0):
    out = {}
    for p in struct.bl_rna.properties:
        k = p.identifier
        if k in ("rna_type", "name", "filepath"):
            continue
        if p.type == 'POINTER':
            if depth < 6:
                sub = getattr(struct, k, None)
                if sub is not None:
                    out[k] = _dump(sub, depth + 1)
            continue
        if p.is_readonly or p.type == 'COLLECTION':
            continue
        v = getattr(struct, k)
        try:
            v = tuple(v)
        except TypeError:
            pass
        out[k] = v
    return out


def _load(struct, data):
    for k, v in data.items():
        if isinstance(v, dict):
            sub = getattr(struct, k, None)
            if sub is not None:
                _load(sub, v)
        else:
            try:
                setattr(struct, k, v)
            except (AttributeError, TypeError, ValueError):
                pass


def _backup_path():
    return os.path.join(bpy.utils.extension_path_user(__package__, create=True), BACKUP)


def register():
    from . import prefs
    p = prefs.get()
    if p is not None and not p.apply_theme:
        return
    theme = bpy.context.preferences.themes[0]
    path = _backup_path()
    if not os.path.exists(path):  # keep an older backup: it is the user's real theme
        with open(path, "w", encoding="utf-8") as f:
            json.dump(_dump(theme), f)
    apply(theme)


def unregister():
    path = _backup_path()
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    _load(bpy.context.preferences.themes[0], data)
    os.remove(path)
