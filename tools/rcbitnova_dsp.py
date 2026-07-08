"""Pure-Python DSP mirror for RCBitNova (no numpy/scipy).

Mirrors the exact math transcribed into JSFX, so numeric correctness is
verified by pytest offline. Filters use Andy Simper's TPT state-variable form.
"""
from __future__ import annotations

import cmath
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
    elif ftype == "bandpass":
        g = math.tan(math.pi * fc / sr); k = 1.0 / q
        m0, m1, m2 = 0.0, k, 0.0
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


def q_eff(ftype, q_knob, qchar, gain_bits_eff, q_max=16.0):
    """Proportional-Q law (V0.3). For a bell band, Q rises with the static gain:
    Q_eff = min(q_max, q_knob*(1 + qchar*|gain_bits_eff|)). qchar in [0,1]; qchar=0 or
    a non-bell type returns q_knob exactly (bit-identical fast path). gain_bits_eff is
    the signed static gain exponent (Macro + Micro*0.01)*BitRatio."""
    if qchar == 0.0 or ftype != "bell":
        return q_knob
    qe = q_knob * (1.0 + qchar * abs(gain_bits_eff))
    return q_max if qe > q_max else qe          # qe >= q_knob always; no lower clamp


def svf_response(coeffs, freq, sr):
    """Exact |H(e^jw)| of the Simper TPT-SVF from its coefficient dict, via a
    state-space evaluation. Cheap and exact; use instead of svf_magnitude for
    bandwidth searches."""
    a1, a2, a3 = coeffs["a1"], coeffs["a2"], coeffs["a3"]
    m0, m1, m2 = coeffs["m0"], coeffs["m1"], coeffs["m2"]
    A11 = 2.0 * a1 - 1.0; A12 = -2.0 * a2
    A21 = 2.0 * a2;       A22 = 1.0 - 2.0 * a3
    B1 = 2.0 * a2; B2 = 2.0 * a3
    C1 = m1 * a1 + m2 * a2
    C2 = -m1 * a2 + m2 * (1.0 - a3)
    D = m0 + m1 * a2 + m2 * a3
    z = cmath.exp(1j * 2.0 * math.pi * freq / sr)
    M11 = z - A11; M12 = -A12
    M21 = -A21;    M22 = z - A22
    det = M11 * M22 - M12 * M21
    x1 = (M22 * B1 - M12 * B2) / det
    x2 = (-M21 * B1 + M11 * B2) / det
    return abs(C1 * x1 + C2 * x2 + D)


def process_band_stereo(ftype, placement, fc, q, gain_lin, sr, Lin, Rin):
    """Apply one band to a stereo L/R pair per placement. Running domain is L/R;
    mid/side placements transform locally and recombine."""
    c = svf_make(ftype, fc, q, gain_lin, sr)
    if placement == "both":
        return svf_process(c, Lin), svf_process(c, Rin)
    if placement == "left":
        return svf_process(c, Lin), list(Rin)
    if placement == "right":
        return list(Lin), svf_process(c, Rin)
    # mid / side
    M = [(l + r) * 0.5 for l, r in zip(Lin, Rin)]
    S = [(l - r) * 0.5 for l, r in zip(Lin, Rin)]
    if placement == "mid":
        M = svf_process(c, M)
    elif placement == "side":
        S = svf_process(c, S)
    else:
        raise ValueError(f"unknown placement {placement!r}")
    return ([m + s for m, s in zip(M, S)], [m - s for m, s in zip(M, S)])


# ---- Phase 2b: Soft dynamics (Mode A) ----

def ceiling_lin(ceil_macro, ceil_micro):
    """Ceiling as a power of two, bits below 0 dBFS."""
    return 2.0 ** (-(ceil_macro + ceil_micro / 100.0))


def env_coeffs(atk_ms, rel_ms, sr):
    return (math.exp(-1.0 / (atk_ms * 0.001 * sr)),
            math.exp(-1.0 / (rel_ms * 0.001 * sr)))


def gain_env_step(env_gain, gr, atk, rel):
    coef = atk if gr < env_gain else rel
    return gr + (env_gain - gr) * coef


def modea_process(signal, fc, q, sr, ceiling, atk_ms, rel_ms):
    """Single-channel Mode-A Soft: detector -> envelope -> modulated bell-cut."""
    det = svf_make("bandpass", fc, q, 1.0, sr)
    da1, da2, da3, dk = det["a1"], det["a2"], det["a3"], det["k"]
    atk, rel = env_coeffs(atk_ms, rel_ms, sr)
    cg = math.tan(math.pi * fc / sr)
    dic1 = dic2 = cic1 = cic2 = 0.0
    env = 1.0
    out = []
    for x in signal:
        v3 = x - dic2
        v1 = da1 * dic1 + da2 * v3
        v2 = dic2 + da2 * dic1 + da3 * v3
        dic1 = 2.0 * v1 - dic1
        dic2 = 2.0 * v2 - dic2
        level = abs(dk * v1)
        gr = ceiling / level if level > ceiling else 1.0
        env = gain_env_step(env, gr, atk, rel)
        A = math.sqrt(env)
        ck = 1.0 / (q * A)
        ca1 = 1.0 / (1.0 + cg * (cg + ck))
        ca2 = cg * ca1
        ca3 = cg * ca2
        cm1 = ck * (A * A - 1.0)
        cv3 = x - cic2
        cv1 = ca1 * cic1 + ca2 * cv3
        cv2 = cic2 + ca2 * cic1 + ca3 * cv3
        cic1 = 2.0 * cv1 - cic1
        cic2 = 2.0 * cv2 - cic2
        out.append(x + cm1 * cv1)
    return out


