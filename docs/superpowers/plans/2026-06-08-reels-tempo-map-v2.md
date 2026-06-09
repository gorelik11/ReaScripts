# Reels Tempo Map V2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `reels_tempo_map_v2.py` that anchors the first tempo marker exactly on the time-selection start (beat 1), eliminating the ~2s phase lag, while preserving other songs' tempo maps in the same project.

**Architecture:** V1 (`reels_tempo_map.py`) stays untouched. V2 is a new, self-contained ReaScript that reuses V1's proven pure/window helpers (copied verbatim) and adds three new layers: (1) re-phase the madmom downbeat grid so a grid line lands on the time-selection start; (2) back-fill the skipped anacrusis bars so beat 1 sits exactly on the anchor; (3) a multi-song-safe write that deletes existing tempo markers ONLY within the analysis window before setting new ones by time (the vault-documented album-mapping pattern). The shared analyzer `reels_madmom_analyze.py` is unchanged.

**Tech Stack:** Python (REAPER ReaScript, bare `RPR_*` API), madmom via subprocess, pytest with an in-memory FakeReaper harness.

---

## Context the engineer needs

- **REAPER `RPR_*` return convention:** retval + ALL params echoed, including input-only ones.
  - `EnumProjectMarkers(idx,...)` → 7-tuple `(retval, idx, isrgn, pos, rgnend, name, markrgnindex)`.
  - `GetTempoTimeSigMarker(0, idx)` → `(retval, proj, idx, timepos, measurepos, beatpos, bpm, num, denom, lineartempo)` — **timepos is at index [3]**.
- **`SetTempoTimeSigMarker(proj, ptidx, timepos, measurepos, beatpos, bpm, num, denom, lineartempo)`** — with `measurepos = -1` REAPER positions by `timepos`. V2 uses `beatpos = 0.0` (vault variant) rather than V1's `-1`; with `measurepos = -1` the two should be equivalent, but `0.0` matches the proven album-mapping Lua.
- **`D_STARTOFFS` / `D_PLAYRATE` are TAKE properties** → read via `GetMediaItemTakeInfo_Value`, not the item function.
- **Crash class:** NEVER `raise SystemExit` / `exit()` inside a ReaScript. Wrap `main()` in top-level `try/except` → dump traceback to a log file.
- **Multi-song safety (vault `tempo-detection.md` Workflow 1):** delete tempo/time-sig markers ONLY within `[window_start, window_end]`, then add new ones by time. Markers of other songs live in other time ranges → never touched.
- **FakeReaper discipline:** every `RPR_*` path is tested in-memory before live. The snap of a time-sig marker to a measure boundary is a **live-only** REAPER behavior the fake cannot reproduce; the narrow-delete IS the real defeat (no old grid → the new first marker defines its own measure 1). Offline tests verify the read-back helper and that the first marker is placed exactly on the anchor when no snap occurs; the snapped branch is confirmed live (Task 9).

## File structure

- **Create:** `reels_tempo_map_v2.py` — the V2 ReaScript (self-contained).
- **Create:** `tests/test_reels_tempo_map_v2.py` — V2 FakeReaper tests (own copy of the fake; V1 tests untouched).
- **Unchanged:** `reels_madmom_analyze.py` (shared analyzer), `reels_tempo_map.py` (V1), `tests/test_reels_tempo_map.py` (V1 tests).

Run all V2 tests from repo root: `python3 -m pytest tests/test_reels_tempo_map_v2.py -q`

---

## Task 1: Scaffold V2 file + test harness, port pure helpers

**Files:**
- Create: `reels_tempo_map_v2.py`
- Create: `tests/test_reels_tempo_map_v2.py`

- [ ] **Step 1: Create the V2 script with header + pure helpers**

Create `reels_tempo_map_v2.py`:

```python
# -*- coding: utf-8 -*-
"""
Universal Madmom Tempo Map V2.0 (REAPER ReaScript)
Run inside REAPER: Actions > ReaScript > Run...

V2 difference vs V1: the first tempo marker is anchored EXACTLY on the start of
the time selection (= beat 1), removing V1's ~2s phase lag. Writing is
multi-song-safe: only markers inside the analysis window are touched, so other
songs' tempo maps in the same project survive.

Workflow:
1. Select an audio item.
2. Make a time selection whose LEFT edge sits on beat 1.
3. Run this script, enter the time signature (e.g. "7/8", "4/4", "12/8").
"""

import os
import sys
import json
import subprocess

def log(m):
    RPR_ShowConsoleMsg(str(m) + "\n")

# Madmom lives in a dedicated venv (REAPER/framework Python has no madmom).
PYTHON_EXE = os.path.expanduser("~/.venvs/madmom/bin/python3")


def _find_analyzer():
    """Locate reels_madmom_analyze.py next to this script (shared with V1)."""
    candidates = []
    try:
        ctx = RPR_get_action_context()
        if len(ctx) > 1 and ctx[1]:
            candidates.append(os.path.dirname(ctx[1]))
    except Exception:
        pass
    if "__file__" in globals():
        candidates.append(os.path.dirname(os.path.abspath(__file__)))
    candidates.append(os.path.expanduser("~/projects/reascripts"))
    candidates.append(os.path.expanduser("~/ReaScripts"))
    for d in candidates:
        p = os.path.join(d, "reels_madmom_analyze.py")
        if os.path.exists(p):
            return p
    return os.path.join(candidates[0] if candidates else ".", "reels_madmom_analyze.py")


ANALYZER_SCRIPT = _find_analyzer()
OUTPUT_JSON = os.path.join(os.path.expanduser("~"), "madmom_result_v2.json")
ERROR_LOG = os.path.join(os.path.expanduser("~"), "reels_tempo_map_v2_error.log")


# -- PARSE TIME SIGNATURE (ported verbatim from V1) ----------------

def parse_time_sig(ts_string):
    """Parse '7/8' -> (num, denom, beats_per_bar)."""
    parts = ts_string.strip().split("/")
    if len(parts) != 2:
        return None, None, None
    try:
        num, denom = int(parts[0]), int(parts[1])
    except ValueError:
        return None, None, None
    if num <= 0 or denom <= 0:
        return None, None, None
    if denom == 8 and num % 3 == 0 and num >= 6:
        beats_per_bar = num // 3
    elif denom == 8:
        beats_per_bar = num
    else:
        beats_per_bar = num
    return num, denom, beats_per_bar


def calc_quarter_notes_per_bar(ts_num, ts_denom):
    """REAPER BPM is always quarter-note based."""
    if ts_denom == 4:
        return ts_num
    elif ts_denom == 8:
        return ts_num / 2.0
    elif ts_denom == 2:
        return ts_num * 2
    return ts_num
```

