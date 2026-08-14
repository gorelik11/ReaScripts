"""RCBitNova distortion & aliasing probe.

Measures what listening cannot: harmonic distortion, folded (aliasing) products, and
intermodulation, for each DSP block of RCBitNova. Answers two questions with numbers —
"is the plugin clean where it must be" and "does it need oversampling".

Reads the oracle (tools/rcbitnova_dsp.py) and never modifies it. Pure stdlib, like the oracle.
Design: docs/superpowers/specs/2026-08-14-rcbitnova-distortion-probe-design.md

Key idea: COHERENT SAMPLING. The tone is placed at exactly k bins of the analysis length
(f = k*sr/N with integer k), so the window contains a whole number of periods and a plain
rectangular window leaks nothing. That buys a measurement floor near float64 itself instead of
the ~-92 dB sidelobe floor of any smooth window - and a first attempt here, using
Blackman-Harris on a deliberately inharmonic tone, measured exactly that window floor and
reported it as the plugin's distortion. Harmonics then land exactly on bin k*h (folded about
Nyquist), and everything else is a genuine product of the DSP.

k is chosen ODD and coprime with N so that harmonics fold onto distinct bins rather than piling
onto each other or onto the fundamental.
"""

import math

try:                                   # importable both as `tools.rcbitnova_probe` (pytest,
    from tools import rcbitnova_dsp as dsp   # which runs from the repo root) and directly from
except ImportError:                          # inside tools/ for quick one-off sweeps
    import rcbitnova_dsp as dsp

SILENT = -400.0          # dB value standing for "nothing there at all"


# --------------------------------------------------------------------------- tones

def tone_bin(N, sr=48000, target_hz=1000.0):
    """Pick a COHERENT tone: f = k*sr/N with k an odd integer, as near target_hz as possible.

    Returns (freq_hz, k). Coherence is what removes the need for a window at all, which is what
    puts the measurement floor near float64 rather than at the window's sidelobe level.
    """
    k = max(1, int(round(target_hz * N / sr)))
    if k % 2 == 0:          # odd k is coprime with a power-of-two N
        k += 1
    return k * sr / N, k


def sine(n, freq, sr, amp=0.5, phase=0.0):
    w = 2.0 * math.pi * freq / sr
    return [amp * math.sin(w * i + phase) for i in range(n)]


def two_tone(n, f1, f2, sr, amp=0.25):
    w1 = 2.0 * math.pi * f1 / sr
    w2 = 2.0 * math.pi * f2 / sr
    return [amp * math.sin(w1 * i) + amp * math.sin(w2 * i) for i in range(n)]


# --------------------------------------------------------------------------- analysis

