# MIDI Adaptive Quantize — Design

**Date:** 2026-05-31
**Status:** Approved for implementation
**Language:** Python ReaScript
**Script:** `MIDI Adaptive Quantize V1.0.py`
**Base:** reuses the pure decision core of `Grid Align Transients V1.0.py`
(copied verbatim into a standalone script — no audio code).

## Problem

A MIDI quantizer that corrects **only the note starts that are genuinely off
the grid** (deviation above a threshold) and leaves the rest of the performance
as played, so the groove is preserved — unlike REAPER's built-in full quantize,
which snaps everything. Same selection/decision logic as Grid Align Transients,
applied to MIDI note onsets instead of audio attacks. No audio detection or
slicing.

## User decisions (captured)

- **Reuse Grid Align's pure decision core, COPIED** into a standalone script
  (option B). No shared module yet; drift risk accepted; a later extraction into
  a shared core is possible once both scripts are stable.
- **Drop all audio:** transient detector, audio accessor, splits, gap-fill,
  MK-Slicer, WAV reading. None of it appears here.
- **Edit = quantize note START only.** The note end stays fixed, so the note's
  length changes. Guard: skip a note whose new start would reach or cross its end
  (never create a zero/negative-length note).
- **Grid base = MIDI editor grid** (`MIDI_GetGrid(take)`), with `Allow 1/16` and
  `Include triplets` toggles layered on top (same as Grid Align). The MIDI editor
  grid is independent of the project/arrange grid; we use what the user sees in
  the piano roll.
- **Threshold in milliseconds** (tempo-converted, like Grid Align).
- **Correct both directions** (early and late) when above threshold. **Adaptive**
  mode inherits the previous finalized note's lag (groove-relative); the adaptive
  chain resets per take. **Snap** mode goes to the nearest grid candidate.

## Scope precedence

1. **MIDI editor open AND notes selected** in the active take → exactly those
   selected notes (the explicit pick wins; no time-selection clipping applied).
2. Else, **selected MIDI items**:
   - **with a time selection** → all notes of the selected items whose start
     falls within the time selection;
   - **no time selection** → all notes of the selected items (whole).
3. **No selected items** → show a message and abort.

Notes are read and edited per take; PPQ↔time conversions are per take. (Multiple
selected items / takes are processed independently.)

## Dialog (4 fields, `GetUserInputs`)

| Parameter | Values | Purpose |
|---|---|---|
| `Grid threshold (ms)` | number | minimum off-grid distance to trigger a correction |
| `Correction mode` | `snap` / `adaptive` | nearest grid vs groove-relative lag inheritance |
| `Allow 1/16` | `0` / `1` | union straight 1/16 candidates |
| `Include triplets` | `0` / `1` | union triplet-family candidates |

(The `Transient source` field from Grid Align is removed — MIDI note onsets are
exact, so there is no detection step.)

## Reused pure core (copied verbatim from Grid Align Transients V1.0)

`build_grid_candidates_qn`, `choose_family_for_group`, `group_transients`,
`select_family_positions`, `compute_move`. They operate in QN/seconds with
identical semantics: threshold tolerance, snap/adaptive `prev_lag` chaining,
max-move guard (a move may not exceed one local grid step), straight/triplet
family selection, and time-proximity grouping. **These must stay behaviorally
identical to the audio version** — if the core changes in Grid Align, mirror it
here (the accepted drift risk of option B).

## Algorithm

1. **Resolve scope** → a list of target notes grouped by take.
2. **Per take:** `grid_qn = MIDI_GetGrid(take)`. For each target note, read
   `startppqpos`/`endppqpos` via `MIDI_GetNote`; onset time =
   `MIDI_GetProjTimeFromPPQPos(take, startppqpos)`. `qn_of_time =
   TimeMap2_timeToQN`, `time_of_qn = TimeMap2_QNToTime` (same mapping as Grid
   Align).