def _modea_two_channels(chA, chB, fc, q, sr, ceiling, atk_ms, rel_ms, linked):
    """Two channels with independent cut SVFs. If linked, one shared envelope
    from max(levelA, levelB); else independent envelopes."""
    det = svf_make("bandpass", fc, q, 1.0, sr)
    da1, da2, da3, dk = det["a1"], det["a2"], det["a3"], det["k"]
    atk, rel = env_coeffs(atk_ms, rel_ms, sr)
    cg = math.tan(math.pi * fc / sr)
    dA1 = dA2 = dB1 = dB2 = 0.0
    cA1 = cA2 = cB1 = cB2 = 0.0
    envA = envB = 1.0
    outA, outB = [], []
    for xa, xb in zip(chA, chB):
        v3 = xa - dA2; v1a = da1 * dA1 + da2 * v3; v2 = dA2 + da2 * dA1 + da3 * v3
        dA1 = 2.0 * v1a - dA1; dA2 = 2.0 * v2 - dA2
        v3 = xb - dB2; v1b = da1 * dB1 + da2 * v3; v2 = dB2 + da2 * dB1 + da3 * v3
        dB1 = 2.0 * v1b - dB1; dB2 = 2.0 * v2 - dB2
        levelA = abs(dk * v1a); levelB = abs(dk * v1b)
        if linked:
            lev = levelA if levelA > levelB else levelB
            gr = ceiling / lev if lev > ceiling else 1.0
            envA = gain_env_step(envA, gr, atk, rel); envB = envA
        else:
            grA = ceiling / levelA if levelA > ceiling else 1.0
            grB = ceiling / levelB if levelB > ceiling else 1.0
            envA = gain_env_step(envA, grA, atk, rel)
            envB = gain_env_step(envB, grB, atk, rel)
        A = math.sqrt(envA); ck = 1.0 / (q * A)
        ca1 = 1.0 / (1.0 + cg * (cg + ck)); ca2 = cg * ca1; ca3 = cg * ca2
        cm1 = ck * (A * A - 1.0)
        cv3 = xa - cA2; cv1 = ca1 * cA1 + ca2 * cv3; cv2 = cA2 + ca2 * cA1 + ca3 * cv3
        cA1 = 2.0 * cv1 - cA1; cA2 = 2.0 * cv2 - cA2
        outA.append(xa + cm1 * cv1)
        A = math.sqrt(envB); ck = 1.0 / (q * A)
        ca1 = 1.0 / (1.0 + cg * (cg + ck)); ca2 = cg * ca1; ca3 = cg * ca2
        cm1 = ck * (A * A - 1.0)
        cv3 = xb - cB2; cv1 = ca1 * cB1 + ca2 * cv3; cv2 = cB2 + ca2 * cB1 + ca3 * cv3
        cB1 = 2.0 * cv1 - cB1; cB2 = 2.0 * cv2 - cB2
        outB.append(xb + cm1 * cv1)
    return outA, outB


def modea_stereo(Lin, Rin, fc, q, sr, ceiling, atk_ms, rel_ms, dyn_mode):
    """Both-placement Mode-A with stereo linking (linked / dual_lr / dual_ms)."""
    if dyn_mode == "dual_ms":
        M = [(l + r) * 0.5 for l, r in zip(Lin, Rin)]
        S = [(l - r) * 0.5 for l, r in zip(Lin, Rin)]
        Mo, So = _modea_two_channels(M, S, fc, q, sr, ceiling, atk_ms, rel_ms, False)
        return ([m + s for m, s in zip(Mo, So)], [m - s for m, s in zip(Mo, So)])
    linked = dyn_mode == "linked"
    return _modea_two_channels(Lin, Rin, fc, q, sr, ceiling, atk_ms, rel_ms, linked)


# ---- Phase 3a: Mode B Brick (band-split, bit-exact) ----

