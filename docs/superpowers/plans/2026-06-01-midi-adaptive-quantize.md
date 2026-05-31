# MIDI Adaptive Quantize V1.0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a standalone REAPER Python ReaScript that quantizes only the MIDI note starts that are off-grid beyond a threshold (snap or adaptive), preserving the rest of the performance — no audio, no splits.

**Architecture:** Reuse Grid Align Transients' pure decision core (copied verbatim: QN grid candidates, family selection, time-proximity grouping, threshold + snap/adaptive + max-move-guard decision). New code: scope resolution, a pure per-group note-move planner, a start-only move guard, and the REAPER MIDI glue (dialog, read via `MIDI_GetNote`, write via `MIDI_SetNote`, one undo block). Everything except the RPR glue is pure and tested headlessly; the glue is tested with a mock-`RPR` harness.

**Tech Stack:** REAPER Python ReaScript API (`RPR_*`, `MIDI_*`, `TimeMap2_*`), Python stdlib (`math`), the project's custom headless test-harness pattern (`midi_quant_test_headless.py`, not pytest).

---

## File Structure

- Create: `MIDI Adaptive Quantize V1.0.py` — the production script: copied pure core + scope resolver + note-move planner + start-only guard + MIDI glue (`_run_in_reaper`) + entry point.
- Create: `midi_quant_test_headless.py` — deterministic no-REAPER harness: pure-function tests, a mock-`RPR` end-to-end glue test, and a `runpy` entry-point no-SystemExit guard.

Units: pure helpers are importable and tested without REAPER. The only RPR-dependent code is the dialog and the `_run_in_reaper` transaction, covered by the mock-RPR harness plus the report-schema check.

Units convention: timing math in **seconds**; the dialog converts `Grid threshold (ms)` to seconds before calling helpers; tests pass seconds directly. Grid candidates live in **QN**.

---

### Task 1: Scaffold script and harness

**Files:**
- Create: `MIDI Adaptive Quantize V1.0.py`
- Create: `midi_quant_test_headless.py`

- [ ] **Step 1: Write the scaffold script**

```python
#!/usr/bin/env python3
"""MIDI Adaptive Quantize V1.0 — quantize only off-grid MIDI note starts."""

from __future__ import annotations

import math


def run_quantize(config=None):
    config = config or {}
    if config.get("headless"):
        return {"moved_notes": 0, "skipped_notes": 0, "ends_unchanged": True}
    return _run_in_reaper(config)


def _run_in_reaper(config):
    raise NotImplementedError("REAPER path added in Task 7")


def main():
    # A REAPER ReaScript runs in an embedded interpreter; NEVER raise SystemExit
    # / sys.exit() / exit() — it routes to Py_Exit and kills the whole REAPER
    # process. Just call run_quantize and return normally.
    run_quantize()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Write the harness skeleton**

```python
#!/usr/bin/env python3
"""Headless harness for MIDI Adaptive Quantize checks."""

from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT_PATH = Path(__file__).with_name("MIDI Adaptive Quantize V1.0.py")


def load_module(path: Path):
    spec = importlib.util.spec_from_file_location("midi_quant_v1", str(path))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_entrypoint_presence() -> None:
    module = load_module(SCRIPT_PATH)
    assert hasattr(module, "run_quantize"), "Missing run_quantize(config=None)"


TESTS = [test_entrypoint_presence]


