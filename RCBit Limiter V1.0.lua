-- RCBit Limiter V1.0
-- Split-based peak limiter using JS:RCBitRangeGain for bit-accurate gain reduction
-- Each peak window gets its own split with precisely calculated Bit Ratio
-- Non-peak segments remain clean with no plugins
--
-- Author: Dima Gorelik
-- Co-developed with Claude (Anthropic)
-- License: MIT
--
-- Requires: JS:RCBitRangeGain JSFX plugin by RCJacH

local BIT_DB = 20 * math.log(2, 10)  -- 6.0206 dB per bit
local MERGE_TOLERANCE = 0.02         -- merge adjacent windows within 0.02 bit ratio

local default_ceiling = "-9.0"
local default_attack = "10"
local default_release = "50"
local default_window = "5"

local retval, user_input = reaper.GetUserInputs(
  "RCBit Limiter V1.0", 4,
  "Ceiling (dB):,Attack (ms):,Release (ms):,Analysis window (ms):,extrawidth=80",
  default_ceiling .. "," .. default_attack .. "," .. default_release .. "," .. default_window
)
if not retval then return end

local ceiling_db, attack_ms, release_ms, window_ms = user_input:match("([^,]+),([^,]+),([^,]+),([^,]+)")
local THRESHOLD_DB = tonumber(ceiling_db)
local ATTACK_SEC = tonumber(attack_ms) / 1000
local RELEASE_SEC = tonumber(release_ms) / 1000
local WINDOW_SEC = tonumber(window_ms) / 1000

if not THRESHOLD_DB or not ATTACK_SEC or not RELEASE_SEC or not WINDOW_SEC then
  reaper.ShowMessageBox("Invalid input. Please enter numeric values.", "RCBit Limiter", 0)
  return
end

local THRESHOLD_LIN = 10 ^ (THRESHOLD_DB / 20)

reaper.Undo_BeginBlock()
reaper.PreventUIRefresh(1)

local item = reaper.GetSelectedMediaItem(0, 0)
if not item then
  reaper.ShowMessageBox("Please select a media item.", "RCBit Limiter", 0)
  return
end

local take = reaper.GetActiveTake(item)
if not take or reaper.TakeIsMIDI(take) then
  reaper.ShowMessageBox("Selected item must be audio.", "RCBit Limiter", 0)
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

  if peak > THRESHOLD_LIN then
    local proj_time = item_pos + (t - take_offset) / take_rate
    local reduction_db = 20 * math.log(THRESHOLD_LIN / peak, 10)
    local bit_ratio = math.abs(reduction_db) / BIT_DB
    bit_ratio = math.min(bit_ratio, 3.0)
    table.insert(windows, {time = proj_time, bit_ratio = bit_ratio})
  end

  t = t + WINDOW_SEC
end

reaper.DestroyAudioAccessor(accessor)

if #windows == 0 then
  reaper.PreventUIRefresh(-1)
  reaper.ShowMessageBox("No peaks exceeding " .. THRESHOLD_DB .. " dB found.", "RCBit Limiter", 0)
  reaper.Undo_EndBlock("RCBit Limiter - no changes", -1)
  return
end

-- Merge adjacent windows with similar bit_ratio
local regions = {}
local cur = {
  s = windows[1].time,
  e = windows[1].time + WINDOW_SEC,
  bit_ratio = windows[1].bit_ratio
}

for i = 2, #windows do
  local w = windows[i]
  if w.time <= cur.e + 0.0001 and math.abs(w.bit_ratio - cur.bit_ratio) <= MERGE_TOLERANCE then
    cur.e = w.time + WINDOW_SEC
    if w.bit_ratio > cur.bit_ratio then
      cur.bit_ratio = w.bit_ratio
    end
  else
    table.insert(regions, cur)
    cur = {s = w.time, e = w.time + WINDOW_SEC, bit_ratio = w.bit_ratio}
  end
end
table.insert(regions, cur)

-- Apply attack/release expansion and clamp to item bounds
for _, reg in ipairs(regions) do
  reg.s = math.max(reg.s - ATTACK_SEC, item_pos)
  reg.e = math.min(reg.e + RELEASE_SEC, item_end)
end

-- Collect unique split points sorted descending (right to left)
local split_set = {}
for _, reg in ipairs(regions) do
  split_set[reg.s] = true
  split_set[reg.e] = true
end

local split_points = {}
for pos, _ in pairs(split_set) do
  if pos > item_pos + 0.001 and pos < item_end - 0.001 then
    table.insert(split_points, pos)
  end
end
table.sort(split_points, function(a, b) return a > b end)

-- Split item from right to left
for _, pos in ipairs(split_points) do
  reaper.SplitMediaItem(item, pos)
end

-- Find all items on the track in original range and add RCBitRangeGain to peak splits
local peak_count = 0
local num_items = reaper.CountTrackMediaItems(track)

for i = 0, num_items - 1 do
  local it = reaper.GetTrackMediaItem(track, i)
  local it_pos = reaper.GetMediaItemInfo_Value(it, "D_POSITION")
  local it_len = reaper.GetMediaItemInfo_Value(it, "D_LENGTH")

  if it_pos >= item_pos - 0.001 and it_pos + it_len <= item_end + 0.001 then
    local it_mid = it_pos + it_len / 2

    for _, reg in ipairs(regions) do
      if it_mid >= reg.s - 0.001 and it_mid <= reg.e + 0.001 then
        local tk = reaper.GetActiveTake(it)
        if tk then
          local fx_idx = reaper.TakeFX_AddByName(tk, "JS:RCBitRangeGain", -1)
          if fx_idx >= 0 then
            -- For JSFX, TakeFX_SetParam uses actual slider values
            reaper.TakeFX_SetParam(tk, fx_idx, 0, -1)              -- Macro Shift: -1
            reaper.TakeFX_SetParam(tk, fx_idx, 1, 0)               -- Micro Shift: 0
            reaper.TakeFX_SetParam(tk, fx_idx, 2, reg.bit_ratio)   -- Bit Ratio: calculated
            peak_count = peak_count + 1
          end
        end
        break
      end
    end
  end
end

reaper.PreventUIRefresh(-1)
reaper.UpdateArrange()

local msg = string.format(
  "Done!\n\nCeiling: %g dB\nAttack: %g ms\nRelease: %g ms\nWindow: %g ms\n\n"
  .. "%d peak region(s) found\n%d split(s) with RCBitRangeGain applied\n\n"
  .. "Macro Shift: -1 | Bit Ratios calculated per peak",
  THRESHOLD_DB, ATTACK_SEC * 1000, RELEASE_SEC * 1000, WINDOW_SEC * 1000,
  #regions, peak_count)
reaper.ShowMessageBox(msg, "RCBit Limiter V1.0", 0)
reaper.Undo_EndBlock("RCBit Limiter V1.0 (" .. THRESHOLD_DB .. " dB)", -1)
