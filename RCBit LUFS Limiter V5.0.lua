-- RCBit LUFS Limiter V5.0
-- Combined LUFS gain staging + peak limiting using RCBitRangeGain
-- Dual-instance architecture: separate RCBit for LUFS and limiting
--
-- V5 new features over V4:
--   - Dual-instance (Micro) mode: Instance 1 for LUFS, Instance 2 for limiting
--   - Combined mode: single RCBit per split (like V4)
--   - Track scope: process all items on a track
--   - Item scope: process selected item only (like V4)
--   - MonoRun/StereoRun LUFS measurement via render (captures post-FX loudness)
--   - SWS LUFS measurement (direct take analysis, like V4)
--   - LUFS=0 for pure peak limiting (no LUFS gain)
--
-- Author: Dima Gorelik
-- Co-developed with Claude (Anthropic)
-- License: MIT
--
-- Requires: JS:RCBitRangeGain JSFX plugin by RCJacH
-- Requires: SWS extension (for NF_AnalyzeTakeLoudness)

local BIT_DB = 6.0206
local MIN_GAIN_DB = 0.15
local PEAK_MARGIN_DB = 0.0
local MIN_REGION_SEC = 0.02  -- 20ms
local BR_STEP = 0.05         -- JSFX slider step

-- calc_rcbit_params: calculate Macro and Bit Ratio for a given gain
-- floor_br: if true, quantize BR DOWN to BR_STEP (prevents peaks exceeding ceiling)
--           if false, quantize BR to nearest BR_STEP
local function calc_rcbit_params(gain_db, floor_br)
  if math.abs(gain_db) < MIN_GAIN_DB then
    return nil, nil
  end
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
  if effective_gain < MIN_GAIN_DB then
    return nil, nil
  end

  return macro, bit_ratio
end

-- SR fallback chain
local function get_sr(source)
  local sr = reaper.GetMediaSourceSampleRate(source)
  if sr == 0 then
    local parent = reaper.GetMediaSourceParent(source)
    if parent then sr = reaper.GetMediaSourceSampleRate(parent) end
  end
  if sr == 0 then
    sr = reaper.GetSetProjectInfo(0, "PROJECT_SRATE", 0, false)
  end
  if sr == 0 then sr = 44100 end
  return sr
end

-- LUFS measurement: SWS method
local function measure_lufs_sws(take)
  local lufs_ok, lufs_integrated = reaper.NF_AnalyzeTakeLoudness(take, true)
  if not lufs_ok or lufs_integrated == nil or lufs_integrated <= -200 then
    return nil
  end
  local source = reaper.GetMediaItemTake_Source(take)
  local num_ch = reaper.GetMediaSourceNumChannels(source)
  if num_ch == 1 then
    local pan_law = reaper.GetSetProjectInfo(0, "PROJECT_PANLAW", 0, false)
    if pan_law == 0 then pan_law = 3 end
    return lufs_integrated - pan_law
  end
  return lufs_integrated
end

-- LUFS measurement: Render method (MonoRun or StereoRun)
local function measure_lufs_render(track, start_time, end_time, mono)
  -- Save time selection
  local ts_start, ts_end = reaper.GetSet_LoopTimeRange(false, false, 0, 0, false)
  local track_count_before = reaper.CountTracks(0)

  -- Save solo states
  local solo_states = {}
  for i = 0, track_count_before - 1 do
    local tr = reaper.GetTrack(0, i)
    solo_states[i] = reaper.GetMediaTrackInfo_Value(tr, "I_SOLO")
    reaper.SetMediaTrackInfo_Value(tr, "I_SOLO", 0)
  end

  -- Solo target track, set time selection, select track
  reaper.SetMediaTrackInfo_Value(track, "I_SOLO", 2) -- solo in place
  reaper.GetSet_LoopTimeRange(true, false, start_time, end_time, false)
  reaper.SetOnlyTrackSelected(track)

  -- Render to stem
  local action = mono and 41716 or 41720
  reaper.Main_OnCommand(action, 0)

  -- Find new track
  local new_count = reaper.CountTracks(0)
  local lufs = nil
  if new_count > track_count_before then
    local stem_track = reaper.GetTrack(0, new_count - 1)
    local stem_item = reaper.GetTrackMediaItem(stem_track, 0)
    if stem_item then
      local stem_take = reaper.GetActiveTake(stem_item)
      if stem_take then
        local ok, integrated = reaper.NF_AnalyzeTakeLoudness(stem_take, true)
        if ok and integrated and integrated > -200 then
          lufs = integrated
        end
      end
    end
    reaper.DeleteTrack(stem_track)
  end

  -- Restore solo states
  for i = 0, math.min(reaper.CountTracks(0) - 1, track_count_before - 1) do
    local tr = reaper.GetTrack(0, i)
    if tr then
      reaper.SetMediaTrackInfo_Value(tr, "I_SOLO", solo_states[i] or 0)
    end
  end

  -- Restore time selection
  reaper.GetSet_LoopTimeRange(true, false, ts_start, ts_end, false)

  return lufs