def modeb_brick(signal, fc, q, sr, ceiling, look_ms, rel_ms):
    """Single-channel Mode-B Brick: band-split + lookahead worst-peak +
    bit-exact clamp + recombine. Guarantees the band contribution <= ceiling."""
    det = svf_make("bandpass", fc, q, 1.0, sr)
    a1, a2, a3, k = det["a1"], det["a2"], det["a3"], det["k"]
    L = max(1, int(look_ms * 0.001 * sr + 0.5))
    rel = math.exp(-1.0 / (rel_ms * 0.001 * sr))
    size = L + 1
    band_ring = [0.0] * size
    peak_ring = [0.0] * size
    dry_ring = [0.0] * size
    wpos = 0
    ic1 = ic2 = 0.0
    env = 1.0
    out = []
    for x in signal:
        v3 = x - ic2
        v1 = a1 * ic1 + a2 * v3
        v2 = ic2 + a2 * ic1 + a3 * v3
        ic1 = 2.0 * v1 - ic1
        ic2 = 2.0 * v2 - ic2
        b = k * v1
        band_ring[wpos] = b
        peak_ring[wpos] = abs(b)
        dry_ring[wpos] = x
        worst = 0.0
        for i in range(size):
            p = peak_ring[(wpos - i) % size]
            if p > worst:
                worst = p
        tgt = ceiling / worst if worst > ceiling else 1.0
        if tgt < env:
            env = tgt
        else:
            env = tgt + (env - tgt) * rel
            if env > 1.0:
                env = 1.0
        rpos = (wpos - L) % size
        bd = band_ring[rpos]
        xd = dry_ring[rpos]
        lim = bd * env
        if abs(lim) > ceiling:
            lim = ceiling if lim > 0 else -ceiling
        out.append(xd - bd + lim)
        wpos = (wpos + 1) % size
    return out


def _modeb_brick_two(chA, chB, fc, q, sr, ceiling, look_ms, rel_ms, linked):
    det = svf_make("bandpass", fc, q, 1.0, sr)
    a1, a2, a3, k = det["a1"], det["a2"], det["a3"], det["k"]
    L = max(1, int(look_ms * 0.001 * sr + 0.5))
    rel = math.exp(-1.0 / (rel_ms * 0.001 * sr))
    size = L + 1
    bA = [0.0] * size; pA = [0.0] * size; dA = [0.0] * size
    bB = [0.0] * size; pB = [0.0] * size; dB = [0.0] * size
    wpos = 0
    iA1 = iA2 = iB1 = iB2 = 0.0
    envA = envB = 1.0
    outA, outB = [], []

    def _worst(ring):
        w = 0.0
        for i in range(size):
            p = ring[(wpos - i) % size]
            if p > w:
                w = p
        return w

    for xa, xb in zip(chA, chB):
        v3 = xa - iA2; v1a = a1 * iA1 + a2 * v3; v2 = iA2 + a2 * iA1 + a3 * v3
        iA1 = 2.0 * v1a - iA1; iA2 = 2.0 * v2 - iA2
        v3 = xb - iB2; v1b = a1 * iB1 + a2 * v3; v2 = iB2 + a2 * iB1 + a3 * v3
        iB1 = 2.0 * v1b - iB1; iB2 = 2.0 * v2 - iB2
        ba = k * v1a; bb = k * v1b
        bA[wpos] = ba; pA[wpos] = abs(ba); dA[wpos] = xa
        bB[wpos] = bb; pB[wpos] = abs(bb); dB[wpos] = xb
        wa = _worst(pA); wb = _worst(pB)
        if linked:
            w = wa if wa > wb else wb
            tgt = ceiling / w if w > ceiling else 1.0
            if tgt < envA: envA = tgt
            else:
                envA = tgt + (envA - tgt) * rel
                if envA > 1.0: envA = 1.0
            envB = envA
        else:
            tgt = ceiling / wa if wa > ceiling else 1.0
            if tgt < envA: envA = tgt
            else:
                envA = tgt + (envA - tgt) * rel
                if envA > 1.0: envA = 1.0
            tgt = ceiling / wb if wb > ceiling else 1.0
            if tgt < envB: envB = tgt
            else:
                envB = tgt + (envB - tgt) * rel
                if envB > 1.0: envB = 1.0
        rpos = (wpos - L) % size
        bda = bA[rpos]; lim = bda * envA
        if abs(lim) > ceiling: lim = ceiling if lim > 0 else -ceiling
        outA.append(dA[rpos] - bda + lim)
        bdb = bB[rpos]; lim = bdb * envB
        if abs(lim) > ceiling: lim = ceiling if lim > 0 else -ceiling
        outB.append(dB[rpos] - bdb + lim)
        wpos = (wpos + 1) % size
    return outA, outB


def modeb_brick_stereo(Lin, Rin, fc, q, sr, ceiling, look_ms, rel_ms, dyn_mode):
    if dyn_mode == "dual_ms":
        M = [(l + r) * 0.5 for l, r in zip(Lin, Rin)]
        S = [(l - r) * 0.5 for l, r in zip(Lin, Rin)]
        Mo, So = _modeb_brick_two(M, S, fc, q, sr, ceiling, look_ms, rel_ms, False)
        return ([m + s for m, s in zip(Mo, So)], [m - s for m, s in zip(Mo, So)])
    linked = dyn_mode == "linked"
    return _modeb_brick_two(Lin, Rin, fc, q, sr, ceiling, look_ms, rel_ms, linked)


# ---- Phase 3b: Mode B Soft (band-split RCBitLimiter) ----

