# MIDI Adaptive Quantize V2 — ReaImGui Dialog Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace MIDI Adaptive Quantize's typed CSV dialog with a one-shot ReaImGui window using real dropdowns and a forest-green theme, keeping the quantize core intact.

**Architecture:** Only the input layer changes (mirrors Grid Align Transients V2). The pure functions and the quantize core (`plan_note_moves`, `_quantize_take`, scope, undo wrapper) stay as-is except a localized `allow_sixteenth`→`grid_choice` change. A new `_open_dialog()`/`_ga_frame()` runs a `defer`-driven ReaImGui window (green accents); on Apply it builds the same `config` dict the core consumes and calls `_run_in_reaper(cfg, show_report=True)`. Settings persist in `ExtState`.

**Tech Stack:** Python ReaScript; ReaImGui v0.10.x via the bundled API shim `…/Scripts/ReaTeam Extensions/API/imgui.py`; custom `python3` test harness (copied for V2); FakeReaper (`FakeImGui`) for offline glue tests (mandatory before live — see the `reascripts` skill).

---

## Spec

`docs/superpowers/specs/2026-06-02-midi-adaptive-quantize-v2-gui-design.md`

## V1 stays untouched

The user keeps `MIDI Adaptive Quantize V1.0.py`. **Do not rename, edit, or delete it, and
do not touch `midi_quant_test_headless.py`.** V2 is a COPY with its own harness.

## File Structure

- **`MIDI Adaptive Quantize V2.0.py`** (NEW, copy of V1): the whole V2 script.
- **`midi_quant_v2_test_headless.py`** (NEW, copy of `midi_quant_test_headless.py`,
  repointed): V2 test harness; gets the updated/added tests.
- **`_reaper_fakes.py`** (NEW, worktree root): `FakeImGui` (echo widgets + scripted
  Apply/Cancel + no-op style calls) for the offline dialog test.

Working directory for ALL commands: `/Users/macbook/projects/reascripts/.claude/worktrees/midi-adaptive-quantize`. Run the harness with `/Library/Frameworks/Python.framework/Versions/3.11/bin/python3 <harness>.py`. The harness is a CUSTOM runner (NOT pytest): a `TESTS=[...]` list + `main()` printing `PASS: N checks`; new tests must be appended to `TESTS`.

## Config dict schema (V2)

`_run_in_reaper` consumes:
```python
{
  "grid_threshold_ms": float,        # e.g. 15.0
  "mode":              "snap"|"adaptive",
  "grid_choice":       "project"|"1/8"|"1/16"|"1/32",   # replaces allow_sixteenth
  "include_triplets":  bool,
}
```
Plus the test-only `{"headless": True, ...}` short-circuit, unchanged.

---

### Task 1: COPY V1 → V2 + V2 harness (V1 untouched)

**Files:**
- Create: `MIDI Adaptive Quantize V2.0.py` (copy of `…V1.0.py`)
- Create: `midi_quant_v2_test_headless.py` (copy of `midi_quant_test_headless.py`, repointed)
- DO NOT touch `MIDI Adaptive Quantize V1.0.py` or `midi_quant_test_headless.py`.

- [ ] **Step 1: Copy (no git mv — V1 must remain)**

```bash
cp "MIDI Adaptive Quantize V1.0.py" "MIDI Adaptive Quantize V2.0.py"
cp midi_quant_test_headless.py midi_quant_v2_test_headless.py
```

- [ ] **Step 2: Repoint ONLY the V2 harness**

In `midi_quant_v2_test_headless.py` change:
```python
SCRIPT_PATH = Path(__file__).with_name("MIDI Adaptive Quantize V1.0.py")
```
to
```python
SCRIPT_PATH = Path(__file__).with_name("MIDI Adaptive Quantize V2.0.py")
```
and in `load_module`, rename the spec name `"midi_quant_v1"` → `"midi_quant_v2"`.

- [ ] **Step 3: Run BOTH suites**

Run: `python3 midi_quant_v2_test_headless.py`  → Expected: `PASS: 11 checks`
Run: `python3 midi_quant_test_headless.py`     → Expected: `PASS: 11 checks` (V1 still green)

- [ ] **Step 4: Commit**

