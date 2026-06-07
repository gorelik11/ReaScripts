# -*- coding: utf-8 -*-
"""
Universal Madmom Tempo Map (REAPER ReaScript)
Run inside REAPER: Actions > ReaScript > Run...

Workflow:
1. Select one or more audio items in REAPER
2. Run this script
3. Enter time signature (e.g. "7/8", "4/4", "12/8")
4. Optional: place a marker named "first beat" to anchor downbeat phase
5. Script calls external madmom via subprocess, creates tempo markers

For multiple songs: render region render matrix to 44/16 WAV,
"Add rendered items to new tracks in project", select items, run script.
"""

import os
import sys
import json
import subprocess

def log(m):
    RPR_ShowConsoleMsg(str(m) + "\n")

# -- SETTINGS ------------------------------------------------------
# Madmom lives in a dedicated venv, NOT REAPER's Python nor the framework
# Python — only this interpreter has madmom/soundfile/numpy<2 installed.
PYTHON_EXE = os.path.expanduser("~/.venvs/madmom/bin/python3")
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__)) if "__file__" in dir() else os.path.expanduser("~/ReaScripts")
ANALYZER_SCRIPT = os.path.join(SCRIPT_DIR, "reels_madmom_analyze.py")
OUTPUT_JSON = os.path.join(os.path.expanduser("~"), "madmom_result.json")


# -- PARSE TIME SIGNATURE ------------------------------------------

def parse_time_sig(ts_string):
    """Parse '7/8' -> (num, denom, beats_per_bar).
    Compound meters (6/8,9/8,12/8): beats = num/3
    Additive meters (5/8,7/8,11/8): beats = num
    Simple meters (x/4): beats = num
    """
    parts = ts_string.strip().split("/")
    if len(parts) != 2:
        return None, None, None
    try:
        num, denom = int(parts[0]), int(parts[1])
    except ValueError:
        return None, None, None
    if num <= 0 or denom <= 0:
        return None, None, None

    if denom == 8 and num % 3 == 0 and num >= 6:
        beats_per_bar = num // 3  # compound
    elif denom == 8:
        beats_per_bar = num  # additive
    else:
        beats_per_bar = num  # simple (x/4, x/2)

    return num, denom, beats_per_bar


def calc_quarter_notes_per_bar(ts_num, ts_denom):
    """REAPER BPM is always quarter-note based."""
    if ts_denom == 4:
        return ts_num
    elif ts_denom == 8:
        return ts_num / 2.0
    elif ts_denom == 2:
        return ts_num * 2
    return ts_num


# -- FIND FIRST BEAT MARKER -----------------------------------------

def find_first_beat_marker(item_start, item_end):
    """Find marker named 'first beat' within item boundaries. Returns time or None."""
    i = 0
    while True:
        ret = RPR_EnumProjectMarkers(i, 0, 0.0, 0.0, "", 0)
        if ret[0] == 0:
            break
        is_rgn, pos, rgnend, name, markrgnidx = ret[1], ret[2], ret[3], ret[4], ret[5]
        if not is_rgn and name.lower().strip() == "first beat":
            if item_start <= pos <= item_end:
                return pos
        i += 1
    return None


# -- GET SELECTED ITEMS ---------------------------------------------

def get_selected_items():
    """Get all selected media items with their audio paths and positions."""
    items = []
    n = RPR_CountSelectedMediaItems(0)
    for i in range(n):
        item = RPR_GetSelectedMediaItem(0, i)
        take = RPR_GetActiveTake(item)
        if not take:
            continue
        source = RPR_GetMediaItemTake_Source(take)
        audio_path = RPR_GetMediaSourceFileName(source, "", 512)[1]
        position = RPR_GetMediaItemInfo_Value(item, "D_POSITION")
        length = RPR_GetMediaItemInfo_Value(item, "D_LENGTH")
        startoffs = RPR_GetMediaItemInfo_Value(item, "D_STARTOFFS")
        playrate = RPR_GetMediaItemInfo_Value(item, "D_PLAYRATE")
        name = RPR_GetTakeName(take)
        items.append({
            "item": item,
            "take": take,
            "audio_path": audio_path,
            "position": position,
            "length": length,
            "startoffs": startoffs,
            "playrate": playrate if playrate else 1.0,
            "name": name,
        })
    return items