def modeb_soft(signal, fc, q, sr, ceiling, look_ms, rel_ms, gsmooth=400.0):
    """Single-channel Mode-B Soft: band-split + lookahead worst-peak + PurestGain
    gain smoothing (no clamp). May slightly exceed the ceiling on transients."""
    det = svf_make("bandpass", fc, q, 1.0, sr)
    a1, a2, a3, k = det["a1"], det["a2"], det["a3"], det["k"]
    L = max(1, int(look_ms * 0.001 * sr + 0.5))
    rel = math.exp(-1.0 / (rel_ms * 0.001 * sr))
    inv_g = 1.0 / (gsmooth + 1.0)
    size = L + 1
    br = [0.0] * size; pr = [0.0] * size; dr = [0.0] * size
    wpos = 0; ic1 = ic2 = 0.0; env = 1.0; gcur = 1.0
    out = []
    for x in signal:
        v3 = x - ic2
        v1 = a1 * ic1 + a2 * v3
        v2 = ic2 + a2 * ic1 + a3 * v3
        ic1 = 2.0 * v1 - ic1
        ic2 = 2.0 * v2 - ic2
        b = k * v1
        br[wpos] = b; pr[wpos] = abs(b); dr[wpos] = x
        worst = 0.0
        for i in range(size):
            p = pr[(wpos - i) % size]
            if p > worst:
                worst = p
        tgt = ceiling / worst if worst > ceiling else 1.0
        if tgt < env:
            env = tgt
        else:
            env = tgt + (env - tgt) * rel
            if env > 1.0:
                env = 1.0
        gcur = (gcur * gsmooth + env) * inv_g
        rpos = (wpos - L) % size
        bd = br[rpos]
        out.append(dr[rpos] - bd + bd * gcur)
        wpos = (wpos + 1) % size
    return out


def _modeb_soft_two(chA, chB, fc, q, sr, ceiling, look_ms, rel_ms, linked, gsmooth):
    det = svf_make("bandpass", fc, q, 1.0, sr)
    a1, a2, a3, k = det["a1"], det["a2"], det["a3"], det["k"]
    L = max(1, int(look_ms * 0.001 * sr + 0.5))
    rel = math.exp(-1.0 / (rel_ms * 0.001 * sr))
    inv_g = 1.0 / (gsmooth + 1.0)
    size = L + 1
    bA = [0.0]*size; pA = [0.0]*size; dA = [0.0]*size
    bB = [0.0]*size; pB = [0.0]*size; dB = [0.0]*size
    wpos = 0
    iA1 = iA2 = iB1 = iB2 = 0.0
    envA = envB = gcA = gcB = 1.0
    outA, outB = [], []

    def _worst(ring):
        w = 0.0
        for i in range(size):
            p = ring[(wpos - i) % size]
            if p > w:
                w = p
        return w

    for xa, xb in zip(chA, chB):
        v3 = xa - iA2; v1a = a1*iA1 + a2*v3; v2 = iA2 + a2*iA1 + a3*v3
        iA1 = 2.0*v1a - iA1; iA2 = 2.0*v2 - iA2
        v3 = xb - iB2; v1b = a1*iB1 + a2*v3; v2 = iB2 + a2*iB1 + a3*v3
        iB1 = 2.0*v1b - iB1; iB2 = 2.0*v2 - iB2
        ba = k*v1a; bb = k*v1b
        bA[wpos] = ba; pA[wpos] = abs(ba); dA[wpos] = xa
        bB[wpos] = bb; pB[wpos] = abs(bb); dB[wpos] = xb
        wa = _worst(pA); wb = _worst(pB)
        if linked:
            w = wa if wa > wb else wb
            tgt = ceiling / w if w > ceiling else 1.0
            if tgt < envA: envA = tgt
            else:
                envA = tgt + (envA - tgt) * rel
                if envA > 1.0: envA = 1.0
            envB = envA
        else:
            tgt = ceiling / wa if wa > ceiling else 1.0
            if tgt < envA: envA = tgt
            else:
                envA = tgt + (envA - tgt) * rel
                if envA > 1.0: envA = 1.0
            tgt = ceiling / wb if wb > ceiling else 1.0
            if tgt < envB: envB = tgt
            else:
                envB = tgt + (envB - tgt) * rel
                if envB > 1.0: envB = 1.0
        gcA = (gcA * gsmooth + envA) * inv_g
        gcB = (gcB * gsmooth + envB) * inv_g
        rpos = (wpos - L) % size
        bda = bA[rpos]; outA.append(dA[rpos] - bda + bda * gcA)
        bdb = bB[rpos]; outB.append(dB[rpos] - bdb + bdb * gcB)
        wpos = (wpos + 1) % size
    return outA, outB


def modeb_soft_stereo(Lin, Rin, fc, q, sr, ceiling, look_ms, rel_ms, dyn_mode, gsmooth=400.0):
    if dyn_mode == "dual_ms":
        M = [(l + r) * 0.5 for l, r in zip(Lin, Rin)]
        S = [(l - r) * 0.5 for l, r in zip(Lin, Rin)]
        Mo, So = _modeb_soft_two(M, S, fc, q, sr, ceiling, look_ms, rel_ms, False, gsmooth)
        return ([m + s for m, s in zip(Mo, So)], [m - s for m, s in zip(Mo, So)])
    linked = dyn_mode == "linked"
    return _modeb_soft_two(Lin, Rin, fc, q, sr, ceiling, look_ms, rel_ms, linked, gsmooth)


# ---- Phase 3c: Mode B Soft+Hard cascade (two ceilings) ----