```bash
git add "MIDI Adaptive Quantize V2.0.py" midi_quant_v2_test_headless.py
git commit -m "chore: copy MIDI Adaptive Quantize V1.0 -> V2.0 with its own harness (V1 untouched)"
```

> For Tasks 2–7, "the harness" = `midi_quant_v2_test_headless.py` and "the script" =
> `MIDI Adaptive Quantize V2.0.py`. Never edit the V1 files.

---

### Task 2: Add `resolve_fine_qn` grid-choice helper (TDD)

**Files:** Modify `MIDI Adaptive Quantize V2.0.py`; Test `midi_quant_v2_test_headless.py`

- [ ] **Step 1: Write the failing test** (append to harness, register in `TESTS`):

```python
def test_resolve_fine_qn() -> None:
    module = load_module(SCRIPT_PATH)
    f = module.resolve_fine_qn
    assert f("1/8", 1.0) == 0.5
    assert f("1/16", 1.0) == 0.25
    assert f("1/32", 1.0) == 0.125
    assert f("project", 1.0) == 1.0
    assert f("project", 0.5) == 0.5
    assert f("bogus", 0.75) == 0.75   # unknown -> project grid
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 midi_quant_v2_test_headless.py`
Expected: FAIL — `AttributeError: ... 'resolve_fine_qn'`

- [ ] **Step 3: Implement** — in `MIDI Adaptive Quantize V2.0.py`, directly above `build_grid_candidates_qn`:

```python
def resolve_fine_qn(grid_choice, grid_qn):
    """Fine straight-grid step (QN) for a Grid dropdown choice.

    'project' (or any unknown value) falls back to the project grid step.
    """
    if grid_choice == "1/8":
        return 0.5
    if grid_choice == "1/16":
        return 0.25
    if grid_choice == "1/32":
        return 0.125
    return grid_qn
```

- [ ] **Step 4: Run to verify it passes**

Run: `python3 midi_quant_v2_test_headless.py`
Expected: `PASS: test_resolve_fine_qn` and `PASS: 12 checks`

- [ ] **Step 5: Commit**

```bash
git add "MIDI Adaptive Quantize V2.0.py" midi_quant_v2_test_headless.py
git commit -m "feat: add resolve_fine_qn grid-choice helper"
```

---

### Task 3: Parameterize `build_grid_candidates_qn` by `fine_qn` (TDD)

**Files:** Modify `MIDI Adaptive Quantize V2.0.py`; Test `midi_quant_v2_test_headless.py` (`test_grid_candidates`)

- [ ] **Step 1: Replace `test_grid_candidates`** with:

```python
def test_grid_candidates() -> None:
    module = load_module(SCRIPT_PATH)
    cfg = {"fine_qn": 0.25, "include_triplets": True,
           "qn_start": 100.0, "qn_end": 102.0}
    out = module.build_grid_candidates_qn(cfg)
    assert any(abs(x - 100.25) < 1e-9 for x in out["straight"])
    assert any(abs(x - (100.0 + 1.0 / 3.0)) < 1e-9 for x in out["triplet"])
    assert module.build_grid_candidates_qn(dict(cfg, include_triplets=False))["triplet"] == []
    # 1/8 choice -> straight spacing 0.5; no 100.25 sixteenth line present
    eighth = module.build_grid_candidates_qn(
        {"fine_qn": 0.5, "include_triplets": False, "qn_start": 100.0, "qn_end": 102.0})
    assert any(abs(x - 100.5) < 1e-9 for x in eighth["straight"])
    assert not any(abs(x - 100.25) < 1e-9 for x in eighth["straight"])
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 midi_quant_v2_test_headless.py`
Expected: FAIL — `KeyError: 'grid_qn'`

- [ ] **Step 3: Replace the body of `build_grid_candidates_qn`** with:

```python
def build_grid_candidates_qn(cfg):
    """Straight + optional triplet candidate families (QN).

    cfg["fine_qn"] is the already-resolved straight-grid step (see resolve_fine_qn).
    Triplets, when enabled, subdivide that step by 3.
    """
    q0, q1 = cfg["qn_start"], cfg["qn_end"]
    step_straight = cfg["fine_qn"]
    straight = _frange_qn(q0, q1, step_straight)
    triplet = []
    if cfg.get("include_triplets"):
        triplet = _frange_qn(q0, q1, step_straight / 3.0)
    return {"straight": straight, "triplet": triplet}
```

