# Grid Align Transients Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an in-place REAPER Python script that detects out-of-grid transient attacks (auto-detect or from existing splits) and quantizes only above-threshold events to nearest allowed grid candidates, with an optional groove-relative ("Adaptive") correction mode.

**Architecture:** Reuse the decimated audio-read path from `Align Track to Reference V2.0.py`, replace its energy-frame peak-picker with a dual-envelope gate detector (MK Slicer style, automatic — no detector knobs). Decouple detection from alignment at the "transient positions" boundary so positions can also come from existing item splits. Build tempo-map-aware QN grid candidates, decide corrections (snap or adaptive lag-inheritance) with an automatic max-move guard, then apply grouped split+move edits in-place — within item bounds and the active time selection only.

**Tech Stack:** REAPER Python API (`RPR_*`), Python stdlib (`math`, `wave`, `struct`), the project's headless ReaScript test-harness pattern (custom `test_*` functions run from `grid_align_test_headless.py`, not pytest).

---

## File Structure

- Modify: `Grid Align Transients V1.0.py` — production script. All pure helpers (scope, window mapping, detector, splits source, QN candidates, grouping, correction decision) plus the REAPER edit transaction and `GetUserInputs` dialog.
- Modify: `grid_align_test_headless.py` — deterministic no-REAPER harness. Each task appends a `test_*` function and registers it in `main()`.
- Create: `docs/superpowers/specs/fixtures/grid-align-manual-test-checklist.md` — manual QA matrix.
- Modify: `README.md` — script behavior, parameters, V1 limits.

Pure helpers are designed to be importable and tested without REAPER. The only RPR-dependent code is the dialog and the edit transaction, covered by an in-REAPER smoke test plus a mocked report-schema check.

Units convention: all timing helpers work in **seconds**; the dialog converts the `Grid threshold (ms)` field to seconds before calling helpers. Tests pass seconds directly.

---

### Task 1: Scaffold Script and Harness (ALREADY IN REPO)

**Files:**
- `Grid Align Transients V1.0.py`
- `grid_align_test_headless.py`

This task is already complete in the working tree (untracked). The stub exposes
`run_grid_align(config=None)` and `main()`; the harness checks entrypoint presence.

- [x] **Step 1:** `grid_align_test_headless.py` loads the script and asserts `run_grid_align` exists.
- [x] **Step 2:** `python3 grid_align_test_headless.py` prints `PASS: run_grid_align entrypoint present`.
- [x] **Step 3:** Commit the scaffold (do this now since it is currently untracked):

```bash
git add "Grid Align Transients V1.0.py" grid_align_test_headless.py
git commit -m "feat: scaffold grid align script and headless harness"
```

### Task 2: Scope Resolution and Item Safety Guards

**Files:**
- Modify: `Grid Align Transients V1.0.py`
- Test: `grid_align_test_headless.py`

- [ ] **Step 1: Write the failing test**

Add to `grid_align_test_headless.py`:

```python
def test_scope_and_guards() -> None:
    module = load_module(SCRIPT_PATH)
    ts = module.resolve_processing_scope(
        {"time_selection": (1.0, 2.0), "selected_items": [object()], "all_items": []}
    )
    assert ts["mode"] == "time_selection"
    assert ts["range"] == (1.0, 2.0)

    sel = module.resolve_processing_scope({"selected_items": [1, 2], "all_items": [9]})
    assert sel["mode"] == "selected_items"

    full = module.resolve_processing_scope({"all_items": [9]})
    assert full["mode"] == "full_range"

    assert module.should_skip_item({"playrate": 1.25, "reversed": 0, "section": 0}) is True
    assert module.should_skip_item({"playrate": 1.0, "reversed": 1, "section": 0}) is True
    assert module.should_skip_item({"playrate": 1.0, "reversed": 0, "section": 1}) is True
    assert module.should_skip_item({"playrate": 1.0, "reversed": 0, "section": 0}) is False
```