def _modeb_cascade_ch(chA, chB, two, fc, q, sr, cS, cH, look_ms, rel_ms,
                      soft_on, hard_on, linked, gsmooth):
    """1 or 2 channels through the Soft+Hard cascade (one lookahead)."""
    det = svf_make("bandpass", fc, q, 1.0, sr)
    a1, a2, a3, k = det["a1"], det["a2"], det["a3"], det["k"]
    L = max(1, int(look_ms * 0.001 * sr + 0.5))
    rel = math.exp(-1.0 / (rel_ms * 0.001 * sr))
    inv_g = 1.0 / (gsmooth + 1.0)
    size = L + 1
    bA = [0.0]*size; pA = [0.0]*size; dA = [0.0]*size
    bB = [0.0]*size; pB = [0.0]*size; dB = [0.0]*size
    wpos = 0
    iA1 = iA2 = iB1 = iB2 = 0.0
    envSA = gcA = envHA = 1.0
    envSB = gcB = envHB = 1.0
    outA = []
    outB = [] if two else None

    def _worst(ring):
        w = 0.0
        for i in range(size):
            p = ring[(wpos - i) % size]
            if p > w:
                w = p
        return w

    def _stage(worst, envS, gc, envH):
        if soft_on:
            tS = cS / worst if worst > cS else 1.0
            envS = tS if tS < envS else min(1.0, tS + (envS - tS) * rel)
            gc = (gc * gsmooth + envS) * inv_g
        else:
            gc = 1.0
        if hard_on:
            ps = worst * gc
            tH = cH / ps if ps > cH else 1.0
            envH = tH if tH < envH else min(1.0, tH + (envH - tH) * rel)
        else:
            envH = 1.0
        return gc * envH, envS, gc, envH

    xbs = chB if two else chA
    for xa, xb in zip(chA, xbs):
        v3 = xa - iA2; v1a = a1*iA1 + a2*v3; v2 = iA2 + a2*iA1 + a3*v3
        iA1 = 2.0*v1a - iA1; iA2 = 2.0*v2 - iA2
        ba = k * v1a
        bA[wpos] = ba; pA[wpos] = abs(ba); dA[wpos] = xa
        if two:
            v3 = xb - iB2; v1b = a1*iB1 + a2*v3; v2 = iB2 + a2*iB1 + a3*v3
            iB1 = 2.0*v1b - iB1; iB2 = 2.0*v2 - iB2
            bb = k * v1b
            bB[wpos] = bb; pB[wpos] = abs(bb); dB[wpos] = xb
        wa = _worst(pA)
        wb = _worst(pB) if two else 0.0
        if linked:
            w = wa if wa > wb else wb
            gA, envSA, gcA, envHA = _stage(w, envSA, gcA, envHA)
            gB = gA
        else:
            gA, envSA, gcA, envHA = _stage(wa, envSA, gcA, envHA)
            gB = 1.0
            if two:
                gB, envSB, gcB, envHB = _stage(wb, envSB, gcB, envHB)
        rpos = (wpos - L) % size
        bda = bA[rpos]; lim = bda * gA
        if hard_on and abs(lim) > cH:
            lim = cH if lim > 0 else -cH
        outA.append(dA[rpos] - bda + lim)
        if two:
            bdb = bB[rpos]; lim = bdb * gB
            if hard_on and abs(lim) > cH:
                lim = cH if lim > 0 else -cH
            outB.append(dB[rpos] - bdb + lim)
        wpos = (wpos + 1) % size
    return outA, outB


def modeb_cascade(signal, fc, q, sr, ceil_soft, ceil_hard, look_ms, rel_ms,
                  soft_on, hard_on, gsmooth=400.0):
    out, _ = _modeb_cascade_ch(signal, signal, False, fc, q, sr, ceil_soft, ceil_hard,
                               look_ms, rel_ms, soft_on, hard_on, False, gsmooth)
    return out


def modeb_cascade_stereo(Lin, Rin, fc, q, sr, ceil_soft, ceil_hard, look_ms, rel_ms,
                         soft_on, hard_on, dyn_mode, gsmooth=400.0):
    if dyn_mode == "dual_ms":
        M = [(l + r) * 0.5 for l, r in zip(Lin, Rin)]
        S = [(l - r) * 0.5 for l, r in zip(Lin, Rin)]
        Mo, So = _modeb_cascade_ch(M, S, True, fc, q, sr, ceil_soft, ceil_hard,
                                   look_ms, rel_ms, soft_on, hard_on, False, gsmooth)
        return ([m + s for m, s in zip(Mo, So)], [m - s for m, s in zip(Mo, So)])
    linked = dyn_mode == "linked"
    A, B = _modeb_cascade_ch(Lin, Rin, True, fc, q, sr, ceil_soft, ceil_hard,
                             look_ms, rel_ms, soft_on, hard_on, linked, gsmooth)
    return A, B


# ---- Phase 2c: Mode A Soft+Hard cascade (bell-cut) ----

