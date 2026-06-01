# Grid Align Transients V2 — ReaImGui Dialog Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Grid Align Transients' typed CSV dialog with a one-shot ReaImGui window that uses real dropdowns for every choice, keeping the tested processing core intact.

**Architecture:** Only the input layer changes. The pure functions and the live `_run_in_reaper(config)` core stay as-is except for a localized grid-resolution change (`allow_sixteenth` boolean → `grid_choice` dropdown). A new `_open_dialog()` runs a `defer`-driven ReaImGui window; on **Apply** it builds the same `config` dict the core already consumes and calls `_run_in_reaper(cfg, show_report=True)`. Settings persist in `ExtState`.

**Tech Stack:** Python ReaScript; ReaImGui v0.10.x via the bundled API shim `…/Scripts/ReaTeam Extensions/API/imgui.py`; existing custom headless harness `grid_align_test_headless.py` (run with `python3`, not pytest).

---

## Spec

`docs/superpowers/specs/2026-06-01-grid-align-transients-v2-gui-design.md`

## File Structure

- **`Grid Align Transients V2.0.py`** (renamed from `…V1.0.py`): the whole script. Sections: pure logic (unchanged), grid-resolution helper (new), core `_run_in_reaper` (signature + grid mapping change), interactive GUI layer (new), entry point (unchanged shape, no `SystemExit`).
- **`grid_align_test_headless.py`**: custom test harness. Repoint `SCRIPT_PATH`, update two existing tests, add three new tests.

## Config dict schema (V2)

`_run_in_reaper` consumes exactly these keys:

```python
{
  "grid_threshold_ms": float,        # e.g. 15.0
  "transient_source":  "auto"|"splits",
  "mode":              "snap"|"adaptive",
  "grid_choice":       "project"|"1/8"|"1/16"|"1/32",   # replaces allow_sixteenth
  "include_triplets":  bool,
}
```

Plus the test-only `{"headless": True, ...}` short-circuit, unchanged.

---

### Task 1: Rename V1 → V2 and repoint the harness (no behavior change)

**Files:**
- Rename: `Grid Align Transients V1.0.py` → `Grid Align Transients V2.0.py`
- Modify: `grid_align_test_headless.py` (SCRIPT_PATH + module name)

- [ ] **Step 1: Rename the script with git**

```bash
git mv "Grid Align Transients V1.0.py" "Grid Align Transients V2.0.py"
```

- [ ] **Step 2: Repoint the harness**

In `grid_align_test_headless.py` change:

```python
SCRIPT_PATH = Path(__file__).with_name("Grid Align Transients V1.0.py")
```
to
```python
SCRIPT_PATH = Path(__file__).with_name("Grid Align Transients V2.0.py")
```
and in `load_module`, rename the spec name `"grid_align_v1"` → `"grid_align_v2"`.

- [ ] **Step 3: Run the suite to confirm green after rename**

Run: `python3 grid_align_test_headless.py`
Expected: `PASS: 15 checks`

- [ ] **Step 4: Commit**

```bash
git add "Grid Align Transients V2.0.py" grid_align_test_headless.py
git commit -m "refactor: rename Grid Align Transients V1.0 -> V2.0, repoint harness"
```

---

### Task 2: Add `resolve_fine_qn` grid-choice helper (TDD)

**Files:**
- Modify: `Grid Align Transients V2.0.py` (add helper near `build_grid_candidates_qn`)
- Test: `grid_align_test_headless.py`

- [ ] **Step 1: Write the failing test**

Add to `grid_align_test_headless.py`:

```python
def test_resolve_fine_qn() -> None:
    module = load_module(SCRIPT_PATH)
    f = module.resolve_fine_qn
    assert f("1/8", 1.0) == 0.5
    assert f("1/16", 1.0) == 0.25
    assert f("1/32", 1.0) == 0.125
    assert f("project", 1.0) == 1.0
    assert f("project", 0.5) == 0.5
    assert f("bogus", 0.75) == 0.75   # unknown choice -> project grid
```

Register it in the `TESTS` list (append `test_resolve_fine_qn`).

- [ ] **Step 2: Run to verify it fails**

Run: `python3 grid_align_test_headless.py`
Expected: FAIL — `AttributeError: module ... has no attribute 'resolve_fine_qn'`

- [ ] **Step 3: Implement the helper**

