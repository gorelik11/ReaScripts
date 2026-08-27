"""Generate the deterministic material the null test renders through both plugins.

30.000 s, 48 kHz, stereo, 32-bit float. Four sections, each aimed at a different way a difference
could hide:

  0.0 -  12.0 s  log sweep 20 Hz -> 20 kHz at -6 dBFS: every band, every filter, one pass
 12.0 -  20.0 s  white noise at -12 dBFS, deterministic LCG: broadband, all bands at once
 20.0 -  22.0 s  digital silence: anything that rings, decays or leaks shows here
 22.0 -  30.0 s  full-scale transients once a second: attack/release, ceilings, Mode B

Committed as a GENERATOR rather than as an 11.5 MB wav in a public repo. It is byte-reproducible:
integer arithmetic for the LCG, no seeds from the clock, no floating-point accumulation of phase.
Regenerate with `python3 tools/make_null_fixture.py`.
"""

import array
import math
import os
import struct

SECONDS = 30
OUT = os.path.join("tests", "fixtures", "null_30s.wav")


def _samples(SR):
    n = SR * SECONDS
    left = array.array("f", [0.0]) * n
    right = array.array("f", [0.0]) * n

    # --- log sweep, phase from a closed form so it cannot drift ---
    f0, f1, dur = 20.0, 20000.0, 12.0
    k = math.log(f1 / f0)
    for i in range(int(dur * SR)):
        t = i / SR
        phase = 2 * math.pi * f0 * dur / k * (math.exp(k * t / dur) - 1)
        v = 0.5 * math.sin(phase)
        left[i] = v
        right[i] = v * 0.7        # not identical channels: M/S placement must have something to do

    # --- deterministic noise, integer LCG (glibc constants) ---
    state = 12345
    for i in range(int(12.0 * SR), int(20.0 * SR)):
        state = (1103515245 * state + 12345) & 0x7FFFFFFF
        left[i] = (state / 0x3FFFFFFF - 1.0) * 0.25
        state = (1103515245 * state + 12345) & 0x7FFFFFFF
        right[i] = (state / 0x3FFFFFFF - 1.0) * 0.25

    # --- 20..22 s stays exactly zero ---

    # --- full-scale transients, one per second, 3 ms decay ---
    for s in range(22, 30):
        start = s * SR
        for i in range(int(0.003 * SR)):
            env = 1.0 - i / (0.003 * SR)
            v = env * (1.0 if i % 2 == 0 else -1.0)
            left[start + i] = v
            right[start + i] = -v          # anti-phase: pure Side content
    return left, right


def write_wav(path=OUT, SR=48000):
    """Written at the PROJECT's sample rate, not a fixed 48 kHz: anything else is resampled on the
    way in, which adds a stage neither plugin controls and buys nothing."""
    left, right = _samples(SR)
    n = len(left)
    inter = array.array("f", [0.0]) * (n * 2)
    for i in range(n):
        inter[i * 2] = left[i]
        inter[i * 2 + 1] = right[i]
    data = inter.tobytes()
    fmt = struct.pack("<HHIIHH", 3, 2, SR, SR * 2 * 4, 8, 32)     # WAVE_FORMAT_IEEE_FLOAT
    chunks = (b"fmt " + struct.pack("<I", len(fmt)) + fmt
              + b"data" + struct.pack("<I", len(data)) + data)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(b"RIFF" + struct.pack("<I", 4 + len(chunks)) + b"WAVE" + chunks)
    return path, n


if __name__ == "__main__":
    import sys
    sr = int(sys.argv[1]) if len(sys.argv) > 1 else 48000
    path, n = write_wav(SR=sr)
    print(f"{path}: {n} frames, {n / sr:.3f} s, {sr} Hz stereo 32-bit float")
