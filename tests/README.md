# Test plan

Tests come **first**: a feature's acceptance criteria (its spec, section 7) are turned into tests before the code.
Every criterion has at least one test that fails while the feature is missing or broken.

## Kinds of test

| Kind | Files | Runs in | Notes |
|---|---|---|---|
| Background | `tests/test_*.py` | Blender `--background` | Logic, data, restore on mode off. No windows, no drawing, no keymaps. |
| GUI, simulated input | `tests/gui_*.py` | GUI Blender, `--enable-event-simulate` | Keys and mouse through `window.event_simulate`. Real OS input is ignored while it runs. |
| GUI, real input | `tests/gui_*.py` with `# SIMULATE: 0` | GUI Blender | Moves the **real cursor** (e.g. maximize). Hands off the mouse. Retried once. |
| Mutation check | (by hand / by the auditor) | any of the above | Break the code on purpose; the test must fail; restore the code exactly. |
| Screenshot diff | (planned) | GUI Blender | Compare against private reference screenshots for pixel-perfect UI. |

File markers (first lines of a GUI test):
- `# WAIT: n`: seconds the test needs (default 12).
- `# SIMULATE: 0`: real input, no event simulation.
A GUI test prints exactly one result line: `SHOT: <NAME> PASS` or `SHOT: <NAME> FAIL <reasons>`.

Limits of simulated input (found 2026-11-02):
- Clicking a UI button: send the MOUSEMOVE in one timer step and the press / release in the next, or only the
  first click of a test registers.
- Simulated Shift / Ctrl never reach a UI button's operator (Blender doesn't update the window's modifier state
  for simulated keys). Give the operator `extend` / `toggle`-style properties and call it with them.
- Which button is under the mouse can't be read from a timer (`context.button_*` is empty there). For panels of
  plain properties and operators, a background test that draws the panel into a recording layout is cheaper
  (tests/test_mcp.py).
- A fresh worktree's dev profile has the kit disabled: run `python -I tools/dev.py enable` once, or GUI tests fail
  for no visible reason.

## Keep the suite small (user decision 2026-11-02)

The number of tests must not grow out of proportion with the features. Per feature:
- **One GUI test for the main flow** (the acceptance criteria that can only be seen in the UI), plus background
  tests for logic where they are cheaper.
- **A test for each real bug** that turns up (user report or audit), reproducing it on the old code first.
- No edge-case tests written up front; no separate test per corner of a criterion.
- Mutation checks only when a test looks suspicious (it passed too easily, or checks the code against itself).

## Groups: which tests run when

| Group | Command | Contains | When |
|---|---|---|---|
| quick | `python -I tools/dev.py check quick` | background tests + spec format check | before a commit |
| feature | `python -I tools/dev.py check feature <spec id>` | the files in that spec's `tests:` | while building the feature |
| gui | `python -I tools/dev.py check gui` | all simulated GUI tests | when touching shared input / keymap code |
| real | `python -I tools/dev.py check real` | real-input GUI tests | with `full` |
| full | `python -I tools/dev.py check full` | quick + gui + real | **once at the end of the day**, before the push; before a release batch |

Rules:
1. Never push with a failing test. If a test is wrong, fix the test in the same commit and say so.
2. Test runs never change the user's settings: scripted GUI runs switch the PPG creation popup off and put it back
   before quitting (tools/dev.py).
3. Bugs found by the user get a test that **reproduces the bug on the old code** before the fix.

## Workflow per feature

1. Spec reaches `specced` (user agreed). Specs stay complete: they define the feature.
2. Write the feature's main-flow test; run `check feature <id>`: it fails (nothing built yet).
3. Build until `check feature <id>` passes; status `building` → `built`.
4. No audit per feature. Audits are batched before releases (see features/README.md).
