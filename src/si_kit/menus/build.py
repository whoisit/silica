# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Alex Doss
"""Build Blender Menu classes from the Softimage menu data (data.py) and the mapping (map.py).

Every Softimage submenu becomes one bpy.types.Menu (SI_MT_<hash>). Leaf items are drawn as the mapped Blender
action, or greyed out (si.unmapped) when the kit doesn't do them yet, so the whole Softimage menu is always
visible. TOP_IDS maps the main menu bar labels to their menu idnames.
"""

import hashlib

import bpy

from . import data
from .map import MAP

TOP_IDS = {}       # "File" -> "SI_MT_..."
EXTRA_IDS = {}     # "Viewport Camera" -> "SI_MT_..."
ALL_PATHS = set()  # every leaf/menu path, for tests and the coverage report
_classes = []


def idname(path):
    return "SI_MT_" + hashlib.md5(path.encode("utf-8")).hexdigest()[:10]


def _draw_items(layout, items, path):
    header = None
    for it in items:
        kind = it[0]
        if kind == "sep":
            layout.separator()
            continue
        if kind == "header":
            header = it[1]
            layout.label(text=header)
            continue
        label = it[1]
        p = "/".join(x for x in (path, header, label) if x)
        if kind == "menu":
            m = MAP.get(p)
            if m and m[0] == "menu":
                layout.menu(m[1], text=label)
            elif it[2]:
                layout.menu(idname(p), text=label)
            else:
                _grey(layout, label, p)
            continue
        m = MAP.get(p)
        if m is None:
            _grey(layout, label, p)
        elif m[0] == "op":
            try:
                op = layout.operator(m[1], text=label)
            except Exception:
                _grey(layout, label, p)
                continue
            if op is not None:
                for k, v in m[2].items():
                    try:
                        setattr(op, k, v)
                    except (AttributeError, TypeError):
                        pass
        elif m[0] == "prim":
            layout.operator("si.get_primitive", text=label).kind = m[1]
        elif m[0] == "menu":
            layout.menu(m[1], text=label)
        else:
            _grey(layout, label, p)


def _grey(layout, label, path):
    row = layout.row()
    row.enabled = False
    row.operator("si.unmapped", text=label).path = path


def _make(path, label, items):
    def draw(self, context):
        _draw_items(self.layout, items, path)
    cls = type(idname(path), (bpy.types.Menu,), {"bl_idname": idname(path), "bl_label": label, "draw": draw})
    _classes.append(cls)
    _walk(items, path)
    return cls


def _walk(items, path):
    header = None
    for it in items:
        if it[0] == "header":
            header = it[1]
        elif it[0] in ("item", "menu"):
            p = "/".join(x for x in (path, header, it[1]) if x)
            ALL_PATHS.add(p)
            if it[0] == "menu" and it[2]:
                _make(p, it[1], it[2])


def build():
    _classes.clear()
    TOP_IDS.clear()
    EXTRA_IDS.clear()
    ALL_PATHS.clear()
    for title in data.TOP:
        _make(title, title, data.MENUS[title])
        TOP_IDS[title] = idname(title)
    for title, items in data.EXTRA.items():
        _make(title, title, items)
        EXTRA_IDS[title] = idname(title)


def coverage():
    """{top menu: (mapped, total)} for leaf items."""
    out = {}
    for p in ALL_PATHS:
        top = p.split("/", 1)[0]
        m, t = out.get(top, (0, 0))
        out[top] = (m + (1 if p in MAP else 0), t + 1)
    return out


def register():
    build()
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
    _classes.clear()
