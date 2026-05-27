-- In-REAPER acceptance test for "Swap MIDI Events In Time Selection V1.0.lua".
-- Builds two aligned MIDI items (0..4s) on two new tracks:
--   item A: note pitch 60 @1s, CC#1 value 100 @1s
--   item B: note pitch 67 @1s
-- Time selection 0.5..3.5 (covers the 1s events). Selects both, runs the swap.
-- Expects after swap: A has pitch 67 (no CC), B has pitch 60 + CC#1.
-- Writes PASS/FAIL lines to ~/swap_midi_test_results.txt.

-- During verification (before deploy) the script lives in the repo:
local SCRIPT = "/Users/macbook/projects/reascripts/Swap MIDI Events In Time Selection V1.0.lua"
-- After Task 7 deploy you may instead point at the installed copy:
-- local SCRIPT = reaper.GetResourcePath() .. "/Scripts/Swap MIDI Events In Time Selection V1.0.lua"

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