def _modea_cascade_ch(chA, chB, two, fc, q, sr, cS, cH, atk_ms, rel_ms,
                      soft_on, hard_on, linked):
    det = svf_make("bandpass", fc, q, 1.0, sr)
    da1, da2, da3, dk = det["a1"], det["a2"], det["a3"], det["k"]
    atk, rel = env_coeffs(atk_ms, rel_ms, sr)
    cg = math.tan(math.pi * fc / sr)
    dA1 = dA2 = dB1 = dB2 = 0.0
    cA1 = cA2 = cB1 = cB2 = 0.0
    esA = ehA = esB = ehB = 1.0
    outA = []
    outB = [] if two else None

    def _gain(level, es, eh):
        if soft_on:
            tS = cS / level if level > cS else 1.0
            es = gain_env_step(es, tS, atk, rel)
            gS = es
        else:
            gS = 1.0
        if hard_on:
            ps = level * gS
            tH = cH / ps if ps > cH else 1.0
            eh = gain_env_step(eh, tH, 0.0, rel)   # instant attack
            gH = eh
        else:
            gH = 1.0
        return gS * gH, es, eh

    def _cut(x, g, c1, c2):
        A = math.sqrt(g); ck = 1.0 / (q * A)
        ca1 = 1.0 / (1.0 + cg * (cg + ck)); ca2 = cg * ca1; ca3 = cg * ca2
        cm1 = ck * (A * A - 1.0)
        cv3 = x - c2; cv1 = ca1 * c1 + ca2 * cv3; cv2 = c2 + ca2 * c1 + ca3 * cv3
        return x + cm1 * cv1, 2.0 * cv1 - c1, 2.0 * cv2 - c2

    xbs = chB if two else chA
    for xa, xb in zip(chA, xbs):
        v3 = xa - dA2; v1a = da1 * dA1 + da2 * v3; v2 = dA2 + da2 * dA1 + da3 * v3
        dA1 = 2.0 * v1a - dA1; dA2 = 2.0 * v2 - dA2
        lvA = abs(dk * v1a)
        lvB = 0.0
        if two:
            v3 = xb - dB2; v1b = da1 * dB1 + da2 * v3; v2 = dB2 + da2 * dB1 + da3 * v3
            dB1 = 2.0 * v1b - dB1; dB2 = 2.0 * v2 - dB2
            lvB = abs(dk * v1b)
        if linked:
            lev = lvA if lvA > lvB else lvB
            gA, esA, ehA = _gain(lev, esA, ehA)
            gB = gA
        else:
            gA, esA, ehA = _gain(lvA, esA, ehA)
            gB = 1.0
            if two:
                gB, esB, ehB = _gain(lvB, esB, ehB)
        oa, cA1, cA2 = _cut(xa, gA, cA1, cA2)
        outA.append(oa)
        if two:
            ob, cB1, cB2 = _cut(xb, gB, cB1, cB2)
            outB.append(ob)
    return outA, outB


def modea_cascade(signal, fc, q, sr, ceil_soft, ceil_hard, atk_ms, rel_ms, soft_on, hard_on):
    out, _ = _modea_cascade_ch(signal, signal, False, fc, q, sr, ceil_soft, ceil_hard,
                               atk_ms, rel_ms, soft_on, hard_on, False)
    return out


def modea_cascade_stereo(Lin, Rin, fc, q, sr, ceil_soft, ceil_hard, atk_ms, rel_ms,
                         soft_on, hard_on, dyn_mode):
    if dyn_mode == "dual_ms":
        M = [(l + r) * 0.5 for l, r in zip(Lin, Rin)]
        S = [(l - r) * 0.5 for l, r in zip(Lin, Rin)]
        Mo, So = _modea_cascade_ch(M, S, True, fc, q, sr, ceil_soft, ceil_hard,
                                   atk_ms, rel_ms, soft_on, hard_on, False)
        return ([m + s for m, s in zip(Mo, So)], [m - s for m, s in zip(Mo, So)])
    linked = dyn_mode == "linked"
    A, B = _modea_cascade_ch(Lin, Rin, True, fc, q, sr, ceil_soft, ceil_hard,
                             atk_ms, rel_ms, soft_on, hard_on, linked)
    return A, B


# ---- Phase S-A: Mode A shelf dynamics (V0.2) ----

DET_Q = 0.7071  # fixed shelf-region detector Q (Butterworth: monotonic, no bump)


def shelf_cut_coeffs(shelf_type, g0, q, gdyn):
    """Per-sample shelf-cut coefficients without tan(). g0 = tan(pi*fc/sr),
    precomputed once. Matches svf_make(shelf_type, fc, q, gdyn, sr) exactly:
    the only fc-dependent term is g = g0 * gdyn**0.25 (highshelf) or
    g0 / gdyn**0.25 (lowshelf). shelf_type: 'lowshelf' | 'highshelf'."""
    A = math.sqrt(gdyn)
    rA = math.sqrt(A)
    k = 1.0 / q
    if shelf_type == "highshelf":
        g = g0 * rA
        m0, m1, m2 = A * A, k * (1.0 - A) * A, (1.0 - A * A)
    elif shelf_type == "lowshelf":
        g = g0 / rA
        m0, m1, m2 = 1.0, k * (A - 1.0), (A * A - 1.0)
    else:
        raise ValueError(f"unknown shelf_type {shelf_type!r}")
    a1 = 1.0 / (1.0 + g * (g + k))
    a2 = g * a1
    a3 = g * a2
    return a1, a2, a3, k, m0, m1, m2