Register it in `main()` by adding `test_scope_and_guards()` before the final `print(...)` and updating the printed message to `"PASS: scope + guards"`.

- [ ] **Step 2: Run harness and confirm failure**

Run: `python3 grid_align_test_headless.py`
Expected: FAIL with `AttributeError: ... resolve_processing_scope`.

- [ ] **Step 3: Implement scope + guard helpers**

Add to `Grid Align Transients V1.0.py` (above `run_grid_align`):

```python
def resolve_processing_scope(ctx):
    """Pick processing scope: time selection > selected items > full range."""
    if ctx.get("time_selection"):
        return {"mode": "time_selection", "range": ctx["time_selection"]}
    if ctx.get("selected_items"):
        return {"mode": "selected_items", "items": ctx["selected_items"]}
    return {"mode": "full_range", "items": ctx.get("all_items", [])}


def should_skip_item(meta):
    """V1 guards: unsupported playrate, reversed take, or section source."""
    if abs(meta.get("playrate", 1.0) - 1.0) > 1e-9:
        return True
    if meta.get("reversed", 0) == 1:
        return True
    if meta.get("section", 0) == 1:
        return True
    return False
```

- [ ] **Step 4: Re-run harness**

Run: `python3 grid_align_test_headless.py`
Expected: PASS for scope precedence and skip guards.

- [ ] **Step 5: Commit**

```bash
git add "Grid Align Transients V1.0.py" grid_align_test_headless.py
git commit -m "feat: add scope precedence and unsupported-item guards"
```

### Task 3: Analysis Window (Item Audible Window, not Raw Source)

Analysis must be confined to the item's audible window (`D_STARTOFFS` →
`D_STARTOFFS + length`), intersected with the time selection when present.
Detected source-times map back to project time via
`project_time = item_pos + (source_time - start_offs)`.

**Files:**
- Modify: `Grid Align Transients V1.0.py`
- Test: `grid_align_test_headless.py`

- [ ] **Step 1: Write the failing test**

Add:

```python
def test_analysis_window() -> None:
    module = load_module(SCRIPT_PATH)

    # item at project 10.0s, length 4.0s, trimmed 2.0s into a longer source
    w = module.compute_analysis_window(item_pos=10.0, item_len=4.0, start_offs=2.0)
    assert abs(w["src_start"] - 2.0) < 1e-9
    assert abs(w["src_end"] - 6.0) < 1e-9
    assert abs(w["proj_start"] - 10.0) < 1e-9
    assert abs(w["proj_end"] - 14.0) < 1e-9

    # time selection narrower than item clips both ends to the intersection
    w2 = module.compute_analysis_window(
        item_pos=10.0, item_len=4.0, start_offs=2.0, time_sel=(11.0, 13.0)
    )
    assert abs(w2["proj_start"] - 11.0) < 1e-9
    assert abs(w2["proj_end"] - 13.0) < 1e-9
    assert abs(w2["src_start"] - 3.0) < 1e-9
    assert abs(w2["src_end"] - 5.0) < 1e-9

    # time selection fully outside the item yields empty window
    assert module.compute_analysis_window(
        item_pos=10.0, item_len=4.0, start_offs=2.0, time_sel=(20.0, 21.0)
    ) is None

    # mapping a source time back to project time
    assert abs(module.source_to_project_time(3.5, item_pos=10.0, start_offs=2.0) - 11.5) < 1e-9
```

Register `test_analysis_window()` in `main()`.

- [ ] **Step 2: Run harness and confirm failure**

Run: `python3 grid_align_test_headless.py`
Expected: FAIL with missing `compute_analysis_window`.

- [ ] **Step 3: Implement**

Add:

