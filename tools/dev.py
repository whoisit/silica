# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Alex Doss
"""Dev launcher: Blender 5.2 with an isolated user profile (.dev/user), the kit linked in as an extension.

    python -I tools/dev.py link                 # junction .dev/user/extensions/user_default/<id> -> src/si_kit
    python -I tools/dev.py enable               # enable the extension in the dev profile (background)
    python -I tools/dev.py gui                  # open Blender (dev profile)
    python -I tools/dev.py shot OUT.png [--script s.py] [--mode on|off] [--size 1600x900] [--wait 3]
                                               # open Blender, optionally run a script, screenshot the window, quit
    python -I tools/dev.py test [pattern]       # run tests/test_*.py in background Blender
    python -I tools/dev.py guitest              # run tests/gui_*.py in a GUI Blender (simulated input)
    python -I tools/dev.py check quick|gui|real|full      # test groups (tests/README.md: which group runs when)
    python -I tools/dev.py check feature <spec id>        # the tests listed in that spec's `tests:`

Your normal Blender preferences are never touched (BLENDER_USER_RESOURCES points at .dev/user).
"""
import os, re, subprocess, sys, textwrap

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEV = os.path.join(ROOT, ".dev")


def _blender_path():
    """Blender 5.2 executable: $SI_BLENDER, else the first line of .dev/blender_path.txt, else `blender` on PATH."""
    if os.environ.get("SI_BLENDER"):
        return os.environ["SI_BLENDER"]
    local = os.path.join(DEV, "blender_path.txt")
    if os.path.isfile(local):
        line = open(local, encoding="utf-8").readline().strip()
        if line:
            return line
    return "blender"


BLENDER = _blender_path()
USER = os.path.join(DEV, "user")
EXT_ID = "silica"
MODULE = "bl_ext.user_default." + EXT_ID
SRC = os.path.join(ROOT, "src", "si_kit")


def env():
    e = dict(os.environ)
    e["BLENDER_USER_RESOURCES"] = USER
    e["SI_KIT_ROOT"] = ROOT
    return e


def link():
    dst_dir = os.path.join(USER, "extensions", "user_default")
    os.makedirs(dst_dir, exist_ok=True)
    dst = os.path.join(dst_dir, EXT_ID)
    if os.path.exists(dst):
        return dst
    subprocess.check_call(["cmd", "/c", "mklink", "/J", dst, SRC], stdout=subprocess.DEVNULL)
    return dst


def run_blender(args, timeout=600):
    p = subprocess.run([BLENDER] + args, env=env(), capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=timeout)
    return p


def write_tmp(name, code):
    os.makedirs(os.path.join(DEV, "tmp"), exist_ok=True)
    path = os.path.join(DEV, "tmp", name)
    open(path, "w", encoding="utf-8").write(code)
    return path


ENABLE = textwrap.dedent('''
    import bpy, addon_utils
    bpy.ops.extensions.repo_refresh_all() if hasattr(bpy.ops.extensions, "repo_refresh_all") else None
    mod = "%s"
    addon_utils.enable(mod, default_set=True, handle_error=None)
    print("ENABLED", mod in bpy.context.preferences.addons)
    bpy.context.preferences.view.show_splash = False
    bpy.ops.wm.save_userpref()
''' % MODULE)


SHOT = '''
import bpy, sys, os, traceback
OUT = %(out)r
SCRIPT = %(script)r
MODE = %(mode)r
WAIT = %(wait)s
SIZE = %(size)r

def log(*a):
    print("SHOT:", *a, flush=True)

def step1():
    try:
        import importlib
        kit = importlib.import_module(%(module)r)
        from importlib import import_module
        mode = import_module(%(module)r + ".mode")
        if MODE == "on" and not mode.is_on():
            mode.enter_mode()
        elif MODE == "off" and mode.is_on():
            mode.exit_mode()
        p = import_module(%(module)r + ".prefs").get()
        if SCRIPT and p is not None:
            # scripted runs: no PPG popup after Get > Primitive (it would take the test's mouse input);
            # put back before quitting so the dev profile keeps the user's setting
            _saved["ppg_on_create"] = p.ppg_on_create
            p.ppg_on_create = False
        if SCRIPT:
            g = {"__name__": "__shot__", "bpy": bpy}
            exec(compile(open(SCRIPT, encoding="utf-8").read(), SCRIPT, "exec"), g)
    except Exception:
        log("ERROR", traceback.format_exc())
    bpy.app.timers.register(step2, first_interval=WAIT)
    return None

_saved = {}


def step2():
    try:
        import importlib
        p = importlib.import_module(%(module)r + ".prefs").get()
        if p is not None and "ppg_on_create" in _saved:
            p.ppg_on_create = _saved["ppg_on_create"]
        win = bpy.context.window_manager.windows[0]
        with bpy.context.temp_override(window=win):
            bpy.ops.screen.screenshot(filepath=OUT)
        log("saved", OUT)
    except Exception:
        log("ERROR", traceback.format_exc())
    bpy.app.timers.register(lambda: bpy.ops.wm.quit_blender() and None, first_interval=0.3)
    return None

bpy.app.timers.register(step1, first_interval=1.0)
'''


