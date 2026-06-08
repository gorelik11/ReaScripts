# -*- coding: utf-8 -*-
"""
Universal Madmom Tempo Map V2.0 (REAPER ReaScript)
Run inside REAPER: Actions > ReaScript > Run...

V2 difference vs V1: the first tempo marker is anchored EXACTLY on the start of
the time selection (= beat 1), removing V1's ~2s phase lag. Writing is
multi-song-safe: only markers inside the analysis window are touched, so other
songs' tempo maps in the same project survive.

Workflow:
1. Select an audio item.
2. Make a time selection whose LEFT edge sits on beat 1.
3. Run this script, enter the time signature (e.g. "7/8", "4/4", "12/8").
"""

import math
import os
import json
import subprocess

def log(m):
    RPR_ShowConsoleMsg(str(m) + "\n")

# Madmom lives in a dedicated venv (REAPER/framework Python has no madmom).
PYTHON_EXE = os.path.expanduser("~/.venvs/madmom/bin/python3")


def _find_analyzer():
    """Locate reels_madmom_analyze.py next to this script (shared with V1)."""
    candidates = []
    try:
        ctx = RPR_get_action_context()
        if len(ctx) > 1 and ctx[1]:
            candidates.append(os.path.dirname(ctx[1]))
    except Exception:
        pass
    if "__file__" in globals():
        candidates.append(os.path.dirname(os.path.abspath(__file__)))
    candidates.append(os.path.expanduser("~/projects/reascripts"))
    candidates.append(os.path.expanduser("~/ReaScripts"))
    for d in candidates:
        p = os.path.join(d, "reels_madmom_analyze.py")
        if os.path.exists(p):
            return p
    return os.path.join(candidates[0] if candidates else ".", "reels_madmom_analyze.py")


ANALYZER_SCRIPT = _find_analyzer()
OUTPUT_JSON = os.path.join(os.path.expanduser("~"), "madmom_result_v2.json")
ERROR_LOG = os.path.join(os.path.expanduser("~"), "reels_tempo_map_v2_error.log")


# -- PARSE TIME SIGNATURE (ported verbatim from V1) ----------------

def parse_time_sig(ts_string):
    """Parse '7/8' -> (num, denom, beats_per_bar)."""
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
        beats_per_bar = num // 3
    elif denom == 8:
        beats_per_bar = num
    else:
        beats_per_bar = num
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


# -- GET SELECTED ITEMS (ported from V1) ---------------------------

def get_selected_items():
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
        startoffs = RPR_GetMediaItemTakeInfo_Value(take, "D_STARTOFFS")
        playrate = RPR_GetMediaItemTakeInfo_Value(take, "D_PLAYRATE")
        name = RPR_GetTakeName(take)
        items.append({
            "item": item, "take": take, "audio_path": audio_path,
            "position": position, "length": length, "startoffs": startoffs,
            "playrate": playrate if playrate else 1.0, "name": name,
        })
    return items


# -- ANALYSIS WINDOW: time selection > item bounds > whole file -----

def get_time_selection():
    """Return (start, end) of the loop/time selection, or None when empty."""
    ret = RPR_GetSet_LoopTimeRange(False, False, 0.0, 0.0, False)
    start, end = ret[2], ret[3]
    if end <= start:
        return None
    return (start, end)


