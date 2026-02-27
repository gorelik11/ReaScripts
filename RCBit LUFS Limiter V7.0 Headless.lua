-- RCBit LUFS Limiter V7.0 Headless
-- No dialogs — reads params from ~/rcbit_v7_params.txt, writes results to ~/rcbit_v7_results.txt
-- For iterative testing via reapy
--
-- V7 improvements over V6:
--   - Fixed RENDER_SETTINGS: 3 (stems selected tracks) instead of 32
--   - Full-speed offline render via projrenderlimit=0
--   - Auto-close render dialog via renderclosewhendone=17
--   - RENDER_ADDTOPROJ=0 to prevent duplicate track creation
--   - All render config saved/restored cleanly
--   - Respects user crossfade settings (no longer removes auto-crossfades)

local BIT_DB = 6.0206
local MIN_GAIN_DB = 0.15
local PEAK_MARGIN_DB = 0.0
local MIN_REGION_SEC = 0.02
local BR_STEP = 0.05

local params_file = os.getenv("HOME") .. "/rcbit_v7_params.txt"
local results_file = os.getenv("HOME") .. "/rcbit_v7_results.txt"

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

local TARGET_LUFS = tonumber(params.TARGET_LUFS) or -24
local CEILING_DB = tonumber(params.CEILING_DB) or -0.5
local ATTACK_SEC = (tonumber(params.ATTACK_MS) or 0) / 1000
local RELEASE_SEC = (tonumber(params.RELEASE_MS) or 70) / 1000
local WINDOW_SEC = (tonumber(params.WINDOW_MS) or 5) / 1000
local PEAK_SOURCE = params.PEAK_SOURCE or "SWS"

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

reaper.Undo_BeginBlock()
reaper.PreventUIRefresh(1)

local item = reaper.GetSelectedMediaItem(0, 0)
if not item then
  write_result("ERROR: No selected item")
  reaper.PreventUIRefresh(-1)
  reaper.Undo_EndBlock("RCBit V7 Headless - failed", -1)
  return
end

local take = reaper.GetActiveTake(item)
if not take or reaper.TakeIsMIDI(take) then
  write_result("ERROR: Not audio item")
  reaper.PreventUIRefresh(-1)
  reaper.Undo_EndBlock("RCBit V7 Headless - failed", -1)
  return
end

local source = reaper.GetMediaItemTake_Source(take)
local num_ch = reaper.GetMediaSourceNumChannels(source)
local sr = reaper.GetMediaSourceSampleRate(source)
local is_mono = (num_ch == 1)

if sr == 0 then
  local parent = reaper.GetMediaSourceParent(source)
  if parent then sr = reaper.GetMediaSourceSampleRate(parent) end
end
if sr == 0 then sr = reaper.GetSetProjectInfo(0, "PROJECT_SRATE", 0, false) end
if sr == 0 then sr = 44100 end

local item_pos = reaper.GetMediaItemInfo_Value(item, "D_POSITION")
local item_len = reaper.GetMediaItemInfo_Value(item, "D_LENGTH")
local item_end = item_pos + item_len
local track = reaper.GetMediaItem_Track(item)
local take_offset = reaper.GetMediaItemTakeInfo_Value(take, "D_STARTOFFS")
local take_rate = reaper.GetMediaItemTakeInfo_Value(take, "D_PLAYRATE")

local orig_ts_start, orig_ts_end = reaper.GetSet_LoopTimeRange(false, false, 0, 0, false)

-- LUFS via SWS (always)
local lufs_ok, lufs_integrated = reaper.NF_AnalyzeTakeLoudness(take, false)
if not lufs_ok or not lufs_integrated or lufs_integrated <= -200 then
  write_result("ERROR: LUFS analysis failed")
  reaper.PreventUIRefresh(-1)
  reaper.Undo_EndBlock("RCBit V7 Headless - failed", -1)
  return
end

local current_lufs = lufs_integrated
if is_mono then
  local pan_law = reaper.GetSetProjectInfo(0, "PROJECT_PANLAW", 0, false)
  if pan_law == 0 then pan_law = 3 end
  current_lufs = lufs_integrated - pan_law
end

local lufs_gain_db = TARGET_LUFS - current_lufs

