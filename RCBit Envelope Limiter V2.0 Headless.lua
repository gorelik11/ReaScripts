-- RCBit Envelope Limiter V2.0 Headless
-- LUFS+Peak or Peak-only limiter via FX parameter envelope automation.
-- No splits — writes Macro + BR envelopes on RCBitRangeGain.
-- Accessor-based peak analysis — no render, no defer, fully synchronous.
-- Supports time selection: if active, only scans/limits within that range.
--
-- Based on V5.0 (proven envelope approach) + V8.0 (accessor patterns)
--
-- Reads params from ~/rcbit_env_v2_params.txt
-- Writes results to ~/rcbit_env_v2_results.txt
--
-- Params:
--   TARGET_LUFS  (0 = peak-only limiter, no LUFS gain)
--   CEILING_DB   (peak ceiling in dB, e.g. -0.5)
--   ATTACK_MS    (attack time in ms)
--   RELEASE_MS   (release time in ms)
--   WINDOW_MS    (analysis window in ms)
--   FX_SCOPE     (TakeFX or TrackFX, default TakeFX)

local BIT_DB = 6.0206
local MIN_GAIN_DB = 0.15
local BR_STEP = 0.05
local MIN_REGION_SEC = 0.02
local PEAK_MARGIN_DB = 0.0

local params_file = os.getenv("HOME") .. "/rcbit_env_v2_params.txt"
local results_file = os.getenv("HOME") .. "/rcbit_env_v2_results.txt"

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
  local key, val = line:match("(%S+)%s*=%s*(%S+)")
  if key then params[key] = val end
end
f:close()

local TARGET_LUFS = tonumber(params.TARGET_LUFS) or 0
local CEILING_DB = tonumber(params.CEILING_DB) or -0.5
local ATTACK_SEC = (tonumber(params.ATTACK_MS) or 0) / 1000
local RELEASE_SEC = (tonumber(params.RELEASE_MS) or 70) / 1000
local WINDOW_SEC = (tonumber(params.WINDOW_MS) or 5) / 1000
local FX_SCOPE = params.FX_SCOPE or "TakeFX"

-- ============ HELPERS ============
-- FX param envelope points use ACTUAL slider values, not normalized 0-1
local function macro_to_env(m) return m end
local function br_to_env(br) return br end

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

-- Write envelope points (shape=1 = square/step)
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

-- FX helpers (scope-aware, matching V5.0 pattern)
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
write_result("RUNNING")

reaper.Undo_BeginBlock()
reaper.PreventUIRefresh(1)

local item = reaper.GetSelectedMediaItem(0, 0)
if not item then
  write_result("ERROR: No selected item")
  reaper.PreventUIRefresh(-1)
  reaper.Undo_EndBlock("RCBit Env V2 - failed", -1)
  return
end

local take = reaper.GetActiveTake(item)
if not take or reaper.TakeIsMIDI(take) then
  write_result("ERROR: Not audio item")
  reaper.PreventUIRefresh(-1)
  reaper.Undo_EndBlock("RCBit Env V2 - failed", -1)
  return
end

local source = reaper.GetMediaItemTake_Source(take)
local num_ch = get_ch(source)
local sr = get_sr(source)
local is_mono = (num_ch == 1)

local item_pos = reaper.GetMediaItemInfo_Value(item, "D_POSITION")
local item_len = reaper.GetMediaItemInfo_Value(item, "D_LENGTH")
local item_end = item_pos + item_len
local track = reaper.GetMediaItem_Track(item)
local take_offset = reaper.GetMediaItemTakeInfo_Value(take, "D_STARTOFFS")
local take_rate = reaper.GetMediaItemTakeInfo_Value(take, "D_PLAYRATE")

-- ============ TIME SELECTION SUPPORT ============
local ts_start, ts_end = reaper.GetSet_LoopTimeRange(false, false, 0, 0, false)
local has_time_sel = (ts_end - ts_start > 0.001)
local scan_start = item_pos
local scan_end = item_end

if has_time_sel then
  scan_start = math.max(ts_start, item_pos)
  scan_end = math.min(ts_end, item_end)
  if scan_end - scan_start < 0.001 then
    write_result("ERROR: Time selection doesn't overlap item")
    reaper.PreventUIRefresh(-1)
    reaper.Undo_EndBlock("RCBit Env V2 - failed", -1)
    return
  end
end

-- ============ LUFS MEASUREMENT ============
local lufs_gain_db = 0
local current_lufs = 0

