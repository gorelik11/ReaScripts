-- RCBit Envelope Limiter V3.0 Headless
-- Peak limiter via FX parameter envelope automation on RCBitRangeGain.
-- No splits — writes envelopes.
-- Combined mode: single RCBit, Macro + BR envelopes.
-- Micro mode: single RCBit, Macro=0 + fixed BR + Micro envelope (finer resolution, gradual release).
-- Accessor-based peak analysis. Supports time selection.
--
-- Reads params from ~/rcbit_env_v3_params.txt
-- Writes results to ~/rcbit_env_v3_results.txt
--
-- Params:
--   CEILING_DB   (peak ceiling in dB, e.g. -0.5)
--   ATTACK_MS    (attack time in ms)
--   RELEASE_MS   (release time in ms)
--   WINDOW_MS    (analysis window in ms)
--   FX_SCOPE     (TakeFX or TrackFX, default TakeFX)
--   LIMITER_MODE (Combined or Micro, default Combined)

local BIT_DB = 6.0206
local MIN_GAIN_DB = 0.15
local BR_STEP = 0.05
local MIN_REGION_SEC = 0.02
local PEAK_MARGIN_DB = 0.0

local params_file = os.getenv("HOME") .. "/rcbit_env_v3_params.txt"
local results_file = os.getenv("HOME") .. "/rcbit_env_v3_results.txt"

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

local CEILING_DB = tonumber(params.CEILING_DB) or -0.5
local ATTACK_SEC = (tonumber(params.ATTACK_MS) or 0) / 1000
local RELEASE_SEC = (tonumber(params.RELEASE_MS) or 70) / 1000
local WINDOW_SEC = (tonumber(params.WINDOW_MS) or 5) / 1000
local FX_SCOPE = params.FX_SCOPE or "TakeFX"
local LIMITER_MODE = params.LIMITER_MODE or "Combined"

-- ============ HELPERS ============
local function calc_rcbit_params(gain_db, ceil_br)
  if math.abs(gain_db) < MIN_GAIN_DB then return nil, nil end
  local total_bits = gain_db / BIT_DB
  local macro = math.floor(math.abs(total_bits) + 0.5)
  if macro == 0 then macro = 1 end
  if gain_db < 0 then macro = -macro end
  local bit_ratio = math.abs(gain_db) / (math.abs(macro) * BIT_DB)
  bit_ratio = math.min(math.max(bit_ratio, 0.0), 3.0)
  if ceil_br then
    bit_ratio = math.ceil(bit_ratio / BR_STEP) * BR_STEP
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

local function get_ch(source)
  local ch = reaper.GetMediaSourceNumChannels(source)
  if ch == 0 then
    local parent = reaper.GetMediaSourceParent(source)
    if parent then ch = reaper.GetMediaSourceNumChannels(parent) end
  end
  if ch == 0 then ch = 1 end
  return ch
end

