-- Envelope-based Limiter (Item) V2.0
-- Brick-wall peak limiter via item/take volume automation envelope
-- Writes gain reduction to the item's own volume envelope, keeping track envelope clean
-- No splits, no FX — pure envelope automation
--
-- V2.0 improvements over V1.0:
--   - Accessor reads from position 0 (D_STARTOFFS baked in — works on split items)
--   - SR fallback chain: source → parent → project → 44100
--   - CH fallback chain: source → parent → 1
--
-- Author: Dima Gorelik
-- Co-developed with Claude (Anthropic)
-- License: MIT

local retval, user_input = reaper.GetUserInputs(
  "Envelope-based Limiter (Item) V2.0", 4,
  "Ceiling (dB):,Attack (ms):,Release (ms):,Analysis window (ms):,extrawidth=80",
  "-0.5,0,70,5"
)
if not retval then return end

local ceiling_db, attack_ms, release_ms, window_ms = user_input:match("([^,]+),([^,]+),([^,]+),([^,]+)")
local THRESHOLD_DB = tonumber(ceiling_db)
local ATTACK_SEC = tonumber(attack_ms) / 1000
local RELEASE_SEC = tonumber(release_ms) / 1000
local WINDOW_SEC = tonumber(window_ms) / 1000

if not THRESHOLD_DB or not ATTACK_SEC or not RELEASE_SEC or not WINDOW_SEC then
  reaper.ShowMessageBox("Invalid input. Please enter numeric values.", "Error", 0)
  return
end

local THRESHOLD_LIN = 10 ^ (THRESHOLD_DB / 20)

reaper.Undo_BeginBlock()
reaper.PreventUIRefresh(1)

local item = reaper.GetSelectedMediaItem(0, 0)
if not item then
  reaper.PreventUIRefresh(-1)
  reaper.ShowMessageBox("Please select a media item.", "Error", 0)
  reaper.Undo_EndBlock("Envelope limiter (item) V2 - failed", -1)
  return
end

local take = reaper.GetActiveTake(item)
if not take or reaper.TakeIsMIDI(take) then
  reaper.PreventUIRefresh(-1)
  reaper.ShowMessageBox("Selected item must be audio.", "Error", 0)
  reaper.Undo_EndBlock("Envelope limiter (item) V2 - failed", -1)
  return
end

local item_pos = reaper.GetMediaItemInfo_Value(item, "D_POSITION")
local item_len = reaper.GetMediaItemInfo_Value(item, "D_LENGTH")
local item_end = item_pos + item_len

local source = reaper.GetMediaItemTake_Source(take)
local sr = reaper.GetMediaSourceSampleRate(source)
local num_ch = reaper.GetMediaSourceNumChannels(source)
local take_rate = reaper.GetMediaItemTakeInfo_Value(take, "D_PLAYRATE")

-- SR fallback chain
if sr == 0 then
  local parent = reaper.GetMediaSourceParent(source)
  if parent then sr = reaper.GetMediaSourceSampleRate(parent) end
end
if sr == 0 then sr = reaper.GetSetProjectInfo(0, "PROJECT_SRATE", 0, false) end
if sr == 0 then sr = 44100 end

-- CH fallback chain
if num_ch == 0 then
  local parent = reaper.GetMediaSourceParent(source)
  if parent then num_ch = reaper.GetMediaSourceNumChannels(parent) end
  if num_ch == 0 then num_ch = 1 end
end

-- Analyze audio peaks per window (position 0, offset baked in)
local accessor = reaper.CreateTakeAudioAccessor(take)
local samples_per_win = math.max(math.floor(sr * WINDOW_SEC), 1)
local buf_size = samples_per_win * num_ch

local reductions = {}
local t = 0
local t_end_src = item_len * take_rate

