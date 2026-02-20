-- RCBit LUFS Limiter V5.0 — ENVELOPE-BASED
-- No splits. Uses FX parameter envelope automation on RCBit instances.
--
-- Features:
--   - LUFS gain via RCBit Macro+BR (static or envelope)
--   - Peak limiting: Combined (Macro+BR envelope) or Micro (2nd instance, Micro envelope)
--   - FX placement: TakeFX (on item) or TrackFX (on track insert, post-plugins)
--   - LUFS source: SWS item, MonoRun, StereoRun (dry render)
--   - LUFS=0: limit-only mode
--
-- Author: Dima Gorelik
-- Co-developed with Claude (Anthropic)
-- License: MIT
--
-- Requires: JS:RCBitRangeGain JSFX plugin by RCJacH
-- Requires: SWS extension (for NF_AnalyzeTakeLoudness)

local BIT_DB = 6.0206
local MIN_GAIN_DB = 0.15
local BR_STEP = 0.05
local MIN_REGION_SEC = 0.02

-- ============ HELPERS ============
local function macro_to_norm(m) return (m + 16) / 32 end
local function br_to_norm(br) return br / 3.0 end
local function micro_to_norm(mi) return (mi + 100) / 200 end

local function calc_rcbit_params(gain_db, floor_br)
  if math.abs(gain_db) < MIN_GAIN_DB then return nil, nil end
  local total_bits = gain_db / BIT_DB
  local macro = math.floor(math.abs(total_bits) + 0.5)
  if macro == 0 then macro = 1 end
  if gain_db < 0 then macro = -macro end
  local bit_ratio = math.abs(gain_db) / (math.abs(macro) * BIT_DB)
  bit_ratio = math.min(math.max(bit_ratio, 0.0), 3.0)
  if floor_br then
    bit_ratio = math.floor(bit_ratio / BR_STEP) * BR_STEP
  else
    bit_ratio = math.floor(bit_ratio / BR_STEP + 0.5) * BR_STEP
  end
  local effective_gain = math.abs(macro) * bit_ratio * BIT_DB
  if effective_gain < MIN_GAIN_DB then return nil, nil end
  return macro, bit_ratio
end

local function get_sr(source)
  local sr = reaper.GetMediaSourceSampleRate(source)
  if sr == 0 then
    local parent = reaper.GetMediaSourceParent(source)
    if parent then sr = reaper.GetMediaSourceSampleRate(parent) end
  end
  if sr == 0 then sr = reaper.GetSetProjectInfo(0, "PROJECT_SRATE", 0, false) end
  if sr == 0 then sr = 44100 end
  return sr
end

local function measure_lufs_sws(take)
  local ok, integrated = reaper.NF_AnalyzeTakeLoudness(take, true)
  if not ok or not integrated or integrated <= -200 then return nil end
  local source = reaper.GetMediaItemTake_Source(take)
  local nch = reaper.GetMediaSourceNumChannels(source)
  if nch == 1 then
    local pan_law = reaper.GetSetProjectInfo(0, "PROJECT_PANLAW", 0, false)
    if pan_law == 0 then pan_law = 3 end
    return integrated - pan_law
  end
  return integrated
end

local function measure_lufs_render(track, start_time, end_time, mono)
  local ts_s, ts_e = reaper.GetSet_LoopTimeRange(false, false, 0, 0, false)
  local tc_before = reaper.CountTracks(0)
  local solos = {}
  for i = 0, tc_before - 1 do
    local tr = reaper.GetTrack(0, i)
    solos[i] = reaper.GetMediaTrackInfo_Value(tr, "I_SOLO")
    reaper.SetMediaTrackInfo_Value(tr, "I_SOLO", 0)
  end
  reaper.SetMediaTrackInfo_Value(track, "I_SOLO", 2)
  reaper.GetSet_LoopTimeRange(true, false, start_time, end_time, false)
  reaper.SetOnlyTrackSelected(track)
  reaper.Main_OnCommand(mono and 41716 or 41720, 0)
  local new_count = reaper.CountTracks(0)
  local lufs = nil
  if new_count > tc_before then
    local stem_track = reaper.GetTrack(0, new_count - 1)
    local stem_item = reaper.GetTrackMediaItem(stem_track, 0)
    if stem_item then
      local stem_take = reaper.GetActiveTake(stem_item)
      if stem_take then
        local ok2, integrated = reaper.NF_AnalyzeTakeLoudness(stem_take, true)
        if ok2 and integrated and integrated > -200 then lufs = integrated end
      end
    end
    reaper.DeleteTrack(stem_track)
  end
  for i = 0, math.min(reaper.CountTracks(0) - 1, tc_before - 1) do
    local tr = reaper.GetTrack(0, i)
    if tr then reaper.SetMediaTrackInfo_Value(tr, "I_SOLO", solos[i] or 0) end
  end
  reaper.SetMediaTrackInfo_Value(track, "B_MUTE", 0)
  reaper.GetSet_LoopTimeRange(true, false, ts_s, ts_e, false)
  return lufs