# -- ANALYSIS WINDOW: time selection > item bounds > whole file ------

def get_time_selection():
    """Return (start, end) project times of the loop/time selection, or None.

    REAPER reports an empty selection as start == end.
    """
    ret = RPR_GetSet_LoopTimeRange(False, False, 0.0, 0.0, False)
    start, end = ret[2], ret[3]
    if end <= start:
        return None
    return (start, end)


def compute_analysis_window(item_position, item_length, startoffs, playrate, ts_range):
    """Decide which slice of the SOURCE file to analyze for one item.

    Priority: an overlapping time selection, else the item's own bounds (which,
    for an untrimmed item, is the whole file).

    Returns (src_start, src_end, window_proj_start) where src_* are seconds into
    the source file and window_proj_start is the project time the window begins
    at — or None if a time selection exists but does not touch this item.

    Source/project mapping: src = startoffs + (proj - item_position) * playrate.
    """
    item_end = item_position + item_length
    if ts_range is not None:
        p0 = max(ts_range[0], item_position)
        p1 = min(ts_range[1], item_end)
        if p1 <= p0:
            return None
    else:
        p0, p1 = item_position, item_end

    src_start = startoffs + (p0 - item_position) * playrate
    src_end = startoffs + (p1 - item_position) * playrate
    return (src_start, src_end, p0)


# -- RUN MADMOM ----------------------------------------------------

