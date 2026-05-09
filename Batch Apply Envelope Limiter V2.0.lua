-- Batch Apply Envelope Limiter V2.0
-- Apply an envelope limiter script to multiple selected items sequentially.
-- Uses ShowMessageBox for limiter choice (no truncation), then GetUserInputs for params.
-- Same settings apply to all items.
--
-- Supported limiters:
--   1 = RCBit LUFS Env V3 (LUFS + peak, Combined/Micro, SWS/DryRun)
--   2 = RCBit Env V4 (peak-only, Combined/Micro, Accessor/DryRun)
--   3 = RCBit Env V3 (peak-only, Combined/Micro, Accessor only)
--   4 = Env Item V2 (take volume envelope, no FX)

-----------------------------------------------------
-- SETTINGS
-----------------------------------------------------
local SHOW_RESULT = true

local LIMITERS = {
  { name = "LUFS Env V3",
    named_id = "RS59352a04c4a489b8696871e2c0519665fe8bf4b1",
    params_file = os.getenv("HOME") .. "/rcbit_lufs_env_v3_params.txt",
    results_file = os.getenv("HOME") .. "/rcbit_lufs_env_v3_results.txt",
    fields = {"TARGET_LUFS", "CEILING_DB", "ATTACK_MS", "RELEASE_MS", "WINDOW_MS", "FX_SCOPE", "LIMITER_MODE", "LUFS_SOURCE"},
    defaults = {"-9", "-0.5", "0", "70", "5", "TakeFX", "Combined", "SWS"},
  },
  { name = "Env V4",
    named_id = "RS5d83f05248eb1ab0ace05df8d9e660150869589d",
    params_file = os.getenv("HOME") .. "/rcbit_env_v4_params.txt",
    results_file = os.getenv("HOME") .. "/rcbit_env_v4_results.txt",
    fields = {"CEILING_DB", "ATTACK_MS", "RELEASE_MS", "WINDOW_MS", "FX_SCOPE", "LIMITER_MODE", "PEAK_SOURCE"},
    defaults = {"-0.5", "0", "70", "5", "TakeFX", "Combined", "Accessor"},
  },
  { name = "Env V3",
    named_id = "RSe9fe067871887f09aa5bbd335f1abd5d98039461",
    params_file = os.getenv("HOME") .. "/rcbit_env_v3_params.txt",
    results_file = os.getenv("HOME") .. "/rcbit_env_v3_results.txt",
    fields = {"CEILING_DB", "ATTACK_MS", "RELEASE_MS", "WINDOW_MS", "FX_SCOPE", "LIMITER_MODE"},
    defaults = {"-0.5", "0", "70", "5", "TakeFX", "Combined"},
  },
  { name = "Env Item V2",
    named_id = "RS4375420f21dd272912c446862e28aef2756cfd53",
    params_file = os.getenv("HOME") .. "/env_item_limiter_v2_params.txt",
    results_file = os.getenv("HOME") .. "/env_item_limiter_v2_results.txt",
    fields = {"CEILING_DB", "ATTACK_MS", "RELEASE_MS", "WINDOW_MS"},
    defaults = {"-0.5", "0", "70", "5"},
  },
}

-----------------------------------------------------

-- Resolve named command IDs
for i, lim in ipairs(LIMITERS) do
  if lim.named_id ~= "" then
    lim.cmd = reaper.NamedCommandLookup("_" .. lim.named_id)
  end
  if not lim.cmd or lim.cmd == 0 then lim.cmd = 0 end
end

local item_count = reaper.CountSelectedMediaItems(0)
if item_count == 0 then
  reaper.MB("No items selected.\nSelect one or more items and run again.",
            "Batch Envelope Limiter V2", 0)
  return
end

-- Dialog 1: Choose limiter via cascading ShowMessageBox
-- Page 1: YES=LUFS Env V3, NO=next page
local choice = nil

local r1 = reaper.ShowMessageBox(
  "Batch Envelope Limiter V2 — " .. item_count .. " item(s)\n\n"
  .. "Choose limiter:\n\n"
  .. "YES = 1. LUFS Env V3 (LUFS+peak, Combined/Micro)\n"
  .. "NO = 2. Env V4 (peak-only, Accessor/DryRun)\n\n"
  .. "(Cancel for more options)",
  "Choose Limiter (1/2)", 3)

if r1 == 6 then
  choice = 1
elseif r1 == 7 then
  choice = 2
elseif r1 == 2 then
  -- Page 2
  local r2 = reaper.ShowMessageBox(
    "More limiters:\n\n"
    .. "YES = 3. Env V3 (peak-only, Accessor only)\n"
    .. "NO = 4. Env Item V2 (take volume envelope, no FX)\n\n"
    .. "(Cancel to abort)",
    "Choose Limiter (3/4)", 3)
  if r2 == 6 then
    choice = 3
  elseif r2 == 7 then
    choice = 4
  else
    return
  end
end

if not choice then return end

local lim = LIMITERS[choice]
if lim.cmd == 0 then
  reaper.MB("Script not registered: " .. lim.name .. "\nInstall the headless version first.",
            "Batch Envelope Limiter V2", 0)
  return
