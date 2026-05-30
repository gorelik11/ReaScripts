# Grid Align Transients — Design

**Date:** 2026-05-27 (revised 2026-05-30)
**Status:** Revised for user review
**Language:** Python ReaScript
**Base:** `Align Track to Reference V2.0.py` audio-read pipeline (detector replaced)

## Problem

We need a simpler alignment script derived from `Align Track to Reference`, but
with **grid as reference** instead of another track. The script should:

- detect note attacks/transients in the target material,
- identify only events that are far enough from grid,
- split and move only those local segments to the nearest allowed grid point,
- leave everything else untouched and **keep the track essentially "live"** —
  no wholesale slicing like MK Slicer.

Goal: preserve groove while correcting only obvious timing misses.

## User Decisions (captured)

- Core approach: reuse `Align`-style transient logic (`Transient-first`).
- **Detector:** hybrid — reuse `Align V2` decimated audio-read path, but replace
  the energy-frame peak-picker with a **dual-envelope gate** (MK Slicer style).
- **Detection is automatic:** no detector knobs exposed. `Sensitivity`, `Retrig`
  and the noise floor are fixed internal constants. Rationale: without a live
  preview (which a GUI Lua tool like MK Slicer has) blind detector knobs are
  meaningless; the real detector is the relative envelope rise, which is
  level-independent.
- **Two transient sources** (decoupled at the "transient positions" boundary):
  - `Auto-detect` (default) — built-in detector, analysis-only, no pre-split.
  - `Existing splits` — use existing item split/edit points as transient
    positions. Lets a user pre-slice with MK Slicer or REAPER's native Dynamic
    Split (both have previews) and then align only what is off-grid. This is the
    only mode that involves an already-sliced track and it is opt-in.
- Quantize target: nearest allowed grid point.
- Grid behavior:
  - support current grid lines,
  - support nearest subdivision including 1/16 (toggle),
  - triplets are **not default**; controlled by a dedicated toggle.
- **Correction mode toggle:**
  - `Snap to grid` (default) — above-threshold events go to nearest grid.
  - `Adaptive (groove-relative)` — inherit the lag of the previous finalized
    transient when both lag behind the grid (see Algorithm step 4).
- **Max move is automatic:** derived from the finest active grid step, not a
  user ms field. A correction may never cross into a neighbor candidate's slot.
- Correction policy: only transients with deviation above threshold are edited.
- Editing mode: **in-place** (optimized for time-selection workflow).
- **Time selection is a hard boundary** (see Scope).
- **Analysis domain is the item's audible window, not the raw source.**

## Approaches Considered

1. **Transient-first (selected)**
- Reuse audio read from `Align`, replace matcher with grid-candidate matcher.
- Pros: musical behavior, minimal false edits, consistent with existing tool.
- Cons: slightly more complex grouping logic.

2. Peak-window detection
- Use analysis windows and local peaks without onset matching.
- Pros: simpler implementation.
- Cons: less robust on dense/complex material; more false positives.

3. Full MK Slicer hybrid (Lua detector bundled with Python aligner) — rejected
- Pros: maximum control and live preview.
- Cons: heavy/fragile coupling to a large third-party script with no clean API;
  no detection-quality gain (same dual-envelope algorithm). The `Existing
  splits` source captures the useful part of this idea without the coupling.

## Functional Design

### Inputs (dialog — 5 fields)

| Parameter | Values | Purpose |
|---|---|---|
| `Grid threshold (ms)` | number | minimum distance from grid to trigger correction |
| `Transient source` | `Auto-detect` / `Existing splits` | where attack positions come from |
| `Correction mode` | `Snap to grid` / `Adaptive` | how above-threshold events are placed |
| `Allow 1/16` | `Off` / `On` | union straight 1/16 candidates |
| `Include triplets` | `Off` / `On` | union triplet-family candidates |

Removed vs. earlier draft: `Mode (0..100)`, `Detect threshold (dB)`,
`Max move (ms)` — all replaced by automatic/internal behavior.

