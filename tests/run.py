# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Alex Doss
"""Test runner, executed inside background Blender by `python -I tools/dev.py test [pattern ...]`.

Enables the kit, imports every tests/test_*.py whose name contains one of the patterns and runs its test_*
functions in order. A pattern `file.py::test_name` runs that one function.

A test that needs private data it can't find raises `Skip("why")` (injected into every test module): it is
reported as `skip`, and as a failure when SI_REQUIRE_PRIVATE=1 (set by tools/dev.py on the owner's machine).
No test run at all is a failure too (a spec pointing at a renamed file would otherwise pass).
"""
import importlib.util, os, sys, traceback

import addon_utils
import bpy

HERE = os.path.dirname(os.path.abspath(__file__))
MODULE = "bl_ext.user_default.silica"
patterns = [a for a in sys.argv[sys.argv.index("--") + 1:] if a] if "--" in sys.argv else []
REQUIRE = os.environ.get("SI_REQUIRE_PRIVATE") == "1"


class Skip(Exception):
    """Raised by a test that can't run here (private scenes absent)."""


def wanted(fn, name=None):
    if not patterns:
        return True
    for p in patterns:
        f, _sep, func = p.partition("::")
        if f in fn and (not func or name is None or func == name):
            return True
    return False


addon_utils.enable(MODULE, default_set=True)
kit = sys.modules[MODULE]

results = []   # (file, name, state, detail): state ok / skip / FAIL
for fn in sorted(os.listdir(HERE)):
    if not (fn.startswith("test_") and fn.endswith(".py")) or not wanted(fn):
        continue
    spec = importlib.util.spec_from_file_location(fn[:-3], os.path.join(HERE, fn))
    mod = importlib.util.module_from_spec(spec)
    mod.Skip = Skip
    try:
        spec.loader.exec_module(mod)
    except Exception:
        results.append((fn, "import", "FAIL", traceback.format_exc()))
        continue
    mod.KIT = MODULE
    mod.Skip = Skip         # again: a module may define a stand-in Skip for linters
    for name in sorted(n for n in dir(mod) if n.startswith("test_")):
        if not callable(getattr(mod, name)) or not wanted(fn, name):
            continue
        try:
            getattr(mod, name)()
            results.append((fn, name, "ok", None))
        except Skip as e:
            results.append((fn, name, "FAIL" if REQUIRE else "skip",
                            "skipped, but this machine requires private data (SI_REQUIRE_PRIVATE): %s" % e
                            if REQUIRE else str(e)))
        except Exception:
            results.append((fn, name, "FAIL", traceback.format_exc()))

print("=== TESTS")
for fn, name, state, detail in results:
    print("%-5s%s::%s%s" % (state, fn, name, ("  (%s)" % detail) if state == "skip" else ""))
fails = [r for r in results if r[2] == "FAIL"]
for fn, name, state, detail in fails:
    print("\n--- %s::%s\n%s" % (fn, name, detail))
n = {s: sum(1 for r in results if r[2] == s) for s in ("ok", "skip", "FAIL")}
print("%d passed, %d skipped, %d failed" % (n["ok"], n["skip"], n["FAIL"]))
if not results:
    print("NO TESTS matched %r" % patterns)
print("ALL PASSED" if results and not fails else "FAILURES")
sys.stdout.flush()
