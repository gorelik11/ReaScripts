-- RCBit LUFS Limiter V8.0 Headless
-- No dialogs — reads params from ~/rcbit_v8_params.txt, writes results to ~/rcbit_v8_results.txt
-- For iterative testing via reapy
--
-- V8 improvements over V7:
--   - Accessor-based peak analysis only (no render mode, no temp files)
--   - Accessor reads from position 0 on split items (D_STARTOFFS baked in)
--   - Post-split verification: re-reads source peaks via accessor, tightens BR if over ceiling
--   - Eliminates ~0.3 dB BR quantization overshoot
--   - Respects user crossfade settings

local BIT_DB = 6.0206
local MIN_GAIN_DB = 0.15
local PEAK_MARGIN_DB = 0.0
local MIN_REGION_SEC = 0.02
local BR_STEP = 0.05
local VERIFY_TOLERANCE = 0.01

local params_file = os.getenv("HOME") .. "/rcbit_v8_params.txt"
local results_file = os.getenv("HOME") .. "/rcbit_v8_results.txt"

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

-- Get SR with fallback chain
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

-- Get channel count with fallback
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

-- Read source peak from a take via accessor (from position 0, offset baked in)
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

reaper.Undo_BeginBlock()
reaper.PreventUIRefresh(1)

local item = reaper.GetSelectedMediaItem(0, 0)
if not item then
  write_result("ERROR: No selected item")
  reaper.PreventUIRefresh(-1)
  reaper.Undo_EndBlock("RCBit V8 Headless - failed", -1)
  return
end

local take = reaper.GetActiveTake(item)
if not take or reaper.TakeIsMIDI(take) then
  write_result("ERROR: Not audio item")
  reaper.PreventUIRefresh(-1)
  reaper.Undo_EndBlock("RCBit V8 Headless - failed", -1)
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
if num_ch == 0 then
  local parent = reaper.GetMediaSourceParent(source)
  if parent then num_ch = reaper.GetMediaSourceNumChannels(parent) end
  if num_ch == 0 then num_ch = 1 end
  is_mono = (num_ch == 1)
end

local item_pos = reaper.GetMediaItemInfo_Value(item, "D_POSITION")
local item_len = reaper.GetMediaItemInfo_Value(item, "D_LENGTH")
local item_end = item_pos + item_len
local track = reaper.GetMediaItem_Track(item)
local take_rate = reaper.GetMediaItemTakeInfo_Value(take, "D_PLAYRATE")

-- LUFS via SWS
local lufs_ok, lufs_integrated = reaper.NF_AnalyzeTakeLoudness(take, false)
if not lufs_ok or not lufs_integrated or lufs_integrated <= -200 then
  write_result("ERROR: LUFS analysis failed")
  reaper.PreventUIRefresh(-1)
  reaper.Undo_EndBlock("RCBit V8 Headless - failed", -1)
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
  reaper.Undo_EndBlock("RCBit V8 Headless - no changes", -1)
  return
end

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
  local peak_after_gain = peak_db + lufs_gain_db
  local is_peak = (peak_after_gain > CEILING_DB + PEAK_MARGIN_DB)
  table.insert(windows, {
    time = proj_time, is_peak = is_peak,
    peak_gain_db = CEILING_DB - peak_db
  })
  t = t + WINDOW_SEC
end
reaper.DestroyAudioAccessor(accessor)

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
    .. "CH: %d | SR: %d\n"
    .. "LUFS: %.1f → %.1f (gain: %+.2f, eff: %+.2f)\n"
    .. "Ceiling: %.1f | Macro: %d | BR: %.2f",
    num_ch, sr,
    current_lufs, TARGET_LUFS, lufs_gain_db, eff,
    CEILING_DB, macro or 0, bit_ratio or 0))
  reaper.Undo_EndBlock("RCBit LUFS Limiter V8.0", -1)
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

-- Phase 5: Post-split verification via accessor
local verify_fixes = 0
num_items = reaper.CountTrackMediaItems(track)

for i = 0, num_items - 1 do
  local it = reaper.GetTrackMediaItem(track, i)
  local it_pos = reaper.GetMediaItemInfo_Value(it, "D_POSITION")
  local it_len = reaper.GetMediaItemInfo_Value(it, "D_LENGTH")
  if it_pos >= item_pos - 0.001 and it_pos + it_len <= item_end + 0.001 then
    local tk = reaper.GetActiveTake(it)
    if tk and reaper.TakeFX_GetCount(tk) > 0 then
      -- Read source peak via accessor (from pos 0, offset baked in)
      local it_sr = get_source_sr(tk)
      local it_ch = get_source_ch(tk)
      local src_peak_db = read_source_peak_db(tk, it_sr, it_ch)

      if src_peak_db > -200 then
        -- Get current RCBit params
        local macro = reaper.TakeFX_GetParam(tk, 0, 0)
        local br = reaper.TakeFX_GetParam(tk, 0, 2)
        local eff_gain = math.abs(macro) * br * BIT_DB
        if macro < 0 then eff_gain = -eff_gain end
        local post_fx_peak = src_peak_db + eff_gain

        -- If over ceiling, tighten BR
        if post_fx_peak > CEILING_DB + VERIFY_TOLERANCE then
          local fixed = false
          if macro > 0 then
            -- Positive gain (boost) overshooting: decrease BR to reduce boost
            while br > 0 and post_fx_peak > CEILING_DB + VERIFY_TOLERANCE do
              br = br - BR_STEP
              if br < 0 then br = 0 end
              eff_gain = macro * br * BIT_DB
              post_fx_peak = src_peak_db + eff_gain
              fixed = true
            end
          elseif macro < 0 then
            -- Negative gain (reduction) insufficient: increase BR to increase reduction
            while br < 3.0 and post_fx_peak > CEILING_DB + VERIFY_TOLERANCE do
              br = br + BR_STEP
              if br > 3.0 then br = 3.0 end
              eff_gain = -(math.abs(macro) * br * BIT_DB)
              post_fx_peak = src_peak_db + eff_gain
              fixed = true
            end
          end
          if fixed then
            if macro > 0 and br <= 0 then
              -- Boost gain too small — remove FX
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
  .. "CH: %d | SR: %d\n"
  .. "LUFS: %.1f → %.1f (gain: %+.2f, eff: %+.2f)\n"
  .. "Ceiling: %.1f | Attack: %dms | Release: %dms | Window: %dms\n"
  .. "Windows: %d (%d peak)\n"
  .. "Regions: %d (%d peak, %d boost)\n"
  .. "Splits: %d | FX: %d | Skip: %d | Clean: %d\n"
  .. "Verification fixes: %d\n"
  .. "---\n%s",
  num_ch, sr,
  current_lufs, TARGET_LUFS, lufs_gain_db, lufs_eff,
  CEILING_DB, ATTACK_SEC*1000, RELEASE_SEC*1000, WINDOW_SEC*1000,
  #windows, peak_win_count,
  #regions, peak_r, boost_r,
  #split_points, fx_count, skip_count, clean_count,
  verify_fixes,
  table.concat(region_log, "\n")))

reaper.Undo_EndBlock("RCBit LUFS Limiter V8.0", -1)