- [ ] **Step 4: Run to verify it passes**

Run: `python3 midi_quant_v2_test_headless.py`
Expected: `PASS: test_grid_candidates` and `PASS: 12 checks`

- [ ] **Step 5: Commit**

```bash
git add "MIDI Adaptive Quantize V2.0.py" midi_quant_v2_test_headless.py
git commit -m "refactor: build_grid_candidates_qn takes explicit fine_qn"
```

---

### Task 4: Rework routing + `_run_in_reaper` + `_quantize_take` grid mapping (drop text dialog)

**Files:** Modify `MIDI Adaptive Quantize V2.0.py`; Test `midi_quant_v2_test_headless.py` (4 tests)

CRASH LAW: no `raise SystemExit`/`sys.exit()`/`exit()`. The MIDI undo wrapper
(`_undo_begin`/`_undo_end`) must stay unchanged.

- [ ] **Step 1: Update the four affected tests (they will fail).**

REPLACE `test_report_schema_headless`:
```python
def test_report_schema_headless() -> None:
    module = load_module(SCRIPT_PATH)
    rep = module.run_quantize({"headless": True, "grid_threshold_ms": 15.0,
                               "mode": "snap", "grid_choice": "1/16",
                               "include_triplets": False})
    for key in ("moved_notes", "skipped_notes", "ends_unchanged"):
        assert key in rep, (key, rep)
    assert rep["ends_unchanged"] is True
    assert isinstance(rep["moved_notes"], int)
```

In `test_run_in_reaper_mock`, change the `_run_in_reaper` call config from
`{"grid_threshold_ms": 15.0, "mode": "snap", "allow_sixteenth": True, "include_triplets": False}`
to
`{"grid_threshold_ms": 15.0, "mode": "snap", "grid_choice": "1/16", "include_triplets": False}`.
(`"1/16"` reproduces the old `allow_sixteenth=True` fine grid of 0.25 QN, so the asserted
outcome is unchanged. Leave everything else in that test as-is.)

In `test_undo_registers_state_change`, make the same config change (the `_run_in_reaper`
call near the end): `"allow_sixteenth": True` → `"grid_choice": "1/16"`.

REPLACE `test_entrypoint_no_systemexit` with (no GetUserInputs; the GUI import fails
cleanly in plain Python):
```python
def test_entrypoint_no_systemexit() -> None:
    """Running the file as __main__ must NOT raise SystemExit (Py_Exit kills REAPER).

    In plain Python the ReaImGui import path cannot resolve, so the interactive dialog
    returns None cleanly. Guard that the entry returns without SystemExit.
    """
    import runpy
    mocks = {"RPR_ShowMessageBox": lambda *a: 0,
             "RPR_GetResourcePath": lambda *a: "/nonexistent"}
    try:
        runpy.run_path(str(SCRIPT_PATH), init_globals=mocks, run_name="__main__")
    except SystemExit as exc:
        raise AssertionError("entry raised SystemExit -> would kill REAPER") from exc
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 midi_quant_v2_test_headless.py`
Expected: FAIL — `KeyError: 'allow_sixteenth'` in `_quantize_take`, and/or the entry test.

- [ ] **Step 3: Reroute `run_quantize`.** Replace the whole function with:

```python
def run_quantize(config=None):
    config = config or {}
    if config.get("headless"):
        return {"moved_notes": 0, "skipped_notes": 0, "ends_unchanged": True}
    if config.get("grid_threshold_ms") is not None:
        return _run_in_reaper(config)   # explicit config (automation / live tests)
    return _open_dialog()               # interactive: ReaImGui defer loop
```

- [ ] **Step 4: Delete `_read_dialog`** (the entire `RPR_GetUserInputs` parser function).

