# MIDI Adaptive Quantize V2 — ReaImGui Dialog Design

**Date:** 2026-06-02
**Status:** Approved (brainstorm)
**Worktree/branch:** `.claude/worktrees/midi-adaptive-quantize` / `worktree-midi-adaptive-quantize`
**Pattern source:** mirrors `Grid Align Transients V2` (ReaImGui dropdown dialog). Same
approach, different script (MIDI note quantize) and a green accent theme.

## Problem

`MIDI Adaptive Quantize V1.0`'s parameter entry is `RPR_GetUserInputs` — a single CSV
text field. Every run forces hand-typing choice values (e.g. the word `adaptive`) and a
cryptic `Allow 1/16 (0/1)` flag. There are no real choosers. V2 replaces the input layer
with a one-shot ReaImGui dialog using real dropdowns, leaving the quantize core intact.

## Scope

In scope:
- Replace the text dialog with a **one-shot ReaImGui dialog** (open → choose → Apply →
  close; Cancel/close = no edits).
- Real dropdowns (`ImGui_Combo`) for Mode and Grid; a checkbox for Triplets; numeric
  Threshold.
- A **forest-green accent theme** (dim `0.26/0.55/0.27`, hover/active `0.36/0.72/0.38`).
- Remember last-used settings via `ExtState` (section `MidiAdaptiveQuantize`).
- Keep V1 working: V2 is a COPY (`MIDI Adaptive Quantize V2.0.py`), V1 untouched.

Out of scope: any change to the quantize algorithm; live preview; persistent panel.

## Non-negotiable constraints

- **No `SystemExit`/`sys.exit()`/`exit()`** anywhere — REAPER's embedded interpreter
  routes those to `Py_Exit` and kills the host. The defer loop ends by not re-deferring.
- **MIDI-edit undo registration stays as V1 has it:** `_undo_begin`/`_undo_end` already
  use `Undo_BeginBlock2(0)` + `MarkProjectDirty(0)` + `Undo_OnStateChange2(0,label)` +
  `Undo_EndBlock2(0,label,-1)` (a bare block does NOT record `MIDI_SetNote` edits). Do
  not weaken this.
- The dialog performs no edits until Apply; on ReaImGui import failure it returns None
  gracefully (no crash).

## Architecture

Only the **input layer** changes (mirrors Grid Align V2). The pure functions and the
quantize core (`plan_note_moves`, `_quantize_take`, scope resolution, the
`_undo_begin`/`_undo_end` wrapper) stays
as-is, except a localized grid-resolution change.

```
main()
  └─ run_quantize()                 # entry: routes by config
       ├─ _run_in_reaper(cfg, show_report)   # core; given a full config dict
       └─ _open_dialog()            # NEW interactive path (ReaImGui defer loop)
              └─ _ga_frame()         # per-frame; on Apply -> _run_in_reaper(cfg, show_report=True)
```

- `_read_dialog()` (the `GetUserInputs` CSV parser) is **removed**.
- `_open_dialog()` loads ReaImGui (graceful `None` if missing), applies the green theme,
  and kicks a `defer` loop; `_ga_frame()` renders one frame and, on Apply, builds the
  `config` dict and calls `_run_in_reaper(cfg, show_report=True)`.
- `_run_in_reaper(config, show_report=False)` always receives a full config (no
  `from_dialog` branch); the two message boxes are gated on `show_report`.
- `run_quantize` routes: `headless` → stub; explicit `grid_threshold_ms` → core
  directly; otherwise → `_open_dialog()`.

### ReaImGui usage (Python)

Bundled shim `…/Scripts/ReaTeam Extensions/API/imgui.py` (v0.10.x). Lifecycle: create
context once; `reaper.defer` loop renders one window per frame (`Begin`→widgets→`End`,
End always called); state seeded from `ExtState`. The dropdown items use the
null-separated, null-terminated string form. The dialog string is run via
`RPR_defer("_ga_frame()")` against the module-level frame function (`_GA` holds
`{imgui, ctx, ui}`).

## Window layout & fields

```
┌─ MIDI Adaptive Quantize V2 ────────┐   (green accents)
│ Threshold   [ 15 ] ms              │
│ Mode        [ Snap to grid      ▾ ]│
│ Grid        [ 1/16              ▾ ]│
│ Triplets    [x] include triplet grid│
│        [  Apply  ]   [ Cancel ]    │
└────────────────────────────────────┘
```