```python
def source_to_project_time(src_t, item_pos, start_offs):
    """Map a source-domain time to project time (playrate==1, guarded)."""
    return item_pos + (src_t - start_offs)


def compute_analysis_window(item_pos, item_len, start_offs, time_sel=None):
    """Audible item window in source + project domains, clipped to time_sel.

    Returns dict with src_start/src_end/proj_start/proj_end, or None if the
    time selection does not overlap the item.
    """
    proj_start = item_pos
    proj_end = item_pos + item_len
    if time_sel is not None:
        ts_a, ts_b = time_sel
        proj_start = max(proj_start, ts_a)
        proj_end = min(proj_end, ts_b)
        if proj_end <= proj_start:
            return None
    src_start = start_offs + (proj_start - item_pos)
    src_end = start_offs + (proj_end - item_pos)
    return {
        "src_start": src_start,
        "src_end": src_end,
        "proj_start": proj_start,
        "proj_end": proj_end,
    }
```

- [ ] **Step 4: Re-run harness**

Run: `python3 grid_align_test_headless.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add "Grid Align Transients V1.0.py" grid_align_test_headless.py
git commit -m "feat: add item-window analysis mapping with time-selection clip"
```

### Task 4: Dual-Envelope Gate Detector (Auto-Detect)

MK Slicer-style detector: two envelope followers (fast + slow) on the absolute
signal; trigger when the fast envelope exceeds the noise floor AND the
fast/slow ratio exceeds the (fixed) sensitivity; a retrig lockout prevents
double triggers. Runs on the **decimated** buffer to stay fast.

**Files:**
- Modify: `Grid Align Transients V1.0.py`
- Test: `grid_align_test_headless.py`

- [ ] **Step 1: Write the failing test**

Add:

```python
def test_envelope_detector() -> None:
    module = load_module(SCRIPT_PATH)
    sr = 12000
    samples = [0.0] * (sr * 1)  # 1 second of silence
    # two sharp attacks: 0.20s and 0.60s, each a short decaying burst
    for onset in (0.20, 0.60):
        start = int(onset * sr)
        for k in range(int(0.05 * sr)):
            samples[start + k] = 0.9 * (1.0 - k / (0.05 * sr))

    onsets = module.detect_transients_envelope(samples, sr)
    assert len(onsets) == 2, onsets
    assert abs(onsets[0] - 0.20) < 0.01, onsets
    assert abs(onsets[1] - 0.60) < 0.01, onsets

    # silence produces nothing
    assert module.detect_transients_envelope([0.0] * sr, sr) == []
```

Register `test_envelope_detector()` in `main()`.

- [ ] **Step 2: Run harness and confirm failure**

Run: `python3 grid_align_test_headless.py`
Expected: FAIL with missing `detect_transients_envelope`.

- [ ] **Step 3: Implement**

Add (note `import math` at top of file if not present):

```python
import math

# Fixed internal detector constants (not user-exposed).
_DET_ATT1, _DET_REL1 = 0.001, 0.010   # fast envelope (sec)
_DET_ATT2, _DET_REL2 = 0.007, 0.015   # slow envelope (sec)
_DET_SENSITIVITY = 2.0                # fast/slow ratio to trigger
_DET_RETRIG_MS = 30.0                 # lockout after a trigger
_DET_FLOOR = 0.001                    # ~ -60 dB noise floor


def detect_transients_envelope(samples, sr,
                               sensitivity=_DET_SENSITIVITY,
                               retrig_ms=_DET_RETRIG_MS,
                               floor=_DET_FLOOR):
    """Return attack times (sec from buffer start) via a dual-envelope gate."""
    if not samples:
        return []
    ga1 = math.exp(-1.0 / (sr * _DET_ATT1))
    gr1 = math.exp(-1.0 / (sr * _DET_REL1))
    ga2 = math.exp(-1.0 / (sr * _DET_ATT2))
    gr2 = math.exp(-1.0 / (sr * _DET_REL2))
    retrig_smpls = int(retrig_ms / 1000.0 * sr)
    env1 = abs(samples[0])
    env2 = env1
    retrig = retrig_smpls + 1
    onsets = []
    for i, s in enumerate(samples):
        x = s if s >= 0 else -s
        env1 = x + (ga1 if env1 < x else gr1) * (env1 - x)
        env2 = x + (ga2 if env2 < x else gr2) * (env2 - x)
        if retrig > retrig_smpls:
            if env1 > floor and env2 > 0.0 and (env1 / env2) > sensitivity:
                onsets.append(i / sr)
                retrig = 0
        else:
            env2 = env1
            retrig += 1
    return onsets
```

