# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Alex Doss
"""Softimage mode on/off must leave Blender exactly as it was."""
import importlib

import bpy

KIT = None  # set by run.py


def _m(name):
    return importlib.import_module(KIT + "." + name)


def _theme_snapshot():
    return _m("theme")._dump(bpy.context.preferences.themes[0])


def _tool_panels():
    docks = _m("ui.docks")
    return {c: c.__dict__.get("poll") for c in docks._tool_tab_panels()}


def test_roundtrip_restores_everything():
    mode = _m("mode")
    if mode.is_on():
        mode.exit_mode()
    theme_before = _theme_snapshot()
    draw_left_before = bpy.types.TOPBAR_HT_upper_bar.draw_left
    props_hdr_before = bpy.types.PROPERTIES_HT_header.draw
    v3d_hdr_before = bpy.types.VIEW3D_HT_header.draw
    panels_before = _tool_panels()
    ws_before = set(bpy.data.workspaces.keys())

    mode.enter_mode()
    assert mode.is_on()
    assert bpy.types.TOPBAR_HT_upper_bar.draw_left is not draw_left_before
    assert hasattr(bpy.types, "SI_PT_mcp_transform")
    assert hasattr(bpy.ops.si, "get_primitive")
    ui = bpy.context.preferences.themes[0].view_3d.space.gradients
    assert abs(ui.high_gradient[0] - 108 / 255) < 0.01, "Softimage viewport colour applied"
    ne = bpy.context.preferences.themes[0].node_editor        # spec ui.node-colors
    body = sum(ne.node_backdrop[:3]) / 3
    assert body > 0.7, "node body too dark for black text: %.2f" % body
    assert abs(ne.shader_node[0] - 130 / 255) < 0.01 and abs(ne.output_node[0] - 212 / 255) < 0.01
    assert abs(ne.space.back[0] - 171 / 255) < 0.01
    # Blender's tool-tab panels are wrapped but still registered
    for c in panels_before:
        assert c.is_registered, c

    mode.exit_mode()
    assert not mode.is_on()
    assert bpy.types.TOPBAR_HT_upper_bar.draw_left is draw_left_before
    assert bpy.types.PROPERTIES_HT_header.draw is props_hdr_before, "Properties header not restored"
    assert bpy.types.VIEW3D_HT_header.draw is v3d_hdr_before, "3D View header not restored"
    assert not hasattr(bpy.types.WindowManager, "si_explorer_filter")
    assert not hasattr(bpy.types, "SI_PT_mcp_transform")
    after = _tool_panels()
    for c, poll in panels_before.items():
        assert c.is_registered, "built-in panel not re-registered: %s" % c.__name__
        assert after.get(c) is poll, "poll not restored: %s" % c.__name__
    assert _theme_snapshot() == theme_before, "theme not restored"
    assert set(bpy.data.workspaces.keys()) <= ws_before | {"Softimage"}


def test_roundtrip_twice():
    mode = _m("mode")
    for _ in range(2):
        mode.enter_mode()
        mode.exit_mode()
    assert not mode.is_on()


def _looks_si(t):
    """Our theme's fingerprint: the Softimage button grey on regular widgets."""
    return all(abs(a - b / 255) < 0.005 for a, b in zip(t.user_interface.wcol_regular.inner[:3], (199, 196, 193)))


def test_stale_softimage_theme_never_becomes_the_backup():
    """Bug 2026-11-02 (user): mode off showed the Softimage colours. Preferences had been saved while the mode was
    on, and the backup was gone (it is deleted on mode off), so the next mode on backed up the Softimage theme."""
    import json, os
    mode, theme = _m("mode"), _m("theme")
    if mode.is_on():
        mode.exit_mode()
    t = bpy.context.preferences.themes[0]
    default_regular = tuple(t.user_interface.wcol_regular.inner)    # factory startup: Blender's default theme
    path = theme._backup_path()

    theme.apply(t)                       # preferences as saved while the mode was on ...
    if os.path.exists(path):
        os.remove(path)                  # ... and no backup left
    mode.enter_mode()
    mode.exit_mode()
    assert not _looks_si(t), "mode off kept the Softimage theme (no backup)"
    assert tuple(t.user_interface.wcol_regular.inner) == default_regular, "not Blender's default theme"

    theme.apply(t)                       # a backup that itself holds the Softimage theme is ignored
    with open(path, "w", encoding="utf-8") as f:
        json.dump(theme._dump(t), f)
    mode.enter_mode()
    mode.exit_mode()
    assert not _looks_si(t), "mode off restored a Softimage-coloured backup"

    theme.apply(t)                       # startup with the mode off repairs a stale Softimage theme
    theme.repair()
    assert not _looks_si(t), "startup repair left the Softimage theme"
    assert not os.path.exists(path)