if TARGET_LUFS ~= 0 then
  local lufs_ok, lufs_integrated = reaper.NF_AnalyzeTakeLoudness(take, false)
  if not lufs_ok or not lufs_integrated or lufs_integrated <= -200 then
    write_result("ERROR: LUFS analysis failed")
    reaper.PreventUIRefresh(-1)
    reaper.Undo_EndBlock("RCBit Env V2 - failed", -1)
    return
  end
  current_lufs = lufs_integrated
  if is_mono then
    local pan_law = reaper.GetSetProjectInfo(0, "PROJECT_PANLAW", 0, false)
    if pan_law == 0 then pan_law = 3 end
    current_lufs = lufs_integrated - pan_law
  end
  lufs_gain_db = TARGET_LUFS - current_lufs
end

-- ============ PEAK ANALYSIS VIA ACCESSOR ============
local accessor = reaper.CreateTakeAudioAccessor(take)
local samples_per_win = math.max(math.floor(sr * WINDOW_SEC), 1)
local buf_size = samples_per_win * num_ch
local window_dur = WINDOW_SEC / take_rate

-- Convert scan bounds from project time to source time
-- Accessor position 0 = item start (D_STARTOFFS baked in), no take_offset needed
local src_scan_start = (scan_start - item_pos) * take_rate
local src_scan_end = (scan_end - item_pos) * take_rate

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
  local proj_time = item_pos + t / take_rate
  local peak_db = -math.huge
  if peak > 0 then peak_db = 20 * math.log(peak, 10) end
  local peak_after_gain = peak_db + lufs_gain_db
  local is_peak = (peak_after_gain > CEILING_DB + PEAK_MARGIN_DB)
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
  write_result(string.format("OK\nNo peaks exceed %.1f dB. Nothing to do.\nCH: %d | SR: %d\nWindows: %d",
    CEILING_DB, num_ch, sr, #windows))
  reaper.Undo_EndBlock("RCBit Env V2 - no peaks", -1)
  return
end

if peak_win_count == 0 and TARGET_LUFS ~= 0 then
  local lufs_m, lufs_br = calc_rcbit_params(lufs_gain_db, false)
  if not lufs_m then
    reaper.PreventUIRefresh(-1)
    write_result(string.format("OK\nAlready near target LUFS (%.1f, gain=%.2f dB)", current_lufs, lufs_gain_db))
    reaper.Undo_EndBlock("RCBit Env V2 - no changes", -1)
    return
  end
  local fx = add_fx(FX_SCOPE, take, track, "JS:RCBitRangeGain")
  if fx >= 0 then
    set_param(FX_SCOPE, take, track, fx, 0, lufs_m)
    set_param(FX_SCOPE, take, track, fx, 1, 0)
    set_param(FX_SCOPE, take, track, fx, 2, lufs_br)
  end
  local eff = lufs_m * lufs_br * BIT_DB
  reaper.PreventUIRefresh(-1)
  reaper.UpdateArrange()
  write_result(string.format(
    "OK\nNo peaks exceed ceiling after LUFS gain\n"
    .. "CH: %d | SR: %d | FX: %s\nLUFS: %.1f → %d (gain: %+.2f, eff: %+.2f)\n"
    .. "Static %s: M=%d BR=%.2f",
    num_ch, sr, FX_SCOPE, current_lufs, TARGET_LUFS, lufs_gain_db, eff, FX_SCOPE, lufs_m, lufs_br))
  reaper.Undo_EndBlock("RCBit Envelope Limiter V2.0", -1)
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

-- Attack/release
for i, reg in ipairs(regions) do
  if reg.is_peak then
    local ns = math.max(reg.s - ATTACK_SEC, scan_start)
    local ne = math.min(reg.e + RELEASE_SEC, scan_end)
    if i > 1 and not regions[i-1].is_peak and regions[i-1].e > ns then regions[i-1].e = ns end
    if i < #regions and not regions[i+1].is_peak and regions[i+1].s < ne then regions[i+1].s = ne end
    reg.s = ns; reg.e = ne
  end
end

-- Remove zero-length
local valid = {}
for _, r in ipairs(regions) do if r.e - r.s > 0.001 then table.insert(valid, r) end end
regions = valid

-- Merge adjacent peaks
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

-- Absorb tiny
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

-- Assign gains
for _, reg in ipairs(regions) do
  reg.gain_db = reg.is_peak and reg.min_gain or lufs_gain_db
end

-- Merge same params
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

-- ============ APPLY FX WITH ENVELOPES (V5.0 PATTERN) ============
-- Find or add RCBitRangeGain
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
  write_result("ERROR: Could not add RCBitRangeGain")
  reaper.Undo_EndBlock("RCBit Env V2 - failed", -1)
  return
end

-- Set base params to neutral using normalized values
-- Macro=0: norm = (0+16)/32 = 0.5
-- Micro=0: norm = (0+100)/200 = 0.5
-- BR=0: norm = 0/3 = 0.0
if FX_SCOPE == "TakeFX" then
  reaper.TakeFX_SetParamNormalized(take, fx_idx, 0, 0.5)   -- Macro=0
  reaper.TakeFX_SetParamNormalized(take, fx_idx, 1, 0.5)   -- Micro=0
  reaper.TakeFX_SetParamNormalized(take, fx_idx, 2, 0.0)   -- BR=0
else
  reaper.TrackFX_SetParamNormalized(track, fx_idx, 0, 0.5)
  reaper.TrackFX_SetParamNormalized(track, fx_idx, 1, 0.5)
  reaper.TrackFX_SetParamNormalized(track, fx_idx, 2, 0.0)
end

-- Set track automation mode to READ so envelopes are applied during playback/render
reaper.SetTrackAutomationMode(track, 1)  -- 1 = READ

-- Create FX param envelopes (V5.0 pattern)
local get_env, env_err = get_env_func(FX_SCOPE, take, track, fx_idx)
if not get_env then
  reaper.PreventUIRefresh(-1)
  write_result("ERROR: " .. (env_err or "Cannot create envelope"))
  reaper.Undo_EndBlock("RCBit Env V2 - failed", -1)
  return
end

local env_macro = get_env(0)  -- Macro param
local env_br = get_env(2)     -- BR param

if not env_macro or not env_br then
  reaper.PreventUIRefresh(-1)
  write_result("ERROR: Failed to create envelopes")
  reaper.Undo_EndBlock("RCBit Env V2 - failed", -1)
  return
end

-- For TakeFX envelopes, times must be item-relative (0 = item start)
-- For TrackFX envelopes, times are project time
local env_time_offset = 0
if FX_SCOPE == "TakeFX" then
  env_time_offset = -item_pos
end

-- Build envelope regions with offset times
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

-- Write Macro envelope (shape=1 = square/step)
local macro_pts = write_env_points(env_macro, env_regions, function(reg)
  local m, _ = calc_rcbit_params(reg.gain_db, reg.is_peak)
  return macro_to_env(m or 0)
end, 1, env_range_start, env_range_end)

-- Write BR envelope
local br_pts = write_env_points(env_br, env_regions, function(reg)
  local _, br = calc_rcbit_params(reg.gain_db, reg.is_peak)
  return br_to_env(br or 0)
end, 1, env_range_start, env_range_end)

-- ============ RESULTS ============
local peak_regions, clean_regions = 0, 0
for _, r in ipairs(regions) do
  if r.is_peak then peak_regions = peak_regions + 1
  else clean_regions = clean_regions + 1 end
end

local result = string.format("OK\nCH: %d | SR: %d | FX: %s\n", num_ch, sr, FX_SCOPE)

if TARGET_LUFS ~= 0 then
  local lufs_m, lufs_br = calc_rcbit_params(lufs_gain_db, false)
  local lufs_eff = lufs_m and (lufs_m * lufs_br * BIT_DB) or 0
  result = result .. string.format("LUFS: %.1f → %d (gain: %+.2f, eff: %+.2f)\n",
    current_lufs, TARGET_LUFS, lufs_gain_db, lufs_eff)
else
  result = result .. "LUFS: disabled (peak-only)\n"
end

result = result .. string.format(
  "Ceiling: %.1f dB | Attack: %dms | Release: %dms | Window: %dms\n",
  CEILING_DB, ATTACK_SEC * 1000, RELEASE_SEC * 1000, WINDOW_SEC * 1000)

if has_time_sel then
  result = result .. string.format("Time selection: %.3f - %.3f\n", scan_start, scan_end)
end

result = result .. string.format(
  "Windows: %d (%d peak)\nRegions: %d (%d peak, %d clean)\n"
  .. "Envelope points: %d Macro, %d BR\n---",
  #windows, peak_win_count,
  #regions, peak_regions, clean_regions,
  macro_pts, br_pts)

for i, reg in ipairs(regions) do
  local m, br = calc_rcbit_params(reg.gain_db, reg.is_peak)
  local eff = 0
  if m and br then eff = math.abs(m) * br * BIT_DB * (m < 0 and -1 or 1) end
  result = result .. string.format(
    "\n  R%d: %.3f-%.3f %s gain=%.2f M=%s BR=%s eff=%+.2f",
    i, reg.s, reg.e,
    reg.is_peak and "PEAK" or "CLEAN",
    reg.gain_db,
    m and tostring(m) or "0", br and string.format("%.2f", br) or "0.00",
    eff)
end

write_result(result)

reaper.PreventUIRefresh(-1)
reaper.UpdateArrange()
reaper.Undo_EndBlock("RCBit Envelope Limiter V2.0", -1)
