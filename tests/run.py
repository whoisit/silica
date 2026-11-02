# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Alex Doss
"""Test runner, executed inside background Blender by `python -I tools/dev.py test [pattern]`.

Enables the kit, imports every tests/test_*.py and runs its test_* functions in order.
"""
import importlib.util, os, sys, traceback

import addon_utils
import bpy

HERE = os.path.dirname(os.path.abspath(__file__))
MODULE = "bl_ext.user_default.silica"
pattern = sys.argv[sys.argv.index("--") + 1] if "--" in sys.argv and len(sys.argv) > sys.argv.index("--") + 1 else ""

addon_utils.enable(MODULE, default_set=True)
kit = sys.modules[MODULE]

results = []
for fn in sorted(os.listdir(HERE)):
    if not (fn.startswith("test_") and fn.endswith(".py")) or pattern not in fn:
        continue
    spec = importlib.util.spec_from_file_location(fn[:-3], os.path.join(HERE, fn))
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception:
        results.append((fn, "import", traceback.format_exc()))
        continue
    mod.KIT = MODULE
    for name in sorted(n for n in dir(mod) if n.startswith("test_")):
        try:
            getattr(mod, name)()
            results.append((fn, name, None))
        except Exception:
            results.append((fn, name, traceback.format_exc()))

print("=== TESTS")
fails = [r for r in results if r[2]]
for fn, name, err in results:
    print(("FAIL " if err else "ok   ") + fn + "::" + name)
for fn, name, err in fails:
    print("\n--- %s::%s\n%s" % (fn, name, err))
print("%d passed, %d failed" % (len(results) - len(fails), len(fails)))
print("ALL PASSED" if not fails else "FAILURES")
sys.stdout.flush()