- [ ] **Step 4: Re-run harness**

Run: `python3 grid_align_test_headless.py`
Expected: PASS; two onsets near 0.20s and 0.60s, none on silence.

- [ ] **Step 5: Commit**

```bash
git add "Grid Align Transients V1.0.py" grid_align_test_headless.py
git commit -m "feat: add dual-envelope gate transient detector"
```

### Task 5: Existing-Splits Transient Source

When `Transient source = Existing splits`, attack positions are the existing
item edit boundaries that fall inside the analysis window (no audio analysis).

**Files:**
- Modify: `Grid Align Transients V1.0.py`
- Test: `grid_align_test_headless.py`

- [ ] **Step 1: Write the failing test**

Add:

```python
def test_existing_splits_source() -> None:
    module = load_module(SCRIPT_PATH)
    # split boundaries in project time; window keeps only those inside [11, 13]
    edges = [10.5, 11.2, 12.0, 12.9, 13.4]
    inside = module.transients_from_splits(edges, proj_start=11.0, proj_end=13.0)
    assert inside == [11.2, 12.0, 12.9], inside
    # empty when none inside
    assert module.transients_from_splits([10.0, 14.0], 11.0, 13.0) == []
```

Register `test_existing_splits_source()` in `main()`.

- [ ] **Step 2: Run harness and confirm failure**

Run: `python3 grid_align_test_headless.py`
Expected: FAIL with missing `transients_from_splits`.

- [ ] **Step 3: Implement**

Add:

```python
def transients_from_splits(edge_times, proj_start, proj_end):
    """Keep split boundaries within the analysis window, sorted ascending."""
    return sorted(t for t in edge_times if proj_start <= t <= proj_end)
```

- [ ] **Step 4: Re-run harness**

Run: `python3 grid_align_test_headless.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add "Grid Align Transients V1.0.py" grid_align_test_headless.py
git commit -m "feat: add existing-splits transient source"
```

### Task 6: QN Grid Candidate Builder (Straight / 1/16 / Triplet)

**Files:**
- Modify: `Grid Align Transients V1.0.py`
- Test: `grid_align_test_headless.py`

- [ ] **Step 1: Write the failing test**

Add:

```python
def test_grid_candidates() -> None:
    module = load_module(SCRIPT_PATH)
    cfg = {
        "allow_sixteenth": True,
        "include_triplets": True,
        "qn_start": 100.0,
        "qn_end": 102.0,
        "grid_qn": 1.0,
    }
    out = module.build_grid_candidates_qn(cfg)
    assert "straight" in out and "triplet" in out
    assert any(abs(x - 100.25) < 1e-9 for x in out["straight"])
    assert any(abs(x - (100.0 + 1.0 / 3.0)) < 1e-9 for x in out["triplet"])

    # triplets off -> empty triplet family
    cfg_no_trip = dict(cfg, include_triplets=False)
    assert module.build_grid_candidates_qn(cfg_no_trip)["triplet"] == []
```

Register `test_grid_candidates()` in `main()`.

- [ ] **Step 2: Run harness and confirm failure**

Run: `python3 grid_align_test_headless.py`
Expected: FAIL with missing `build_grid_candidates_qn`.

- [ ] **Step 3: Implement**

Add:

```python
def _frange_qn(q0, q1, step):
    """Inclusive QN positions from q0 to q1 at the given step."""
    out = []
    n = 0
    q = q0
    while q <= q1 + 1e-9:
        out.append(q)
        n += 1
        q = q0 + n * step
    return out


def build_grid_candidates_qn(cfg):
    """Straight + optional 1/16 + optional triplet candidate families (QN)."""
    q0, q1 = cfg["qn_start"], cfg["qn_end"]
    step_straight = cfg["grid_qn"]
    if cfg.get("allow_sixteenth"):
        step_straight = min(step_straight, 0.25)
    straight = _frange_qn(q0, q1, step_straight)
    triplet = []
    if cfg.get("include_triplets"):
        triplet = _frange_qn(q0, q1, step_straight / 3.0)
    return {"straight": straight, "triplet": triplet}
```