- [ ] **Step 5: Update `_quantize_take` grid mapping.** Inside `_quantize_take`, REPLACE:
```python
    fine_qn = grid_qn
    if cfg["allow_sixteenth"]:
        fine_qn = min(fine_qn, 0.25)
    if cfg["include_triplets"]:
        fine_qn = fine_qn / 3.0
```
with:
```python
    straight_qn = resolve_fine_qn(cfg["grid_choice"], grid_qn)
    fine_qn = straight_qn / 3.0 if cfg["include_triplets"] else straight_qn
```
Then REPLACE the phase + candidate build:
```python
    qn_lo = qn_of_time(min(onsets))
    q0 = math.floor(qn_lo / grid_qn) * grid_qn
    families = build_grid_candidates_qn({
        "allow_sixteenth": cfg["allow_sixteenth"], "include_triplets": cfg["include_triplets"],
        "grid_qn": grid_qn, "qn_start": q0, "qn_end": qn_of_time(max(onsets)) + grid_qn})
```
with:
```python
    qn_lo = qn_of_time(min(onsets))
    q0 = math.floor(qn_lo / straight_qn) * straight_qn  # align to chosen fine grid
    families = build_grid_candidates_qn({
        "fine_qn": straight_qn, "include_triplets": cfg["include_triplets"],
        "qn_start": q0, "qn_end": qn_of_time(max(onsets)) + straight_qn})
```

- [ ] **Step 6: Update `_run_in_reaper` signature + report gating.** Replace the header:
```python
def _run_in_reaper(config):
    from_dialog = config.get("grid_threshold_ms") is None
    cfg = _read_dialog() if from_dialog else config
    if cfg is None:
        return None
```
with:
```python
def _run_in_reaper(config, show_report=False):
    cfg = config
```
Then change BOTH `if from_dialog:` (the empty-scope guidance box and the final summary
box) to `if show_report:`. After this, `from_dialog` and `_read_dialog` must not appear
anywhere in the file.

- [ ] **Step 7: Relabel user-facing strings V1.0 → V2.0.** In `MIDI Adaptive Quantize
V2.0.py`, change the module docstring and every user-facing `"MIDI Adaptive Quantize
V1.0"` literal (the two `ShowMessageBox` calls and the undo label passed to `_undo_end`)
to `"MIDI Adaptive Quantize V2.0"`.

- [ ] **Step 8: Add the temporary `_open_dialog` stub** (real version in Task 6), e.g. just
above `run_quantize`:
```python
def _open_dialog():
    return None  # replaced in Task 6
```

- [ ] **Step 9: Run the full suite**

Verify first:
`grep -n "from_dialog\|allow_sixteenth\|_read_dialog\|Adaptive Quantize V1.0" "MIDI Adaptive Quantize V2.0.py"` → returns NOTHING.
`grep -nE "raise SystemExit|sys\.exit|[^_a-zA-Z]exit\(" "MIDI Adaptive Quantize V2.0.py"` → only comment lines.

Run: `python3 midi_quant_v2_test_headless.py`
Expected: `PASS: 12 checks`

- [ ] **Step 10: Commit**

```bash
git add "MIDI Adaptive Quantize V2.0.py" midi_quant_v2_test_headless.py
git commit -m "feat: route quantize through config core; grid_choice + show_report; drop text dialog"
```

---

### Task 5: ExtState defaults persistence (TDD)

**Files:** Modify `MIDI Adaptive Quantize V2.0.py`; Test `midi_quant_v2_test_headless.py`

- [ ] **Step 1: Write the failing test** (append, register in `TESTS`):

```python
def test_ext_state_defaults() -> None:
    module = load_module(SCRIPT_PATH)
    store = {}
    module.RPR_GetExtState = lambda sect, key: store.get((sect, key), "")
    module.RPR_SetExtState = lambda sect, key, val, persist: store.__setitem__((sect, key), val)

    assert module._load_defaults() == {
        "threshold_ms": 15, "mode": "snap", "grid": "1/16", "triplets": False}

    module._save_defaults({"threshold_ms": 22, "mode": "adaptive",
                           "grid": "1/32", "triplets": True})
    assert module._load_defaults() == {
        "threshold_ms": 22, "mode": "adaptive", "grid": "1/32", "triplets": True}

    store[("MidiAdaptiveQuantize", "mode")] = "garbage"
    store[("MidiAdaptiveQuantize", "grid")] = "1/3"
    d = module._load_defaults()
    assert d["mode"] == "snap" and d["grid"] == "1/16"
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 midi_quant_v2_test_headless.py`
Expected: FAIL — `AttributeError: ... '_load_defaults'`

- [ ] **Step 3: Implement constants + helpers.** Add near the other module-level glue
(e.g. just above `_open_dialog`):