end

-- ============ REGION BUILDING ============
local function build_and_process_regions(windows, window_dur, item_pos, item_end,
                                          lufs_gain_db, attack_sec, release_sec)
  if #windows == 0 then return {} end
  local regions = {}
  local cur = {
    s = windows[1].time, e = windows[1].time + window_dur,
    is_peak = windows[1].is_peak, min_gain = windows[1].gain_db
  }
  for i = 2, #windows do
    local w = windows[i]
    if w.is_peak == cur.is_peak then
      cur.e = w.time + window_dur
      if w.gain_db < cur.min_gain then cur.min_gain = w.gain_db end
    else
      table.insert(regions, cur)
      cur = { s = w.time, e = w.time + window_dur, is_peak = w.is_peak, min_gain = w.gain_db }
    end
  end
  table.insert(regions, cur)

  for i, reg in ipairs(regions) do
    if reg.is_peak then
      local ns = math.max(reg.s - attack_sec, item_pos)
      local ne = math.min(reg.e + release_sec, item_end)
      if i > 1 and not regions[i-1].is_peak and regions[i-1].e > ns then regions[i-1].e = ns end
      if i < #regions and not regions[i+1].is_peak and regions[i+1].s < ne then regions[i+1].s = ne end
      reg.s = ns; reg.e = ne
    end
  end

  local valid = {}
  for _, r in ipairs(regions) do if r.e - r.s > 0.001 then table.insert(valid, r) end end
  regions = valid

  local merged = {regions[1]}
  for i = 2, #regions do
    local p, c = merged[#merged], regions[i]
    if p.is_peak and c.is_peak and c.s <= p.e + 0.001 then
      p.e = math.max(p.e, c.e)
      if c.min_gain < p.min_gain then p.min_gain = c.min_gain end
    else
      table.insert(merged, c)
    end
  end
  regions = merged

  local changed = true
  while changed do
    changed = false
    local new = {}
    for i, reg in ipairs(regions) do
      local dur = reg.e - reg.s
      if dur < MIN_REGION_SEC and #new > 0 then
        new[#new].e = reg.e; changed = true
      elseif dur < MIN_REGION_SEC and #new == 0 and i < #regions then
        regions[i+1].s = reg.s; changed = true
      else
        table.insert(new, reg)
      end
    end
    regions = new
  end

  for _, reg in ipairs(regions) do
    reg.gain_db = reg.is_peak and reg.min_gain or lufs_gain_db
  end
  return regions
end

-- ============ ENVELOPE POINT WRITING ============
local function write_env_points(env, regions, value_func, shape, item_pos, item_end)
  if not env then return 0 end
  local n_existing = reaper.CountEnvelopePoints(env)
  for i = n_existing - 1, 0, -1 do
    reaper.DeleteEnvelopePointEx(env, -1, i)
  end
  local count = 0
  if #regions > 0 and item_pos then
    reaper.InsertEnvelopePoint(env, item_pos, value_func(regions[1]), shape, 0, false, true)
    count = count + 1
  end
  for _, reg in ipairs(regions) do
    reaper.InsertEnvelopePoint(env, reg.s, value_func(reg), shape, 0, false, true)
    count = count + 1
  end
  if #regions > 0 and item_end then
    reaper.InsertEnvelopePoint(env, item_end, value_func(regions[#regions]), shape, 0, false, true)
    count = count + 1
  end
  reaper.Envelope_SortPoints(env)
  return count
end

-- ============ DIALOG ============
local retval, user_input = reaper.GetUserInputs(
  "RCBit LUFS Limiter V5.0", 8,
  "Target LUFS (0=limit only):,"
  .. "Peak Ceiling (dB):,"
  .. "Attack (ms):,"
  .. "Release (ms):,"
  .. "Analysis Window (ms):,"
  .. "FX Scope (TakeFX/TrackFX):,"
  .. "Limiter (Combined/Micro):,"
  .. "LUFS Source (SWS/MonoRun/StereoRun):,"
  .. "extrawidth=120",
  "-9,-0.5,0,70,5,TakeFX,Combined,SWS"
)
if not retval then return end

local vals = {}
for v in user_input:gmatch("([^,]+)") do table.insert(vals, v) end

local TARGET_LUFS = tonumber(vals[1])
local CEILING_DB = tonumber(vals[2])
local ATTACK_SEC = tonumber(vals[3]) / 1000
local RELEASE_SEC = tonumber(vals[4]) / 1000
local WINDOW_SEC = tonumber(vals[5]) / 1000
local FX_SCOPE = vals[6] or "TakeFX"
local LIMITER_MODE = vals[7] or "Combined"
local LUFS_SOURCE = vals[8] or "SWS"

if not TARGET_LUFS or not CEILING_DB or not ATTACK_SEC or not RELEASE_SEC or not WINDOW_SEC then
  reaper.ShowMessageBox("Invalid input. Please enter numeric values.", "Error", 0)
  return
end

-- Normalize string params
FX_SCOPE = (FX_SCOPE == "TrackFX") and "TrackFX" or "TakeFX"
LIMITER_MODE = (LIMITER_MODE == "Micro") and "Micro" or "Combined"
if LUFS_SOURCE ~= "MonoRun" and LUFS_SOURCE ~= "StereoRun" then LUFS_SOURCE = "SWS" end

-- ============ MAIN ============
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
local sr = get_sr(source)

local item_pos = reaper.GetMediaItemInfo_Value(item, "D_POSITION")
local item_len = reaper.GetMediaItemInfo_Value(item, "D_LENGTH")
local item_end = item_pos + item_len
local track = reaper.GetMediaItem_Track(item)
local take_offset = reaper.GetMediaItemTakeInfo_Value(take, "D_STARTOFFS")
local take_rate = reaper.GetMediaItemTakeInfo_Value(take, "D_PLAYRATE")

-- ============ LUFS MEASUREMENT ============
local lufs_gain_db = 0
local current_lufs = 0

if TARGET_LUFS ~= 0 then
  if LUFS_SOURCE == "SWS" then
    current_lufs = measure_lufs_sws(take)
  elseif LUFS_SOURCE == "MonoRun" or LUFS_SOURCE == "StereoRun" then
    current_lufs = measure_lufs_render(track, item_pos, item_end, LUFS_SOURCE == "MonoRun")
  end
  if not current_lufs then
    reaper.PreventUIRefresh(-1)
    reaper.ShowMessageBox(
      "LUFS analysis failed. Item may be silent or offline.\nEnsure SWS extension is installed.",
      "Error", 0)
    reaper.Undo_EndBlock("V5 failed", -1)
    return
  end
  lufs_gain_db = TARGET_LUFS - current_lufs
end

-- ============ PEAK ANALYSIS ============
local accessor = reaper.CreateTakeAudioAccessor(take)
local samples_per_win = math.max(math.floor(sr * WINDOW_SEC), 1)
local buf_size = samples_per_win * num_ch
local window_dur = WINDOW_SEC / take_rate

local windows = {}
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
  local proj_time = item_pos + (t - take_offset) / take_rate
  local peak_db = -math.huge
  if peak > 0 then peak_db = 20 * math.log(peak, 10) end
  local peak_after_gain = peak_db + lufs_gain_db
  local is_peak = (peak_after_gain > CEILING_DB)
  table.insert(windows, {
    time = proj_time,
    is_peak = is_peak,
    gain_db = is_peak and (CEILING_DB - peak_db) or lufs_gain_db
  })
  t = t + WINDOW_SEC
end
reaper.DestroyAudioAccessor(accessor)

local peak_win_count = 0
for _, w in ipairs(windows) do if w.is_peak then peak_win_count = peak_win_count + 1 end end

-- ============ EDGE CASES ============
if peak_win_count == 0 and TARGET_LUFS == 0 then
  reaper.PreventUIRefresh(-1)
  reaper.ShowMessageBox(
    string.format("No peaks exceed %.1f dB. LUFS=0. Nothing to do.", CEILING_DB),
    "RCBit LUFS Limiter V5.0", 0)
  reaper.Undo_EndBlock("V5 - no changes", -1)
  return
end

if peak_win_count == 0 and TARGET_LUFS ~= 0 then
  local lufs_m, lufs_br = calc_rcbit_params(lufs_gain_db, false)
  if not lufs_m then
    reaper.PreventUIRefresh(-1)
    reaper.ShowMessageBox(
      string.format("Already near target LUFS (current=%.1f, gain=%.2fdB).", current_lufs, lufs_gain_db),
      "RCBit LUFS Limiter V5.0", 0)
    reaper.Undo_EndBlock("V5 - no changes", -1)
    return
  end
  if FX_SCOPE == "TakeFX" then
    local fx = reaper.TakeFX_AddByName(take, "JS:RCBitRangeGain", -1)
    if fx >= 0 then
      reaper.TakeFX_SetParam(take, fx, 0, lufs_m)
      reaper.TakeFX_SetParam(take, fx, 1, 0)
      reaper.TakeFX_SetParam(take, fx, 2, lufs_br)
    end
  else
    local fx = reaper.TrackFX_AddByName(track, "JS:RCBitRangeGain", false, -1)
    if fx >= 0 then
      reaper.TrackFX_SetParam(track, fx, 0, lufs_m)
      reaper.TrackFX_SetParam(track, fx, 1, 0)
      reaper.TrackFX_SetParam(track, fx, 2, lufs_br)
    end
  end
  local eff = lufs_m * lufs_br * BIT_DB
  reaper.PreventUIRefresh(-1)
  reaper.UpdateArrange()
  reaper.ShowMessageBox(string.format(
    "Done!\n\nNo peaks exceed %.1f dB after LUFS gain.\n"
    .. "Applied static LUFS RCBit (%s): M=%d BR=%.2f eff=%+.2fdB\n"
    .. "LUFS: %.1f → %d (gain: %+.2fdB)",
    CEILING_DB, FX_SCOPE, lufs_m, lufs_br, eff,
    current_lufs, TARGET_LUFS, lufs_gain_db),
    "RCBit LUFS Limiter V5.0", 0)
  reaper.Undo_EndBlock("RCBit LUFS Limiter V5.0", -1)
  return
end

-- ============ BUILD REGIONS ============
local regions = build_and_process_regions(windows, window_dur, item_pos, item_end,
                                           lufs_gain_db, ATTACK_SEC, RELEASE_SEC)

-- ============ APPLY FX WITH ENVELOPES ============
local fx_count = 0
local env_points = 0

local function get_env_func(scope, take2, track2, fx_idx)
  if scope == "TakeFX" then
    if not reaper.TakeFX_GetEnvelope then
      return nil, "TakeFX_GetEnvelope not available (need REAPER v6.37+)"
    end
    return function(param) return reaper.TakeFX_GetEnvelope(take2, fx_idx, param, true) end
  else
    return function(param) return reaper.GetFXEnvelope(track2, fx_idx, param, true) end
  end
end

local function add_fx(scope, take2, track2, name)
  if scope == "TakeFX" then
    return reaper.TakeFX_AddByName(take2, name, -1)
  else
    return reaper.TrackFX_AddByName(track2, name, false, -1)
  end
end

local function set_param(scope, take2, track2, fx, param, value)
  if scope == "TakeFX" then
    reaper.TakeFX_SetParam(take2, fx, param, value)
  else
    reaper.TrackFX_SetParam(track2, fx, param, value)
  end
end

if LIMITER_MODE == "Combined" then
  local fx_idx = add_fx(FX_SCOPE, take, track, "JS:RCBitRangeGain")
  if fx_idx < 0 then
    reaper.PreventUIRefresh(-1)
    reaper.ShowMessageBox("Could not add RCBitRangeGain FX.", "Error", 0)
    reaper.Undo_EndBlock("V5 failed", -1)
    return
  end
  fx_count = 1
  set_param(FX_SCOPE, take, track, fx_idx, 0, 0)
  set_param(FX_SCOPE, take, track, fx_idx, 1, 0)
  set_param(FX_SCOPE, take, track, fx_idx, 2, 0)

  local get_env, err = get_env_func(FX_SCOPE, take, track, fx_idx)
  if not get_env then
    reaper.PreventUIRefresh(-1)
    reaper.ShowMessageBox(err or "Cannot create envelope.", "Error", 0)
    reaper.Undo_EndBlock("V5 failed", -1)
    return
  end

  local env_macro = get_env(0)
  local macro_pts = write_env_points(env_macro, regions, function(reg)
    local m, br = calc_rcbit_params(reg.gain_db, reg.is_peak)
    return macro_to_norm(m or 0)
  end, 1, item_pos, item_end)

  local env_br = get_env(2)
  local br_pts = write_env_points(env_br, regions, function(reg)
    local m, br = calc_rcbit_params(reg.gain_db, reg.is_peak)
    return br_to_norm(br or 0)
  end, 1, item_pos, item_end)

  env_points = (macro_pts or 0) + (br_pts or 0)

elseif LIMITER_MODE == "Micro" then
  local max_correction = 0
  for _, reg in ipairs(regions) do
    if reg.is_peak then
      local corr = math.abs(reg.gain_db - lufs_gain_db)
      if corr > max_correction then max_correction = corr end
    end
  end
  local limiter_br = math.max(1, math.min(3, math.ceil(max_correction / BIT_DB)))

  if TARGET_LUFS ~= 0 and math.abs(lufs_gain_db) >= MIN_GAIN_DB then
    local lufs_m, lufs_br = calc_rcbit_params(lufs_gain_db, false)
    if lufs_m then
      local fx1 = add_fx(FX_SCOPE, take, track, "JS:RCBitRangeGain")
      if fx1 >= 0 then
        set_param(FX_SCOPE, take, track, fx1, 0, lufs_m)
        set_param(FX_SCOPE, take, track, fx1, 1, 0)
        set_param(FX_SCOPE, take, track, fx1, 2, lufs_br)
        fx_count = fx_count + 1
      end
    end
  end

  local fx2 = add_fx(FX_SCOPE, take, track, "JS:RCBitRangeGain")
  if fx2 < 0 then
    reaper.PreventUIRefresh(-1)
    reaper.ShowMessageBox("Could not add limiter RCBitRangeGain FX.", "Error", 0)
    reaper.Undo_EndBlock("V5 failed", -1)
    return
  end
  fx_count = fx_count + 1
  set_param(FX_SCOPE, take, track, fx2, 0, 0)
  set_param(FX_SCOPE, take, track, fx2, 1, 0)
  set_param(FX_SCOPE, take, track, fx2, 2, limiter_br)

  local get_env, err = get_env_func(FX_SCOPE, take, track, fx2)
  if not get_env then
    reaper.PreventUIRefresh(-1)
    reaper.ShowMessageBox(err or "Cannot create envelope.", "Error", 0)
    reaper.Undo_EndBlock("V5 failed", -1)
    return
  end

  local env_micro = get_env(1)
  local micro_pts = write_env_points(env_micro, regions, function(reg)
    if reg.is_peak then
      local correction = reg.gain_db - lufs_gain_db
      local micro_val = correction / (limiter_br * BIT_DB) * 100
      micro_val = math.max(-100, math.min(100, micro_val))
      micro_val = math.floor(micro_val)
      return micro_to_norm(micro_val)
    else
      return micro_to_norm(0)
    end
  end, 1, item_pos, item_end)

  env_points = micro_pts or 0
end

reaper.PreventUIRefresh(-1)
reaper.UpdateArrange()

-- ============ RESULT DIALOG ============
local peak_regions = 0
for _, r in ipairs(regions) do if r.is_peak then peak_regions = peak_regions + 1 end end

local msg = "Done!\n\n"
msg = msg .. string.format("Mode: %s | FX: %s | LUFS: %s\n\n", LIMITER_MODE, FX_SCOPE, LUFS_SOURCE)

if TARGET_LUFS ~= 0 then
  local lufs_m, lufs_br = calc_rcbit_params(lufs_gain_db, false)
  local eff = lufs_m and (lufs_m * lufs_br * BIT_DB) or 0
  msg = msg .. string.format(
    "Current LUFS: %.1f\nTarget LUFS: %d\n"
    .. "LUFS Gain: %+.2f dB (actual: %+.2f dB)\n",
    current_lufs, TARGET_LUFS, lufs_gain_db, eff)
else
  msg = msg .. "LUFS: disabled (pure limiting)\n"
end

msg = msg .. string.format("Peak Ceiling: %.1f dB\n\n", CEILING_DB)
msg = msg .. string.format(
  "%d peak window(s) detected\n"
  .. "%d region(s) (%d peak, %d boost)\n"
  .. "%d FX instance(s)\n"
  .. "%d envelope point(s)\n"
  .. "NO SPLITS — envelope automation only",
  peak_win_count,
  #regions, peak_regions, #regions - peak_regions,
  fx_count, env_points)

reaper.ShowMessageBox(msg, "RCBit LUFS Limiter V5.0", 0)
reaper.Undo_EndBlock("RCBit LUFS Limiter V5.0", -1)
