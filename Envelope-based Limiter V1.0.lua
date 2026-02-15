-- Envelope-based Limiter V1.0
-- Brick-wall peak limiter via volume automation envelope
-- Analyzes selected audio item for peaks exceeding a user-defined ceiling
-- and creates precise volume automation to tame them with configurable attack/release
--
-- Author: Dima Gorelik
-- Co-developed with Claude (Anthropic)
-- License: MIT

-- Default values
local default_ceiling = "-9.0"
local default_attack = "10"
local default_release = "50"
local default_window = "5"

-- User input dialog
local retval, user_input = reaper.GetUserInputs(
  "Envelope-based Limiter V1.0", 4,
  "Ceiling (dB):,Attack (ms):,Release (ms):,Analysis window (ms):,extrawidth=80",
  default_ceiling .. "," .. default_attack .. "," .. default_release .. "," .. default_window
)

if not retval then return end

local ceiling_db, attack_ms, release_ms, window_ms = user_input:match("([^,]+),([^,]+),([^,]+),([^,]+)")
local THRESHOLD_DB = tonumber(ceiling_db)
local ATTACK_SEC = tonumber(attack_ms) / 1000
local RELEASE_SEC = tonumber(release_ms) / 1000
local WINDOW_SEC = tonumber(window_ms) / 1000

if not THRESHOLD_DB or not ATTACK_SEC or not RELEASE_SEC or not WINDOW_SEC then
  reaper.ShowMessageBox("Invalid input. Please enter numeric values.", "Envelope-based Limiter", 0)
  return
end

local THRESHOLD_LIN = 10 ^ (THRESHOLD_DB / 20)

reaper.Undo_BeginBlock()
reaper.PreventUIRefresh(1)

local item = reaper.GetSelectedMediaItem(0, 0)
if not item then
  reaper.ShowMessageBox("Please select a media item.", "Envelope-based Limiter", 0)
  return
end

local take = reaper.GetActiveTake(item)
if not take or reaper.TakeIsMIDI(take) then
  reaper.ShowMessageBox("Selected item must be audio.", "Envelope-based Limiter", 0)
  return
end

local item_pos = reaper.GetMediaItemInfo_Value(item, "D_POSITION")
local item_len = reaper.GetMediaItemInfo_Value(item, "D_LENGTH")
local item_end = item_pos + item_len
local track = reaper.GetMediaItem_Track(item)

local source = reaper.GetMediaItemTake_Source(take)
local sr = reaper.GetMediaSourceSampleRate(source)
local num_ch = reaper.GetMediaSourceNumChannels(source)
local take_offset = reaper.GetMediaItemTakeInfo_Value(take, "D_STARTOFFS")
local take_rate = reaper.GetMediaItemTakeInfo_Value(take, "D_PLAYRATE")

-- Analyze audio peaks
local accessor = reaper.CreateTakeAudioAccessor(take)
local samples_per_win = math.max(math.floor(sr * WINDOW_SEC), 1)
local buf_size = samples_per_win * num_ch

local reductions = {}
local t = take_offset
local t_end = take_offset + item_len * take_rate

while t < t_end do
  local buf = reaper.new_array(buf_size)
  buf.clear()
  reaper.GetAudioAccessorSamples(accessor, sr, num_ch, t, samples_per_win, buf)

  local peak = 0
  for i = 1, buf_size do
    local s = math.abs(buf[i])
    if s > peak then peak = s end
  end

  if peak > THRESHOLD_LIN then
    local proj_time = item_pos + (t - take_offset) / take_rate
    local gain = THRESHOLD_LIN / peak
    table.insert(reductions, {time = proj_time, gain = gain})
  end

  t = t + WINDOW_SEC
end

reaper.DestroyAudioAccessor(accessor)

if #reductions == 0 then
  reaper.PreventUIRefresh(-1)
  reaper.ShowMessageBox("No peaks exceeding " .. THRESHOLD_DB .. " dB found.", "Envelope-based Limiter", 0)
  reaper.Undo_EndBlock("Envelope limiter - no changes", -1)
  return
end

-- Merge consecutive reductions into regions (using release time as merge gap)
local regions = {}
local cur = {s = reductions[1].time, e = reductions[1].time + WINDOW_SEC, points = {reductions[1]}}

for i = 2, #reductions do
  local r = reductions[i]
  if r.time <= cur.e + RELEASE_SEC then
    cur.e = r.time + WINDOW_SEC
    table.insert(cur.points, r)
  else
    table.insert(regions, cur)
    cur = {s = r.time, e = r.time + WINDOW_SEC, points = {r}}
  end
end
table.insert(regions, cur)

-- Get or show volume envelope
local env = reaper.GetTrackEnvelopeByName(track, "Volume")
if not env then
  reaper.SetOnlyTrackSelected(track)
  reaper.Main_OnCommand(40406, 0)
  env = reaper.GetTrackEnvelopeByName(track, "Volume")
end

if not env then
  reaper.PreventUIRefresh(-1)
  reaper.ShowMessageBox("Could not access volume envelope.", "Envelope-based Limiter", 0)
  reaper.Undo_EndBlock("Envelope limiter - failed", -1)
  return
end

-- Clear existing points in item range
reaper.DeleteEnvelopePointRange(env, item_pos - 0.001, item_end + 0.001)

-- Write automation with user-defined attack/release
reaper.InsertEnvelopePoint(env, item_pos, 1.0, 0, 0, false, true)

for _, reg in ipairs(regions) do
  local atk_start = math.max(reg.s - ATTACK_SEC, item_pos)
  local rel_end = math.min(reg.e + RELEASE_SEC, item_end)

  -- Unity before attack
  reaper.InsertEnvelopePoint(env, atk_start, 1.0, 0, 0, false, true)

  -- Per-window gain reduction points
  for _, p in ipairs(reg.points) do
    reaper.InsertEnvelopePoint(env, p.time, p.gain, 0, 0, false, true)
  end

  -- Release back to unity
  reaper.InsertEnvelopePoint(env, rel_end, 1.0, 0, 0, false, true)
end

reaper.InsertEnvelopePoint(env, item_end, 1.0, 0, 0, false, true)
reaper.Envelope_SortPoints(env)

reaper.PreventUIRefresh(-1)
reaper.UpdateArrange()

local msg = string.format(
  "Done!\n\nCeiling: %g dB\nAttack: %g ms\nRelease: %g ms\nWindow: %g ms\n\n%d region(s), %d automation points.",
  THRESHOLD_DB, ATTACK_SEC*1000, RELEASE_SEC*1000, WINDOW_SEC*1000, #regions, #reductions)
reaper.ShowMessageBox(msg, "Envelope-based Limiter V1.0", 0)
reaper.Undo_EndBlock("Envelope limiter V1.0 (" .. THRESHOLD_DB .. " dB)", -1)