In `Grid Align Transients V2.0.py`, directly above `build_grid_candidates_qn`:

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

Run: `python3 grid_align_test_headless.py`
Expected: `PASS: test_resolve_fine_qn` and `PASS: 16 checks`

- [ ] **Step 5: Commit**

```bash
git add "Grid Align Transients V2.0.py" grid_align_test_headless.py
git commit -m "feat: add resolve_fine_qn grid-choice helper"
```

---

### Task 3: Parameterize `build_grid_candidates_qn` by `fine_qn` (TDD)

**Files:**
- Modify: `Grid Align Transients V2.0.py` (`build_grid_candidates_qn`)
- Test: `grid_align_test_headless.py` (`test_grid_candidates`)

- [ ] **Step 1: Update the test to the new schema (it will fail)**

Replace `test_grid_candidates` with:

```python
def test_grid_candidates() -> None:
    module = load_module(SCRIPT_PATH)
    cfg = {
        "fine_qn": 0.25,
        "include_triplets": True,
        "qn_start": 100.0,
        "qn_end": 102.0,
    }
    out = module.build_grid_candidates_qn(cfg)
    assert "straight" in out and "triplet" in out
    assert any(abs(x - 100.25) < 1e-9 for x in out["straight"])
    assert any(abs(x - (100.0 + 1.0 / 3.0)) < 1e-9 for x in out["triplet"])

    cfg_no_trip = dict(cfg, include_triplets=False)
    assert module.build_grid_candidates_qn(cfg_no_trip)["triplet"] == []

    # 1/8 choice -> straight spacing 0.5; no 100.25 sixteenth line present
    eighth = module.build_grid_candidates_qn(
        {"fine_qn": 0.5, "include_triplets": False,
         "qn_start": 100.0, "qn_end": 102.0})
    assert any(abs(x - 100.5) < 1e-9 for x in eighth["straight"])
    assert not any(abs(x - 100.25) < 1e-9 for x in eighth["straight"])
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 grid_align_test_headless.py`
Expected: FAIL — `KeyError: 'grid_qn'` (old impl still reads `grid_qn`/`allow_sixteenth`).

- [ ] **Step 3: Update the implementation**

Replace the body of `build_grid_candidates_qn` with:

```python
def build_grid_candidates_qn(cfg):
    """Straight + optional triplet candidate families (QN).

    cfg["fine_qn"] is the already-resolved straight-grid step (see
    resolve_fine_qn). Triplets, when enabled, subdivide that step by 3.
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

Run: `python3 grid_align_test_headless.py`
Expected: `PASS: test_grid_candidates` and `PASS: 16 checks`

- [ ] **Step 5: Commit**

```bash
git add "Grid Align Transients V2.0.py" grid_align_test_headless.py
git commit -m "refactor: build_grid_candidates_qn takes explicit fine_qn"
```

---

### Task 4: Rework `_run_in_reaper` + `run_grid_align` routing (grid_choice, show_report, drop text dialog)

**Files:**
- Modify: `Grid Align Transients V2.0.py` (`run_grid_align`, `_run_in_reaper`, delete `_read_user_dialog`)
- Test: `grid_align_test_headless.py` (`test_report_schema_headless`, `test_entrypoint_no_systemexit`)

- [ ] **Step 1: Update the two affected tests (they will fail)**

Replace `test_report_schema_headless` with (only the config keys change):

```python
def test_report_schema_headless() -> None:
    module = load_module(SCRIPT_PATH)
    report = module.run_grid_align({
        "headless": True,
        "grid_threshold_ms": 15.0,
        "mode": "snap",
        "transient_source": "auto",
        "grid_choice": "1/16",
        "include_triplets": False,
    })
    for key in ("edited_segments", "skipped", "neighbor_touched", "crossed_time_selection"):
        assert key in report, (key, report)
    assert report["neighbor_touched"] is False
    assert report["crossed_time_selection"] is False
    assert isinstance(report["edited_segments"], int)
