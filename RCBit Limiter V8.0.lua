-- RCBit Limiter V8.0
-- Split-based peak limiter using JS:RCBitRangeGain for bit-accurate gain reduction
-- Accessor-based post-split verification eliminates BR quantization overshoot
-- Clean segments remain untouched (no FX)
--
-- V8 improvements over V7:
--   - Accessor reads from position 0 (D_STARTOFFS baked in)
--   - Post-split verification tightens BR if over ceiling
--   - Eliminates ~0.3 dB overshoot from BR quantization
--
-- Author: Dima Gorelik
-- Co-developed with Claude (Anthropic)
-- License: MIT
--
-- Requires: JS:RCBitRangeGain JSFX plugin by RCJacH

local BIT_DB = 6.0206
local MIN_GAIN_DB = 0.15
local MIN_REGION_SEC = 0.02
local BR_STEP = 0.05
local VERIFY_TOLERANCE = 0.01

local function calc_rcbit_params(gain_db)
  if math.abs(gain_db) < MIN_GAIN_DB then return nil, nil end
  local total_bits = gain_db / BIT_DB
  local macro = math.floor(math.abs(total_bits) + 0.5)
  if macro == 0 then macro = 1 end
  if gain_db < 0 then macro = -macro end
  local bit_ratio = math.abs(gain_db) / (math.abs(macro) * BIT_DB)
  bit_ratio = math.min(math.max(bit_ratio, 0.0), 3.0)
  bit_ratio = math.floor(bit_ratio / BR_STEP) * BR_STEP
  local effective_gain = math.abs(macro) * bit_ratio * BIT_DB
  if effective_gain < MIN_GAIN_DB then return nil, nil end
  return macro, bit_ratio
end

local function get_source_sr(take)
  local src = reaper.GetMediaItemTake_Source(take)
  local sr_val = reaper.GetMediaSourceSampleRate(src)
  if sr_val == 0 then
    local parent = reaper.GetMediaSourceParent(src)
    if parent then sr_val = reaper.GetMediaSourceSampleRate(parent) end
  end
  if sr_val == 0 then sr_val = reaper.GetSetProjectInfo(0, "PROJECT_SRATE", 0, false) end
  if sr_val == 0 then sr_val = 44100 end
  return sr_val
end

local function get_source_ch(take)
  local src = reaper.GetMediaItemTake_Source(take)
  local ch = reaper.GetMediaSourceNumChannels(src)
  if ch == 0 then
    local parent = reaper.GetMediaSourceParent(src)
    if parent then ch = reaper.GetMediaSourceNumChannels(parent) end
  end
  if ch == 0 then ch = 1 end
  return ch
end

local function read_source_peak_db(take, sr_val, ch)
  local item = reaper.GetMediaItemTake_Item(take)
  local len = reaper.GetMediaItemInfo_Value(item, "D_LENGTH")
  local rate = reaper.GetMediaItemTakeInfo_Value(take, "D_PLAYRATE")
  local t_end = len * rate
  local accessor = reaper.CreateTakeAudioAccessor(take)
  local chunk = 4096
  local max_peak = 0
  local t = 0
  while t < t_end do
    local ns = math.min(chunk, math.floor((t_end - t) * sr_val) + 1)
    if ns <= 0 then break end
    local buf = reaper.new_array(ns * ch)
    buf.clear()
    reaper.GetAudioAccessorSamples(accessor, sr_val, ch, t, ns, buf)
    for s = 1, ns * ch do
      local val = math.abs(buf[s])
      if val > max_peak then max_peak = val end
    end
    t = t + ns / sr_val
  end
  reaper.DestroyAudioAccessor(accessor)
  if max_peak > 0 then return 20 * math.log(max_peak, 10) end
  return -math.huge
end

