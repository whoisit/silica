# Test plan

Tests come **first**: a feature's main flow (from its acceptance criteria, spec section 7) becomes a test before
the code, and it fails while the feature is missing or broken. Other criteria are checked by the batch audit, by
reading the code or by a probe; a criterion needs no test of its own (user decisions 2026-11-02, 2026-11-16).

## Kinds of test

| Kind | Files | Runs in | Notes |
|---|---|---|---|
| Background | `tests/test_*.py` | Blender `--background` | Logic, data, restore on mode off. No windows, no drawing, no keymaps. |
| GUI, simulated input | `tests/gui_*.py` | GUI Blender, `--enable-event-simulate` | Keys and mouse through `window.event_simulate`. Real OS input is ignored while it runs. |
| GUI, real input | `tests/gui_*.py` with `# SIMULATE: 0` | GUI Blender | Moves the **real cursor** (e.g. maximize). Hands off the mouse: a red countdown note (tools/handsoff.py) comes up 5 s before, and a red banner shows in the test window. Retried once; a pass on the retry is reported as such. |
| Reader check | `tests/scn_*_check.py` | plain Python (no Blender) | The .scn reader against Softimage's own exports (private scenes). Exit 0 pass, 1 fail, 77 skipped. |
| Mutation check | (by hand / by the auditor) | any of the above | Break the code on purpose; the test must fail; restore the code exactly. |
| Screenshot diff | (planned) | GUI Blender | Compare against private reference screenshots for pixel-perfect UI. |

GUI tests use the shared harness `tests/_gui.py` (`Run`: steps, checks, the result line; fresh area / region
lookups; key and drag helpers). Never copy a step runner into a test.
File markers (first lines of a GUI test):
- `# WAIT: n`: timeout in seconds (default 12). Blender quits as soon as the test prints its result line, so a
  generous value costs nothing; a test that reaches it fails with TIMEOUT.
- `# SIMULATE: 0`: real input, no event simulation.
A GUI test prints exactly one result line: `SHOT: <NAME> PASS` or `SHOT: <NAME> FAIL <reasons>` (`Run` does it).
The report starts with the display scale the run saw (`ui_scale`, `pixel_size`). While a test runs, a strip along
the bottom of its 3D views and node editors says so (grey: simulated input, your mouse is ignored; red: hands off).

Limits of simulated input (found 2026-11-02):
- Clicking a UI button: send the MOUSEMOVE in one timer step and the press / release in the next, or only the
  first click of a test registers.
- Simulated Shift / Ctrl never reach a UI button's operator (Blender doesn't update the window's modifier state
  for simulated keys). Give the operator `extend` / `toggle`-style properties and call it with them.
- Which button is under the mouse can't be read from a timer (`context.button_*` is empty there). For panels of
  plain properties and operators, a background test that draws the panel into a recording layout is cheaper
  (tests/test_mcp.py).
- Pixel positions must use Blender's widget unit (round(18 x `ui_scale`) + 2 x `pixel_size`: `explorer.unit()`),
  which includes Windows display scaling: the desktop runs at 125 % since about 2026-11-12, and tests with 20 px
  rows broke (2026-11-16). Keep clicks away from region edges (View2D scrollbars).
- Look areas and regions up in the step that uses them: an editor change or a workspace switch replaces them.
- A fresh worktree's dev profile has the kit disabled: run `python -I tools/dev.py enable` once (`check gui`
  stops with that message).

## Private data: skipped is not passed

Tests on private Softimage scenes raise `Skip("why")` (background; `run.py` injects it) or exit 77 (reader
checks) when the data isn't there: the report says `skip`, never `ok`. On the owner's machine a file
`.dev/require_private` (in the main checkout; worktrees see it) turns every skip into a failure. A loop over
scenes or truth files counts what it checked and skips (or fails) when that is zero. Known reader gaps are listed
by name (`scn_materials_check.KNOWN_GAPS`): a new failure fails, and so does a listed scene that matches now.

## Keep the suite small (user decisions 2026-11-02, 2026-11-16)

The number of tests must not grow out of proportion with the features. Per feature:
- **One GUI test for the main flow** (what can only be seen in the UI), plus background tests for logic where
  they are cheaper.
- **A test for each real bug** that turns up (user report or audit), reproducing it on the old code first. Say
  so in its docstring (date, what broke).
- No edge-case tests written up front; no separate test per corner of a criterion. An audit adds a test only for
  a bug it showed, never because a criterion has no test of its own.
- When a feature is rewritten, its old tests are deleted or merged into the new ones in the same commit.
- Every `test_*.py` / `gui_*.py` is listed in a spec's `tests:`; `roadmap.py --check` (in `check quick`) fails on
  an unlisted file and on a listed file that doesn't exist.
- Timing budgets: at most one 10,000-object timing per module, with 3-5 times headroom over the measured value,
  so it catches a slow algorithm and not a busy machine.
- Mutation checks only when a test looks suspicious (it passed too easily, or checks the code against itself).

## Groups: which tests run when

| Group | Command | Contains | When |
|---|---|---|---|
| quick | `python -I tools/dev.py check quick` | background tests + spec check | before a commit |
| feature | `python -I tools/dev.py check feature <spec id>` | the files in that spec's `tests:` | while building the feature |
| gui | `python -I tools/dev.py check gui` | all simulated GUI tests | when touching shared input / keymap code |
| real | `python -I tools/dev.py check real` | real-input GUI tests | with `full` |
| full | `python -I tools/dev.py check full` | quick + reader checks + gui + real | **once at the end of the day**, before the push; before a release batch |

`python -I tools/dev.py test file.py::test_name` runs one background test; several patterns can be given.
No test matched is a failure.

Rules:
1. Never push with a failing test. If a test is wrong, fix the test in the same commit and say so.
2. Test runs never change the user's settings: scripted GUI runs switch the PPG creation popup off and put it back
   before quitting (tools/dev.py).
3. Bugs found by the user get a test that **reproduces the bug on the old code** before the fix.
4. A flaky test (fails, then passes unchanged) is fixed or deleted the same week, never re-run until green. Note it
   in PICKUP.md until then.

## Workflow per feature

1. Spec reaches `specced` (user agreed). Specs stay complete: they define the feature.
2. Write the feature's main-flow test; run `check feature <id>`: it fails (nothing built yet).
3. Build until `check feature <id>` passes; status `building` → `built`.
4. No audit per feature. Audits are batched before releases (see features/README.md).
