# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Alex Doss
"""Silica: a Softimage layer for Blender (frontend, skin and workflow).

Two layers:
- always registered: preferences + the mode switch (so you can always get back to plain Blender);
- "Softimage mode" (MODE_MODULES): theme, top menu bar, layout, docks, operators. Switching the mode off
  unregisters them, which puts back everything they changed.
"""

from . import prefs, mode

ALWAYS = (prefs, mode)


def register():
    for m in ALWAYS:
        m.register()
    mode.restore_on_startup()


def unregister():
    mode.exit_mode(keep_flag=True)
    for m in reversed(ALWAYS):
        m.unregister()
