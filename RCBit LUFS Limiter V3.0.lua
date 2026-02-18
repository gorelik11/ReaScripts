-- RCBit LUFS Limiter V3.0
-- Combined LUFS gain staging + peak limiting using RCBitRangeGain
-- Single RCBit per split — never doubles up
--
-- V3 improvements over V1:
--   - Binary classification: each window is BOOST or PEAK, no intermediate transitions
--   - Attack/release expansion applied before region absorption
--   - Minimum region length — tiny splits absorbed into neighbors
--   - Post-split cleanup: merge adjacent items with identical settings
--   - Skip FX entirely when effective gain < 0.15 dB
--   - Peak regions shrink adjacent boost regions (no cascade merging)
--
-- Author: Dima Gorelik
-- Co-developed with Claude (Anthropic)
-- License: MIT
--
-- Requires: JS:RCBitRangeGain JSFX plugin by RCJacH
-- Requires: SWS extension (for NF_AnalyzeTakeLoudness)

local BIT_DB = 6.0206
local MIN_GAIN_DB = 0.15         -- skip FX below this
local PEAK_MARGIN_DB = 0.0       -- split at any peak exceeding ceiling
local MIN_REGION_SEC = 0.02      -- minimum region length (20ms) — smaller regions get absorbed

-- Helper: calculate Macro Shift and Bit Ratio for a given gain in dB
local function calc_rcbit_params(gain_db)
  if math.abs(gain_db) < MIN_GAIN_DB then
    return nil, nil
  end

  local total_bits = gain_db / BIT_DB
  local macro = math.floor(math.abs(total_bits) + 0.5)
  if macro == 0 then macro = 1 end
  if gain_db < 0 then macro = -macro end

  local bit_ratio = math.abs(gain_db) / (math.abs(macro) * BIT_DB)
  bit_ratio = math.min(math.max(bit_ratio, 0.0), 3.0)

  return macro, bit_ratio
end