local retval, user_input = reaper.GetUserInputs(
  "RCBit Limiter V8.0", 4,
  "Ceiling (dB):,Attack (ms):,Release (ms):,Analysis Window (ms):,extrawidth=80",
  "-0.5,0,70,5"
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
  reaper.PreventUIRefresh(-1)
  reaper.ShowMessageBox("Please select a media item.", "Error", 0)
  reaper.Undo_EndBlock("RCBit Limiter V8 - failed", -1)
  return
end

local take = reaper.GetActiveTake(item)
if not take or reaper.TakeIsMIDI(take) then
  reaper.PreventUIRefresh(-1)
  reaper.ShowMessageBox("Selected item must be audio.", "Error", 0)
  reaper.Undo_EndBlock("RCBit Limiter V8 - failed", -1)
  return
end

local source = reaper.GetMediaItemTake_Source(take)
local num_ch = reaper.GetMediaSourceNumChannels(source)
local sr = reaper.GetMediaSourceSampleRate(source)

if sr == 0 then
  local parent = reaper.GetMediaSourceParent(source)
  if parent then sr = reaper.GetMediaSourceSampleRate(parent) end
end
if sr == 0 then sr = reaper.GetSetProjectInfo(0, "PROJECT_SRATE", 0, false) end
if sr == 0 then sr = 44100 end
if num_ch == 0 then
  local parent = reaper.GetMediaSourceParent(source)
  if parent then num_ch = reaper.GetMediaSourceNumChannels(parent) end
  if num_ch == 0 then num_ch = 1 end
end

local item_pos = reaper.GetMediaItemInfo_Value(item, "D_POSITION")
local item_len = reaper.GetMediaItemInfo_Value(item, "D_LENGTH")
local item_end = item_pos + item_len
local track = reaper.GetMediaItem_Track(item)
local take_rate = reaper.GetMediaItemTakeInfo_Value(take, "D_PLAYRATE")

-- Peak analysis via accessor (position 0, offset baked in)
local windows = {}
local accessor = reaper.CreateTakeAudioAccessor(take)
local samples_per_win = math.max(math.floor(sr * WINDOW_SEC), 1)
local buf_size = samples_per_win * num_ch
local t = 0
local t_end_src = item_len * take_rate

while t < t_end_src do
  local buf = reaper.new_array(buf_size)
  buf.clear()
  reaper.GetAudioAccessorSamples(accessor, sr, num_ch, t, samples_per_win, buf)
  local peak = 0
  for i = 1, buf_size do
    local s = math.abs(buf[i])
    if s > peak then peak = s end
  end
  local proj_time = item_pos + t / take_rate
  local peak_db = -math.huge
  if peak > 0 then peak_db = 20 * math.log(peak, 10) end
  table.insert(windows, {
    time = proj_time, is_peak = (peak_db > CEILING_DB),
    reduction_db = CEILING_DB - peak_db
  })
  t = t + WINDOW_SEC
end
reaper.DestroyAudioAccessor(accessor)

local peak_win_count = 0
for _, w in ipairs(windows) do
  if w.is_peak then peak_win_count = peak_win_count + 1 end
end

if peak_win_count == 0 then
  reaper.PreventUIRefresh(-1)
  reaper.ShowMessageBox(
    string.format("No peaks exceeding %.1f dB found.", CEILING_DB),
    "RCBit Limiter V8.0", 0)
  reaper.Undo_EndBlock("RCBit Limiter V8 - no changes", -1)
  return
end

-- Build regions
local regions = {}
local cur = {
  s = windows[1].time, e = windows[1].time + WINDOW_SEC,
  is_peak = windows[1].is_peak, min_reduction = windows[1].reduction_db
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
    cur = { s = w.time, e = w.time + WINDOW_SEC,
            is_peak = w.is_peak, min_reduction = w.reduction_db }
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

local valid = {}
for _, reg in ipairs(regions) do
  if reg.e - reg.s > 0.001 then table.insert(valid, reg) end
end
regions = valid

local mp = {regions[1]}
for i = 2, #regions do
  local prev = mp[#mp]
  local curr = regions[i]
  if prev.is_peak and curr.is_peak and curr.s <= prev.e + 0.001 then
    prev.e = math.max(prev.e, curr.e)
    if curr.min_reduction < prev.min_reduction then prev.min_reduction = curr.min_reduction end
  else
    table.insert(mp, curr)
  end
end
regions = mp

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

local mg = {regions[1]}
for i = 2, #regions do
  local prev = mg[#mg]
  local curr = regions[i]
  if prev.is_peak == curr.is_peak then
    prev.e = curr.e
    if curr.is_peak and curr.min_reduction < prev.min_reduction then
      prev.min_reduction = curr.min_reduction
    end
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

for _, sp in ipairs(split_points) do
  reaper.SplitMediaItem(item, sp)
end

-- Apply FX to peak splits only
local fx_count, skip_count = 0, 0
local num_items = reaper.CountTrackMediaItems(track)

for i = 0, num_items - 1 do
  local it = reaper.GetTrackMediaItem(track, i)
  local it_pos = reaper.GetMediaItemInfo_Value(it, "D_POSITION")
  local it_len = reaper.GetMediaItemInfo_Value(it, "D_LENGTH")
  if it_pos >= item_pos - 0.001 and it_pos + it_len <= item_end + 0.001 then
    local it_mid = it_pos + it_len / 2
    for _, reg in ipairs(regions) do
      if it_mid >= reg.s - 0.001 and it_mid <= reg.e + 0.001 and reg.is_peak then
        local macro, bit_ratio = calc_rcbit_params(reg.min_reduction)
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
        break
      end
    end
  end
end

-- Post-split verification via accessor
local verify_fixes = 0
num_items = reaper.CountTrackMediaItems(track)

for i = 0, num_items - 1 do
  local it = reaper.GetTrackMediaItem(track, i)
  local it_pos = reaper.GetMediaItemInfo_Value(it, "D_POSITION")
  local it_len = reaper.GetMediaItemInfo_Value(it, "D_LENGTH")
  if it_pos >= item_pos - 0.001 and it_pos + it_len <= item_end + 0.001 then
    local tk = reaper.GetActiveTake(it)
    if tk and reaper.TakeFX_GetCount(tk) > 0 then
      local it_sr = get_source_sr(tk)
      local it_ch = get_source_ch(tk)
      local src_peak_db = read_source_peak_db(tk, it_sr, it_ch)

      if src_peak_db > -200 then
        local macro = reaper.TakeFX_GetParam(tk, 0, 0)
        local br = reaper.TakeFX_GetParam(tk, 0, 2)
        local eff_gain = math.abs(macro) * br * BIT_DB
        if macro < 0 then eff_gain = -eff_gain end
        local post_fx_peak = src_peak_db + eff_gain

        if post_fx_peak > CEILING_DB + VERIFY_TOLERANCE then
          local fixed = false
          if macro < 0 then
            while br < 3.0 and post_fx_peak > CEILING_DB + VERIFY_TOLERANCE do
              br = br + BR_STEP
              if br > 3.0 then br = 3.0 end
              eff_gain = -(math.abs(macro) * br * BIT_DB)
              post_fx_peak = src_peak_db + eff_gain
              fixed = true
            end
          elseif macro > 0 then
            while br > 0 and post_fx_peak > CEILING_DB + VERIFY_TOLERANCE do
              br = br - BR_STEP
              if br < 0 then br = 0 end
              eff_gain = macro * br * BIT_DB
              post_fx_peak = src_peak_db + eff_gain
              fixed = true
            end
          end
          if fixed then
            if macro > 0 and br <= 0 then
              reaper.TakeFX_Delete(tk, 0)
              fx_count = fx_count - 1
              skip_count = skip_count + 1
            else
              reaper.TakeFX_SetParam(tk, 0, 2, br)
            end
            verify_fixes = verify_fixes + 1
          end
        end
      end
    end
  end
end

reaper.PreventUIRefresh(-1)
reaper.UpdateArrange()

local peak_r, clean_r = 0, 0
for _, r in ipairs(regions) do
  if r.is_peak then peak_r = peak_r + 1 else clean_r = clean_r + 1 end
end

reaper.ShowMessageBox(string.format(
  "Done!\n\n"
  .. "Channels: %d | SR: %d\n"
  .. "Ceiling: %.1f dB\n"
  .. "Attack: %d ms | Release: %d ms | Window: %d ms\n\n"
  .. "%d peak window(s) detected\n"
  .. "%d region(s) (%d peak, %d clean)\n"
  .. "%d split(s) created\n"
  .. "%d items with RCBitRangeGain\n"
  .. "%d items skipped (gain < %.2f dB)\n"
  .. "%d verification fixes",
  num_ch, sr, CEILING_DB,
  ATTACK_SEC*1000, RELEASE_SEC*1000, WINDOW_SEC*1000,
  peak_win_count, #regions, peak_r, clean_r,
  #split_points, fx_count, skip_count, MIN_GAIN_DB,
  verify_fixes),
  "RCBit Limiter V8.0", 0)
reaper.Undo_EndBlock("RCBit Limiter V8.0", -1)