```

Replace `test_entrypoint_no_systemexit` with (no GetUserInputs anymore; the GUI
import fails cleanly in plain Python and must NOT raise SystemExit):

```python
def test_entrypoint_no_systemexit() -> None:
    """Running the file as __main__ must NOT raise SystemExit.

    REAPER runs a ReaScript in an embedded interpreter; SystemExit there routes to
    Py_Exit -> C exit() and kills REAPER. In plain Python the ReaImGui import path
    cannot resolve, so the interactive dialog returns None cleanly. Guard that the
    entry returns without SystemExit. (Regression guard for the crash law.)
    """
    import runpy
    mocks = {
        "RPR_ShowMessageBox": lambda *a: 0,
        "RPR_GetResourcePath": lambda *a: "/nonexistent",
    }
    try:
        runpy.run_path(str(SCRIPT_PATH), init_globals=mocks, run_name="__main__")
    except SystemExit as exc:  # pragma: no cover - this is the bug we guard against
        raise AssertionError(
            "ReaScript __main__ raised SystemExit -> would terminate REAPER"
        ) from exc
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 grid_align_test_headless.py`
Expected: FAIL — `KeyError: 'allow_sixteenth'` somewhere in `_run_in_reaper`, or the
entrypoint test importing the (still text-dialog) `__main__`.

- [ ] **Step 3: Reroute `run_grid_align`**

Replace `run_grid_align` with:

```python
def run_grid_align(config=None):
    config = config or {}
    if config.get("headless"):
        return {
            "edited_segments": 0,
            "skipped": 0,
            "neighbor_touched": False,
            "crossed_time_selection": False,
        }
    if config.get("grid_threshold_ms") is not None:
        return _run_in_reaper(config)   # explicit config (automation / live tests)
    return _open_dialog()               # interactive: ReaImGui defer loop
```

- [ ] **Step 4: Delete `_read_user_dialog`**

Remove the entire `_read_user_dialog` function (the `RPR_GetUserInputs` parser).

- [ ] **Step 5: Update `_run_in_reaper` signature, grid mapping, and report gating**

Change the function header and the first ~30 lines. Replace:

```python
def _run_in_reaper(config):
    from_dialog = config.get("grid_threshold_ms") is None
    cfg = _read_user_dialog() if from_dialog else config
    if cfg is None:
        return None  # user cancelled

    threshold_s = cfg["grid_threshold_ms"] / 1000.0
    mode = cfg["mode"]
    source_mode = cfg["transient_source"]
    grid_qn = _project_grid_qn()
    fine_qn = grid_qn
    if cfg["allow_sixteenth"]:
        fine_qn = min(fine_qn, 0.25)
    if cfg["include_triplets"]:
        fine_qn = fine_qn / 3.0
```

with:

```python
def _run_in_reaper(config, show_report=False):
    cfg = config
    threshold_s = cfg["grid_threshold_ms"] / 1000.0
    mode = cfg["mode"]
    source_mode = cfg["transient_source"]
    grid_qn = _project_grid_qn()
    straight_qn = resolve_fine_qn(cfg["grid_choice"], grid_qn)  # straight family step
    # smallest candidate spacing drives the max-move guard step
    fine_qn = straight_qn / 3.0 if cfg["include_triplets"] else straight_qn
```

Then in `families_for`, phase-align to the chosen fine grid and pass `fine_qn`.
Replace:

```python
    def families_for(win):
        qn_lo = qn_of_time(win["proj_start"])
        q0 = math.floor(qn_lo / grid_qn) * grid_qn
        cfg_w = {"allow_sixteenth": cfg["allow_sixteenth"],
                 "include_triplets": cfg["include_triplets"],
                 "grid_qn": grid_qn, "qn_start": q0,
                 "qn_end": qn_of_time(win["proj_end"]) + grid_qn}
        return build_grid_candidates_qn(cfg_w), q0
```

with:

```python
    def families_for(win):
        qn_lo = qn_of_time(win["proj_start"])
        q0 = math.floor(qn_lo / straight_qn) * straight_qn  # align to chosen fine grid
        cfg_w = {"fine_qn": straight_qn,
                 "include_triplets": cfg["include_triplets"],
                 "qn_start": q0,
                 "qn_end": qn_of_time(win["proj_end"]) + straight_qn}
        return build_grid_candidates_qn(cfg_w), q0