def _gui_files(real):
    out = []
    for fn in sorted(os.listdir(os.path.join(ROOT, "tests"))):
        if fn.startswith("gui_") and fn.endswith(".py"):
            src = open(os.path.join(ROOT, "tests", fn), encoding="utf-8").read()
            is_real = bool(re.search(r"^# SIMULATE:\s*0", src, re.M))
            if is_real == real:
                out.append(fn)
    return out


def _run_gui(files):
    """Run GUI test files; returns (all passed, report lines)."""
    ok, lines = True, []
    for fn in files:
        src = open(os.path.join(ROOT, "tests", fn), encoding="utf-8").read()
        m = re.search(r"^# WAIT:\s*(\d+)", src, re.M)
        wait = m.group(1) if m else "12"
        sim = "0" if re.search(r"^# SIMULATE:\s*0", src, re.M) else "1"
        line = []
        for attempt in range(2 if sim == "0" else 1):     # real input: the user's own mouse can interfere
            out = os.path.abspath(os.path.join(DEV, "shots", fn[:-3] + ".png"))
            code = SHOT % {"out": out, "script": os.path.join(ROOT, "tests", fn), "mode": "on",
                           "wait": float(wait), "size": "1600x900", "module": MODULE}
            extra = ["--enable-event-simulate"] if sim == "1" else []
            p = run_blender(extra + ["--window-geometry", "0", "0", "1600", "900",
                                     "--python", write_tmp("shot.py", code)], timeout=300)
            line = [l for l in (p.stdout + p.stderr).splitlines() if l.startswith("SHOT:") and ("PASS" in l or "FAIL" in l)]
            if line and "FAIL" not in line[0]:
                break
        res = line[0] if line else "SHOT: no result (timed out?)"
        ok = ok and bool(line) and "FAIL" not in line[0]
        lines.append("%-30s %s" % (fn, res[:400]))
    return ok, lines


def _run_background(pattern=""):
    p = run_blender(["--background", "--factory-startup", "--python", os.path.join(ROOT, "tests", "run.py"),
                     "--", pattern], timeout=900)
    out = p.stdout + p.stderr
    summary = [l for l in out.splitlines() if l.startswith(("ok ", "FAIL ")) or "passed," in l]
    fails = out[out.find("--- "):out.find("passed,")] if "FAILURES" in out else ""
    return "ALL PASSED" in out, summary + ([fails[-3000:]] if fails else [])


def _spec_tests(spec_id):
    import json as _json
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import roadmap
    for root, _d, files in os.walk(os.path.join(ROOT, "features")):
        if "spec.md" in files and "_template" not in root:
            meta = roadmap.parse(os.path.join(root, "spec.md"))
            if meta["id"] == spec_id:
                t = meta.get("tests", [])
                return t if isinstance(t, list) else [t]
    raise SystemExit("no spec with id " + spec_id)


