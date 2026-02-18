-- RCBit Limiter V3.0
-- Split-based peak limiter using JS:RCBitRangeGain for bit-accurate gain reduction
-- Each peak region gets its own split with precisely calculated Macro/Bit Ratio
-- Non-peak segments remain clean with no plugins
--
-- V3 improvements over V1:
--   - Binary classification: each window is PEAK or CLEAN
--   - Attack/release expansion before tiny region absorption
--   - Peak regions shrink adjacent clean regions (no cascade merging)
--   - Minimum region length — tiny splits absorbed into neighbors
--   - Proper Macro/Bit Ratio calculation via calc_rcbit_params
--   - Skip FX when effective gain < 0.15 dB
--
-- Author: Dima Gorelik
-- Co-developed with Claude (Anthropic)
-- License: MIT
--
-- Requires: JS:RCBitRangeGain JSFX plugin by RCJacH

local BIT_DB = 6.0206
local MIN_GAIN_DB = 0.15
local MIN_REGION_SEC = 0.02  -- 20ms

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
  "RCBit Limiter V3.0", 4,
  "Ceiling (dB):,Attack (ms):,Release (ms):,Analysis Window (ms):,extrawidth=80",
  "-9.0,10,50,5"
)
if not retval then return end

local vals = {}
for v in user_input:gmatch("([^,]+)") do table.insert(vals, tonumber(v)) end
local CEILING_DB = vals[1]
local ATTACK_SEC = vals[2] / 1000
local RELEASE_SEC = vals[3] / 1000
local WINDOW_SEC = vals[4] / 1000

if not CEILING_DB or not ATTACK_SEC or not RELEASE_SEC or not WINDOW_SEC then
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

local item_pos = reaper.GetMediaItemInfo_Value(item, "D_POSITION")
local item_len = reaper.GetMediaItemInfo_Value(item, "D_LENGTH")
local item_end = item_pos + item_len
local track = reaper.GetMediaItem_Track(item)

local source = reaper.GetMediaItemTake_Source(take)
local sr = reaper.GetMediaSourceSampleRate(source)
local num_ch = reaper.GetMediaSourceNumChannels(source)
local take_offset = reaper.GetMediaItemTakeInfo_Value(take, "D_STARTOFFS")
local take_rate = reaper.GetMediaItemTakeInfo_Value(take, "D_PLAYRATE")

if sr == 0 then
  -- Fallback: use project sample rate
  sr = reaper.GetSetProjectInfo(0, "PROJECT_SRATE", 0, false)
  if sr == 0 then sr = 44100 end
end

-- Analyze audio peaks per window
local accessor = reaper.CreateTakeAudioAccessor(take)
local samples_per_win = math.max(math.floor(sr * WINDOW_SEC), 1)
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

  local is_peak = (peak_db > CEILING_DB)
  local reduction_db = CEILING_DB - peak_db  -- negative for peaks above ceiling

  table.insert(windows, {
    time = proj_time,
    is_peak = is_peak,
    reduction_db = reduction_db
  })

  t = t + WINDOW_SEC
end

reaper.DestroyAudioAccessor(accessor)

-- Count peaks
local peak_win_count = 0
for _, w in ipairs(windows) do
  if w.is_peak then peak_win_count = peak_win_count + 1 end
end

if peak_win_count == 0 then
  reaper.PreventUIRefresh(-1)
  reaper.ShowMessageBox(
    string.format("No peaks exceeding %.1f dB found.", CEILING_DB),
    "RCBit Limiter V3.0", 0)
  reaper.Undo_EndBlock("RCBit Limiter V3 - no changes", -1)
  return
end

-- Build regions: merge consecutive windows of same type
-- PEAK regions track min reduction (most aggressive needed)
local regions = {}
local cur = {
  s = windows[1].time,
  e = windows[1].time + WINDOW_SEC,
  is_peak = windows[1].is_peak,
  min_reduction = windows[1].reduction_db
}

for i = 2, #windows do
  local w = windows[i]
  if w.is_peak == cur.is_peak then
    cur.e = w.time + WINDOW_SEC
    if w.is_peak and w.reduction_db < cur.min_reduction then
      cur.min_reduction = w.reduction_db
    end
  else
    table.insert(regions, cur)
    cur = {
      s = w.time,
      e = w.time + WINDOW_SEC,
      is_peak = w.is_peak,
      min_reduction = w.reduction_db
    }
  end
end
table.insert(regions, cur)

-- Apply attack/release: expand peak regions, shrink adjacent clean regions
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
    if curr.min_reduction < prev.min_reduction then
      prev.min_reduction = curr.min_reduction
    end
  else
    table.insert(merged_peaks, curr)
  end
end
regions = merged_peaks

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

regions = absorb_tiny_regions(regions)

-- Merge adjacent regions of same type
local merged = {regions[1]}
for i = 2, #regions do
  local prev = merged[#merged]
  local curr = regions[i]
  if prev.is_peak == curr.is_peak then
    prev.e = curr.e
    if curr.is_peak and curr.min_reduction < prev.min_reduction then
      prev.min_reduction = curr.min_reduction
    end
  else
    table.insert(merged, curr)
  end
end
regions = merged

-- Collect split points
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

-- Apply RCBitRangeGain to peak splits only
local fx_count = 0
local skip_count = 0
local num_items = reaper.CountTrackMediaItems(track)

for i = 0, num_items - 1 do
  local it = reaper.GetTrackMediaItem(track, i)
  local it_pos = reaper.GetMediaItemInfo_Value(it, "D_POSITION")
  local it_len = reaper.GetMediaItemInfo_Value(it, "D_LENGTH")

  if it_pos >= item_pos - 0.001 and it_pos + it_len <= item_end + 0.001 then
    local it_mid = it_pos + it_len / 2

    local matched_region = nil
    for _, reg in ipairs(regions) do
      if it_mid >= reg.s - 0.001 and it_mid <= reg.e + 0.001 then
        matched_region = reg
        break
      end
    end

    if matched_region and matched_region.is_peak then
      local gain_db = matched_region.min_reduction
      local macro, bit_ratio = calc_rcbit_params(gain_db)
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
end

reaper.PreventUIRefresh(-1)
reaper.UpdateArrange()

local peak_regions = 0
local clean_regions = 0
for _, r in ipairs(regions) do
  if r.is_peak then peak_regions = peak_regions + 1
  else clean_regions = clean_regions + 1 end
end

local msg = string.format(
  "Done!\n\n"
  .. "Ceiling: %.1f dB\n"
  .. "Attack: %.0f ms | Release: %.0f ms | Window: %.0f ms\n\n"
  .. "%d peak window(s) detected\n"
  .. "%d region(s) (%d peak, %d clean)\n"
  .. "%d split(s) created\n"
  .. "%d items with RCBitRangeGain\n"
  .. "%d items skipped (gain < %.2f dB)\n"
  .. "%d clean items (no FX)\n\n"
  .. "Macro Shift: -1 | Bit Ratios calculated per peak",
  CEILING_DB,
  ATTACK_SEC * 1000, RELEASE_SEC * 1000, WINDOW_SEC * 1000,
  peak_win_count, #regions, peak_regions, clean_regions,
  #split_points, fx_count, skip_count, MIN_GAIN_DB,
  num_items - fx_count - skip_count)
reaper.ShowMessageBox(msg, "RCBit Limiter V3.0", 0)
reaper.Undo_EndBlock("RCBit Limiter V3.0 (" .. CEILING_DB .. " dB)", -1)
