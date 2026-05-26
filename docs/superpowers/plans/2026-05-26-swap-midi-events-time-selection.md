# Swap MIDI Events In Time Selection — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A single-file ReaScript (Lua) that swaps all MIDI events between the two selected MIDI items within the current time selection, without splitting either item.

**Architecture:** One self-contained `.lua` file. Pure helpers (window math, membership, pool-id parsing) carry no REAPER dependency and are unit-tested with the `lua` CLI. REAPER-bound orchestration (validate → snapshot → delete → cross-insert → sort) is verified by an in-REAPER integration harness. Sorting is suspended with `MIDI_DisableSort` during edits so CC-shape index bookkeeping is deterministic, then restored with `MIDI_Sort`. The whole edit runs under one undo block with `pcall` cleanup.

**Tech Stack:** Lua 5.x (REAPER's ReaScript), `lua` CLI for unit tests, reapy for running the integration harness.

**Spec:** `docs/superpowers/specs/2026-05-26-swap-midi-notes-time-selection-design.md`

---

## Verified API signatures (from official docs + live installed scripts)

```
MIDI_CountEvts(take)                         -> retval, notecnt, ccevtcnt, textsyxevtcnt
MIDI_GetNote(take, noteidx)                  -> retval, sel, muted, startppq, endppq, chan, pitch, vel
MIDI_GetCC(take, ccidx)                      -> retval, sel, muted, ppqpos, chanmsg, chan, msg2, msg3
MIDI_GetCCShape(take, ccidx)                 -> retval, shape, beztension
MIDI_GetTextSysexEvt(take, idx)              -> retval, sel, muted, ppqpos, type, msg
MIDI_GetProjTimeFromPPQPos(take, ppqpos)     -> projtime
MIDI_GetPPQPosFromProjTime(take, projtime)   -> ppqpos
MIDI_InsertNote(take, sel, muted, startppq, endppq, chan, pitch, vel, noSortIn)  -- noSortIn supported
MIDI_InsertCC(take, sel, muted, ppqpos, chanmsg, chan, msg2, msg3)               -- NO noSort param
MIDI_InsertTextSysexEvt(take, sel, muted, ppqpos, type, bytestr)                 -- NO noSort param
MIDI_SetCCShape(take, ccidx, shape, beztension)
MIDI_DeleteNote(take, noteidx) / MIDI_DeleteCC(take, ccidx) / MIDI_DeleteTextSysexEvt(take, idx)
MIDI_DisableSort(take)   -- single arg; suspends sorting
MIDI_Sort(take)          -- sorts and clears DisableSort state
```

## File Structure

- Create: `Swap MIDI Events In Time Selection V1.0.lua` (repo root — versioned authoring copy).
- Create: `tests/test_swap_midi_core.lua` (pure-helper unit tests; `lua` CLI).
- Create: `tests/swap_midi_integration_harness.lua` (in-REAPER acceptance test).
- Deploy (copy, Task 7): `/Users/macbook/Library/Application Support/REAPER/Scripts/Swap MIDI Events In Time Selection V1.0.lua`.

Function layout inside the script:
- Pure: `compute_effective_window`, `in_window`, `extract_pool_id`.
- REAPER-bound: `get_two_midi_takes`, `snapshot_take`, `delete_snapshot`, `insert_snapshot`, `main`.
- Bottom guard runs `main()` only when the `reaper` global exists (so `dofile` from a `lua`-CLI test loads the functions without executing).

---

## Task 1: Setup, lua CLI, and script skeleton

**Files:**
- Create: `Swap MIDI Events In Time Selection V1.0.lua`
- Create: `tests/test_swap_midi_core.lua` (empty placeholder this task)

- [ ] **Step 1: Install the lua CLI (for pure-helper unit tests)**

Run: `brew install lua && lua -v`
Expected: prints e.g. `Lua 5.4.x`

- [ ] **Step 2: Create the script with header + run guard only**

Create `Swap MIDI Events In Time Selection V1.0.lua`:

```lua
-- Swap MIDI Events In Time Selection V1.0.lua
-- Swaps ALL MIDI events (notes, CC, pitch bend, sustain, program change,
-- text/sysex) between the two selected MIDI items, within the current time
-- selection, WITHOUT splitting either item. An event belongs to the swap if
-- its START falls inside the effective window (time selection intersected with
-- both item bodies); it moves whole to the same absolute project time in the
-- other item.
--
-- Caveat: pooled MIDI copies elsewhere in the project are edited in place
-- (REAPER's normal pooling behavior). Two items sharing one source are rejected.

-- ===== pure helpers (no REAPER deps; unit-tested via lua CLI) =====
-- (added in Tasks 2-4)

-- ===== REAPER-bound (added in Task 6) =====

-- ===== entry point =====
if reaper ~= nil and reaper.CountSelectedMediaItems ~= nil then
  main()
end
```

- [ ] **Step 3: Verify the skeleton loads under lua without running main**

Run: `lua -e 'dofile("Swap MIDI Events In Time Selection V1.0.lua"); print("loaded ok")'`
Expected: prints `loaded ok` (the guard sees no `reaper`, so `main` is never called; `main` being undefined is fine because the guard short-circuits on `reaper == nil`).

- [ ] **Step 4: Commit**

```bash
git add "Swap MIDI Events In Time Selection V1.0.lua"
git commit -m "feat: skeleton for Swap MIDI Events In Time Selection"
```

---

## Task 2: Pure helper `in_window`

**Files:**
- Modify: `Swap MIDI Events In Time Selection V1.0.lua`
- Test: `tests/test_swap_midi_core.lua`

- [ ] **Step 1: Write the failing test**

Create `tests/test_swap_midi_core.lua`:

```lua
-- Unit tests for pure helpers. Run from repo root: lua tests/test_swap_midi_core.lua
-- reaper is nil here, so the script's bottom guard skips main().
dofile("Swap MIDI Events In Time Selection V1.0.lua")

local failures = 0
local function check(name, cond)
  if cond then print("ok   - " .. name)
  else print("FAIL - " .. name); failures = failures + 1 end
end

-- in_window: half-open [winStart, winEnd)
check("start is inside",      in_window(2.0, 2.0, 4.0) == true)
check("end is exclusive",     in_window(4.0, 2.0, 4.0) == false)
check("just before outside",  in_window(1.999, 2.0, 4.0) == false)
check("middle inside",        in_window(3.0, 2.0, 4.0) == true)

if failures == 0 then print("\nALL PASS"); os.exit(0)
else print("\n" .. failures .. " FAILURE(S)"); os.exit(1) end
```

- [ ] **Step 2: Run test to verify it fails**

Run: `lua tests/test_swap_midi_core.lua`
Expected: FAIL — error `attempt to call a nil value (global 'in_window')`.

- [ ] **Step 3: Implement `in_window`**

In the script, under the `pure helpers` comment, add:

```lua
function in_window(projTime, winStart, winEnd)
  return projTime >= winStart and projTime < winEnd
end
```

- [ ] **Step 4: Run test to verify it passes**

Run: `lua tests/test_swap_midi_core.lua`
Expected: 4 `ok` lines, then `ALL PASS`.

- [ ] **Step 5: Commit**

```bash
git add "Swap MIDI Events In Time Selection V1.0.lua" tests/test_swap_midi_core.lua
git commit -m "feat: in_window membership helper (half-open interval)"
```

---

## Task 3: Pure helper `compute_effective_window`

**Files:**
- Modify: `Swap MIDI Events In Time Selection V1.0.lua`
- Test: `tests/test_swap_midi_core.lua`

- [ ] **Step 1: Add the failing test**

In `tests/test_swap_midi_core.lua`, add before the final pass/fail block:

```lua
-- compute_effective_window: intersection of time selection and both item bodies
do
  local ws, we = compute_effective_window(1.0, 5.0, 0.0, 4.0, 2.0, 9.0)
  check("eff start = max(1,0,2) = 2", ws == 2.0)
  check("eff end   = min(5,4,9) = 4", we == 4.0)
end
do
  local ws, we = compute_effective_window(0.0, 1.0, 2.0, 3.0, 0.0, 5.0)
  check("no overlap -> we <= ws", we <= ws)
end
```

- [ ] **Step 2: Run test to verify it fails**

Run: `lua tests/test_swap_midi_core.lua`
Expected: FAIL — `attempt to call a nil value (global 'compute_effective_window')`.

- [ ] **Step 3: Implement `compute_effective_window`**

In the script, under the `pure helpers` comment, add:

```lua
function compute_effective_window(tsStart, tsEnd, aStart, aEnd, bStart, bEnd)
  local winStart = math.max(tsStart, aStart, bStart)
  local winEnd   = math.min(tsEnd, aEnd, bEnd)
  return winStart, winEnd
end
```

- [ ] **Step 4: Run test to verify it passes**

Run: `lua tests/test_swap_midi_core.lua`
Expected: all `ok`, `ALL PASS`.

- [ ] **Step 5: Commit**

```bash
git add "Swap MIDI Events In Time Selection V1.0.lua" tests/test_swap_midi_core.lua
git commit -m "feat: compute_effective_window (TS intersect both items)"
```

---

## Task 4: Pure helper `extract_pool_id`

**Files:**
- Modify: `Swap MIDI Events In Time Selection V1.0.lua`
- Test: `tests/test_swap_midi_core.lua`

- [ ] **Step 1: Add the failing test**

In `tests/test_swap_midi_core.lua`, add before the final pass/fail block:

```lua
-- extract_pool_id: pull the POOLEDEVTS GUID from an item state chunk
do
  local chunk = "<ITEM\n<SOURCE MIDI\nHASDATA 1 960 QN\n"
             .. "POOLEDEVTS {ABCD1234-1111-2222-3333-444455556666}\n>\n>"
  check("pool id extracted",
    extract_pool_id(chunk) == "{ABCD1234-1111-2222-3333-444455556666}")
  check("nil chunk -> nil", extract_pool_id(nil) == nil)
  check("no pool line -> nil",
    extract_pool_id("<ITEM\n<SOURCE MIDI\n>\n>") == nil)
end
```

- [ ] **Step 2: Run test to verify it fails**

Run: `lua tests/test_swap_midi_core.lua`
Expected: FAIL — `attempt to call a nil value (global 'extract_pool_id')`.

- [ ] **Step 3: Implement `extract_pool_id`**

In the script, under the `pure helpers` comment, add:

```lua
function extract_pool_id(chunk)
  -- Pooled MIDI sources carry a "POOLEDEVTS {GUID}" line; pooled copies share it.
  if not chunk then return nil end
  return chunk:match("POOLEDEVTS%s+({[%x%-]+})")
end
```

- [ ] **Step 4: Run test to verify it passes**

Run: `lua tests/test_swap_midi_core.lua`
Expected: all `ok`, `ALL PASS`.

- [ ] **Step 5: Commit**

```bash
git add "Swap MIDI Events In Time Selection V1.0.lua" tests/test_swap_midi_core.lua
git commit -m "feat: extract_pool_id from item state chunk"
```

---

## Task 5: Integration harness (failing acceptance test)

The REAPER-bound functions cannot be exercised by the `lua` CLI (they call `reaper.*`). This harness is the acceptance test: it builds a known scenario inside REAPER, runs the swap script, and asserts the result.

**Files:**
- Create: `tests/swap_midi_integration_harness.lua`

- [ ] **Step 1: Write the harness**

Create `tests/swap_midi_integration_harness.lua`:

```lua
-- In-REAPER acceptance test for "Swap MIDI Events In Time Selection V1.0.lua".
-- Builds two aligned MIDI items (0..4s) on two new tracks:
--   item A: note pitch 60 @1s, CC#1 value 100 @1s
--   item B: note pitch 67 @1s
-- Time selection 0.5..3.5 (covers the 1s events). Selects both, runs the swap.
-- Expects after swap: A has pitch 67 (no CC), B has pitch 60 + CC#1.
-- Writes PASS/FAIL lines to ~/swap_midi_test_results.txt.

local SCRIPT = reaper.GetResourcePath() ..
  "/Scripts/Swap MIDI Events In Time Selection V1.0.lua"
-- During dev before deploy (Task 7), point at the repo copy instead:
-- local SCRIPT = "/Users/macbook/projects/reascripts/Swap MIDI Events In Time Selection V1.0.lua"

local out = {}
local function log(s) out[#out + 1] = s end

local function add_note(take, pitch, t_start, t_end, vel)
  local sp = reaper.MIDI_GetPPQPosFromProjTime(take, t_start)
  local ep = reaper.MIDI_GetPPQPosFromProjTime(take, t_end)
  reaper.MIDI_InsertNote(take, false, false, sp, ep, 0, pitch, vel or 96, true)
end

local function add_cc(take, cc, val, t)
  local p = reaper.MIDI_GetPPQPosFromProjTime(take, t)
  reaper.MIDI_InsertCC(take, false, false, p, 0xB0, 0, cc, val)
end

local function first_note_pitch(take)
  local _, n = reaper.MIDI_CountEvts(take)
  if n < 1 then return nil end
  local _, _, _, _, _, _, pitch = reaper.MIDI_GetNote(take, 0)
  return pitch
end

local function cc_count(take)
  local _, _, cc = reaper.MIDI_CountEvts(take)
  return cc
end

reaper.Undo_BeginBlock()

-- fresh tracks at the end of the project
local base = reaper.CountTracks(0)
reaper.InsertTrackAtIndex(base, false)
reaper.InsertTrackAtIndex(base + 1, false)
local trA = reaper.GetTrack(0, base)
local trB = reaper.GetTrack(0, base + 1)

local itemA = reaper.CreateNewMIDIItemInProj(trA, 0.0, 4.0, false)
local itemB = reaper.CreateNewMIDIItemInProj(trB, 0.0, 4.0, false)
local takeA = reaper.GetActiveTake(itemA)
local takeB = reaper.GetActiveTake(itemB)

add_note(takeA, 60, 1.0, 2.0)
add_cc(takeA, 1, 100, 1.0)
add_note(takeB, 67, 1.0, 2.0)
reaper.MIDI_Sort(takeA)
reaper.MIDI_Sort(takeB)

-- select exactly the two items
reaper.SelectAllMediaItems(0, false)
reaper.SetMediaItemSelected(itemA, true)
reaper.SetMediaItemSelected(itemB, true)
reaper.GetSet_LoopTimeRange(true, false, 0.5, 3.5, false)

-- run the swap
dofile(SCRIPT)

-- assertions
local pa, pb = first_note_pitch(takeA), first_note_pitch(takeB)
log((pa == 67) and "PASS itemA note now 67" or ("FAIL itemA note = " .. tostring(pa)))
log((pb == 60) and "PASS itemB note now 60" or ("FAIL itemB note = " .. tostring(pb)))
log((cc_count(takeA) == 0) and "PASS itemA CC moved out" or ("FAIL itemA cc = " .. cc_count(takeA)))
log((cc_count(takeB) == 1) and "PASS itemB received CC" or ("FAIL itemB cc = " .. cc_count(takeB)))

reaper.Undo_EndBlock("swap midi integration harness", -1)

local f = io.open(os.getenv("HOME") .. "/swap_midi_test_results.txt", "w")
f:write(table.concat(out, "\n") .. "\n")
f:close()
```

- [ ] **Step 2: Run the harness in REAPER and verify it FAILS**

With REAPER open and the reapy server running, from repo root:

```bash
python3 - <<'PY'
import reapy
from reapy import reascript_api as RPR
path = "/Users/macbook/projects/reascripts/tests/swap_midi_integration_harness.lua"
# point harness SCRIPT at the repo copy during dev (see comment in harness)
aid = RPR.AddRemoveReaScript(True, 0, path, True)
RPR.Main_OnCommand(aid, 0)
PY
cat ~/swap_midi_test_results.txt
```

Expected: FAIL lines — the swap script has no `main`/REAPER functions yet, so notes are unchanged (`FAIL itemA note = 60`, `FAIL itemB note = 67`). (If `dofile` errors because `main` is undefined, that also counts as red.)

- [ ] **Step 3: Commit**

```bash
git add tests/swap_midi_integration_harness.lua
git commit -m "test: in-REAPER integration harness for MIDI swap"
```

---

## Task 6: Implement REAPER-bound functions

**Files:**
- Modify: `Swap MIDI Events In Time Selection V1.0.lua`

- [ ] **Step 1: Add validation, snapshot, delete, insert, and main**

In the script, under the `REAPER-bound` comment (above the entry-point guard), add:

```lua
local TITLE = "Swap MIDI Events"

local function msg(text)
  reaper.ShowMessageBox(text, TITLE, 0)
end

function get_two_midi_takes()
  if reaper.CountSelectedMediaItems(0) ~= 2 then
    return nil, "Select exactly 2 MIDI items."
  end
  local itemA = reaper.GetSelectedMediaItem(0, 0)
  local itemB = reaper.GetSelectedMediaItem(0, 1)
  local takeA = reaper.GetActiveTake(itemA)
  local takeB = reaper.GetActiveTake(itemB)
  if not takeA or not takeB
     or not reaper.TakeIsMIDI(takeA) or not reaper.TakeIsMIDI(takeB) then
    return nil, "Both selected items must have an active MIDI take."
  end
  local _, chunkA = reaper.GetItemStateChunk(itemA, "", false)
  local _, chunkB = reaper.GetItemStateChunk(itemB, "", false)
  local poolA = extract_pool_id(chunkA)
  local poolB = extract_pool_id(chunkB)
  if poolA and poolB and poolA == poolB then
    return nil, "The two items share one pooled MIDI source. Swap aborted."
  end
  return { itemA = itemA, itemB = itemB, takeA = takeA, takeB = takeB }
end

function snapshot_take(take, winStart, winEnd)
  local snap = { notes = {}, ccs = {}, sysex = {} }
  local _, noteCnt, ccCnt, sysexCnt = reaper.MIDI_CountEvts(take)
  for i = 0, noteCnt - 1 do
    local ok, sel, muted, sppq, eppq, chan, pitch, vel = reaper.MIDI_GetNote(take, i)
    if ok then
      local tstart = reaper.MIDI_GetProjTimeFromPPQPos(take, sppq)
      if in_window(tstart, winStart, winEnd) then
        local tend = reaper.MIDI_GetProjTimeFromPPQPos(take, eppq)
        snap.notes[#snap.notes + 1] = { tstart = tstart, tend = tend, chan = chan,
          pitch = pitch, vel = vel, muted = muted, sel = sel, idx = i }
      end
    end
  end
  for i = 0, ccCnt - 1 do
    local ok, sel, muted, ppq, chanmsg, chan, m2, m3 = reaper.MIDI_GetCC(take, i)
    if ok then
      local t = reaper.MIDI_GetProjTimeFromPPQPos(take, ppq)
      if in_window(t, winStart, winEnd) then
        local hasShape, shape, bez = reaper.MIDI_GetCCShape(take, i)
        snap.ccs[#snap.ccs + 1] = { t = t, chanmsg = chanmsg, chan = chan,
          m2 = m2, m3 = m3, muted = muted, sel = sel,
          hasShape = hasShape, shape = shape, bez = bez, idx = i }
      end
    end
  end
  for i = 0, sysexCnt - 1 do
    local ok, sel, muted, ppq, etype, emsg = reaper.MIDI_GetTextSysexEvt(take, i)
    if ok then
      local t = reaper.MIDI_GetProjTimeFromPPQPos(take, ppq)
      if in_window(t, winStart, winEnd) then
        snap.sysex[#snap.sysex + 1] = { t = t, etype = etype, emsg = emsg,
          muted = muted, sel = sel, idx = i }
      end
    end
  end
  return snap
end

function delete_snapshot(take, snap)
  local function del(list, fn)
    local idxs = {}
    for _, e in ipairs(list) do idxs[#idxs + 1] = e.idx end
    table.sort(idxs, function(a, b) return a > b end) -- descending: stable indices
    for _, idx in ipairs(idxs) do fn(take, idx) end
  end
  del(snap.notes, reaper.MIDI_DeleteNote)
  del(snap.ccs, reaper.MIDI_DeleteCC)
  del(snap.sysex, reaper.MIDI_DeleteTextSysexEvt)
end

function insert_snapshot(dstTake, snap)
  for _, n in ipairs(snap.notes) do
    local sppq = reaper.MIDI_GetPPQPosFromProjTime(dstTake, n.tstart)
    local eppq = reaper.MIDI_GetPPQPosFromProjTime(dstTake, n.tend)
    reaper.MIDI_InsertNote(dstTake, n.sel, n.muted, sppq, eppq, n.chan, n.pitch, n.vel, true)
  end
  -- CC count AFTER deletions, BEFORE inserting any CC (sort suspended -> appends)
  local _, _, ccBase = reaper.MIDI_CountEvts(dstTake)
  for k, c in ipairs(snap.ccs) do
    local ppq = reaper.MIDI_GetPPQPosFromProjTime(dstTake, c.t)
    reaper.MIDI_InsertCC(dstTake, c.sel, c.muted, ppq, c.chanmsg, c.chan, c.m2, c.m3)
    if c.hasShape then
      reaper.MIDI_SetCCShape(dstTake, ccBase + (k - 1), c.shape, c.bez)
    end
  end
  for _, s in ipairs(snap.sysex) do
    local ppq = reaper.MIDI_GetPPQPosFromProjTime(dstTake, s.t)
    reaper.MIDI_InsertTextSysexEvt(dstTake, s.sel, s.muted, ppq, s.etype, s.emsg)
  end
end

function main()
  local ctx, err = get_two_midi_takes()
  if not ctx then msg(err); return end

  local tsStart, tsEnd = reaper.GetSet_LoopTimeRange(false, false, 0, 0, false)
  if tsEnd <= tsStart then msg("Set a time selection first."); return end

  local aStart = reaper.GetMediaItemInfo_Value(ctx.itemA, "D_POSITION")
  local aEnd = aStart + reaper.GetMediaItemInfo_Value(ctx.itemA, "D_LENGTH")
  local bStart = reaper.GetMediaItemInfo_Value(ctx.itemB, "D_POSITION")
  local bEnd = bStart + reaper.GetMediaItemInfo_Value(ctx.itemB, "D_LENGTH")
  local winStart, winEnd =
    compute_effective_window(tsStart, tsEnd, aStart, aEnd, bStart, bEnd)
  if winEnd <= winStart then
    msg("The time selection does not overlap both items."); return
  end

  local snapA = snapshot_take(ctx.takeA, winStart, winEnd)
  local snapB = snapshot_take(ctx.takeB, winStart, winEnd)
  local total = #snapA.notes + #snapA.ccs + #snapA.sysex
              + #snapB.notes + #snapB.ccs + #snapB.sysex
  if total == 0 then return end -- nothing to swap; no undo point

  reaper.Undo_BeginBlock()
  reaper.PreventUIRefresh(1)
  reaper.MIDI_DisableSort(ctx.takeA)
  reaper.MIDI_DisableSort(ctx.takeB)

  local ok, perr = pcall(function()
    delete_snapshot(ctx.takeA, snapA)
    delete_snapshot(ctx.takeB, snapB)
    insert_snapshot(ctx.takeB, snapA)
    insert_snapshot(ctx.takeA, snapB)
  end)

  reaper.MIDI_Sort(ctx.takeA) -- also clears DisableSort state
  reaper.MIDI_Sort(ctx.takeB)
  reaper.PreventUIRefresh(-1)
  reaper.UpdateArrange()
  reaper.Undo_EndBlock("Swap MIDI events in time selection", -1)

  if not ok then
    msg("Error during swap:\n" .. tostring(perr) .. "\n\nUse Undo to revert.")
  end
end
```

- [ ] **Step 2: Re-run the pure unit tests (must stay green)**

Run: `lua tests/test_swap_midi_core.lua`
Expected: `ALL PASS` (the new code did not touch the pure helpers).

- [ ] **Step 3: Run the integration harness and verify it PASSES**

```bash
python3 - <<'PY'
import reapy
from reapy import reascript_api as RPR
path = "/Users/macbook/projects/reascripts/tests/swap_midi_integration_harness.lua"
aid = RPR.AddRemoveReaScript(True, 0, path, True)
RPR.Main_OnCommand(aid, 0)
PY
cat ~/swap_midi_test_results.txt
```

Expected, all four lines:
```
PASS itemA note now 67
PASS itemB note now 60
PASS itemA CC moved out
PASS itemB received CC
```

If any line is FAIL, debug with superpowers:systematic-debugging before continuing. Use REAPER's Undo to revert the harness scenario between runs.

- [ ] **Step 4: Commit**

```bash
git add "Swap MIDI Events In Time Selection V1.0.lua"
git commit -m "feat: implement MIDI event swap (validate, snapshot, swap, undo)"
```

---

## Task 7: Deploy to REAPER Scripts folder and manual smoke test

**Files:**
- Create (copy): `/Users/macbook/Library/Application Support/REAPER/Scripts/Swap MIDI Events In Time Selection V1.0.lua`

- [ ] **Step 1: Copy the validated script into the REAPER Scripts folder**

```bash
cp "Swap MIDI Events In Time Selection V1.0.lua" \
   "/Users/macbook/Library/Application Support/REAPER/Scripts/Swap MIDI Events In Time Selection V1.0.lua"
```

- [ ] **Step 2: Confirm the two copies are identical**

Run:
```bash
diff "Swap MIDI Events In Time Selection V1.0.lua" \
     "/Users/macbook/Library/Application Support/REAPER/Scripts/Swap MIDI Events In Time Selection V1.0.lua" && echo "identical"
```
Expected: prints `identical` (no diff output).

- [ ] **Step 3: Manual smoke test in REAPER (real edge cases)**

In REAPER, register the deployed script as an action (Actions → New action → Load ReaScript) and run it against each scenario from the spec test plan, confirming by eye / MIDI editor:
- two items at different positions → events land at the same absolute time;
- a note whose start is in-window but end is past the window/edge → moves whole, no split;
- a CC lane with bezier + linear shapes → shapes preserved on the destination;
- not-exactly-2 / no time selection / no overlap / a selected audio item → clean message, no edits;
- pooled twins (same source) → rejected with the pool message.

- [ ] **Step 4: Commit (deployed copy is outside the repo; record completion)**

```bash
git add -A
git commit -m "chore: deploy Swap MIDI Events script to REAPER Scripts folder" --allow-empty
```

---

## Self-Review (completed during planning)

**Spec coverage:**
- Membership by start → `in_window` + `snapshot_take` (Tasks 2, 6). ✓
- All event types → notes/CC/sysex in `snapshot_take`/`insert_snapshot` (Task 6). ✓
- Effective window bounds safety → `compute_effective_window` + abort (Tasks 3, 6). ✓
- Strict validation (exactly 2, both MIDI) → `get_two_midi_takes` (Task 6). ✓
- Same-source pooled guard → `extract_pool_id` + guard (Tasks 4, 6). ✓
- CC-shape conditional + `ccBase+(k-1)` under `MIDI_DisableSort` → `insert_snapshot` (Task 6). ✓
- Ascending original-index insertion → snapshot arrays built 0..n-1, iterated in order (Task 6). ✓
- `pcall` cleanup, single undo block, PreventUIRefresh balance → `main` (Task 6). ✓
- Nothing-to-swap early return (no undo) → `main` total==0 (Task 6). ✓
- Both files (repo + REAPER Scripts) → Task 7. ✓

**Placeholder scan:** none — every code step contains full code; every run step has a command and expected output.

**Type/name consistency:** `compute_effective_window`, `in_window`, `extract_pool_id`, `get_two_midi_takes`, `snapshot_take`, `delete_snapshot`, `insert_snapshot`, `main` used identically across tasks; snapshot entry fields (`tstart/tend/chan/pitch/vel/muted/sel`, `t/chanmsg/chan/m2/m3/hasShape/shape/bez`, `t/etype/emsg`) consistent between `snapshot_take` and `insert_snapshot`.