local function write_env_points(env, regions, value_func, shape, range_start, range_end)
  if not env then return 0 end
  local n_existing = reaper.CountEnvelopePoints(env)
  for i = n_existing - 1, 0, -1 do
    reaper.DeleteEnvelopePointEx(env, -1, i)
  end
  local count = 0
  if #regions > 0 then
    reaper.InsertEnvelopePoint(env, range_start, value_func(regions[1]), shape, 0, false, true)
    count = count + 1
  end
  for _, reg in ipairs(regions) do
    reaper.InsertEnvelopePoint(env, reg.s, value_func(reg), shape, 0, false, true)
    count = count + 1
  end
  if #regions > 0 then
    reaper.InsertEnvelopePoint(env, range_end, value_func(regions[#regions]), shape, 0, false, true)
    count = count + 1
  end
  reaper.Envelope_SortPoints(env)
  return count
end

local function add_fx(scope, take2, track2, name)
  if scope == "TakeFX" then
    return reaper.TakeFX_AddByName(take2, name, -1)
  else
    return reaper.TrackFX_AddByName(track2, name, false, -1)
  end
end

local function get_fx_count(scope, take2, track2)
  if scope == "TakeFX" then
    return reaper.TakeFX_GetCount(take2)
  else
    return reaper.TrackFX_GetCount(track2)
  end
end

local function get_fx_name(scope, take2, track2, idx)
  if scope == "TakeFX" then
    return reaper.TakeFX_GetFXName(take2, idx)
  else
    return reaper.TrackFX_GetFXName(track2, idx)
  end
end

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

-- ============ MAIN ============
reaper.Undo_BeginBlock()
reaper.PreventUIRefresh(1)

local item = reaper.GetSelectedMediaItem(0, 0)
if not item then
  reaper.PreventUIRefresh(-1)
  reaper.Undo_EndBlock("RCBit Env V3 - failed", -1)
  write_result("ERROR: No selected item.")
  return
end

local take = reaper.GetActiveTake(item)
if not take or reaper.TakeIsMIDI(take) then
  reaper.PreventUIRefresh(-1)
  reaper.Undo_EndBlock("RCBit Env V3 - failed", -1)
  write_result("ERROR: Selected item is not audio.")
  return
end

local source = reaper.GetMediaItemTake_Source(take)
local num_ch = get_ch(source)
local sr = get_sr(source)

local item_pos = reaper.GetMediaItemInfo_Value(item, "D_POSITION")
local item_len = reaper.GetMediaItemInfo_Value(item, "D_LENGTH")
local item_end = item_pos + item_len
local track = reaper.GetMediaItem_Track(item)
local take_offset = reaper.GetMediaItemTakeInfo_Value(take, "D_STARTOFFS")
local take_rate = reaper.GetMediaItemTakeInfo_Value(take, "D_PLAYRATE")

-- ============ TIME SELECTION ============
local ts_start, ts_end = reaper.GetSet_LoopTimeRange(false, false, 0, 0, false)
local has_time_sel = (ts_end - ts_start > 0.001)
local scan_start = item_pos
local scan_end = item_end

if has_time_sel then
  scan_start = math.max(ts_start, item_pos)
  scan_end = math.min(ts_end, item_end)
  if scan_end - scan_start < 0.001 then
    reaper.PreventUIRefresh(-1)
    reaper.Undo_EndBlock("RCBit Env V3 - failed", -1)
    write_result("ERROR: Time selection doesn't overlap item.")
    return
  end
end

-- ============ PEAK ANALYSIS VIA ACCESSOR ============
local accessor = reaper.CreateTakeAudioAccessor(take)
local samples_per_win = math.max(math.floor(sr * WINDOW_SEC), 1)
local buf_size = samples_per_win * num_ch
local window_dur = WINDOW_SEC / take_rate

local src_scan_start = take_offset + (scan_start - item_pos) * take_rate
local src_scan_end = take_offset + (scan_end - item_pos) * take_rate

local windows = {}
local t = src_scan_start

while t < src_scan_end do
  local buf = reaper.new_array(buf_size)
  buf.clear()
  local win_samples = math.min(samples_per_win, math.floor((src_scan_end - t) * sr))
  if win_samples <= 0 then break end
  reaper.GetAudioAccessorSamples(accessor, sr, num_ch, t, win_samples, buf)
  local peak = 0
  for i = 1, win_samples * num_ch do
    local s = math.abs(buf[i])
    if s > peak then peak = s end
  end
  local proj_time = item_pos + (t - take_offset) / take_rate
  local peak_db = -math.huge
  if peak > 0 then peak_db = 20 * math.log(peak, 10) end
  local is_peak = (peak_db > CEILING_DB + PEAK_MARGIN_DB)
  table.insert(windows, {
    time = proj_time,
    is_peak = is_peak,
    gain_db = is_peak and (CEILING_DB - peak_db) or 0
  })
  t = t + WINDOW_SEC
end
reaper.DestroyAudioAccessor(accessor)

local peak_win_count = 0
for _, w in ipairs(windows) do if w.is_peak then peak_win_count = peak_win_count + 1 end end

if peak_win_count == 0 then
  reaper.PreventUIRefresh(-1)
  reaper.Undo_EndBlock("RCBit Env V3 - no peaks", -1)
  write_result(string.format("OK: No peaks exceed %.1f dB. Nothing to do. CH:%d SR:%d Win:%d",
    CEILING_DB, num_ch, sr, #windows))
  return
end

-- ============ BUILD REGIONS ============
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
    local ns = math.max(reg.s - ATTACK_SEC, scan_start)
    local ne = math.min(reg.e + RELEASE_SEC, scan_end)
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
  reg.gain_db = reg.is_peak and reg.min_gain or 0
end

-- Merge regions with same params (Combined mode only)
if LIMITER_MODE == "Combined" then
  local mg = {regions[1]}
  for i = 2, #regions do
    local prev = mg[#mg]
    local curr = regions[i]
    local pm, pbr = calc_rcbit_params(prev.gain_db, prev.is_peak)
    local cm, cbr = calc_rcbit_params(curr.gain_db, curr.is_peak)
    if pm == cm and pbr and cbr and math.abs(pbr - cbr) < 0.001 then
      prev.e = curr.e
    elseif pm == nil and cm == nil then
      prev.e = curr.e
    else
      table.insert(mg, curr)
    end
  end
  regions = mg
end

-- ============ APPLY FX WITH ENVELOPES ============
local fx_idx = -1
local n_fx = get_fx_count(FX_SCOPE, take, track)
for i = 0, n_fx - 1 do
  local _, name = get_fx_name(FX_SCOPE, take, track, i)
  if name:match("RCBitRangeGain") then fx_idx = i; break end
end
if fx_idx < 0 then
  fx_idx = add_fx(FX_SCOPE, take, track, "JS:RCBitRangeGain")
end
if fx_idx < 0 then
  reaper.PreventUIRefresh(-1)
  reaper.Undo_EndBlock("RCBit Env V3 - failed", -1)
  write_result("ERROR: Could not add RCBitRangeGain.")
  return
end

-- Time offset: item-relative for TakeFX, project time for TrackFX
local env_time_offset = 0
if FX_SCOPE == "TakeFX" then
  env_time_offset = -item_pos
end

local env_regions = {}
for _, reg in ipairs(regions) do
  table.insert(env_regions, {
    s = reg.s + env_time_offset,
    e = reg.e + env_time_offset,
    is_peak = reg.is_peak,
    gain_db = reg.gain_db,
    min_gain = reg.min_gain,
  })
end
local env_range_start = scan_start + env_time_offset
local env_range_end = scan_end + env_time_offset

local env_points_info = ""

if LIMITER_MODE == "Combined" then
  -- Set base params to neutral
  if FX_SCOPE == "TakeFX" then
    reaper.TakeFX_SetParamNormalized(take, fx_idx, 0, 0.5)   -- Macro=0
    reaper.TakeFX_SetParamNormalized(take, fx_idx, 1, 0.5)   -- Micro=0
    reaper.TakeFX_SetParamNormalized(take, fx_idx, 2, 0.0)   -- BR=0
  else
    reaper.TrackFX_SetParamNormalized(track, fx_idx, 0, 0.5)
    reaper.TrackFX_SetParamNormalized(track, fx_idx, 1, 0.5)
    reaper.TrackFX_SetParamNormalized(track, fx_idx, 2, 0.0)
  end

  local get_env, env_err = get_env_func(FX_SCOPE, take, track, fx_idx)
  if not get_env then
    reaper.PreventUIRefresh(-1)
    reaper.Undo_EndBlock("RCBit Env V3 - failed", -1)
    write_result("ERROR: " .. (env_err or "Cannot create envelope"))
    return
  end

  local env_macro = get_env(0)
  local env_br = get_env(2)

  -- Envelope points use ACTUAL slider values
  local macro_pts = write_env_points(env_macro, env_regions, function(reg)
    local m, _ = calc_rcbit_params(reg.gain_db, reg.is_peak)
    return m or 0
  end, 1, env_range_start, env_range_end)

  local br_pts = write_env_points(env_br, env_regions, function(reg)
    local _, br = calc_rcbit_params(reg.gain_db, reg.is_peak)
    return br or 0
  end, 1, env_range_start, env_range_end)

  env_points_info = string.format("EnvPts: %d Macro, %d BR", macro_pts, br_pts)

elseif LIMITER_MODE == "Micro" then
  -- Micro mode: Macro=0, fixed BR, Micro envelope with gradual release
  local max_correction = 0
  for _, reg in ipairs(regions) do
    if reg.is_peak then
      local corr = math.abs(reg.gain_db)
      if corr > max_correction then max_correction = corr end
    end
  end
  local limiter_br = math.max(1, math.min(3, math.ceil(max_correction / BIT_DB)))

  -- Set base params: Macro=0, Micro=0, BR=limiter_br
  if FX_SCOPE == "TakeFX" then
    reaper.TakeFX_SetParamNormalized(take, fx_idx, 0, 0.5)
    reaper.TakeFX_SetParamNormalized(take, fx_idx, 1, 0.5)
    reaper.TakeFX_SetParamNormalized(take, fx_idx, 2, limiter_br / 3.0)
  else
    reaper.TrackFX_SetParamNormalized(track, fx_idx, 0, 0.5)
    reaper.TrackFX_SetParamNormalized(track, fx_idx, 1, 0.5)
    reaper.TrackFX_SetParamNormalized(track, fx_idx, 2, limiter_br / 3.0)
  end

  local get_env, env_err = get_env_func(FX_SCOPE, take, track, fx_idx)
  if not get_env then
    reaper.PreventUIRefresh(-1)
    reaper.Undo_EndBlock("RCBit Env V3 - failed", -1)
    write_result("ERROR: " .. (env_err or "Cannot create envelope"))
    return
  end

  local env_micro = get_env(1)

  local function calc_micro(gain_db)
    local micro_val = gain_db / (limiter_br * BIT_DB) * 100
    micro_val = math.max(-100, math.min(100, micro_val))
    return math.floor(micro_val)
  end

  -- Clear existing points
  local n_existing = reaper.CountEnvelopePoints(env_micro)
  for i = n_existing - 1, 0, -1 do
    reaper.DeleteEnvelopePointEx(env_micro, -1, i)
  end

  local micro_pts = 0

  if #env_regions > 0 then
    local first_val = env_regions[1].is_peak and calc_micro(env_regions[1].gain_db) or 0
    reaper.InsertEnvelopePoint(env_micro, env_range_start, first_val, 1, 0, false, true)
    micro_pts = micro_pts + 1
  end

  for idx, reg in ipairs(env_regions) do
    if reg.is_peak then
      local mv = calc_micro(reg.gain_db)
      local ramp_start = reg.e - RELEASE_SEC

      if ramp_start > reg.s + 0.001 then
        reaper.InsertEnvelopePoint(env_micro, reg.s, mv, 1, 0, false, true)
        micro_pts = micro_pts + 1
        reaper.InsertEnvelopePoint(env_micro, ramp_start, mv, 0, 0, false, true)
        micro_pts = micro_pts + 1
      else
        reaper.InsertEnvelopePoint(env_micro, reg.s, mv, 0, 0, false, true)
        micro_pts = micro_pts + 1
      end
    else
      reaper.InsertEnvelopePoint(env_micro, reg.s, 0, 1, 0, false, true)
      micro_pts = micro_pts + 1
    end
  end

  if #env_regions > 0 then
    local final_val = env_regions[#env_regions].is_peak and 0 or 0
    reaper.InsertEnvelopePoint(env_micro, env_range_end, final_val, 1, 0, false, true)
    micro_pts = micro_pts + 1
  end

  reaper.Envelope_SortPoints(env_micro)

  env_points_info = string.format("EnvPts: %d Micro (BR=%d) MaxCorr:%.2fdB",
    micro_pts, limiter_br, max_correction)
end

-- ============ SUMMARY ============
local peak_regions, clean_regions = 0, 0
for _, r in ipairs(regions) do
  if r.is_peak then peak_regions = peak_regions + 1
  else clean_regions = clean_regions + 1 end
end

local result = string.format(
  "OK: Scope=%s Mode=%s Ceiling=%.1f Atk=%dms Rel=%dms Win=%dms "
  .. "CH=%d SR=%d Windows=%d(%dpeak) Regions=%d(%dpeak,%dclean) %s",
  FX_SCOPE, LIMITER_MODE,
  CEILING_DB, ATTACK_SEC * 1000, RELEASE_SEC * 1000, WINDOW_SEC * 1000,
  num_ch, sr,
  #windows, peak_win_count,
  #regions, peak_regions, clean_regions,
  env_points_info)

if has_time_sel then
  result = result .. string.format(" TimeSel:%.3f-%.3f", scan_start, scan_end)
end

write_result(result)

reaper.PreventUIRefresh(-1)
reaper.UpdateArrange()
reaper.Undo_EndBlock("RCBit Envelope Limiter V3.0", -1)