- [ ] **Step 2: Create the V2 test file with its own FakeReaper**

Create `tests/test_reels_tempo_map_v2.py`:

```python
# -*- coding: utf-8 -*-
"""FakeReaper tests for reels_tempo_map_v2.py.

V2-specific: phase anchoring (re-phase + anacrusis back-fill) and multi-song-safe
narrow delete. Self-contained fake (V1 tests stay untouched).

Run from repo root:  python3 -m pytest tests/test_reels_tempo_map_v2.py -q
"""
from __future__ import annotations

import importlib
from dataclasses import dataclass

import pytest

import reels_tempo_map_v2 as mod


@dataclass
class FakeItem:
    item_id: int
    position: float
    length: float
    audio_path: str
    take_name: str
    startoffs: float = 0.0
    playrate: float = 1.0


@dataclass
class TempoMarkerCall:
    timepos: float
    bpm: float
    ts_num: int
    ts_denom: int


class TempoFakes:
    def __init__(self):
        self.items = []
        self.selected_ids = []
        self.console = []
        self.tempo_calls = []          # list[TempoMarkerCall]; index == REAPER marker idx
        self.undo_begin = 0
        self.undo_end = 0
        self.undo_labels = []
        self.update_timeline = 0
        self.update_arrange = 0
        self.message_boxes = []
        self.time_selection = None
        self._user_input = (False, "")
        self._next_id = 1

    # builders ----------------------------------------------------------
    def add_item(self, position, length, audio_path, take_name="take",
                 startoffs=0.0, playrate=1.0):
        item = FakeItem(self._next_id, position, length, audio_path, take_name,
                        startoffs, playrate)
        self._next_id += 1
        self.items.append(item)
        return item

    def set_time_selection(self, start, end):
        self.time_selection = (start, end)

    def select(self, item):
        self.selected_ids.append(item.item_id)

    def add_existing_tempo_marker(self, timepos, bpm=120.0, ts_num=0, ts_denom=0):
        self.tempo_calls.append(TempoMarkerCall(timepos, bpm, ts_num, ts_denom))

    def set_user_input(self, ok, csv):
        self._user_input = (ok, csv)

    def _item_by_id(self, item_id):
        for it in self.items:
            if it.item_id == item_id:
                return it
        raise AssertionError(f"unknown item_id {item_id}")

    # RPR_* factory -----------------------------------------------------
    def as_globals(self):
        f = self

        def RPR_ShowConsoleMsg(msg):
            f.console.append(msg)

        def RPR_ShowMessageBox(msg, title, _flags):
            f.message_boxes.append((msg, title))
            return 0

        def RPR_CountSelectedMediaItems(_proj):
            return len(f.selected_ids)

        def RPR_GetSelectedMediaItem(_proj, idx):
            return f.selected_ids[idx]

        def RPR_GetActiveTake(item_id):
            return item_id

        def RPR_GetMediaItemTake_Source(take_id):
            return take_id

        def RPR_GetMediaSourceFileName(source, _buf, sz):
            return (source, f._item_by_id(source).audio_path, sz)

        def RPR_GetMediaItemInfo_Value(item_id, param):
            it = f._item_by_id(item_id)
            if param == "D_POSITION":
                return it.position
            if param == "D_LENGTH":
                return it.length
            raise KeyError(param)

        def RPR_GetMediaItemTakeInfo_Value(take_id, param):
            it = f._item_by_id(take_id)
            if param == "D_STARTOFFS":
                return it.startoffs
            if param == "D_PLAYRATE":
                return it.playrate
            raise KeyError(param)

        def RPR_GetSet_LoopTimeRange(is_set, is_loop, start, end, allow):
            s, e = f.time_selection if f.time_selection else (0.0, 0.0)
            return (is_set, is_loop, s, e, allow)

        def RPR_GetTakeName(take_id):
            return f._item_by_id(take_id).take_name

        def RPR_SetTempoTimeSigMarker(_proj, _ptidx, timepos, _measpos, _beatpos,
                                       bpm, ts_num, ts_denom, _linear):
            f.tempo_calls.append(TempoMarkerCall(timepos, bpm, ts_num, ts_denom))
            return True

        def RPR_CountTempoTimeSigMarkers(_proj):
            return len(f.tempo_calls)

        def RPR_GetTempoTimeSigMarker(_proj, idx, *_a):
            c = f.tempo_calls[idx]
            return (1, 0, idx, c.timepos, 0, 0.0, c.bpm, c.ts_num, c.ts_denom, 0)

        def RPR_DeleteTempoTimeSigMarker(_proj, idx):
            del f.tempo_calls[idx]
            return True

        def RPR_GetUserInputs(title, num_inputs, captions, defaults, size):
            ok, csv = f._user_input
            return (ok, title, num_inputs, captions, csv, size)

        def RPR_Undo_BeginBlock():
            f.undo_begin += 1

        def RPR_Undo_EndBlock(label, _flags):
            f.undo_end += 1
            f.undo_labels.append(label)

        def RPR_UpdateTimeline():
            f.update_timeline += 1

        def RPR_UpdateArrange():
            f.update_arrange += 1

        return {k: v for k, v in locals().items() if k.startswith("RPR_")}


@pytest.fixture
def fakes():
    importlib.reload(mod)
    f = TempoFakes()
    for name, fn in f.as_globals().items():
        setattr(mod, name, fn)
    return f


# --- pure-logic tests ------------------------------------------------------

@pytest.mark.parametrize("ts,expected", [
    ("4/4", (4, 4, 4)),
    ("7/8", (7, 8, 7)),
    ("12/8", (12, 8, 4)),
])
def test_parse_time_sig(ts, expected):
    assert mod.parse_time_sig(ts) == expected


@pytest.mark.parametrize("num,denom,qn", [(4, 4, 4), (7, 8, 3.5), (12, 8, 6.0)])
def test_calc_quarter_notes_per_bar(num, denom, qn):
    assert mod.calc_quarter_notes_per_bar(num, denom) == qn
```

