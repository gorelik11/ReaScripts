-- LUFS Envelope Limiter V1.0
-- Combined LUFS gain staging + peak limiting via take volume envelope
-- No splits, no FX — pure automation with per-window gain precision
--
-- Unlike the split-based RCBit Limiter, this writes continuous gain
-- to the take volume envelope. No JSFX quantization — exact gains.
--
-- Author: Dima Gorelik
-- Co-developed with Claude (Anthropic)
-- License: MIT
--
-- Requires: SWS extension (for NF_AnalyzeTakeLoudness and take envelope)

local MIN_GAIN_DB = 0.15
local PEAK_MARGIN_DB = 0.0

-- Dialog
local retval, user_input = reaper.GetUserInputs(
  "LUFS Envelope Limiter V1.0", 5,
  "Target LUFS:,Peak Ceiling (dB):,Attack (ms):,Release (ms):,Analysis Window (ms):,extrawidth=80",
  "-9,-0.5,0,70,5"
)
if not retval then return end

local vals = {}
for v in user_input:gmatch("([^,]+)") do table.insert(vals, tonumber(v)) end
local TARGET_LUFS = vals[1]
local CEILING_DB = vals[2]
local ATTACK_SEC = vals[3] / 1000
local RELEASE_SEC = vals[4] / 1000
local WINDOW_SEC = vals[5] / 1000

if not TARGET_LUFS or not CEILING_DB or not ATTACK_SEC or not RELEASE_SEC or not WINDOW_SEC then
  reaper.ShowMessageBox("Invalid input. Please enter numeric values.", "Error", 0)
  return
end

local CEILING_LIN = 10 ^ (CEILING_DB / 20)

reaper.Undo_BeginBlock()
reaper.PreventUIRefresh(1)

local item = reaper.GetSelectedMediaItem(0, 0)
if not item then
  reaper.ShowMessageBox("Please select a media item.", "Error", 0)
  return
end

local take = reaper.GetActiveTake(item)
if not take or reaper.TakeIsMIDI(take) then
  reaper.ShowMessageBox("Selected item must be audio.", "Error", 0)
  return
end

local source = reaper.GetMediaItemTake_Source(take)
local num_ch = reaper.GetMediaSourceNumChannels(source)
local sr = reaper.GetMediaSourceSampleRate(source)
local is_mono = (num_ch == 1)

-- SR fallback
if sr == 0 then
  local parent = reaper.GetMediaSourceParent(source)
  if parent then sr = reaper.GetMediaSourceSampleRate(parent) end
end
if sr == 0 then sr = reaper.GetSetProjectInfo(0, "PROJECT_SRATE", 0, false) end
if sr == 0 then sr = 44100 end

local item_pos = reaper.GetMediaItemInfo_Value(item, "D_POSITION")
local item_len = reaper.GetMediaItemInfo_Value(item, "D_LENGTH")
local item_end = item_pos + item_len
local take_offset = reaper.GetMediaItemTakeInfo_Value(take, "D_STARTOFFS")
local take_rate = reaper.GetMediaItemTakeInfo_Value(take, "D_PLAYRATE")

-- Measure LUFS
local lufs_ok, lufs_integrated = reaper.NF_AnalyzeTakeLoudness(take, true)
if not lufs_ok or lufs_integrated == nil or lufs_integrated <= -200 then
  reaper.PreventUIRefresh(-1)
  reaper.ShowMessageBox(
    "LUFS analysis failed. The item may be silent or offline.\n"
    .. "Ensure SWS extension is installed.",
    "Error", 0)
  reaper.Undo_EndBlock("LUFS Env Limiter - failed", -1)
  return
end

local current_lufs = lufs_integrated
if is_mono then
  local pan_law = reaper.GetSetProjectInfo(0, "PROJECT_PANLAW", 0, false)
  if pan_law == 0 then pan_law = 3 end
  current_lufs = lufs_integrated - pan_law
end

local lufs_gain_db = TARGET_LUFS - current_lufs
local lufs_gain_lin = 10 ^ (lufs_gain_db / 20)

if math.abs(lufs_gain_db) < MIN_GAIN_DB then
  reaper.PreventUIRefresh(-1)
  reaper.ShowMessageBox(
    string.format("Already at target LUFS (%.1f).", current_lufs),
    "LUFS Envelope Limiter V1.0", 0)
  reaper.Undo_EndBlock("LUFS Env Limiter - no changes", -1)
  return
end

-- Analyze peaks per window
local accessor = reaper.CreateTakeAudioAccessor(take)
local samples_per_win = math.max(math.floor(sr * WINDOW_SEC), 1)
local buf_size = samples_per_win * num_ch

local win_data = {}
local t = take_offset
local t_end = take_offset + item_len * take_rate
local peak_count = 0

while t < t_end do
  local buf = reaper.new_array(buf_size)
  buf.clear()
  reaper.GetAudioAccessorSamples(accessor, sr, num_ch, t, samples_per_win, buf)

  local peak = 0
  for i = 1, buf_size do
    local s = math.abs(buf[i])
    if s > peak then peak = s end
  end

  local proj_time = item_pos + (t - take_offset) / take_rate
  local gain_lin = lufs_gain_lin
  local is_peak = false

  if peak > 0 then
    local peak_after_gain = peak * lufs_gain_lin
    if peak_after_gain > CEILING_LIN then
      gain_lin = CEILING_LIN / peak
      is_peak = true
      peak_count = peak_count + 1
    end
  end

  table.insert(win_data, {
    time = proj_time,
    gain_lin = gain_lin,
    is_peak = is_peak
  })

  t = t + WINDOW_SEC
end

