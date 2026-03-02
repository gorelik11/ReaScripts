-- Envelope Based Limiter (Item) V2.0 Headless
-- Brick-wall peak limiter via item/take volume automation envelope
-- Writes gain reduction to the item's own volume envelope, keeping track envelope clean
-- No splits, no FX — pure envelope automation
--
-- Reads params from ~/env_item_limiter_v2_params.txt
-- Writes results to ~/env_item_limiter_v2_results.txt
--
-- Params:
--   CEILING_DB   (peak ceiling in dB, e.g. -0.5)
--   ATTACK_MS    (attack time in ms)
--   RELEASE_MS   (release time in ms)
--   WINDOW_MS    (analysis window in ms)

local params_file = os.getenv("HOME") .. "/env_item_limiter_v2_params.txt"
local results_file = os.getenv("HOME") .. "/env_item_limiter_v2_results.txt"

local function write_result(msg)
  local f = io.open(results_file, "w")
  f:write(msg)
  f:close()
end

-- Read params
local f = io.open(params_file, "r")
if not f then
  write_result("ERROR: Cannot read " .. params_file)
  return
end
local params = {}
for line in f:lines() do
  local key, val = line:match("(%S+)%s*=%s*(.+)")
  if key then params[key] = val:match("^%s*(.-)%s*$") end
end
f:close()

local THRESHOLD_DB = tonumber(params.CEILING_DB) or -0.5
local ATTACK_SEC = (tonumber(params.ATTACK_MS) or 0) / 1000
local RELEASE_SEC = (tonumber(params.RELEASE_MS) or 70) / 1000
local WINDOW_SEC = (tonumber(params.WINDOW_MS) or 5) / 1000

local THRESHOLD_LIN = 10 ^ (THRESHOLD_DB / 20)

reaper.Undo_BeginBlock()
reaper.PreventUIRefresh(1)

local item = reaper.GetSelectedMediaItem(0, 0)
if not item then
  reaper.PreventUIRefresh(-1)
  reaper.Undo_EndBlock("Env limiter item V2 - failed", -1)
  write_result("ERROR: No selected item.")
  return
end

local take = reaper.GetActiveTake(item)
if not take or reaper.TakeIsMIDI(take) then
  reaper.PreventUIRefresh(-1)
  reaper.Undo_EndBlock("Env limiter item V2 - failed", -1)
  write_result("ERROR: Selected item is not audio.")
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
  reaper.Undo_EndBlock("Env limiter item V2 - no changes", -1)
  write_result(string.format("OK: No peaks exceeding %.1f dB found. CH=%d SR=%d", THRESHOLD_DB, num_ch, sr))
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
  reaper.Undo_EndBlock("Env limiter item V2 - failed", -1)
  write_result("ERROR: Could not access take volume envelope.")
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
  reaper.InsertEnvelopePoint(env, to_item_time(reg.s), 1.0, 0, 0, false, true)
  for _, p in ipairs(reg.points) do
    reaper.InsertEnvelopePoint(env, to_item_time(p.time), p.gain, 0, 0, false, true)
  end
  reaper.InsertEnvelopePoint(env, to_item_time(reg.e), 1.0, 0, 0, false, true)
end

reaper.InsertEnvelopePoint(env, to_item_time(item_end), 1.0, 0, 0, false, true)
reaper.Envelope_SortPoints(env)

reaper.PreventUIRefresh(-1)
reaper.UpdateArrange()

write_result(string.format(
  "OK: Ceiling=%.1fdB Atk=%dms Rel=%dms Win=%dms CH=%d SR=%d Regions=%d Points=%d",
  THRESHOLD_DB, ATTACK_SEC*1000, RELEASE_SEC*1000, WINDOW_SEC*1000,
  num_ch, sr, #regions, #reductions))

reaper.Undo_EndBlock("Envelope limiter (item) V2.0 (" .. THRESHOLD_DB .. " dB)", -1)
