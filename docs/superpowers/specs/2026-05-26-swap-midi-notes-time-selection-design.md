# Swap MIDI Events In Time Selection — Design

**Date:** 2026-05-26
**Status:** Approved for planning
**Language:** Lua (ReaScript)

## Goal

Swap the MIDI content of two selected MIDI items within the current time
selection, **without splitting** either item. Events that fall in the window
move whole from one item to the other and vice versa.

## User Decisions

- **Membership criterion:** by event *start*. A note belongs to the window if
  its start position is inside `[tsStart, tsEnd)`. CC / pitch bend / sustain /
  program change / text / sysex are points — membership is by their position.
- **Scope:** all MIDI events in the window (notes **and** CC, pitch bend,
  sustain CC64, program change, text/sysex), not notes only.
- **Language:** Lua. Python/EEL do not simplify this task — the ReaScript MIDI
  API is cleanest in Lua (multiple return values vs Python out-parameter
  tuples). EEL2 is unsuitable (weak string/struct handling).
- **Placement:** primary file in
  `/Users/macbook/Library/Application Support/REAPER/Scripts`; versioned copy in
  the repo root alongside the other `.lua` scripts.

## Filename

`Swap MIDI Notes In Time Selection V1.0.lua`

## Core Idea — One Coordinate System via Project Time

MIDI positions are stored in PPQ relative to a take; the time selection is in
project seconds. The whole script hinges on translating between them:

- **Membership / snapshot:** convert each event's PPQ → project time with
  `MIDI_GetProjTimeFromPPQPos(take, ppq)`, then test against the time selection.
- **Insertion into the other take:** convert project time → that take's PPQ with
  `MIDI_GetPPQPosFromProjTime(take, projtime)`.

Consequence: an event keeps the **same absolute project moment** after the swap;
it simply lives in the other item. When the two items are aligned (same
position/length) this is identical to "relative to item start". Tempo is handled
automatically by the conversion functions.

## Algorithm (no splits)

1. **Validate.** Exactly 2 MIDI items selected and a non-empty time selection.
   Otherwise show a message (`ShowMessageBox` / `MB`) and abort. Resolve each
   item's active take; both must be MIDI takes.
2. **Read time selection.** `GetSet_LoopTimeRange(false, false, ...)` →
   `tsStart`, `tsEnd` (project time).
3. **Snapshot both takes first** (before deleting anything), capturing every
   in-window event from take A and take B:
   - **Notes** (`MIDI_GetNote`): startppq, endppq, chan, pitch, vel, muted,
     selected. Store start **and** end as project time so duration survives the
     move to a take with a different PPQ origin.
   - **CC** (`MIDI_CountEvts` + `MIDI_GetCC`): ppqpos→projtime, chanmsg, chan,
     msg2, msg3, muted, selected, plus curve shape via `MIDI_GetCCShape`.
   - **Text/Sysex** (`MIDI_GetTextSysexEvt`): ppqpos→projtime, type, raw bytes,
     selected, muted.
4. **Delete in-window events from both takes**, iterating indices in
   **descending** order per event class so deletions do not shift the indices of
   not-yet-processed events.
5. **Re-insert cross-wise.** Insert take A's snapshot into take B and take B's
   snapshot into take A. For each event convert its stored project time(s) to
   the destination take's PPQ:
   - `MIDI_InsertNote` (with `noSortIn = true`),
   - `MIDI_InsertCC` (+ `MIDI_SetCCShape` to restore the curve),
   - `MIDI_InsertTextSysexEvt`.
6. **Sort** both takes once with `MIDI_Sort(take)`.

## Edge Cases

- **Note straddling the right boundary** (start inside, end outside): moved
  whole (per the "by start" decision). No split.
- **Tail extends past destination item's right edge** (items differ in length):
  left as-is. REAPER tolerates notes past item end; only the portion inside the
  item sounds. No clamping, no split.
- **Window empty in one item:** the swap is effectively one-directional — still
  correct.
- **Identical/zero overlap:** if neither take has any in-window event, abort
  early *before* opening the undo block — no edit, no undo point, no message
  needed (or a brief "nothing to swap" notice).

## Wrapping & UX

- Single undo block: `Undo_BeginBlock()` / `Undo_EndBlock(desc, -1)`.
- `PreventUIRefresh(1)` around the edits, `UpdateArrange()` / `UpdateItemInProject`
  afterward so the editor/arrange view reflects the change.
- No dialogs, no hardcoded params: operates on the current selection and time
  selection only.

## Test Plan

1. **Aligned items, different notes in window** → notes swap; events outside the
   window untouched in both items.
2. **Items on different tracks / positions** → swapped events sound at the same
   absolute project time as before.
3. **Note on boundary** (start inside, end outside) → moves whole, no split.
4. **Item with CC + sustain + pitch bend** → those events and CC curve shapes
   move across correctly.
5. **No time selection / not exactly 2 MIDI items** → clean message, no edits.

## Out of Scope (YAGNI)

- Splitting notes at the time-selection boundary.
- A configuration dialog (criterion / scope toggles).
- Handling more than two items.
- Preserving per-event selection beyond what the insert calls already allow.
