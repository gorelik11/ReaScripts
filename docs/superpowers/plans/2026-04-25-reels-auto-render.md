# Reels Auto-Render Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Automatically build a tempo map, create ~50 reel regions at bar boundaries, and sequentially render each reel with fade-out and video-flash prevention.

**Architecture:** Two scripts. A Python script (external, via reapy) runs madmom beat detection, sets tempo markers, and creates reel regions. A Lua script (inside REAPER) iterates reel regions and renders each one with temporary split/fade/nudge.

**Tech Stack:** Python 3, madmom, soundfile, reapy; Lua (REAPER ReaScript)

---

## File Structure

| File | Responsibility |
|------|---------------|
| `reels_tempo_map.py` | Phase 1+2: madmom analysis, tempo markers, reel region creation. Runs externally via `python3`. |
| `Reels Sequential Render.lua` | Phase 3: iterates reel regions, does split/fade/nudge per reel, renders, undoes. Runs inside REAPER. |

---

### Task 1: Python Script — Madmom Tempo Map + Reel Regions

**Files:**
- Create: `reels_tempo_map.py`

This is a single-run workflow script. It connects to REAPER via reapy, reads song regions, runs madmom analysis, sets tempo markers, and creates reel regions. No TDD — this is tested interactively against the live REAPER project.

- [ ] **Step 1: Scaffold script with reapy connection and region reading**

```python
#!/usr/bin/env python3
"""
Reels Auto-Render: Tempo Map + Reel Region Creator
Reads song regions from REAPER, runs madmom beat detection,
sets tempo markers, and creates reel regions at bar boundaries.
"""

import reapy
import numpy as np
import soundfile as sf
from madmom.features.downbeats import RNNDownBeatProcessor, DBNDownBeatTrackingProcessor

FADE_DURATION = 3.0  # seconds
TARGET_REEL_DURATION = 57.0  # 60s minus fade

# Compositions to analyze: (region_name_substring, beats_per_bar, time_sig_num, time_sig_denom)
COMPOSITIONS = [
    ("Cafe On the Beach", 7, 7, 8),
    ("Beskid's Air", 4, 4, 4),
    ("Shinanim Shinanim", 4, 4, 4),
    ("Trzcina", 4, 4, 4),
    ("Elhayaar", 4, 12, 8),   # 12/8 = 4 dotted-quarter groups for madmom
    ("Karapaty", 4, 4, 4),
]

# Skip these (manual reel creation):
SKIP = ["Italo Disco", "Rubato Intro"]


def get_audio_source_path(project):
    """Get the audio file path from track 1 (Dima Gorelik Trio HD)."""
    track = project.tracks[1]
    item = track.items[0]
    take = item.active_take
    source = take.source
    return source.filename


def get_song_regions(project):
    """Read all regions from the project, return list of (name, start, end)."""
    regions = []
    i = 0
    while True:
        ret = reapy.reascript_api.RPR_EnumProjectMarkers3(
            0, i, 0, 0.0, 0.0, "", 0, 0
        )
        # ret: (retval, proj, idx, isrgn, pos, rgnend, name, name_sz, markrgnindexnumber)
        if ret[0] == 0:
            break
        idx, is_rgn, pos, rgnend, name = ret[0], ret[3], ret[4], ret[5], ret[6]
        if is_rgn:
            regions.append({"name": name, "start": pos, "end": rgnend, "idx": ret[8]})
        i += 1
    return regions


def main():
    project = reapy.Project()
    audio_path = get_audio_source_path(project)
    print(f"Audio source: {audio_path}")

    song_regions = get_song_regions(project)
    print(f"Found {len(song_regions)} regions:")
    for r in song_regions:
        print(f"  {r['name']}: {r['start']:.1f}s - {r['end']:.1f}s")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run script to verify reapy connection and region reading**

Run: `python3 reels_tempo_map.py`
Expected: prints audio source path and lists all 8 regions with correct times.

- [ ] **Step 3: Add madmom beat detection function**

Add after `get_song_regions`:

```python
def analyze_beats(audio_path, start, end, beats_per_bar):
    """Run madmom downbeat detection on an audio segment.
    Returns array of (time, beat_number) where beat_number=1 is a downbeat.
    Times are in project time (offset by region start).
    """
    audio, sr = sf.read(audio_path, start=int(start * 44100), stop=int(end * 44100))
    if audio.ndim > 1:
        audio = np.mean(audio, axis=1)  # mono

    proc = RNNDownBeatProcessor()
    activations = proc(audio)
    dbn = DBNDownBeatTrackingProcessor(beats_per_bar=[beats_per_bar], fps=100)
    beats = dbn(activations)

    # beats: array of (time_in_segment, beat_number)
    # Convert to project time
    beats[:, 0] += start
    return beats


