# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Alex Doss
"""Dev launcher: Blender 5.2 with an isolated user profile (.dev/user), the kit linked in as an extension.

    python -I tools/dev.py link                 # junction .dev/user/extensions/user_default/<id> -> src/si_kit
    python -I tools/dev.py enable               # enable the extension in the dev profile (background)
    python -I tools/dev.py gui                  # open Blender (dev profile)
    python -I tools/dev.py shot OUT.png [--script s.py] [--mode on|off] [--size 1600x900] [--wait 3]
                                               # open Blender, optionally run a script, screenshot the window, quit
    python -I tools/dev.py test [pattern ...]   # run tests/test_*.py in background Blender (file.py::test_x: one)
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


def _require_private():
    """True on the owner's machine: a `.dev/require_private` file in this checkout or in the main one (worktrees
    share it). Tests that skip for missing private scenes then fail instead of passing silently."""
    if os.environ.get("SI_REQUIRE_PRIVATE") in ("0", "1"):
        return os.environ["SI_REQUIRE_PRIVATE"] == "1"
    roots = [ROOT]
    try:
        common = subprocess.run(["git", "-C", ROOT, "rev-parse", "--path-format=absolute", "--git-common-dir"],
                                capture_output=True, text=True).stdout.strip()
        if common:
            roots.append(os.path.dirname(common))
    except OSError:
        pass
    return any(os.path.isfile(os.path.join(r, ".dev", "require_private")) for r in roots)


REQUIRE_PRIVATE = _require_private()


def env():
    e = dict(os.environ)
    e["BLENDER_USER_RESOURCES"] = USER
    e["SI_KIT_ROOT"] = ROOT
    e["SI_REQUIRE_PRIVATE"] = "1" if REQUIRE_PRIVATE else "0"
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
    """Run Blender; a run past `timeout` is killed and returned with returncode None and what it printed."""
    try:
        return subprocess.run([BLENDER] + args, env=env(), capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired as e:
        def text(b):
            return b.decode("utf-8", "replace") if isinstance(b, bytes) else (b or "")
        return subprocess.CompletedProcess(e.cmd, None, text(e.stdout),
                                           text(e.stderr) + "\nTIMEOUT after %ss" % timeout)


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
SIM = %(sim)r

def log(*a):
    print("SHOT:", *a, flush=True)

import builtins, re as _re, time as _time
_state = {"done": False, "t0": 0.0}
_RESULT = _re.compile(r"^SHOT: \\S+ (PASS|FAIL)")

def _print(*a, **k):
    """The test's print: its result line (`SHOT: NAME PASS|FAIL ...`) ends the run."""
    builtins.print(*a, **k)
    if _RESULT.match(k.get("sep", " ").join(str(x) for x in a)):
        _state["done"] = True

def _banner():
    """A strip along the bottom of the 3D views and node editors while a test runs: red for real input (the
    cursor moves on its own: hands off), grey for simulated input (real mouse and keys are ignored)."""
    try:
        import blf, gpu
        from gpu_extras.batch import batch_for_shader
        r = bpy.context.region
        sc = bpy.context.preferences.system.ui_scale
        w, h = r.width, int(24 * sc)
        real = SIM == "0"
        sh = gpu.shader.from_builtin('UNIFORM_COLOR')
        b = batch_for_shader(sh, 'TRI_FAN', {"pos": [(0, 0), (w, 0), (w, h), (0, h)]})
        gpu.state.blend_set('ALPHA')
        sh.bind()
        sh.uniform_float("color", (0.75, 0.07, 0.07, 0.95) if real else (0.1, 0.1, 0.1, 0.7))
        b.draw(sh)
        gpu.state.blend_set('NONE')
        msg = ("SILICA TEST: HANDS OFF THE MOUSE, the cursor moves on its own" if real else
               "Silica test running (simulated input): your mouse and keys are ignored in this window")
        blf.size(0, int(12 * sc))
        blf.color(0, 1, 1, 1, 1)
        blf.position(0, int(8 * sc), int(7 * sc), 0)
        blf.draw(0, msg)
    except Exception:
        pass

_handles = []

def _show_banner():
    for space in (bpy.types.SpaceView3D, bpy.types.SpaceNodeEditor):
        _handles.append((space, space.draw_handler_add(_banner, (), 'WINDOW', 'POST_PIXEL')))