reaper.DestroyAudioAccessor(accessor)

-- If no peaks, just set a flat gain
if peak_count == 0 then
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
  if env then
    reaper.DeleteEnvelopePointRange(env, -0.001, item_len + 0.001)
    reaper.InsertEnvelopePoint(env, 0, lufs_gain_lin, 0, 0, false, true)
    reaper.InsertEnvelopePoint(env, item_len, lufs_gain_lin, 0, 0, false, true)
    reaper.Envelope_SortPoints(env)
  end
  reaper.PreventUIRefresh(-1)
  reaper.UpdateArrange()
  reaper.ShowMessageBox(
    string.format(
      "Done!\n\nCurrent LUFS: %.1f\nTarget LUFS: %.1f\nGain: %+.2f dB\n\n"
      .. "No peaks exceed %.1f dB after gain.\n"
      .. "Flat gain applied via take volume envelope.",
      current_lufs, TARGET_LUFS, lufs_gain_db, CEILING_DB),
    "LUFS Envelope Limiter V1.0", 0)
  reaper.Undo_EndBlock("LUFS Envelope Limiter V1.0", -1)
  return
end

-- Identify peak regions
local peak_regions = {}
local in_peak = false
local peak_start_idx = 0

for i, w in ipairs(win_data) do
  if w.is_peak and not in_peak then
    in_peak = true
    peak_start_idx = i
  elseif not w.is_peak and in_peak then
    in_peak = false
    table.insert(peak_regions, {start_idx = peak_start_idx, end_idx = i - 1})
  end
end
if in_peak then
  table.insert(peak_regions, {start_idx = peak_start_idx, end_idx = #win_data})
end

-- Apply release: ramp from peak gain back to lufs_gain over RELEASE_SEC
for _, pr in ipairs(peak_regions) do
  local peak_end_time = win_data[pr.end_idx].time + WINDOW_SEC
  local release_end_time = peak_end_time + RELEASE_SEC
  local last_peak_gain = win_data[pr.end_idx].gain_lin

  for i = pr.end_idx + 1, #win_data do
    local w = win_data[i]
    if w.time >= release_end_time then break end
    if not w.is_peak then
      local frac = (w.time - peak_end_time) / RELEASE_SEC
      frac = math.min(math.max(frac, 0), 1)
      local interp_gain = last_peak_gain + (lufs_gain_lin - last_peak_gain) * frac
      if interp_gain < w.gain_lin then
        w.gain_lin = interp_gain
      end
    end
  end
end

-- Apply attack: ramp from lufs_gain to peak gain over ATTACK_SEC
if ATTACK_SEC > 0 then
  for _, pr in ipairs(peak_regions) do
    local peak_start_time = win_data[pr.start_idx].time
    local attack_start_time = peak_start_time - ATTACK_SEC
    local first_peak_gain = win_data[pr.start_idx].gain_lin

    for i = pr.start_idx - 1, 1, -1 do
      local w = win_data[i]
      if w.time + WINDOW_SEC <= attack_start_time then break end
      if not w.is_peak then
        local frac = (peak_start_time - w.time) / ATTACK_SEC
        frac = math.min(math.max(frac, 0), 1)
        local interp_gain = first_peak_gain + (lufs_gain_lin - first_peak_gain) * frac
        if interp_gain < w.gain_lin then
          w.gain_lin = interp_gain
        end
      end
    end
  end
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
    .. "Try manually enabling it first.",
    "Error", 0)
  reaper.Undo_EndBlock("LUFS Env Limiter - failed", -1)
  return
end

-- Take envelope uses item-relative time
local function to_item_time(proj_time)
  return proj_time - item_pos
end

-- Clear existing points
reaper.DeleteEnvelopePointRange(env, to_item_time(item_pos) - 0.001, to_item_time(item_end) + 0.001)

-- Write envelope points, skipping redundant ones
local points_written = 0
local prev_gain = nil
local gain_tolerance = 0.001

local first_gain = win_data[1].gain_lin
reaper.InsertEnvelopePoint(env, to_item_time(item_pos), first_gain, 0, 0, false, true)
points_written = points_written + 1
prev_gain = first_gain

for i, w in ipairs(win_data) do
  local gain_change = math.abs(w.gain_lin - prev_gain)
  if gain_change > gain_tolerance or
     (i > 1 and w.is_peak ~= win_data[i-1].is_peak) then
    reaper.InsertEnvelopePoint(env, to_item_time(w.time), w.gain_lin, 0, 0, false, true)
    points_written = points_written + 1
    prev_gain = w.gain_lin
  end
end

reaper.InsertEnvelopePoint(env, to_item_time(item_end), lufs_gain_lin, 0, 0, false, true)
points_written = points_written + 1

reaper.Envelope_SortPoints(env)

reaper.PreventUIRefresh(-1)
reaper.UpdateArrange()

local msg = string.format(
  "Done!\n\n"
  .. "Current LUFS: %.1f\nTarget LUFS: %.1f\n"
  .. "LUFS Gain: %+.2f dB\n"
  .. "Peak Ceiling: %.1f dB\n\n"
  .. "%d peak window(s) detected\n"
  .. "%d peak region(s)\n"
  .. "%d envelope points written\n\n"
  .. "No splits, no FX — pure take volume envelope.\n"
  .. "Peaks limited to exact ceiling (no quantization).",
  current_lufs, TARGET_LUFS, lufs_gain_db,
  CEILING_DB,
  peak_count, #peak_regions, points_written)
reaper.ShowMessageBox(msg, "LUFS Envelope Limiter V1.0", 0)
reaper.Undo_EndBlock("LUFS Envelope Limiter V1.0", -1)
