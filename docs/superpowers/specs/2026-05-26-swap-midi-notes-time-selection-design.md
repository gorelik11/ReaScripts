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

`Swap MIDI Events In Time Selection V1.0.lua`

## Core Idea — One Coordinate System via Project Time

MIDI positions are stored in PPQ relative to a take; the time selection is in
project seconds. The whole script hinges on translating between them:

- **Membership / snapshot:** convert each event's PPQ → project time with
  `MIDI_GetProjTimeFromPPQPos(take, ppq)`, then test against the effective window
  (see below).
- **Insertion into the other take:** convert project time → that take's PPQ with
  `MIDI_GetPPQPosFromProjTime(take, projtime)`.

Consequence: an event keeps the **same absolute project moment** after the swap;
it simply lives in the other item. When the two items are aligned (same
position/length) this is identical to "relative to item start". Tempo is handled
automatically by the conversion functions (including a tempo-map change inside
the window).

### Effective Window (bounds safety)

`MIDI_GetPPQPosFromProjTime` extrapolates linearly: a project time outside the
destination item still yields a PPQ value, which would be negative or far past
the item. To make the swap well-defined we never operate outside where **both**
items exist. Define:

```
winStart = max(tsStart, itemA_start, itemB_start)
winEnd   = min(tsEnd,   itemA_end,   itemB_end)
```

Membership and snapshotting use `[winStart, winEnd)` — the intersection of the
time selection with both item bodies. Because the window is inside both items, a
moved event's **start** always maps to an in-bounds PPQ in the destination take;
no negative/extrapolated positions. To be precise: the event *start* is clamped
to both item bodies, but a note *end* may still extend past the destination
item's right edge (membership is by start) — that tail is tolerated, not
clamped. If `winStart >= winEnd` (items do not both overlap the time selection)
the script aborts early with a notice.

## Algorithm (no splits)

1. **Validate (strict).**
   - Selected **media item** count must be **exactly 2** (`CountSelectedMediaItems`).
     Any other count (including a stray selected audio item) → message + abort.
     No "smart" ignoring of audio items — predictability over convenience.
   - Both items' active takes must exist and be MIDI (`TakeIsMIDI`).
   - A non-empty time selection must exist.
   - **Same-source guard:** if both takes resolve to the same `PCM_source`
     (the items are the same pool / one is a pooled twin of the other),
     swapping is degenerate and destructive — abort with a clear message.
2. **Read time selection.** `GetSet_LoopTimeRange(false, false, ...)` →
   `tsStart`, `tsEnd` (project time). Compute the **effective window**
   `[winStart, winEnd)` (see *Effective Window* above); abort if empty.
3. **Snapshot both takes first** (before deleting anything), capturing every
   event whose start falls in `[winStart, winEnd)` from take A and take B:
   - **Notes** (`MIDI_GetNote`): startppq, endppq, chan, pitch, vel, muted,
     selected. Store start **and** end as project time so duration survives the
     move to a take with a different PPQ origin.
   - **CC / channel-pressure / pitch bend / program change**
     (`MIDI_CountEvts` + `MIDI_GetCC`): ppqpos→projtime, chanmsg, chan, msg2,
     msg3, muted, selected. Curve shape via `MIDI_GetCCShape` is stored **only
     if it returns true** — for non-shapeable messages (pitch bend, program
     change, etc.) it may return false; store a "no shape" marker and skip
     `MIDI_SetCCShape` for those on re-insert.
   - **Text/Sysex** (`MIDI_GetTextSysexEvt`): ppqpos→projtime, type, raw bytes,
     selected, muted.

   Each snapshot entry also keeps its **original event index**. Snapshot arrays
   are built in ascending original-index order so insertion order is stable —
   this makes the `ccBase + k` CC indexing deterministic even when multiple
   events share the same ppq / project time.
4. **Delete in-window events from both takes**, iterating indices in
   **descending** order per event class so deletions do not shift the indices of
   not-yet-processed events.
