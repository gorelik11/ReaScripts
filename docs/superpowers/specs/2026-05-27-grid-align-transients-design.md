# Grid Align Transients — Design

**Date:** 2026-05-27
**Status:** Revised for user review
**Language:** Python ReaScript
**Base:** `Align Track to Reference V2.0.py` onset/split pipeline

## Problem

We need a simpler alignment script derived from `Align Track to Reference`, but
with **grid as reference** instead of another track. The script should:

- detect note attacks/transients in the target material,
- identify only events that are far enough from grid,
- split and move only those local segments to the nearest allowed grid point,
- leave everything else untouched.

Goal: preserve groove while correcting only obvious timing misses.

## User Decisions (captured)

- Core approach: reuse `Align`-style transient logic (`Transient-first`).
- Quantize target: nearest grid point.
- Grid behavior:
  - support current grid lines,
  - support nearest subdivision including 1/16,
  - triplets are **not default**; controlled by a dedicated toggle.
- Triplets UX: separate button/toggle `Include triplets` (`Off` by default).
- Correction policy: only transients with deviation above threshold are edited.
- Editing mode: **in-place** (optimized for time-selection workflow).

## Approaches Considered

1. **Transient-first (selected)**
- Reuse onset detection and grouping behavior from `Align`.
- Compare each detected transient to nearest allowed grid candidate.
- Pros: musical behavior, minimal false edits, consistent with existing tool.
- Cons: slightly more complex grouping logic.

2. Peak-window detection
- Use analysis windows and local peaks without onset matching.
- Pros: simpler implementation.
- Cons: less robust on dense/complex material; more false positives.

3. Marker-assisted workflow
- Use transient markers, then quantize marker-selected positions.
- Pros: visual control.
- Cons: less one-click, introduces extra project objects.

## Functional Design

### Inputs

- `Threshold (ms)` — minimum distance from grid to trigger correction.
- `Mode (0..100)` — same philosophy as `Align`:
  - low = more musical/conservative,
  - high = more precise/aggressive.
  - In this script, `Mode` controls onset sensitivity and grouping window only.
- `Grid candidates`:
  - `Current grid`,
  - `Allow 1/16 candidates` (`Off/On`).
- `Include triplets` (`Off/On`) — if on, triplet candidates join the grid set.
- `Max move (ms)` — safety cap for any single correction.

### Scope precedence

Same as existing alignment scripts:

1. Time selection
2. Selected items
3. Full target range

### Output behavior

- Script performs local split+move on detected out-of-grid attacks.
- Non-target regions remain untouched.
- Gap handling and short crossfade are applied with **in-item-only** operations.
- Single undo point for full operation.
- Multiple selected items are processed independently, item-by-item.
- Trimmed items are supported: analysis and move timing must account for take
  source offset (`D_STARTOFFS`) so detection stays sample-accurate to audible
  item content.
- Split/move operations are constrained to each item's own bounds; no edit may
  leak into neighboring items.

## Algorithm

1. Detect transients in processing scope
- Use the inherited energy-difference peak-picker from `Align V2` (not REAPER
  transient API, not madmom), with sensitivity interpolated by `Mode`.

2. Build candidate grid positions
- Build candidates manually in QN space (tempo-map aware), then map QN -> time:
  `TimeMap2_timeToQN` / `TimeMap2_QNToTime`.
- Do not use `BR_GetClosestGridDivision` as primary matcher, because its result
  follows project grid mode and cannot honor script-local toggles reliably.
- Base family: straight candidates from current grid division.
- If `Allow 1/16 candidates=On`, union straight 1/16 candidates.
- If `Include triplets=On`, add triplet family candidates.
- For each candidate group (see step 4), evaluate straight vs triplet family and
  pick one family for the whole group by lower aggregate absolute timing error.

3. Decide correction
- `delta_ms = transient_time - nearest_grid_time`.
- If `abs(delta_ms) <= threshold`: skip.
- If `abs(delta_ms) > threshold`: mark as correction candidate.

4. Group candidates (musical constraint)
- Group nearby candidates (grouping window derived from `Mode`).
- Per group, choose anchor event with largest `abs(delta_ms)`.
- Move group as one local segment to avoid over-fragmentation.

5. Split and move
- Create split boundaries around each chosen group.
- If `abs(delta) > Max move`: skip that correction (no partial clamp move).
- Else move selected segment by `-delta`.
- Apply right-to-left processing order for stability.

6. Cleanup
- Fill micro-gaps created by shifts.
- Apply small overlap/crossfade without modifying neighboring items.
- Restore selection state where possible.

## Error Handling

- No valid target items in scope -> clear user message and abort.
- No detected transients -> message and abort safely.
- No candidates exceed threshold -> message: nothing to quantize.
- Candidate family conflict in group -> deterministic tie-break to straight.
- Invalid dialog input -> reject and show corrective prompt.
- Item has unsupported `D_PLAYRATE` / reverse / section edge case in V1 ->
  warn and skip item safely.

## Non-Goals (V1)

- Stretch markers or time-stretch quantization.
- Full-note duration quantization (only attack alignment).
- Swing/humanize generation.
- Automatic musical key/rhythm inference.
- New-track clone workflow (V1 is in-place by decision).

## Test Strategy

- Dry runs on:
  - straight 1/16 groove without triplets,
  - groove with intentional triplet attacks with toggle off/on,
  - sparse percussion (few transients),
  - dense material (close attacks),
  - multiple selected items with different start positions,
  - trimmed item (non-zero `D_STARTOFFS`) vs full-source item parity.
  - items with `D_PLAYRATE != 1.0` and reversed takes (warn/skip behavior).
- Validate:
  - only above-threshold events are moved,
  - unchanged regions remain bit-identical in position,
  - no unfilled gaps/click-prone boundaries,
  - behavior differs predictably across `Mode` extremes,
  - trimmed items align by audible content (not raw source position),
  - no cross-item boundary corruption in multi-item processing.
  - max-move overflow events are skipped (never partially moved).
  - group-level family decision preserves intended groove in triplet-toggle mode.

## Implementation Notes

- Start from `Align Track to Reference V2.0.py` and remove dual-track matching.
- Replace reference-onset matcher with grid-candidate matcher.
- Implement grid candidate generation in QN space against project tempo map.
- Keep reverse-order item processing and one-undo transaction.
- Keep UI minimal and REAPER-native (`GetUserInputs` + optional extstate memory).