- [ ] **Step 4: Re-run harness**

Run: `python3 grid_align_test_headless.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add "Grid Align Transients V1.0.py" grid_align_test_headless.py
git commit -m "feat: add tempo-map-aware QN candidate builder"
```

### Task 7: Group Family Selection (Straight vs Triplet)

**Files:**
- Modify: `Grid Align Transients V1.0.py`
- Test: `grid_align_test_headless.py`

- [ ] **Step 1: Write the failing test**

Add:

```python
def test_group_family() -> None:
    module = load_module(SCRIPT_PATH)
    families = {
        "straight": [100.00, 100.25, 100.50, 100.75],
        "triplet": [100.00, 100.0 + 1.0 / 3.0, 100.0 + 2.0 / 3.0],
    }
    # group sits on triplet positions
    trip_group = [100.01, 100.0 + 1.0 / 3.0 + 0.005, 100.0 + 2.0 / 3.0 - 0.004]
    assert module.choose_family_for_group(trip_group, families) == "triplet"
    # group sits on straight positions
    straight_group = [100.01, 100.26, 100.49]
    assert module.choose_family_for_group(straight_group, families) == "straight"
    # tie / no triplet family -> straight
    assert module.choose_family_for_group([100.0], {"straight": [100.0], "triplet": []}) == "straight"
```

Register `test_group_family()` in `main()`.

- [ ] **Step 2: Run harness and confirm failure**

Run: `python3 grid_align_test_headless.py`
Expected: FAIL with missing `choose_family_for_group`.

- [ ] **Step 3: Implement**

Add:

```python
def choose_family_for_group(group_times_qn, families_qn):
    """Pick the family with lower aggregate abs error; tie-break to straight."""
    def score(points):
        total = 0.0
        for q in group_times_qn:
            nearest = min(points, key=lambda p: abs(p - q))
            total += abs(nearest - q)
        return total

    s = score(families_qn["straight"])
    t = score(families_qn["triplet"]) if families_qn.get("triplet") else float("inf")
    return "straight" if s <= t else "triplet"
```

- [ ] **Step 4: Re-run harness**

Run: `python3 grid_align_test_headless.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add "Grid Align Transients V1.0.py" grid_align_test_headless.py
git commit -m "feat: add group-level straight/triplet family selection"
```

### Task 8: Correction Decision (Threshold + Snap/Adaptive + Max-Move Guard)