5. **Re-insert cross-wise.** Insert take A's snapshot into take B and take B's
   snapshot into take A. For each event convert its stored project time(s) to
   the destination take's PPQ. **Insert all events with `noSortIn = true`** so
   indices stay stable until the final sort:
   - `MIDI_InsertNote`,
   - `MIDI_InsertCC`, then restore the curve with `MIDI_SetCCShape` **only for
     entries that captured a shape** (skip pitch bend / program change / other
     non-shapeable messages). Because `MIDI_InsertCC` returns no index, capture
     the CC count **after the deletions** (`ccBase`, via `MIDI_CountEvts`) and
     insert CCs in **ascending original-index order**; with `noSort` each new CC
     is appended at the tail, so the k-th inserted CC has index `ccBase + k`.
     Call `MIDI_SetCCShape(take, ccBase+k, shape, beztension)` **before**
     `MIDI_Sort` (sorting renumbers indices).
   - `MIDI_InsertTextSysexEvt` (raw bytes preserved verbatim, including
     binary-ish payloads).
6. **Sort** both takes once with `MIDI_Sort(take)` after all inserts and CC
   shape restores are done.

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
- **Items do not both overlap the time selection:** `winStart >= winEnd` →
  abort with a notice (handled by the effective-window check, not a crash).

## Pooled / Shared MIDI Sources

Pooled MIDI items share one `PCM_source`; a destructive edit to one changes
every pooled copy. For V1.0:

- **Same-source guard (enforced):** if the two selected items resolve to the
  same source, abort (see validation). Swapping an item against its own pool
  twin is meaningless and would corrupt both views.
- **Other pooled copies elsewhere (documented limitation):** if one of the two
  items has *additional* pooled copies elsewhere in the project, those copies
  change too — this is REAPER's normal pooling behavior. V1.0 does **not**
  detect or unpool; it edits in place. This caveat is noted in the script
  header. Auto-unpool/clone-before-edit is explicitly out of scope for V1.0.

## Wrapping & UX

- Single undo block: `Undo_BeginBlock()` / `Undo_EndBlock(desc, -1)`.
- **Protected execution.** The edit body (snapshot → delete → insert → sort)
  runs inside `pcall`/`xpcall`. A `cleanup()` that always runs restores
  `PreventUIRefresh(-1)` and closes the undo block, regardless of success or a
  Lua runtime error — so a mid-edit error can never leave the UI frozen or an
  undo block dangling. On caught error: surface the message, end the undo block
  (REAPER coalesces the partial change as one undoable step the user can revert).
- `PreventUIRefresh(1)` around the edits; `MIDI_Sort` per take, then
  `UpdateArrange()` / `UpdateItemInProject` afterward so arrange + open MIDI
  editor reflect the change.
- No dialogs, no hardcoded params: operates on the current selection and time
  selection only.

## Test Plan

1. **Aligned items, different notes in window** → notes swap; events outside the
   window untouched in both items.
2. **Items on different tracks / positions** → swapped events sound at the same
   absolute project time as before.
3. **Destination item starts before / after source item** (different positions
   and lengths) → effective window clamps correctly; no negative/out-of-bounds
   PPQ; only the overlap region swaps.
4. **Tempo-map change inside the selection** → durations and positions survive
   (project-time mapping handles it); no drift.
5. **Note on boundary** (start inside, end outside) → moves whole, no split;
   tail past destination right edge tolerated.
6. **CC shape test** — bezier + linear + square shapes in the window → shapes
   restored on the destination (guards the `ccBase + k` indexing off-by-one).
7. **Text/Sysex with binary-ish payload** → bytes preserved verbatim.
8. **Pooled MIDI item** — (a) two items sharing one source → aborts via
   same-source guard; (b) an item with a pooled copy elsewhere → in-place edit,
   copy changes too (documented behavior).
9. **Selected audio item present** (3 items, one audio) → strict validation
   aborts with a message; no edits.
10. **No time selection / not exactly 2 MIDI items / no overlap** → clean
    message, no edits, no dangling undo block.
11. **Forced runtime error mid-edit** (manual injection during dev) → `cleanup`
    restores `PreventUIRefresh` and closes the undo block.

## Out of Scope (YAGNI)

- Splitting notes at the time-selection boundary.
- A configuration dialog (criterion / scope toggles).
- Handling more than two items.
- Preserving per-event selection beyond what the insert calls already allow.