def _shelf_cascade_ch(chA, chB, two, shelf_type, fc, q, sr, cS, cH,
                      atk_ms, rel_ms, soft_on, hard_on, linked):
    """Mode-A shelf dynamics, one or two channels (mirror of _modea_cascade_ch).
    Detector: HP tap (highshelf) / LP tap (lowshelf) of an SVF at fc with fixed
    DET_Q. Cut: full shelf filter of the band's fc/q, gain = gSoft * gHard from
    the existing Soft+Hard cascade. q is the band's shelf Q (audio path only)."""
    high = shelf_type == "highshelf"
    det = svf_make("hp" if high else "lp", fc, DET_Q, 1.0, sr)
    da1, da2, da3, dk = det["a1"], det["a2"], det["a3"], det["k"]
    atk, rel = env_coeffs(atk_ms, rel_ms, sr)
    g0 = math.tan(math.pi * fc / sr)
    dA1 = dA2 = dB1 = dB2 = 0.0
    cA1 = cA2 = cB1 = cB2 = 0.0
    esA = ehA = esB = ehB = 1.0
    outA = []
    outB = [] if two else None

    def _gain(level, es, eh):
        if soft_on:
            tS = cS / level if level > cS else 1.0
            es = gain_env_step(es, tS, atk, rel)
            gS = es
        else:
            gS = 1.0
        if hard_on:
            ps = level * gS
            tH = cH / ps if ps > cH else 1.0
            eh = gain_env_step(eh, tH, 0.0, rel)   # instant attack
            gH = eh
        else:
            gH = 1.0
        return gS * gH, es, eh

    def _cut(x, gdyn, c1, c2):
        a1, a2, a3, k, m0, m1, m2 = shelf_cut_coeffs(shelf_type, g0, q, gdyn)
        v3 = x - c2
        v1 = a1 * c1 + a2 * v3
        v2 = c2 + a2 * c1 + a3 * v3
        return m0 * x + m1 * v1 + m2 * v2, 2.0 * v1 - c1, 2.0 * v2 - c2

    xbs = chB if two else chA
    for xa, xb in zip(chA, xbs):
        v3 = xa - dA2; v1 = da1 * dA1 + da2 * v3; v2 = dA2 + da2 * dA1 + da3 * v3
        dA1 = 2.0 * v1 - dA1; dA2 = 2.0 * v2 - dA2
        lvA = abs(xa - dk * v1 - v2) if high else abs(v2)
        lvB = 0.0
        if two:
            v3 = xb - dB2; v1 = da1 * dB1 + da2 * v3; v2 = dB2 + da2 * dB1 + da3 * v3
            dB1 = 2.0 * v1 - dB1; dB2 = 2.0 * v2 - dB2
            lvB = abs(xb - dk * v1 - v2) if high else abs(v2)
        if linked:
            lev = lvA if lvA > lvB else lvB
            gA, esA, ehA = _gain(lev, esA, ehA)
            gB = gA
        else:
            gA, esA, ehA = _gain(lvA, esA, ehA)
            gB = 1.0
            if two:
                gB, esB, ehB = _gain(lvB, esB, ehB)
        oa, cA1, cA2 = _cut(xa, gA, cA1, cA2)
        outA.append(oa)
        if two:
            ob, cB1, cB2 = _cut(xb, gB, cB1, cB2)
            outB.append(ob)
    return outA, outB


def shelf_cascade(signal, shelf_type, fc, q, sr, ceil_soft, ceil_hard,
                  atk_ms, rel_ms, soft_on, hard_on):
    out, _ = _shelf_cascade_ch(signal, signal, False, shelf_type, fc, q, sr,
                               ceil_soft, ceil_hard, atk_ms, rel_ms,
                               soft_on, hard_on, False)
    return out


def shelf_cascade_stereo(Lin, Rin, shelf_type, fc, q, sr, ceil_soft, ceil_hard,
                         atk_ms, rel_ms, soft_on, hard_on, dyn_mode):
    if dyn_mode == "dual_ms":
        M = [(l + r) * 0.5 for l, r in zip(Lin, Rin)]
        S = [(l - r) * 0.5 for l, r in zip(Lin, Rin)]
        Mo, So = _shelf_cascade_ch(M, S, True, shelf_type, fc, q, sr, ceil_soft,
                                   ceil_hard, atk_ms, rel_ms, soft_on, hard_on,
                                   False)
        return ([m + s for m, s in zip(Mo, So)], [m - s for m, s in zip(Mo, So)])
    linked = dyn_mode == "linked"
    return _shelf_cascade_ch(Lin, Rin, True, shelf_type, fc, q, sr, ceil_soft,
                             ceil_hard, atk_ms, rel_ms, soft_on, hard_on, linked)