def _watch():
    if _state["done"] or bpy.app.driver_namespace.get("si_test_done"):   # tests/_gui.py sets the flag
        bpy.app.timers.register(step2, first_interval=0.3)   # let the last redraw land in the screenshot
        return None
    if _time.time() - _state["t0"] > WAIT:
        log("TIMEOUT FAIL no result line after %%ss (WAIT)" %% WAIT)
        step2()
        return None
    return 0.2

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
        sysp = bpy.context.preferences.system
        log("env ui_scale=%%s pixel_size=%%s" %% (round(sysp.ui_scale, 3), sysp.pixel_size))
        if SCRIPT:
            _show_banner()
            g = {"__name__": "__shot__", "bpy": bpy, "print": _print}
            sys.path.insert(0, os.path.dirname(SCRIPT))        # tests/_gui.py
            bpy.app.driver_namespace["si_test_done"] = False
            _state["t0"] = _time.time()
            exec(compile(open(SCRIPT, encoding="utf-8").read(), SCRIPT, "exec"), g)
    except Exception:
        log("ERROR FAIL", traceback.format_exc())
        _state["done"] = True
    if SCRIPT:
        bpy.app.timers.register(_watch, first_interval=0.2)
    else:
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


RESULT = re.compile(r"^SHOT: \S+ (PASS|FAIL)")


def _gui_preflight():
    """One clear failure instead of a row of confusing ones when the dev profile has the kit disabled."""
    p = run_blender(["--background", "--python-expr",
                     "import bpy; print('KIT_ENABLED', %r in bpy.context.preferences.addons)" % MODULE], timeout=120)
    return "KIT_ENABLED True" in (p.stdout or "")


def _passed(line):
    m = RESULT.match(line)
    return bool(m) and m.group(1) == "PASS"


def _run_gui(files):
    """Run GUI test files; returns (all passed, report lines). Each Blender quits as soon as its test prints its
    result line; `# WAIT: n` is only the timeout."""
    if not _gui_preflight():
        return False, ["GUI: the kit is not enabled in the dev profile: run `python -I tools/dev.py enable`"]
    ok, lines, env_line = True, [], ""
    for fn in files:
        src = open(os.path.join(ROOT, "tests", fn), encoding="utf-8").read()
        m = re.search(r"^# WAIT:\s*(\d+)", src, re.M)
        wait = float(m.group(1) if m else "12")
        sim = "0" if re.search(r"^# SIMULATE:\s*0", src, re.M) else "1"
        attempts = []
        for attempt in range(2 if sim == "0" else 1):     # real input: the user's own mouse can interfere
            out = os.path.abspath(os.path.join(DEV, "shots", fn[:-3] + ".png"))
            code = SHOT % {"out": out, "script": os.path.join(ROOT, "tests", fn), "mode": "on",
                           "wait": wait, "size": "1600x900", "module": MODULE, "sim": sim}
            if sim == "0":                  # real input: tell whoever sits here to let go of the mouse first
                subprocess.run([sys.executable, "-I", os.path.join(ROOT, "tools", "handsoff.py"), "5", fn[:-3]])
            extra = ["--enable-event-simulate"] if sim == "1" else []
            p = run_blender(extra + ["--window-geometry", "0", "0", "1600", "900",
                                     "--python", write_tmp("shot.py", code)], timeout=wait + 120)
            text = (p.stdout or "") + (p.stderr or "")
            env_line = env_line or next((l for l in text.splitlines() if l.startswith("SHOT: env ")), "")
            res = [l for l in text.splitlines() if RESULT.match(l) or l.startswith(("SHOT: ERROR", "SHOT: TIMEOUT"))]
            if p.returncode is None:
                res.append("TIMEOUT: Blender did not quit (killed after %ds)" % (wait + 120))
            if not res:
                tail = text.strip().splitlines()[-1][:300] if text.strip() else ""
                res = ["no result line" + (": " + tail if tail else "")]
            bad = [r for r in res if not _passed(r)]
            attempts.append(bad[0] if bad else res[-1])
            if not bad:
                break
        passed = _passed(attempts[-1])
        note = "  (passed on retry; first: %s)" % attempts[0][:150] if passed and len(attempts) > 1 else ""
        ok = ok and passed
        lines.append("%-30s %s%s" % (fn, attempts[-1][:400], note))
    if env_line:
        lines.insert(0, env_line[len("SHOT: "):])
    return ok, lines


