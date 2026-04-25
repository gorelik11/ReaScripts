-- Reels Sequential Render.lua
-- Iterates reel regions (matching "Reel" in name), renders each with
-- 3s fade-out and video-flash prevention (split + nudge).
--
-- Prerequisites:
--   - Reel regions created by reels_tempo_map.py
--   - Render settings configured in render dialog (AVFoundation, Bus track)
--   - Bus track (track index 2) selected

local FADE_DURATION = 3.0
local NUDGE_AMOUNT = 0.04  -- ~1 frame at 25fps
local VIDEO_TRACK_IDX = 0  -- "Elha"
local AUDIO_TRACK_IDX = 1  -- "Dima Gorelik Trio HD"

function collect_reel_regions()
  local reels = {}
  local i = 0
  while true do
    local ret, isrgn, pos, rgnend, name, markrgnidx = reaper.EnumProjectMarkers(i)
    if ret == 0 then break end
    if isrgn and name:find("Reel") then
      table.insert(reels, {
        name = name,
        start = pos,
        rgnend = rgnend,
        idx = markrgnidx,
      })
    end
    i = i + 1
  end
  table.sort(reels, function(a, b) return a.start < b.start end)
  return reels
end

function get_item_at_time(track_idx, time)
  local track = reaper.GetTrack(0, track_idx)
  local n = reaper.GetTrackNumMediaItems(track)
  for i = 0, n - 1 do
    local item = reaper.GetTrackMediaItem(track, i)
    local pos = reaper.GetMediaItemInfo_Value(item, "D_POSITION")
    local len = reaper.GetMediaItemInfo_Value(item, "D_LENGTH")
    if pos <= time and pos + len > time then
      return item
    end
  end
  return nil
end

function render_single_reel(reel)
  local split_time = reel.rgnend

  reaper.Undo_BeginBlock()
  reaper.PreventUIRefresh(1)

  -- Set time selection to reel region
  reaper.GetSet_LoopTimeRange2(0, true, false, reel.start, reel.rgnend, false)

  -- Set render filename pattern
  reaper.GetSetProjectInfo_String(0, "RENDER_PATTERN", reel.name, true)

  for _, track_idx in ipairs({VIDEO_TRACK_IDX, AUDIO_TRACK_IDX}) do
    local item = get_item_at_time(track_idx, split_time - 0.001)
    if item then
      local item_end = reaper.GetMediaItemInfo_Value(item, "D_POSITION")
                     + reaper.GetMediaItemInfo_Value(item, "D_LENGTH")

      if split_time < item_end - 0.01 then
        -- Normal case: split, fade, nudge
        local new_item = reaper.SplitMediaItem(item, split_time)
        if new_item then
          reaper.SetMediaItemInfo_Value(item, "D_FADEOUTLEN", FADE_DURATION)
          local new_pos = reaper.GetMediaItemInfo_Value(new_item, "D_POSITION")
          reaper.SetMediaItemInfo_Value(new_item, "D_POSITION", new_pos + NUDGE_AMOUNT)
        end
      else
        -- Last reel: just add fade out, no split needed
        reaper.SetMediaItemInfo_Value(item, "D_FADEOUTLEN", FADE_DURATION)
      end
    end
  end

  reaper.PreventUIRefresh(-1)
  reaper.UpdateArrange()
  reaper.Undo_EndBlock("Reel render prep: " .. reel.name, -1)

  -- Render using most recent settings
  reaper.Main_OnCommand(42230, 0)

  -- Undo the prep (split + fade + nudge)
  reaper.Undo_DoUndo2(0)
  reaper.UpdateArrange()
end

function main()
  local reels = collect_reel_regions()

  if #reels == 0 then
    reaper.ShowMessageBox(
      "No reel regions found. Run reels_tempo_map.py first.",
      "Reels Sequential Render", 0
    )
    return
  end

  local msg = string.format("Found %d reel regions.\n\nFirst: %s\nLast: %s\n\nStart rendering?",
    #reels, reels[1].name, reels[#reels].name)

  local ok = reaper.ShowMessageBox(msg, "Reels Sequential Render", 1)
  if ok ~= 1 then return end

  -- Save current render pattern to restore later
  local _, orig_pattern = reaper.GetSetProjectInfo_String(0, "RENDER_PATTERN", "", false)

  for i, reel in ipairs(reels) do
    reaper.ShowConsoleMsg(string.format("[%d/%d] Rendering: %s\n", i, #reels, reel.name))
    render_single_reel(reel)
  end

  -- Restore original render pattern
  reaper.GetSetProjectInfo_String(0, "RENDER_PATTERN", orig_pattern, true)

  reaper.ShowMessageBox(
    string.format("Done! Rendered %d reels.", #reels),
    "Reels Sequential Render", 0
  )
end

main()