def compute_analysis_window(item_position, item_length, startoffs, playrate, ts_range):
    """Decide which slice of the SOURCE file to analyze for one item.

    Returns (src_start, src_end, window_proj_start) where src_* are seconds into
    the source and window_proj_start is the project time the window begins at
    (= beat-1 anchor) - or None if a time selection exists but misses this item.
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


# -- RUN MADMOM (ported from V1) -----------------------------------

def run_madmom(audio_path, beats_per_bar, ts_num, ts_denom,
               src_start=-1.0, src_end=-1.0):
    """Call the shared external madmom analyzer. Returns result dict or None."""
    try:
        process = subprocess.Popen(
            [PYTHON_EXE, ANALYZER_SCRIPT, audio_path, OUTPUT_JSON,
             str(beats_per_bar), str(ts_num), str(ts_denom),
             str(src_start), str(src_end)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env={"PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
                 "PYTHONIOENCODING": "utf-8",
                 "HOME": os.path.expanduser("~"), "TMPDIR": "/tmp"},
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
        with open(OUTPUT_JSON, "r") as fh:
            return json.load(fh)
    except Exception as e:
        log("ERROR: {}".format(e))
        return None


# -- PHASE CORRECTION ----------------------------------------------

def compute_bar_period(proj_downbeats):
    """Median of the first (up to 4) downbeat intervals - robust to jitter.

    Returns the bar period in project seconds, or None if there are fewer than
    two downbeats.
    """
    if len(proj_downbeats) < 2:
        return None
    intervals = [proj_downbeats[i + 1] - proj_downbeats[i]
                 for i in range(min(4, len(proj_downbeats) - 1))]
    intervals.sort()
    m = len(intervals) // 2
    if len(intervals) % 2:
        return intervals[m]
    return (intervals[m - 1] + intervals[m]) / 2.0


def rephase_to_anchor(proj_downbeats, anchor, period):
    """Shift the whole downbeat grid by a small delta so the first downbeat lands
    on the grid line (anchor + k*period) nearest to it. This snaps the detected
    phase onto an anchor-based grid without changing bar durations.
    """
    if not proj_downbeats or not period:
        return list(proj_downbeats)
    d0 = proj_downbeats[0]
    k = math.floor((d0 - anchor) / period + 0.5)  # round half up (round() is banker's)
    delta = (anchor + k * period) - d0
    return [d + delta for d in proj_downbeats]


def build_grid(proj_downbeats, anchor, period, eps=1e-6):
    """Produce the final downbeat grid in project time with beat 1 EXACTLY on the
    anchor (time-selection start).

    1. Re-phase the detected downbeats onto an anchor-based grid.
    2. Keep downbeats at or after the anchor.
    3. If the first kept downbeat is within half a bar of the anchor, snap it to
       the anchor. Otherwise (madmom dropped the opening bars) back-fill whole
       bars from the anchor up to the first kept downbeat.
    """
    if not proj_downbeats:
        return [anchor]
    if not period:
        return [anchor] + [d for d in proj_downbeats if d > anchor + eps]
    rp = rephase_to_anchor(proj_downbeats, anchor, period)
    kept = [d for d in rp if d >= anchor - eps]
    if not kept:
        return [anchor]
    if abs(kept[0] - anchor) <= period / 2.0:
        kept[0] = anchor
        return kept
    # back-fill the missed anacrusis bars
    backfill = []
    t = kept[0] - period
    while t >= anchor - eps:
        backfill.append(t)
        t -= period
    backfill.reverse()
    if backfill:
        backfill[0] = anchor          # pin the very first line exactly on the anchor
    else:
        backfill = [anchor]
    return backfill + kept


# -- MULTI-SONG-SAFE WRITE -----------------------------------------

def clear_tempo_markers_in_range(start, end, eps=1e-6):
    """Delete tempo/time-sig markers whose time is within [start, end] ONLY.

    This is the vault-documented album-mapping pattern: markers of other songs
    live in other time ranges, so they are never touched. Iterate in reverse so
    index deletion stays valid. Returns the count removed.
    """
    n = RPR_CountTempoTimeSigMarkers(0)
    removed = 0
    for i in range(n - 1, -1, -1):
        # REAPER's Python binding requires ALL out-params passed positionally
        # (proj, ptidx, + 7 placeholders); it echoes retval + all params, so
        # timepos is at index 3.
        ret = RPR_GetTempoTimeSigMarker(0, i, 0.0, 0, 0.0, 0.0, 0, 0, False)
        timepos = ret[3]
        if start - eps <= timepos <= end + eps:
            RPR_DeleteTempoTimeSigMarker(0, i)
            removed += 1
    return removed


def _first_marker_pos_near(timepos):
    """Return the actual project time of the tempo marker closest to `timepos`
    (used to verify REAPER did not snap the anchor marker away)."""
    n = RPR_CountTempoTimeSigMarkers(0)
    best = None
    for i in range(n):
        t = RPR_GetTempoTimeSigMarker(0, i, 0.0, 0, 0.0, 0.0, 0, 0, False)[3]
        if best is None or abs(t - timepos) < abs(best - timepos):
            best = t
    return best


def create_tempo_markers_v2(downbeats, anchor, ts_num, ts_denom, window_end,
                            playrate=1.0):
    """Build an anchored, anacrusis-filled tempo grid and write it.

    downbeats: window-relative madmom downbeats (seconds).
    anchor:    project time the window starts at (= beat 1).
    window_end: project time the window ends at (delete bound for narrow clear).
    Returns the number of markers written.
    """
    qn_per_bar = calc_quarter_notes_per_bar(ts_num, ts_denom)
    if not playrate:
        playrate = 1.0

    # window-relative source time -> project time
    proj_downbeats = [anchor + d / playrate for d in downbeats]
    period = compute_bar_period(proj_downbeats)
    grid = build_grid(proj_downbeats, anchor, period)

    # append a sentinel one bar past the last downbeat so the final grid point
    # also gets a marker written (the loop writes at grid[i], using bar_dur to
    # the next point; without a sentinel the last downbeat would be skipped)
    if period and len(grid) >= 1:
        grid = grid + [grid[-1] + period]

    # multi-song-safe: wipe only the current window, then write by time
    clear_tempo_markers_in_range(anchor, window_end)

    count = 0
    for i in range(len(grid) - 1):
        bar_dur = grid[i + 1] - grid[i]
        if bar_dur <= 0:
            continue
        bpm = qn_per_bar * 60.0 / bar_dur
        if bpm < 30 or bpm > 300:
            continue
        if count == 0:
            RPR_SetTempoTimeSigMarker(0, -1, grid[i], -1, 0.0, bpm,
                                       ts_num, ts_denom, False)
        else:
            RPR_SetTempoTimeSigMarker(0, -1, grid[i], -1, 0.0, bpm, 0, 0, False)
        count += 1

    # verify the anchor marker did not get snapped away (live diagnostic)
    if count:
        actual = _first_marker_pos_near(anchor)
        if actual is not None and abs(actual - anchor) > 1e-3:
            log("  WARNING: first marker snapped to {:.4f}s (anchor {:.4f}s, "
                "delta {:.4f}s)".format(actual, anchor, actual - anchor))

    RPR_UpdateTimeline()
    return count


# -- MAIN ----------------------------------------------------------

def main():
    log("=== Universal Madmom Tempo Map V2.0 ===\n")
    log("Analyzer: {}\n".format(ANALYZER_SCRIPT))

    items = get_selected_items()
    if not items:
        RPR_ShowMessageBox("Select one or more audio items first.",
                           "Madmom Tempo Map V2", 0)
        return
    log("Selected {} item(s)".format(len(items)))

    rv = RPR_GetUserInputs("Madmom Tempo Map V2", 1,
                           "Time Signature (e.g. 4/4, 7/8, 12/8)", "4/4", 64)
    if not rv[0]:
        return
    ts_input = rv[4]
    ts_num, ts_denom, beats_per_bar = parse_time_sig(ts_input)
    if ts_num is None:
        RPR_ShowMessageBox("Invalid time signature: " + ts_input, "Error", 0)
        return
    log("Time signature: {}/{}, beats_per_bar={}\n".format(ts_num, ts_denom, beats_per_bar))

    ts_range = get_time_selection()
    if ts_range is not None:
        log("Time selection (beat 1 anchor): {:.2f}s - {:.2f}s\n".format(*ts_range))
    else:
        log("No time selection - using item bounds (beat 1 = item start)\n")

    RPR_Undo_BeginBlock()
    for item_info in items:
        log("Processing: {} ({})".format(item_info["name"], item_info["audio_path"]))
        window = compute_analysis_window(
            item_info["position"], item_info["length"],
            item_info["startoffs"], item_info["playrate"], ts_range)
        if window is None:
            log("  Skipped (outside time selection)\n")
            continue
        src_start, src_end, window_proj_start = window
        window_proj_end = window_proj_start + (src_end - src_start) / item_info["playrate"]
        log("  Analyzing source {:.2f}s - {:.2f}s (anchor {:.2f}s)".format(
            src_start, src_end, window_proj_start))

        result = run_madmom(item_info["audio_path"], beats_per_bar, ts_num, ts_denom,
                            src_start, src_end)
        if result is None:
            log("  FAILED - skipping")
            continue

        count = create_tempo_markers_v2(
            result["downbeats"], window_proj_start, ts_num, ts_denom,
            window_proj_end, item_info["playrate"])
        log("  Created {} tempo markers (beat 1 anchored)\n".format(count))

    RPR_Undo_EndBlock("Madmom tempo map V2", -1)
    RPR_UpdateArrange()
    log("Done!")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        tb = traceback.format_exc()
        try:
            RPR_ShowConsoleMsg("\n*** ERROR ***\n" + tb + "\n")
        except Exception:
            pass
        try:
            with open(ERROR_LOG, "w") as _f:
                _f.write(tb)
        except Exception:
            pass