- [ ] **Step 3: Run the tests — verify they pass**

Run: `python3 -m pytest tests/test_reels_tempo_map_v2.py -q`
Expected: PASS (6 tests).

- [ ] **Step 4: Commit**

```bash
git add reels_tempo_map_v2.py tests/test_reels_tempo_map_v2.py
git commit -m "feat(tempo-v2): scaffold V2 script + FakeReaper harness with ported pure helpers"
```

---

## Task 2: Port window/item/madmom helpers

**Files:**
- Modify: `reels_tempo_map_v2.py` (append helpers)
- Modify: `tests/test_reels_tempo_map_v2.py` (append window tests)

- [ ] **Step 1: Append item/window/madmom helpers to `reels_tempo_map_v2.py`**

```python
# -- GET SELECTED ITEMS (ported from V1) ---------------------------

def get_selected_items():
    items = []
    n = RPR_CountSelectedMediaItems(0)
    for i in range(n):
        item = RPR_GetSelectedMediaItem(0, i)
        take = RPR_GetActiveTake(item)
        if not take:
            continue
        source = RPR_GetMediaItemTake_Source(take)
        audio_path = RPR_GetMediaSourceFileName(source, "", 512)[1]
        position = RPR_GetMediaItemInfo_Value(item, "D_POSITION")
        length = RPR_GetMediaItemInfo_Value(item, "D_LENGTH")
        startoffs = RPR_GetMediaItemTakeInfo_Value(take, "D_STARTOFFS")
        playrate = RPR_GetMediaItemTakeInfo_Value(take, "D_PLAYRATE")
        name = RPR_GetTakeName(take)
        items.append({
            "item": item, "take": take, "audio_path": audio_path,
            "position": position, "length": length, "startoffs": startoffs,
            "playrate": playrate if playrate else 1.0, "name": name,
        })
    return items


# -- ANALYSIS WINDOW: time selection > item bounds > whole file -----

def get_time_selection():
    """Return (start, end) of the loop/time selection, or None when empty."""
    ret = RPR_GetSet_LoopTimeRange(False, False, 0.0, 0.0, False)
    start, end = ret[2], ret[3]
    if end <= start:
        return None
    return (start, end)


def compute_analysis_window(item_position, item_length, startoffs, playrate, ts_range):
    """Decide which slice of the SOURCE file to analyze for one item.

    Returns (src_start, src_end, window_proj_start) where src_* are seconds into
    the source and window_proj_start is the project time the window begins at
    (= beat-1 anchor) — or None if a time selection exists but misses this item.
    """
    item_end = item_position + item_length
    if ts_range is not None:
        p0 = max(ts_range[0], item_position)
        p1 = min(ts_range[1], item_end)
        if p1 <= p0:
            return None
    else:
        p0, p1 = item_position, item_end
    src_start = startoffs + (p0 - item_position) * playrate
    src_end = startoffs + (p1 - item_position) * playrate
    return (src_start, src_end, p0)


# -- RUN MADMOM (ported from V1) -----------------------------------

def run_madmom(audio_path, beats_per_bar, ts_num, ts_denom,
               src_start=-1.0, src_end=-1.0):
    """Call the shared external madmom analyzer. Returns result dict or None."""
    try:
        process = subprocess.Popen(
            [PYTHON_EXE, ANALYZER_SCRIPT, audio_path, OUTPUT_JSON,
             str(beats_per_bar), str(ts_num), str(ts_denom),
             str(src_start), str(src_end)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env={"PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
                 "PYTHONIOENCODING": "utf-8",
                 "HOME": os.path.expanduser("~"), "TMPDIR": "/tmp"},
        )
        raw_stdout, raw_stderr = process.communicate()
        stdout = raw_stdout.decode("utf-8", errors="replace") if raw_stdout else ""
        stderr = raw_stderr.decode("utf-8", errors="replace") if raw_stderr else ""
        if stdout:
            log(stdout)
        if stderr:
            log("STDERR: " + stderr)
        if process.returncode != 0:
            log("ERROR: madmom exited with code {}".format(process.returncode))
            return None
        if not os.path.exists(OUTPUT_JSON):
            log("ERROR: output JSON not created")
            return None
        with open(OUTPUT_JSON, "r") as fh:
            return json.load(fh)
    except Exception as e:
        log("ERROR: {}".format(e))
        return None
```

