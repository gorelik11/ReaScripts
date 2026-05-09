-- RCBit Envelope Limiter V4.0
-- Peak limiter via FX parameter envelope automation on RCBitRangeGain.
-- No splits — writes envelopes.
-- Combined mode: single RCBit, Macro + BR envelopes.
-- Micro mode: single RCBit, Macro=0 + fixed BR + Micro envelope (finer resolution).
-- Peak source: Accessor (raw source, fast) or DryRun (post-FX via RENDER_STATS, for multi-pass).
-- Processes ALL selected items (TakeFX mode). Supports time selection.

local BIT_DB = 6.0206
local MIN_GAIN_DB = 0.15
local BR_STEP = 0.05
local MIN_REGION_SEC = 0.02
local PEAK_MARGIN_DB = 0.0

-- ============ DIALOG ============
local scope_ret = reaper.ShowMessageBox(
  "Choose FX scope for RCBitRangeGain envelope:\n\nYES = TakeFX (item-level)\nNO = TrackFX (track-level)",
  "RCBit Envelope Limiter V4.0 — FX Scope", 3)
if scope_ret == 2 then return end
local FX_SCOPE = (scope_ret == 6) and "TakeFX" or "TrackFX"

local mode_ret = reaper.ShowMessageBox(
  "Limiter mode?\n\n"
  .. "YES = Combined (single RCBit, Macro+BR envelope)\n"
  .. "NO = Micro (single RCBit, Micro envelope — finer resolution)",
  "RCBit Envelope Limiter V4.0 — Mode", 3)
if mode_ret == 2 then return end
local LIMITER_MODE = (mode_ret == 6) and "Combined" or "Micro"

local peak_ret = reaper.ShowMessageBox(
  "Peak source?\n\n"
  .. "YES = Accessor (raw source, fast — default)\n"
  .. "NO = DryRun (post-FX via RENDER_STATS — use for multi-pass limiting)",
  "RCBit Envelope Limiter V4.0 — Peak Source", 3)
if peak_ret == 2 then return end
local PEAK_SOURCE = "Accessor"
if peak_ret == 7 then
  local ch_ret = reaper.ShowMessageBox(
    "Dry run channel mode?\n\n"
    .. "YES = Mono (42448)\n"
    .. "NO = Stereo (42439)",
    "Dry Run Channels", 3)
  if ch_ret == 2 then return end
  PEAK_SOURCE = (ch_ret == 6) and "MonoDryRun" or "StereoDryRun"
end

local ok, csv = reaper.GetUserInputs(
  "RCBit Envelope Limiter V4.0 (" .. FX_SCOPE .. "/" .. LIMITER_MODE .. "/" .. PEAK_SOURCE .. ")", 4,
  "Peak Ceiling (dB),Attack (ms),Release (ms),Analysis Window (ms)",
  "-0.5,0,70,5")
if not ok then return end

local vals = {}
for v in csv:gmatch("[^,]+") do table.insert(vals, tonumber(v)) end

local CEILING_DB = vals[1] or -0.5
local ATTACK_SEC = (vals[2] or 0) / 1000
local RELEASE_SEC = (vals[3] or 70) / 1000
local WINDOW_SEC = (vals[4] or 5) / 1000

local use_dryrun = (PEAK_SOURCE ~= "Accessor")
local is_mono_dryrun = (PEAK_SOURCE == "MonoDryRun")

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

local function measure_peak_dryrun(track2, start_time, end_time, mono)
  local orig_ts_start, orig_ts_end = reaper.GetSet_LoopTimeRange(false, false, 0, 0, false)
  local orig_settings = reaper.GetSetProjectInfo(0, "RENDER_SETTINGS", 0, false)
  local orig_rclose = reaper.SNM_GetIntConfigVar("renderclosewhendone", 0)

  reaper.GetSet_LoopTimeRange(true, false, start_time, end_time, false)
  reaper.SetOnlyTrackSelected(track2)
  reaper.GetSetProjectInfo(0, "RENDER_SETTINGS", 3, true)

  local action = mono and "42448" or "42439"
  local dr_ok, result = reaper.GetSetProjectInfo_String(0, "RENDER_STATS", action, false)

  reaper.GetSetProjectInfo(0, "RENDER_SETTINGS", orig_settings, true)
  reaper.SNM_SetIntConfigVar("renderclosewhendone", orig_rclose)
  reaper.GetSet_LoopTimeRange(true, false, orig_ts_start, orig_ts_end, false)

  if not dr_ok or not result or result == "" then return nil, "Dry run failed" end

  local peak_db
  for field in result:gmatch("[^;]+") do
    local name, value = field:match("(%u+):(.+)")
    if name == "PEAK" then peak_db = tonumber(value) end
  end

  if not peak_db then return nil, "No PEAK in result: " .. result end
  return peak_db, nil
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