end

-- Absorb tiny regions into neighbors
local function absorb_tiny_regions(regs)
  local changed = true
  while changed do
    changed = false
    local new_regs = {}
    for i, reg in ipairs(regs) do
      local duration = reg.e - reg.s
      if duration < MIN_REGION_SEC and #new_regs > 0 then
        new_regs[#new_regs].e = reg.e
        changed = true
      elseif duration < MIN_REGION_SEC and #new_regs == 0 and i < #regs then
        regs[i + 1].s = reg.s
        changed = true
      else
        table.insert(new_regs, reg)
      end
    end
    regs = new_regs
  end
  return regs
end

-- Process a single item through the full pipeline
local function process_item(item, track, lufs_gain_db, ceiling_db,
                            attack_sec, release_sec, window_sec,
                            limiter_mode)
  local take = reaper.GetActiveTake(item)
  if not take or reaper.TakeIsMIDI(take) then return nil end

  local source = reaper.GetMediaItemTake_Source(take)
  local num_ch = reaper.GetMediaSourceNumChannels(source)
  local sr = get_sr(source)

  local item_pos = reaper.GetMediaItemInfo_Value(item, "D_POSITION")
  local item_len = reaper.GetMediaItemInfo_Value(item, "D_LENGTH")
  local item_end = item_pos + item_len
  local take_offset = reaper.GetMediaItemTakeInfo_Value(take, "D_STARTOFFS")
  local take_rate = reaper.GetMediaItemTakeInfo_Value(take, "D_PLAYRATE")

  -- Peak analysis: binary classification
  local accessor = reaper.CreateTakeAudioAccessor(take)
  local samples_per_win = math.max(math.floor(sr * window_sec), 1)
  local buf_size = samples_per_win * num_ch
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
    local is_peak = (peak_after_gain > ceiling_db + PEAK_MARGIN_DB)
    table.insert(windows, {
      time = proj_time,
      is_peak = is_peak,
      peak_gain_db = ceiling_db - peak_db
    })
    t = t + window_sec
  end
  reaper.DestroyAudioAccessor(accessor)

  -- Count peaks
  local peak_win_count = 0
  for _, w in ipairs(windows) do
    if w.is_peak then peak_win_count = peak_win_count + 1 end
  end

  -- No peaks: apply uniform LUFS gain
  if peak_win_count == 0 then
    if math.abs(lufs_gain_db) >= MIN_GAIN_DB then
      local macro, br = calc_rcbit_params(lufs_gain_db, false)
      if macro then
        local fx_idx = reaper.TakeFX_AddByName(take, "JS:RCBitRangeGain", -1)
        if fx_idx >= 0 then
          reaper.TakeFX_SetParam(take, fx_idx, 0, macro)
          reaper.TakeFX_SetParam(take, fx_idx, 1, 0)
          reaper.TakeFX_SetParam(take, fx_idx, 2, br)
        end
      end
    end
    return {splits = 0, fx_count = (math.abs(lufs_gain_db) >= MIN_GAIN_DB) and 1 or 0,
            skip_count = 0, peak_wins = 0, region_count = 1, peak_regions = 0, micro_br = 1}
  end

  if #windows == 0 then return nil end

  -- Build regions: merge consecutive windows of same type
  local regions = {}
  local cur = {
    s = windows[1].time,
    e = windows[1].time + window_sec,
    is_peak = windows[1].is_peak,
    min_gain = windows[1].peak_gain_db
  }
  for i = 2, #windows do
    local w = windows[i]
    if w.is_peak == cur.is_peak then
      cur.e = w.time + window_sec
      if w.is_peak and w.peak_gain_db < cur.min_gain then
        cur.min_gain = w.peak_gain_db
      end
    else
      table.insert(regions, cur)
      cur = {
        s = w.time, e = w.time + window_sec,
        is_peak = w.is_peak, min_gain = w.peak_gain_db
      }
    end
  end
  table.insert(regions, cur)

  -- Attack/release expansion
  for i, reg in ipairs(regions) do
    if reg.is_peak then
      local new_s = math.max(reg.s - attack_sec, item_pos)
      local new_e = math.min(reg.e + release_sec, item_end)
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

  -- Remove zero/negative-length regions
  local valid = {}
  for _, r in ipairs(regions) do
    if r.e - r.s > 0.001 then table.insert(valid, r) end
  end
  regions = valid

  -- Merge adjacent peak regions
  local merged = {regions[1]}
  for i = 2, #regions do
    local prev = merged[#merged]
    local curr = regions[i]
    if prev.is_peak and curr.is_peak and curr.s <= prev.e + 0.001 then
      prev.e = math.max(prev.e, curr.e)
      if curr.min_gain < prev.min_gain then prev.min_gain = curr.min_gain end
    else
      table.insert(merged, curr)
    end
  end
  regions = merged

  -- Absorb tiny regions
  regions = absorb_tiny_regions(regions)

  -- Assign gains
  for _, reg in ipairs(regions) do
    if reg.is_peak then
      reg.gain_db = reg.min_gain  -- ceiling - peak_db
    else
      reg.gain_db = lufs_gain_db
    end
  end

  -- Merge adjacent regions (mode-dependent)
  if limiter_mode == "Combined" then
    local merged2 = {regions[1]}
    for i = 2, #regions do
      local prev = merged2[#merged2]
      local curr = regions[i]
      local prev_m, prev_br = calc_rcbit_params(prev.gain_db, prev.is_peak)
      local curr_m, curr_br = calc_rcbit_params(curr.gain_db, curr.is_peak)
      if prev_m == curr_m and prev_br ~= nil and curr_br ~= nil
        and math.abs(prev_br - curr_br) < 0.001 then
        prev.e = curr.e
      else
        table.insert(merged2, curr)
      end
    end
    regions = merged2
  else
    -- Micro mode: merge adjacent boost regions, merge adjacent peak with same gain
    local merged2 = {regions[1]}
    for i = 2, #regions do
      local prev = merged2[#merged2]
      local curr = regions[i]
      if not prev.is_peak and not curr.is_peak then
        prev.e = curr.e
      elseif prev.is_peak and curr.is_peak
        and math.abs(prev.min_gain - curr.min_gain) < 0.001 then
        prev.e = curr.e
      else
        table.insert(merged2, curr)
      end
    end
    regions = merged2
  end

  -- For Micro mode: compute micro_br from max correction
  local micro_br = 1
  if limiter_mode == "Micro" and lufs_gain_db ~= 0 then
    local max_correction = 0
    for _, reg in ipairs(regions) do
      if reg.is_peak then
        local correction = math.abs(reg.gain_db - lufs_gain_db)
        if correction > max_correction then max_correction = correction end
      end
    end
    if max_correction > 0 then
      micro_br = math.ceil(max_correction / BIT_DB)
      micro_br = math.min(micro_br, 3)
      if micro_br < 1 then micro_br = 1 end
    end
  end

  -- Collect split points
  local split_points = {}
  for i = 2, #regions do
    local pos = regions[i].s
    if pos > item_pos + 0.001 and pos < item_end - 0.001 then
      table.insert(split_points, pos)
    end
  end
  table.sort(split_points, function(a, b) return a > b end)

  -- Remove duplicates
  local unique = {}
  for _, pos in ipairs(split_points) do
    if #unique == 0 or math.abs(pos - unique[#unique]) > 0.001 then
      table.insert(unique, pos)
    end
  end
  split_points = unique

  -- Split from right to left
  for _, pos in ipairs(split_points) do
    reaper.SplitMediaItem(item, pos)
  end

  -- Apply FX to splits
  local fx_count = 0
  local skip_count = 0
  local num_items = reaper.CountTrackMediaItems(track)

  for i = 0, num_items - 1 do
    local it = reaper.GetTrackMediaItem(track, i)
    local it_pos = reaper.GetMediaItemInfo_Value(it, "D_POSITION")
    local it_len = reaper.GetMediaItemInfo_Value(it, "D_LENGTH")

    if it_pos >= item_pos - 0.001 and it_pos + it_len <= item_end + 0.001 then
      local it_mid = it_pos + it_len / 2
      local gain = lufs_gain_db
      local is_peak_item = false
      local reg_min_gain = 0

      for _, reg in ipairs(regions) do
        if it_mid >= reg.s - 0.001 and it_mid <= reg.e + 0.001 then
          gain = reg.gain_db
          is_peak_item = reg.is_peak
          reg_min_gain = reg.min_gain or reg.gain_db
          break
        end
      end

      local tk = reaper.GetActiveTake(it)
      if tk then
        if limiter_mode == "Combined" then
          local effective_gain
          if lufs_gain_db == 0 then
            effective_gain = is_peak_item and gain or 0
          else
            effective_gain = gain
          end

          local macro, br = calc_rcbit_params(effective_gain, is_peak_item)
          if macro then
            local fx_idx = reaper.TakeFX_AddByName(tk, "JS:RCBitRangeGain", -1)
            if fx_idx >= 0 then
              reaper.TakeFX_SetParam(tk, fx_idx, 0, macro)
              reaper.TakeFX_SetParam(tk, fx_idx, 1, 0)
              reaper.TakeFX_SetParam(tk, fx_idx, 2, br)
              fx_count = fx_count + 1
            end
          else
            skip_count = skip_count + 1
          end

        elseif limiter_mode == "Micro" then
          if lufs_gain_db == 0 then
            -- LUFS=0 + Micro: falls back to Combined behavior
            if is_peak_item then
              local macro, br = calc_rcbit_params(gain, true)
              if macro then
                local fx_idx = reaper.TakeFX_AddByName(tk, "JS:RCBitRangeGain", -1)
                if fx_idx >= 0 then
                  reaper.TakeFX_SetParam(tk, fx_idx, 0, macro)
                  reaper.TakeFX_SetParam(tk, fx_idx, 1, 0)
                  reaper.TakeFX_SetParam(tk, fx_idx, 2, br)
                  fx_count = fx_count + 1
                end
              else
                skip_count = skip_count + 1
              end
            end
          else
            -- Instance 1: LUFS gain on ALL splits
            local lufs_macro, lufs_br = calc_rcbit_params(lufs_gain_db, false)
            if lufs_macro then
              local fx_idx = reaper.TakeFX_AddByName(tk, "JS:RCBitRangeGain", -1)
              if fx_idx >= 0 then
                reaper.TakeFX_SetParam(tk, fx_idx, 0, lufs_macro)
                reaper.TakeFX_SetParam(tk, fx_idx, 1, 0)
                reaper.TakeFX_SetParam(tk, fx_idx, 2, lufs_br)
                fx_count = fx_count + 1
              end
            end

            -- Instance 2: Limiter correction on PEAK splits only
            if is_peak_item then
              local correction = reg_min_gain - lufs_gain_db  -- negative
              if math.abs(correction) >= MIN_GAIN_DB then
                local micro_val = correction / (micro_br * BIT_DB) * 100
                micro_val = math.max(-100, math.min(100, micro_val))
                micro_val = math.floor(micro_val)

                local fx_idx2 = reaper.TakeFX_AddByName(tk, "JS:RCBitRangeGain", -1)
                if fx_idx2 >= 0 then
                  reaper.TakeFX_SetParam(tk, fx_idx2, 0, 0)         -- Macro = 0
                  reaper.TakeFX_SetParam(tk, fx_idx2, 1, micro_val) -- Micro
                  reaper.TakeFX_SetParam(tk, fx_idx2, 2, micro_br)  -- BR
                  fx_count = fx_count + 1
                end
              end
            end
          end
        end
      end
    end
  end

  local peak_region_count = 0
  for _, r in ipairs(regions) do
    if r.is_peak then peak_region_count = peak_region_count + 1 end
  end

  return {
    splits = #split_points,
    fx_count = fx_count,
    skip_count = skip_count,
    peak_wins = peak_win_count,
    region_count = #regions,
    peak_regions = peak_region_count,
    micro_br = micro_br
  }
end

-- ===== DIALOG =====

local retval, user_input = reaper.GetUserInputs(
  "RCBit LUFS Limiter V5.0", 8,
  "Target LUFS (0=limit only):,"
  .. "Peak Ceiling (dB):,"
  .. "Attack (ms):,"
  .. "Release (ms):,"
  .. "Analysis Window (ms):,"
  .. "Scope (Item/Track):,"
  .. "Limiter (Combined/Micro):,"
  .. "LUFS Source (SWS/MonoRun/StereoRun):,"
  .. "extrawidth=120",
  "-14,-0.5,0,70,5,Item,Combined,SWS"
)
if not retval then return end

local vals = {}
for v in user_input:gmatch("([^,]+)") do table.insert(vals, v) end

local TARGET_LUFS = tonumber(vals[1])
local CEILING_DB = tonumber(vals[2])
local ATTACK_SEC = tonumber(vals[3]) / 1000
local RELEASE_SEC = tonumber(vals[4]) / 1000
local WINDOW_SEC = tonumber(vals[5]) / 1000
local SCOPE = vals[6] or "Item"
local LIMITER_MODE = vals[7] or "Combined"
local LUFS_SOURCE = vals[8] or "SWS"

if not TARGET_LUFS or not CEILING_DB or not ATTACK_SEC or not RELEASE_SEC or not WINDOW_SEC then
  reaper.ShowMessageBox("Invalid input. Please enter numeric values.", "Error", 0)
  return
end

-- Validate string params
SCOPE = (SCOPE == "Track") and "Track" or "Item"
LIMITER_MODE = (LIMITER_MODE == "Micro") and "Micro" or "Combined"
if LUFS_SOURCE ~= "MonoRun" and LUFS_SOURCE ~= "StereoRun" then
  LUFS_SOURCE = "SWS"
end

-- ===== MAIN =====

reaper.Undo_BeginBlock()
reaper.PreventUIRefresh(1)

local item = reaper.GetSelectedMediaItem(0, 0)
if not item then
  reaper.PreventUIRefresh(-1)
  reaper.ShowMessageBox("Please select a media item.", "Error", 0)
  reaper.Undo_EndBlock("RCBit LUFS Limiter V5 - no item", -1)
  return
end

local take = reaper.GetActiveTake(item)
if not take or reaper.TakeIsMIDI(take) then
  reaper.PreventUIRefresh(-1)
  reaper.ShowMessageBox("Selected item must be audio.", "Error", 0)
  reaper.Undo_EndBlock("RCBit LUFS Limiter V5 - not audio", -1)
  return
end

local track = reaper.GetMediaItem_Track(item)

-- Determine items to process
local items_to_process = {}
if SCOPE == "Track" then
  local num = reaper.CountTrackMediaItems(track)
  for i = 0, num - 1 do
    local it = reaper.GetTrackMediaItem(track, i)
    local tk = reaper.GetActiveTake(it)
    if tk and not reaper.TakeIsMIDI(tk) then
      table.insert(items_to_process, it)
    end
  end
else
  table.insert(items_to_process, item)
end

-- Measure LUFS
local lufs_gain_db = 0
local current_lufs = nil

if TARGET_LUFS ~= 0 then
  if LUFS_SOURCE == "SWS" then
    current_lufs = measure_lufs_sws(take)
  elseif LUFS_SOURCE == "MonoRun" or LUFS_SOURCE == "StereoRun" then
    local render_start, render_end
    if SCOPE == "Track" then
      render_start = math.huge
      render_end = -math.huge
      for _, it in ipairs(items_to_process) do
        local pos = reaper.GetMediaItemInfo_Value(it, "D_POSITION")
        local len = reaper.GetMediaItemInfo_Value(it, "D_LENGTH")
        if pos < render_start then render_start = pos end
        if pos + len > render_end then render_end = pos + len end
      end
    else
      render_start = reaper.GetMediaItemInfo_Value(item, "D_POSITION")
      render_end = render_start + reaper.GetMediaItemInfo_Value(item, "D_LENGTH")
    end
    current_lufs = measure_lufs_render(track, render_start, render_end,
                                       LUFS_SOURCE == "MonoRun")
  end

  if not current_lufs then
    reaper.PreventUIRefresh(-1)
    reaper.ShowMessageBox(
      "LUFS analysis failed. The item may be silent or offline.\n"
      .. "Ensure SWS extension is installed.",
      "Error", 0)
    reaper.Undo_EndBlock("RCBit LUFS Limiter V5 - LUFS failed", -1)
    return
  end

  lufs_gain_db = TARGET_LUFS - current_lufs

  -- Check if already at target (only for non-zero LUFS and no-peaks scenario)
  -- We still proceed even if lufs_gain is small, because peaks may need limiting
end

-- Process items
local total_stats = {splits = 0, fx_count = 0, skip_count = 0, peak_wins = 0,
                     items_processed = 0, micro_br = 1, region_count = 0,
                     peak_regions = 0}

for _, it in ipairs(items_to_process) do
  local stats = process_item(it, track, lufs_gain_db, CEILING_DB,
                             ATTACK_SEC, RELEASE_SEC, WINDOW_SEC, LIMITER_MODE)
  if stats then
    total_stats.splits = total_stats.splits + stats.splits
    total_stats.fx_count = total_stats.fx_count + stats.fx_count
    total_stats.skip_count = total_stats.skip_count + (stats.skip_count or 0)
    total_stats.peak_wins = total_stats.peak_wins + stats.peak_wins
    total_stats.items_processed = total_stats.items_processed + 1
    total_stats.region_count = total_stats.region_count + (stats.region_count or 0)
    total_stats.peak_regions = total_stats.peak_regions + (stats.peak_regions or 0)
    if stats.micro_br and stats.micro_br > total_stats.micro_br then
      total_stats.micro_br = stats.micro_br
    end
  end
end

reaper.PreventUIRefresh(-1)
reaper.UpdateArrange()

-- Build result message
local lufs_m, lufs_br = calc_rcbit_params(lufs_gain_db, false)
local lufs_eff = lufs_m and (lufs_m * lufs_br * BIT_DB) or 0

local msg = "Done!\n\n"
msg = msg .. string.format("Scope: %s | Mode: %s | LUFS Source: %s\n\n", SCOPE, LIMITER_MODE, LUFS_SOURCE)

if TARGET_LUFS ~= 0 and current_lufs then
  msg = msg .. string.format(
    "Current LUFS: %.1f\nTarget LUFS: %.1f\n"
    .. "LUFS Gain: %+.2f dB (actual: %+.2f dB)\n",
    current_lufs, TARGET_LUFS, lufs_gain_db, lufs_eff)
else
  msg = msg .. "LUFS: disabled (pure limiting)\n"
end

msg = msg .. string.format("Peak Ceiling: %.1f dB\n\n", CEILING_DB)

if SCOPE == "Track" then
  msg = msg .. string.format("Items processed: %d\n", total_stats.items_processed)
end

msg = msg .. string.format(
  "%d peak window(s) detected\n"
  .. "%d region(s) (%d peak, %d boost)\n"
  .. "%d split(s) created\n"
  .. "%d FX instance(s) applied\n"
  .. "%d item(s) skipped (gain < %.2f dB)\n",
  total_stats.peak_wins,
  total_stats.region_count, total_stats.peak_regions,
  total_stats.region_count - total_stats.peak_regions,
  total_stats.splits, total_stats.fx_count,
  total_stats.skip_count, MIN_GAIN_DB)

if LIMITER_MODE == "Micro" and lufs_gain_db ~= 0 then
  msg = msg .. string.format("\nMicro mode: BR=%d for limiter instance\n", total_stats.micro_br)
  msg = msg .. "Peak splits have 2 RCBit instances (LUFS + Limiter)"
elseif LIMITER_MODE == "Combined" then
  msg = msg .. "\nBR quantized to " .. BR_STEP .. " steps (peak: floor, boost: round)"
  msg = msg .. "\nEach split has exactly ONE RCBit."
end

reaper.ShowMessageBox(msg, "RCBit LUFS Limiter V5.0", 0)
reaper.Undo_EndBlock("RCBit LUFS Limiter V5.0", -1)
