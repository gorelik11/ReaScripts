"""The V1.6 analyser's arithmetic, in Python, so the EEL2 version can be checked against it.

Everything here is what `@gfx` does per frame: window, transform, magnitudes, bins to columns,
bits, tilt, smoothing, and the red rule. The plugin's own display cannot be asserted, so this is
the authority for "what should be on screen", and the live matrix only has to confirm that the
screen agrees with it at a couple of points.

UNITS. RCBitNova's vertical axis is BITS, not dB: 1 bit = 6.020599913 dB. The conversion happens
once, at the source - `log2(mag)` - rather than in dB with a translation at the end, so there is
no second place where a factor of 6 can be dropped.

TWO THINGS THAT ARE EASY TO GET BACKWARDS, both of which the design review caught in prose:

1. The binning branches. Where a screen column spans AT MOST ONE bin (`b1 - b0 <= 1`, i.e. pixels
   are denser than bins - the low end) the value is INTERPOLATED between adjacent bins. Where a
   column contains SEVERAL bins (the high end) it is their MAXIMUM. A mean up there smooths real
   peaks away and still looks entirely believable, which is what makes the mistake expensive.
2. The low edge. The bin INDEX is clamped before the interpolation fraction is computed. At
   192 kHz, 20 Hz is bin 0.853; computing the fraction first and clamping after interpolates the
   wrong pair.

No numpy: nothing else in tools/ needs it, and an FFT is thirty lines.

Run: python3 -m pytest tests/test_rcbitnova_spectrum.py -v
"""

import cmath
import math

FFT_N = 8192
BITS_PER_DB = 1.0 / 6.020599913
FLOOR_BITS = -20.0            # the bottom of the analyser's own scale
CEIL_BITS = 2.0               # the top; drawing clamps to it, the maths does not


def hann(n):
    return [0.5 - 0.5 * math.cos(2 * math.pi * i / n) for i in range(n)]


def _fft(a):
    """In-place iterative radix-2 Cooley-Tukey on a list of complex. len(a) must be a power of 2."""
    n = len(a)
    assert n & (n - 1) == 0, "FFT length must be a power of two"
    j = 0
    for i in range(1, n):
        bit = n >> 1
        while j & bit:
            j ^= bit
            bit >>= 1
        j |= bit
        if i < j:
            a[i], a[j] = a[j], a[i]
    length = 2
    while length <= n:
        step = cmath.exp(-2j * math.pi / length)
        for i in range(0, n, length):
            w = 1 + 0j
            for k in range(i, i + length // 2):
                u = a[k]
                v = a[k + length // 2] * w
                a[k] = u + v
                a[k + length // 2] = u - v
                w *= step
        length <<= 1
    return a


def magnitudes(samples, fft_n=FFT_N, window=None):
    """Hann-windowed magnitudes of the last `fft_n` samples, scaled by 4/fft_n.

    That scale makes a full-scale sine read 1.0: a Hann window has a coherent gain of 0.5 and a
    real sine splits its energy between +f and -f, so the peak bin holds A * fft_n / 4.
    """
    w = window or hann(fft_n)
    buf = [complex(samples[i] * w[i], 0.0) for i in range(fft_n)]
    _fft(buf)
    scale = 4.0 / fft_n
    return [abs(buf[i]) * scale for i in range(fft_n // 2)]


def _bits(mag):
    return math.log(max(mag, 1e-12), 2)


def column_freqs(px_n, f_min, f_max):
    """The left edge of every column, plus the right edge of the last one."""
    span = math.log(f_max / f_min)
    return [f_min * math.exp(span * i / (px_n - 1)) for i in range(px_n)]


def to_columns(mags, srate, px_n, f_min, f_max, fft_n=FFT_N):
    """Bins -> one value per screen column, in BITS. Columns at or above Nyquist read the floor."""
    edges = column_freqs(px_n, f_min, f_max)
    nyq = srate * 0.5
    top = fft_n // 2
    out = []
    for i in range(px_n):
        f0 = edges[i]
        f1 = edges[i + 1] if i + 1 < px_n else f_max
        if f0 >= nyq:
            # Nothing is representable up here. Repeating the last real bin - the obvious clamp -
            # would draw content in exactly the octave this plugin's FIR Brick is judged by.
            out.append(FLOOR_BITS)
            continue
        b0 = f0 * fft_n / srate
        b1 = f1 * fft_n / srate
        if b1 - b0 <= 1.0:
            idx = int(math.floor(b0))
            idx = max(1, min(top - 2, idx))          # INDEX first...
            frac = b0 - idx                          # ...then the fraction
            frac = 0.0 if frac < 0.0 else (1.0 if frac > 1.0 else frac)
            mg = mags[idx] + (mags[idx + 1] - mags[idx]) * frac
        else:
            lo = max(1, int(math.floor(b0)))
            hi = min(top - 1, int(math.ceil(b1)))
            mg = 0.0
            for b in range(lo, hi + 1):
                if mags[b] > mg:
                    mg = mags[b]
        out.append(max(_bits(mg), FLOOR_BITS))
    return out


def apply_tilt(cols, srate, px_n, f_min, f_max, tilt_db):
    """Add `tilt_db` per octave, referenced to 1 kHz, expressed in bits."""
    if tilt_db == 0:
        return list(cols)
    edges = column_freqs(px_n, f_min, f_max)
    per_oct = tilt_db * BITS_PER_DB
    return [cols[i] + per_oct * math.log(max(edges[i], 1e-9) / 1000.0, 2) for i in range(px_n)]


def smooth3(cols, passes=2):
    """prev*0.25 + cur*0.5 + next*0.25 over the interior, `passes` times. Ends are untouched -
    the reference leaves them alone and a null against it would notice."""
    out = list(cols)
    for _ in range(passes):
        prev = out[0]
        for i in range(1, len(out) - 1):
            cur = out[i]
            out[i] = prev * 0.25 + cur * 0.5 + out[i + 1] * 0.25
            prev = cur
    return out


def red_state(mid_cols, side_cols, prev_state, floor_bits=-16.0, hyst_bits=0.1):
    """0 normal, 1 warm red (Side above Mid), 2 bright red (Side more than a bit above Mid).

    Two guards, without which the rule lies. The FLOOR: near the display's own bottom the two
    values differ by arithmetic noise, and the top of the graph would flicker red over silence.
    The HYSTERESIS: exact equality is a coin flip thirty times a second.
    """
    out = []
    for i, (md, sd) in enumerate(zip(mid_cols, side_cols)):
        prev = prev_state[i] if i < len(prev_state) else 0
        if max(md, sd) < floor_bits:
            out.append(0)
            continue
        st = prev
        if prev == 0:
            if sd > md + hyst_bits:
                st = 1
        else:
            if sd < md - hyst_bits:
                st = 0
        if st >= 1:
            st = 2 if sd > md + 1.0 else 1
        out.append(st)
    return out
