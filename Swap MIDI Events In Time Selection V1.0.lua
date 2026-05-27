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

function in_window(projTime, winStart, winEnd)
  return projTime >= winStart and projTime < winEnd
end

function compute_effective_window(tsStart, tsEnd, aStart, aEnd, bStart, bEnd)
  local winStart = math.max(tsStart, aStart, bStart)
  local winEnd   = math.min(tsEnd, aEnd, bEnd)
  return winStart, winEnd
end

function extract_pool_id(chunk)
  -- Pooled MIDI sources carry a "POOLEDEVTS {GUID}" line; pooled copies share it.
  if not chunk then return nil end
  return chunk:match("POOLEDEVTS%s+({[%x%-]+})")
end

-- ===== REAPER-bound (added in Task 6) =====

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

  local ok, perr = pcall(function()
    reaper.MIDI_DisableSort(ctx.takeA)
    reaper.MIDI_DisableSort(ctx.takeB)
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

-- ===== entry point =====
if reaper ~= nil and reaper.CountSelectedMediaItems ~= nil then
  main()
end