| Field | Widget | Options / range | config key |
|---|---|---|---|
| Threshold | `InputInt`/drag | integer ms, default 15 | `grid_threshold_ms` (float) |
| Correction mode | `Combo` | `Snap to grid` / `Adaptive (groove)` | `mode` = `snap`/`adaptive` |
| Grid | `Combo` | `Project grid` / `1/8` / `1/16` / `1/32` | `grid_choice` (new) |
| Triplets | `Checkbox` | on/off | `include_triplets` (bool) |

(There is no "Transient source" field — for MIDI the notes themselves are the events.)

## Green accent theme

In `_ga_frame`, before the widgets, push accent colors and pop the same count after
`End`. Accent slots (each with a hover/active brighter variant):

- `Col_Button` / `Col_ButtonHovered` / `Col_ButtonActive`
- `Col_FrameBg` / `Col_FrameBgHovered` / `Col_FrameBgActive` (combo/input backgrounds)
- `Col_Header` / `Col_HeaderHovered` / `Col_HeaderActive` (combo-selected / checkbox)
- `Col_CheckMark`
- `Col_TitleBgActive`

Palette: base/dim = `rgb(0.26, 0.55, 0.27)`, hover/active = `rgb(0.36, 0.72, 0.38)`.
Colors are packed as ReaImGui expects (0xRRGGBBAA int). Background stays the ReaImGui
default dark. The exact slot→color table and pack helper are pinned in the plan.

## Config schema change: Grid

V1 used a boolean `allow_sixteenth` that hard-forced `fine_qn = min(grid, 0.25)`. V2
replaces it with `grid_choice`, mapped to the fine grid step in QN:

| `grid_choice` | `fine_qn` |
|---|---|
| `project` | project grid QN (`MIDI_GetGrid`) |
| `1/8` | 0.5 |
| `1/16` | 0.25 |
| `1/32` | 0.125 |

Core touch points (local, test-covered):
- `_quantize_take`: derive `fine_qn` from `grid_choice` via a new `resolve_fine_qn`
  helper (instead of the `allow_sixteenth` branch); align the candidate phase
  `q0 = floor(qn_lo/straight_qn)*straight_qn` to the chosen fine grid; pass `fine_qn`
  to `build_grid_candidates_qn`.
- `build_grid_candidates_qn(cfg)`: take an explicit `fine_qn` (straight step) instead of
  the hard-coded `0.25`/`allow_sixteenth`.
- Triplets still subdivide the straight step by 3.

## Settings persistence

Section `MidiAdaptiveQuantize`; keys `threshold_ms`, `mode`, `grid`, `triplets`. Saved
on Apply, read on open; missing/invalid → V1 defaults (`15 / snap / 1/16 / off`).

## Testing (FakeReaper-first, per the reascripts skill)

1. **Pure** → `midi_quant_v2_test_headless.py` (custom python3 harness, copy of the V1
   one repointed): tests for `resolve_fine_qn`, `build_grid_candidates_qn(fine_qn)`,
   `_load_defaults`/`_save_defaults`.
2. **FakeReaper glue** → a local `_reaper_fakes.py` with `FakeImGui` (echoing widgets +
   scripted Apply/Cancel, plus no-op `PushStyleColor`/`PopStyleColor` and integer
   `Col_*()` stubs so the theme calls don't break). Test `_ga_frame`'s
   dropdown-index → config mapping (Mode idx1→`adaptive`, Grid idx3→`1/32`), Apply calls
   `_run_in_reaper(cfg, show_report=True)` once, Cancel/close does nothing, redefer
   otherwise.
3. **Live** → final smoke in REAPER (window opens with green accents + working
   dropdowns; Apply quantizes selected notes/items inside one undo; Cancel no-op;
   ExtState round-trips). Entry asserted free of `SystemExit`.

## Files

- `MIDI Adaptive Quantize V2.0.py` (NEW, copy of V1 + changes). V1 untouched.
- `midi_quant_v2_test_headless.py` (NEW, copy of `midi_quant_test_headless.py`,
  repointed).
- `_reaper_fakes.py` (NEW in the worktree root): FakeImGui (+ style stubs).

## Follow-up

This is the second identical port of the ReaImGui-dropdown-dialog pattern (after Grid
Align V2). Strong case to extract it into a reusable skill — separate cycle.