def run_madmom(audio_path, beats_per_bar, ts_num, ts_denom,
               src_start=-1.0, src_end=-1.0):
    """Call external madmom analyzer. Returns result dict or None.

    src_start/src_end (seconds into the source file) limit analysis to a window;
    -1 means "whole file". Downbeats in the result are relative to the window.
    """
    try:
        process = subprocess.Popen(
            [PYTHON_EXE, ANALYZER_SCRIPT, audio_path, OUTPUT_JSON,
             str(beats_per_bar), str(ts_num), str(ts_denom),
             str(src_start), str(src_end)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={
                "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
                "PYTHONIOENCODING": "utf-8",
                "HOME": os.path.expanduser("~"),
                "TMPDIR": "/tmp",
            },
        )
        raw_stdout, raw_stderr = process.communicate()
        stdout = raw_stdout.decode("utf-8", errors="replace") if raw_stdout else ""
        stderr = raw_stderr.decode("utf-8", errors="replace") if raw_stderr else ""
        if stdout:
            log(stdout)
        if stderr:
            log("STDERR: " + stderr)
        if process.returncode != 0:
            log("ERROR: madmom exited with code {}".format(process.returncode))
            return None
        if not os.path.exists(OUTPUT_JSON):
            log("ERROR: output JSON not created")
            return None
        with open(OUTPUT_JSON, "r") as f:
            return json.load(f)
    except Exception as e:
        log("ERROR: {}".format(e))
        return None


# -- CREATE TEMPO MARKERS -------------------------------------------

def create_tempo_markers(downbeats, offset, ts_num, ts_denom, playrate=1.0,
                         first_beat_time=None):
    """Create tempo markers from downbeat times.
    downbeats: times relative to the START of the analyzed window
    offset: project time the analyzed window begins at (window_proj_start)
    playrate: item play rate — window-relative source time maps to project time
              as proj = offset + downbeat / playrate
    first_beat_time: optional anchor (project time) for phase alignment
    """
    qn_per_bar = calc_quarter_notes_per_bar(ts_num, ts_denom)
    if not playrate:
        playrate = 1.0

    # Window-relative source time -> project time
    proj_downbeats = [offset + d / playrate for d in downbeats]

    # If first_beat marker exists, find closest downbeat and shift phase
    if first_beat_time is not None:
        min_dist = float('inf')
        best_idx = 0
        for i, d in enumerate(proj_downbeats):
            dist = abs(d - first_beat_time)
            if dist < min_dist:
                min_dist = dist
                best_idx = i
        # Start from this downbeat
        proj_downbeats = proj_downbeats[best_idx:]
        log("  Anchored to 'first beat' marker at {:.2f}s (offset {})".format(
            first_beat_time, best_idx))

    # Calculate BPM and set markers
    count = 0
    for i in range(len(proj_downbeats) - 1):
        bar_dur = proj_downbeats[i + 1] - proj_downbeats[i]
        if bar_dur <= 0:
            continue
        bpm = qn_per_bar * 60.0 / bar_dur
        if bpm < 30 or bpm > 300:
            continue
        if count == 0:
            RPR_SetTempoTimeSigMarker(0, -1, proj_downbeats[i], -1, -1, bpm,
                                       ts_num, ts_denom, False)
        else:
            RPR_SetTempoTimeSigMarker(0, -1, proj_downbeats[i], -1, -1, bpm,
                                       0, 0, False)
        count += 1

    RPR_UpdateTimeline()
    return count


# -- MAIN ----------------------------------------------------------

def main():
    log("=== Universal Madmom Tempo Map ===\n")

    # Get selected items
    items = get_selected_items()
    if not items:
        RPR_ShowMessageBox("Select one or more audio items first.", "Madmom Tempo Map", 0)
        return

    log("Selected {} item(s)".format(len(items)))

    # Ask for time signature
    rv = RPR_GetUserInputs("Madmom Tempo Map", 1,
                            "Time Signature (e.g. 4/4, 7/8, 12/8)", "4/4", 64)
    if not rv[0]:
        return
    ts_input = rv[4]

    ts_num, ts_denom, beats_per_bar = parse_time_sig(ts_input)
    if ts_num is None:
        RPR_ShowMessageBox("Invalid time signature: " + ts_input, "Error", 0)
        return

    log("Time signature: {}/{}, beats_per_bar={}\n".format(ts_num, ts_denom, beats_per_bar))

    # Time selection (if any) scopes analysis; else each item's own bounds.
    ts_range = get_time_selection()
    if ts_range is not None:
        log("Time selection active: {:.2f}s - {:.2f}s\n".format(*ts_range))

    RPR_Undo_BeginBlock()

    for item_info in items:
        log("Processing: {} ({})".format(item_info["name"], item_info["audio_path"]))
        log("  Position: {:.2f}s, Length: {:.2f}s".format(
            item_info["position"], item_info["length"]))

        # Decide which slice of the source to analyze
        window = compute_analysis_window(
            item_info["position"], item_info["length"],
            item_info["startoffs"], item_info["playrate"], ts_range)
        if window is None:
            log("  Skipped (outside time selection)\n")
            continue
        src_start, src_end, window_proj_start = window
        log("  Analyzing source {:.2f}s - {:.2f}s (project start {:.2f}s)".format(
            src_start, src_end, window_proj_start))

        # Check for "first beat" marker within the analyzed project window
        window_proj_end = window_proj_start + (src_end - src_start) / item_info["playrate"]
        first_beat = find_first_beat_marker(window_proj_start, window_proj_end)
        if first_beat is not None:
            log("  Found 'first beat' marker at {:.2f}s".format(first_beat))

        # Run madmom on the chosen window
        result = run_madmom(item_info["audio_path"], beats_per_bar, ts_num, ts_denom,
                            src_start, src_end)
        if result is None:
            log("  FAILED - skipping")
            continue

        # Create tempo markers (downbeats are window-relative)
        count = create_tempo_markers(
            result["downbeats"],
            window_proj_start,
            ts_num, ts_denom,
            item_info["playrate"],
            first_beat
        )
        log("  Created {} tempo markers\n".format(count))

    RPR_Undo_EndBlock("Madmom tempo map", -1)
    RPR_UpdateArrange()
    log("Done!")


if __name__ == "__main__":
    main()
