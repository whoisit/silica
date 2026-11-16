# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Alex Doss
"""Shared harness for the GUI tests (tests/gui_*.py), imported by them (tools/dev.py puts tests/ on sys.path).

    from _gui import Run, win, views3d, reg, key, drag
    R = Run("MY_TEST")                # the result line's name
    s, check, S = R.s, R.check, R.S   # s(fn, wait): queue a step; check(cond, msg): record a failure
    ...
    R.start(0.8)                      # first step after 0.8 s

Steps run one per timer tick; an exception in a step is recorded as a failure (last traceback lines) and the
next step runs. After the last step the result line is printed, exactly once:
`SHOT: <NAME> PASS` or `SHOT: <NAME> FAIL <reasons>`, and tools/dev.py quits Blender right away.

Area and region lookups are done at call time (`views3d()`, `reg(area)`): an editor change or a workspace switch
replaces the regions, and a region held from an earlier step goes stale.
"""
import traceback

import bpy


class Run:
    def __init__(self, name, step=0.3):
        self.name, self.step = name, step
        self.steps, self.errors, self.S = [], [], {}
        self.reported = False

    def s(self, fn, w=None):
        self.steps.append((fn, self.step if w is None else w))

    def check(self, cond, msg):
        if not cond:
            self.errors.append(msg)

    def fail(self, msg):
        self.errors.append(msg)

    def _tick(self):
        if not self.steps:
            self.report()
            return None
        fn, w = self.steps.pop(0)
        try:
            fn()
        except Exception:
            tb = traceback.format_exc().strip().splitlines()
            self.errors.append("%s: %s" % (getattr(fn, "__name__", "step"), " / ".join(tb[-3:])))
        return w

    def report(self):
        if self.reported:
            return
        self.reported = True
        print("SHOT: %s %s" % (self.name, "PASS" if not self.errors else "FAIL " + " | ".join(self.errors)),
              flush=True)
        bpy.app.driver_namespace["si_test_done"] = True      # tools/dev.py: quit now

    def start(self, first=0.8):
        bpy.app.timers.register(self._tick, first_interval=first)


def win():
    return bpy.context.window_manager.windows[0]


def views3d():
    """The 3D views, top-left first."""
    return sorted((a for a in win().screen.areas if a.type == 'VIEW_3D'), key=lambda a: (-a.y, a.x))


def reg(area, kind='WINDOW'):
    return next(r for r in area.regions if r.type == kind)


def center(area):
    return area.x + area.width // 2, area.y + area.height // 2


def key(k, p, **mods):
    """Press and release `k` with the mouse at window position p."""
    w = win()
    w.event_simulate(type='MOUSEMOVE', value='NOTHING', x=p[0], y=p[1])
    w.event_simulate(type=k, value='PRESS', x=p[0], y=p[1], **mods)
    w.event_simulate(type=k, value='RELEASE', x=p[0], y=p[1], **mods)


def drag(a, b, button='LEFTMOUSE', n=8, **mods):
    w = win()
    w.event_simulate(type='MOUSEMOVE', value='NOTHING', x=a[0], y=a[1], **mods)
    w.event_simulate(type=button, value='PRESS', x=a[0], y=a[1], **mods)
    for k in range(1, n + 1):
        w.event_simulate(type='MOUSEMOVE', value='NOTHING', x=a[0] + (b[0] - a[0]) * k // n,
                         y=a[1] + (b[1] - a[1]) * k // n, **mods)
    w.event_simulate(type=button, value='RELEASE', x=b[0], y=b[1], **mods)