3. **Build QN candidates** over the take's target-note QN span, phase-aligned
   (floor the span start to a grid multiple), honoring `allow_sixteenth` /
   `include_triplets`.
4. **Group** onsets with `group_transients` (gap = half the local grid step) so
   chords and flams move as one unit while a 1/16 melodic line quantizes
   note-by-note.
5. **Decide per group, left→right:** `choose_family_for_group` →
   `select_family_positions` → anchor = the note with the largest |delta to its
   nearest candidate| → `compute_move(anchor_delta, threshold_s, mode, prev_lag,
   local_grid_step_s)`, where `local_grid_step_s = grid_step_for(anchor_qn)`
   (tempo-map correct). Thread `prev_lag`; reset it per take.
6. **Apply per group:** shift the START of every note in the group by the
   group's move (delta seconds → new start time → `MIDI_GetPPQPosFromProjTime`
   → `MIDI_SetNote` with the new `startppqpos`, `endppqpos` unchanged,
   `noSortIn=true`). Skip any note whose new start would leave it shorter than a
   minimum length `MIN_NOTE_TICKS` (= 1 PPQ tick).
7. Wrap each take's edits in `MIDI_DisableSort(take)` … `MIDI_Sort(take)`; wrap
   the whole operation in one `Undo_BeginBlock()` / `Undo_EndBlock(name, -1)`.

## Edge cases / error handling

- No target notes in scope → message, abort safely.
- New start would reach/cross the note end → **skip that note** (no degenerate
  length). The max-move guard already bounds the shift to one grid step.
- Multiple takes → processed independently; adaptive chain resets per take.
- Tempo map → local grid step computed per group at the anchor's grid line.
- Muted notes are processed normally (mute is orthogonal to timing).
- Invalid dialog input → reject and abort.

## Entry point (CRITICAL — lesson from the Grid Align crash)

```python
def main():
    run()          # returns normally; NO raise SystemExit / sys.exit / exit()

if __name__ == "__main__":
    main()
```

REAPER runs ReaScripts in an embedded interpreter; a `SystemExit` routes to
`Py_Exit` → C `exit()` and terminates the whole REAPER process. The CLI idiom
`raise SystemExit(main())` is fatal here.

## Non-goals (V1)

- Quantizing note ends or lengths (start only).
- Swing / humanize generation.
- CC / pitch-bend / sysex quantization.
- Cross-take adaptive chaining.
- Extracting a shared core module (deferred; core is copied for now).

## Testing strategy

Maximize headless coverage in a Python fake-REAPER (mock-`RPR`) environment
before any live run:

- **Pure-function tests** (mirror Grid Align's): grid candidates, family
  selection, grouping, `compute_move` snap/adaptive/guard, local grid step.
- **Mock-RPR glue harness** exercising the MIDI path end to end with mocked
  `MIDI_GetNote`/`MIDI_SetNote`, `MIDI_GetGrid`,
  `MIDI_GetProjTimeFromPPQPos`/`MIDI_GetPPQPosFromProjTime`, `TimeMap2_*`, and the
  scope APIs (`CountSelectedMediaItems`, `MIDIEditor_GetActive`/`…GetTake`,
  selected-note flags, time selection). Assertions: only above-threshold notes
  move; start-only (ends unchanged); start-crosses-end notes are skipped; scope
  precedence (selected notes → items+TS → items → none); adaptive chain resets
  per take; tempo-map local step varies across a window.
- **Entry-point regression guard:** `runpy` run as `__main__` with a mocked
  cancel dialog asserts no `SystemExit` is raised.
- **Live REAPER smoke** deferred until the user opens the project — then a small
  selection first, reversible via one undo.

## File structure

- Create: `MIDI Adaptive Quantize V1.0.py` — standalone script (copied pure core
  + MIDI glue + entry point).
- Create: `midi_quant_test_headless.py` — pure-function tests + mock-RPR glue
  tests + entry-point guard.
- Optional: a manual QA checklist under `docs/superpowers/specs/fixtures/`.
