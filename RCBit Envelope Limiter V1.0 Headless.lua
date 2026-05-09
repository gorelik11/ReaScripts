-- RCBit Envelope Limiter V1.0 Headless
-- Peak-only limiter via FX parameter envelopes on track-insert RCBitRangeGain.
-- No splits — writes Macro + BR automation envelopes.
-- Renders track to temp WAV for accurate post-FX peak measurement.
-- Uses deferred execution: render happens after script returns to REAPER,
-- so reapy connection doesn't timeout during modal render dialog.
--
-- Reads params from ~/rcbit_env_limiter_params.txt
-- Writes results to ~/rcbit_env_limiter_results.txt

local BIT_DB = 6.0206
local MIN_GAIN_DB = 0.15
local BR_STEP = 0.05
local MIN_REGION_SEC = 0.02
local PEAK_MARGIN_DB = 0.0

local params_file = os.getenv("HOME") .. "/rcbit_env_limiter_params.txt"
local results_file = os.getenv("HOME") .. "/rcbit_env_limiter_results.txt"

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

local CEILING_DB = tonumber(params.CEILING_DB) or -0.5
local ATTACK_SEC = (tonumber(params.ATTACK_MS) or 0) / 1000
local RELEASE_SEC = (tonumber(params.RELEASE_MS) or 70) / 1000
local WINDOW_SEC = (tonumber(params.WINDOW_MS) or 5) / 1000

-- RCBit parameter calculation
local function calc_rcbit_params(gain_db, floor_br)
  if math.abs(gain_db) < MIN_GAIN_DB then return nil, nil end
  local total_bits = gain_db / BIT_DB
  local macro = math.floor(math.abs(total_bits) + 0.5)
  if macro == 0 then macro = 1 end
  if gain_db < 0 then macro = -macro end
  local bit_ratio = math.abs(gain_db) / (math.abs(macro) * BIT_DB)
  bit_ratio = math.min(math.max(bit_ratio, 0.0), 3.0)
  if floor_br then
    bit_ratio = math.ceil(bit_ratio / BR_STEP) * BR_STEP  -- ceil ensures peak is reduced below ceiling
  else
    bit_ratio = math.floor(bit_ratio / BR_STEP + 0.5) * BR_STEP
  end
  return macro, bit_ratio
end

-- Normalization for FX param envelopes
local function macro_to_norm(m) return (m + 16) / 32 end
local function br_to_norm(br) return br / 3.0 end

-- SR/CH helpers with fallback chains
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

-- Find RCBitRangeGain on track insert
local function find_rcbit_on_track(track)
  local n = reaper.TrackFX_GetCount(track)
  for i = 0, n - 1 do
    local _, name = reaper.TrackFX_GetFXName(track, i, "")
    if name:match("RCBitRangeGain") then return i end
  end
  return nil
end