def check(group, args):
    """Test groups, see tests/README.md. Returns an exit code."""
    link()
    results = []
    ok = True
    if group in ("quick", "full"):
        r = subprocess.run([sys.executable, "-I", os.path.join(ROOT, "tools", "roadmap.py"), "--check"],
                           capture_output=True, text=True)
        results.append("specs: " + r.stdout.strip())
        ok = ok and r.returncode == 0
        passed, lines = _run_background()
        results += lines
        ok = ok and passed
    if group in ("gui", "full"):
        passed, lines = _run_gui(_gui_files(real=False))
        results += lines
        ok = ok and passed
    if group in ("real", "full"):
        passed, lines = _run_gui(_gui_files(real=True))
        results += lines
        ok = ok and passed
    if group == "feature":
        files = [os.path.basename(t) for t in _spec_tests(args[0])]
        bg = [f for f in files if f.startswith("test_")]
        gui = [f for f in files if f.startswith("gui_")]
        for f in [f for f in files if f.startswith("scn_")]:   # plain-Python reader checks (no Blender)
            r = subprocess.run([sys.executable, "-I", os.path.join(ROOT, "tests", f)], capture_output=True, text=True)
            lines = (r.stdout + r.stderr).strip().splitlines()
            results.append("%s %s: %s" % ("ok  " if r.returncode == 0 else "FAIL", f, " | ".join(lines[-4:])))
            ok = ok and r.returncode == 0
        for f in bg:
            passed, lines = _run_background(f[:-3])
            results += lines
            ok = ok and passed
        if gui:
            passed, lines = _run_gui(gui)
            results += lines
            ok = ok and passed
        if not files:
            results.append("spec %s lists no tests" % args[0])
            ok = False
    print("\n".join(results))
    print("CHECK %s: %s" % (group, "PASS" if ok else "FAIL"))
    return 0 if ok else 1


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "gui"
    if cmd == "link":
        print(link())
    elif cmd == "enable":
        link()
        p = run_blender(["--background", "--python", write_tmp("enable.py", ENABLE)])
        print("\n".join(l for l in p.stdout.splitlines() if "ENABLED" in l or "Error" in l or "rror" in l)[-3000:])
        print(p.stderr[-2000:])
    elif cmd == "gui":
        link()
        subprocess.Popen([BLENDER] + sys.argv[2:], env=env())
    elif cmd == "shot":
        link()
        out = os.path.abspath(sys.argv[2])
        args = sys.argv[3:]
        opt = {"--script": "", "--mode": "", "--size": "1600x900", "--wait": "3", "--simulate": "0"}
        for i in range(0, len(args), 2):
            opt[args[i]] = args[i + 1]
        script = os.path.abspath(opt["--script"]) if opt["--script"] else ""
        w, h = opt["--size"].split("x")
        code = SHOT % {"out": out, "script": script, "mode": opt["--mode"], "wait": float(opt["--wait"]),
                       "size": opt["--size"], "module": MODULE}
        extra = ["--enable-event-simulate"] if opt["--simulate"] == "1" else []
        p = run_blender(extra + ["--window-geometry", "0", "0", w, h, "--python", write_tmp("shot.py", code)],
                        timeout=300)
        print("\n".join(l for l in (p.stdout + p.stderr).splitlines()
                        if l.startswith("SHOT") or "Error" in l or "Traceback" in l or "si_kit" in l)[-6000:])
    elif cmd == "check":
        sys.exit(check(sys.argv[2] if len(sys.argv) > 2 else "quick", sys.argv[3:]))
    elif cmd == "guitest":
        link()
        ok = True
        for fn in sorted(os.listdir(os.path.join(ROOT, "tests"))):
            if not (fn.startswith("gui_") and fn.endswith(".py")):
                continue
            src = open(os.path.join(ROOT, "tests", fn), encoding="utf-8").read()
            import re as _re
            m = _re.search(r"^# WAIT:\s*(\d+)", src, _re.M)       # a test can ask for more time
            wait = m.group(1) if m else "12"
            sim = "0" if _re.search(r"^# SIMULATE:\s*0", src, _re.M) else "1"   # real-input tests opt out
            sys.argv = [sys.argv[0], "shot", os.path.join(DEV, "shots", fn[:-3] + ".png"), "--mode", "on",
                        "--simulate", sim, "--wait", wait, "--script", os.path.join(ROOT, "tests", fn)]
            import io, contextlib
            for attempt in range(2 if sim == "0" else 1):     # real-input tests: the user's own mouse can interfere
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    main()
                line = [l for l in buf.getvalue().splitlines() if "PASS" in l or "FAIL" in l]
                if line and "FAIL" not in line[0]:
                    break
            print(fn, "->", line[0] if line else buf.getvalue()[-500:])
            ok = ok and bool(line) and "FAIL" not in line[0]
        sys.exit(0 if ok else 1)
    elif cmd == "test":
        link()
        pat = sys.argv[2] if len(sys.argv) > 2 else ""
        p = run_blender(["--background", "--factory-startup", "--python", os.path.join(ROOT, "tests", "run.py"),
                         "--", pat], timeout=900)
        out = p.stdout + p.stderr
        start = out.find("=== TESTS")
        print(out[start:] if start >= 0 else out[-6000:])
        sys.exit(0 if "ALL PASSED" in out else 1)


if __name__ == "__main__":
    main()
