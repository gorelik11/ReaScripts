#!/usr/bin/env python3
"""
External madmom analyzer — called via subprocess from REAPER ReaScript.
Usage: python3 reels_madmom_analyze.py <audio_path> <output_json> <beats_per_bar> <time_sig_num> <time_sig_denom> [src_start_sec] [src_end_sec]

src_start_sec/src_end_sec (optional) restrict analysis to a window of the source
file; -1 (or omitted) means the whole file. Downbeat times in the output are
relative to the START of the analyzed window.

Writes JSON with downbeat times to output_json.
"""

import sys
import json
from madmom.audio.signal import Signal
from madmom.features.downbeats import RNNDownBeatProcessor, DBNDownBeatTrackingProcessor

# madmom's RNNDownBeatProcessor was trained at 44.1 kHz. If we hand it raw
# samples at another rate it silently assumes 44100 and ALL beat times scale by
# file_sr/44100 (e.g. a 96 kHz file comes out stretched ~2.18x). Loading via
# madmom's Signal with an explicit sample_rate resamples first, so any project /
# file rate (44.1, 48, 88.2, 96 kHz) yields correct times in seconds.
MADMOM_SR = 44100


def main():
    if len(sys.argv) not in (6, 8):
        print("Usage: python3 reels_madmom_analyze.py <audio_path> <output_json> <beats_per_bar> <ts_num> <ts_denom> [src_start_sec] [src_end_sec]")
        sys.exit(1)

    audio_path = sys.argv[1]
    output_path = sys.argv[2]
    beats_per_bar = int(sys.argv[3])
    ts_num = int(sys.argv[4])
    ts_denom = int(sys.argv[5])
    src_start = float(sys.argv[6]) if len(sys.argv) == 8 else -1.0
    src_end = float(sys.argv[7]) if len(sys.argv) == 8 else -1.0

    print(f"Audio: {audio_path}")
    print(f"beats_per_bar={beats_per_bar}, time_sig={ts_num}/{ts_denom}")

    # Window the source (seconds); -1 means "whole file". madmom Signal resamples
    # to MADMOM_SR and downmixes to mono; beat times come out relative to `start`.
    win = {}
    if src_start is not None and src_start >= 0:
        win["start"] = src_start
    if src_end is not None and src_end >= 0:
        win["stop"] = src_end

    audio = Signal(audio_path, sample_rate=MADMOM_SR, num_channels=1, **win)
    if win:
        print(f"Window: {win.get('start', 0.0):.2f}s - "
              f"{win.get('stop', len(audio) / MADMOM_SR):.2f}s")
    print(f"Loaded {len(audio)/MADMOM_SR:.1f}s audio at {MADMOM_SR}Hz (resampled)")

    proc = RNNDownBeatProcessor()
    activations = proc(audio)
    dbn = DBNDownBeatTrackingProcessor(beats_per_bar=[beats_per_bar], fps=100)
    beats = dbn(activations)

    # All beats and downbeats
    all_beats = [{"time": float(b[0]), "beat": int(b[1])} for b in beats]
    downbeats = [float(b[0]) for b in beats if int(b[1]) == 1]

    result = {
        "audio_path": audio_path,
        "beats_per_bar": beats_per_bar,
        "time_sig_num": ts_num,
        "time_sig_denom": ts_denom,
        "duration": len(audio) / MADMOM_SR,
        "downbeats": downbeats,
        "all_beats": all_beats,
    }

    with open(output_path, "w") as f:
        json.dump(result, f, indent=2)
    print(f"Found {len(downbeats)} downbeats, written to {output_path}")


if __name__ == "__main__":
    main()
