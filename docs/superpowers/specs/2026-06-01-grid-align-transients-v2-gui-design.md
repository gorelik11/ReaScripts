# Grid Align Transients V2 — ReaImGui Dialog Design

**Date:** 2026-06-01
**Status:** Approved (brainstorm)
**Supersedes input layer of:** `2026-05-27-grid-align-transients-design.md`

## Problem

V1's parameter entry is `RPR_GetUserInputs` — a single CSV text field. Every run
forces the user to hand-type choice values (e.g. the word `adaptive`) and a
cryptic `Allow 1/16 (0/1)` flag. There are no real choosers. The goal of V2 is to
**fix the input UX**: replace typed choices with real dropdowns, while leaving the
proven processing core untouched.

## Scope

In scope:
- Replace the text dialog with a **one-shot ReaImGui dialog** (open → choose →
  Apply → close; Cancel/close = no edits).
- Real dropdowns (`ImGui_Combo`) for every field that is a choice.
- Remember last-used settings via `ExtState` and preload them as defaults.

Out of scope (future phase): live waveform/transient preview; persistent always-on
panel; any change to detection or correction algorithms.

## Non-negotiable constraints

- **No `SystemExit`/`sys.exit()`/`exit()`** anywhere — REAPER's embedded
  interpreter routes those to `Py_Exit` and kills the host. The defer loop ends by
  simply not re-deferring.
- Processing stays inside **one** `Undo_BeginBlock`/`Undo_EndBlock` (already in the
  core; the dialog calls the core once on Apply).
- The dialog must not run any edit until Apply is pressed.

## Architecture

Only the **input layer** changes. The pure logic and the live `_run_in_reaper`
path (and its 15 headless tests) stay as-is, except for the single Grid-mapping
touch described below.

```
main()
  └─ run_grid_align()            # unchanged entry
       └─ _run_in_reaper(config) # unchanged core; accepts a config dict
                ▲
                │ config dict (same shape the core already consumes)
        _imgui_dialog()          # NEW — replaces _read_user_dialog()
```

- `_read_user_dialog()` (the `GetUserInputs` CSV parser) is **removed**.
- `_imgui_dialog()` is **added**: it builds and runs the ReaImGui window and
  returns a `config` dict, or `None` on Cancel/close. `_run_in_reaper` keeps its
  existing `from_dialog` branch logic but obtains `cfg` from `_imgui_dialog()`.
- Clean boundary: the core never imports or references ImGui; the dialog never
  references RPR edit functions beyond reading defaults.

### ReaImGui usage (Python)

Use the bundled API shim `…/Scripts/ReaTeam Extensions/API/imgui.py`
(ReaImGui v0.10.x, cfillion). Lifecycle:

1. Create context once (`ImGui_CreateContext('Grid Align Transients V2')`).
2. A `reaper.defer` loop renders one window per frame:
   `ImGui_Begin` → widgets → `ImGui_End`.
3. State (current dropdown indices, threshold, triplets bool) lives in module-level
   vars seeded from `ExtState`.
4. **Apply** → assemble `config`, stop the loop, run the core once, save `ExtState`.
   **Cancel** or window close (`ImGui_Begin` returns open=false, or Esc) → stop the
   loop, return `None`.

If the shim import fails (extension missing), show a `ShowMessageBox` telling the
user to install ReaImGui via ReaPack, and return `None` (no crash).

## Window layout & fields

```
┌─ Grid Align Transients V2 ─────────┐
│ Threshold   [ 15 ] ms              │
│ Source      [ Auto (detect)     ▾ ]│
│ Mode        [ Snap to grid      ▾ ]│
│ Grid        [ 1/16              ▾ ]│
│ Triplets    [x] include triplet grid│
│                                    │
│        [  Apply  ]   [ Cancel ]    │
└────────────────────────────────────┘
```

| Field | Widget | Options / range | config key |
|---|---|---|---|
| Threshold | `InputInt`/drag | integer ms, default 15 | `grid_threshold_ms` (float) |
| Transient source | `Combo` | `Auto (detect)` / `Existing splits` | `transient_source` = `auto`/`splits` |
| Correction mode | `Combo` | `Snap to grid` / `Adaptive (groove)` | `mode` = `snap`/`adaptive` |
| Grid | `Combo` | `Project grid` / `1/8` / `1/16` / `1/32` | `grid_choice` (new) |
| Triplets | `Checkbox` | on/off | `include_triplets` (bool) |

## Config schema change: Grid

V1 used a boolean `allow_sixteenth` that hard-forced `fine_qn = min(grid, 0.25)`.
V2 replaces it with `grid_choice`, mapped to the fine grid step in quarter notes:

| `grid_choice` | `fine_qn` |
|---|---|
| `project` | project grid QN (`_project_grid_qn()`) |
| `1/8` | 0.5 |
| `1/16` | 0.25 |
| `1/32` | 0.125 |

Core touch points (logic, local and test-covered):
- `_run_in_reaper`: derive `fine_qn` from `grid_choice` (table above) instead of the
  `allow_sixteenth` branch; triplets still divide by 3 when enabled.
- `build_grid_candidates_qn(cfg)`: take an explicit `fine_qn` (the straight family
  step) instead of the hard-coded `0.25`/`allow_sixteenth` flag.
- Update headless tests that reference `allow_sixteenth` to the new `grid_choice` /
  `fine_qn` form; add a test asserting each `grid_choice` yields the expected
  `fine_qn` and candidate spacing. Keep all other tests green.

## Settings persistence

Section `GridAlignTransients`; keys `threshold_ms`, `source`, `mode`, `grid`,
`triplets`. Saved on Apply, read on dialog open; missing/invalid → V1 defaults
(`15 / auto / snap / 1/16 / off`).

## Testing

- Headless suite stays green (the pure functions are unchanged except the
  `fine_qn` parameterization), plus the new `grid_choice → fine_qn` test.
- The ImGui dialog itself is GUI code (not unit-tested); verify live by running the
  action: dropdowns open, Apply runs the core once with one undo, Cancel does
  nothing, ExtState round-trips. Entry point asserted free of `SystemExit`.

## Follow-up deliverable

Once the pattern is proven live, extract it into a reusable skill: **building a
ReaImGui settings dialog (with Combo dropdowns + ExtState defaults) for a
ReaScript** — the user's stated end goal.