```python
_EXT_SECT = "MidiAdaptiveQuantize"
_MODES = ["snap", "adaptive"]
_GRIDS = ["project", "1/8", "1/16", "1/32"]


def _load_defaults():
    """Read last-used dialog settings from ExtState, with safe fallbacks."""
    def g(key, default):
        v = RPR_GetExtState(_EXT_SECT, key)  # noqa: F821
        return v if v else default
    try:
        thr = int(float(g("threshold_ms", "15")))
    except ValueError:
        thr = 15
    mode = g("mode", "snap")
    grid = g("grid", "1/16")
    return {
        "threshold_ms": thr,
        "mode": mode if mode in _MODES else "snap",
        "grid": grid if grid in _GRIDS else "1/16",
        "triplets": g("triplets", "0") not in ("0", "", "off", "no"),
    }


def _save_defaults(st):
    RPR_SetExtState(_EXT_SECT, "threshold_ms", str(st["threshold_ms"]), True)  # noqa: F821
    RPR_SetExtState(_EXT_SECT, "mode", st["mode"], True)                       # noqa: F821
    RPR_SetExtState(_EXT_SECT, "grid", st["grid"], True)                       # noqa: F821
    RPR_SetExtState(_EXT_SECT, "triplets", "1" if st["triplets"] else "0", True)  # noqa: F821
```

- [ ] **Step 4: Run to verify it passes**

Run: `python3 midi_quant_v2_test_headless.py`
Expected: `PASS: test_ext_state_defaults` and `PASS: 13 checks`

- [ ] **Step 5: Commit**

```bash
git add "MIDI Adaptive Quantize V2.0.py" midi_quant_v2_test_headless.py
git commit -m "feat: ExtState persistence for MIDI quantize dialog defaults"
```

---

### Task 6: ReaImGui dialog with forest-green theme (`_open_dialog` + frame)

**Files:** Modify `MIDI Adaptive Quantize V2.0.py`. GUI/defer code (not unit-tested here;
Task 7 fake-tests `_ga_frame`, Task 8 verifies live). Suite stays `13 checks`.
The constants `_MODES`, `_GRIDS`, `_EXT_SECT`, `_load_defaults`, `_save_defaults` already
exist (Task 5) — reuse, do NOT redefine.

- [ ] **Step 1: Add labels, palette, theme helper, and `_items`/`_GA`** above `_open_dialog`:

```python
_MODE_LABELS = ["Snap to grid", "Adaptive (groove)"]
_GRID_LABELS = ["Project grid", "1/8", "1/16", "1/32"]

# forest-green accent palette (ReaImGui packs colors as 0xRRGGBBAA)
def _rgba(r, g, b, a=1.0):
    return ((int(r * 255) << 24) | (int(g * 255) << 16)
            | (int(b * 255) << 8) | int(a * 255))

_GREEN_DIM = _rgba(0.26, 0.55, 0.27)
_GREEN_HOT = _rgba(0.36, 0.72, 0.38)
_GREEN_DARK = _rgba(0.16, 0.30, 0.17)

_GA = None  # holds {"imgui", "ctx", "ui"} while the dialog is open


def _items(labels):
    """ReaImGui Combo expects null-terminated, null-separated items."""
    return "\0".join(labels) + "\0"


def _theme_pairs(ImGui):
    """(color-slot, color) pairs for the green accent; pushed before Begin."""
    return [
        (ImGui.Col_Button(), _GREEN_DIM),
        (ImGui.Col_ButtonHovered(), _GREEN_HOT),
        (ImGui.Col_ButtonActive(), _GREEN_HOT),
        (ImGui.Col_FrameBg(), _GREEN_DARK),
        (ImGui.Col_FrameBgHovered(), _GREEN_DIM),
        (ImGui.Col_FrameBgActive(), _GREEN_DIM),
        (ImGui.Col_Header(), _GREEN_DIM),
        (ImGui.Col_HeaderHovered(), _GREEN_HOT),
        (ImGui.Col_HeaderActive(), _GREEN_HOT),
        (ImGui.Col_CheckMark(), _GREEN_HOT),
        (ImGui.Col_TitleBgActive(), _GREEN_DIM),
    ]
```

- [ ] **Step 2: Replace the `_open_dialog` stub** with:

