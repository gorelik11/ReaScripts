#!/usr/bin/env python3
"""
External madmom analyzer — called via subprocess from REAPER ReaScript.
Usage: python3 reels_madmom_analyze.py <audio_path> <output_json> <beats_per_bar> <time_sig_num> <time_sig_denom>

Writes JSON with downbeat times to output_json.
"""

import sys
import json
import numpy as np
import soundfile as sf
from madmom.features.downbeats import RNNDownBeatProcessor, DBNDownBeatTrackingProcessor


def main():
    if len(sys.argv) != 6:
        print("Usage: python3 reels_madmom_analyze.py <audio_path> <output_json> <beats_per_bar> <ts_num> <ts_denom>")
        sys.exit(1)

    audio_path = sys.argv[1]
    output_path = sys.argv[2]
    beats_per_bar = int(sys.argv[3])
    ts_num = int(sys.argv[4])
    ts_denom = int(sys.argv[5])

    print(f"Audio: {audio_path}")
    print(f"beats_per_bar={beats_per_bar}, time_sig={ts_num}/{ts_denom}")

    info = sf.info(audio_path)
    sr = info.samplerate
    audio, sr = sf.read(audio_path)
    if audio.ndim > 1:
        audio = np.mean(audio, axis=1)

    print(f"Loaded {len(audio)/sr:.1f}s audio at {sr}Hz")

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
        "duration": len(audio) / sr,
        "downbeats": downbeats,
        "all_beats": all_beats,
    }

    with open(output_path, "w") as f:
        json.dump(result, f, indent=2)
    print(f"Found {len(downbeats)} downbeats, written to {output_path}")


if __name__ == "__main__":
    main()