end

-- Read existing params from file (if any)
local current = {}
local f = io.open(lim.params_file, "r")
if f then
  for line in f:lines() do
    local key, val = line:match("(%S+)%s*=%s*(.+)")
    if key then current[key] = val:match("^%s*(.-)%s*$") end
  end
  f:close()
end

-- Build defaults from file or hardcoded
local values = {}
for i, field in ipairs(lim.fields) do
  values[#values + 1] = current[field] or lim.defaults[i]
end

-- Dialog 2: Edit params
local field_labels = table.concat(lim.fields, ",")
local field_defaults = table.concat(values, ",")

local retval2, input2 = reaper.GetUserInputs(
  lim.name .. " — Settings (" .. item_count .. " items)", #lim.fields,
  field_labels .. ",extrawidth=60",
  field_defaults)
if not retval2 then return end

-- Parse input and write params file
local new_values = {}
for v in input2:gmatch("([^,]+)") do
  new_values[#new_values + 1] = v:match("^%s*(.-)%s*$")
end

local pf = io.open(lim.params_file, "w")
for i, field in ipairs(lim.fields) do
  pf:write(field .. "=" .. (new_values[i] or lim.defaults[i]) .. "\n")
end
pf:close()

-- Store items: position + track GUID (robust across modifications)
-- Process in REVERSE order so changes on later items don't shift earlier ones
local items_info = {}
for i = 0, item_count - 1 do
  local item = reaper.GetSelectedMediaItem(0, i)
  local pos = reaper.GetMediaItemInfo_Value(item, "D_POSITION")
  local len = reaper.GetMediaItemInfo_Value(item, "D_LENGTH")
  local track = reaper.GetMediaItem_Track(item)
  local track_guid = reaper.GetTrackGUID(track)
  items_info[#items_info + 1] = {pos = pos, len = len, track_guid = track_guid}
end

table.sort(items_info, function(a, b) return a.pos > b.pos end)

-- Helper: find item by position and track
local function find_item(pos, track_guid)
  local total = reaper.CountMediaItems(0)
  local best = nil
  local best_dist = math.huge
  for i = 0, total - 1 do
    local it = reaper.GetMediaItem(0, i)
    local it_pos = reaper.GetMediaItemInfo_Value(it, "D_POSITION")
    local it_track = reaper.GetMediaItem_Track(it)
    local it_tguid = reaper.GetTrackGUID(it_track)
    if it_tguid == track_guid then
      local dist = math.abs(it_pos - pos)
      if dist < best_dist then
        best_dist = dist
        best = it
      end
    end
  end
  if best_dist < 0.001 then return best end
  return nil
end

local processed = 0
local skipped = 0
local errors = {}
local log_file = os.getenv("HOME") .. "/batch_env_limiter_log.txt"
local log = io.open(log_file, "w")
log:write("Limiter: " .. lim.name .. "\n")
log:write("Params: " .. input2 .. "\n\n")

for idx, info in ipairs(items_info) do
  local item = find_item(info.pos, info.track_guid)
  if item then
    log:write(string.format("Item %d: pos=%.3f len=%.3f — ", idx, info.pos, info.len))

    -- Set time selection to item bounds
    reaper.GetSet_LoopTimeRange(true, false, info.pos, info.pos + info.len, false)

    -- Select the item's track
    local track = reaper.GetMediaItem_Track(item)
    reaper.SetOnlyTrackSelected(track)

    -- Deselect all items, select just this one
    reaper.SelectAllMediaItems(0, false)
    reaper.SetMediaItemSelected(item, true)

    -- Commit state
    reaper.UpdateArrange()

    -- Run the limiter
    reaper.Main_OnCommand(lim.cmd, 0)

    -- Check results file if available
    if lim.results_file then
      local rf = io.open(lim.results_file, "r")
      if rf then
        local first_line = rf:read("*l") or ""
        rf:close()
        if first_line:match("^ERROR") then
          log:write("ERROR: " .. first_line .. "\n")
          errors[#errors + 1] = string.format("Item %d (pos=%.1f): %s", idx, info.pos, first_line)
        else
          log:write("OK\n")
        end
      else
        log:write("OK (no results file)\n")
      end
    else
      log:write("OK\n")
    end

    processed = processed + 1
  else
    skipped = skipped + 1
    log:write(string.format("Item %d: pos=%.3f — SKIPPED (not found)\n", idx, info.pos))
  end
end

log:close()

-- Clear time selection
reaper.GetSet_LoopTimeRange(true, false, 0, 0, false)
reaper.UpdateArrange()

if SHOW_RESULT then
  local msg = processed .. " of " .. item_count .. " items processed."
  if skipped > 0 then
    msg = msg .. "\n" .. skipped .. " items skipped (not found)."
  end
  if #errors > 0 then
    msg = msg .. "\n\nErrors:\n" .. table.concat(errors, "\n")
  end
  msg = msg .. "\n\nLog: ~/batch_env_limiter_log.txt"
  reaper.MB(msg, "Batch Envelope Limiter V2", 0)
end
