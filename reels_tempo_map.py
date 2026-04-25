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
    """Read all regions from the project, return list of dicts with name, start, end, idx."""
    regions = []
    i = 0
    while True:
        ret = reapy.reascript_api.RPR_EnumProjectMarkers3(
            0, i, 0, 0.0, 0.0, "", 0, 0
        )
        if ret[0] == 0:
            break
        idx, is_rgn, pos, rgnend, name = ret[0], ret[3], ret[4], ret[5], ret[6]
        if is_rgn:
            regions.append({"name": name, "start": pos, "end": rgnend, "idx": ret[8]})
        i += 1
    return regions


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

    # Convert to project time
    beats[:, 0] += start
    return beats


def get_downbeats(beats):
    """Extract downbeat times (beat_number == 1) from madmom output."""
    return beats[beats[:, 1] == 1, 0]


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
            if bpm < 30 or bpm > 300:
                continue
            if i == 0:
                reapy.reascript_api.RPR_SetTempoTimeSigMarker(
                    0, -1, time, -1, -1, bpm, time_sig_num, time_sig_denom, False
                )
            else:
                reapy.reascript_api.RPR_SetTempoTimeSigMarker(
                    0, -1, time, -1, -1, bpm, 0, 0, False
                )
        reapy.reascript_api.RPR_UpdateTimeline()


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
            reel_end = db + FADE_DURATION
            reel_end = min(reel_end, region_end)
            name = f"{composition_name} - Reel {reel_num:02d}"

            rgn_idx = reapy.reascript_api.RPR_AddProjectMarker2(
                0, True, reel_start, reel_end, name, -1, 0
            )

            # Try to set lane 2 via flags
            lane_flags = 2 << 8
            reapy.reascript_api.RPR_SetProjectMarker4(
                0, rgn_idx, True, reel_start, reel_end, name, 0, lane_flags
            )

            created.append({"name": name, "start": reel_start, "end": reel_end})
            reel_num += 1
            reel_start = db

    # Final segment
    if reel_start < region_end - 5:
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


def main():
    project = reapy.Project()
    audio_path = get_audio_source_path(project)
    print(f"Audio source: {audio_path}")

    song_regions = get_song_regions(project)
    print(f"Found {len(song_regions)} regions")

    total_reels = 0

    for comp_name, beats_per_bar, ts_num, ts_denom in COMPOSITIONS:
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
            analysis_start = 2166.6

        print(f"\nAnalyzing: {comp_name} ({ts_num}/{ts_denom})")
        print(f"  Range: {analysis_start:.1f}s - {region['end']:.1f}s")

        beats = analyze_beats(audio_path, analysis_start, region["end"], beats_per_bar)
        downbeats = get_downbeats(beats)
        print(f"  Found {len(downbeats)} downbeats")

        if len(downbeats) < 2:
            print(f"  WARNING: Too few downbeats, skipping")
            continue

        bpms = calculate_bpm(downbeats, ts_num, ts_denom)
        set_tempo_markers(project, bpms, ts_num, ts_denom, analysis_start)
        print(f"  Set {len(bpms)} tempo markers")

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