-- Dialog
local retval, user_input = reaper.GetUserInputs(
  "RCBit LUFS Limiter V3.0", 5,
  "Target LUFS:,Peak Ceiling (dB):,Attack (ms):,Release (ms):,Analysis Window (ms):,extrawidth=80",
  "-24,-6.2,10,50,5"
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

local item_pos = reaper.GetMediaItemInfo_Value(item, "D_POSITION")
local item_len = reaper.GetMediaItemInfo_Value(item, "D_LENGTH")
local item_end = item_pos + item_len
local track = reaper.GetMediaItem_Track(item)
local take_offset = reaper.GetMediaItemTakeInfo_Value(take, "D_STARTOFFS")
local take_rate = reaper.GetMediaItemTakeInfo_Value(take, "D_PLAYRATE")

-- Measure current LUFS via SWS
local success, lufs_integrated = reaper.NF_AnalyzeTakeLoudness(take, true)
if not success then
  reaper.PreventUIRefresh(-1)
  reaper.ShowMessageBox("LUFS analysis failed. Ensure SWS extension is installed.", "Error", 0)
  reaper.Undo_EndBlock("RCBit LUFS Limiter - failed", -1)
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
  reaper.PreventUIRefresh(-1)
  reaper.ShowMessageBox(
    string.format("Already at target LUFS (%.1f).", current_lufs),
    "RCBit LUFS Limiter V3.0", 0)
  reaper.Undo_EndBlock("RCBit LUFS Limiter - no changes", -1)
  return
end

-- Analyze peaks: binary classification (BOOST or PEAK)
local accessor = reaper.CreateTakeAudioAccessor(take)
local samples_per_win = math.max(math.floor(sr * WINDOW_SEC), 1)
local buf_size = samples_per_win * num_ch

local windows = {}  -- {time, is_peak, peak_gain_db}
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
  local peak_gain = CEILING_DB - peak_db  -- gain that would bring peak to exactly ceiling

  table.insert(windows, {
    time = proj_time,
    is_peak = is_peak,
    peak_gain_db = peak_gain
  })

  t = t + WINDOW_SEC
end

reaper.DestroyAudioAccessor(accessor)

-- Count peaks
local peak_win_count = 0
for _, w in ipairs(windows) do
  if w.is_peak then peak_win_count = peak_win_count + 1 end
end

-- If no peaks exceed ceiling, apply RCBit to whole item
if peak_win_count == 0 then
  local macro, bit_ratio = calc_rcbit_params(lufs_gain_db)
  if macro then
    local fx_idx = reaper.TakeFX_AddByName(take, "JS:RCBitRangeGain", -1)
    if fx_idx >= 0 then
      reaper.TakeFX_SetParam(take, fx_idx, 0, macro)
      reaper.TakeFX_SetParam(take, fx_idx, 1, 0)
      reaper.TakeFX_SetParam(take, fx_idx, 2, bit_ratio)
    end
  end
  reaper.PreventUIRefresh(-1)
  reaper.UpdateArrange()
  reaper.ShowMessageBox(
    string.format(
      "Done!\n\nCurrent LUFS: %.1f\nTarget LUFS: %.1f\nGain: %+.2f dB\n\n"
      .. "No peaks exceed %.1f dB (with %.1f dB margin) after gain.\n"
      .. "RCBitRangeGain applied to whole item.\n\nMacro: %d | Bit Ratio: %.4f",
      current_lufs, TARGET_LUFS, lufs_gain_db, CEILING_DB, PEAK_MARGIN_DB,
      macro or 0, bit_ratio or 0),
    "RCBit LUFS Limiter V3.0", 0)
  reaper.Undo_EndBlock("RCBit LUFS Limiter V3.0", -1)
  return
end

-- Build regions: merge consecutive windows of same type
-- BOOST regions get full LUFS gain
-- PEAK regions get the minimum (most conservative) peak_gain_db
local regions = {}
local cur = {
  s = windows[1].time,
  e = windows[1].time + WINDOW_SEC,
  is_peak = windows[1].is_peak,
  min_gain = windows[1].peak_gain_db
}

for i = 2, #windows do
  local w = windows[i]
  if w.is_peak == cur.is_peak then
    -- Same type — extend
    cur.e = w.time + WINDOW_SEC
    if w.is_peak and w.peak_gain_db < cur.min_gain then
      cur.min_gain = w.peak_gain_db
    end
  else
    -- Type changed — save current, start new
    table.insert(regions, cur)
    cur = {
      s = w.time,
      e = w.time + WINDOW_SEC,
      is_peak = w.is_peak,
      min_gain = w.peak_gain_db
    }
  end
end
table.insert(regions, cur)

-- Absorb tiny regions into neighbors
local function absorb_tiny_regions(regs)
  local changed = true
  while changed do
    changed = false
    local new_regs = {}
    for i, reg in ipairs(regs) do
      local duration = reg.e - reg.s
      if duration < MIN_REGION_SEC and #new_regs > 0 then
        -- Absorb into previous region
        new_regs[#new_regs].e = reg.e
        -- If absorbing a peak into boost, keep the boost gain
        -- If absorbing a boost into peak, keep the peak gain (conservative)
        if reg.is_peak and not new_regs[#new_regs].is_peak then
          -- Tiny peak absorbed into boost — boost wins (peak was marginal)
        elseif not reg.is_peak and new_regs[#new_regs].is_peak then
          -- Tiny boost absorbed into peak — keep peak's conservative gain
        end
        changed = true
      elseif duration < MIN_REGION_SEC and #new_regs == 0 and i < #regs then
        -- First region is tiny — merge with next
        regs[i + 1].s = reg.s
        if reg.is_peak and not regs[i + 1].is_peak then
          -- Tiny peak at start, next is boost — boost wins
        elseif not reg.is_peak and regs[i + 1].is_peak then
          -- Tiny boost at start, next is peak — keep peak gain
        end
        changed = true
      else
        table.insert(new_regs, reg)
      end
    end
    regs = new_regs
  end
  return regs
end

-- Apply attack/release: expand peak regions, shrink adjacent boost regions
for i, reg in ipairs(regions) do
  if reg.is_peak then
    local new_s = math.max(reg.s - ATTACK_SEC, item_pos)
    local new_e = math.min(reg.e + RELEASE_SEC, item_end)
    -- Shrink previous boost region if it overlaps
    if i > 1 and not regions[i-1].is_peak and regions[i-1].e > new_s then
      regions[i-1].e = new_s
    end
    -- Shrink next boost region if it overlaps
    if i < #regions and not regions[i+1].is_peak and regions[i+1].s < new_e then
      regions[i+1].s = new_e
    end
    reg.s = new_s
    reg.e = new_e
  end
end

-- Remove zero/negative-length regions
local valid_regions = {}
for _, reg in ipairs(regions) do
  if reg.e - reg.s > 0.001 then
    table.insert(valid_regions, reg)
  end
end
regions = valid_regions

-- Merge adjacent peak regions that now touch/overlap
local merged_peaks = {regions[1]}
for i = 2, #regions do
  local prev = merged_peaks[#merged_peaks]
  local curr = regions[i]
  if prev.is_peak and curr.is_peak and curr.s <= prev.e + 0.001 then
    prev.e = math.max(prev.e, curr.e)
    if curr.min_gain < prev.min_gain then
      prev.min_gain = curr.min_gain
    end
  else
    table.insert(merged_peaks, curr)
  end
end
regions = merged_peaks

-- Absorb remaining tiny regions into neighbors
regions = absorb_tiny_regions(regions)

-- Assign gains
for _, reg in ipairs(regions) do
  if reg.is_peak then
    reg.gain_db = reg.min_gain
  else
    reg.gain_db = lufs_gain_db
  end
end

-- Merge adjacent regions with same gain (within tolerance)
local merged = {regions[1]}
for i = 2, #regions do
  local prev = merged[#merged]
  local curr = regions[i]
  local prev_m, prev_br = calc_rcbit_params(prev.gain_db)
  local curr_m, curr_br = calc_rcbit_params(curr.gain_db)

  if prev_m == curr_m and prev_br ~= nil and curr_br ~= nil
    and math.abs(prev_br - curr_br) < 0.001 then
    -- Same RCBit params — merge
    prev.e = curr.e
  else
    table.insert(merged, curr)
  end
end
regions = merged

-- Collect split points (only between different-gain regions)
local split_points = {}
for i = 2, #regions do
  local pos = regions[i].s
  if pos > item_pos + 0.001 and pos < item_end - 0.001 then
    table.insert(split_points, pos)
  end
end
table.sort(split_points, function(a, b) return a > b end)

-- Remove duplicate split points
local unique_splits = {}
for _, pos in ipairs(split_points) do
  if #unique_splits == 0 or math.abs(pos - unique_splits[#unique_splits]) > 0.001 then
    table.insert(unique_splits, pos)
  end
end
split_points = unique_splits

-- Split from right to left
for _, pos in ipairs(split_points) do
  reaper.SplitMediaItem(item, pos)
end

-- Apply RCBitRangeGain to splits
local fx_count = 0
local skip_count = 0
local num_items = reaper.CountTrackMediaItems(track)

for i = 0, num_items - 1 do
  local it = reaper.GetTrackMediaItem(track, i)
  local it_pos = reaper.GetMediaItemInfo_Value(it, "D_POSITION")
  local it_len = reaper.GetMediaItemInfo_Value(it, "D_LENGTH")

  if it_pos >= item_pos - 0.001 and it_pos + it_len <= item_end + 0.001 then
    local it_mid = it_pos + it_len / 2

    -- Find which region this item belongs to
    local gain = lufs_gain_db  -- default
    for _, reg in ipairs(regions) do
      if it_mid >= reg.s - 0.001 and it_mid <= reg.e + 0.001 then
        gain = reg.gain_db
        break
      end
    end

    local macro, bit_ratio = calc_rcbit_params(gain)
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
    end
  end
end

reaper.PreventUIRefresh(-1)
reaper.UpdateArrange()

local lufs_macro, lufs_br = calc_rcbit_params(lufs_gain_db)
local peak_regions = 0
for _, r in ipairs(regions) do
  if r.is_peak then peak_regions = peak_regions + 1 end
end

local msg = string.format(
  "Done!\n\n"
  .. "Current LUFS: %.1f\nTarget LUFS: %.1f\nLUFS Gain: %+.2f dB (Macro: %d, BR: %.4f)\n"
  .. "Peak Ceiling: %.1f dB (margin: %.1f dB)\n\n"
  .. "%d peak window(s) detected\n"
  .. "%d region(s) after merging (%d peak, %d boost)\n"
  .. "%d split(s) created\n"
  .. "%d items with RCBitRangeGain\n"
  .. "%d items skipped (gain < %.2f dB)\n\n"
  .. "Each split has exactly ONE RCBit.",
  current_lufs, TARGET_LUFS, lufs_gain_db, lufs_macro or 0, lufs_br or 0,
  CEILING_DB, PEAK_MARGIN_DB,
  peak_win_count, #regions, peak_regions, #regions - peak_regions,
  #split_points, fx_count, skip_count, MIN_GAIN_DB)
reaper.ShowMessageBox(msg, "RCBit LUFS Limiter V3.0", 0)
reaper.Undo_EndBlock("RCBit LUFS Limiter V3.0", -1)