- [ ] **Step 2: Append window tests to `tests/test_reels_tempo_map_v2.py`**

```python
# --- window logic ----------------------------------------------------------

def test_get_selected_items(fakes):
    a = fakes.add_item(10.0, 5.0, "/a.wav", "Drums", startoffs=2.0, playrate=1.0)
    fakes.select(a)
    items = mod.get_selected_items()
    assert items[0]["audio_path"] == "/a.wav"
    assert items[0]["startoffs"] == 2.0
    assert items[0]["name"] == "Drums"


def test_get_time_selection_none_when_empty(fakes):
    assert mod.get_time_selection() is None


def test_get_time_selection_returns_range(fakes):
    fakes.set_time_selection(3.0, 9.0)
    assert mod.get_time_selection() == (3.0, 9.0)


def test_window_ts_inside_item(fakes):
    assert mod.compute_analysis_window(10.0, 8.0, 0.0, 1.0, (12.0, 16.0)) == (2.0, 6.0, 12.0)


def test_window_no_ts_is_whole_item(fakes):
    assert mod.compute_analysis_window(10.0, 8.0, 0.0, 1.0, None) == (0.0, 8.0, 10.0)


def test_window_ts_no_overlap_returns_none(fakes):
    assert mod.compute_analysis_window(10.0, 8.0, 0.0, 1.0, (50.0, 60.0)) is None
```

- [ ] **Step 3: Run the tests — verify they pass**

Run: `python3 -m pytest tests/test_reels_tempo_map_v2.py -q`
Expected: PASS (12 tests).

- [ ] **Step 4: Commit**

```bash
git add reels_tempo_map_v2.py tests/test_reels_tempo_map_v2.py
git commit -m "feat(tempo-v2): port item/window/madmom helpers with tests"
```

---

## Task 3: `compute_bar_period`

**Files:**
- Modify: `reels_tempo_map_v2.py`
- Modify: `tests/test_reels_tempo_map_v2.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_reels_tempo_map_v2.py`:

```python
# --- phase: bar period -----------------------------------------------------

def test_compute_bar_period_constant():
    assert mod.compute_bar_period([0.0, 2.0, 4.0, 6.0]) == 2.0


def test_compute_bar_period_median_of_first_four():
    # intervals: 2.0, 2.0, 2.0, 10.0 -> median(2,2,2,10) = 2.0 (robust to outlier)
    assert mod.compute_bar_period([0.0, 2.0, 4.0, 6.0, 16.0]) == 2.0


def test_compute_bar_period_too_few_returns_none():
    assert mod.compute_bar_period([5.0]) is None
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m pytest tests/test_reels_tempo_map_v2.py -k compute_bar_period -v`
Expected: FAIL with `AttributeError: module ... has no attribute 'compute_bar_period'`.

- [ ] **Step 3: Implement `compute_bar_period`**

Append to `reels_tempo_map_v2.py` (after `run_madmom`):

```python
# -- PHASE CORRECTION ----------------------------------------------

def compute_bar_period(proj_downbeats):
    """Median of the first (up to 4) downbeat intervals — robust to jitter.

    Returns the bar period in project seconds, or None if there are fewer than
    two downbeats.
    """
    if len(proj_downbeats) < 2:
        return None
    intervals = [proj_downbeats[i + 1] - proj_downbeats[i]
                 for i in range(min(4, len(proj_downbeats) - 1))]
    intervals.sort()
    m = len(intervals) // 2
    if len(intervals) % 2:
        return intervals[m]
    return (intervals[m - 1] + intervals[m]) / 2.0
```

- [ ] **Step 4: Run to verify pass**

Run: `python3 -m pytest tests/test_reels_tempo_map_v2.py -k compute_bar_period -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add reels_tempo_map_v2.py tests/test_reels_tempo_map_v2.py
git commit -m "feat(tempo-v2): compute_bar_period (robust median bar length)"
```

---

## Task 4: `rephase_to_anchor`

**Files:**
- Modify: `reels_tempo_map_v2.py`
- Modify: `tests/test_reels_tempo_map_v2.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_reels_tempo_map_v2.py`:

```python
# --- phase: re-phase to anchor ---------------------------------------------

def test_rephase_shifts_nearest_line_onto_anchor():
    # downbeats start 0.2s late; anchor 0.0, period 0.9 -> shift everything -0.2
    out = mod.rephase_to_anchor([0.2, 1.1, 2.0], 0.0, 0.9)
    assert out == pytest.approx([0.0, 0.9, 1.8])


def test_rephase_picks_nearest_grid_line_when_anacrusis_skipped():
    # first downbeat ~2 bars in (1.8); anchor 0.0, period 0.9 -> stays on grid
    out = mod.rephase_to_anchor([1.8, 2.7, 3.6], 0.0, 0.9)
    assert out == pytest.approx([1.8, 2.7, 3.6])


def test_rephase_noop_without_period():
    assert mod.rephase_to_anchor([1.0, 2.0], 0.0, None) == [1.0, 2.0]
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m pytest tests/test_reels_tempo_map_v2.py -k rephase -v`
Expected: FAIL with `AttributeError: ... 'rephase_to_anchor'`.