```

- [ ] **Step 6: Gate the two MessageBoxes on `show_report` instead of `from_dialog`**

In `_run_in_reaper`, the empty-scope guidance box and the final summary box are
currently `if from_dialog:`. Change both to `if show_report:`. (Same message text;
only the condition name changes.)

- [ ] **Step 7: Run the full suite**

Run: `python3 grid_align_test_headless.py`
Expected: `PASS: 16 checks` (all green; `_open_dialog` not yet defined will only
fail if reached — it is not reached by any test except the entrypoint guard, which
returns before calling it because `RPR_GetResourcePath` mock + failed import path).

NOTE: `_open_dialog` does not exist yet. `run_grid_align(None)` references it. The
entrypoint test calls `main()` → `run_grid_align(None)` → `_open_dialog()`. So Task 4
cannot be green alone. **Combine Steps 7 verification with Task 5+6 being present**,
OR add a temporary stub `def _open_dialog(): return None` now and replace it in Task 6.
Add the stub now:

```python
def _open_dialog():
    return None  # replaced in Task 6
```

Re-run: `python3 grid_align_test_headless.py` → Expected: `PASS: 16 checks`.

- [ ] **Step 8: Commit**

```bash
git add "Grid Align Transients V2.0.py" grid_align_test_headless.py
git commit -m "feat: route grid align through config core; grid_choice + show_report; drop text dialog"
```

---

### Task 5: ExtState defaults persistence (TDD)

**Files:**
- Modify: `Grid Align Transients V2.0.py` (add ExtState constants + helpers)
- Test: `grid_align_test_headless.py`

- [ ] **Step 1: Write the failing test**

```python
def test_ext_state_defaults() -> None:
    module = load_module(SCRIPT_PATH)
    store = {}
    module.RPR_GetExtState = lambda sect, key: store.get((sect, key), "")
    module.RPR_SetExtState = lambda sect, key, val, persist: store.__setitem__((sect, key), val)

    # empty store -> V1 defaults
    assert module._load_defaults() == {
        "threshold_ms": 15, "source": "auto", "mode": "snap",
        "grid": "1/16", "triplets": False}

    # round-trip
    module._save_defaults({"threshold_ms": 22, "source": "splits",
                           "mode": "adaptive", "grid": "1/32", "triplets": True})
    assert module._load_defaults() == {
        "threshold_ms": 22, "source": "splits", "mode": "adaptive",
        "grid": "1/32", "triplets": True}

    # invalid stored values fall back to defaults
    store[("GridAlignTransients", "source")] = "garbage"
    store[("GridAlignTransients", "grid")] = "1/3"
    d = module._load_defaults()
    assert d["source"] == "auto" and d["grid"] == "1/16"
```

Register `test_ext_state_defaults` in `TESTS`.

- [ ] **Step 2: Run to verify it fails**

Run: `python3 grid_align_test_headless.py`
Expected: FAIL — `AttributeError: ... '_load_defaults'`

- [ ] **Step 3: Implement constants + helpers**

Add near the top of the REAPER-glue section (after the `_EDGE_EPS` constants):

```python
_EXT_SECT = "GridAlignTransients"
_SOURCES = ["auto", "splits"]
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
    src = g("source", "auto")
    mode = g("mode", "snap")
    grid = g("grid", "1/16")
    return {
        "threshold_ms": thr,
        "source": src if src in _SOURCES else "auto",
        "mode": mode if mode in _MODES else "snap",
        "grid": grid if grid in _GRIDS else "1/16",
        "triplets": g("triplets", "0") not in ("0", "", "off", "no"),
    }


def _save_defaults(st):
    RPR_SetExtState(_EXT_SECT, "threshold_ms", str(st["threshold_ms"]), True)  # noqa: F821
    RPR_SetExtState(_EXT_SECT, "source", st["source"], True)                   # noqa: F821
    RPR_SetExtState(_EXT_SECT, "mode", st["mode"], True)                       # noqa: F821
    RPR_SetExtState(_EXT_SECT, "grid", st["grid"], True)                       # noqa: F821
    RPR_SetExtState(_EXT_SECT, "triplets", "1" if st["triplets"] else "0", True)  # noqa: F821