while t < t_end_src do
  local buf = reaper.new_array(buf_size)
  buf.clear()
  reaper.GetAudioAccessorSamples(accessor, sr, num_ch, t, samples_per_win, buf)

  local peak = 0
  for i = 1, buf_size do
    local s = math.abs(buf[i])
    if s > peak then peak = s end
  end

  if peak > THRESHOLD_LIN then
    local proj_time = item_pos + t / take_rate
    local gain = THRESHOLD_LIN / peak
    table.insert(reductions, {time = proj_time, gain = gain})
  end

  t = t + WINDOW_SEC
end

reaper.DestroyAudioAccessor(accessor)

if #reductions == 0 then
  reaper.PreventUIRefresh(-1)
  reaper.ShowMessageBox(
    string.format("No peaks exceeding %.1f dB found.", THRESHOLD_DB),
    "Envelope-based Limiter (Item) V2.0", 0)
  reaper.Undo_EndBlock("Envelope limiter (item) V2 - no changes", -1)
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

-- Apply attack/release expansion and clamp to item bounds
for _, reg in ipairs(regions) do
  reg.s = math.max(reg.s - ATTACK_SEC, item_pos)
  reg.e = math.min(reg.e + RELEASE_SEC, item_end)
end

-- Get or activate take volume envelope
local env = reaper.GetTakeEnvelopeByName(take, "Volume")
if not env then
  reaper.SelectAllMediaItems(0, false)
  reaper.SetMediaItemSelected(item, true)
  reaper.Main_OnCommand(reaper.NamedCommandLookup("_S&M_TAKEENVSHOW1"), 0)
  env = reaper.GetTakeEnvelopeByName(take, "Volume")
end
if not env then
  reaper.Main_OnCommand(40693, 0)
  env = reaper.GetTakeEnvelopeByName(take, "Volume")
end

if not env then
  reaper.PreventUIRefresh(-1)
  reaper.ShowMessageBox(
    "Could not access take volume envelope.\n"
    .. "Try manually enabling it: right-click item > Take > Show take volume envelope, then run again.",
    "Error", 0)
  reaper.Undo_EndBlock("Envelope limiter (item) V2 - failed", -1)
  return
end

-- Take envelope points use time relative to item start
local function to_item_time(proj_time)
  return proj_time - item_pos
end

-- Clear existing envelope points in item range
reaper.DeleteEnvelopePointRange(env, to_item_time(item_pos) - 0.001, to_item_time(item_end) + 0.001)

-- Write automation
reaper.InsertEnvelopePoint(env, to_item_time(item_pos), 1.0, 0, 0, false, true)

for _, reg in ipairs(regions) do
  -- Unity before attack
  reaper.InsertEnvelopePoint(env, to_item_time(reg.s), 1.0, 0, 0, false, true)

  -- Per-window gain reduction points
  for _, p in ipairs(reg.points) do
    reaper.InsertEnvelopePoint(env, to_item_time(p.time), p.gain, 0, 0, false, true)
  end

  -- Release back to unity
  reaper.InsertEnvelopePoint(env, to_item_time(reg.e), 1.0, 0, 0, false, true)
end

reaper.InsertEnvelopePoint(env, to_item_time(item_end), 1.0, 0, 0, false, true)
reaper.Envelope_SortPoints(env)

reaper.PreventUIRefresh(-1)
reaper.UpdateArrange()

reaper.ShowMessageBox(string.format(
  "Done!\n\n"
  .. "Channels: %d | SR: %d\n"
  .. "Ceiling: %.1f dB\n"
  .. "Attack: %d ms | Release: %d ms | Window: %d ms\n\n"
  .. "%d region(s), %d automation points.\n\n"
  .. "Automation written to item/take volume envelope.",
  num_ch, sr, THRESHOLD_DB,
  ATTACK_SEC*1000, RELEASE_SEC*1000, WINDOW_SEC*1000,
  #regions, #reductions),
  "Envelope-based Limiter (Item) V2.0", 0)
reaper.Undo_EndBlock("Envelope limiter (item) V2.0 (" .. THRESHOLD_DB .. " dB)", -1)
