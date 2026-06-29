"""Pure-Python DSP mirror for RCBitNova (no numpy/scipy).

Mirrors the exact math transcribed into JSFX, so numeric correctness is
verified by pytest offline. Filters use Andy Simper's TPT state-variable form.
"""
from __future__ import annotations

import math

ONE_BIT_DB = 6.0206


def bit_gain(macro: float, micro: float, bit_ratio: float) -> float:
    """Linear gain: 2 ^ ((macro + micro/100) * bit_ratio)."""
    return 2.0 ** ((macro + micro / 100.0) * bit_ratio)


def bit_gain_db(macro: float, micro: float, bit_ratio: float) -> float:
    """Display dB for a bit gain."""
    return (macro + micro / 100.0) * bit_ratio * ONE_BIT_DB


def encode_ms(l: float, r: float) -> tuple[float, float]:
    return (l + r) * 0.5, (l - r) * 0.5


def decode_ms(m: float, s: float) -> tuple[float, float]:
    return m + s, m - s


def svf_make(ftype: str, fc: float, q: float, gain_lin: float, sr: float) -> dict:
    """Andy Simper TPT-SVF coefficients. A = sqrt(gain_lin)."""
    A = math.sqrt(gain_lin)
    if ftype == "lp":
        g = math.tan(math.pi * fc / sr); k = 1.0 / q
        m0, m1, m2 = 0.0, 0.0, 1.0
    elif ftype == "hp":
        g = math.tan(math.pi * fc / sr); k = 1.0 / q
        m0, m1, m2 = 1.0, -k, -1.0
    elif ftype == "bell":
        g = math.tan(math.pi * fc / sr); k = 1.0 / (q * A)
        m0, m1, m2 = 1.0, k * (A * A - 1.0), 0.0
    elif ftype == "lowshelf":
        g = math.tan(math.pi * fc / sr) / math.sqrt(A); k = 1.0 / q
        m0, m1, m2 = 1.0, k * (A - 1.0), (A * A - 1.0)
    elif ftype == "highshelf":
        g = math.tan(math.pi * fc / sr) * math.sqrt(A); k = 1.0 / q
        m0, m1, m2 = A * A, k * (1.0 - A) * A, (1.0 - A * A)
    else:
        raise ValueError(f"unknown ftype {ftype!r}")
    a1 = 1.0 / (1.0 + g * (g + k))
    a2 = g * a1
    a3 = g * a2
    return {"a1": a1, "a2": a2, "a3": a3, "k": k, "m0": m0, "m1": m1, "m2": m2}


def svf_process(coeffs: dict, samples) -> list:
    a1, a2, a3 = coeffs["a1"], coeffs["a2"], coeffs["a3"]
    m0, m1, m2 = coeffs["m0"], coeffs["m1"], coeffs["m2"]
    ic1 = ic2 = 0.0
    out = []
    for v0 in samples:
        v3 = v0 - ic2
        v1 = a1 * ic1 + a2 * v3
        v2 = ic2 + a2 * ic1 + a3 * v3
        ic1 = 2.0 * v1 - ic1
        ic2 = 2.0 * v2 - ic2
        out.append(m0 * v0 + m1 * v1 + m2 * v2)
    return out


def svf_magnitude(coeffs: dict, freq: float, sr: float, n: int = 1 << 15) -> float:
    """Steady-state magnitude: RMS(out_tail) / RMS(in_tail) for a unit sine."""
    w = 2.0 * math.pi * freq / sr
    samples = [math.sin(w * i) for i in range(n)]
    out = svf_process(coeffs, samples)
    half = n // 2
    acc_o = sum(out[i] * out[i] for i in range(half, n))
    acc_i = sum(samples[i] * samples[i] for i in range(half, n))
    return math.sqrt(acc_o / acc_i)