```python
def _open_dialog():
    """Open the ReaImGui settings window; on Apply, run the core once.

    Returns None immediately (the window runs on a defer loop). Any failure to load
    ReaImGui returns None without crashing the host.
    """
    global _GA
    try:
        import os
        import sys
        api = os.path.join(RPR_GetResourcePath(),  # noqa: F821
                           "Scripts", "ReaTeam Extensions", "API")
        if api not in sys.path:
            sys.path.insert(0, api)
        import imgui as _ImGui
    except Exception:
        try:
            RPR_ShowMessageBox(  # noqa: F821
                "ReaImGui is required for the MIDI Adaptive Quantize dialog.\n\n"
                "Install it via ReaPack:\n"
                "Extensions > ReaPack > Browse packages > search 'ReaImGui'.",
                "MIDI Adaptive Quantize V2.0", 0)
        except Exception:
            pass
        return None

    try:
        st = _load_defaults()
        ctx = _ImGui.CreateContext("MIDI Adaptive Quantize V2")
        _GA = {
            "imgui": _ImGui,
            "ctx": ctx,
            "ui": {
                "thr": st["threshold_ms"],
                "mode": _MODES.index(st["mode"]),
                "grid": _GRIDS.index(st["grid"]),
                "trip": st["triplets"],
            },
        }
        RPR_defer("_ga_frame()")  # noqa: F821
    except Exception:
        _GA = None
    return None
```

- [ ] **Step 3: Add the module-level frame function** (after `_open_dialog`):

```python
def _ga_frame():
    """One ReaImGui frame (green theme). Re-defers until Apply / Cancel / close."""
    global _GA
    g = _GA
    if g is None:
        return
    ImGui = g["imgui"]
    ctx = g["ctx"]
    ui = g["ui"]

    pairs = _theme_pairs(ImGui)
    for slot, col in pairs:
        ImGui.PushStyleColor(ctx, slot, col)

    visible, open_ = ImGui.Begin(ctx, "MIDI Adaptive Quantize V2", True)
    apply_clicked = False
    cancel_clicked = False
    if visible:
        _, ui["thr"] = ImGui.InputInt(ctx, "Threshold (ms)", ui["thr"])
        _, ui["mode"] = ImGui.Combo(ctx, "Mode", ui["mode"], _items(_MODE_LABELS))
        _, ui["grid"] = ImGui.Combo(ctx, "Grid", ui["grid"], _items(_GRID_LABELS))
        _, ui["trip"] = ImGui.Checkbox(ctx, "Include triplet grid", ui["trip"])
        apply_clicked = ImGui.Button(ctx, "Apply")
        ImGui.SameLine(ctx)
        cancel_clicked = ImGui.Button(ctx, "Cancel")
    ImGui.End(ctx)  # ImGui requires End even when Begin returns not-visible
    ImGui.PopStyleColor(ctx, len(pairs))

    if apply_clicked:
        thr = int(ui["thr"]) if ui["thr"] and ui["thr"] > 0 else 15
        st = {"threshold_ms": thr, "mode": _MODES[ui["mode"]],
              "grid": _GRIDS[ui["grid"]], "triplets": bool(ui["trip"])}
        _save_defaults(st)
        cfg = {"grid_threshold_ms": float(thr), "mode": st["mode"],
               "grid_choice": st["grid"], "include_triplets": st["triplets"]}
        _GA = None
        _run_in_reaper(cfg, show_report=True)
        return
    if cancel_clicked or open_ == 0:
        _GA = None
        return
    RPR_defer("_ga_frame()")  # noqa: F821
```

- [ ] **Step 4: Verify + run suite**

`python3 -c "import ast; ast.parse(open('MIDI Adaptive Quantize V2.0.py').read())"` → no error.
`grep -c "def _open_dialog" "MIDI Adaptive Quantize V2.0.py"` → `1` (stub replaced, not duplicated).
Run: `python3 midi_quant_v2_test_headless.py` → Expected: `PASS: 13 checks`

- [ ] **Step 5: Commit**

```bash
git add "MIDI Adaptive Quantize V2.0.py"
git commit -m "feat: ReaImGui settings dialog with dropdowns + forest-green theme"
```

---

### Task 7: FakeReaper test of the dialog mapping (offline, BEFORE live)

**Files:** Create `_reaper_fakes.py`; Test `midi_quant_v2_test_headless.py`

