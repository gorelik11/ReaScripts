# Reels Tempo Map V2 — Design Spec

**Date:** 2026-06-08
**Status:** Approved (brainstorming complete)
**Branch:** `feat/grid-align-v2-gui` (working tree)

## Goal

Eliminate the **phase lag** between the real first beat and the first tempo
marker that V1 produces. V1 works live and is the trusted baseline — it stays
**untouched**. V2 is a **new file** built next to it.

## Problem

V1's first tempo marker lags the true musical beat-1 by ~2s. Two independent
causes:

1. **madmom anacrusis (~1.6s):** madmom labels the opening as a pickup/anacrusis,
   so `downbeats[0]` lands ~1.6s into the analysis window instead of at its start.
2. **REAPER measure-snap (~0.5s):** historically suspected snapping of the first
   time-sig marker to the existing measure grid. To be confirmed empirically —
   may be an artifact of the rolled-back full-align code, not a real effect with
   the documented `measurepos=-1` set-by-time pattern.

## Decisions (from brainstorming)

- **Beat-1 anchor = start of the time selection.** No marker-name reading
  (the `EnumProjectMarkers` name came back empty live; only `pos` is reliable).
  The selection start serves both roles: left edge of the analysis window AND
  the phase anchor. Fallback when no time selection: item bounds (beat-1 = item
  start, no hard anchor — same as V1's window logic).
- **Multi-song safety is mandatory.** Mapping song 2 must NOT destroy song 1's
  tempo map. This is achieved by the vault-documented narrow-delete pattern
  (`tempo-detection.md` Workflow 1): delete tempo/time-sig markers **only within
  `[window_start, window_end]`**, then add new markers **by time**
  (`measurepos = -1`). Other songs live in other time ranges → never touched.
  No global tempo-map reset. The "global bar renumbering" concern does not bite
  in practice (vault confirms whole-album mapping preserved each song).

## Algorithm

### Shared analyzer
`reels_madmom_analyze.py` is **shared, unchanged**. It already emits
`downbeats` (window-relative) and `all_beats`.

### V2 flow (`reels_tempo_map_v2.py`)
1. Get selected items + time signature (reuse V1 parsing: `parse_time_sig`,
   `calc_quarter_notes_per_bar`).
2. Determine analysis window per item: time selection → item bounds → whole file
   (reuse V1 `get_time_selection` / `compute_analysis_window`).
3. `window_proj_start = window's project start` = **beat 1**.
4. Run madmom on the window → `downbeats` (window-relative seconds).
5. **Phase fix:**
   - Map to project time: `PD = [window_proj_start + d/playrate for d in downbeats]`.
   - Bar period `P` = median of the first few `PD[i+1]-PD[i]` intervals (robust to
     jitter).
   - **Re-phase:** shift the whole grid by a small `Δ` so the nearest grid line
     lands exactly on `window_proj_start`:
     `Δ = round((PD[0]-window_proj_start)/P)*P - (PD[0]-window_proj_start)`.
   - **Back-fill anacrusis:** if the first re-phased downbeat is > `window_proj_start`,
     prepend `window_proj_start + k*P` for `k=0,1,...` up to it. Beat 1 sits exactly
     on the selection start.
6. **Multi-song-safe write:**
   - Delete existing tempo/time-sig markers with `window_start <= t <= window_end`
     (narrow, bounded — never global).
   - Set markers by time: first marker carries the time signature, rest carry
     bpm only. Try `beatpos = 0.0` (vault) vs `beatpos = -1` (V1) and keep whichever
     keeps the first marker exactly on `window_proj_start`.
   - Read the first marker's position back; if REAPER moved it, nudge/retry.

### BPM
Reuse V1: quarter-note-based, `bpm = qn_per_bar * 60 / bar_dur`, clamp 30–300.

## Safety
- No `SystemExit` / `exit()` (crash class).
- Top-level `try/except` dumps traceback to `~/reels_tempo_map_v2_error.log`.
- `Undo_BeginBlock`/`EndBlock` wrap the edit.
- Never touch automation READ mode.

## Testing (FakeReaper, before live)
New test file `tests/test_reels_tempo_map_v2.py` (V1 tests untouched):
- re-phase snaps the first grid line onto `window_start` (anacrusis 1.6s → beat 1 at 0).
- back-fill reconstructs the missed opening bar(s).
- narrow delete removes only markers inside `[window_start, window_end]`, leaves
  a neighboring "song" marker outside the range intact (multi-song-safety regression).
- snap-defeat: after write, first marker is at `window_start` (assert beatpos variant).
- BPM math regression on a known downbeat sequence.

## Out of scope
- Changing V1 in any way.
- Global tempo-map operations.
- Cross-song bar-number continuity (positions + tempo are preserved; absolute bar
  numbering across songs is explicitly not a goal).

## Files
- NEW: `reels_tempo_map_v2.py`
- NEW: `tests/test_reels_tempo_map_v2.py`
- SHARED/unchanged: `reels_madmom_analyze.py`
- UNCHANGED: `reels_tempo_map.py` (V1), `tests/test_reels_tempo_map.py`