def get_downbeats(beats):
    """Extract downbeat times (beat_number == 1) from madmom output."""
    return beats[beats[:, 1] == 1, 0]
```

- [ ] **Step 4: Add BPM calculation and tempo marker setting**

Add after `get_downbeats`:

```python
def calculate_bpm(downbeats, time_sig_num, time_sig_denom):
    """Calculate BPM for each bar from downbeat intervals.
    REAPER BPM is always quarter-note based.
    For x/4: quarter_notes_per_bar = x
    For x/8: quarter_notes_per_bar = x / 2
    """
    if time_sig_denom == 4:
        quarter_notes_per_bar = time_sig_num
    elif time_sig_denom == 8:
        quarter_notes_per_bar = time_sig_num / 2.0
    else:
        quarter_notes_per_bar = time_sig_num

    bpms = []
    for i in range(len(downbeats) - 1):
        bar_duration = downbeats[i + 1] - downbeats[i]
        if bar_duration > 0:
            bpm = quarter_notes_per_bar * 60.0 / bar_duration
            bpms.append((downbeats[i], bpm))
    return bpms


def set_tempo_markers(project, bpms, time_sig_num, time_sig_denom, region_start):
    """Set tempo markers in REAPER. First marker also sets time signature."""
    with reapy.inside_reaper():
        for i, (time, bpm) in enumerate(bpms):
            # Filter outliers (< 30 or > 300 BPM)
            if bpm < 30 or bpm > 300:
                continue
            if i == 0:
                # First marker: set time signature too
                reapy.reascript_api.RPR_SetTempoTimeSigMarker(
                    0, -1, time, -1, -1, bpm, time_sig_num, time_sig_denom, False
                )
            else:
                reapy.reascript_api.RPR_SetTempoTimeSigMarker(
                    0, -1, time, -1, -1, bpm, 0, 0, False
                )
        reapy.reascript_api.RPR_UpdateTimeline()
```

- [ ] **Step 5: Add reel region creation**

Add after `set_tempo_markers`:

```python
def create_reel_regions(project, composition_name, downbeats, region_end):
    """Create reel regions at bar boundaries, ~57s apart + 3s fade.
    Regions placed on lane 2 via SetProjectMarker4 flags.
    """
    reel_num = 1
    reel_start = downbeats[0]
    created = []

    for db in downbeats[1:]:
        elapsed = db - reel_start
        if elapsed >= TARGET_REEL_DURATION:
            # This downbeat is the cut point
            reel_end = db + FADE_DURATION
            # Don't extend past region end
            reel_end = min(reel_end, region_end)
            name = f"{composition_name} - Reel {reel_num:02d}"

            # Create region
            rgn_idx = reapy.reascript_api.RPR_AddProjectMarker2(
                0, True, reel_start, reel_end, name, -1, 0
            )

            # Set to lane 2: flags bit 8+ = lane number
            # Lane 2 means flags = (2 << 8) | existing_flags
            lane_flags = 2 << 8
            reapy.reascript_api.RPR_SetProjectMarker4(
                0, rgn_idx, True, reel_start, reel_end, name, 0, lane_flags
            )

            created.append({"name": name, "start": reel_start, "end": reel_end})
            reel_num += 1
            reel_start = db  # Next reel starts at this downbeat

    # Final segment: from last reel_start to region_end
    if reel_start < region_end - 5:  # Skip if less than 5s remaining
        reel_end = region_end
        name = f"{composition_name} - Reel {reel_num:02d}"
        rgn_idx = reapy.reascript_api.RPR_AddProjectMarker2(
            0, True, reel_start, reel_end, name, -1, 0
        )
        lane_flags = 2 << 8
        reapy.reascript_api.RPR_SetProjectMarker4(
            0, rgn_idx, True, reel_start, reel_end, name, 0, lane_flags
        )
        created.append({"name": name, "start": reel_start, "end": reel_end})

    return created