- [ ] **Step 1: Create `_reaper_fakes.py`** in the worktree root:

```python
"""FakeReaper: in-memory stand-ins for REAPER APIs so ReaScript glue can be unit
tested without a live REAPER. Extend with RPR_* / audio-item fakes as needed."""


class FakeImGui:
    """Scripted ReaImGui stand-in. Widgets echo the passed-in value; Button returns
    True only for the label selected via apply/cancel. Any unknown attribute (color
    constants Col_*, PushStyleColor/PopStyleColor, etc.) becomes a no-op returning 0,
    so theme calls don't break the test."""

    def __init__(self, apply=False, cancel=False, open_=1):
        self._apply = apply
        self._cancel = cancel
        self._open = open_
        self.ended = 0
        self.pushed = 0
        self.popped = 0

    def CreateContext(self, label):
        return object()

    def Begin(self, ctx, name, p_open=None, flags=None):
        return True, self._open

    def End(self, ctx):
        self.ended += 1

    def InputInt(self, ctx, label, v, *a):
        return False, v

    def Combo(self, ctx, label, current, items, *a):
        return False, current

    def Checkbox(self, ctx, label, v, *a):
        return False, v

    def Button(self, ctx, label, *a):
        if label == "Apply":
            return self._apply
        if label == "Cancel":
            return self._cancel
        return False

    def SameLine(self, ctx, *a):
        return None

    def PushStyleColor(self, ctx, slot, col):
        self.pushed += 1

    def PopStyleColor(self, ctx, count=1):
        self.popped += count

    def __getattr__(self, name):
        # Col_* color constants and any other unscripted call -> no-op returning 0.
        return lambda *a, **k: 0
```

- [ ] **Step 2: Write the failing tests** (append to harness; ensure `import sys` and
`sys.path.insert(0, str(Path(__file__).parent))` are present near the top so
`_reaper_fakes` imports):

```python
def test_dialog_apply_mapping() -> None:
    module = load_module(SCRIPT_PATH)
    from _reaper_fakes import FakeImGui
    calls = {"run": [], "defer": 0, "saved": None}
    module._run_in_reaper = lambda cfg, show_report=False: calls["run"].append((cfg, show_report))
    module.RPR_defer = lambda s: calls.__setitem__("defer", calls["defer"] + 1)
    module._save_defaults = lambda st: calls.__setitem__("saved", st)

    fake = FakeImGui(apply=True)
    module._GA = {"imgui": fake, "ctx": object(),
                  "ui": {"thr": 22, "mode": 1, "grid": 3, "trip": True}}
    module._ga_frame()

    assert module._GA is None
    assert calls["defer"] == 0
    assert fake.ended == 1
    assert fake.pushed == fake.popped and fake.pushed > 0   # theme balanced
    assert len(calls["run"]) == 1
    cfg, show_report = calls["run"][0]
    assert show_report is True
    assert cfg == {
        "grid_threshold_ms": 22.0,
        "mode": "adaptive",        # mode index 1
        "grid_choice": "1/32",     # grid index 3
        "include_triplets": True,
    }
    assert calls["saved"]["mode"] == "adaptive" and calls["saved"]["grid"] == "1/32"


def test_dialog_cancel_and_redefer() -> None:
    module = load_module(SCRIPT_PATH)
    from _reaper_fakes import FakeImGui
    calls = {"run": 0, "defer": 0}
    module._run_in_reaper = lambda cfg, show_report=False: calls.__setitem__("run", calls["run"] + 1)
    module.RPR_defer = lambda s: calls.__setitem__("defer", calls["defer"] + 1)
    module._save_defaults = lambda st: None
    base_ui = {"thr": 15, "mode": 0, "grid": 2, "trip": False}

    module._GA = {"imgui": FakeImGui(cancel=True), "ctx": object(), "ui": dict(base_ui)}
    module._ga_frame()
    assert calls["run"] == 0 and calls["defer"] == 0 and module._GA is None

    module._GA = {"imgui": FakeImGui(open_=1), "ctx": object(), "ui": dict(base_ui)}
    module._ga_frame()
    assert calls["run"] == 0 and calls["defer"] == 1 and module._GA is not None

    module._GA = {"imgui": FakeImGui(open_=0), "ctx": object(), "ui": dict(base_ui)}
    module._ga_frame()
    assert calls["defer"] == 1 and module._GA is None
```
Register both in `TESTS`.