### Internal detector constants (not exposed)

- Fast envelope: attack 1 ms, release 10 ms.
- Slow envelope: attack 7 ms, release 15 ms.
- Trigger: `env_fast > noise_floor` **and** `env_fast / env_slow > Sensitivity`.
- Noise floor: ~ -60 dB. `Sensitivity` and `Retrig` lockout: fixed MK-style
  defaults.

### Scope precedence

1. **Time selection** — if active, analysis **and** edits happen only inside it;
   its boundaries are hard edges. No sample outside the time selection is
   analyzed, split, or moved. If the time selection is narrower than an item,
   the analysis window is the intersection of the item's audible window and the
   time selection.
2. Selected items.
3. Full target range.

### Analysis domain (item window, not raw source)

Even when a whole item is selected, the analysis domain is the item's **audible
window**, not the underlying source file's full extent. This is the non-obvious
trap for a Python script that reads/resamples the WAV directly: it would
otherwise "see" trimmed-off source tails.

- Recommended read path: `CreateTakeAudioAccessor`. Accessor position 0 is the
  first audible sample of the item, so the trim/`D_STARTOFFS` window is honored
  automatically. (Accessor returns raw source without Take FX — fine for attack
  detection.)
- If raw `wave` reading is used instead, the window must be applied explicitly:
  read only `[D_STARTOFFS … D_STARTOFFS + item_length]`.
- Map detected positions back to project time:
  `project_time = item_pos + (source_time - D_STARTOFFS)`.
- Decimation/resampling math is computed in **seconds** via the source sample
  rate, never in raw sample counts — sample-rate agnostic.

### Output behavior

- Script performs **local** split+move only on detected out-of-grid attacks.
  In `Auto-detect`, detection is analysis-only and never splits the item; the
  only splits created are the ~2 boundaries around each above-threshold
  correction. The rest of the item stays a single continuous "live" region.
- Non-target regions remain untouched.
- Gap handling and short crossfade use **in-item-only** operations.
- Single undo point for full operation.
- Multiple selected items are processed independently, item-by-item.
- Trimmed items are supported (analysis window per Analysis domain above).
- Split/move operations are constrained to each item's own bounds and to the
  active time selection; no edit may leak into neighboring items or outside the
  time selection.
- Audio read path supports common WAV sample rates (44.1k/48k/88.2k/96k/192k)
  and remains sample-rate agnostic in timing math.

## Algorithm

1. **Resolve scope & analysis window** (time selection → selected items → full
   range), clipped to each item's audible window.

2. **Obtain transient positions**
   - `Auto-detect`: read decimated audio for the analysis window and run the
     dual-envelope gate (analysis only, no edits). The trigger sample is the
     attack position; map to project time.
   - `Existing splits`: take existing split/edit boundaries inside the window as
     attack positions (no audio analysis).

3. **Build candidate grid positions**
   - Build candidates in QN space (tempo-map aware), then map QN -> time via
     `TimeMap2_timeToQN` / `TimeMap2_QNToTime`.
   - Do not use `BR_GetClosestGridDivision` as primary matcher (it follows the
     project grid mode and cannot honor script-local toggles reliably).
   - Base family: straight candidates from current grid division.
   - If `Allow 1/16=On`, union straight 1/16 candidates.
   - If `Include triplets=On`, add triplet-family candidates.
   - Per group (step 5), pick straight vs triplet family by lower aggregate
     absolute timing error; deterministic tie-break to straight.

4. **Decide correction (per transient)**
   - `delta = transient_time - nearest_grid_time` (positive = behind/late).
   - If `abs(delta) <= Grid threshold`: skip (event stays as is).
   - Else (above threshold) the target depends on `Correction mode`:
     - **`Snap to grid`:** target = nearest grid time.
     - **`Adaptive`:** processed left→right; `prev` = nearest preceding
       finalized transient, `prev_lag = prev_final - prev_grid`. By construction
       every finalized transient is within threshold of its grid, so the chain
       never drifts. Decision table:

       | Previous | Current | Target for current |
       |---|---|---|
       | ahead of grid | behind grid | grid |
       | behind grid | ahead of grid | grid |
       | behind grid | behind grid | grid + prev_lag |
       | both within threshold | | untouched |

       First event / no preceding transient → fall back to `Snap to grid`.