```

- [ ] **Step 4: Run to verify it passes**

Run: `python3 grid_align_test_headless.py`
Expected: `PASS: test_ext_state_defaults` and `PASS: 17 checks`

- [ ] **Step 5: Commit**

```bash
git add "Grid Align Transients V2.0.py" grid_align_test_headless.py
git commit -m "feat: ExtState persistence for grid align dialog defaults"
```

---

### Task 6: ReaImGui dialog (`_open_dialog` + module-level frame)

**Files:**
- Modify: `Grid Align Transients V2.0.py` (replace the `_open_dialog` stub; add `_ga_frame`, `_items`, label lists, `_GA` global)

No unit test — this is GUI/defer code verified live in Task 7. Implement exactly:

- [ ] **Step 1: Add label lists and helper above `_open_dialog`**

```python
_SOURCE_LABELS = ["Auto (detect)", "Existing splits"]
_MODE_LABELS = ["Snap to grid", "Adaptive (groove)"]
_GRID_LABELS = ["Project grid", "1/8", "1/16", "1/32"]

_GA = None  # holds {"imgui", "ctx", "ui"} while the dialog is open


def _items(labels):
    """ReaImGui Combo expects null-terminated, null-separated items."""
    return "\0".join(labels) + "\0"
```

- [ ] **Step 2: Replace the `_open_dialog` stub**

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
                "ReaImGui is required for the Grid Align dialog.\n\n"
                "Install it via ReaPack:\n"
                "Extensions > ReaPack > Browse packages > search 'ReaImGui'.",
                "Grid Align Transients V2", 0)
        except Exception:
            pass
        return None

    try:
        st = _load_defaults()
        ctx = _ImGui.CreateContext("Grid Align Transients V2")
        _GA = {
            "imgui": _ImGui,
            "ctx": ctx,
            "ui": {
                "thr": st["threshold_ms"],
                "src": _SOURCES.index(st["source"]),
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

- [ ] **Step 3: Add the module-level frame function**

```python
def _ga_frame():
    """One ReaImGui frame. Re-defers itself until Apply / Cancel / window close."""
    global _GA
    g = _GA
    if g is None:
        return
    ImGui = g["imgui"]
    ctx = g["ctx"]
    ui = g["ui"]

    visible, open_ = ImGui.Begin(ctx, "Grid Align Transients V2", True)
    apply_clicked = False
    cancel_clicked = False
    if visible:
        _, ui["thr"] = ImGui.InputInt(ctx, "Threshold (ms)", ui["thr"])
        _, ui["src"] = ImGui.Combo(ctx, "Source", ui["src"], _items(_SOURCE_LABELS))
        _, ui["mode"] = ImGui.Combo(ctx, "Mode", ui["mode"], _items(_MODE_LABELS))
        _, ui["grid"] = ImGui.Combo(ctx, "Grid", ui["grid"], _items(_GRID_LABELS))
        _, ui["trip"] = ImGui.Checkbox(ctx, "Include triplet grid", ui["trip"])
        apply_clicked = ImGui.Button(ctx, "Apply")
        ImGui.SameLine(ctx)
        cancel_clicked = ImGui.Button(ctx, "Cancel")
    ImGui.End(ctx)  # ImGui requires End even when Begin returns not-visible

    if apply_clicked:
        thr = int(ui["thr"]) if ui["thr"] and ui["thr"] > 0 else 15
        st = {"threshold_ms": thr, "source": _SOURCES[ui["src"]],
              "mode": _MODES[ui["mode"]], "grid": _GRIDS[ui["grid"]],
              "triplets": bool(ui["trip"])}
        _save_defaults(st)
        cfg = {"grid_threshold_ms": float(thr),
               "transient_source": st["source"], "mode": st["mode"],
               "grid_choice": st["grid"], "include_triplets": st["triplets"]}
        _GA = None
        _run_in_reaper(cfg, show_report=True)
        return
    if cancel_clicked or open_ == 0:
        _GA = None
        return
    RPR_defer("_ga_frame()")  # noqa: F821
```

- [ ] **Step 4: Run the suite (still green; GUI code is not unit-tested)**

Run: `python3 grid_align_test_headless.py`
Expected: `PASS: 17 checks`

- [ ] **Step 5: Commit**

```bash
git add "Grid Align Transients V2.0.py"
git commit -m "feat: ReaImGui settings dialog with dropdowns for Grid Align V2"
```

---

### Task 7: Live verification in REAPER (reapy loop + manual GUI check)

**Files:**
- Use existing: `_ga_headless_runner.py`, `_ga_drive.py` (from the earlier test session)

This task confirms the refactored core and the GUI behave live. The reapy server
must be running in REAPER with the two identical palmas items present (Palmas 1
selected). Undo between runs.

- [ ] **Step 1: Core path live (explicit config, bypasses GUI)**

Edit `_ga_headless_runner.py`'s config block to the V2 schema:

```python
    config = {
        "grid_threshold_ms": 15.0,
        "transient_source": "auto",
        "mode": "snap",
        "grid_choice": "1/16",
        "include_triplets": False,
    }
