---
name: reascripts-gui
description: Use when adding or designing a GUI for a REAPER ReaScript — replacing a GetUserInputs text dialog with real dropdowns/buttons, building a settings window, or theming one. Covers ReaImGui dialogs (Python proven, Lua via translation) and custom gfx GUIs (Lua). NOT for JSFX UIs (use reaper-jsfx-ui).
---

# ReaScript GUIs

Give a ReaScript a real window with dropdowns/buttons instead of `GetUserInputs`.
Two proven host-language paths + one bridge:

| Need | Use |
|---|---|
| **Dropdowns / a settings dialog** (Python) | **ReaImGui** — `Combo` widgets. Proven core below. |
| Dropdowns in **Lua** | ReaImGui — same API, translate the glue (verify live first time). |
| **Fully custom look** (meters, waveform, bespoke sliders), Lua | hand-drawn `gfx.*`. Reference: `RCBit Sample Limiter V1.7.lua`. No native dropdown. |
| **JSFX** plugin UI | **REQUIRED:** use the `reaper-jsfx-ui` skill instead. |

Canonical Python examples to copy from (full working code, FakeReaper-tested, live-confirmed):
`Grid Align Transients V2.0.py` and `MIDI Adaptive Quantize V2.0.py` (+ their `_reaper_fakes.py`).

## ReaImGui dropdown dialog (Python) — the recipe

A persistent window runs on REAPER's `defer` loop; the script returns immediately.

1. **Routing** — `run_x(config=None)`: `headless` → stub; explicit config (e.g. `grid_threshold_ms is not None`) → `_run_in_reaper(cfg)`; else → `_open_dialog()`.
2. **`_open_dialog()`** — load the shim, seed UI from ExtState, kick the loop:
   ```python
   import os, sys
   api = os.path.join(RPR_GetResourcePath(), "Scripts", "ReaTeam Extensions", "API")
   if api not in sys.path: sys.path.insert(0, api)
   import imgui as ImGui          # the ONLY way to reach ReaImGui from Python
   ctx = ImGui.CreateContext("My Tool")
   # store {imgui, ctx, ui} in a MODULE-LEVEL global, then:
   RPR_defer("_my_frame()")       # defer takes a STRING naming a module-level fn
   ```
   Wrap the import in `try/except` → on failure show a "install ReaImGui via ReaPack" `RPR_ShowMessageBox` and `return None` (never crash).
3. **`_my_frame()`** (module-level, because `RPR_defer` evals the string in module globals):
   ```python
   vis, open_ = ImGui.Begin(ctx, "My Tool", True)
   if vis:
       _, ui["amt"]  = ImGui.InputInt(ctx, "Amount", ui["amt"])
       ui["mode"]    = _combo(ImGui, ctx, "Mode", ui["mode"], ["Snap", "Adaptive"])  # portable dropdown
       _, ui["trip"] = ImGui.Checkbox(ctx, "Triplets", ui["trip"])
       apply_  = ImGui.Button(ctx, "Apply"); ImGui.SameLine(ctx)
       cancel_ = ImGui.Button(ctx, "Cancel")
   ImGui.End(ctx)                 # ALWAYS call End, even when not visible
   if apply_:  _save_ext(ui); _run_in_reaper(build_cfg(ui), show_report=True); return  # stop deferring
   if cancel_ or open_ == 0: return
   RPR_defer("_my_frame()")
   ```
   `_combo` returns the chosen index; `InputInt`/`Checkbox` return `(changed, value)`. Map the dropdown INDEX to the config string (`_MODES[idx]`). Build the dropdown portably (NOT the version-gated `ImGui_Combo` helper — see gotchas):
   ```python
   def _combo(ImGui, ctx, label, idx, labels):
       if ImGui.BeginCombo(ctx, label, labels[idx]):
           for i, lab in enumerate(labels):
               clicked, _ = ImGui.Selectable(ctx, lab, i == idx)
               if clicked: idx = i
           ImGui.EndCombo(ctx)
       return idx
   ```
   For an option that only applies in some modes, wrap its `_combo` in `ImGui.BeginDisabled(ctx)`/`ImGui.EndDisabled(ctx)` to grey it out.