```

- [ ] **Step 6: Wire up main() with full pipeline**

Replace the `main()` function:

```python
def main():
    project = reapy.Project()
    audio_path = get_audio_source_path(project)
    print(f"Audio source: {audio_path}")

    song_regions = get_song_regions(project)
    print(f"Found {len(song_regions)} regions")

    total_reels = 0

    for comp_name, beats_per_bar, ts_num, ts_denom in COMPOSITIONS:
        # Find matching region
        region = None
        for r in song_regions:
            if comp_name in r["name"]:
                region = r
                break

        if region is None:
            print(f"WARNING: Region not found for '{comp_name}', skipping")
            continue

        # For Elhayaar, start analysis after rubato intro
        analysis_start = region["start"]
        if "Elhayaar" in comp_name and "Rubato" not in comp_name:
            # Rubato intro ends at ~2166.6s
            analysis_start = 2166.6

        print(f"\nAnalyzing: {comp_name} ({ts_num}/{ts_denom})")
        print(f"  Range: {analysis_start:.1f}s - {region['end']:.1f}s")

        # Phase 1: Beat detection
        beats = analyze_beats(audio_path, analysis_start, region["end"], beats_per_bar)
        downbeats = get_downbeats(beats)
        print(f"  Found {len(downbeats)} downbeats")

        if len(downbeats) < 2:
            print(f"  WARNING: Too few downbeats, skipping")
            continue

        # Phase 1: Tempo markers
        bpms = calculate_bpm(downbeats, ts_num, ts_denom)
        set_tempo_markers(project, bpms, ts_num, ts_denom, analysis_start)
        print(f"  Set {len(bpms)} tempo markers")

        # Phase 2: Reel regions
        reels = create_reel_regions(project, comp_name, downbeats, region["end"])
        total_reels += len(reels)
        print(f"  Created {len(reels)} reel regions:")
        for reel in reels:
            dur = reel['end'] - reel['start']
            print(f"    {reel['name']}: {dur:.1f}s")

    print(f"\nDone! Created {total_reels} reel regions total.")
    print("Review regions in REAPER, then run 'Reels Sequential Render.lua'")


if __name__ == "__main__":
    main()
```

- [ ] **Step 7: Test on one composition first**

Temporarily change `COMPOSITIONS` to only include `("Karapaty", 4, 4, 4)` (simplest case).

Run: `python3 reels_tempo_map.py`

Verify in REAPER:
- Tempo markers appear within Karapaty region
- BPM values look reasonable (~120-180 for a 4/4 piece)
- Reel regions appear (check if lane 2 works, if not — regions are still created)
- Each reel is approximately 60s

If `SetProjectMarker4` flags for lane don't work, fall back: create regions normally, user drags to lane 2.

- [ ] **Step 8: Run full pipeline on all 6 compositions**

Restore full `COMPOSITIONS` list.

Run: `python3 reels_tempo_map.py`

Verify: tempo markers and reel regions for all 6 compositions. User reviews and adjusts boundaries as needed.

- [ ] **Step 9: Commit**

```bash
git add reels_tempo_map.py
git commit -m "feat: add reels tempo map and region creator (madmom + reapy)"
```

---

### Task 2: Lua Script — Sequential Render with Fade/Nudge

**Files:**
- Create: `Reels Sequential Render.lua`

- [ ] **Step 1: Write the reel region collector**

```lua
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
  -- Sort by start time
  table.sort(reels, function(a, b) return a.start < b.start end)
  return reels