- [ ] **Step 3: Implement `rephase_to_anchor`**

Append to `reels_tempo_map_v2.py`:

```python
def rephase_to_anchor(proj_downbeats, anchor, period):
    """Shift the whole downbeat grid by a small delta so the first downbeat lands
    on the grid line (anchor + k*period) nearest to it. This snaps the detected
    phase onto an anchor-based grid without changing bar durations.
    """
    if not proj_downbeats or not period:
        return list(proj_downbeats)
    d0 = proj_downbeats[0]
    k = round((d0 - anchor) / period)
    delta = (anchor + k * period) - d0
    return [d + delta for d in proj_downbeats]
```

- [ ] **Step 4: Run to verify pass**

Run: `python3 -m pytest tests/test_reels_tempo_map_v2.py -k rephase -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add reels_tempo_map_v2.py tests/test_reels_tempo_map_v2.py
git commit -m "feat(tempo-v2): rephase_to_anchor (snap grid line to beat 1)"
```

---

## Task 5: `build_grid` (re-phase + anacrusis back-fill)

**Files:**
- Modify: `reels_tempo_map_v2.py`
- Modify: `tests/test_reels_tempo_map_v2.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_reels_tempo_map_v2.py`:

```python
# --- phase: build_grid (anchor + back-fill) --------------------------------

def test_build_grid_no_anacrusis_starts_on_anchor():
    # first downbeat already ~on the anchor
    out = mod.build_grid([0.05, 0.95, 1.85], anchor=0.0, period=0.9)
    assert out[0] == pytest.approx(0.0)
    assert out == pytest.approx([0.0, 0.9, 1.8])


def test_build_grid_backfills_skipped_anacrusis():
    # madmom skipped ~2 opening bars (first downbeat at 1.8); back-fill to anchor
    out = mod.build_grid([1.8, 2.7, 3.6], anchor=0.0, period=0.9)
    assert out[0] == pytest.approx(0.0)        # beat 1 exactly on anchor
    assert out == pytest.approx([0.0, 0.9, 1.8, 2.7, 3.6])


def test_build_grid_anchor_offset_project_time():
    # anchor at project time 12.0 (time selection start)
    out = mod.build_grid([13.85, 14.75], anchor=12.0, period=0.95)
    assert out[0] == pytest.approx(12.0)
    assert out[1] == pytest.approx(12.95)


def test_build_grid_empty_returns_anchor_only():
    assert mod.build_grid([], anchor=5.0, period=1.0) == [5.0]
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m pytest tests/test_reels_tempo_map_v2.py -k build_grid -v`
Expected: FAIL with `AttributeError: ... 'build_grid'`.

- [ ] **Step 3: Implement `build_grid`**

Append to `reels_tempo_map_v2.py`:

```python
def build_grid(proj_downbeats, anchor, period, eps=1e-6):
    """Produce the final downbeat grid in project time with beat 1 EXACTLY on the
    anchor (time-selection start).

    1. Re-phase the detected downbeats onto an anchor-based grid.
    2. Keep downbeats at or after the anchor.
    3. If the first kept downbeat is within half a bar of the anchor, snap it to
       the anchor. Otherwise (madmom dropped the opening bars) back-fill whole
       bars from the anchor up to the first kept downbeat.
    """
    if not proj_downbeats:
        return [anchor]
    if not period:
        return [anchor] + [d for d in proj_downbeats if d > anchor + eps]
    rp = rephase_to_anchor(proj_downbeats, anchor, period)
    kept = [d for d in rp if d >= anchor - eps]
    if not kept:
        return [anchor]
    if abs(kept[0] - anchor) <= period / 2.0:
        kept[0] = anchor
        return kept
    # back-fill the missed anacrusis bars
    backfill = []
    t = kept[0] - period
    while t >= anchor - eps:
        backfill.append(t)
        t -= period
    backfill.reverse()
    if backfill:
        backfill[0] = anchor          # pin the very first line exactly on the anchor
    else:
        backfill = [anchor]
    return backfill + kept
```

- [ ] **Step 4: Run to verify pass**

Run: `python3 -m pytest tests/test_reels_tempo_map_v2.py -k build_grid -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add reels_tempo_map_v2.py tests/test_reels_tempo_map_v2.py
git commit -m "feat(tempo-v2): build_grid anchors beat 1 + back-fills anacrusis"
```

---

## Task 6: `clear_tempo_markers_in_range` (multi-song-safe narrow delete)

**Files:**
- Modify: `reels_tempo_map_v2.py`
- Modify: `tests/test_reels_tempo_map_v2.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_reels_tempo_map_v2.py`:

```python
# --- multi-song-safe narrow delete -----------------------------------------

def test_clear_removes_only_markers_inside_window(fakes):
    fakes.add_existing_tempo_marker(5.0)    # before window -> survives (other song)
    fakes.add_existing_tempo_marker(12.0)   # inside window  -> deleted
    fakes.add_existing_tempo_marker(14.0)   # inside window  -> deleted
    fakes.add_existing_tempo_marker(40.0)   # after window   -> survives (other song)
    removed = mod.clear_tempo_markers_in_range(10.0, 18.0)
    assert removed == 2
    remaining = [c.timepos for c in fakes.tempo_calls]
    assert remaining == [5.0, 40.0]


def test_clear_nothing_in_empty_project(fakes):
    assert mod.clear_tempo_markers_in_range(0.0, 100.0) == 0
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m pytest tests/test_reels_tempo_map_v2.py -k clear -v`
Expected: FAIL with `AttributeError: ... 'clear_tempo_markers_in_range'`.

- [ ] **Step 3: Implement `clear_tempo_markers_in_range`**

Append to `reels_tempo_map_v2.py`:

```python
# -- MULTI-SONG-SAFE WRITE -----------------------------------------

def clear_tempo_markers_in_range(start, end, eps=1e-6):
    """Delete tempo/time-sig markers whose time is within [start, end] ONLY.

    This is the vault-documented album-mapping pattern: markers of other songs
    live in other time ranges, so they are never touched. Iterate in reverse so
    index deletion stays valid. Returns the count removed.
    """
    n = RPR_CountTempoTimeSigMarkers(0)
    removed = 0
    for i in range(n - 1, -1, -1):
        ret = RPR_GetTempoTimeSigMarker(0, i)
        timepos = ret[3]
        if start - eps <= timepos <= end + eps:
            RPR_DeleteTempoTimeSigMarker(0, i)
            removed += 1
    return removed
```

- [ ] **Step 4: Run to verify pass**

Run: `python3 -m pytest tests/test_reels_tempo_map_v2.py -k clear -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add reels_tempo_map_v2.py tests/test_reels_tempo_map_v2.py
git commit -m "feat(tempo-v2): clear_tempo_markers_in_range (multi-song-safe narrow delete)"
```

---

## Task 7: `create_tempo_markers_v2` (write grid, first marker on anchor, read-back)

**Files:**
- Modify: `reels_tempo_map_v2.py`
- Modify: `tests/test_reels_tempo_map_v2.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_reels_tempo_map_v2.py`:

```python
# --- marker creation -------------------------------------------------------

def test_create_markers_first_on_anchor_4_4(fakes):
    # grid built from downbeats 0.0,2.0,4.0,6.0 at anchor 0.0 -> 120 BPM 4/4
    count = mod.create_tempo_markers_v2([0.0, 2.0, 4.0], 0.0, 4, 4, 6.0, playrate=1.0)
    assert count == 3
    assert fakes.tempo_calls[0].timepos == pytest.approx(0.0)   # beat 1 on anchor
    assert [round(c.bpm, 3) for c in fakes.tempo_calls] == [120.0, 120.0, 120.0]
    # first marker carries the time signature, rest pass 0/0
    assert (fakes.tempo_calls[0].ts_num, fakes.tempo_calls[0].ts_denom) == (4, 4)
    assert (fakes.tempo_calls[1].ts_num, fakes.tempo_calls[1].ts_denom) == (0, 0)
    assert fakes.update_timeline == 1


def test_create_markers_backfilled_first_marker_is_anchor(fakes):
    # madmom skipped the opening bar: downbeats relative to window start at 2.0,4.0,6.0
    # window anchor (project) = 10.0, playrate 1 -> project downbeats 12,14,16
    # back-fill -> first marker at the anchor 10.0
    mod.create_tempo_markers_v2([2.0, 4.0, 6.0], 10.0, 4, 4, 8.0, playrate=1.0)
    assert fakes.tempo_calls[0].timepos == pytest.approx(10.0)


def test_create_markers_7_8_quarter_based_bpm(fakes):
    # 7/8 -> qn_per_bar 3.5; 1.0s bars -> bpm = 3.5*60 = 210
    mod.create_tempo_markers_v2([0.0, 1.0, 2.0], 0.0, 7, 8, 3.0, playrate=1.0)
    assert round(fakes.tempo_calls[0].bpm, 3) == 210.0


def test_create_markers_respects_playrate(fakes):
    # window-relative downbeats compressed by playrate 2 into project time
    mod.create_tempo_markers_v2([0.0, 4.0, 8.0], 10.0, 4, 4, 6.0, playrate=2.0)
    assert [c.timepos for c in fakes.tempo_calls] == pytest.approx([10.0, 12.0, 14.0])
    assert round(fakes.tempo_calls[0].bpm, 2) == 120.0
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m pytest tests/test_reels_tempo_map_v2.py -k create_markers -v`
Expected: FAIL with `AttributeError: ... 'create_tempo_markers_v2'`.

- [ ] **Step 3: Implement `create_tempo_markers_v2` + read-back helper**

Append to `reels_tempo_map_v2.py`:

```python
def _first_marker_pos_near(timepos):
    """Return the actual project time of the tempo marker closest to `timepos`
    (used to verify REAPER did not snap the anchor marker away)."""
    n = RPR_CountTempoTimeSigMarkers(0)
    best = None
    for i in range(n):
        t = RPR_GetTempoTimeSigMarker(0, i)[3]
        if best is None or abs(t - timepos) < abs(best - timepos):
            best = t
    return best


def create_tempo_markers_v2(downbeats, anchor, ts_num, ts_denom, window_end,
                            playrate=1.0):
    """Build an anchored, anacrusis-filled tempo grid and write it.

    downbeats: window-relative madmom downbeats (seconds).
    anchor:    project time the window starts at (= beat 1).
    window_end: project time the window ends at (delete bound for narrow clear).
    Returns the number of markers written.
    """
    qn_per_bar = calc_quarter_notes_per_bar(ts_num, ts_denom)
    if not playrate:
        playrate = 1.0

    # window-relative source time -> project time
    proj_downbeats = [anchor + d / playrate for d in downbeats]
    period = compute_bar_period(proj_downbeats)
    grid = build_grid(proj_downbeats, anchor, period)

    # multi-song-safe: wipe only the current window, then write by time
    clear_tempo_markers_in_range(anchor, window_end)

    count = 0
    for i in range(len(grid) - 1):
        bar_dur = grid[i + 1] - grid[i]
        if bar_dur <= 0:
            continue
        bpm = qn_per_bar * 60.0 / bar_dur
        if bpm < 30 or bpm > 300:
            continue
        if count == 0:
            RPR_SetTempoTimeSigMarker(0, -1, grid[i], -1, 0.0, bpm,
                                       ts_num, ts_denom, False)
        else:
            RPR_SetTempoTimeSigMarker(0, -1, grid[i], -1, 0.0, bpm, 0, 0, False)
        count += 1

    # verify the anchor marker did not get snapped away (live diagnostic)
    if count:
        actual = _first_marker_pos_near(anchor)
        if actual is not None and abs(actual - anchor) > 1e-3:
            log("  WARNING: first marker snapped to {:.4f}s (anchor {:.4f}s, "
                "delta {:.4f}s)".format(actual, anchor, actual - anchor))

    RPR_UpdateTimeline()
    return count
```

- [ ] **Step 4: Run to verify pass**

Run: `python3 -m pytest tests/test_reels_tempo_map_v2.py -k create_markers -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add reels_tempo_map_v2.py tests/test_reels_tempo_map_v2.py
git commit -m "feat(tempo-v2): create_tempo_markers_v2 (anchored write + snap read-back)"
```

---

## Task 8: `main()` wiring + end-to-end / multi-song tests

**Files:**
- Modify: `reels_tempo_map_v2.py`
- Modify: `tests/test_reels_tempo_map_v2.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_reels_tempo_map_v2.py`:

```python
# --- main() end-to-end -----------------------------------------------------

def test_main_anchors_first_marker_on_time_selection_start(fakes, monkeypatch):
    item = fakes.add_item(0.0, 20.0, "/song.wav", "Song")
    fakes.select(item)
    fakes.set_time_selection(5.0, 13.0)           # beat 1 = 5.0
    fakes.set_user_input(True, "4/4")
    # madmom skipped the opening: first downbeat 2.0s into the window
    monkeypatch.setattr(mod, "run_madmom",
                        lambda *a, **k: {"downbeats": [2.0, 4.0, 6.0]})
    mod.main()
    assert fakes.tempo_calls[0].timepos == pytest.approx(5.0)   # exactly on selection start


def test_main_preserves_other_song_tempo_map(fakes, monkeypatch):
    fakes.add_existing_tempo_marker(100.0, bpm=90.0, ts_num=3, ts_denom=4)  # song 2, far away
    item = fakes.add_item(0.0, 20.0, "/song1.wav", "Song1")
    fakes.select(item)
    fakes.set_time_selection(0.0, 8.0)
    fakes.set_user_input(True, "4/4")
    monkeypatch.setattr(mod, "run_madmom",
                        lambda *a, **k: {"downbeats": [0.0, 2.0, 4.0]})
    mod.main()
    survivors = [c.timepos for c in fakes.tempo_calls if c.timepos >= 50.0]
    assert survivors == [100.0]                    # song 2 untouched


def test_main_no_items_shows_message(fakes):
    mod.main()
    assert fakes.message_boxes and "Select" in fakes.message_boxes[0][0]


def test_main_cancel_does_nothing(fakes):
    item = fakes.add_item(0.0, 8.0, "/song.wav")
    fakes.select(item)
    fakes.set_user_input(False, "")
    mod.main()
    assert fakes.tempo_calls == []
    assert fakes.undo_begin == 0


def test_main_invalid_time_sig_aborts(fakes):
    item = fakes.add_item(0.0, 8.0, "/song.wav")
    fakes.select(item)
    fakes.set_user_input(True, "garbage")
    mod.main()
    assert fakes.tempo_calls == []
    assert fakes.message_boxes and "Invalid" in fakes.message_boxes[0][0]


def test_main_full_run_undo_block(fakes, monkeypatch):
    item = fakes.add_item(0.0, 8.0, "/song.wav", "Song")
    fakes.select(item)
    fakes.set_time_selection(0.0, 8.0)
    fakes.set_user_input(True, "4/4")
    monkeypatch.setattr(mod, "run_madmom",
                        lambda *a, **k: {"downbeats": [0.0, 2.0, 4.0]})
    mod.main()
    assert fakes.undo_begin == 1 and fakes.undo_end == 1
    assert fakes.undo_labels == ["Madmom tempo map V2"]
    assert fakes.update_arrange == 1
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m pytest tests/test_reels_tempo_map_v2.py -k main -v`
Expected: FAIL with `AttributeError: ... 'main'`.

- [ ] **Step 3: Implement `main()` + crash-safe entry**

Append to `reels_tempo_map_v2.py`:

```python
# -- MAIN ----------------------------------------------------------

def main():
    log("=== Universal Madmom Tempo Map V2.0 ===\n")
    log("Analyzer: {}\n".format(ANALYZER_SCRIPT))

    items = get_selected_items()
    if not items:
        RPR_ShowMessageBox("Select one or more audio items first.",
                           "Madmom Tempo Map V2", 0)
        return
    log("Selected {} item(s)".format(len(items)))

    rv = RPR_GetUserInputs("Madmom Tempo Map V2", 1,
                           "Time Signature (e.g. 4/4, 7/8, 12/8)", "4/4", 64)
    if not rv[0]:
        return
    ts_input = rv[4]
    ts_num, ts_denom, beats_per_bar = parse_time_sig(ts_input)
    if ts_num is None:
        RPR_ShowMessageBox("Invalid time signature: " + ts_input, "Error", 0)
        return
    log("Time signature: {}/{}, beats_per_bar={}\n".format(ts_num, ts_denom, beats_per_bar))

    ts_range = get_time_selection()
    if ts_range is not None:
        log("Time selection (beat 1 anchor): {:.2f}s - {:.2f}s\n".format(*ts_range))
    else:
        log("No time selection - using item bounds (beat 1 = item start)\n")

    RPR_Undo_BeginBlock()
    for item_info in items:
        log("Processing: {} ({})".format(item_info["name"], item_info["audio_path"]))
        window = compute_analysis_window(
            item_info["position"], item_info["length"],
            item_info["startoffs"], item_info["playrate"], ts_range)
        if window is None:
            log("  Skipped (outside time selection)\n")
            continue
        src_start, src_end, window_proj_start = window
        window_proj_end = window_proj_start + (src_end - src_start) / item_info["playrate"]
        log("  Analyzing source {:.2f}s - {:.2f}s (anchor {:.2f}s)".format(
            src_start, src_end, window_proj_start))

        result = run_madmom(item_info["audio_path"], beats_per_bar, ts_num, ts_denom,
                            src_start, src_end)
        if result is None:
            log("  FAILED - skipping")
            continue

        count = create_tempo_markers_v2(
            result["downbeats"], window_proj_start, ts_num, ts_denom,
            window_proj_end, item_info["playrate"])
        log("  Created {} tempo markers (beat 1 anchored)\n".format(count))

    RPR_Undo_EndBlock("Madmom tempo map V2", -1)
    RPR_UpdateArrange()
    log("Done!")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        tb = traceback.format_exc()
        try:
            RPR_ShowConsoleMsg("\n*** ERROR ***\n" + tb + "\n")
        except Exception:
            pass
        try:
            with open(ERROR_LOG, "w") as _f:
                _f.write(tb)
        except Exception:
            pass
```

- [ ] **Step 4: Run the full V2 suite — verify all pass**

Run: `python3 -m pytest tests/test_reels_tempo_map_v2.py -q`
Expected: PASS (all V2 tests).

- [ ] **Step 5: Run the V1 suite — verify still untouched/green**

Run: `python3 -m pytest tests/test_reels_tempo_map.py -q`
Expected: PASS (V1 unchanged, 45 tests).

- [ ] **Step 6: Commit**

```bash
git add reels_tempo_map_v2.py tests/test_reels_tempo_map_v2.py
git commit -m "feat(tempo-v2): main() wiring + end-to-end & multi-song-safety tests"
```

---

## Task 9: Live verification in REAPER (manual — not automated)

**Files:** none (verification only).

> The first-marker measure-snap is a live-only REAPER behavior the fake cannot
> reproduce. This task confirms the anchor holds and that other songs survive.

- [ ] **Step 1: Single-song anchor check**
  1. Load a song item, make a time selection whose left edge is exactly on the audible beat 1.
  2. Run `reels_tempo_map_v2.py`, enter the song's time signature.
  3. Confirm the FIRST tempo marker sits exactly on the time-selection start (zoom in; it should align with the downbeat transient, not lag ~2s).
  4. If the console logs `WARNING: first marker snapped to ...`, note the delta — that is the residual measure-snap to address (try `measurepos` math; do NOT change V1).

- [ ] **Step 2: Multi-song safety check**
  1. With the song-1 tempo map in place, select the song-2 item further along the timeline, make its time selection on its beat 1, run V2 again.
  2. Confirm song-1's tempo markers are unchanged (positions + BPM intact) and song-2 now has its own anchored map.

- [ ] **Step 3: Anacrusis / pickup check**
  1. Use a song with a pickup/anacrusis intro (where V1 lagged).
  2. Confirm V2 back-fills the opening bar(s) and beat 1 lands on the selection start.

- [ ] **Step 4: Update memory + commit any live fixes**
  - Update memory `reels-tempo-map-state` with the V2 live result (anchor holds? snap residual?).
  - If live edits were needed, commit them: `git commit -m "fix(tempo-v2): <live fix>"`.

---

## Self-Review notes (already applied)

- **Spec coverage:** anchor=selection-start (Task 5/7/8), re-phase (Task 4), back-fill (Task 5), multi-song-safe narrow delete (Task 6/8), snap read-back (Task 7/9 live), crash-safety + undo + log (Task 8), V1 untouched + shared analyzer (Tasks 1/2 copy, no V1 edits; Task 8 Step 5 guards V1 tests).
- **Naming consistency:** `compute_bar_period`, `rephase_to_anchor`, `build_grid`, `clear_tempo_markers_in_range`, `create_tempo_markers_v2`, `_first_marker_pos_near`, `main` — used identically across tasks.
- **Fallback:** no time selection → item bounds, beat 1 = item start (Task 2 `compute_analysis_window` + Task 8 `main`).