-- Write envelope points (shape=1 = square/step)
local function write_env_points(env, regions, value_func, item_pos, item_end)
  if not env then return 0 end
  local n_existing = reaper.CountEnvelopePoints(env)
  for i = n_existing - 1, 0, -1 do
    reaper.DeleteEnvelopePointEx(env, -1, i)
  end
  local count = 0
  if #regions > 0 and item_pos then
    reaper.InsertEnvelopePoint(env, item_pos, value_func(regions[1]), 1, 0, false, true)
    count = count + 1
  end
  for _, reg in ipairs(regions) do
    reaper.InsertEnvelopePoint(env, reg.s, value_func(reg), 1, 0, false, true)
    count = count + 1
  end
  if #regions > 0 and item_end then
    reaper.InsertEnvelopePoint(env, item_end, value_func(regions[#regions]), 1, 0, false, true)
    count = count + 1
  end
  reaper.Envelope_SortPoints(env)
  return count
end

-- ============ PHASE 1: VALIDATE + SETUP RENDER ============

write_result("RUNNING")

local item = reaper.GetSelectedMediaItem(0, 0)
if not item then
  write_result("ERROR: No selected item")
  return
end

local take = reaper.GetActiveTake(item)
if not take or reaper.TakeIsMIDI(take) then
  write_result("ERROR: Not audio item")
  return
end

local track = reaper.GetMediaItem_Track(item)
local item_pos = reaper.GetMediaItemInfo_Value(item, "D_POSITION")
local item_len = reaper.GetMediaItemInfo_Value(item, "D_LENGTH")
local item_end = item_pos + item_len

local source = reaper.GetMediaItemTake_Source(take)
local sr = get_sr(source)
local num_ch = get_ch(source)

-- Save time selection
local orig_ts_start, orig_ts_end = reaper.GetSet_LoopTimeRange(false, false, 0, 0, false)

-- Find and disable existing RCBit on track (so render measures without it)
local existing_rcbit = find_rcbit_on_track(track)
local rcbit_was_enabled = false
if existing_rcbit then
  rcbit_was_enabled = reaper.TrackFX_GetEnabled(track, existing_rcbit)
  reaper.TrackFX_SetEnabled(track, existing_rcbit, false)
end

-- Setup render
local proj_path = reaper.GetProjectPath()
local sep = package.config:sub(1, 1)
local tmp_dir = proj_path .. sep .. "tmp"
reaper.RecursiveCreateDirectory(tmp_dir, 0)
local tmp_filename = "_RCBIT_ENV_LIM_V1"

-- Catalog existing files before render (to find the NEW one after)
local existing_files = {}
local ei = 0
while true do
  local fn = reaper.EnumerateFiles(tmp_dir, ei)
  if not fn then break end
  if fn:match("^" .. tmp_filename) and fn:match("%.wav$") then
    existing_files[fn] = true
  end
  ei = ei + 1
end

-- Save render settings
local _, orig_rf = reaper.GetSetProjectInfo_String(0, "RENDER_FILE", "", false)
local _, orig_rp = reaper.GetSetProjectInfo_String(0, "RENDER_PATTERN", "", false)
local orig_rb = reaper.GetSetProjectInfo(0, "RENDER_BOUNDSFLAG", 0, false)
local orig_rs = reaper.GetSetProjectInfo(0, "RENDER_SETTINGS", 0, false)
local orig_rsr = reaper.GetSetProjectInfo(0, "RENDER_SRATE", 0, false)
local orig_rch = reaper.GetSetProjectInfo(0, "RENDER_CHANNELS", 0, false)
local _, orig_rfmt = reaper.GetSetProjectInfo_String(0, "RENDER_FORMAT", "", false)
local orig_addtoproj = reaper.GetSetProjectInfo(0, "RENDER_ADDTOPROJ", 0, false)
local orig_speed = reaper.SNM_GetIntConfigVar("projrenderlimit", 0)
local orig_rclose = reaper.SNM_GetIntConfigVar("renderclosewhendone", 0)
local orig_solo = reaper.GetMediaTrackInfo_Value(track, "I_SOLO")

-- Configure render
reaper.GetSet_LoopTimeRange(true, false, item_pos, item_end, false)
reaper.SetOnlyTrackSelected(track)
reaper.SetMediaTrackInfo_Value(track, "I_SOLO", 2)  -- solo in place

reaper.GetSetProjectInfo_String(0, "RENDER_FILE", tmp_dir, true)
reaper.GetSetProjectInfo_String(0, "RENDER_PATTERN", tmp_filename, true)
reaper.GetSetProjectInfo(0, "RENDER_BOUNDSFLAG", 2, true)   -- time selection
reaper.GetSetProjectInfo(0, "RENDER_SETTINGS", 3, true)     -- stems (selected tracks)
reaper.GetSetProjectInfo(0, "RENDER_SRATE", sr, true)
reaper.GetSetProjectInfo(0, "RENDER_CHANNELS", num_ch, true)
reaper.GetSetProjectInfo_String(0, "RENDER_FORMAT", "ZXZhdwgA", true)  -- WAV 8-bit PCM
reaper.GetSetProjectInfo(0, "RENDER_ADDTOPROJ", 0, true)
reaper.SNM_SetIntConfigVar("projrenderlimit", 0)            -- full-speed offline
reaper.SNM_SetIntConfigVar("renderclosewhendone", 17)       -- auto-close + silent increment

-- ============ DEFERRED: RENDER + PHASE 2 ============
-- Use defer so the render dialog opens AFTER this script returns to REAPER.
-- This prevents reapy connection timeout during the modal render dialog.

reaper.defer(function()
  reaper.Undo_BeginBlock()

  -- Trigger render (modal dialog — blocks until render completes)
  reaper.Main_OnCommand(42230, 0)

  -- Restore render settings
  reaper.GetSetProjectInfo_String(0, "RENDER_FILE", orig_rf, true)
  reaper.GetSetProjectInfo_String(0, "RENDER_PATTERN", orig_rp, true)
  reaper.GetSetProjectInfo(0, "RENDER_BOUNDSFLAG", orig_rb, true)
  reaper.GetSetProjectInfo(0, "RENDER_SETTINGS", orig_rs, true)
  reaper.GetSetProjectInfo(0, "RENDER_SRATE", orig_rsr, true)
  reaper.GetSetProjectInfo(0, "RENDER_CHANNELS", orig_rch, true)
  reaper.GetSetProjectInfo_String(0, "RENDER_FORMAT", orig_rfmt, true)
  reaper.GetSetProjectInfo(0, "RENDER_ADDTOPROJ", orig_addtoproj, true)
  reaper.SNM_SetIntConfigVar("projrenderlimit", orig_speed)
  reaper.SNM_SetIntConfigVar("renderclosewhendone", orig_rclose)
  reaper.SetMediaTrackInfo_Value(track, "I_SOLO", orig_solo)

  -- Find the NEW rendered file (not in existing_files)
  local rendered_file = nil
  local fi = 0
  while true do
    local fn = reaper.EnumerateFiles(tmp_dir, fi)
    if not fn then break end
    if fn:match("^" .. tmp_filename) and fn:match("%.wav$") and not existing_files[fn] then
      rendered_file = tmp_dir .. sep .. fn
      break
    end
    fi = fi + 1
  end

  if not rendered_file then
    if existing_rcbit and rcbit_was_enabled then
      reaper.TrackFX_SetEnabled(track, existing_rcbit, true)
    end
    reaper.GetSet_LoopTimeRange(true, false, orig_ts_start, orig_ts_end, false)
    write_result("ERROR: Render failed — no NEW temp WAV found in " .. tmp_dir)
    reaper.Undo_EndBlock("RCBit Env Limiter V1 - failed", -1)
    return
  end

  -- ============ SCAN PEAKS ON RENDERED FILE ============
  local n_tracks = reaper.CountTracks(0)
  reaper.InsertTrackAtIndex(n_tracks, false)
  local temp_track = reaper.GetTrack(0, n_tracks)
  reaper.SetOnlyTrackSelected(temp_track)
  reaper.SetEditCurPos(0, false, false)
  reaper.InsertMedia(rendered_file, 0)

  local n_temp_items = reaper.CountTrackMediaItems(temp_track)
  if n_temp_items == 0 then
    reaper.DeleteTrack(temp_track)
    if existing_rcbit and rcbit_was_enabled then
      reaper.TrackFX_SetEnabled(track, existing_rcbit, true)
    end
    reaper.GetSet_LoopTimeRange(true, false, orig_ts_start, orig_ts_end, false)
    write_result("ERROR: Failed to import rendered file")
    reaper.Undo_EndBlock("RCBit Env Limiter V1 - failed", -1)
    return
  end

  local temp_item = reaper.GetTrackMediaItem(temp_track, 0)
  local temp_take = reaper.GetActiveTake(temp_item)
  local temp_source = reaper.GetMediaItemTake_Source(temp_take)
  local temp_sr = reaper.GetMediaSourceSampleRate(temp_source)
  if temp_sr == 0 then temp_sr = sr end
  local temp_num_ch = reaper.GetMediaSourceNumChannels(temp_source)
  if temp_num_ch == 0 then temp_num_ch = num_ch end

  local windows = {}
  local accessor = reaper.CreateTakeAudioAccessor(temp_take)
  local samples_per_win = math.max(math.floor(temp_sr * WINDOW_SEC), 1)
  local buf_size = samples_per_win * temp_num_ch
  local t = 0
  local t_end_render = item_len

  while t < t_end_render do
    local buf = reaper.new_array(buf_size)
    buf.clear()
    local win_samples = math.min(samples_per_win, math.floor((t_end_render - t) * temp_sr))
    if win_samples <= 0 then break end
    reaper.GetAudioAccessorSamples(accessor, temp_sr, temp_num_ch, t, win_samples, buf)
    local peak = 0
    for i_s = 1, win_samples * temp_num_ch do
      local s = math.abs(buf[i_s])
      if s > peak then peak = s end
    end
    local proj_time = item_pos + t
    local peak_db = -math.huge
    if peak > 0 then peak_db = 20 * math.log(peak, 10) end
    local is_peak = (peak_db > CEILING_DB + PEAK_MARGIN_DB)
    table.insert(windows, {
      time = proj_time, is_peak = is_peak,
      peak_gain_db = CEILING_DB - peak_db  -- negative = reduction needed
    })
    t = t + WINDOW_SEC
  end

  reaper.DestroyAudioAccessor(accessor)
  reaper.DeleteTrack(temp_track)
  reaper.SetOnlyTrackSelected(track)

  -- Restore time selection
  reaper.GetSet_LoopTimeRange(true, false, orig_ts_start, orig_ts_end, false)

  -- Restore item selection
  reaper.SelectAllMediaItems(0, false)
  reaper.SetMediaItemSelected(item, true)

  -- ============ CHECK FOR PEAKS ============
  local peak_count = 0
  for _, w in ipairs(windows) do
    if w.is_peak then peak_count = peak_count + 1 end
  end

  -- Find max peak across all windows for debug
  local max_peak_db = -math.huge
  for _, w in ipairs(windows) do
    if w.peak_gain_db ~= nil then
      local pdb = CEILING_DB - w.peak_gain_db  -- reconstruct peak_db
      if pdb > max_peak_db then max_peak_db = pdb end
    end
  end

  if peak_count == 0 then
    if existing_rcbit and rcbit_was_enabled then
      reaper.TrackFX_SetEnabled(track, existing_rcbit, true)
    end
    write_result(string.format(
      "OK\nCH: %d | SR: %d\nNo peaks exceeding %.1f dB found.\nCeiling: %.1f dB | Attack: %dms | Release: %dms | Window: %dms\n"
      .. "Max peak: %.2f dB | Windows: %d\nRendered: %s",
      num_ch, sr, CEILING_DB, CEILING_DB,
      ATTACK_SEC * 1000, RELEASE_SEC * 1000, WINDOW_SEC * 1000,
      max_peak_db, #windows, rendered_file))
    reaper.Undo_EndBlock("RCBit Env Limiter V1 - no peaks", -1)
    return
  end

  -- ============ BUILD REGIONS ============
  -- Step 1: Merge consecutive windows of same type
  local regions = {}
  local cur = {
    s = windows[1].time, e = windows[1].time + WINDOW_SEC,
    is_peak = windows[1].is_peak, min_gain = windows[1].peak_gain_db
  }
  for i = 2, #windows do
    local w = windows[i]
    if w.is_peak == cur.is_peak then
      cur.e = w.time + WINDOW_SEC
      if w.is_peak and w.peak_gain_db < cur.min_gain then
        cur.min_gain = w.peak_gain_db
      end
    else
      table.insert(regions, cur)
      cur = {s = w.time, e = w.time + WINDOW_SEC, is_peak = w.is_peak, min_gain = w.peak_gain_db}
    end
  end
  table.insert(regions, cur)

  -- Step 2: Attack/release extension on peak regions
  for i, reg in ipairs(regions) do
    if reg.is_peak then
      local new_s = math.max(reg.s - ATTACK_SEC, item_pos)
      local new_e = math.min(reg.e + RELEASE_SEC, item_end)
      if i > 1 and not regions[i - 1].is_peak and regions[i - 1].e > new_s then
        regions[i - 1].e = new_s
      end
      if i < #regions and not regions[i + 1].is_peak and regions[i + 1].s < new_e then
        regions[i + 1].s = new_e
      end
      reg.s = new_s
      reg.e = new_e
    end
  end

  -- Step 3: Remove zero-length regions
  local valid = {}
  for _, reg in ipairs(regions) do
    if reg.e - reg.s > 0.001 then table.insert(valid, reg) end
  end
  regions = valid

  -- Step 4: Merge adjacent peak regions
  local mp = {regions[1]}
  for i = 2, #regions do
    local prev = mp[#mp]
    local curr = regions[i]
    if prev.is_peak and curr.is_peak and curr.s <= prev.e + 0.001 then
      prev.e = math.max(prev.e, curr.e)
      if curr.min_gain < prev.min_gain then prev.min_gain = curr.min_gain end
    else
      table.insert(mp, curr)
    end
  end
  regions = mp

  -- Step 5: Absorb tiny regions (<20ms)
  local function absorb(regs)
    local changed = true
    while changed do
      changed = false
      local nr = {}
      for i, reg in ipairs(regs) do
        local d = reg.e - reg.s
        if d < MIN_REGION_SEC and #nr > 0 then
          nr[#nr].e = reg.e; changed = true
        elseif d < MIN_REGION_SEC and #nr == 0 and i < #regs then
          regs[i + 1].s = reg.s; changed = true
        else
          table.insert(nr, reg)
        end
      end
      regs = nr
    end
    return regs
  end
  regions = absorb(regions)

  -- Step 6: Assign gains (peak = reduction, clean = 0 passthrough)
  for _, reg in ipairs(regions) do
    reg.gain_db = reg.is_peak and reg.min_gain or 0
  end

  -- Step 7: Merge regions with identical RCBit params
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

  -- ============ ADD/RE-ENABLE RCBIT ON TRACK INSERT ============
  local fx_idx = existing_rcbit
  if fx_idx then
    reaper.TrackFX_SetEnabled(track, fx_idx, true)
    reaper.TrackFX_SetParam(track, fx_idx, 0, 0)  -- Macro=0
    reaper.TrackFX_SetParam(track, fx_idx, 1, 0)  -- Micro=0
    reaper.TrackFX_SetParam(track, fx_idx, 2, 0)  -- BR=0
  else
    fx_idx = reaper.TrackFX_AddByName(track, "JS:RCBitRangeGain", false, -1)
    if fx_idx < 0 then
      write_result("ERROR: Could not add RCBitRangeGain to track")
      reaper.Undo_EndBlock("RCBit Env Limiter V1 - failed", -1)
      return
    end
    reaper.TrackFX_SetParam(track, fx_idx, 0, 0)
    reaper.TrackFX_SetParam(track, fx_idx, 1, 0)
    reaper.TrackFX_SetParam(track, fx_idx, 2, 0)
  end

  -- ============ WRITE ENVELOPES ============
  local macro_env = reaper.GetFXEnvelope(track, fx_idx, 0, true)  -- Macro param
  local br_env = reaper.GetFXEnvelope(track, fx_idx, 2, true)     -- BR param

  local macro_count = write_env_points(macro_env, regions, function(reg)
    local m, _ = calc_rcbit_params(reg.gain_db, reg.is_peak)
    return macro_to_norm(m or 0)
  end, item_pos, item_end)

  local br_count = write_env_points(br_env, regions, function(reg)
    local _, br = calc_rcbit_params(reg.gain_db, reg.is_peak)
    return br_to_norm(br or 0)
  end, item_pos, item_end)

  -- Set track automation mode to READ so envelopes control FX params
  reaper.SetTrackAutomationMode(track, 1)  -- 0=trim, 1=read, 2=touch, 3=write, 4=latch

  -- ============ RESULTS ============
  local peak_regions = 0
  local clean_regions = 0
  for _, reg in ipairs(regions) do
    if reg.is_peak then peak_regions = peak_regions + 1
    else clean_regions = clean_regions + 1 end
  end

  local result = string.format(
    "OK\nCH: %d | SR: %d\nCeiling: %.1f dB | Attack: %dms | Release: %dms | Window: %dms\n"
    .. "Windows: %d (%d peak)\nRegions: %d (%d peak, %d clean)\n"
    .. "Envelope points: %d Macro, %d BR\nRendered: %s\n---",
    num_ch, sr, CEILING_DB,
    ATTACK_SEC * 1000, RELEASE_SEC * 1000, WINDOW_SEC * 1000,
    #windows, peak_count,
    #regions, peak_regions, clean_regions,
    macro_count, br_count,
    rendered_file)

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

  reaper.UpdateArrange()
  reaper.Undo_EndBlock("RCBit Envelope Limiter V1.0", -1)
end)
