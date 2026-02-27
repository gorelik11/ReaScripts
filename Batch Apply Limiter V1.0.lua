-- Batch Apply Limiter V1.0
-- Apply a limiter script to multiple selected items sequentially.
-- Each item is processed with the same settings (from params file).
--
-- Usage: Select multiple items → run this script → choose limiter → done.
-- The limiter's params file must already exist from a previous run.
--
-- Params files:
--   LUFS V8: ~/rcbit_v8_params.txt
--   Lim  V8: ~/rcbit_limiter_v8_params.txt
--   LUFS V6: ~/rcbit_v6_params.txt
--   Env  V2: uses dialog defaults (no params file)

-----------------------------------------------------
-- SETTINGS
-----------------------------------------------------
local SHOW_DIALOG = true
local SHOW_RESULT = true

-- Available limiters (named command IDs — stable across sessions)
local LIMITERS = {
  {name = "LUFS V8", named_id = "RS72928ed6d26d21c6144d6783cf9e05c354d76e92"},
  {name = "Lim V8",  named_id = "RS5651d862b4148716f74908abb57c1a2cfd7a9960"},
  {name = "LUFS V6", named_id = "RS4ea15987de3ed846432f69e3d60adc9ad58169d9"},
  {name = "Env V2",  named_id = "RS8f4e25e7c9483f84b16046235f77e72409c75f4d"},
}
local DEFAULT_CHOICE = 1  -- LUFS V8
-----------------------------------------------------

local item_count = reaper.CountSelectedMediaItems(0)
if item_count == 0 then
  reaper.MB("No items selected.\nSelect one or more items and run again.",
            "Batch Limiter", 0)
  return
end

-- Resolve named command IDs to numeric
for _, lim in ipairs(LIMITERS) do
  lim.cmd = reaper.NamedCommandLookup("_" .. lim.named_id)
end

-- Choose limiter
local action_id = LIMITERS[DEFAULT_CHOICE].cmd

if SHOW_DIALOG then
  -- Build choice list
  local names = {}
  for i, lim in ipairs(LIMITERS) do
    names[#names + 1] = tostring(i) .. "=" .. lim.name
  end
  local prompt = table.concat(names, "  ")

  local retval, input = reaper.GetUserInputs(
    "Batch Limiter — " .. item_count .. " item(s)", 1,
    prompt .. ":,extrawidth=60",
    tostring(DEFAULT_CHOICE))
  if not retval then return end

  local choice = tonumber(input)
  if not choice or not LIMITERS[choice] then
    reaper.MB("Invalid choice. Enter 1-" .. #LIMITERS, "Batch Limiter", 0)
    return
  end
  action_id = LIMITERS[choice].cmd

  if action_id == 0 then
    reaper.MB("Script not registered: " .. LIMITERS[choice].name ..
              "\nCheck Action List.", "Batch Limiter", 0)
    return
  end
end

-- Store items: position + length + track GUID (robust across splits)
-- Process in REVERSE order so splits on later items don't shift earlier items
local items_info = {}
for i = 0, item_count - 1 do
  local item = reaper.GetSelectedMediaItem(0, i)
  local pos = reaper.GetMediaItemInfo_Value(item, "D_POSITION")
  local len = reaper.GetMediaItemInfo_Value(item, "D_LENGTH")
  local track = reaper.GetMediaItem_Track(item)
  local track_guid = reaper.GetTrackGUID(track)
  items_info[#items_info + 1] = {pos = pos, len = len, track_guid = track_guid}
end

-- Sort by position descending (process last item first)
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
local log_file = os.getenv("HOME") .. "/batch_limiter_log.txt"
local log = io.open(log_file, "w")

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
    reaper.Main_OnCommand(action_id, 0)

    processed = processed + 1
    log:write("OK\n")
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
  reaper.MB(msg, "Batch Limiter", 0)
end