def main() -> int:
    for test in TESTS:
        test()
        print(f"PASS: {test.__name__}")
    print(f"PASS: {len(TESTS)} checks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

(Note: `raise SystemExit` is fine HERE — the harness is a normal CLI, never run inside REAPER.)

- [ ] **Step 3: Run harness, expect pass**

Run: `python3 midi_quant_test_headless.py`
Expected: `PASS: test_entrypoint_presence` then `PASS: 1 checks`.

- [ ] **Step 4: Commit**

```bash
git add "MIDI Adaptive Quantize V1.0.py" midi_quant_test_headless.py
git commit -m "feat: scaffold MIDI Adaptive Quantize script and harness"
```

### Task 2: Copy the pure decision core (verbatim from Grid Align)

The decision logic must stay identical to the audio version. Copy these functions
**verbatim** from `Grid Align Transients V1.0.py` into `MIDI Adaptive Quantize V1.0.py`
(below the imports, above `run_quantize`), unchanged:
`_frange_qn`, `build_grid_candidates_qn`, `choose_family_for_group`,
`group_transients`, `select_family_positions`, `compute_move`.

**Files:**
- Modify: `MIDI Adaptive Quantize V1.0.py`
- Test: `midi_quant_test_headless.py`

- [ ] **Step 1: Write the failing tests** (append to harness, register in `TESTS`)

```python
def test_grid_candidates() -> None:
    module = load_module(SCRIPT_PATH)
    cfg = {"allow_sixteenth": True, "include_triplets": True,
           "qn_start": 100.0, "qn_end": 102.0, "grid_qn": 1.0}
    out = module.build_grid_candidates_qn(cfg)
    assert any(abs(x - 100.25) < 1e-9 for x in out["straight"])
    assert any(abs(x - (100.0 + 1.0 / 3.0)) < 1e-9 for x in out["triplet"])
    assert module.build_grid_candidates_qn(dict(cfg, include_triplets=False))["triplet"] == []


def test_group_transients() -> None:
    module = load_module(SCRIPT_PATH)
    assert module.group_transients([0.10, 0.12, 0.50, 0.52, 1.20], 0.1) == \
        [[0.10, 0.12], [0.50, 0.52], [1.20]]


def test_compute_move() -> None:
    module = load_module(SCRIPT_PATH)
    th, step = 0.015, 0.125
    assert module.compute_move(0.010, th, "snap", None, step) is None       # within tol
    assert abs(module.compute_move(0.040, th, "snap", None, step) + 0.040) < 1e-9
    assert abs(module.compute_move(0.040, th, "adaptive", 0.010, step) - (0.010 - 0.040)) < 1e-9
    assert module.compute_move(0.200, th, "snap", None, step) is None       # max-move guard
```

- [ ] **Step 2: Run, expect fail**

Run: `python3 midi_quant_test_headless.py`
Expected: FAIL with `AttributeError: ... build_grid_candidates_qn`.

- [ ] **Step 3: Copy the six functions verbatim from `Grid Align Transients V1.0.py`.**

Open `Grid Align Transients V1.0.py`, copy `_frange_qn`, `build_grid_candidates_qn`,
`choose_family_for_group`, `group_transients`, `select_family_positions`,
`compute_move` exactly as written, and paste them into `MIDI Adaptive Quantize V1.0.py`
below `import math`.

- [ ] **Step 4: Run, expect pass**

Run: `python3 midi_quant_test_headless.py`
Expected: PASS for the three new tests.

- [ ] **Step 5: Commit**

```bash
git add "MIDI Adaptive Quantize V1.0.py" midi_quant_test_headless.py
git commit -m "feat: copy pure grid-quant decision core into MIDI script"
```

### Task 3: Scope resolution

**Files:**
- Modify: `MIDI Adaptive Quantize V1.0.py`
- Test: `midi_quant_test_headless.py`

- [ ] **Step 1: Write the failing test**

```python
def test_resolve_scope() -> None:
    module = load_module(SCRIPT_PATH)
    R = module.resolve_quant_scope

    # selected notes win outright (no clip applied)
    s = R({"selected_notes": [1, 2], "selected_items": [9], "time_sel": (1.0, 2.0)})
    assert s["mode"] == "notes" and s["notes"] == [1, 2] and s["clip"] is None

    # no notes, items + time selection -> items clipped
    s = R({"selected_items": [9], "time_sel": (1.0, 2.0)})
    assert s["mode"] == "items" and s["items"] == [9] and s["clip"] == (1.0, 2.0)

    # no notes, items, no time selection -> items whole
    s = R({"selected_items": [9]})
    assert s["mode"] == "items" and s["clip"] is None

    # nothing selected -> none (with or without time selection)
    assert R({"time_sel": (1.0, 2.0)})["mode"] == "none"
    assert R({})["mode"] == "none"
```

- [ ] **Step 2: Run, expect fail** (`AttributeError: resolve_quant_scope`)

- [ ] **Step 3: Implement** (add above `run_quantize`)

```python
def resolve_quant_scope(ctx):
    """Scope precedence: selected notes > selected items (clipped to time sel) > none.

    Selected notes win outright (explicit pick, no clip). Otherwise selected items
    are the unit, with any time selection as a clip bound applied per note window
    downstream. Nothing selected -> do nothing.
    """
    notes = ctx.get("selected_notes") or []
    items = ctx.get("selected_items") or []
    ts = ctx.get("time_sel")
    if notes:
        return {"mode": "notes", "notes": notes, "clip": None}
    if items:
        return {"mode": "items", "items": items, "clip": ts}
    return {"mode": "none"}
```

- [ ] **Step 4: Run, expect pass**

- [ ] **Step 5: Commit**

```bash
git add "MIDI Adaptive Quantize V1.0.py" midi_quant_test_headless.py
git commit -m "feat: add MIDI quantize scope resolution"
```

### Task 4: Start-only move guard

**Files:**
- Modify: `MIDI Adaptive Quantize V1.0.py`
- Test: `midi_quant_test_headless.py`

- [ ] **Step 1: Write the failing test**

```python
def test_quantized_start_ppq() -> None:
    module = load_module(SCRIPT_PATH)
    # ok: new start leaves >= MIN_NOTE_TICKS before end
    assert module.quantized_start_ppq(new_start=100, end=960, min_ticks=1) == 100
    # skip: new start would reach/cross the end (returns None)
    assert module.quantized_start_ppq(new_start=959, end=960, min_ticks=2) is None
    assert module.quantized_start_ppq(new_start=960, end=960, min_ticks=1) is None
    # exact boundary allowed (start + min_ticks == end)
    assert module.quantized_start_ppq(new_start=959, end=960, min_ticks=1) == 959
```

- [ ] **Step 2: Run, expect fail** (`AttributeError: quantized_start_ppq`)

- [ ] **Step 3: Implement**

```python
MIN_NOTE_TICKS = 1  # never shrink a note below this many PPQ ticks


def quantized_start_ppq(new_start, end, min_ticks=MIN_NOTE_TICKS):
    """New note start in PPQ, or None to skip (would not leave a positive length)."""
    if new_start > end - min_ticks:
        return None
    return new_start
```

- [ ] **Step 4: Run, expect pass**

- [ ] **Step 5: Commit**

```bash
git add "MIDI Adaptive Quantize V1.0.py" midi_quant_test_headless.py
git commit -m "feat: add start-only move guard (skip end-crossing notes)"
```

### Task 5: Per-group note-move planner (pure)

Mirrors Grid Align's group→family→anchor decision, but returns per-group note
moves (seconds) instead of audio segments. One move per group (chord/flam moves
together); adaptive `prev_lag` chains left→right.

**Files:**
- Modify: `MIDI Adaptive Quantize V1.0.py`
- Test: `midi_quant_test_headless.py`

- [ ] **Step 1: Write the failing test**

```python
def test_plan_note_moves() -> None:
    module = load_module(SCRIPT_PATH)
    ident = lambda x: x                       # 1 QN == 1 sec for the test
    families = {"straight": [0.0, 1.0, 2.0, 3.0], "triplet": []}
    grid_step_for = lambda q0: 1.0            # constant 1s grid step

    # two lone onsets, each 0.04 late of an integer grid point, snap mode
    moves = module.plan_note_moves(
        onsets=[1.04, 2.04], families=families, qn_of_time=ident, time_of_qn=ident,
        grid_step_for=grid_step_for, threshold_s=0.015, mode="snap", gap_s=0.1)
    assert len(moves) == 2
    assert abs(moves[0]["move"] - (-0.04)) < 1e-9
    assert moves[0]["onsets"] == [1.04]

    # within-tolerance onset is left out entirely
    none_moves = module.plan_note_moves(
        onsets=[1.005], families=families, qn_of_time=ident, time_of_qn=ident,
        grid_step_for=grid_step_for, threshold_s=0.015, mode="snap", gap_s=0.1)
    assert none_moves == []
```

- [ ] **Step 2: Run, expect fail** (`AttributeError: plan_note_moves`)

- [ ] **Step 3: Implement**

```python
def plan_note_moves(onsets, families, qn_of_time, time_of_qn,
                    grid_step_for, threshold_s, mode, gap_s):
    """Decide grouped note-start moves (seconds), left->right.

    onsets: ascending note start times (project seconds; chords repeat a time).
    Returns a list of {"onsets": [group times], "move": seconds}; only groups
    whose anchor exceeds the threshold (and passes the max-move guard) appear.
    """
    groups = group_transients(onsets, gap_s)
    planned = []
    prev_lag = None
    for g in groups:
        qns = [qn_of_time(t) for t in g]
        fam = select_family_positions(families, choose_family_for_group(qns, families))
        anchor_t = anchor_delta = anchor_grid = anchor_qn = None
        for t, tq in zip(g, qns):
            nearest_qn = min(fam, key=lambda p: abs(p - tq))
            grid_t = time_of_qn(nearest_qn)
            d = t - grid_t
            if anchor_t is None or abs(d) > abs(anchor_delta):
                anchor_t, anchor_delta, anchor_grid, anchor_qn = t, d, grid_t, nearest_qn
        move = compute_move(anchor_delta, threshold_s, mode, prev_lag,
                            grid_step_for(anchor_qn))
        if move is None:
            if abs(anchor_delta) <= threshold_s:
                prev_lag = anchor_delta
            continue
        prev_lag = (anchor_t + move) - anchor_grid
        planned.append({"onsets": list(g), "move": move})
    return planned
```

- [ ] **Step 4: Run, expect pass**

- [ ] **Step 5: Commit**

```bash
git add "MIDI Adaptive Quantize V1.0.py" midi_quant_test_headless.py
git commit -m "feat: add pure per-group MIDI note-move planner"
```

### Task 6: Report-schema headless path

**Files:**
- Modify: `MIDI Adaptive Quantize V1.0.py` (already returns the report in `run_quantize` headless branch)
- Test: `midi_quant_test_headless.py`

- [ ] **Step 1: Write the failing test**

```python
def test_report_schema_headless() -> None:
    module = load_module(SCRIPT_PATH)
    rep = module.run_quantize({"headless": True, "grid_threshold_ms": 15.0,
                               "mode": "snap", "allow_sixteenth": True,
                               "include_triplets": False})
    for key in ("moved_notes", "skipped_notes", "ends_unchanged"):
        assert key in rep, (key, rep)
    assert rep["ends_unchanged"] is True
    assert isinstance(rep["moved_notes"], int)
```

- [ ] **Step 2: Run, expect pass** (the Task-1 scaffold already returns this schema)

Run: `python3 midi_quant_test_headless.py`
Expected: PASS (no code change needed; this locks the schema).

- [ ] **Step 3: Commit**

```bash
git add midi_quant_test_headless.py
git commit -m "test: lock MIDI quantize headless report schema"
```

### Task 7: REAPER MIDI glue + orchestration (`_run_in_reaper`)

Wire the pure pieces to the REAPER MIDI API. RPR globals are injected by REAPER at
runtime; reference them only inside functions so the harness can import the module.

**Files:**
- Modify: `MIDI Adaptive Quantize V1.0.py`
- Test: `midi_quant_test_headless.py` (mock-RPR end-to-end)

- [ ] **Step 1: Write the failing mock-RPR test**

```python
def test_run_in_reaper_mock() -> None:
    """End-to-end in a fake REAPER: one take, three notes; only the off-grid one
    moves, its end is unchanged, and a degenerate move is skipped."""
    import types
    module = load_module(SCRIPT_PATH)

    # one take (id=1), 960 PPQ/QN, tempo 60 BPM so 1 QN == 1 sec, grid = 1 QN.
    # notes: n0 on-grid (0.000s), n1 late by 0.040s at QN 1, n2 a tiny note whose
    # move would cross its end (skipped). startppq in ticks (960/QN).
    notes = [
        {"start": 0,    "end": 480, "sel": True, "muted": False, "chan": 0, "pitch": 60},
        {"start": 960 + 38, "end": 1440, "sel": True, "muted": False, "chan": 0, "pitch": 62},
        {"start": 1882, "end": 1900, "sel": True, "muted": False, "chan": 0, "pitch": 64},  # early+short: snap-right crosses end -> skipped
    ]
    set_calls = []
    g = {}
    g["RPR_GetUserInputs"] = lambda *a: (1, a[0], a[1], "15,snap,1,0", a[4])
    g["RPR_GetSet_LoopTimeRange"] = lambda *a: (0, 0, 0.0, 0.0, 0)  # no time sel
    g["RPR_MIDIEditor_GetActive"] = lambda: 0                       # no editor
    g["RPR_CountSelectedMediaItems"] = lambda p: 1
    g["RPR_GetSelectedMediaItem"] = lambda p, i: 100
    g["RPR_GetActiveTake"] = lambda item: 1
    g["RPR_TakeIsMIDI"] = lambda take: True
    g["RPR_MIDI_CountEvts"] = lambda take, a, b, c: (3, take, 3, 0, 0)  # (retval, take, notecnt, cc, text)
    def get_note(take, i, *a):  # wrapper echoes all params: (retval, take, idx, sel, muted, start, end, chan, pitch, vel)
        n = notes[i]
        return (True, take, i, n["sel"], n["muted"], n["start"], n["end"], n["chan"], n["pitch"], 96)
    g["RPR_MIDI_GetNote"] = get_note
    def set_note(take, i, sel, muted, startppq, endppq, chan, pitch, vel, noSort):
        set_calls.append({"i": i, "start": startppq, "end": endppq})
        notes[i]["start"], notes[i]["end"] = startppq, endppq
        return True
    g["RPR_MIDI_SetNote"] = set_note
    g["RPR_MIDI_DisableSort"] = lambda take: None
    g["RPR_MIDI_Sort"] = lambda take: None
    g["RPR_MIDI_GetGrid"] = lambda take, a, b: (1.0, take, 0.0)      # grid = 1 QN
    g["RPR_MIDI_GetProjTimeFromPPQPos"] = lambda take, ppq: ppq / 960.0      # 1 QN == 1 sec
    g["RPR_MIDI_GetPPQPosFromProjTime"] = lambda take, t: round(t * 960.0)
    g["RPR_TimeMap2_timeToQN"] = lambda proj, t: t                  # 1 sec == 1 QN
    g["RPR_TimeMap2_QNToTime"] = lambda proj, q: q
    for noop in ("RPR_Undo_BeginBlock", "RPR_UpdateArrange"):
        g[noop] = lambda *a: None
    g["RPR_Undo_EndBlock"] = lambda *a: None
    g["RPR_ShowMessageBox"] = lambda *a: 0
    for k, v in g.items():
        setattr(module, k, v)

    rep = module._run_in_reaper({"grid_threshold_ms": 15.0, "mode": "snap",
                                 "allow_sixteenth": True, "include_triplets": False})
    moved = {c["i"] for c in set_calls}
    assert 0 not in moved, "on-grid note must not move"
    assert 1 in moved, "off-grid note must move"
    # start-only: the moved note's end is unchanged (1440)
    n1 = [c for c in set_calls if c["i"] == 1][-1]
    assert n1["end"] == 1440, n1
    assert abs(n1["start"] - 960) <= 1, n1  # snapped to QN 1 (=960 ticks)
    assert rep["ends_unchanged"] is True
    assert rep["moved_notes"] >= 1 and rep["skipped_notes"] >= 1
```

- [ ] **Step 2: Run, expect fail** (`NotImplementedError` / missing RPR usage)

- [ ] **Step 3: Implement the glue + orchestration**

Add the dialog reader, scope gathering, and `_run_in_reaper`. Replace the
`_run_in_reaper` stub.

```python
def _read_dialog():
    res = RPR_GetUserInputs(  # noqa: F821
        "MIDI Adaptive Quantize V1.0", 4,
        "Grid threshold (ms),Correction mode (snap/adaptive),Allow 1/16 (0/1),Include triplets (0/1)",
        "15,snap,1,0", 256)
    if not isinstance(res, tuple) or not res[0]:
        return None
    csv = next((res[i] for i in range(len(res) - 1, -1, -1)
                if isinstance(res[i], str) and "," in res[i]), None)
    if csv is None:
        return None
    p = [x.strip() for x in csv.split(",")]
    if len(p) != 4:
        return None
    try:
        thr = float(p[0])
    except ValueError:
        RPR_ShowMessageBox("Invalid threshold.", "Error", 0)  # noqa: F821
        return None
    return {"grid_threshold_ms": thr,
            "mode": "adaptive" if p[1].lower().startswith("a") else "snap",
            "allow_sixteenth": p[2] not in ("0", "", "off", "no"),
            "include_triplets": p[3] not in ("0", "", "off", "no")}


def _note_count(take):
    # wrapper echoes params: (retval, take, notecnt, cc, text)
    return RPR_MIDI_CountEvts(take, 0, 0, 0)[2]  # noqa: F821


def _get_note(take, i):
    """Note i as a dict, or None if not found. Wrapper return shape:
    (retval, take, idx, selected, muted, startppq, endppq, chan, pitch, vel)."""
    r = RPR_MIDI_GetNote(take, i, 0, 0, 0, 0, 0, 0, 0)  # noqa: F821
    if not r[0]:
        return None
    return {"sel": r[3], "muted": r[4], "start": r[5], "end": r[6],
            "chan": r[7], "pitch": r[8], "vel": r[9]}


def _active_editor_selected_notes():
    """(take, [note indices]) for selected notes in the active MIDI editor, or (None, [])."""
    ed = RPR_MIDIEditor_GetActive()  # noqa: F821
    if not ed:
        return None, []
    take = RPR_MIDIEditor_GetTake(ed)  # noqa: F821
    if not take or not RPR_TakeIsMIDI(take):  # noqa: F821
        return None, []
    sel = [i for i in range(_note_count(take))
           if (_get_note(take, i) or {}).get("sel")]
    return (take, sel) if sel else (None, [])


def _selected_midi_takes():
    """List of takes for selected MIDI items."""
    out = []
    for i in range(RPR_CountSelectedMediaItems(0)):  # noqa: F821
        take = RPR_GetActiveTake(RPR_GetSelectedMediaItem(0, i))  # noqa: F821
        if take and RPR_TakeIsMIDI(take):  # noqa: F821
            out.append(take)
    return out


def _time_selection():
    r = RPR_GetSet_LoopTimeRange(False, False, 0.0, 0.0, False)  # noqa: F821
    fs = [x for x in r if isinstance(x, float)]
    return (fs[0], fs[1]) if len(fs) >= 2 and fs[1] > fs[0] + 1e-4 else None


def _quantize_take(take, cfg, note_indices, time_sel):
    """Decide+apply moves for one take. Returns (moved, skipped)."""
    grid_qn = RPR_MIDI_GetGrid(take, 0.0, 0.0)[0]  # noqa: F821  (QN)
    qn_of_time = lambda t: RPR_TimeMap2_timeToQN(0, t)          # noqa: F821,E731
    time_of_qn = lambda q: RPR_TimeMap2_QNToTime(0, q)         # noqa: F821,E731
    fine_qn = grid_qn
    if cfg["allow_sixteenth"]:
        fine_qn = min(fine_qn, 0.25)
    if cfg["include_triplets"]:
        fine_qn = fine_qn / 3.0
    grid_step_for = lambda q0: time_of_qn(q0 + fine_qn) - time_of_qn(q0)  # noqa: E731

    # gather (index, onset_time, end_ppq), filtered to time selection if any
    notes = []
    for i in note_indices:
        nt = _get_note(take, i)
        if nt is None:
            continue
        t = RPR_MIDI_GetProjTimeFromPPQPos(take, nt["start"])  # noqa: F821
        if time_sel and not (time_sel[0] <= t <= time_sel[1]):
            continue
        notes.append({"i": i, "t": t, "end": nt["end"], "note": nt})
    if not notes:
        return 0, 0
    notes.sort(key=lambda n: n["t"])
    onsets = [n["t"] for n in notes]

    qn_lo = qn_of_time(min(onsets))
    q0 = math.floor(qn_lo / grid_qn) * grid_qn
    families = build_grid_candidates_qn({
        "allow_sixteenth": cfg["allow_sixteenth"], "include_triplets": cfg["include_triplets"],
        "grid_qn": grid_qn, "qn_start": q0, "qn_end": qn_of_time(max(onsets)) + grid_qn})

    gap_s = max(0.01, 0.5 * grid_step_for(q0))
    plans = plan_note_moves(onsets, families, qn_of_time, time_of_qn,
                            grid_step_for, cfg["grid_threshold_ms"] / 1000.0,
                            cfg["mode"], gap_s)
    move_by_t = {}
    for p in plans:
        for t in p["onsets"]:
            move_by_t[round(t, 9)] = p["move"]

    moved = skipped = 0
    RPR_MIDI_DisableSort(take)  # noqa: F821
    for n in notes:
        mv = move_by_t.get(round(n["t"], 9))
        if mv is None:
            continue
        new_sppq = RPR_MIDI_GetPPQPosFromProjTime(take, n["t"] + mv)  # noqa: F821
        guarded = quantized_start_ppq(new_sppq, n["end"])
        if guarded is None:
            skipped += 1
            continue
        nt = n["note"]
        RPR_MIDI_SetNote(take, n["i"], nt["sel"], nt["muted"], guarded, n["end"],  # noqa: F821
                         nt["chan"], nt["pitch"], nt["vel"], True)
        moved += 1
    RPR_MIDI_Sort(take)  # noqa: F821
    return moved, skipped


def _run_in_reaper(config):
    from_dialog = config.get("grid_threshold_ms") is None
    cfg = _read_dialog() if from_dialog else config
    if cfg is None:
        return None

    time_sel = _time_selection()
    note_take, sel_notes = _active_editor_selected_notes()
    scope = resolve_quant_scope({
        "selected_notes": sel_notes,
        "selected_items": [] if sel_notes else _selected_midi_takes(),
        "time_sel": time_sel})

    if scope["mode"] == "none":
        if from_dialog:
            RPR_ShowMessageBox(  # noqa: F821
                "Nothing to quantize.\n\nSelect notes in the MIDI editor, or select "
                "MIDI item(s). Nothing selected = no-op.",
                "MIDI Adaptive Quantize V1.0", 0)
        return {"moved_notes": 0, "skipped_notes": 0, "ends_unchanged": True}

    RPR_Undo_BeginBlock()  # noqa: F821
    moved = skipped = 0
    try:
        if scope["mode"] == "notes":
            moved, skipped = _quantize_take(note_take, cfg, scope["notes"], None)
        else:
            for take in scope["items"]:
                all_idx = list(range(_note_count(take)))
                m, s = _quantize_take(take, cfg, all_idx, scope["clip"])
                moved += m
                skipped += s
    finally:
        RPR_UpdateArrange()  # noqa: F821
        RPR_Undo_EndBlock("MIDI Adaptive Quantize V1.0", -1)  # noqa: F821

    report = {"moved_notes": moved, "skipped_notes": skipped, "ends_unchanged": True}
    if from_dialog:
        RPR_ShowMessageBox(  # noqa: F821
            "MIDI Adaptive Quantize V1.0\n\nMoved: {}\nSkipped (would cross end): {}\n"
            "Mode: {}".format(moved, skipped, cfg["mode"]),
            "MIDI Adaptive Quantize V1.0", 0)
    return report
```

Register `test_run_in_reaper_mock` in `TESTS`.

- [ ] **Step 4: Run, expect pass**

Run: `python3 midi_quant_test_headless.py`
Expected: PASS — note 0 not moved, note 1 snapped to 960 with end 1440, note 2 skipped.

- [ ] **Step 5: Commit**

```bash
git add "MIDI Adaptive Quantize V1.0.py" midi_quant_test_headless.py
git commit -m "feat: add REAPER MIDI glue + orchestration with mock-RPR test"
```

### Task 8: Entry-point no-SystemExit guard

**Files:**
- Test: `midi_quant_test_headless.py`

- [ ] **Step 1: Write the failing test**

```python
def test_entrypoint_no_systemexit() -> None:
    """Running the file as __main__ must NOT raise SystemExit (Py_Exit kills REAPER)."""
    import runpy
    calls = {"dialog": 0}

    def fake_dialog(*a):
        calls["dialog"] += 1
        return (0,) + tuple(a)  # retval 0 -> cancel -> run_quantize returns None

    mocks = {"RPR_GetUserInputs": fake_dialog, "RPR_ShowMessageBox": lambda *a: 0,
             "RPR_GetSet_LoopTimeRange": lambda *a: (0, 0, 0.0, 0.0, 0),
             "RPR_MIDIEditor_GetActive": lambda: 0,
             "RPR_CountSelectedMediaItems": lambda p: 0}
    try:
        runpy.run_path(str(SCRIPT_PATH), init_globals=mocks, run_name="__main__")
    except SystemExit as exc:
        raise AssertionError("entry raised SystemExit -> would kill REAPER") from exc
    assert calls["dialog"] == 1, "entry did not reach run_quantize"
```

- [ ] **Step 2: Run, expect pass** (entry point already avoids SystemExit)

Run: `python3 midi_quant_test_headless.py`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add midi_quant_test_headless.py
git commit -m "test: guard MIDI quantize entry point against SystemExit"
```

## Final Verification

- [ ] Run: `python3 midi_quant_test_headless.py`
Expected: PASS for every registered `test_*` (entrypoint, candidates, grouping, compute_move, scope, start-guard, planner, report schema, mock-RPR end-to-end, no-SystemExit).

- [ ] Live REAPER smoke (when the user opens the project): on a small note selection in the MIDI editor and on selected MIDI item(s) ± a time selection — only above-threshold note starts move, ends are unchanged, degenerate moves skipped, one undo reverts all. Start with a tiny selection.