- [ ] **Step 3: Run.** `python3 midi_quant_v2_test_headless.py`. If a test fails, the bug is
in `_ga_frame` (index lookups `_MODES`/`_GRIDS`, `show_report=True`, theme push/pop
balance, or `_GA` teardown). Fix `_ga_frame`, not the tests.
Expected: `PASS: test_dialog_apply_mapping`, `PASS: test_dialog_cancel_and_redefer`, `PASS: 15 checks`.

- [ ] **Step 4: Commit**

```bash
git add _reaper_fakes.py midi_quant_v2_test_headless.py "MIDI Adaptive Quantize V2.0.py"
git commit -m "test: FakeReaper dialog-mapping tests for MIDI Quantize V2 (offline, pre-live)"
```
(Include the script in the commit only if you had to fix `_ga_frame`.)

---

### Task 8: Live verification in REAPER (reapy + manual GUI check)

Requires reapy running in REAPER with a MIDI item / selected notes. Human-in-loop for the
GUI. Undo between runs.

- [ ] **Step 1: Trigger the action so the window opens.**

```bash
/Library/Frameworks/Python.framework/Versions/3.11/bin/python3 - <<'PY'
import reapy
from reapy import reascript_api as RPR
path = "/Users/macbook/projects/reascripts/.claude/worktrees/midi-adaptive-quantize/MIDI Adaptive Quantize V2.0.py"
cmd = RPR.AddRemoveReaScript(True, 0, path, True)
RPR.Main_OnCommand(int(cmd), 0)
print("triggered", cmd)
PY
```

Confirm by hand IN REAPER:
- Window "MIDI Adaptive Quantize V2" opens with **green** accents: Threshold field, Mode
  + Grid dropdowns, Triplets checkbox, Apply / Cancel.
- Dropdowns open and show their options (no typing).
- **Cancel** / close makes no edits.
- Re-open remembers the last selection (ExtState).
- With MIDI notes selected (in the MIDI editor) or a MIDI item selected, **Apply**
  quantizes them, shows the summary box, and a single Undo restores the original notes
  (undo history shows "MIDI Adaptive Quantize V2.0").

If the window never appears (ReaScript console NameError on the import/defer), adjust the
import path / `RPR_defer("_ga_frame()")` form, re-run the suite (`PASS: 15 checks`), repeat.

- [ ] **Step 2: Commit any live-fix to the script (if needed); otherwise nothing to commit.**

---

## Self-Review

**Spec coverage:**
- V1 preserved (copy) → Task 1. ✓
- One-shot ReaImGui dialog, real dropdowns (Mode/Grid), Triplets checkbox → Task 6. ✓
- Forest-green theme (push/pop accents) → Task 6 (`_theme_pairs`, palette). ✓
- Grid `grid_choice` mapping project/1/8/1/16/1/32 → Tasks 2–4. ✓
- ExtState defaults (no Source field) → Task 5; used in Task 6. ✓
- No `SystemExit`; MIDI undo wrapper unchanged → Task 4 (entry guard; `_undo_*` untouched). ✓
- Graceful "install ReaImGui" message → Task 6 except block. ✓
- FakeReaper glue test BEFORE live → Task 7 (`FakeImGui` incl. style stubs). ✓
- Live verification → Task 8. ✓

**Placeholder scan:** No TBD/TODO; every code step shows complete code. The only stub
(`_open_dialog` in Task 4) is explicitly replaced in Task 6.

**Type/name consistency:** `grid_choice` (config) vs `grid` (ExtState/UI) are distinct by
design, mapped in `_ga_frame` (`grid_choice = _GRIDS[ui["grid"]]`). `resolve_fine_qn`,
`build_grid_candidates_qn(cfg["fine_qn"])`, `straight_qn`,
`_run_in_reaper(config, show_report)`, `_open_dialog`/`_ga_frame`/`_GA`/`_items`/
`_theme_pairs`, `_load_defaults`/`_save_defaults`, `_MODES`/`_GRIDS` used consistently.

## Follow-up

Second identical port of the ReaImGui-dropdown-dialog pattern (after Grid Align V2) →
extract a reusable skill (the user's stated end goal); separate cycle.