4. **ExtState** — `RPR_GetExtState`/`RPR_SetExtState(sect,key,val,True)` to remember last choices; validate against the canonical lists, fall back to defaults.
5. **Green/custom theme** — before `Begin`, `ImGui.PushStyleColor(ctx, ImGui.Col_Button(), 0xRRGGBBAA)` for each slot (Button/Header/FrameBg/CheckMark/TitleBgActive + hover/active); after `End`, `ImGui.PopStyleColor(ctx, <same count>)`. Pack `0xRRGGBBAA`.

## Non-obvious glue gotchas (where agents get it wrong)

- **`ImGui_Combo` is version-gated — use `BeginCombo`/`Selectable`/`EndCombo` instead.** The one-call `Combo`/null-separated-items helper throws `ImGui_Combo: requires REAPER v6.44 or newer (use BeginCombo or BeginListBox for wider compatibility)` on some machines (seen LIVE on Big Sur / REAPER v7.73, while it rendered fine on Sequoia) — a portability trap, since the dialog runs across the user's machines. Build dropdowns with the `_combo` helper above. (Live-confirmed fix in Drift Sync Correct V2.)
- **Every REAPER API call is `RPR_`-prefixed in Python** (`RPR_MIDI_GetNote`, `RPR_MIDIEditor_GetActive`, `RPR_Undo_BeginBlock2`). Bare `MIDI_GetNote(...)` → `NameError`. (ReaImGui shim funcs are the exception — they're `ImGui.X` after `import imgui`.)
- **Wrapper return shapes echo output params.** `RPR_MIDI_CountEvts(take,0,0,0)` → `(retval, take, notecnt, ccs, sysex)` (note count is `[2]`). `RPR_MIDI_GetNote(...)` → 10-tuple. Read the shape; don't assume scalars.
- **`RPR_defer` takes a STRING** evaluated in module globals — the frame fn must be module-level, not a closure/lambda.
- **CRASH LAW:** never `raise SystemExit`/`sys.exit()`/`exit()` (REAPER's embedded interpreter routes to `Py_Exit` → kills REAPER). The defer loop ends by not re-deferring. See the `reascripts` skill.
- **Undo:** one block around edits; for MIDI-API edits use the explicit `Undo_BeginBlock2(0)`+`MarkProjectDirty(0)`+`Undo_OnStateChange2(0,label)`+`Undo_EndBlock2(0,label,-1)` form or undo won't record.

## Testing — FakeReaper FIRST (mandatory)

Per the `reascripts` skill: (1) pure logic → plain unit tests; (2) the `_*_frame` mapping → a **FakeReaper** test with a fake `imgui` (echo widgets, scripted Apply/Cancel, no-op `PushStyleColor`/`PopStyleColor`, `__getattr__`→no-op/0 for `Col_*`/`BeginCombo`/`Selectable`/`BeginDisabled`) + spies on `_run_in_reaper`/`RPR_defer` — preset the `ui` indices, then assert dropdown index→config mapping and Apply-calls-core-once BEFORE live (`BeginCombo`→0 skips the combo body, so the test drives the frame via the preset indices); (3) live smoke last. Copy `_reaper_fakes.py`'s `FakeImGui`.

## Lua paths (briefly)

- **Lua + ReaImGui:** same widget API; differences are only host glue — load via `reaper.ImGui_*` (or `dofile(reaper.GetResourcePath()..'/Scripts/ReaTeam Extensions/API/imgui.lua')('0.9')`), `reaper.defer(function() ... end)` (Lua takes a real function, not a string). Verify the exact incantation live the first time.
- **Lua + gfx (custom look):** `gfx.init(name,w,h)` + a `reaper.defer(mainloop)` that draws each frame with `gfx.rect/circle/line/measurestr`, hit-testing `gfx.mouse_x/_y/_cap` yourself. No native dropdown — hand-roll a popup or use cycle-buttons. Full worked example: `RCBit Sample Limiter V1.7.lua` (`draw_button`/`draw_slider`/`draw_preview`/`mainloop`). No Lua FakeReaper harness yet → test by live smoke with `/tmp` reports.