def _shelf_modeb_cascade_ch(chA, chB, two, shelf_type, fc, sr, cS, cH, look_ms, rel_ms,
                            soft_on, hard_on, linked, gsmooth):
    """Mode-B shelf split limiter, 1 or 2 channels (mirror of _modeb_cascade_ch).
    Extracts the shelf region via a fixed-DET_Q SVF: HP tap (high shelf) or LP tap
    (low shelf), limits that branch through the same Soft+Hard lookahead cascade as
    Bell, and passes the remainder untouched (perfect reconstruction LP + k*BP + HP
    == input). Band shelf Q is intentionally unused (spec section 4 Q-asymmetry)."""
    high = shelf_type == "highshelf"
    det = svf_make("hp" if high else "lp", fc, DET_Q, 1.0, sr)
    a1, a2, a3, k = det["a1"], det["a2"], det["a3"], det["k"]
    L = max(1, int(look_ms * 0.001 * sr + 0.5))
    rel = math.exp(-1.0 / (rel_ms * 0.001 * sr))
    inv_g = 1.0 / (gsmooth + 1.0)
    size = L + 1
    bA = [0.0]*size; pA = [0.0]*size; dA = [0.0]*size
    bB = [0.0]*size; pB = [0.0]*size; dB = [0.0]*size
    wpos = 0
    iA1 = iA2 = iB1 = iB2 = 0.0
    envSA = gcA = envHA = 1.0
    envSB = gcB = envHB = 1.0
    outA = []
    outB = [] if two else None

    def _worst(ring):
        w = 0.0
        for i in range(size):
            p = ring[(wpos - i) % size]
            if p > w:
                w = p
        return w

    def _stage(worst, envS, gc, envH):
        if soft_on:
            tS = cS / worst if worst > cS else 1.0
            envS = tS if tS < envS else min(1.0, tS + (envS - tS) * rel)
            gc = (gc * gsmooth + envS) * inv_g
        else:
            gc = 1.0
        if hard_on:
            ps = worst * gc
            tH = cH / ps if ps > cH else 1.0
            envH = tH if tH < envH else min(1.0, tH + (envH - tH) * rel)
        else:
            envH = 1.0
        return gc * envH, envS, gc, envH

    xbs = chB if two else chA
    for xa, xb in zip(chA, xbs):
        v3 = xa - iA2; v1a = a1*iA1 + a2*v3; v2 = iA2 + a2*iA1 + a3*v3
        iA1 = 2.0*v1a - iA1; iA2 = 2.0*v2 - iA2
        ba = (xa - k*v1a - v2) if high else v2
        bA[wpos] = ba; pA[wpos] = abs(ba); dA[wpos] = xa
        if two:
            v3 = xb - iB2; v1b = a1*iB1 + a2*v3; v2 = iB2 + a2*iB1 + a3*v3
            iB1 = 2.0*v1b - iB1; iB2 = 2.0*v2 - iB2
            bb = (xb - k*v1b - v2) if high else v2
            bB[wpos] = bb; pB[wpos] = abs(bb); dB[wpos] = xb
        wa = _worst(pA)
        wb = _worst(pB) if two else 0.0
        if linked:
            w = wa if wa > wb else wb
            gA, envSA, gcA, envHA = _stage(w, envSA, gcA, envHA)
            gB = gA
        else:
            gA, envSA, gcA, envHA = _stage(wa, envSA, gcA, envHA)
            gB = 1.0
            if two:
                gB, envSB, gcB, envHB = _stage(wb, envSB, gcB, envHB)
        rpos = (wpos - L) % size
        bda = bA[rpos]; lim = bda * gA
        if hard_on and abs(lim) > cH:
            lim = cH if lim > 0 else -cH
        outA.append(dA[rpos] - bda + lim)
        if two:
            bdb = bB[rpos]; lim = bdb * gB
            if hard_on and abs(lim) > cH:
                lim = cH if lim > 0 else -cH
            outB.append(dB[rpos] - bdb + lim)
        wpos = (wpos + 1) % size
    return outA, outB


def shelf_modeb_cascade(signal, shelf_type, fc, q, sr, ceil_soft, ceil_hard,
                        look_ms, rel_ms, soft_on, hard_on, gsmooth=400.0):
    # q accepted for API parallelism with shelf_cascade; Mode B split ignores the
    # band Q (fixed DET_Q, spec section 4 Q-asymmetry).
    out, _ = _shelf_modeb_cascade_ch(signal, signal, False, shelf_type, fc, sr,
                                     ceil_soft, ceil_hard, look_ms, rel_ms,
                                     soft_on, hard_on, False, gsmooth)
    return out


def shelf_modeb_cascade_stereo(Lin, Rin, shelf_type, fc, q, sr, ceil_soft, ceil_hard,
                               look_ms, rel_ms, soft_on, hard_on, dyn_mode, gsmooth=400.0):
    if dyn_mode == "dual_ms":
        M = [(l + r) * 0.5 for l, r in zip(Lin, Rin)]
        S = [(l - r) * 0.5 for l, r in zip(Lin, Rin)]
        Mo, So = _shelf_modeb_cascade_ch(M, S, True, shelf_type, fc, sr, ceil_soft,
                                         ceil_hard, look_ms, rel_ms, soft_on, hard_on,
                                         False, gsmooth)
        return ([m + s for m, s in zip(Mo, So)], [m - s for m, s in zip(Mo, So)])
    linked = dyn_mode == "linked"
    return _shelf_modeb_cascade_ch(Lin, Rin, True, shelf_type, fc, sr, ceil_soft,
                                   ceil_hard, look_ms, rel_ms, soft_on, hard_on,
                                   linked, gsmooth)