def spectrum(sig, N=None, skip=None):
    """Magnitude spectrum of the steady-state part of `sig`, RECTANGULAR window.

    No window function is applied, and that is deliberate: with a coherent tone (tone_bin) the
    segment holds a whole number of periods, so there is no leakage to suppress, and any smooth
    window would only raise the floor to its own sidelobe level (~-92 dB for Blackman-Harris).

    `skip` samples are discarded first so a dynamics stage's attack, or a convolution engine's
    latency, is not scored as distortion.
    """
    if N is None:
        N = 1 << (len(sig).bit_length() - 1)
        N = min(N, 16384)
    if skip is None:
        skip = min(len(sig) - N, N)
    seg = sig[skip:skip + N]
    if len(seg) < N:
        seg = seg + [0.0] * (N - len(seg))
    X = dsp.lp_fft([complex(v, 0.0) for v in seg])
    return [abs(v) for v in X[:N // 2]]


def _peak_near(mag, b, halfwidth=4):
    """Largest magnitude within +/-halfwidth bins of float bin b, and its index."""
    lo = max(0, int(math.floor(b)) - halfwidth)
    hi = min(len(mag) - 1, int(math.ceil(b)) + halfwidth)
    idx = max(range(lo, hi + 1), key=lambda i: mag[i])
    return mag[idx], idx


def _db(x, ref):
    if x <= 0.0 or ref <= 0.0:
        return SILENT
    return 20.0 * math.log10(x / ref)


def analyse_tone(sig, bin_f, N=None, skip=None, n_harm=12, halfwidth=1, sideband_bins=64):
    """Harmonic / aliasing / modulation metrics for a single-tone run.

    Three DIFFERENT things get separated, because lumping them together makes the numbers
    meaningless (a first attempt did exactly that and reported identical figures for 5 kHz and
    19 kHz - impossible for real aliasing, and the giveaway that it was measuring modulation
    sidebands instead):

      thd          harmonics h*f that still fit BELOW Nyquist - ordinary harmonic distortion
      alias_peak   harmonics h*f ABOVE Nyquist, which fold back to |h*f mod fs| - these are
                   aliasing products, the ones oversampling would remove
      sideband     the largest component within +/-sideband_bins of the fundamental or of a
                   harmonic - amplitude modulation by a time-varying gain, NOT aliasing, and
                   oversampling would not touch it
      other        largest remaining component anywhere else

    bin_f: the fundamental's integer bin (from tone_bin) at the SAME N used here.
    All levels in dB relative to the fundamental; SILENT (-400) means nothing measurable.
    """
    mag = spectrum(sig, N=N, skip=skip)
    half = len(mag)
    fund, fund_i = _peak_near(mag, bin_f, halfwidth)
    if fund <= 0.0:
        return {"fund": 0.0, "thd": SILENT, "alias_peak": SILENT, "alias_bin": -1,
                "sideband": SILENT, "other": SILENT, "noise_floor": SILENT, "harmonics": []}

    claimed = set()
    near = set()

    def claim(idx, into):
        for i in range(max(0, idx - halfwidth), min(half, idx + halfwidth + 1)):
            into.add(i)

    def mark_near(idx):
        for i in range(max(0, idx - sideband_bins), min(half, idx + sideband_bins + 1)):
            near.add(i)

    claim(fund_i, claimed)
    mark_near(fund_i)

    true_harm = []
    folded_harm = []
    harm_levels = []
    period = 2.0 * half                      # bins spanning 0..fs
    for h in range(2, n_harm + 1):
        raw = bin_f * h
        folded = raw > half                  # above Nyquist -> it can only appear folded
        b = raw % period
        if b > half:
            b = period - b
        if b < 1 or b > half - 2:
            harm_levels.append(SILENT)
            continue
        lvl, idx = _peak_near(mag, b, halfwidth)
        claim(idx, claimed)
        mark_near(idx)
        db = _db(lvl, fund)
        harm_levels.append(db)
        (folded_harm if folded else true_harm).append(db)

    for i in range(0, 3):                    # DC region
        claimed.add(i)
        near.add(i)

    def rms_db(levels):
        lin = [10 ** (v / 20.0) for v in levels if v > SILENT]
        return 20.0 * math.log10(math.sqrt(sum(x * x for x in lin))) if lin else SILENT

    thd = rms_db(true_harm)
    alias_peak = max(folded_harm) if folded_harm else SILENT

    rest_near = [(mag[i], i) for i in range(half) if i not in claimed and i in near]
    rest_far = [(mag[i], i) for i in range(half) if i not in claimed and i not in near]
    sideband = _db(max(rest_near)[0], fund) if rest_near else SILENT
    if rest_far:
        omax, oidx = max(rest_far, key=lambda t: t[0])
        other = _db(omax, fund)
        vals = sorted(v for v, _ in rest_far)
        noise = _db(vals[len(vals) // 2], fund)
    else:
        other, oidx, noise = SILENT, -1, SILENT

    return {"fund": fund, "thd": thd, "alias_peak": alias_peak, "alias_bin": oidx,
            "sideband": sideband, "other": other, "noise_floor": noise,
            "harmonics": harm_levels}


def analyse_two_tone(sig, b1, b2, N=None, skip=None, halfwidth=1):
    """Largest intermodulation product not present in the input, in dB below the tones."""
    mag = spectrum(sig, N=N, skip=skip)
    half = len(mag)
    a1, i1 = _peak_near(mag, b1, halfwidth)
    a2, i2 = _peak_near(mag, b2, halfwidth)
    ref = max(a1, a2)
    if ref <= 0.0:
        return {"imd": SILENT, "imd_bin": -1}
    claimed = set()
    for idx in (i1, i2):
        for i in range(max(0, idx - halfwidth), min(half, idx + halfwidth + 1)):
            claimed.add(i)
    for i in range(0, 3):
        claimed.add(i)
    rest = [(mag[i], i) for i in range(half) if i not in claimed]
    if not rest:
        return {"imd": SILENT, "imd_bin": -1}
    amax, aidx = max(rest, key=lambda t: t[0])
    return {"imd": _db(amax, ref), "imd_bin": aidx}


# --------------------------------------------------------------------------- block runners
#
# Each runner takes a mono signal and returns a mono signal, so the probe can treat every DSP
# block uniformly. They are thin wrappers over the oracle - no DSP lives here.

def run_band(sig, sr, ftype="bell", fc=1000.0, q=0.707, gain_lin=1.0):
    L, _ = dsp.process_band_stereo(ftype, "both", fc, q, gain_lin, sr, sig, sig)
    return L


def run_hplp_min(sig, sr, ftype="hp", freq=100.0, resonance=0.0, nsec=4):
    L, _ = dsp.process_hplp_butter_stereo(sig, sig, ftype, freq, resonance, sr, nsec, "both")
    return L


def run_hplp_linear(sig, sr, ftype="hp", freq=100.0, resonance=0.0, nsec=4, BD=8192, P=2048):
    ker = dsp.impulse_fft_kernel(BD, ftype, freq, resonance, nsec, 14.0, sr)
    return dsp.partitioned_convolve(sig, ker, P)


def run_fir_brick(sig, sr, ftype="lp", freq=15000.0, BD=8192, P=2048):
    ker = dsp.fir_brick_kernel(BD, ftype, freq, 14.0, sr)
    return dsp.partitioned_convolve(sig, ker, P)


def run_bit_gain(sig, macro=0, micro=0, bit_ratio=1.0):
    g = dsp.bit_gain(macro, micro, bit_ratio)
    return [x * g for x in sig]


def run_modea(sig, sr, fc=1000.0, q=2.0, ceiling=0.25, atk=1.0, rel=80.0):
    return dsp.modea_process(sig, fc, q, sr, ceiling, atk, rel)


def run_modeb(sig, sr, fc=1000.0, q=2.0, ceil_soft=0.25, ceil_hard=0.5,
              look=2.0, rel=80.0, soft_on=True, hard_on=True):
    return dsp.modeb_cascade(sig, fc, q, sr, ceil_soft, ceil_hard, look, rel,
                             soft_on, hard_on)


# --------------------------------------------------------------------------- probes

def probe_tone(runner, sr=48000, N=8192, target_hz=1000.0, amp=0.5, pad=3, **kw):
    """Run one tone through `runner` and return its metrics.

    `pad` analysis-lengths of extra signal are generated so the steady state can be analysed
    after discarding startup (dynamics attack, convolution latency).
    """
    freq, b = tone_bin(N, sr=sr, target_hz=target_hz)
    n = N * (pad + 1)
    sig = sine(n, freq, sr, amp=amp)
    out = runner(sig, **kw) if kw else runner(sig)
    res = analyse_tone(out, b, N=N, skip=N * pad)
    res["freq"] = freq
    return res


def probe_two_tone(runner, sr=48000, N=8192, f1_hz=19000.0, f2_hz=20000.0, amp=0.25,
                   pad=3, **kw):
    f1, b1 = tone_bin(N, sr=sr, target_hz=f1_hz)
    f2, b2 = tone_bin(N, sr=sr, target_hz=f2_hz)
    n = N * (pad + 1)
    sig = two_tone(n, f1, f2, sr, amp=amp)
    out = runner(sig, **kw) if kw else runner(sig)
    res = analyse_two_tone(out, b1, b2, N=N, skip=N * pad)
    res["f1"], res["f2"] = f1, f2
    return res


def is_bit_transparent(runner, sr=48000, N=4096, target_hz=1000.0, amp=0.5, **kw):
    """True when the block returns its input bit-for-bit (the strongest possible claim)."""
    freq, _ = tone_bin(N, sr=sr, target_hz=target_hz)
    sig = sine(N * 2, freq, sr, amp=amp)
    out = runner(sig, **kw) if kw else runner(sig)
    return list(out[:len(sig)]) == sig