5. **Group candidates (musical constraint)**
   - Group nearby attacks to avoid over-fragmentation.
   - In `Adaptive`, `prev` for the decision is the previous finalized group
     anchor.

6. **Max-move guard (automatic)**
   - The move may not exceed the finest active grid step / must stay inside the
     intended candidate's slot, so a transient can never be dragged onto a
     neighbor's hit. If a correction would exceed this bound: skip it (no partial
     clamp move).

7. **Split and move (in-place)**
   - Create split boundaries around each chosen group, inside the item only.
   - Move the segment by the computed amount.
   - Right-to-left application order for position stability (decision pass for
     `Adaptive` is left-to-right; application is right-to-left).

8. **Cleanup**
   - Fill micro-gaps created by shifts.
   - Apply small overlap/crossfade with in-item-only operations.
   - Restore selection state where possible.

## Error Handling

- No valid target items in scope -> clear user message and abort.
- No detected transients -> message and abort safely.
- No candidates exceed threshold -> message: nothing to quantize.
- `Existing splits` chosen but item has no usable splits -> message and skip.
- Candidate family conflict in group -> deterministic tie-break to straight.
- Invalid dialog input -> reject and show corrective prompt.
- Item has unsupported `D_PLAYRATE != 1.0` / reverse / section edge case in V1 ->
  warn and skip item safely.

## Non-Goals (V1)

- Stretch markers or time-stretch quantization.
- Full-note duration quantization (only attack alignment).
- Swing/humanize generation.
- Automatic musical key/rhythm inference.
- New-track clone workflow (V1 is in-place by decision).
- Built-in preview/visualization (preview is delegated to MK Slicer / native
  Dynamic Split via the `Existing splits` source).
- Wholesale slicing of the item.

## Test Strategy

- Dry runs on:
  - straight 1/16 groove without triplets,
  - groove with intentional triplet attacks with toggle off/on,
  - sparse percussion (few transients),
  - dense material (close attacks),
  - multiple selected items with different start positions,
  - trimmed item (non-zero `D_STARTOFFS`) vs full-source item parity,
  - same rhythmic source rendered at 44.1k/48k/96k for consistent timing,
  - items with `D_PLAYRATE != 1.0` and reversed takes (warn/skip behavior),
  - `Adaptive` mode: late-after-late inheritance, rush-snaps-to-grid,
    first-event fallback,
  - `Existing splits` source on a pre-sliced item.
- Validate:
  - only above-threshold events are moved,
  - unchanged regions remain bit-identical in position,
  - `Auto-detect` creates no splits outside corrections (track stays live),
  - no unfilled gaps/click-prone boundaries,
  - time-selection boundaries are never crossed,
  - analysis respects the item's audible window, not the raw source,
  - trimmed items align by audible content (not raw source position),
  - no cross-item boundary corruption in multi-item processing,
  - max-move overflow events are skipped (never partially moved),
  - group-level family decision preserves intended groove in triplet-toggle mode,
  - `Adaptive` chain never drifts beyond threshold across a long run.

## Implementation Notes

- Start from `Align Track to Reference V2.0.py` and remove dual-track matching.
- Replace the energy-frame peak-picker with the dual-envelope gate detector.
- Prefer `CreateTakeAudioAccessor` for the read path (item-window correctness).
- Implement grid candidate generation in QN space against project tempo map.
- Keep reverse-order edit application and one-undo transaction.
- Keep UI minimal and REAPER-native (`GetUserInputs` + optional extstate memory).
- Keep the dual-envelope loop on decimated audio to avoid hanging REAPER on long
  selections.