end
```

- [ ] **Step 2: Write the split/fade/nudge/render/undo core**

Add after `collect_reel_regions`:

```lua
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
  local fade_start = reel.rgnend - FADE_DURATION
  local split_time = reel.rgnend

  -- Begin undo block for all prep modifications
  reaper.Undo_BeginBlock()
  reaper.PreventUIRefresh(1)

  -- Set time selection to reel region
  reaper.GetSet_LoopTimeRange2(0, true, false, reel.start, reel.rgnend, false)

  -- Set render filename pattern
  reaper.GetSetProjectInfo_String(0, "RENDER_PATTERN", reel.name, true)

  local split_items = {}  -- {track_idx, original_item, new_item}

  for _, track_idx in ipairs({VIDEO_TRACK_IDX, AUDIO_TRACK_IDX}) do
    local item = get_item_at_time(track_idx, split_time - 0.001)
    if item then
      -- Split at region end
      local new_item = reaper.SplitMediaItem(item, split_time)
      if new_item then
        -- Set fade out on the first part (pre-split)
        reaper.SetMediaItemInfo_Value(item, "D_FADEOUTLEN", FADE_DURATION)

        -- Nudge second part forward
        local new_pos = reaper.GetMediaItemInfo_Value(new_item, "D_POSITION")
        reaper.SetMediaItemInfo_Value(new_item, "D_POSITION", new_pos + NUDGE_AMOUNT)

        table.insert(split_items, {
          track_idx = track_idx,
          item = item,
          new_item = new_item,
        })
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
```

- [ ] **Step 3: Write main execution loop with progress**

Add after `render_single_reel`:

```lua
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
```

- [ ] **Step 4: Test on a single reel region**

Create one test reel region manually in REAPER (name it "Test - Reel 01"). Run the Lua script. Verify:
- Time selection is set correctly
- Item is split at region end
- Fade out appears on the pre-split portion
- Post-split item is nudged forward
- Render produces a file with correct name
- After render, the split/fade/nudge is undone (items restored to original state)

If the undo doesn't fully restore (e.g., split leaves artifacts), switch to manual restore approach instead of `Undo_DoUndo2`.

- [ ] **Step 5: Handle edge case — last reel of a composition**

The last reel's region end might be at or past the item end. In that case, there's nothing to split/nudge — just add fade out.

Update `render_single_reel` — replace the split logic with:

```lua
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
          table.insert(split_items, {
            track_idx = track_idx,
            item = item,
            new_item = new_item,
          })
        end
      else
        -- Last reel: just add fade out, no split needed
        reaper.SetMediaItemInfo_Value(item, "D_FADEOUTLEN", FADE_DURATION)
      end
    end
```

- [ ] **Step 6: Full render test**

Run `Reels Sequential Render.lua` with all reel regions present. Monitor:
- Console output shows progress `[1/N] Rendering: ...`
- Each render completes without errors
- After all renders, items are back to original state (no splits, no fades)
- Output files exist in project directory with correct names

- [ ] **Step 7: Commit**

```bash
git add "Reels Sequential Render.lua"
git commit -m "feat: add sequential reel renderer with fade-out and video-flash prevention"
```

---

### Task 3: Verify Region Lane 2

**Files:**
- Modify: `reels_tempo_map.py` (if needed)

- [ ] **Step 1: Test SetProjectMarker4 lane flags**

After running `reels_tempo_map.py`, check in REAPER if reel regions appear on lane 2. The flag encoding `lane << 8` is undocumented and may not work.

If regions are on lane 1 (default):

- [ ] **Step 2 (fallback): Use chunk editing for lane assignment**

Replace `SetProjectMarker4` lane logic in `reels_tempo_map.py` with a post-processing step:

```python
def set_regions_to_lane2(project):
    """Move all reel regions to lane 2 by editing project state chunk."""
    with reapy.inside_reaper():
        # Get project chunk
        chunk = reapy.reascript_api.RPR_GetSetProjectInfo_String(
            0, "PROJECT_STATE", "", False
        )
        # This approach may not work — REAPER doesn't expose full project chunk via API
        # Alternative: user selects all reel regions and uses REAPER's region lane UI
    print("NOTE: If regions are not on lane 2, select them and drag to lane 2 in REAPER")
```

If chunk editing is not feasible, document: "After running the Python script, select all 'Reel' regions in the Region/Marker Manager and drag to lane 2."

- [ ] **Step 3: Commit if changes were made**

```bash
git add reels_tempo_map.py
git commit -m "fix: region lane assignment fallback"
```