-- ============ PROCESS ONE ITEM ============
-- Returns: { ok=bool, msg=string, peak_regions=int, clean_regions=int, ... }
local function process_item(item)
  local take = reaper.GetActiveTake(item)
  if not take or reaper.TakeIsMIDI(take) then
    return { ok = false, msg = "not audio" }
  end

  local source = reaper.GetMediaItemTake_Source(take)
  local num_ch = get_ch(source)
  local sr = get_sr(source)

  local item_pos = reaper.GetMediaItemInfo_Value(item, "D_POSITION")
  local item_len = reaper.GetMediaItemInfo_Value(item, "D_LENGTH")
  local item_end = item_pos + item_len
  local track = reaper.GetMediaItem_Track(item)
  local take_rate = reaper.GetMediaItemTakeInfo_Value(take, "D_PLAYRATE")

  -- Time selection
  local ts_start, ts_end = reaper.GetSet_LoopTimeRange(false, false, 0, 0, false)
  local has_time_sel = (ts_end - ts_start > 0.001)
  local scan_start = item_pos
  local scan_end = item_end

  if has_time_sel then
    scan_start = math.max(ts_start, item_pos)
    scan_end = math.min(ts_end, item_end)
    if scan_end - scan_start < 0.001 then
      return { ok = false, msg = "time sel doesn't overlap" }
    end
  end

  -- Peak analysis via accessor (spatial map)
  local window_dur = WINDOW_SEC / take_rate
  local windows = {}
  local peak_win_count = 0

  local accessor = reaper.CreateTakeAudioAccessor(take)
  local samples_per_win = math.max(math.floor(sr * WINDOW_SEC), 1)
  local buf_size = samples_per_win * num_ch

  local src_scan_start = (scan_start - item_pos) * take_rate
  local src_scan_end = (scan_end - item_pos) * take_rate

  local accessor_max_db = -math.huge
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
    if peak_db > accessor_max_db then accessor_max_db = peak_db end
    table.insert(windows, {
      time = proj_time,
      peak_db = peak_db,
    })
    t = t + WINDOW_SEC
  end
  reaper.DestroyAudioAccessor(accessor)

  -- Determine effective peak: accessor raw or one dry run
  local effective_max_db = accessor_max_db
  local dryrun_peak_db = nil

  if use_dryrun then
    reaper.PreventUIRefresh(-1)
    local dr_peak, dr_err = measure_peak_dryrun(track, scan_start, scan_end, is_mono_dryrun)
    reaper.PreventUIRefresh(1)
    if not dr_peak then
      return { ok = false, msg = "DryRun failed: " .. (dr_err or "unknown") }
    end
    dryrun_peak_db = dr_peak
    effective_max_db = dr_peak
  end

  if effective_max_db <= CEILING_DB + PEAK_MARGIN_DB then
    local msg = "no peaks"
    if dryrun_peak_db then
      msg = msg .. string.format(" (DryRun: %.1f dB)", dryrun_peak_db)
    end
    return { ok = true, msg = msg, windows = #windows, peak_wins = 0,
             peak_regions = 0, clean_regions = 0 }
  end

  -- Scale accessor peaks to match dry run reality
  -- offset = difference between dry run peak and accessor peak
  local peak_offset = 0
  if use_dryrun and accessor_max_db > -200 then
    peak_offset = effective_max_db - accessor_max_db
  end

  -- Classify windows using offset-corrected peaks
  for _, w in ipairs(windows) do
    local corrected_db = w.peak_db + peak_offset
    w.is_peak = (corrected_db > CEILING_DB + PEAK_MARGIN_DB)
    w.gain_db = w.is_peak and (CEILING_DB - corrected_db) or 0
    if w.is_peak then peak_win_count = peak_win_count + 1 end
  end

  if peak_win_count == 0 then
    return { ok = true, msg = "no peaks", windows = #windows, peak_wins = 0,
             peak_regions = 0, clean_regions = 0 }
  end

  -- Build regions
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

  -- Apply FX with envelopes
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
    return { ok = false, msg = "could not add RCBitRangeGain" }
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
    if FX_SCOPE == "TakeFX" then
      reaper.TakeFX_SetParamNormalized(take, fx_idx, 0, 0.5)
      reaper.TakeFX_SetParamNormalized(take, fx_idx, 1, 0.5)
      reaper.TakeFX_SetParamNormalized(take, fx_idx, 2, 0.0)
    else
      reaper.TrackFX_SetParamNormalized(track, fx_idx, 0, 0.5)
      reaper.TrackFX_SetParamNormalized(track, fx_idx, 1, 0.5)
      reaper.TrackFX_SetParamNormalized(track, fx_idx, 2, 0.0)
    end

    local get_env, env_err = get_env_func(FX_SCOPE, take, track, fx_idx)
    if not get_env then
      return { ok = false, msg = env_err or "cannot create envelope" }
    end

    local env_macro = get_env(0)
    local env_br = get_env(2)

    local macro_pts = write_env_points(env_macro, env_regions, function(reg)
      local m, _ = calc_rcbit_params(reg.gain_db, reg.is_peak)
      return m or 0
    end, 1, env_range_start, env_range_end)

    local br_pts = write_env_points(env_br, env_regions, function(reg)
      local _, br = calc_rcbit_params(reg.gain_db, reg.is_peak)
      return br or 0
    end, 1, env_range_start, env_range_end)

    env_points_info = string.format("%dM+%dBR pts", macro_pts, br_pts)

  elseif LIMITER_MODE == "Micro" then
    local max_correction = 0
    for _, reg in ipairs(regions) do
      if reg.is_peak then
        local corr = math.abs(reg.gain_db)
        if corr > max_correction then max_correction = corr end
      end
    end
    local limiter_br = math.max(1, math.min(3, math.ceil(max_correction / BIT_DB)))

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
      return { ok = false, msg = env_err or "cannot create envelope" }
    end

    local env_micro = get_env(1)

    local function calc_micro(gain_db)
      local micro_val = gain_db / (limiter_br * BIT_DB) * 100
      micro_val = math.max(-100, math.min(100, micro_val))
      return math.floor(micro_val)
    end

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
      reaper.InsertEnvelopePoint(env_micro, env_range_end, 0, 1, 0, false, true)
      micro_pts = micro_pts + 1
    end

    reaper.Envelope_SortPoints(env_micro)

    env_points_info = string.format("%dMi(BR=%d)", micro_pts, limiter_br)
  end

  -- Count final regions
  local peak_regions, clean_regions = 0, 0
  for _, r in ipairs(regions) do
    if r.is_peak then peak_regions = peak_regions + 1
    else clean_regions = clean_regions + 1 end
  end

  return {
    ok = true, msg = "done",
    windows = #windows, peak_wins = peak_win_count,
    peak_regions = peak_regions, clean_regions = clean_regions,
    env_points_info = env_points_info,
  }