```

Select the Palmas 1 item in REAPER, then run:

```bash
/Library/Frameworks/Python.framework/Versions/3.11/bin/python3 _ga_drive.py
```

Expected: `/tmp/grid_align_report.json` shows `edited_segments` > 0 and item count
grows (split+move worked with the new grid mapping). Undo in REAPER (Cmd-Z) restores
one item.

- [ ] **Step 2: Confirm each grid_choice changes spacing**

Re-run Step 1 with `"grid_choice": "1/8"` then `"1/32"`. Expected: `1/8` produces
fewer / coarser corrections than `1/16`; `1/32` produces more. Undo after each.

- [ ] **Step 3: Manual GUI smoke (window + dropdowns + Apply)**

Register the live action and trigger it so the window opens (GUI needs a human):

```bash
/Library/Frameworks/Python.framework/Versions/3.11/bin/python3 - <<'PY'
import reapy
from reapy import reascript_api as RPR
path = "/Users/macbook/projects/reascripts/Grid Align Transients V2.0.py"
cmd = RPR.AddRemoveReaScript(True, 0, path, True)
RPR.Main_OnCommand(int(cmd), 0)
print("triggered", cmd)
PY
```

Confirm IN REAPER, by hand:
- Window titled "Grid Align Transients V2" opens with Threshold field and three
  dropdowns (Source / Mode / Grid) + Triplets checkbox + Apply / Cancel.
- Opening each dropdown shows its two/four options (no typing required).
- **Cancel** / closing the window makes no edits.
- Re-open: the dropdowns remember the last selection (ExtState).
- With Palmas 1 selected, **Apply** aligns it and shows the summary box; a single
  Undo restores the original item.

If the ReaImGui import path or `RPR_defer("_ga_frame()")` string form differs on this
install (window never appears, ReaScript console shows a NameError), adjust the
import/defer lines in `_open_dialog`/`_ga_frame` to the form REAPER reports, re-run
the suite (must stay `PASS: 17 checks`), and repeat this step.

- [ ] **Step 4: Remove the throwaway drivers and commit the verified state**

```bash
git rm -f --ignore-unmatch _ga_headless_runner.py _ga_drive.py 2>/dev/null; rm -f _ga_headless_runner.py _ga_drive.py
git add -A
git commit -m "chore: drop grid-align live test drivers after V2 verification"
```

---

## Self-Review

**Spec coverage:**
- One-shot ReaImGui dialog → Task 6 (`_open_dialog`/`_ga_frame`). ✓
- Real dropdowns for every choice → Task 6 (`Combo` for Source/Mode/Grid; Checkbox
  for Triplets per spec). ✓
- Grid `grid_choice` mapping `project/1/8/1/16/1/32` → Tasks 2–4. ✓
- ExtState defaults → Task 5; loaded in Task 6, saved on Apply. ✓
- No `SystemExit` / single undo block → unchanged core + Task 4 entrypoint guard. ✓
- Graceful "install ReaImGui" message when extension missing → Task 6 except block. ✓
- Tested core untouched except grid mapping → Tasks 2–4 only touch the grid path. ✓
- Live verification → Task 7. ✓

**Placeholder scan:** No TBD/TODO; every code step shows complete code. The only
deliberate stub (`_open_dialog` in Task 4 Step 7) is explicitly replaced in Task 6.

**Type/name consistency:** `grid_choice` (config) vs `grid` (ExtState/UI state) are
distinct by design and mapped in `_ga_frame` (`grid_choice = _GRIDS[ui["grid"]]`).
`resolve_fine_qn`, `build_grid_candidates_qn(cfg["fine_qn"])`, `straight_qn`,
`_run_in_reaper(config, show_report)`, `_open_dialog`, `_ga_frame`, `_GA`,
`_load_defaults`/`_save_defaults`, `_items` are used consistently across tasks.

## Follow-up

Once verified live, extract the ReaImGui-dialog-with-dropdowns+ExtState pattern into
a reusable skill (the user's stated end goal) — separate brainstorm/spec cycle.