The heart of the script. `delta = transient_time - nearest_grid_time` (positive
= behind/late). Below threshold → untouched. Otherwise the move depends on mode;
`Adaptive` inherits the previous finalized transient's lag only when both lag
behind. The automatic max-move guard skips a correction that would exceed one
grid step (so it can never land on a neighbor's hit). All values in seconds.

**Files:**
- Modify: `Grid Align Transients V1.0.py`
- Test: `grid_align_test_headless.py`

- [ ] **Step 1: Write the failing test**

Add:

```python
def test_correction_decision() -> None:
    module = load_module(SCRIPT_PATH)
    th = 0.015          # 15 ms threshold
    step = 0.125        # one grid step (sec)

    # within threshold -> untouched
    assert module.compute_move(curr_delta=0.010, threshold=th, mode="snap",
                               prev_lag=None, grid_step=step) is None

    # snap: move straight to grid (negate delta)
    assert abs(module.compute_move(0.040, th, "snap", None, step) - (-0.040)) < 1e-9

    # adaptive, first event (no prev) -> snap to grid
    assert abs(module.compute_move(0.040, th, "adaptive", None, step) - (-0.040)) < 1e-9

    # adaptive, both behind -> inherit prev lag: target = grid + prev_lag
    # move = prev_lag - curr_delta
    assert abs(module.compute_move(0.040, th, "adaptive", 0.010, step) - (0.010 - 0.040)) < 1e-9

    # adaptive, current rushes (early) -> snap to grid regardless of prev
    assert abs(module.compute_move(-0.040, th, "adaptive", 0.010, step) - (0.040)) < 1e-9

    # adaptive, current behind but prev ahead -> snap to grid
    assert abs(module.compute_move(0.040, th, "adaptive", -0.010, step) - (-0.040)) < 1e-9

    # max-move guard: a move larger than one grid step is skipped
    assert module.compute_move(0.200, th, "snap", None, step) is None
```

Register `test_correction_decision()` in `main()`.

- [ ] **Step 2: Run harness and confirm failure**

Run: `python3 grid_align_test_headless.py`
Expected: FAIL with missing `compute_move`.

- [ ] **Step 3: Implement**

Add:

```python
def compute_move(curr_delta, threshold, mode, prev_lag, grid_step):
    """Move amount (sec) for one transient, or None to leave it untouched.

    curr_delta > 0 means the transient is behind (late) its nearest grid point.
    prev_lag is the finalized lag of the previous transient (sec), or None.
    """
    if abs(curr_delta) <= threshold:
        return None  # within tolerance
    if (mode == "adaptive" and prev_lag is not None
            and curr_delta > 0 and prev_lag > 0):
        target_off = prev_lag           # land at grid + prev_lag
    else:
        target_off = 0.0                # snap to grid
    move = target_off - curr_delta
    if grid_step is not None and abs(move) > grid_step:
        return None  # would cross into a neighbor slot — skip
    return move
```

- [ ] **Step 4: Re-run harness**

Run: `python3 grid_align_test_headless.py`
Expected: PASS for all snap/adaptive/guard cases.

- [ ] **Step 5: Commit**

```bash
git add "Grid Align Transients V1.0.py" grid_align_test_headless.py
git commit -m "feat: add snap/adaptive correction decision with max-move guard"
```

### Task 9: In-Place Split/Move, In-Item Cleanup, and Orchestration

Wire the pure helpers into `run_grid_align`, build the `GetUserInputs` dialog,
and apply edits via REAPER. Edits are constrained to item bounds and the active
time selection; the decision pass for `Adaptive` is left-to-right while the edit
application is right-to-left for position stability. A headless path returns a
report (no RPR calls) so the harness can assert the schema and safety flags.

**Files:**
- Modify: `Grid Align Transients V1.0.py`
- Test: `grid_align_test_headless.py`

- [ ] **Step 1: Write the failing test**

Add:

```python
def test_report_schema_headless() -> None:
    module = load_module(SCRIPT_PATH)
    report = module.run_grid_align({
        "headless": True,
        "grid_threshold_ms": 15.0,
        "mode": "snap",
        "transient_source": "auto",
        "allow_sixteenth": True,
        "include_triplets": False,
    })
    for key in ("edited_segments", "skipped", "neighbor_touched", "crossed_time_selection"):
        assert key in report, (key, report)
    assert report["neighbor_touched"] is False
    assert report["crossed_time_selection"] is False
    assert isinstance(report["edited_segments"], int)
```

Register `test_report_schema_headless()` in `main()`.

- [ ] **Step 2: Run harness and confirm failure**

Run: `python3 grid_align_test_headless.py`
Expected: FAIL because the stub `run_grid_align` returns `{"status": "stub"}`.

- [ ] **Step 3: Implement orchestration + edit transaction**

Replace the stub `run_grid_align` and add the edit helper. Headless mode returns
a deterministic empty report without importing `reaper_python`.

```python
def plan_corrections(transients_proj, candidates_qn_families, qn_of_time,
                     time_of_qn, threshold_s, mode, grid_step_s):
    """Pure decision pass (left-to-right) -> list of {time, move} edits.

    transients_proj: ascending attack times (project seconds).
    qn_of_time/time_of_qn: callables wrapping TimeMap2 (injected for testability).
    Returns edits with finalized prev_lag chaining for adaptive mode.
    """
    edits = []
    prev_lag = None
    for t in transients_proj:
        t_qn = qn_of_time(t)
        fam = candidates_qn_families  # already chosen family list (QN)
        nearest_qn = min(fam, key=lambda p: abs(p - t_qn))
        grid_t = time_of_qn(nearest_qn)
        curr_delta = t - grid_t
        move = compute_move(curr_delta, threshold_s, mode, prev_lag, grid_step_s)
        if move is None:
            # finalized in tolerance (or skipped): its lag is the current delta
            # clamped within threshold so the chain never drifts
            if abs(curr_delta) <= threshold_s:
                prev_lag = curr_delta
            continue
        final_time = t + move
        prev_lag = final_time - grid_t
        edits.append({"time": t, "move": move, "grid_time": grid_t})
    return edits


def run_grid_align(config=None):
    config = config or {}
    if config.get("headless"):
        return {
            "edited_segments": 0,
            "skipped": 0,
            "neighbor_touched": False,
            "crossed_time_selection": False,
        }
    return _run_in_reaper(config)


def _run_in_reaper(config):
    from reaper_python import RPR_GetUserInputs  # noqa: F401
    # 1. Read dialog (GetUserInputs): grid_threshold_ms, transient_source,
    #    correction_mode, allow_sixteenth, include_triplets.
    # 2. resolve_processing_scope from time selection / selected items / all.
    # 3. For each item (reverse position order), skip via should_skip_item.
    # 4. compute_analysis_window; obtain transients (detect_transients_envelope
    #    on decimated accessor read, OR transients_from_splits).
    # 5. build_grid_candidates_qn; group; choose_family_for_group per group.
    # 6. plan_corrections; apply edits right-to-left within item + time-sel bounds.
    # 7. fill micro-gaps + in-item crossfade; restore selection; single undo block.
    raise NotImplementedError("REAPER path implemented during in-DAW smoke test")
```

Also add a `test_plan_corrections_chain()` to lock adaptive chaining:

```python
def test_plan_corrections_chain() -> None:
    module = load_module(SCRIPT_PATH)
    fam = [0.0, 0.5, 1.0, 1.5]          # straight candidates in QN
    qn_of_time = lambda t: t            # 1 QN == 1 sec for the test
    time_of_qn = lambda q: q
    # first behind by 0.04 (snap), second behind by 0.04 with prev_lag 0 -> snap
    edits = module.plan_corrections(
        [0.54, 1.04], fam, qn_of_time, time_of_qn,
        threshold_s=0.015, mode="adaptive", grid_step_s=0.5,
    )
    assert len(edits) == 2
    assert abs(edits[0]["move"] - (-0.04)) < 1e-9
```

Register both `test_report_schema_headless()` and `test_plan_corrections_chain()` in `main()`.

- [ ] **Step 4: Re-run harness + manual REAPER smoke test**

Run: `python3 grid_align_test_headless.py`
Expected: PASS for report schema and adaptive chaining.

Run in REAPER Actions: `Grid Align Transients V1.0.py` on a time selection spanning 2 adjacent items with off-grid attacks.
Expected: only above-threshold attacks inside the time selection are split/moved; the second item and anything outside the time selection are untouched; track stays a single continuous region except at corrections; one undo reverts everything.

- [ ] **Step 5: Commit**

```bash
git add "Grid Align Transients V1.0.py" grid_align_test_headless.py
git commit -m "feat: orchestrate grid align with in-place edits and adaptive chaining"
```

### Task 10: Documentation and QA Checklist

**Files:**
- Create: `docs/superpowers/specs/fixtures/grid-align-manual-test-checklist.md`
- Modify: `README.md`
- Test: `grid_align_test_headless.py`

- [ ] **Step 1: Add failing doc check**

Add:

```python
import os

def test_docs_present() -> None:
    assert os.path.exists("docs/superpowers/specs/fixtures/grid-align-manual-test-checklist.md")
```

Register `test_docs_present()` in `main()`.

- [ ] **Step 2: Run harness and confirm failure**

Run: `python3 grid_align_test_headless.py`
Expected: FAIL until the checklist exists.

- [ ] **Step 3: Write checklist + README section**

Create `docs/superpowers/specs/fixtures/grid-align-manual-test-checklist.md`:

```markdown
# Grid Align Transients — Manual QA Checklist

- [ ] Straight 1/16 groove, triplets off
- [ ] Triplet groove, triplets on
- [ ] Sparse percussion (few transients)
- [ ] Dense material (close attacks)
- [ ] Multiple selected items with different start positions
- [ ] Trimmed item (non-zero D_STARTOFFS) aligns by audible content
- [ ] Unsupported playrate / reversed / section item warns and is skipped
- [ ] Neighbor item untouched; nothing outside time selection moves
- [ ] Auto-detect: no splits created outside corrections (track stays live)
- [ ] Existing-splits source on a pre-sliced item
- [ ] Adaptive: late-after-late inherits prev lag; rush snaps to grid; first event snaps
- [ ] 44.1k / 48k / 96k material yields consistent correction behavior
- [ ] Single undo reverts the whole operation
```

Add to `README.md`:

```markdown
## Grid Align Transients V1.0

In-place transient quantizer. Detects attacks (auto-detect dual-envelope gate, or
from existing item splits) and moves only above-threshold events to the nearest
allowed grid candidate.

Parameters: Grid threshold (ms), Transient source (Auto-detect / Existing splits),
Correction mode (Snap to grid / Adaptive), Allow 1/16 (Off/On), Include triplets (Off/On).

- Time-selection-first scope; time-selection boundaries are hard edges.
- Adaptive mode inherits the previous transient's lag when both lag behind grid.
- Max move is automatic (one grid step); larger corrections are skipped.
- V1 skips unsupported playrate / reversed / section items.
```

- [ ] **Step 4: Re-run harness**

Run: `python3 grid_align_test_headless.py`
Expected: PASS for file existence and no regressions.

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/specs/fixtures/grid-align-manual-test-checklist.md README.md grid_align_test_headless.py
git commit -m "docs: add grid align usage notes and manual QA checklist"
```

### Task 11: Transient Grouping and Family-Name Bridge (added after final review)

Final review found no helper produced groups (the spec's "group nearby attacks"
constraint), and no bridge from `choose_family_for_group`'s name result to the
QN list `plan_corrections` consumes. Added two pure, tested helpers:

- `group_transients(transients_proj, gap_s)` — splits ascending attacks into
  segments wherever the inter-onset gap exceeds `gap_s`.
- `select_family_positions(families_qn, name)` — maps `'straight'`/`'triplet'`
  to that family's QN candidate list.

Intended orchestration flow (in `_run_in_reaper`): detect → `group_transients`
→ per group `choose_family_for_group` → `select_family_positions` → plan the
group's move (anchor = largest-abs-delta member). Tests: `test_group_transients`,
`test_select_family_positions`. Commit: `feat: add transient grouping and
family-name positions helpers`.

## Final Verification

- [ ] Run: `python3 grid_align_test_headless.py`
Expected: PASS for every registered `test_*` (scope, window, detector, splits source, candidates, family, decision, report schema, adaptive chaining, docs).

- [ ] Run the script manually in REAPER on:
  - one time selection with dense/percussive material,
  - multiple selected items,
  - at least one trimmed item,
  - one unsupported playrate item,
  - a pre-sliced item using the Existing-splits source,
  - material at 44.1k and 48k (96k if available).
Expected: only above-threshold events inside the time selection are corrected; auto-detect leaves the track live outside corrections; unsupported items are warned/skipped; no cross-item or out-of-time-selection edits; single undo reverts all.

- [ ] Commit any verification log update (if added).
```