end

-- ============ MAIN ============
local item_count = reaper.CountSelectedMediaItems(0)
if item_count == 0 then
  reaper.ShowMessageBox("No selected items.", "RCBit Envelope Limiter V4.0", 0)
  return
end

reaper.Undo_BeginBlock()
reaper.PreventUIRefresh(1)

local results = {}
local total_ok = 0
local total_skip = 0
local total_err = 0

for item_idx = 0, item_count - 1 do
  local item = reaper.GetSelectedMediaItem(0, item_idx)
  local r = process_item(item)
  r.item_idx = item_idx + 1
  local pos = reaper.GetMediaItemInfo_Value(item, "D_POSITION")
  r.pos = pos
  table.insert(results, r)
  if r.ok and r.msg == "done" then
    total_ok = total_ok + 1
  elseif r.ok then
    total_skip = total_skip + 1
  else
    total_err = total_err + 1
  end
end

-- Build summary
local summary_lines = {}
table.insert(summary_lines, string.format(
  "RCBit Envelope Limiter V4.0 — Done\n\n"
  .. "FX Scope: %s | Mode: %s | Peak Source: %s\n"
  .. "Ceiling: %.1f dB | Attack: %dms | Release: %dms | Window: %dms\n"
  .. "Items: %d selected, %d processed, %d skipped, %d errors\n",
  FX_SCOPE, LIMITER_MODE, PEAK_SOURCE,
  CEILING_DB, ATTACK_SEC * 1000, RELEASE_SEC * 1000, WINDOW_SEC * 1000,
  item_count, total_ok, total_skip, total_err))

for _, r in ipairs(results) do
  local line = string.format("#%d (pos=%.2f): %s", r.item_idx, r.pos, r.msg)
  if r.ok and r.peak_regions and r.peak_regions > 0 then
    line = line .. string.format(" | %dp+%dc %s",
      r.peak_regions, r.clean_regions, r.env_points_info or "")
  end
  table.insert(summary_lines, line)
end

reaper.PreventUIRefresh(-1)
reaper.UpdateArrange()
reaper.Undo_EndBlock("RCBit Envelope Limiter V4.0", -1)
reaper.ShowMessageBox(table.concat(summary_lines, "\n"), "RCBit Envelope Limiter V4.0", 0)