def _run_background(*patterns):
    p = run_blender(["--background", "--factory-startup", "--python", os.path.join(ROOT, "tests", "run.py"),
                     "--"] + list(patterns or [""]), timeout=900)
    out = p.stdout + p.stderr
    summary = [l for l in out.splitlines() if l.startswith(("ok ", "skip ", "FAIL ", "NO TESTS")) or "passed," in l]
    if "FAILURES" in out:
        detail = out[out.find("--- "):out.find(" passed, ")]
    elif "ALL PASSED" not in out:     # Blender crashed or hung before the report: show its last output
        detail = "background run ended without a report:\n" + out[-3000:]
    else:
        detail = ""
    return "ALL PASSED" in out, summary + ([detail[-3000:]] if detail else [])


def _run_scn(files):
    """The plain-Python reader checks (no Blender). Exit 77 = skipped (private scenes absent): a failure where
    private data is required."""
    ok, lines = True, []
    for f in files:
        r = subprocess.run([sys.executable, "-I", os.path.join(ROOT, "tests", f)], capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        out = (r.stdout + r.stderr).strip().splitlines()
        state = {0: "ok  ", 77: "FAIL" if REQUIRE_PRIVATE else "skip"}.get(r.returncode, "FAIL")
        if r.returncode == 77 and REQUIRE_PRIVATE:
            out.append("skipped, but this machine requires private data (.dev/require_private)")
        lines.append("%s %s: %s" % (state, f, " | ".join(out[-4:])))
        ok = ok and state != "FAIL"
    return ok, lines


def _scn_files():
    return sorted(f for f in os.listdir(os.path.join(ROOT, "tests")) if f.startswith("scn_") and f.endswith(".py"))


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
    if group in ("quick", "full") and os.path.isfile(os.path.join(ROOT, "tools", "roadmap.py")):  # not public
        r = subprocess.run([sys.executable, "-I", os.path.join(ROOT, "tools", "roadmap.py"), "--check"],
                           capture_output=True, text=True)
        results.append("specs: " + (r.stdout + r.stderr).strip())
        ok = ok and r.returncode == 0
        passed, lines = _run_background()
        results += lines
        ok = ok and passed
    if group == "full":
        passed, lines = _run_scn(_scn_files())
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
        missing = [f for f in files if not os.path.isfile(os.path.join(ROOT, "tests", f))]
        for f in missing:
            results.append("FAIL %s: listed in the spec but not in tests/" % f)
            ok = False
        files = [f for f in files if f not in missing]
        bg = [f for f in files if f.startswith("test_")]
        gui = [f for f in files if f.startswith("gui_")]
        scn = [f for f in files if f.startswith("scn_")]
        if scn:
            passed, lines = _run_scn(scn)
            results += lines
            ok = ok and passed
        if bg:
            passed, lines = _run_background(*bg)
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
                       "size": opt["--size"], "module": MODULE, "sim": opt["--simulate"]}
        if script and opt["--simulate"] == "0":
            subprocess.run([sys.executable, "-I", os.path.join(ROOT, "tools", "handsoff.py"), "5",
                            os.path.basename(script)[:-3]])
        extra = ["--enable-event-simulate"] if opt["--simulate"] == "1" else []
        p = run_blender(extra + ["--window-geometry", "0", "0", w, h, "--python", write_tmp("shot.py", code)],
                        timeout=300)
        print("\n".join(l for l in (p.stdout + p.stderr).splitlines()
                        if l.startswith("SHOT") or "Error" in l or "Traceback" in l or "si_kit" in l)[-6000:])
    elif cmd == "check":
        sys.exit(check(sys.argv[2] if len(sys.argv) > 2 else "quick", sys.argv[3:]))
    elif cmd == "guitest":                      # old name of `check gui`
        sys.exit(check("gui", []))
    elif cmd == "test":
        link()
        p = run_blender(["--background", "--factory-startup", "--python", os.path.join(ROOT, "tests", "run.py"),
                         "--"] + (sys.argv[2:] or [""]), timeout=900)
        out = p.stdout + p.stderr
        start = out.find("=== TESTS")
        print(out[start:] if start >= 0 else out[-6000:])
        sys.exit(0 if "ALL PASSED" in out else 1)


if __name__ == "__main__":
    main()