if math.abs(lufs_gain_db) < MIN_GAIN_DB then
  write_result(string.format("OK\nAlready at target LUFS (%.1f)", current_lufs))
  reaper.PreventUIRefresh(-1)
  reaper.Undo_EndBlock("RCBit V7 Headless - no changes", -1)
  return
end

-- Peak analysis
local windows = {}

if PEAK_SOURCE == "SWS" then
  local accessor = reaper.CreateTakeAudioAccessor(take)
  local samples_per_win = math.max(math.floor(sr * WINDOW_SEC), 1)
  local buf_size = samples_per_win * num_ch
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
    local is_peak = (peak_after_gain > CEILING_DB + PEAK_MARGIN_DB)
    table.insert(windows, {
      time = proj_time, is_peak = is_peak,
      peak_gain_db = CEILING_DB - peak_db
    })
    t = t + WINDOW_SEC
  end
  reaper.DestroyAudioAccessor(accessor)

elseif PEAK_SOURCE == "Render" then
  local proj_path = reaper.GetProjectPath()
  local sep = package.config:sub(1,1)
  local tmp_dir = proj_path .. sep .. "tmp"
  reaper.RecursiveCreateDirectory(tmp_dir, 0)

  local tmp_filename = "_RCBIT_V7_PEAK_ANALYSIS"

  -- Save ALL render settings (from Archie's Render Template pattern)
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
  reaper.GetSetProjectInfo_String(0, "RENDER_FORMAT", "ZXZhdwgA", true)  -- WAV 32-bit float
  reaper.GetSetProjectInfo(0, "RENDER_ADDTOPROJ", 0, true)    -- don't auto-add to project
  reaper.SNM_SetIntConfigVar("projrenderlimit", 0)            -- full-speed offline
  reaper.SNM_SetIntConfigVar("renderclosewhendone", 17)       -- auto-close + silent increment

  reaper.Main_OnCommand(42230, 0)  -- render with last settings, auto-close

  -- Restore ALL render settings
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
  reaper.GetSet_LoopTimeRange(true, false, orig_ts_start, orig_ts_end, false)

  -- Find rendered file
  local rendered_file = nil
  local i = 0
  while true do
    local fn = reaper.EnumerateFiles(tmp_dir, i)
    if not fn then break end
    if fn:match("^" .. tmp_filename) and fn:match("%.wav$") then
      rendered_file = tmp_dir .. sep .. fn
      break
    end
    i = i + 1
  end

  if not rendered_file then
    write_result("ERROR: Render failed — temp WAV not found in " .. tmp_dir)
    reaper.PreventUIRefresh(-1)
    reaper.Undo_EndBlock("RCBit V7 Headless - failed", -1)
    return
  end

  -- Import to temp track for peak scanning
  local n_tracks = reaper.CountTracks(0)
  reaper.InsertTrackAtIndex(n_tracks, false)
  local temp_track = reaper.GetTrack(0, n_tracks)
  reaper.SetOnlyTrackSelected(temp_track)
  reaper.SetEditCurPos(0, false, false)
  reaper.InsertMedia(rendered_file, 0)

  local n_temp_items = reaper.CountTrackMediaItems(temp_track)
  if n_temp_items == 0 then
    reaper.DeleteTrack(temp_track)
    reaper.SetOnlyTrackSelected(track)
    write_result("ERROR: Failed to import rendered file")
    reaper.PreventUIRefresh(-1)
    reaper.Undo_EndBlock("RCBit V7 Headless - failed", -1)
    return
  end

  local temp_item = reaper.GetTrackMediaItem(temp_track, 0)
  local temp_take = reaper.GetActiveTake(temp_item)
  local temp_source = reaper.GetMediaItemTake_Source(temp_take)
  local temp_sr = reaper.GetMediaSourceSampleRate(temp_source)
  if temp_sr == 0 then temp_sr = sr end
  local temp_num_ch = reaper.GetMediaSourceNumChannels(temp_source)
  if temp_num_ch == 0 then temp_num_ch = num_ch end

  -- Scan peaks on rendered (clean, post-FX) file
  local accessor = reaper.CreateTakeAudioAccessor(temp_take)
  local samples_per_win = math.max(math.floor(temp_sr * WINDOW_SEC), 1)
  local buf_size = samples_per_win * temp_num_ch
  local t = 0
  local t_end_render = item_len

  while t < t_end_render do
    local buf = reaper.new_array(buf_size)
    buf.clear()
    local win_samples = math.min(samples_per_win, math.floor((t_end_render - t) * temp_sr))
    reaper.GetAudioAccessorSamples(accessor, temp_sr, temp_num_ch, t, win_samples, buf)
    local peak = 0
    for i_s = 1, win_samples * temp_num_ch do
      local s = math.abs(buf[i_s])
      if s > peak then peak = s end
    end
    local proj_time = item_pos + t
    local peak_db = -math.huge
    if peak > 0 then peak_db = 20 * math.log(peak, 10) end
    local peak_after_gain = peak_db + lufs_gain_db
    local is_peak = (peak_after_gain > CEILING_DB + PEAK_MARGIN_DB)
    table.insert(windows, {
      time = proj_time, is_peak = is_peak,
      peak_gain_db = CEILING_DB - peak_db
    })
    t = t + WINDOW_SEC
  end

  reaper.DestroyAudioAccessor(accessor)
  reaper.DeleteTrack(temp_track)
  reaper.SetOnlyTrackSelected(track)
end

reaper.GetSet_LoopTimeRange(true, false, orig_ts_start, orig_ts_end, false)

-- Count peaks
local peak_win_count = 0
for _, w in ipairs(windows) do
  if w.is_peak then peak_win_count = peak_win_count + 1 end
end

-- No peaks case
if peak_win_count == 0 then
  local macro, bit_ratio = calc_rcbit_params(lufs_gain_db, false)
  if macro then
    local fx_idx = reaper.TakeFX_AddByName(take, "JS:RCBitRangeGain", -1)
    if fx_idx >= 0 then
      reaper.TakeFX_SetParam(take, fx_idx, 0, macro)
      reaper.TakeFX_SetParam(take, fx_idx, 1, 0)
      reaper.TakeFX_SetParam(take, fx_idx, 2, bit_ratio)
    end
  end
  local eff = macro and (macro * bit_ratio * BIT_DB) or 0
  reaper.PreventUIRefresh(-1)
  reaper.UpdateArrange()
  write_result(string.format(
    "OK\nNo peaks exceed ceiling\n"
    .. "Peak Source: %s | CH: %d | SR: %d\n"
    .. "LUFS: %.1f → %.1f (gain: %+.2f, eff: %+.2f)\n"
    .. "Ceiling: %.1f | Macro: %d | BR: %.2f",
    PEAK_SOURCE, num_ch, sr,
    current_lufs, TARGET_LUFS, lufs_gain_db, eff,
    CEILING_DB, macro or 0, bit_ratio or 0))
  reaper.Undo_EndBlock("RCBit LUFS Limiter V7.0", -1)
  return
end

-- Build regions
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
    cur = { s = w.time, e = w.time + WINDOW_SEC,
            is_peak = w.is_peak, min_gain = w.peak_gain_db }
  end
end
table.insert(regions, cur)

-- Attack/release
for i, reg in ipairs(regions) do
  if reg.is_peak then
    local new_s = math.max(reg.s - ATTACK_SEC, item_pos)
    local new_e = math.min(reg.e + RELEASE_SEC, item_end)
    if i > 1 and not regions[i-1].is_peak and regions[i-1].e > new_s then
      regions[i-1].e = new_s
    end
    if i < #regions and not regions[i+1].is_peak and regions[i+1].s < new_e then
      regions[i+1].s = new_e
    end
    reg.s = new_s
    reg.e = new_e
  end
end

-- Remove zero-length
local valid = {}
for _, reg in ipairs(regions) do
  if reg.e - reg.s > 0.001 then table.insert(valid, reg) end
end
regions = valid

-- Merge adjacent peaks
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

-- Absorb tiny
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
        regs[i+1].s = reg.s; changed = true
      else
        table.insert(nr, reg)
      end
    end
    regs = nr
  end
  return regs
end
regions = absorb(regions)

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
  else
    table.insert(mg, curr)
  end
end
regions = mg

-- Split points
local split_points = {}
for i = 2, #regions do
  local sp = regions[i].s
  if sp > item_pos + 0.001 and sp < item_end - 0.001 then
    table.insert(split_points, sp)
  end
end
table.sort(split_points, function(a, b) return a > b end)

local unique = {}
for _, sp in ipairs(split_points) do
  if #unique == 0 or math.abs(sp - unique[#unique]) > 0.001 then
    table.insert(unique, sp)
  end
end
split_points = unique

-- Split
for _, sp in ipairs(split_points) do
  reaper.SplitMediaItem(item, sp)
end

-- Apply FX
local fx_count, skip_count, clean_count = 0, 0, 0
local num_items = reaper.CountTrackMediaItems(track)

for i = 0, num_items - 1 do
  local it = reaper.GetTrackMediaItem(track, i)
  local it_pos = reaper.GetMediaItemInfo_Value(it, "D_POSITION")
  local it_len = reaper.GetMediaItemInfo_Value(it, "D_LENGTH")
  if it_pos >= item_pos - 0.001 and it_pos + it_len <= item_end + 0.001 then
    local it_mid = it_pos + it_len / 2
    local gain, is_peak_item = lufs_gain_db, false
    for _, reg in ipairs(regions) do
      if it_mid >= reg.s - 0.001 and it_mid <= reg.e + 0.001 then
        gain = reg.gain_db; is_peak_item = reg.is_peak; break
      end
    end
    local macro, bit_ratio = calc_rcbit_params(gain, is_peak_item)
    if macro then
      local tk = reaper.GetActiveTake(it)
      if tk then
        local fx_idx = reaper.TakeFX_AddByName(tk, "JS:RCBitRangeGain", -1)
        if fx_idx >= 0 then
          reaper.TakeFX_SetParam(tk, fx_idx, 0, macro)
          reaper.TakeFX_SetParam(tk, fx_idx, 1, 0)
          reaper.TakeFX_SetParam(tk, fx_idx, 2, bit_ratio)
          fx_count = fx_count + 1
        end
      end
    else
      skip_count = skip_count + 1
      clean_count = clean_count + 1
    end
  end
end

reaper.PreventUIRefresh(-1)
reaper.UpdateArrange()

local lufs_m, lufs_br = calc_rcbit_params(lufs_gain_db, false)
local lufs_eff = lufs_m and (lufs_m * lufs_br * BIT_DB) or 0
local peak_r, boost_r = 0, 0
for _, r in ipairs(regions) do
  if r.is_peak then peak_r = peak_r + 1 else boost_r = boost_r + 1 end
end

-- Build detailed region log
local region_log = {}
for i, r in ipairs(regions) do
  local m, br = calc_rcbit_params(r.gain_db, r.is_peak)
  local eff = m and (math.abs(m) * br * BIT_DB) or 0
  if m and m < 0 then eff = -eff end
  table.insert(region_log, string.format(
    "  R%d: %.3f-%.3f %s gain=%.2f M=%d BR=%.2f eff=%+.2f",
    i, r.s, r.e, r.is_peak and "PEAK" or "BOOST",
    r.gain_db, m or 0, br or 0, eff))
end

write_result(string.format(
  "OK\n"
  .. "Peak Source: %s | CH: %d | SR: %d\n"
  .. "LUFS: %.1f → %.1f (gain: %+.2f, eff: %+.2f)\n"
  .. "Ceiling: %.1f | Attack: %dms | Release: %dms | Window: %dms\n"
  .. "Windows: %d (%d peak)\n"
  .. "Regions: %d (%d peak, %d boost)\n"
  .. "Splits: %d | FX: %d | Skip: %d | Clean: %d\n"
  .. "---\n%s",
  PEAK_SOURCE, num_ch, sr,
  current_lufs, TARGET_LUFS, lufs_gain_db, lufs_eff,
  CEILING_DB, ATTACK_SEC*1000, RELEASE_SEC*1000, WINDOW_SEC*1000,
  #windows, peak_win_count,
  #regions, peak_r, boost_r,
  #split_points, fx_count, skip_count, clean_count,
  table.concat(region_log, "\n")))

reaper.Undo_EndBlock("RCBit LUFS Limiter V7.0", -1)
