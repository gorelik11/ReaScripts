-- Batch Apply Envelope Limiter V1.0
-- Apply an envelope limiter script to multiple selected items sequentially.
-- Dialog: choose limiter + edit params before processing.
-- Same settings apply to all items.
--
-- Supported limiters:
--   1 = RCBit LUFS Env V3 (LUFS + peak, Combined/Micro, SWS/DryRun)
--   2 = RCBit Env V3 (peak-only, Combined/Micro)
--   3 = RCBit Env V2 Headless (peak-only, legacy)
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
  { name = "Env V3",
    named_id = "RSe9fe067871887f09aa5bbd335f1abd5d98039461",
    params_file = os.getenv("HOME") .. "/rcbit_env_v3_params.txt",
    results_file = os.getenv("HOME") .. "/rcbit_env_v3_results.txt",
    fields = {"CEILING_DB", "ATTACK_MS", "RELEASE_MS", "WINDOW_MS", "FX_SCOPE", "LIMITER_MODE"},
    defaults = {"-0.5", "0", "70", "5", "TakeFX", "Combined"},
  },
  { name = "Env V2",
    named_id = "RS1c4348d09651fe5579f8afcf6718da1b3f1c4460",
    params_file = os.getenv("HOME") .. "/rcbit_env_v2_params.txt",
    results_file = os.getenv("HOME") .. "/rcbit_env_v2_results.txt",
    fields = {"CEILING_DB", "ATTACK_MS", "RELEASE_MS", "WINDOW_MS", "FX_SCOPE"},
    defaults = {"-0.5", "0", "70", "5", "TakeFX"},
  },
  { name = "Env Item V2",
    named_id = "RS4375420f21dd272912c446862e28aef2756cfd53",
    params_file = os.getenv("HOME") .. "/env_item_limiter_v2_params.txt",
    results_file = os.getenv("HOME") .. "/env_item_limiter_v2_results.txt",
    fields = {"CEILING_DB", "ATTACK_MS", "RELEASE_MS", "WINDOW_MS"},
    defaults = {"-0.5", "0", "70", "5"},
  },
}

local DEFAULT_CHOICE = 1
-----------------------------------------------------

-- Find headless scripts by searching in REAPER Scripts folder
local scripts_dir = reaper.GetResourcePath() .. "/Scripts/"

local headless_paths = {
  [1] = scripts_dir .. "RCBit LUFS Envelope Limiter V3.0 Headless.lua",
  [2] = scripts_dir .. "RCBit Envelope Limiter V3.0 Headless.lua",
  [4] = scripts_dir .. "Envelope Based Limiter (Item) V2.0 Headless.lua",
}

-- Resolve named command IDs
for i, lim in ipairs(LIMITERS) do
  if lim.named_id ~= "" then
    lim.cmd = reaper.NamedCommandLookup("_" .. lim.named_id)
  elseif headless_paths[i] then
    -- Try to find script by checking if file exists, then lookup
    local f = io.open(headless_paths[i], "r")
    if f then
      f:close()
      -- Register if not already
      local action_id = reaper.AddRemoveReaScript(true, 0, headless_paths[i], true)
      if action_id > 0 then
        lim.cmd = action_id
        local named = reaper.ReverseNamedCommandLookup(action_id)
        if named then lim.named_id = named end
      end
    end
  end
  if not lim.cmd or lim.cmd == 0 then lim.cmd = 0 end
end

local item_count = reaper.CountSelectedMediaItems(0)
if item_count == 0 then
  reaper.MB("No items selected.\nSelect one or more items and run again.",
            "Batch Envelope Limiter", 0)
  return
end

-- Dialog 1: Choose limiter
local names = {}
for i, lim in ipairs(LIMITERS) do
  local avail = lim.cmd > 0 and "" or " [N/A]"
  names[#names + 1] = tostring(i) .. "=" .. lim.name .. avail
end

local retval, input = reaper.GetUserInputs(
  "Batch Envelope Limiter — " .. item_count .. " item(s)", 1,
  table.concat(names, "  ") .. ":,extrawidth=120",
  tostring(DEFAULT_CHOICE))
if not retval then return end

local choice = tonumber(input)
if not choice or not LIMITERS[choice] then
  reaper.MB("Invalid choice. Enter 1-" .. #LIMITERS, "Batch Envelope Limiter", 0)
  return
end

local lim = LIMITERS[choice]
if lim.cmd == 0 then
  reaper.MB("Script not registered: " .. lim.name .. "\nInstall the headless version first.",
            "Batch Envelope Limiter", 0)
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
  lim.name .. " — Settings", #lim.fields,
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
  reaper.MB(msg, "Batch Envelope Limiter", 0)
end
