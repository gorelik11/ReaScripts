import math
import cmath
import pytest
from tools import rcbitnova_dsp as dsp


def test_bit_gain_integer_macro_is_exact_power_of_two():
    assert dsp.bit_gain(1, 0, 1) == 2.0
    assert dsp.bit_gain(2, 0, 1) == 4.0
    assert dsp.bit_gain(-1, 0, 1) == 0.5
    assert dsp.bit_gain(0, 0, 1) == 1.0


def test_bit_gain_micro_is_fraction_of_a_bit():
    assert dsp.bit_gain(0, 100, 1) == pytest.approx(2.0)
    assert dsp.bit_gain(0, -100, 1) == pytest.approx(0.5)


def test_bit_gain_bit_ratio_scales_bits():
    assert dsp.bit_gain(1, 0, 0.5) == pytest.approx(2 ** 0.5)
    assert dsp.bit_gain(2, 0, 0.25) == pytest.approx(2 ** 0.5)


def test_bit_gain_db():
    assert dsp.bit_gain_db(1, 0, 1) == pytest.approx(6.0206)
    assert dsp.bit_gain_db(0, 0, 1) == 0.0


def test_ms_encode():
    assert dsp.encode_ms(1.0, 0.0) == (0.5, 0.5)
    assert dsp.encode_ms(1.0, 1.0) == (1.0, 0.0)


def test_ms_roundtrip():
    for l, r in [(0.3, -0.7), (1.0, 0.0), (-0.2, 0.9)]:
        m, s = dsp.encode_ms(l, r)
        l2, r2 = dsp.decode_ms(m, s)
        assert l2 == pytest.approx(l)
        assert r2 == pytest.approx(r)


SR = 48000


def test_lowpass_passes_dc_blocks_highs():
    c = dsp.svf_make("lp", 1000.0, 0.707, 1.0, SR)
    assert dsp.svf_magnitude(c, 20.0, SR) == pytest.approx(1.0, abs=0.01)
    assert dsp.svf_magnitude(c, 18000.0, SR) < 0.02


def test_highpass_blocks_dc_passes_highs():
    c = dsp.svf_make("hp", 1000.0, 0.707, 1.0, SR)
    assert dsp.svf_magnitude(c, 20.0, SR) < 0.02
    assert dsp.svf_magnitude(c, 18000.0, SR) == pytest.approx(1.0, abs=0.01)


def test_bell_exact_gain_at_center_and_unity_far_away():
    for bits, expect in [(1, 2.0), (2, 4.0), (-1, 0.5)]:
        c = dsp.svf_make("bell", 1000.0, 2.0, dsp.bit_gain(bits, 0, 1), SR)
        assert dsp.svf_magnitude(c, 1000.0, SR) == pytest.approx(expect, rel=0.01)
        assert dsp.svf_magnitude(c, 60.0, SR) == pytest.approx(1.0, abs=0.01)


def test_bell_no_cramping_at_top_octave():
    # A high bell at 18 kHz @ 48k must still reach its exact center gain.
    c = dsp.svf_make("bell", 18000.0, 2.0, dsp.bit_gain(2, 0, 1), SR)
    assert dsp.svf_magnitude(c, 18000.0, SR) == pytest.approx(4.0, rel=0.02)


def test_lowshelf_boosts_dc_unity_highs():
    c = dsp.svf_make("lowshelf", 300.0, 0.707, dsp.bit_gain(1, 0, 1), SR)
    assert dsp.svf_magnitude(c, 20.0, SR) == pytest.approx(2.0, rel=0.02)
    assert dsp.svf_magnitude(c, 18000.0, SR) == pytest.approx(1.0, abs=0.02)


def test_highshelf_boosts_highs_unity_dc():
    c = dsp.svf_make("highshelf", 4000.0, 0.707, dsp.bit_gain(1, 0, 1), SR)
    assert dsp.svf_magnitude(c, 20000.0, SR) == pytest.approx(2.0, rel=0.02)
    assert dsp.svf_magnitude(c, 20.0, SR) == pytest.approx(1.0, abs=0.02)


def _stereo_sigs(n=4096):
    wl = 2 * math.pi * 700.0 / SR
    wr = 2 * math.pi * 1500.0 / SR
    L = [0.5 * math.sin(wl * i) for i in range(n)]
    R = [0.4 * math.sin(wr * i) for i in range(n)]
    return L, R


def test_placement_left_leaves_right_untouched():
    L, R = _stereo_sigs()
    Lout, Rout = dsp.process_band_stereo("bell", "left", 700.0, 2.0,
                                         dsp.bit_gain(1, 0, 1), SR, L, R)
    assert Rout == R
    assert Lout == dsp.svf_process(dsp.svf_make("bell", 700.0, 2.0,
                                   dsp.bit_gain(1, 0, 1), SR), L)


def test_placement_right_leaves_left_untouched():
    L, R = _stereo_sigs()
    Lout, Rout = dsp.process_band_stereo("bell", "right", 1500.0, 2.0,
                                         dsp.bit_gain(1, 0, 1), SR, L, R)
    assert Lout == L


def test_placement_mid_leaves_side_untouched():
    L, R = _stereo_sigs()
    Lout, Rout = dsp.process_band_stereo("bell", "mid", 700.0, 2.0,
                                         dsp.bit_gain(2, 0, 1), SR, L, R)
    side_in = [(l - r) * 0.5 for l, r in zip(L, R)]
    side_out = [(l - r) * 0.5 for l, r in zip(Lout, Rout)]
    assert side_out == pytest.approx(side_in, abs=1e-12)


def test_placement_side_leaves_mid_untouched():
    L, R = _stereo_sigs()
    Lout, Rout = dsp.process_band_stereo("bell", "side", 700.0, 2.0,
                                         dsp.bit_gain(2, 0, 1), SR, L, R)
    mid_in = [(l + r) * 0.5 for l, r in zip(L, R)]
    mid_out = [(l + r) * 0.5 for l, r in zip(Lout, Rout)]
    assert mid_out == pytest.approx(mid_in, abs=1e-12)


def test_placement_both_filters_each_channel():
    L, R = _stereo_sigs()
    g = dsp.bit_gain(1, 0, 1)
    Lout, Rout = dsp.process_band_stereo("bell", "both", 700.0, 2.0, g, SR, L, R)
    assert Lout == dsp.svf_process(dsp.svf_make("bell", 700.0, 2.0, g, SR), L)
    assert Rout == dsp.svf_process(dsp.svf_make("bell", 700.0, 2.0, g, SR), R)


# ---- Phase 2b: Soft dynamics (Mode A) + stereo linking ----

def test_ceiling_lin_bits_below_zero():
    assert dsp.ceiling_lin(0, 0) == 1.0
    assert dsp.ceiling_lin(1, 0) == 0.5
    assert dsp.ceiling_lin(2, 0) == 0.25
    assert dsp.ceiling_lin(1, 50) == pytest.approx(2 ** -1.5)


def test_bandpass_detector_unity_at_center_low_off_band():
    c = dsp.svf_make("bandpass", 1000.0, 2.0, 1.0, SR)
    assert dsp.svf_magnitude(c, 1000.0, SR) == pytest.approx(1.0, abs=0.02)
    assert dsp.svf_magnitude(c, 250.0, SR) < 0.3
    assert dsp.svf_magnitude(c, 4000.0, SR) < 0.3


def test_env_coeffs_ordering():
    atk, rel = dsp.env_coeffs(1.0, 80.0, SR)
    assert 0.0 < atk < rel < 1.0


def test_gain_env_converges_and_instant():
    atk, rel = dsp.env_coeffs(1.0, 80.0, SR)
    env = 1.0
    for _ in range(20000):
        env = dsp.gain_env_step(env, 0.5, atk, rel)
    assert env == pytest.approx(0.5, abs=1e-3)
    assert dsp.gain_env_step(1.0, 0.3, 0.0, 0.9) == pytest.approx(0.3)


def _band_peak(samples, tail=2000):
    return max(abs(v) for v in samples[-tail:])


def test_modea_pulls_band_to_ceiling():
    w = 2 * math.pi * 1000.0 / SR
    sig = [0.8 * math.sin(w * i) for i in range(1 << 15)]
    out = dsp.modea_process(sig, 1000.0, 2.0, SR, 0.2, 1.0, 80.0)
    assert 0.18 <= _band_peak(out) <= 0.24


def test_modea_transparent_below_ceiling():
    w = 2 * math.pi * 1000.0 / SR
    sig = [0.8 * math.sin(w * i) for i in range(1 << 15)]
    out = dsp.modea_process(sig, 1000.0, 2.0, SR, 2.0, 1.0, 80.0)
    assert _band_peak(out) == pytest.approx(0.8, abs=0.02)


def test_modea_dual_lr_equals_independent_channels():
    L, R = _stereo_sigs(1 << 14)
    Lo, Ro = dsp.modea_stereo(L, R, 700.0, 2.0, SR, 0.2, 1.0, 80.0, "dual_lr")
    assert Lo == dsp.modea_process(L, 700.0, 2.0, SR, 0.2, 1.0, 80.0)
    assert Ro == dsp.modea_process(R, 700.0, 2.0, SR, 0.2, 1.0, 80.0)


def test_modea_dual_ms_equals_independent_ms():
    L, R = _stereo_sigs(1 << 14)
    M = [(l + r) * 0.5 for l, r in zip(L, R)]
    S = [(l - r) * 0.5 for l, r in zip(L, R)]
    Mo = dsp.modea_process(M, 700.0, 2.0, SR, 0.2, 1.0, 80.0)
    So = dsp.modea_process(S, 700.0, 2.0, SR, 0.2, 1.0, 80.0)
    Lo, Ro = dsp.modea_stereo(L, R, 700.0, 2.0, SR, 0.2, 1.0, 80.0, "dual_ms")
    assert Lo == pytest.approx([m + s for m, s in zip(Mo, So)], abs=1e-12)
    assert Ro == pytest.approx([m - s for m, s in zip(Mo, So)], abs=1e-12)


def test_modea_linked_applies_equal_gain_no_width_shift():
    w = 2 * math.pi * 700.0 / SR
    mono = [0.8 * math.sin(w * i) for i in range(1 << 14)]
    Lo, Ro = dsp.modea_stereo(mono, list(mono), 700.0, 2.0, SR, 0.2, 1.0, 80.0, "linked")
    assert Lo == pytest.approx(Ro, abs=1e-12)


# ---- Phase 3a: Mode B Brick (band-split, bit-exact) ----

def _band_contrib_peak(out, fc, q, sr, tail=2000):
    bp = dsp.svf_process(dsp.svf_make("bandpass", fc, q, 1.0, sr), out)
    return max(abs(v) for v in bp[-tail:])


def test_modeb_brick_holds_band_at_exact_ceiling():
    w = 2 * math.pi * 1000.0 / SR
    sig = [0.8 * math.sin(w * i) for i in range(1 << 15)]
    for ceiling in (0.25, 0.2, 0.1):
        out = dsp.modeb_brick(sig, 1000.0, 2.0, SR, ceiling, 2.0, 80.0)
        pk = _band_contrib_peak(out, 1000.0, 2.0, SR)
        assert pk <= ceiling * 1.001
        assert pk == pytest.approx(ceiling, rel=0.01)


def test_modeb_brick_transparent_below_ceiling():
    w = 2 * math.pi * 1000.0 / SR
    sig = [0.1 * math.sin(w * i) for i in range(1 << 15)]
    out = dsp.modeb_brick(sig, 1000.0, 2.0, SR, 0.5, 2.0, 80.0)
    assert _band_contrib_peak(out, 1000.0, 2.0, SR) == pytest.approx(0.1, abs=0.01)


def test_modeb_brick_dual_lr_equals_independent():
    L, R = _stereo_sigs(1 << 14)
    Lo, Ro = dsp.modeb_brick_stereo(L, R, 700.0, 2.0, SR, 0.2, 2.0, 80.0, "dual_lr")
    assert Lo == dsp.modeb_brick(L, 700.0, 2.0, SR, 0.2, 2.0, 80.0)
    assert Ro == dsp.modeb_brick(R, 700.0, 2.0, SR, 0.2, 2.0, 80.0)


def test_modeb_brick_dual_ms_equals_independent_ms():
    L, R = _stereo_sigs(1 << 14)
    M = [(l + r) * 0.5 for l, r in zip(L, R)]
    S = [(l - r) * 0.5 for l, r in zip(L, R)]
    Mo = dsp.modeb_brick(M, 700.0, 2.0, SR, 0.2, 2.0, 80.0)
    So = dsp.modeb_brick(S, 700.0, 2.0, SR, 0.2, 2.0, 80.0)
    Lo, Ro = dsp.modeb_brick_stereo(L, R, 700.0, 2.0, SR, 0.2, 2.0, 80.0, "dual_ms")
    assert Lo == pytest.approx([m + s for m, s in zip(Mo, So)], abs=1e-12)
    assert Ro == pytest.approx([m - s for m, s in zip(Mo, So)], abs=1e-12)


def test_modeb_brick_linked_equal_gain():
    w = 2 * math.pi * 700.0 / SR
    mono = [0.8 * math.sin(w * i) for i in range(1 << 14)]
    Lo, Ro = dsp.modeb_brick_stereo(mono, list(mono), 700.0, 2.0, SR, 0.2, 2.0, 80.0, "linked")
    assert Lo == pytest.approx(Ro, abs=1e-12)


# ---- Phase 3b: Mode B Soft (band-split RCBitLimiter) ----

def test_modeb_soft_limits_toward_ceiling():
    w = 2 * math.pi * 1000.0 / SR
    sig = [0.8 * math.sin(w * i) for i in range(1 << 15)]
    out = dsp.modeb_soft(sig, 1000.0, 2.0, SR, 0.2, 2.0, 80.0)
    pk = _band_contrib_peak(out, 1000.0, 2.0, SR)
    assert 0.18 <= pk <= 0.24


def test_modeb_soft_transparent_below_ceiling():
    w = 2 * math.pi * 1000.0 / SR
    sig = [0.1 * math.sin(w * i) for i in range(1 << 15)]
    out = dsp.modeb_soft(sig, 1000.0, 2.0, SR, 0.5, 2.0, 80.0)
    assert _band_contrib_peak(out, 1000.0, 2.0, SR) == pytest.approx(0.1, abs=0.01)


def test_modeb_soft_dual_lr_equals_independent():
    L, R = _stereo_sigs(1 << 14)
    Lo, Ro = dsp.modeb_soft_stereo(L, R, 700.0, 2.0, SR, 0.2, 2.0, 80.0, "dual_lr")
    assert Lo == dsp.modeb_soft(L, 700.0, 2.0, SR, 0.2, 2.0, 80.0)
    assert Ro == dsp.modeb_soft(R, 700.0, 2.0, SR, 0.2, 2.0, 80.0)


def test_modeb_soft_dual_ms_equals_independent_ms():
    L, R = _stereo_sigs(1 << 14)
    M = [(l + r) * 0.5 for l, r in zip(L, R)]
    S = [(l - r) * 0.5 for l, r in zip(L, R)]
    Mo = dsp.modeb_soft(M, 700.0, 2.0, SR, 0.2, 2.0, 80.0)
    So = dsp.modeb_soft(S, 700.0, 2.0, SR, 0.2, 2.0, 80.0)
    Lo, Ro = dsp.modeb_soft_stereo(L, R, 700.0, 2.0, SR, 0.2, 2.0, 80.0, "dual_ms")
    assert Lo == pytest.approx([m + s for m, s in zip(Mo, So)], abs=1e-12)
    assert Ro == pytest.approx([m - s for m, s in zip(Mo, So)], abs=1e-12)


# ---- Phase 3c: Mode B Soft+Hard cascade (two ceilings) ----

def test_cascade_soft_only_equals_modeb_soft():
    w = 2 * math.pi * 1000.0 / SR
    sig = [0.8 * math.sin(w * i) for i in range(1 << 14)]
    a = dsp.modeb_cascade(sig, 1000.0, 2.0, SR, 0.2, 0.4, 2.0, 120.0, 1, 0)
    b = dsp.modeb_soft(sig, 1000.0, 2.0, SR, 0.2, 2.0, 120.0)
    assert a == pytest.approx(b, abs=1e-12)


def test_cascade_hard_only_equals_modeb_brick():
    w = 2 * math.pi * 1000.0 / SR
    sig = [0.8 * math.sin(w * i) for i in range(1 << 14)]
    a = dsp.modeb_cascade(sig, 1000.0, 2.0, SR, 0.2, 0.4, 2.0, 120.0, 0, 1)
    b = dsp.modeb_brick(sig, 1000.0, 2.0, SR, 0.4, 2.0, 120.0)
    assert a == pytest.approx(b, abs=1e-12)


def test_cascade_both_sustained_settles_to_soft_ceiling():
    w = 2 * math.pi * 1000.0 / SR
    sig = [0.8 * math.sin(w * i) for i in range(1 << 15)]
    out = dsp.modeb_cascade(sig, 1000.0, 2.0, SR, 0.2, 0.4, 2.0, 120.0, 1, 1)
    assert _band_contrib_peak(out, 1000.0, 2.0, SR) == pytest.approx(0.2, rel=0.05)


def test_cascade_stereo_dual_ms_equals_independent():
    L, R = _stereo_sigs(1 << 14)
    M = [(l + r) * 0.5 for l, r in zip(L, R)]
    S = [(l - r) * 0.5 for l, r in zip(L, R)]
    Mo = dsp.modeb_cascade(M, 700.0, 2.0, SR, 0.2, 0.4, 2.0, 120.0, 1, 1)
    So = dsp.modeb_cascade(S, 700.0, 2.0, SR, 0.2, 0.4, 2.0, 120.0, 1, 1)
    Lo, Ro = dsp.modeb_cascade_stereo(L, R, 700.0, 2.0, SR, 0.2, 0.4, 2.0, 120.0, 1, 1, "dual_ms")
    assert Lo == pytest.approx([m + s for m, s in zip(Mo, So)], abs=1e-12)
    assert Ro == pytest.approx([m - s for m, s in zip(Mo, So)], abs=1e-12)


# ---- Phase 2c: Mode A Soft+Hard cascade (bell-cut) ----

def test_modea_cascade_soft_only_equals_modea_process():
    w = 2 * math.pi * 1000.0 / SR
    sig = [0.8 * math.sin(w * i) for i in range(1 << 14)]
    a = dsp.modea_cascade(sig, 1000.0, 2.0, SR, 0.2, 0.4, 5.0, 80.0, 1, 0)
    b = dsp.modea_process(sig, 1000.0, 2.0, SR, 0.2, 5.0, 80.0)
    assert a == pytest.approx(b, abs=1e-12)


def test_modea_cascade_both_sustained_near_soft_ceiling():
    w = 2 * math.pi * 1000.0 / SR
    sig = [0.8 * math.sin(w * i) for i in range(1 << 15)]
    out = dsp.modea_cascade(sig, 1000.0, 2.0, SR, 0.2, 0.4, 1.0, 80.0, 1, 1)
    pk = max(abs(v) for v in out[-2000:])
    assert 0.18 <= pk <= 0.26


def test_modea_cascade_stereo_dual_ms_equals_independent():
    L, R = _stereo_sigs(1 << 14)
    M = [(l + r) * 0.5 for l, r in zip(L, R)]
    S = [(l - r) * 0.5 for l, r in zip(L, R)]
    Mo = dsp.modea_cascade(M, 700.0, 2.0, SR, 0.2, 0.4, 5.0, 80.0, 1, 1)
    So = dsp.modea_cascade(S, 700.0, 2.0, SR, 0.2, 0.4, 5.0, 80.0, 1, 1)
    Lo, Ro = dsp.modea_cascade_stereo(L, R, 700.0, 2.0, SR, 0.2, 0.4, 5.0, 80.0, 1, 1, "dual_ms")
    assert Lo == pytest.approx([m + s for m, s in zip(Mo, So)], abs=1e-12)
    assert Ro == pytest.approx([m - s for m, s in zip(Mo, So)], abs=1e-12)


# ---- Phase S-A: Mode A shelf dynamics ----


def test_shelf_cut_coeffs_match_svf_make():
    # Fast per-sample update (no tan) must equal the full recompute to machine zero.
    for st in ("lowshelf", "highshelf"):
        for fc, q in ((6000.0, 0.7071), (200.0, 1.5)):
            g0 = math.tan(math.pi * fc / SR)
            for gdyn in (1.0, 0.7, 0.5, 0.25, 0.1, 2.0 ** -5):
                fast = dsp.shelf_cut_coeffs(st, g0, q, gdyn)
                full = dsp.svf_make(st, fc, q, gdyn, SR)
                ref = (full["a1"], full["a2"], full["a3"], full["k"],
                       full["m0"], full["m1"], full["m2"])
                for a, b in zip(fast, ref):
                    assert abs(a - b) < 1e-15


def test_shelf_cut_coeffs_identity_at_unity_gain():
    # gdyn == 1 must be a bit-exact pass-through filter (m0=1, m1=0, m2=0).
    for st in ("lowshelf", "highshelf"):
        a1, a2, a3, k, m0, m1, m2 = dsp.shelf_cut_coeffs(
            st, math.tan(math.pi * 3000.0 / SR), 0.7071, 1.0)
        assert m0 == 1.0 and m1 == 0.0 and m2 == 0.0


def test_shelf_detector_shape_high():
    # Spec item 1: HP detector at fixed DET_Q — unity passband, 0.7071 at fc,
    # rejects lows, monotonic (no resonant bump).
    det = dsp.svf_make("hp", 6000.0, dsp.DET_Q, 1.0, SR)
    assert dsp.svf_magnitude(det, 1000.0, SR) < 0.05
    assert abs(dsp.svf_magnitude(det, 6000.0, SR) - 0.7071) < 0.01
    assert dsp.svf_magnitude(det, 16000.0, SR) == pytest.approx(1.0, abs=0.02)
    freqs = (500, 1000, 2000, 4000, 6000, 8000, 12000, 16000, 20000)
    vals = [dsp.svf_magnitude(det, f, SR) for f in freqs]
    assert max(vals) < 1.02
    assert all(b >= a - 1e-3 for a, b in zip(vals, vals[1:]))


def test_shelf_detector_shape_low():
    # LP mirror: unity toward DC, 0.7071 at fc, rejects highs.
    det = dsp.svf_make("lp", 200.0, dsp.DET_Q, 1.0, SR)
    assert dsp.svf_magnitude(det, 20.0, SR) == pytest.approx(1.0, abs=0.02)
    assert abs(dsp.svf_magnitude(det, 200.0, SR) - 0.7071) < 0.01
    assert dsp.svf_magnitude(det, 5000.0, SR) < 0.01


def _tone_amp(sig, freq, i0, i1):
    """Amplitude of the `freq` component over window [i0, i1) by correlation."""
    c = s = 0.0
    for i in range(i0, i1):
        w = 2.0 * math.pi * freq * i / SR
        c += sig[i] * math.cos(w)
        s += sig[i] * math.sin(w)
    return 2.0 * math.hypot(c, s) / (i1 - i0)


def test_shelf_cascade_both_stages_off_is_identity():
    # Spec item 3 (equivalence): dynamics fully off -> the cut stage is exact
    # identity, so band output == static shelf output (the cascade models only
    # the post-static cut stage, like modea_cascade).
    sig = [math.sin(0.31 * i) + 0.5 * math.sin(2.7 * i + 1.0) for i in range(2000)]
    for st in ("lowshelf", "highshelf"):
        out = dsp.shelf_cascade(sig, st, 3000.0, 0.7071, SR, 0.25, 0.5,
                                1.0, 80.0, False, False)
        for a, b in zip(out, sig):
            assert abs(a - b) < 1e-12


def test_highshelf_deesser_burst():
    # Spec item 7: 8 kHz burst on a 1 kHz tone; high-shelf band at 6 kHz,
    # Soft only, ceiling 0.25 (2 bits down). Burst ducks toward ceiling;
    # tone unaffected during AND after (full release).
    n = SR
    b0, b1 = int(0.3 * SR), int(0.7 * SR)
    x = []
    for i in range(n):
        v = 0.2 * math.sin(2.0 * math.pi * 1000.0 * i / SR)
        if b0 <= i < b1:
            v += 0.8 * math.sin(2.0 * math.pi * 8000.0 * i / SR)
        x.append(v)
    y = dsp.shelf_cascade(x, "highshelf", 6000.0, 0.7071, SR, 0.25, 0.5,
                          0.5, 60.0, True, False)
    w0, w1 = int(0.5 * SR), int(0.65 * SR)      # steady mid-burst
    red_db = 20.0 * math.log10(_tone_amp(y, 8000.0, w0, w1) /
                               _tone_amp(x, 8000.0, w0, w1))
    q0, q1 = int(0.05 * SR), int(0.25 * SR)     # pre-burst
    tone_db = 20.0 * math.log10(_tone_amp(y, 1000.0, q0, q1) /
                                _tone_amp(x, 1000.0, q0, q1))
    r0, r1 = int(0.9 * SR), int(0.99 * SR)      # post-burst (released)
    rel_db = 20.0 * math.log10(_tone_amp(y, 1000.0, r0, r1) /
                               _tone_amp(x, 1000.0, r0, r1))
    # Measured -6.272 dB at these exact parameters. Two-sided band: catches
    # both "not de-essing" (> -4.5) and "over-killing" (< -9.0) without
    # locking one exact release trajectory forever.
    assert -9.0 < red_db < -4.5
    assert abs(tone_db) < 0.1
    assert abs(rel_db) < 0.1


def test_shelf_cascade_stereo_linked_identical_channels():
    # Linked Both-placement on identical channels must give identical output
    # and equal the single-channel result.
    sig = [0.6 * math.sin(2.0 * math.pi * 9000.0 * i / SR) for i in range(4800)]
    L, R = dsp.shelf_cascade_stereo(sig, sig, "highshelf", 6000.0, 0.7071, SR,
                                    0.25, 0.5, 0.5, 60.0, True, False, "linked")
    mono = dsp.shelf_cascade(sig, "highshelf", 6000.0, 0.7071, SR,
                             0.25, 0.5, 0.5, 60.0, True, False)
    for a, b, m in zip(L, R, mono):
        assert a == b
        assert abs(a - m) < 1e-12


def test_lowshelf_mirror_tames_low_burst():
    # Spec item 6 (mirror symmetry): 60 Hz burst on a 5 kHz tone; low-shelf
    # band at 200 Hz, Soft only, ceiling 0.25. Burst ducked, tone untouched.
    n = SR
    b0, b1 = int(0.3 * SR), int(0.7 * SR)
    x = []
    for i in range(n):
        v = 0.2 * math.sin(2.0 * math.pi * 5000.0 * i / SR)
        if b0 <= i < b1:
            v += 0.8 * math.sin(2.0 * math.pi * 60.0 * i / SR)
        x.append(v)
    y = dsp.shelf_cascade(x, "lowshelf", 200.0, 0.7071, SR, 0.25, 0.5,
                          0.5, 60.0, True, False)
    w0, w1 = int(0.5 * SR), int(0.65 * SR)
    red_db = 20.0 * math.log10(_tone_amp(y, 60.0, w0, w1) /
                               _tone_amp(x, 60.0, w0, w1))
    q0, q1 = int(0.05 * SR), int(0.25 * SR)
    tone_db = 20.0 * math.log10(_tone_amp(y, 5000.0, q0, q1) /
                                _tone_amp(x, 5000.0, q0, q1))
    r0, r1 = int(0.9 * SR), int(0.99 * SR)
    rel_db = 20.0 * math.log10(_tone_amp(y, 5000.0, r0, r1) /
                               _tone_amp(x, 5000.0, r0, r1))
    assert red_db < -6.0
    assert abs(tone_db) < 0.1
    assert abs(rel_db) < 0.1


def test_lowshelf_detector_reacts_to_dc():
    # Spec item 8: the LP detector is unity at DC by design (rumble/boom tamer);
    # a DC offset above the ceiling gets pulled toward it. Documents the kept
    # behaviour of spec section 2.
    n = SR
    x = [0.5] * n
    y = dsp.shelf_cascade(x, "lowshelf", 100.0, 0.7071, SR, 0.25, 0.125,
                          1.0, 80.0, True, False)
    tail = y[-4800:]
    m = sum(tail) / len(tail)
    assert 0.20 < m < 0.32   # 0.5 * gdyn -> ~0.25 (ceiling), not 0.5


def _jsfx_v02_text():
    import pathlib
    p = pathlib.Path(__file__).resolve().parents[1] / "JSFX" / "RCBitNova V0.2"
    return p.read_bytes()


def test_jsfx_v02_is_pure_ascii():
    # REAPER's ascii codec crashed on an em-dash before (see reels_tempo_map);
    # keep the V0.2 source byte-pure.
    data = _jsfx_v02_text()
    bad = [i for i, b in enumerate(data) if b >= 128]
    assert not bad, f"non-ASCII bytes at offsets {bad[:5]} in RCBitNova V0.2"


def test_jsfx_v02_modeb_gates_enable_shelf():
    # Phase S-B: BOTH Mode B gates (@slider any_b/PDC and the @sample Mode B pass)
    # must include shelf types via the `<= 2` predicate (Bell 0, Low Shelf 1, High
    # Shelf 2; HP=3/LP=4 stay static). Exactly two occurrences; if you change this
    # you are altering the Mode B gating and must update this test in the SAME commit.
    text = _jsfx_v02_text().decode("ascii")
    gate = "mbmode[b] == 1 && slider(10*(b+1)+2) <= 2"
    assert text.count(gate) == 2, (
        "Mode B shelf-enabled gate expected exactly twice (any_b + sample pass); "
        "flipping only one gate creates PDC-without-processing or the reverse")
    # the old Bell-only predicate must be fully gone (no half-flip left behind)
    assert "mbmode[b] == 1 && slider(10*(b+1)+2) == 0" not in text


# ---- Phase S-B: Mode B shelf split limiter ----

def _shelf_branch(x, shelf_type, fc, sr):
    """The exact split branch the plugin extracts: HP tap for high shelf, LP tap
    for low shelf, via the fixed-DET_Q detector SVF (same series as the plugin)."""
    ft = "hp" if shelf_type == "highshelf" else "lp"
    return dsp.svf_process(dsp.svf_make(ft, fc, dsp.DET_Q, 1.0, sr), x)


def test_shelf_modeb_transparent_below_ceiling_is_exact_identity():
    # Spec 6.2 perfect-reconstruction + Mode B idle: with the ceiling far above the
    # signal the limiter never engages, so the summed output == input delayed by the
    # lookahead, to machine precision (proto: max err 5.551e-17).
    sig = [0.3*math.sin(0.21*i) + 0.2*math.sin(1.7*i + 0.5) for i in range(4000)]
    L = max(1, int(2.0*0.001*SR + 0.5))
    for st in ("lowshelf", "highshelf"):
        out = dsp.shelf_modeb_cascade(sig, st, 3000.0, 0.7071, SR, 0.9, 0.95,
                                      2.0, 80.0, True, True)
        for n in range(L, len(sig)):
            assert abs(out[n] - sig[n - L]) < 2e-16


def test_shelf_modeb_both_stages_off_is_pure_delay():
    # Spec 6.4: Mode B with both stages off contributes zero correction -> output is
    # the input delayed by the lookahead (proto: 5.551e-17).
    sig = [0.5*math.sin(0.3*i) for i in range(3000)]
    L = max(1, int(2.0*0.001*SR + 0.5))
    for st in ("lowshelf", "highshelf"):
        out = dsp.shelf_modeb_cascade(sig, st, 2500.0, 0.7071, SR, 0.25, 0.5,
                                      2.0, 80.0, False, False)
        for n in range(L, len(sig)):
            assert abs(out[n] - sig[n - L]) < 1e-15


def test_shelf_modeb_highshelf_clamps_branch_at_ceiling():
    # Spec 4 honest guarantee + 6.7 (Mode B de-esser): the extracted HIGH-SHELF
    # region contribution is brick-clamped bit-exactly to the hard ceiling. Recover
    # the clamped branch from output vs delayed input plus an independent HP
    # extraction of the input (proto: recovered peak 0.249999 at ceiling 0.25, from
    # a raw branch peak of 0.6417 -> it genuinely engaged).
    w = 2*math.pi*8000.0/SR
    x = [0.8*math.sin(w*i) for i in range(1 << 15)]
    cH = 0.25
    y = dsp.shelf_modeb_cascade(x, "highshelf", 6000.0, 0.7071, SR, cH, cH,
                                2.0, 80.0, False, True)   # hard only
    L = max(1, int(2.0*0.001*SR + 0.5))
    branch = _shelf_branch(x, "highshelf", 6000.0, SR)
    clamped = [branch[n - L] + (y[n] - x[n - L]) for n in range(L, len(x))]
    assert max(abs(v) for v in clamped[-4000:]) <= cH * 1.001        # clamped to ceiling
    assert max(abs(v) for v in branch[-4000:]) > cH * 2.0            # and it engaged


def test_shelf_modeb_lowshelf_clamps_branch_at_ceiling():
    # Spec 6.6 mirror symmetry (Mode B): the extracted LOW-SHELF region contribution
    # is brick-clamped bit-exactly to the ceiling (proto: recovered peak 0.250000 at
    # ceiling 0.25, from a raw branch peak of 0.7968).
    w = 2*math.pi*60.0/SR
    x = [0.8*math.sin(w*i) for i in range(1 << 16)]
    cH = 0.25
    y = dsp.shelf_modeb_cascade(x, "lowshelf", 200.0, 0.7071, SR, cH, cH,
                                2.0, 200.0, False, True)
    L = max(1, int(2.0*0.001*SR + 0.5))
    branch = _shelf_branch(x, "lowshelf", 200.0, SR)
    clamped = [branch[n - L] + (y[n] - x[n - L]) for n in range(L, len(x))]
    assert max(abs(v) for v in clamped[-4000:]) <= cH * 1.001
    assert max(abs(v) for v in branch[-4000:]) > cH * 2.0


def test_shelf_modeb_dual_lr_equals_independent():
    L, R = _stereo_sigs(1 << 14)
    Lo, Ro = dsp.shelf_modeb_cascade_stereo(L, R, "highshelf", 6000.0, 0.7071, SR,
                                            0.2, 0.4, 2.0, 120.0, 1, 1, "dual_lr")
    assert Lo == dsp.shelf_modeb_cascade(L, "highshelf", 6000.0, 0.7071, SR,
                                         0.2, 0.4, 2.0, 120.0, 1, 1)
    assert Ro == dsp.shelf_modeb_cascade(R, "highshelf", 6000.0, 0.7071, SR,
                                         0.2, 0.4, 2.0, 120.0, 1, 1)


def test_shelf_modeb_dual_ms_equals_independent_ms():
    L, R = _stereo_sigs(1 << 14)
    M = [(l + r) * 0.5 for l, r in zip(L, R)]
    S = [(l - r) * 0.5 for l, r in zip(L, R)]
    Mo = dsp.shelf_modeb_cascade(M, "highshelf", 6000.0, 0.7071, SR, 0.2, 0.4, 2.0, 120.0, 1, 1)
    So = dsp.shelf_modeb_cascade(S, "highshelf", 6000.0, 0.7071, SR, 0.2, 0.4, 2.0, 120.0, 1, 1)
    Lo, Ro = dsp.shelf_modeb_cascade_stereo(L, R, "highshelf", 6000.0, 0.7071, SR,
                                            0.2, 0.4, 2.0, 120.0, 1, 1, "dual_ms")
    assert Lo == pytest.approx([m + s for m, s in zip(Mo, So)], abs=1e-12)
    assert Ro == pytest.approx([m - s for m, s in zip(Mo, So)], abs=1e-12)


def test_shelf_modeb_linked_identical_channels():
    w = 2 * math.pi * 8000.0 / SR
    mono = [0.8 * math.sin(w * i) for i in range(1 << 14)]
    Lo, Ro = dsp.shelf_modeb_cascade_stereo(mono, list(mono), "highshelf", 6000.0,
                                            0.7071, SR, 0.2, 0.4, 2.0, 120.0, 1, 1, "linked")
    assert Lo == pytest.approx(Ro, abs=1e-12)


def test_shelf_modea_dual_lr_equals_independent():
    # Closes the S-A final-review open Minor: Mode A shelf dual_lr had no direct test.
    L, R = _stereo_sigs(1 << 13)
    Lo, Ro = dsp.shelf_cascade_stereo(L, R, "highshelf", 6000.0, 0.7071, SR,
                                      0.25, 0.5, 0.5, 60.0, True, False, "dual_lr")
    assert Lo == dsp.shelf_cascade(L, "highshelf", 6000.0, 0.7071, SR,
                                   0.25, 0.5, 0.5, 60.0, True, False)
    assert Ro == dsp.shelf_cascade(R, "highshelf", 6000.0, 0.7071, SR,
                                   0.25, 0.5, 0.5, 60.0, True, False)


def test_shelf_modea_dual_ms_equals_independent_ms():
    # Closes the S-A final-review open Minor: Mode A shelf dual_ms had no direct test.
    L, R = _stereo_sigs(1 << 13)
    M = [(l + r) * 0.5 for l, r in zip(L, R)]
    S = [(l - r) * 0.5 for l, r in zip(L, R)]
    Mo = dsp.shelf_cascade(M, "highshelf", 6000.0, 0.7071, SR, 0.25, 0.5, 0.5, 60.0, True, False)
    So = dsp.shelf_cascade(S, "highshelf", 6000.0, 0.7071, SR, 0.25, 0.5, 0.5, 60.0, True, False)
    Lo, Ro = dsp.shelf_cascade_stereo(L, R, "highshelf", 6000.0, 0.7071, SR,
                                      0.25, 0.5, 0.5, 60.0, True, False, "dual_ms")
    assert Lo == pytest.approx([m + s for m, s in zip(Mo, So)], abs=1e-12)
    assert Ro == pytest.approx([m - s for m, s in zip(Mo, So)], abs=1e-12)


# ---- Phase V0.3: Proportional-Q law ----

def _octave_bw(fc, q, glin, sr, level_db):
    """Half-gain octave width: distance between the two freqs where |H|_dB == level_db,
    using the exact analytic svf_response (not a sine-probe)."""
    c = dsp.svf_make("bell", fc, q, glin, sr)
    def mdb(f):
        return 20.0 * math.log10(dsp.svf_response(c, f, sr))
    def find(lo, hi):
        for _ in range(60):
            mid = math.sqrt(lo * hi)
            if (mdb(mid) > level_db) == (mdb(lo) > level_db):
                lo = mid
            else:
                hi = mid
        return math.sqrt(lo * hi)
    return math.log2(find(fc, sr / 2.0 - 1.0) / find(1.0, fc))


def test_qeff_s0_is_bit_identical_bell_coeffs():
    # s = 0 -> q_eff == q_knob exactly -> bell coefficient tuple identical to V0.2.
    for qk in (0.5, 0.707, 2.0, 7.0):
        for bits in (-16.0, -6.0, 0.0, 3.0, 16.0):
            glin = 2.0 ** bits
            qe = dsp.q_eff("bell", qk, 0.0, bits)
            assert qe == qk
            assert dsp.svf_make("bell", 1000.0, qe, glin, SR) == \
                   dsp.svf_make("bell", 1000.0, qk, glin, SR)
            # detector (bandpass) tuple identical too (the Mode A/B bell detector site)
            assert dsp.svf_make("bandpass", 1000.0, qe, 1.0, SR) == \
                   dsp.svf_make("bandpass", 1000.0, qk, 1.0, SR)


def test_qeff_bitratio_and_symmetry():
    assert dsp.q_eff("bell", 2.0, 1.0, 0.0) == 2.0            # gain_bits_eff 0 -> no-op
    # BitRatio 0 gives gain_bits_eff 0 regardless of Macro/Micro
    assert dsp.q_eff("bell", 2.0, 1.0, (16 + 100 * 0.01) * 0.0) == 2.0
    # (Macro 2, BitRatio 0.5) == (Macro 1, BitRatio 1): both gain_bits_eff = 1.0
    assert dsp.q_eff("bell", 2.0, 0.7, 2 * 0.5) == dsp.q_eff("bell", 2.0, 0.7, 1 * 1.0)
    # symmetric in sign (boost vs cut)
    assert dsp.q_eff("bell", 2.0, 0.7, 3.0) == dsp.q_eff("bell", 2.0, 0.7, -3.0)


def test_qeff_non_bell_untouched():
    for ft in ("lowshelf", "highshelf", "hp", "lp"):
        for s in (0.0, 0.5, 1.0):
            assert dsp.q_eff(ft, 0.9, s, 12.0) == 0.9


def test_qeff_clamp_worst_case():
    # true worst case: Macro 16, Micro 100, BitRatio 3 -> gain_bits_eff 51
    gbits = (16 + 100 * 0.01) * 3
    assert dsp.q_eff("bell", 10.0, 1.0, gbits) == 16.0
    # a Q_MAX bell stays finite/bounded (no self-oscillation blow-up)
    c = dsp.svf_make("bell", 12000.0, 16.0, 2.0 ** 8, SR)
    out = dsp.svf_process(c, [1.0] + [0.0] * 20000)
    assert all(math.isfinite(v) for v in out)
    assert max(abs(v) for v in out) < 3.0


def test_qeff_proportional_narrowing_monotonic():
    # s = 0 holds constant width; s > 0 narrows monotonically as gain grows.
    fc = 1000.0
    w0 = [_octave_bw(fc, dsp.q_eff("bell", 1.0, 0.0, b), 2.0 ** b, SR, b * 6.0206 / 2.0)
          for b in (0.5, 1.0, 2.0)]
    assert abs(w0[0] - w0[1]) < 1e-6 and abs(w0[1] - w0[2]) < 1e-6   # constant (bisection resolves ~2e-9)
    w1 = [_octave_bw(fc, dsp.q_eff("bell", 1.0, 1.0, b), 2.0 ** b, SR, b * 6.0206 / 2.0)
          for b in (0.5, 1.0, 2.0)]
    assert w1[0] > w1[1] > w1[2]                                     # narrows
    # measured values from the prototype (loose bands, not a locked trajectory)
    assert 0.90 < w1[0] < 0.98 and 0.68 < w1[1] < 0.74 and 0.45 < w1[2] < 0.50


def test_svf_response_matches_probe():
    # the analytic magnitude equals the sine-probe (exact at fc)
    c = dsp.svf_make("bell", 1000.0, 2.0, 4.0, SR)
    assert abs(dsp.svf_response(c, 1000.0, SR) - dsp.svf_magnitude(c, 1000.0, SR)) < 1e-9
    assert abs(dsp.svf_response(c, 1000.0, SR) - 4.0) < 1e-9


def _jsfx_v03_text():
    import pathlib
    return (pathlib.Path(__file__).resolve().parents[1] / "JSFX" / "RCBitNova V0.3").read_bytes()


def test_jsfx_v03_is_pure_ascii():
    data = _jsfx_v03_text()
    bad = [i for i, b in enumerate(data) if b >= 128]
    assert not bad, f"non-ASCII bytes at {bad[:5]} in RCBitNova V0.3"


def test_jsfx_v03_qchar_sliders_added_not_renumbered():
    text = _jsfx_v03_text().decode("ascii")
    # the four new Q Character sliders exist, default 0
    for n in (19, 29, 39, 49):
        assert f"slider{n}:0<0,1,0.001>" in text, f"slider{n} Q Character missing/wrong"
    # existing per-band static/dyn/hard slider numbers are untouched (spot-check anchors)
    for n in (11, 14, 17, 41, 48, 51, 58, 91, 121):
        assert f"slider{n}:" in text
    # exactly four new sliders were added vs the V0.2 count
    import pathlib, re
    v2 = (pathlib.Path(__file__).resolve().parents[1] / "JSFX" / "RCBitNova V0.2").read_text()
    n2 = len(re.findall(r"^slider\d+:", v2, re.M))
    n3 = len(re.findall(r"^slider\d+:", text, re.M))
    assert n3 == n2 + 4


def test_jsfx_v03_band_qeff_wired_at_all_three_bell_q_sites():
    # Guard the core "one shared expression, three Bell Q sites" invariant: a future
    # edit that reverts any substitution (e.g. back to slider(s+4)) must fail here,
    # even though the DSP tests would stay green.
    text = _jsfx_v03_text().decode("ascii")
    assert "function band_qeff(b)" in text                                    # defined
    assert "svf_set(b * 8, slider(s+2), slider(s+3), band_qeff(b), glin);" in text  # site 1: static
    assert "? 0.7071 : band_qeff(b);" in text                                 # site 2: detector qd
    assert "bp[b*3+1] = band_qeff(b);" in text                                # site 3: bp store
    assert text.count("band_qeff(b)") == 4                                    # 1 def + 3 calls, no extras


# ---- Phase V0.4: minimum-phase HP/LP cascade section ----

def _hplp_cmag(f, ftype, fc, q, nsec):
    m = dsp.svf_response(dsp.svf_make(ftype, fc, q, 1.0, SR), f, SR)
    m *= dsp.svf_response(dsp.svf_make(ftype, fc, 0.7071, 1.0, SR), f, SR) ** (nsec - 1)
    return m


def test_hplp_enum_to_sections():
    assert [dsp.hplp_sections(e) for e in range(6)] == [0, 1, 2, 3, 4, 8]


def test_hplp_slope_db_per_oct():
    fc = 100.0
    for nsec in (1, 2, 3, 4, 8):
        s = abs(20*math.log10(_hplp_cmag(fc/4, "hp", fc, 0.7071, nsec))
                - 20*math.log10(_hplp_cmag(fc/8, "hp", fc, 0.7071, nsec)))
        assert abs(s - nsec*12) < 0.5, (nsec, s)


def test_hplp_fc_level_is_minus_3N():
    fc = 100.0
    for nsec in (1, 2, 3, 4, 8):
        assert abs(20*math.log10(_hplp_cmag(fc, "hp", fc, 0.7071, nsec)) - (-3.0103*nsec)) < 0.1


def test_hplp_passband_droop_high_slope():
    fc = 100.0
    assert -2.3 < 20*math.log10(_hplp_cmag(fc*2, "hp", fc, 0.7071, 8)) < -1.9


def test_hplp_resonance_bump():
    fc = 100.0
    def peak(q):
        return max(20*math.log10(_hplp_cmag(fc*(1+i*0.01), "hp", fc, q, 4)) for i in range(80))
    assert peak(2.0) > peak(0.7071) + 2.0


def test_hplp_q10_stability():
    sweep = [math.sin(2*math.pi*(50 + i*0.5)*i/SR) for i in range(20000)]
    for ftype, fc in (("hp", 200.0), ("lp", 8000.0)):
        for nsec in (1, 2, 3, 4, 8):
            out = dsp.hplp_cascade(sweep, ftype, fc, 10.0, SR, nsec)
            assert all(math.isfinite(v) for v in out) and max(abs(v) for v in out) < 100.0


def test_hplp_off_is_identity():
    x = [0.5*math.sin(0.3*i) for i in range(500)]
    assert dsp.hplp_cascade(x, "hp", 100.0, 0.7071, SR, 0) == x
    Lo, Ro = dsp.process_hplp_stereo(x, list(x), "hp", 100.0, 0.7071, SR, 0, "both")
    assert Lo == x and Ro == x


def test_hplp_placement_side_leaves_mono_and_mid():
    mono = [0.5*math.sin(0.25*i) for i in range(400)]
    Lo, Ro = dsp.process_hplp_stereo(mono, mono, "hp", 200.0, 0.7071, SR, 4, "side")
    assert all(abs(a-b) < 1e-12 for a, b in zip(Lo, mono))
    assert all(abs(a-b) < 1e-12 for a, b in zip(Ro, mono))
    L = [0.4*math.sin(0.2*i)+0.1 for i in range(400)]
    R = [0.4*math.sin(0.2*i)-0.1 for i in range(400)]
    Lo, Ro = dsp.process_hplp_stereo(L, R, "hp", 200.0, 0.7071, SR, 4, "side")
    mid_in = [(l+r)*0.5 for l, r in zip(L, R)]
    mid_out = [(a+b)*0.5 for a, b in zip(Lo, Ro)]
    assert all(abs(a-b) < 1e-12 for a, b in zip(mid_out, mid_in))


def test_hplp_12db_equals_existing_single_svf():
    x = [0.5*math.sin(0.3*i) for i in range(500)]
    one = dsp.hplp_cascade(x, "hp", 300.0, 2.0, SR, 1)
    ref = dsp.svf_process(dsp.svf_make("hp", 300.0, 2.0, 1.0, SR), x)
    assert one == ref
    # placement routing continuity: 1-section Both == filter each channel independently
    Lo, Ro = dsp.process_hplp_stereo(x, list(x), "hp", 300.0, 2.0, SR, 1, "both")
    assert Lo == ref and Ro == ref


def test_hplp_cascade_per_section_q_is_locked():
    # Locks "section 0 = user Q, sections 1.. = Butterworth 0.7071" in the time domain
    # (nsec>=2, non-default Q). A bug applying user Q to every section, or Butterworth to
    # all, would otherwise pass every other test.
    x = [0.5*math.sin(0.3*i) for i in range(500)]
    got = dsp.hplp_cascade(x, "hp", 300.0, 2.0, SR, 2)          # sec0 Q=2, sec1 Butterworth
    mid = dsp.svf_process(dsp.svf_make("hp", 300.0, 2.0, 1.0, SR), x)
    ref = dsp.svf_process(dsp.svf_make("hp", 300.0, 0.7071, 1.0, SR), mid)
    assert got == ref


def _jsfx_v04_text():
    import pathlib
    return (pathlib.Path(__file__).resolve().parents[1] / "JSFX" / "RCBitNova V0.4").read_bytes()


def test_jsfx_v04_is_pure_ascii():
    data = _jsfx_v04_text()
    bad = [i for i, b in enumerate(data) if b >= 128]
    assert not bad, f"non-ASCII bytes at {bad[:5]} in RCBitNova V0.4"


def test_jsfx_v04_hplp_sliders_and_wiring():
    text = _jsfx_v04_text().decode("ascii")
    for n, frag in ((131, "HP Slope"), (132, "HP Freq"), (133, "HP Q"), (134, "HP Placement"),
                    (135, "LP Slope"), (136, "LP Freq"), (137, "LP Q"), (138, "LP Placement")):
        assert f"slider{n}:" in text and frag in text, f"slider{n} {frag} missing"
    # section helpers and the @sample calls exist
    assert "function hplp_coef(" in text
    assert "function hplp_run(" in text
    assert "hplp_run(0," in text and "hplp_run(1," in text     # HP and LP invoked
    # enum->sections mapping present (the 96 -> 8 trap)
    assert "== 5 ? 8" in text
    # existing V0.3 slider numbers unchanged (spot-check)
    for n in (14, 19, 48, 91, 123):
        assert f"slider{n}:" in text
    import pathlib, re
    v3 = (pathlib.Path(__file__).resolve().parents[1] / "JSFX" / "RCBitNova V0.3").read_text()
    assert len(re.findall(r"^slider\d+:", text, re.M)) == len(re.findall(r"^slider\d+:", v3, re.M)) + 8


# ---- Phase V0.5: staggered-Butterworth HP/LP + decoupled resonance ----

def _v05_cmag(f, ftype, fc, resonance, nsec):
    fe = dsp.fc_eff(fc, SR)
    m = 1.0
    for k in range(nsec):
        m *= dsp.svf_response(dsp.svf_make(ftype, fe, dsp.butter_q(k, nsec), 1.0, SR), f, SR)
    m *= dsp.svf_response(dsp.svf_make("bell", fe, 2.0, dsp.res_glin(resonance), SR), f, SR)
    return m


def test_v05_butter_flat_at_fc():
    for ft, fc in (("hp", 380.0), ("lp", 6000.0)):
        for n in (1, 2, 3, 4, 8):
            assert abs(20*math.log10(_v05_cmag(fc, ft, fc, 0.0, n)) - (-3.0103)) < 0.05, (ft, n)


def test_v05_slope_db_per_oct():
    # probe INSIDE the stopband and well below Nyquist (both probes < srate/2). HP probes
    # below fc (fc/8, fc/4); LP probes above fc (2*fc, 4*fc) with a low fc so 4*fc stays
    # far below Nyquist. (Measured worst error: HP 0.33, LP 0.54 dB/oct at SR=48000.)
    for ft, fc, f1, f2 in (("hp", 380.0, 380.0/8, 380.0/4), ("lp", 300.0, 1200.0, 600.0)):
        for n in (1, 2, 3, 4, 8):
            s = abs(20*math.log10(_v05_cmag(f1, ft, fc, 0.0, n))
                    - 20*math.log10(_v05_cmag(f2, ft, fc, 0.0, n))) / abs(math.log2(f2/f1))
            assert abs(s - n*12) < 0.8, (ft, n, s)


def test_v05_resonance_peak_height():
    for ft, fc in (("hp", 380.0), ("lp", 6000.0)):
        for n in (1, 8):
            def peak(r):
                return max(20*math.log10(_v05_cmag(fc*(1+i*0.005) if ft == "hp" else fc*(1-i*0.005),
                                                   ft, fc, r, n)) for i in range(200))
            assert peak(0.0) <= 0.1
            assert 7.0 < peak(0.5) < 10.5
            assert 12.0 < peak(1.0) < 15.0


def test_v05_no_dip_single_peak():
    for ft, fc in (("hp", 380.0), ("lp", 6000.0)):
        frs = [1 + i*0.02 for i in range(40)] if ft == "hp" else [1 - i*0.02 for i in range(40)]
        vals = [20*math.log10(_v05_cmag(fc*fr, ft, fc, 1.0, 8)) for fr in frs]
        minima = sum(1 for i in range(1, len(vals)-1)
                     if vals[i] < vals[i-1]-0.03 and vals[i] < vals[i+1]-0.03)
        assert minima == 0, (ft, minima)


def test_v05_resonance0_is_pure_cascade():
    x = [0.5*math.sin(0.3*i) for i in range(400)]
    got = dsp.hplp_butter_cascade(x, "hp", 380.0, 0.0, SR, 4)
    fe = dsp.fc_eff(380.0, SR)
    ref = x
    for k in range(4):
        ref = dsp.svf_process(dsp.svf_make("hp", fe, dsp.butter_q(k, 4), 1.0, SR), ref)
    assert got == ref   # bell at glin=1 is exact identity


def test_v05_always_tick_stable_no_runaway():
    # Always-tick bell: a 1 -> 0 -> 1 Resonance sweep through ONE persistent cascade stays
    # FINITE and BOUNDED (no burst / runaway / NaN). The always-tick keeps the bell state
    # current, so re-enabling Resonance does not cold-start. (An INSTANT glin step is a
    # coefficient change and produces a bounded step like any IIR param jump; smoothness of
    # instant jumps is NOT asserted - Resonance is a continuous automatable control per spec.)
    sig = [0.5*math.sin(0.05*i) + 0.3*math.sin(0.31*i) for i in range(1500)]
    out = []
    fe = dsp.fc_eff(380.0, SR)
    state = [[0.0, 0.0] for _ in range(9)]  # 8 sections + always-tick bell
    for i, v0 in enumerate(sig):
        r = 1.0 if i < 500 else (0.0 if i < 1000 else 1.0)
        coefs = [dsp.svf_make("hp", fe, dsp.butter_q(k, 8), 1.0, SR) for k in range(8)]
        coefs.append(dsp.svf_make("bell", fe, 2.0, dsp.res_glin(r), SR))
        s = v0
        for st in range(9):
            c = coefs[st]; ic1, ic2 = state[st]
            v3 = s - ic2; v1 = c["a1"]*ic1 + c["a2"]*v3; v2 = ic2 + c["a2"]*ic1 + c["a3"]*v3
            state[st][0] = 2*v1 - ic1; state[st][1] = 2*v2 - ic2
            s = c["m0"]*s + c["m1"]*v1 + c["m2"]*v2
        out.append(s)
    assert all(math.isfinite(v) for v in out)
    assert max(abs(v) for v in out) < 50.0   # bounded, no runaway (typical peak is ~1-2)


def test_v05_stability_across_sr_slope_fc():
    for sr in (44100.0, 48000.0, 96000.0, 192000.0):
        sweep = [math.sin(2*math.pi*(30 + i*0.4)*i/sr) for i in range(12000)]
        for ft in ("hp", "lp"):
            for fc in (20.0, 20000.0):
                for n in (1, 4, 8):
                    o = dsp.hplp_butter_cascade(sweep, ft, fc, 1.0, sr, n)
                    assert all(math.isfinite(v) for v in o) and max(abs(v) for v in o) < 1000.0


def test_v05_type_sanitize():
    assert [dsp.hplp_type_sanitize(t) for t in (-1, 0, 1, 2, 3, 4, 5)] == [0, 0, 1, 2, 0, 0, 0]


def test_v05_fc_eff_clamp():
    assert dsp.fc_eff(20000.0, 44100.0) == 20000.0        # below nyquist*0.49=21609
    assert dsp.fc_eff(20000.0, 32000.0) == 32000.0 * 0.49  # clamped on a low-rate session


def test_v05_off_and_placement():
    x = [0.5*math.sin(0.3*i) for i in range(400)]
    assert dsp.hplp_butter_cascade(x, "hp", 380.0, 1.0, SR, 0) == x   # Off = identity even at r=1
    mono = [0.5*math.sin(0.25*i) for i in range(400)]
    Lo, Ro = dsp.process_hplp_butter_stereo(mono, mono, "hp", 200.0, 0.0, SR, 4, "side")
    assert all(abs(a-b) < 1e-12 for a, b in zip(Lo, mono)) and all(abs(a-b) < 1e-12 for a, b in zip(Ro, mono))
    L = [0.4*math.sin(0.2*i)+0.1 for i in range(400)]; R = [0.4*math.sin(0.2*i)-0.1 for i in range(400)]
    Lo, Ro = dsp.process_hplp_butter_stereo(L, R, "hp", 200.0, 0.0, SR, 4, "side")
    mid_in = [(l+r)*0.5 for l, r in zip(L, R)]; mid_out = [(a+b)*0.5 for a, b in zip(Lo, Ro)]
    assert all(abs(a-b) < 1e-12 for a, b in zip(mid_out, mid_in))


def _jsfx_v05_text():
    import pathlib
    return (pathlib.Path(__file__).resolve().parents[1] / "JSFX" / "RCBitNova V0.5").read_bytes()


def test_jsfx_v05_is_pure_ascii():
    data = _jsfx_v05_text()
    bad = [i for i, b in enumerate(data) if b >= 128]
    assert not bad, f"non-ASCII bytes at {bad[:5]} in RCBitNova V0.5"


def test_jsfx_v05_consolidation_and_resonance():
    text = _jsfx_v05_text().decode("ascii")
    # per-band Type enum reduced to Bell/Low Shelf/High Shelf (max 2), all 4 bands
    for n in (12, 22, 32, 42):
        assert f"slider{n}:0<0,2,1{{Bell,Low Shelf,High Shelf}}>" in text, f"slider{n} Type not consolidated"
    # svf_set no longer has an HP/LP branch (High Pass / Low Pass comment gone from svf_set)
    assert "// High Pass" not in text and "// Low Pass" not in text
    # dedicated-section Q sliders became Resonance 0..1
    assert "slider133:0<0,1,0.001>" in text and "Resonance" in text
    assert "slider137:0<0,1,0.001>" in text
    # new DSP wiring present
    assert "function butter_q(" in text
    assert "function hplp_bell(" in text
    assert "hplp_run(0," in text and "hplp_run(1," in text
    # Type sanitize guard present
    assert "> 2 || " in text or "ty > 2" in text


# ---- Phase V0.6: Hand-written FFT/IFFT + Kaiser window (oracle) ----

def test_lp_fft_ifft_roundtrip():
    x = [complex(math.sin(i), 0.3 * math.cos(2 * i)) for i in range(64)]
    rt = dsp.lp_ifft(dsp.lp_fft(x))
    assert max(abs(a - b) for a, b in zip(x, rt)) < 1e-12


def test_lp_fft_matches_naive_dft_small():
    x = [complex(i % 3 - 1, 0) for i in range(8)]
    got = dsp.lp_fft(x)
    for k in range(8):
        ref = sum(x[n] * cmath.exp(-2j * math.pi * k * n / 8) for n in range(8))
        assert abs(got[k] - ref) < 1e-12


def test_kaiser_window_symmetric_and_peaks_center():
    w = dsp.kaiser_window(256, 14.0)
    assert w[0] < 1e-3 and w[-1] < 1e-3
    assert w[128] == pytest.approx(1.0, abs=2e-4)
    assert all(abs(w[i] - w[255 - i]) < 1e-12 for i in range(256))


# ---- Phase V0.6: Kernel construction + symmetry/delay contract (oracle) ----

def test_hplp_digital_mag_matches_v05_min_phase():
    # digital_mag must equal the realized magnitude of the actual V0.5 cascade+bell
    sr = 48000.0
    for f in [80, 250, 1000, 8000, 18000]:
        # reconstruct the V0.5 realized magnitude independently
        fe = dsp.fc_eff(120.0, sr); m = 1.0
        for k in range(4):
            m *= dsp.svf_response(dsp.svf_make("hp", fe, dsp.butter_q(k, 4), 1.0, sr), f, sr)
        m *= dsp.svf_response(dsp.svf_make("bell", fe, 2.0, dsp.res_glin(0.6), sr), f, sr)
        assert dsp.hplp_digital_mag("hp", 120.0, 0.6, 4, f, sr) == pytest.approx(m, rel=1e-12)

def test_identity_kernel_is_delta_at_BD_over_2():
    BD = 8192
    k = dsp.build_lp_kernel(BD, "hp", 100.0, 0.0, 0, 14.0, 48000.0)  # nsec=0 -> mag==1
    peak = max(range(BD), key=lambda i: abs(k[i]))
    other = max(abs(k[i]) for i in range(BD) if abs(i - BD // 2) > 4)
    assert peak == BD // 2
    assert other < 1e-9

def test_kernel_symmetric_about_BD_over_2():
    BD = 8192; half = BD // 2
    k = dsp.build_lp_kernel(BD, "hp", 120.0, 0.6, 4, 14.0, 48000.0)
    kmax = max(abs(v) for v in k)
    asym = max(abs(k[half + d] - k[half - d]) for d in range(1, half)) / kmax
    assert asym < 1e-6           # window-centering half-sample; NOT exact
    assert dsp.kernel_group_delay(BD) == 4096


# ---- Phase V0.6: Magnitude-parity acceptance tests (oracle verification) ----

def _kmag(k, f, sr):
    """|DTFT(kernel)| at frequency f."""
    w = 2.0 * math.pi * f / sr
    return abs(sum(kn * cmath.exp(-1j * w * n) for n, kn in enumerate(k) if kn != 0.0))

def test_linear_passband_matches_v05_within_0p3_dB():
    sr = 48000.0; BD = 8192
    k = dsp.build_lp_kernel(BD, "hp", 120.0, 0.6, 4, 14.0, sr)      # 48 dB/oct + res
    for f in [300, 500, 1000, 4000, 12000, 20000]:                  # passband (>= 2*fc)
        got = 20 * math.log10(_kmag(k, f, sr) + 1e-30)
        ana = 20 * math.log10(dsp.hplp_digital_mag("hp", 120.0, 0.6, 4, f, sr))
        assert abs(got - ana) < 0.3

def test_linear_stopband_is_attenuated():
    sr = 48000.0; BD = 8192
    k = dsp.build_lp_kernel(BD, "hp", 120.0, 0.6, 4, 14.0, sr)
    for f in [20, 30, 40, 55]:                                      # >= ~1 octave below fc
        assert 20 * math.log10(_kmag(k, f, sr) + 1e-30) < -40.0

def test_lp_kernel_passband_matches_v05():
    sr = 48000.0; BD = 8192
    k = dsp.build_lp_kernel(BD, "lp", 8000.0, 0.0, 4, 14.0, sr)     # LP, no resonance
    for f in [100, 500, 2000, 5000]:                               # passband (<= fc/2 region)
        got = 20 * math.log10(_kmag(k, f, sr) + 1e-30)
        ana = 20 * math.log10(dsp.hplp_digital_mag("lp", 8000.0, 0.0, 4, f, sr))
        assert abs(got - ana) < 0.3

def test_fir_brick_symmetric_and_steep():
    sr = 48000.0; BD = 8192; half = BD // 2
    k = dsp.fir_brick_kernel(BD, "hp", 500.0, 14.0, sr)
    kmax = max(abs(v) for v in k)
    assert max(abs(k[half + d] - k[half - d]) for d in range(1, half)) / kmax < 1e-6
    # passband well above fc ~ unity, deep stopband an octave below
    assert 20 * math.log10(_kmag(k, 4000.0, sr) + 1e-30) > -0.5
    assert 20 * math.log10(_kmag(k, 125.0, sr) + 1e-30) < -60.0   # 2 octaves below, beta=14

def test_fir_brick_lp_passes_lows():
    sr = 48000.0; BD = 8192
    k = dsp.fir_brick_kernel(BD, "lp", 2000.0, 14.0, sr)
    assert 20 * math.log10(_kmag(k, 200.0, sr) + 1e-30) > -0.5
    assert 20 * math.log10(_kmag(k, 8000.0, sr) + 1e-30) < -60.0


# ---- Phase V0.6: Partitioned overlap-save FFT convolution (oracle) ----

def _direct_conv(sig, ker):
    return [sum(sig[n - m] * ker[m] for m in range(len(ker)) if 0 <= n - m < len(sig))
            for n in range(len(sig))]


def test_partitioned_identity_latency_is_P():
    sig = [float(i) for i in range(80)]
    ker = [0.0] * 16; ker[0] = 1.0
    out = dsp.partitioned_convolve(sig, ker, 16)
    assert all(out[16 + i] == pytest.approx(sig[i], abs=1e-12) for i in range(32))


def test_partitioned_equals_direct():
    sig = [math.sin(0.3 * i) + 0.5 * math.sin(0.02 * i) for i in range(240)]
    ker = [math.sin(0.7 * i) * math.exp(-0.05 * i) for i in range(64)]   # 4 partitions of P=16
    ref = _direct_conv(sig, ker)
    out = dsp.partitioned_convolve(sig, ker, 16)
    P = 16   # partitioned lags direct by the hop P
    err = max(abs(out[n + P] - ref[n]) for n in range(64, 160))
    assert err < 1e-12


# ---- Task 6: Page-safe memory layout helper ----

PAGE = 65536


def test_lp_engine_buffer_inventory():
    bufs = dsp.lp_engine_buffers(8192, 2048)
    names = {n for n, _, _ in bufs}
    assert {"desbuf", "Hspec", "fdlA", "fdlB", "fftw", "yacc", "tmpc"} <= names
    # FFT-touched buffers are flagged
    touched = {n for n, _, t in bufs if t}
    assert {"desbuf", "Hspec", "fftw", "yacc", "tmpc"} <= touched


def test_page_layout_keeps_every_fft_span_in_one_page():
    for base in [0, 12345, 200000, 458752]:      # incl. the tight ~7-page start
        layout = dsp.page_layout(base, 8192, 2048)
        assert dsp.page_layout_ok(layout, 8192, 2048)


def test_two_engines_layouts_are_disjoint_and_page_safe():
    l1 = dsp.page_layout(0, 8192, 2048)
    l2 = dsp.page_layout(l1["__top"], 8192, 2048)
    assert dsp.page_layout_ok(l1, 8192, 2048)
    assert dsp.page_layout_ok(l2, 8192, 2048)
    assert l2["__top"] > l1["__top"]             # second engine strictly above the first


def test_impulse_fft_kernel_matches_analytic_in_passband_and_transition():
    # The JSFX builds the kernel from the FFT of the min-phase impulse response;
    # build_lp_kernel uses the analytic magnitude. They must agree in passband/transition
    # (same true magnitude there) -> this verifies the shipping JSFX method.
    sr = 96000.0; BD = 8192
    ki = dsp.impulse_fft_kernel(BD, "hp", 240.0, 0.6, 2, 14.0, sr)
    ka = dsp.build_lp_kernel(BD, "hp", 240.0, 0.6, 2, 14.0, sr)
    for f in [200, 300, 500, 1000, 4000, 12000, 20000]:
        gi = 20 * math.log10(_kmag(ki, f, sr) + 1e-30)
        ga = 20 * math.log10(_kmag(ka, f, sr) + 1e-30)
        assert abs(gi - ga) < 0.1


def test_linear_phase_lowfreq_resolution_limit_is_method_independent():
    # At very low freq a fixed-length linear-phase FIR (BD=8192, ~11.7 Hz/bin at 96k) cannot
    # resolve a steep sub-cutoff transition, so its deep-stopband rejection is limited. This
    # is INHERENT to linear phase (identical for the analytic and impulse-FFT builds) -- NOT
    # a transcription bug. Documented so future changes stay aware: use Min phase for deep
    # sub-bass low-cut. (res=0 -> proves it is resolution, not resonance-tail truncation.)
    sr = 96000.0; BD = 8192
    ki = dsp.impulse_fft_kernel(BD, "hp", 20.0, 0.0, 8, 14.0, sr)
    ka = dsp.build_lp_kernel(BD, "hp", 20.0, 0.0, 8, 14.0, sr)
    di = 20 * math.log10(_kmag(ki, 13.0, sr) + 1e-30)
    da = 20 * math.log10(_kmag(ka, 13.0, sr) + 1e-30)
    assert abs(di - da) < 3.0                                  # both builds share the same limit
    true_db = 20 * math.log10(dsp.hplp_digital_mag("hp", 20.0, 0.0, 8, 13.0, sr))
    assert true_db < -55.0                                     # the ideal IIR rejects deeply
    assert di > true_db + 20.0                                 # the FIR cannot (resolution-limited)


def test_dry_ring_size_scales_with_BD():
    lo = dict((n, s) for n, s, _ in dsp.lp_engine_buffers(8192, 2048))
    hi = dict((n, s) for n, s, _ in dsp.lp_engine_buffers(32768, 2048))
    assert lo["dryA"] == 16384 and lo["dryB"] == 16384
    assert hi["dryA"] == 32768 and hi["dryB"] == 32768


def test_dry_ring_covers_engine_latency_at_every_resolution():
    # the complementary-dry delay equals the engine latency BD/2 + P; the ring must exceed it
    for BD in (8192, 16384, 32768):
        lat = BD // 2 + 2048
        bufs = dict((n, s) for n, s, _ in dsp.lp_engine_buffers(BD, 2048))
        assert bufs["dryA"] > lat, f"BD={BD}: ring {bufs['dryA']} cannot hold delay {lat}"


def test_used_span_per_resolution():
    span = lambda BD: sum(s for _, s, _ in dsp.lp_engine_buffers(BD, 2048))
    assert span(8192) == 262144
    assert span(16384) == 425984
    assert span(32768) == 786432


def test_packed_normal_pair_matches_v06_footprint():
    l0, l1 = dsp.lp_packed_layouts(0, 8192, 8192, 2048)
    assert l1["__top"] == 524288          # V0.8: added Hspec2
    assert dsp.page_layout_ok(l0, 8192, 2048)
    assert dsp.page_layout_ok(l1, 8192, 2048)


def test_packed_layouts_all_four_combinations():
    expect = {(8192, 8192): 524288, (32768, 8192): 1048576,
              (8192, 32768): 1048576, (32768, 32768): 1572864}
    for (b0, b1), top in expect.items():
        l0, l1 = dsp.lp_packed_layouts(0, b0, b1, 2048)
        assert l1["__top"] == top, f"({b0},{b1}) top {l1['__top']} != {top}"
        assert dsp.page_layout_ok(l0, b0, 2048)
        assert dsp.page_layout_ok(l1, b1, 2048)


def test_hires_desbuf_page_aligned_even_when_engine_base_is_not():
    # A High desbuf spans exactly one 65536 page, so it MUST start on a page boundary or
    # JSFX corrupts it silently. When engine 1 is packed after an engine whose span is not
    # a whole number of pages, the layout has to PUSH desbuf up to the next boundary.
    # (V0.8 spans: Normal 262144 = 4 pages and High 786432 = 12 pages are both already
    # aligned, so the fallback-16384 span 425984 = 6.5 pages is what exercises the push.)
    l0, l1 = dsp.lp_packed_layouts(0, 16384, 32768, 2048)
    base = l0["__top"]
    assert base == 425984 and base % 65536 != 0          # the base really is unaligned
    assert l1["desbuf"] == 458752                        # pushed up to the next page
    assert l1["desbuf"] % 65536 == 0
    assert dsp.page_layout_ok(l1, 32768, 2048)

    # and in the aligned case no padding is wasted
    m0, m1 = dsp.lp_packed_layouts(0, 8192, 32768, 2048)
    assert m1["desbuf"] == m0["__top"] == 262144


# ---- Task 3: Oracle — hi-res benefit via the production builder, sample-rate scope, BD=32768 ----

_HIRES_CACHE = {}


def _hires_kernel(builder_name, *args):
    """Memoised kernel build - BD=32768 kernels are expensive in pure Python."""
    key = (builder_name, args)
    if key not in _HIRES_CACHE:
        _HIRES_CACHE[key] = getattr(dsp, builder_name)(*args)
    return _HIRES_CACHE[key]


def test_hires_deepens_the_lowcut_with_the_production_builder():
    # PRODUCTION path is impulse_fft_kernel (spec §6), not build_lp_kernel.
    sr = 96000.0
    k8 = _hires_kernel("impulse_fft_kernel", 8192, "hp", 20.0, 0.0, 8, 14.0, sr)
    k32 = _hires_kernel("impulse_fft_kernel", 32768, "hp", 20.0, 0.0, 8, 14.0, sr)
    d8 = 20 * math.log10(_kmag(k8, 10.0, sr) + 1e-30)
    d32 = 20 * math.log10(_kmag(k32, 10.0, sr) + 1e-30)
    assert d8 - d32 >= 20.0        # measured ~27 dB deeper at 10 Hz


def test_hires_40hz_lowcut_approaches_the_ideal_iir():
    sr = 96000.0
    k32 = _hires_kernel("impulse_fft_kernel", 32768, "hp", 40.0, 0.0, 4, 14.0, sr)
    got = 20 * math.log10(_kmag(k32, 20.0, sr) + 1e-30)
    ideal = 20 * math.log10(dsp.hplp_digital_mag("hp", 40.0, 0.0, 4, 20.0, sr))
    assert got - ideal < 8.0       # measured 6.0 dB from ideal


def test_hires_benefit_is_smaller_at_192k_scope_documented():
    # The deep-cut claim is scoped to <=96 kHz: the benefit scales with BD/srate.
    sr = 192000.0
    k8 = _hires_kernel("impulse_fft_kernel", 8192, "hp", 20.0, 0.0, 8, 14.0, sr)
    k32 = _hires_kernel("impulse_fft_kernel", 32768, "hp", 20.0, 0.0, 8, 14.0, sr)
    d8 = 20 * math.log10(_kmag(k8, 10.0, sr) + 1e-30)
    d32 = 20 * math.log10(_kmag(k32, 10.0, sr) + 1e-30)
    assert d8 - d32 >= 5.0         # still improves (measured ~10 dB)
    assert d32 > -40.0             # but NOT a deep cut at 192k - this is the scope, not a bug


def test_kernel_contracts_hold_at_BD_32768():
    sr = 96000.0; BD = 32768; half = BD // 2
    k = _hires_kernel("build_lp_kernel", BD, "hp", 120.0, 0.6, 4, 14.0, sr)
    kmax = max(abs(v) for v in k)
    asym = max(abs(k[half + d] - k[half - d]) for d in range(1, half)) / kmax
    assert asym < 1e-6                          # symmetric about BD/2
    assert dsp.kernel_group_delay(BD) == 16384   # integer group delay
    for f in [300, 1000, 12000]:                 # passband parity vs analytic magnitude
        got = 20 * math.log10(_kmag(k, f, sr) + 1e-30)
        ana = 20 * math.log10(dsp.hplp_digital_mag("hp", 120.0, 0.6, 4, f, sr))
        assert abs(got - ana) < 0.3


def test_impulse_fft_equals_analytic_at_BD_32768_in_passband():
    sr = 96000.0
    ki = _hires_kernel("impulse_fft_kernel", 32768, "hp", 240.0, 0.6, 2, 14.0, sr)
    ka = _hires_kernel("build_lp_kernel", 32768, "hp", 240.0, 0.6, 2, 14.0, sr)
    for f in [500, 1000, 4000, 12000]:
        gi = 20 * math.log10(_kmag(ki, f, sr) + 1e-30)
        ga = 20 * math.log10(_kmag(ka, f, sr) + 1e-30)
        assert abs(gi - ga) < 0.1


# ---- Task 4: Oracle — measured runtime latency per configuration ----

def _impulse_peak(kernels, P, BDs, pos=100):
    """Feed a unit impulse at `pos` through the given kernels in series via
    partitioned_convolve and return the output index of the peak."""
    need = pos + sum(BD // 2 + P for BD in BDs) + 4 * P
    sig = [0.0] * need
    sig[pos] = 1.0
    out = sig
    for ker in kernels:
        out = dsp.partitioned_convolve(out, ker, P)
    return max(range(len(out)), key=lambda i: abs(out[i]))


def test_runtime_latency_formula_on_a_small_geometry():
    # Cheap structural check of "kernel BD/2 + hop P" with a scaled-down geometry.
    BD, P = 512, 128
    ker = dsp.build_lp_kernel(BD, "hp", 4000.0, 0.0, 2, 14.0, 96000.0)
    assert _impulse_peak([ker], P, [BD]) == 100 + BD // 2 + P     # 100 + 384


def test_runtime_latency_single_normal_engine_is_6144():
    ker = _hires_kernel("build_lp_kernel", 8192, "hp", 500.0, 0.0, 2, 14.0, 96000.0)
    assert _impulse_peak([ker], 2048, [8192]) == 100 + 6144


def test_runtime_latency_single_high_engine_is_18432():
    ker = _hires_kernel("build_lp_kernel", 32768, "hp", 500.0, 0.0, 2, 14.0, 96000.0)
    assert _impulse_peak([ker], 2048, [32768]) == 100 + 18432


def test_runtime_latency_series_normal_then_high_is_24576():
    k_n = _hires_kernel("build_lp_kernel", 8192, "hp", 500.0, 0.0, 2, 14.0, 96000.0)
    k_h = _hires_kernel("build_lp_kernel", 32768, "lp", 8000.0, 0.0, 2, 14.0, 96000.0)
    assert _impulse_peak([k_n, k_h], 2048, [8192, 32768]) == 100 + 24576


def test_runtime_latency_series_high_then_high_is_36864():
    k_a = _hires_kernel("build_lp_kernel", 32768, "hp", 500.0, 0.0, 2, 14.0, 96000.0)
    k_b = _hires_kernel("build_lp_kernel", 32768, "lp", 8000.0, 0.0, 2, 14.0, 96000.0)
    assert _impulse_peak([k_a, k_b], 2048, [32768, 32768]) == 100 + 36864


# ---- V0.8 Task 1: integrated two-lane reference engine ----

def test_engine_ref_matches_partitioned_convolve_when_idle():
    # With no switch and no skip, each lane must equal the existing reference engine.
    sig = [math.sin(0.3 * i) + 0.5 * math.sin(0.02 * i) for i in range(240)]
    other = [math.cos(0.21 * i) for i in range(240)]
    ker = [math.sin(0.7 * i) * math.exp(-0.05 * i) for i in range(64)]
    r = dsp.lp_engine_ref(sig, other, ker, ker, 16)
    assert r["outA"] == dsp.partitioned_convolve(sig, ker, 16)
    assert r["outB"] == dsp.partitioned_convolve(other, ker, 16)
    assert r["skipped"] == 0 and r["fade_hops"] == 0


def test_engine_ref_instant_swap_is_the_v07_baseline():
    # fade_len = 0 must reproduce a hard kernel swap at the switch hop.
    sig = [math.sin(0.3 * i) for i in range(240)]
    zeros = [0.0] * 240
    ka = [math.sin(0.7 * i) * math.exp(-0.05 * i) for i in range(64)]
    kb = [math.cos(0.4 * i) * math.exp(-0.03 * i) for i in range(64)]
    r = dsp.lp_engine_ref(sig, zeros, ka, kb, 16, switch_hop=5, fade_len=0)
    assert r["fade_hops"] == 0
    # after the swap the engine must behave like one built on kb alone for fresh history
    assert len(r["outA"]) == len(sig)


def test_engine_ref_advances_fdl_wr_once_per_hop():
    sig = [1.0] * (16 * 7)
    ker = [0.0] * 64; ker[0] = 1.0
    r = dsp.lp_engine_ref(sig, sig, ker, ker, 16)
    assert r["state"]["fdl_wr"] == (16 * 7 // 16) % (64 // 16)


# ---- V0.8 Task 2: Oracle — lane-skip tests (bit-exactness, firing, hop phases) ----

def _skip_case(P, ker, zero_run, onset_phase, tail=None):
    """Signal for lane B: `onset_phase` non-zero samples, then `zero_run` exact zeros,
    then a re-excitation tail. Lane A always carries signal."""
    if tail is None:
        tail = [math.sin(0.3 * i) for i in range(4 * P)]
    head = [math.sin(0.11 * i) + 0.3 for i in range(onset_phase)]
    sigB = head + [0.0] * zero_run + tail
    sigA = [math.sin(0.23 * i) for i in range(len(sigB))]
    return sigA, sigB


def test_lane_skip_is_bit_exact_against_the_non_skipping_engine():
    P = 16; BD = 64; B = 2 * P; skip_after = BD + B
    ker = [math.sin(0.7 * i) * math.exp(-0.05 * i) for i in range(BD)]
    sigA, sigB = _skip_case(P, ker, zero_run=skip_after + 3 * P, onset_phase=P + 5)
    ref = dsp.lp_engine_ref(sigA, sigB, ker, ker, P, skip_after=None)
    got = dsp.lp_engine_ref(sigA, sigB, ker, ker, P, skip_after=skip_after)
    assert got["skipped"] > 0                      # the optimisation really fired
    assert got["outB"] == ref["outB"]              # BIT-identical, not approximately equal
    assert got["outA"] == ref["outA"]              # the running lane is untouched
    assert got["state"]["fdl_wr"] == ref["state"]["fdl_wr"]
    assert got["state"]["fdlB"] == ref["state"]["fdlB"]


def test_lane_skip_output_is_exactly_zero_while_skipping():
    P = 16; BD = 64; B = 2 * P; skip_after = BD + B
    ker = [math.sin(0.7 * i) * math.exp(-0.05 * i) for i in range(BD)]
    sigA, sigB = _skip_case(P, ker, zero_run=skip_after + 4 * P, onset_phase=0)
    got = dsp.lp_engine_ref(sigA, sigB, ker, ker, P, skip_after=skip_after)
    # deep inside the zero run (past the FIR tail) the lane output must be exactly 0.0
    probe = skip_after + 2 * P
    assert all(v == 0.0 for v in got["outB"][probe:probe + P])


def test_lane_skip_never_fires_early_and_covers_hop_phases():
    P = 16; BD = 64; B = 2 * P; skip_after = BD + B
    ker = [math.sin(0.7 * i) * math.exp(-0.05 * i) for i in range(BD)]
    for phase in (0, 1, P - 1):
        for run in (skip_after - 1, skip_after, skip_after + P):
            sigA, sigB = _skip_case(P, ker, zero_run=run, onset_phase=phase)
            ref = dsp.lp_engine_ref(sigA, sigB, ker, ker, P, skip_after=None)
            got = dsp.lp_engine_ref(sigA, sigB, ker, ker, P, skip_after=skip_after)
            assert got["outB"] == ref["outB"], f"phase={phase} run={run} diverged"


def test_lane_skip_all_four_run_skip_combinations():
    P = 16; BD = 64; B = 2 * P; skip_after = BD + B
    ker = [math.sin(0.7 * i) * math.exp(-0.05 * i) for i in range(BD)]
    n = skip_after + 6 * P
    live = [math.sin(0.23 * i) for i in range(n)]
    dead = [0.0] * n
    for sigA, sigB in ((live, live), (live, dead), (dead, live), (dead, dead)):
        ref = dsp.lp_engine_ref(sigA, sigB, ker, ker, P, skip_after=None)
        got = dsp.lp_engine_ref(sigA, sigB, ker, ker, P, skip_after=skip_after)
        assert got["outA"] == ref["outA"] and got["outB"] == ref["outB"]


# ---- V0.8 Task 3: Oracle — crossfade tests (artefact killed, exact landing, endpoint ordering) ----

def _curvature_anomaly_db(y, s0, s1, ref_lo, ref_hi, peak):
    """Worst second-difference spike in [s0,s1) above the steady-state baseline, in dB
    relative to peak. A waveform step shows up as a large curvature spike."""
    base = max(abs(y[n + 1] - 2 * y[n] + y[n - 1]) for n in range(ref_lo, ref_hi))
    worst = max(abs(y[n + 1] - 2 * y[n] + y[n - 1]) for n in range(s0, s1))
    return 20 * math.log10(max(worst - base, 1e-14) / peak)


def test_crossfade_removes_the_step_that_an_instant_swap_creates():
    # The measured worst case from the spec: Slope 24 -> 48 dB/oct under audio.
    sr = 96000.0; BD = 8192; P = 2048
    ka = dsp.impulse_fft_kernel(BD, "hp", 100.0, 0.0, 2, 14.0, sr)
    kb = dsp.impulse_fft_kernel(BD, "hp", 100.0, 0.0, 4, 14.0, sr)
    n = P * 22
    sig = [math.sin(2 * math.pi * 60.0 * i / sr) for i in range(n)]   # below cutoff: kernels differ
    zeros = [0.0] * n
    sw = 8
    inst = dsp.lp_engine_ref(sig, zeros, ka, kb, P, switch_hop=sw, fade_len=0)
    fade = dsp.lp_engine_ref(sig, zeros, ka, kb, P, switch_hop=sw, fade_len=int(0.05 * sr))
    s0, s1 = sw * P - P, sw * P + 6 * P
    peak = max(abs(v) for v in inst["outA"][s1:]) or 1e-9
    a_inst = _curvature_anomaly_db(inst["outA"], s0, s1, s1 + P, len(sig) - 1, peak)
    a_fade = _curvature_anomaly_db(fade["outA"], s0, s1, s1 + P, len(sig) - 1, peak)
    assert a_inst > -20.0        # the baseline really is broken (guards a vacuous test)
    assert a_fade < -60.0        # and the crossfade really fixes it
    assert a_fade < a_inst - 30.0


def test_crossfade_steady_state_is_bit_exact():
    # No switch in flight -> byte-identical to the plain engine (Arthur's discipline).
    sig = [math.sin(0.3 * i) + 0.4 * math.sin(0.017 * i) for i in range(240)]
    zeros = [0.0] * 240
    ker = [math.sin(0.7 * i) * math.exp(-0.05 * i) for i in range(64)]
    r = dsp.lp_engine_ref(sig, zeros, ker, ker, 16, switch_hop=None, fade_len=800)
    assert r["outA"] == dsp.partitioned_convolve(sig, ker, 16)
    assert r["fade_hops"] == 0


def test_crossfade_lands_exactly_and_then_stops_fading():
    P = 16; n = P * 30
    sig = [math.sin(0.3 * i) for i in range(n)]
    zeros = [0.0] * n
    ka = [math.sin(0.7 * i) * math.exp(-0.05 * i) for i in range(64)]
    kb = [math.cos(0.4 * i) * math.exp(-0.03 * i) for i in range(64)]
    fade_len = 3 * P
    r = dsp.lp_engine_ref(sig, zeros, ka, kb, P, switch_hop=5, fade_len=fade_len)
    assert r["fade_hops"] == 3          # ceil(fade_len / P) hops carried a fade
    # after the fade, output must match an engine that used kb from the same hop onward
    ref = dsp.lp_engine_ref(sig, zeros, ka, kb, P, switch_hop=5, fade_len=0)
    tail = slice(5 * P + fade_len + 4 * P, n)
    assert r["outA"][tail] == pytest.approx(ref["outA"][tail], abs=1e-9)


def test_crossfade_endpoint_ordering_over_awkward_fade_lengths():
    # fade_len is not a multiple of P in practice (2400 @48k, 2205 @44.1k).
    P = 16; n = P * 30
    sig = [math.sin(0.3 * i) for i in range(n)]
    zeros = [0.0] * n
    ka = [math.sin(0.7 * i) * math.exp(-0.05 * i) for i in range(64)]
    kb = [math.cos(0.4 * i) * math.exp(-0.03 * i) for i in range(64)]
    for fade_len in (P - 1, P, P + 1, 2 * P + 5):
        r = dsp.lp_engine_ref(sig, zeros, ka, kb, P, switch_hop=5, fade_len=fade_len)
        assert r["fade_hops"] == -(-fade_len // P)     # ceil, no off-by-one hop
        assert len(r["outA"]) == n


def test_crossfade_and_skip_coexist():
    # A fade in progress while lane B is skipped: fade still advances, B stays silent,
    # and lane A matches the non-skipping engine bit-for-bit.
    P = 16; BD = 64; B = 2 * P; skip_after = BD + B
    n = skip_after + 10 * P
    sigA = [math.sin(0.23 * i) for i in range(n)]
    sigB = [0.0] * n
    ka = [math.sin(0.7 * i) * math.exp(-0.05 * i) for i in range(BD)]
    kb = [math.cos(0.4 * i) * math.exp(-0.03 * i) for i in range(BD)]
    sw = (skip_after // P) + 2
    ref = dsp.lp_engine_ref(sigA, sigB, ka, kb, P, switch_hop=sw, fade_len=2 * P, skip_after=None)
    got = dsp.lp_engine_ref(sigA, sigB, ka, kb, P, switch_hop=sw, fade_len=2 * P, skip_after=skip_after)
    assert got["skipped"] > 0
    assert got["fade_hops"] == ref["fade_hops"]        # fade advances despite the skip
    assert got["outA"] == ref["outA"]
    assert all(v == 0.0 for v in got["outB"][skip_after + 2 * P:])


# ---- Task 4: Oracle — Hspec2 in the layout (FFT-touched) + memory tests ----

def test_hspec2_exists_and_is_fft_touched():
    bufs = {n: (s, t) for n, s, t in dsp.lp_engine_buffers(8192, 2048)}
    assert "Hspec2" in bufs
    assert bufs["Hspec2"] == bufs["Hspec"]          # same size AND same fft_touched flag
    assert bufs["Hspec2"][1] is True                # it is a live convolve_c operand


def test_v08_spans_and_packed_tops():
    span = lambda BD: sum(s for _, s, _ in dsp.lp_engine_buffers(BD, 2048))
    assert span(8192) == 262144
    assert span(16384) == 425984
    assert span(32768) == 786432
    expect = {(8192, 8192): 524288, (32768, 8192): 1048576,
              (8192, 32768): 1048576, (32768, 32768): 1572864}
    for (b0, b1), top in expect.items():
        l0, l1 = dsp.lp_packed_layouts(0, b0, b1, 2048)
        assert l1["__top"] == top, f"({b0},{b1}) -> {l1['__top']} != {top}"
        assert dsp.page_layout_ok(l0, b0, 2048)
        assert dsp.page_layout_ok(l1, b1, 2048)


def test_every_hspec2_partition_is_page_safe():
    PAGE = 65536
    for BD in (8192, 16384, 32768):
        for base in (0, 262144, 786432):
            L = dsp.page_layout(base, BD, 2048)
            KMAX = BD // 2048; PB2 = 8192
            for kp in range(KMAX):
                s = L["Hspec2"] + kp * PB2
                assert s // PAGE == (s + PB2 - 1) // PAGE, f"BD={BD} base={base} part={kp}"


# ===================== V0.9: topology mute state machine =====================

def _tm(**kw):
    return dsp.TopoMachine(srate=48000, P=2048, **kw)


def test_v09_idle_machine_does_not_touch_the_signal():
    m = _tm()
    for _ in range(1000):
        assert m.sample() is None          # None == the whole block is skipped
    assert m.state == 0 and m.commit_count == 0


def test_v09_slider_arms_but_does_not_apply():
    m = _tm(phase=0)
    m.slider(phase=1, hp_pl=0, lp_pl=0, bd0=8192, bd1=8192)
    assert m.pend == 1 and m.state == 1     # fading out
    assert m.act_phase == 0                 # NOT applied yet
    assert m.commit_count == 0


def test_v09_commit_happens_exactly_when_the_envelope_reaches_zero():
    m = _tm(phase=0)
    m.slider(phase=1, hp_pl=0, lp_pl=0, bd0=8192, bd1=8192)
    fo = int(48000 * 0.005)
    for _ in range(fo - 1):
        g = m.sample()
        assert g > 0.0
        assert m.block() == "", "committed while the output was still audible"
        assert m.act_phase == 0 and m.commit_count == 0
    assert m.sample() == 0.0        # the last fade-out sample lands exactly on zero
    assert m.state == 2 and m.g == 0.0
    assert m.commit_count == 0, "commit must wait for @block, not happen in @sample"
    assert m.block() == "commit"
    assert m.act_phase == 1 and m.commit_count == 1


def test_v09_fade_out_steps_are_all_exactly_one_over_n():
    m = _tm(phase=0)
    m.slider(phase=1, hp_pl=0, lp_pl=0, bd0=8192, bd1=8192)
    fo = int(48000 * 0.005)
    gains = [m.sample() for _ in range(fo)]
    assert gains[-1] == 0.0
    steps = [gains[i - 1] - gains[i] for i in range(1, len(gains))]
    for s in steps:
        assert abs(s - 1.0 / fo) < 1e-12          # every step 1/N, including the last
    assert abs((1.0 - gains[0]) - 1.0 / fo) < 1e-12


def test_v09_fade_in_steps_are_all_exactly_one_over_n_and_land_on_one():
    m = _tm(phase=1, bd0=8192, bd1=8192)
    m.slider(phase=0, hp_pl=0, lp_pl=0, bd0=8192, bd1=8192)   # Linear->Min: hold 0 samples
    fo = int(48000 * 0.005)
    for _ in range(fo):
        m.sample()
    m.block()                                   # commit
    m.block(); m.block()                        # burn the mt_blocks PDC gate
    while m.state == 2:
        m.sample()
    gains = []
    while m.state == 3:
        gains.append(m.sample())
    assert gains[-1] == 1.0
    steps = [gains[i] - gains[i - 1] for i in range(1, len(gains))]
    for s in steps:
        assert abs(s - 1.0 / fo) < 1e-12
    assert m.state == 0 and m.sample() is None


def test_v09_short_and_degenerate_fade_lengths_are_clamped():
    for sr in (48000, 8000, 100, 1):
        m = dsp.TopoMachine(srate=sr, P=2048, phase=0)
        m.slider(phase=1, hp_pl=0, lp_pl=0, bd0=8192, bd1=8192)
        n = 0
        while m.state == 1 and n < 10000:
            g = m.sample(); n += 1
            assert 0.0 <= g <= 1.0
        assert m.state == 2                     # always terminates, never divides by zero


def _run_to_commit(m, play_state=1):
    """Drive the machine through fade-out and commit; returns samples consumed."""
    n = 0
    while m.state == 1:
        m.sample(); n += 1
    m.block(play_state=play_state)
    return n


def test_v09_hold_matches_the_spec_table_for_every_geometry():
    cases = [
        # (bd0, bd1, expected hold in samples) - FULL KERNEL SUPPORT BD, not lat=BD/2+P
        (8192, 8192, 8192 + 8192 + 4096),      # Normal+Normal  = 20480 = 427 ms @48k
        (32768, 8192, 32768 + 8192 + 4096),    # High+Normal    = 45056 = 939 ms
        (32768, 32768, 32768 + 32768 + 4096),  # High+High      = 69632 = 1.45 s
    ]
    for bd0, bd1, want in cases:
        m = _tm(phase=0)
        m.slider(phase=1, hp_pl=0, lp_pl=0, bd0=bd0, bd1=bd1)
        _run_to_commit(m)
        assert m.hold == want, (bd0, bd1, m.hold, want)


def test_v09_linear_to_min_holds_zero_samples():
    m = _tm(phase=1, bd0=32768, bd1=32768)
    m.slider(phase=0, hp_pl=0, lp_pl=0, bd0=32768, bd1=32768)
    _run_to_commit(m)
    assert m.hold == 0


def test_v09_placement_and_resolution_get_the_same_hold_as_phase():
    base = dict(hp_pl=0, lp_pl=0, bd0=8192, bd1=8192)
    m1 = _tm(phase=1, **base); m1.slider(phase=1, hp_pl=1, lp_pl=0, bd0=8192, bd1=8192)
    m2 = _tm(phase=1, **base); m2.slider(phase=1, hp_pl=0, lp_pl=0, bd0=32768, bd1=8192)
    _run_to_commit(m1); _run_to_commit(m2)
    assert m1.hold == 20480
    assert m2.hold == 45056


def test_v09_hold_is_full_support_not_reported_latency():
    """Guard against a future 'optimization' back to lat0+lat1+P (spec §4.1, Fable P0-1)."""
    m = _tm(phase=0)
    m.slider(phase=1, hp_pl=0, lp_pl=0, bd0=32768, bd1=32768)
    _run_to_commit(m)
    assert m.hold == 69632
    assert m.hold != (32768 // 2 + 2048) * 2 + 2048, "hold fell back to the group-delay length"


def test_v09_fade_in_waits_for_the_block_gate_even_when_the_hold_is_zero():
    m = _tm(phase=1, bd0=8192, bd1=8192)
    m.slider(phase=0, hp_pl=0, lp_pl=0, bd0=8192, bd1=8192)   # hold == 0
    _run_to_commit(m)
    m.block()                                  # ready=1, blocks 2 -> 1
    for _ in range(5000):
        m.sample()
    assert m.state == 2, "fade-in started before the PDC block gate elapsed"
    m.block()                                  # blocks 1 -> 0
    m.sample()
    assert m.state == 3


def test_v09_hold_is_not_consumed_until_kernels_are_ready():
    m = _tm(phase=0)
    m.slider(phase=1, hp_pl=0, lp_pl=0, bd0=8192, bd1=8192)
    while m.state == 1:
        m.sample()
    # the commit block itself reports the kernels as NOT yet built (a BD=32768 rebuild can be
    # deferred past its own @block), so mt_ready must stay 0 from the very first pass
    assert m.block(kernels_ready=False) == "commit"
    for _ in range(3):
        m.block(kernels_ready=False)
    assert m.ready == 0
    for _ in range(50000):
        m.sample()
    assert m.state == 2 and m.pos == 0, "hold consumed before kernels were valid"
    m.block(kernels_ready=True); m.block(kernels_ready=True)
    m.sample()
    assert m.pos == 1


def test_v09_bypass_freezes_the_whole_machine():
    m = _tm(phase=0)
    m.slider(phase=1, hp_pl=0, lp_pl=0, bd0=8192, bd1=8192)
    for _ in range(200000):                    # far longer than fade+hold
        assert m.sample(bypass=True) is None
    assert m.state == 1 and m.pos == 0 and m.commit_count == 0
    # release bypass: the full sequence must still run
    _run_to_commit(m)
    assert m.commit_count == 1 and m.hold == 20480


def test_v09_stopped_transport_commits_early_but_still_holds():
    m = _tm(phase=0)
    m.slider(phase=1, hp_pl=0, lp_pl=0, bd0=8192, bd1=8192)
    assert m.block(play_state=0) == "commit"   # early commit, no samples needed
    assert m.act_phase == 1 and m.state == 2
    m.block(); m.block()
    n = 0
    while m.state == 2 and n < 200000:
        m.sample(); n += 1
    assert n == 20480, "warm-up was skipped by the stopped path"


def test_v09_no_block_while_stopped_still_commits_on_the_first_playback_block():
    m = _tm(phase=0)
    m.slider(phase=1, hp_pl=0, lp_pl=0, bd0=8192, bd1=8192)
    # REAPER delivered no @block at all while stopped: nothing may happen yet
    assert m.commit_count == 0 and m.act_phase == 0
    _run_to_commit(m)                          # first playback block
    assert m.commit_count == 1 and m.act_phase == 1


def test_v09_loading_a_project_with_non_default_topology_does_not_mute():
    """Fable P0-2: EEL2 defaults act_* to 0, and @init hardcodes Normal+Normal. Without the
    boot path, reopening a project saved as Linear/High/Mid would arm a mute AND play through
    the wrong topology until the hold expired - on every reload, and again on every sample-rate
    change (which re-runs @init)."""
    m = dsp.TopoMachine(srate=48000, P=2048, phase=1, hp_pl=1, lp_pl=0,
                        bd0=32768, bd1=32768, boot=True)
    m.slider(phase=1, hp_pl=1, lp_pl=0, bd0=32768, bd1=32768)   # the first @slider pass
    assert m.state == 0, "loading a project armed a spurious mute"
    assert m.act_phase == 1 and m.act_hp_pl == 1
    assert m.act_bd0 == 32768 and m.act_bd1 == 32768, "geometry not adopted at boot"
    assert m.sample() is None, "audio was muted on the first processed sample after load"
    assert m.boot == 0
    # and a real switch afterwards still works normally
    m.slider(phase=1, hp_pl=2, lp_pl=0, bd0=32768, bd1=32768)
    assert m.state == 1 and m.pend == 1


def test_v09_boot_adopts_whatever_the_sliders_say_even_if_it_differs_from_the_constructor():
    """The constructor models EEL2's zero-initialised globals; the sliders model the loaded
    project. Boot must follow the sliders, not the defaults."""
    m = dsp.TopoMachine(srate=48000, P=2048, phase=0, hp_pl=0, lp_pl=0,
                        bd0=8192, bd1=8192, boot=True)
    m.slider(phase=1, hp_pl=2, lp_pl=1, bd0=32768, bd1=8192)
    assert m.state == 0 and m.commit_count == 0
    assert (m.act_phase, m.act_hp_pl, m.act_lp_pl) == (1, 2, 1)
    assert (m.act_bd0, m.act_bd1) == (32768, 8192)


def test_v09_every_commit_clears_the_engines_and_phase_edges_clear_minphase():
    m = _tm(phase=1, bd0=8192, bd1=8192)
    m.slider(phase=1, hp_pl=1, lp_pl=0, bd0=8192, bd1=8192)   # placement only
    _run_to_commit(m)
    assert m.clears == ["engines"]
    m2 = _tm(phase=0)
    m2.slider(phase=1, hp_pl=0, lp_pl=0, bd0=8192, bd1=8192)  # phase edge
    _run_to_commit(m2)
    assert m2.clears == ["engines", "minphase"]


def _noise(n, seed=1):
    """Deterministic stdlib-only pseudo-noise in [-1, 1]."""
    x = seed
    out = []
    for _ in range(n):
        x = (1103515245 * x + 12345) % 2147483648
        out.append(x / 1073741824.0 - 1.0)
    return out


def test_v09_after_a_full_support_hold_the_cleared_engine_equals_a_CONTINUOUS_one():
    """THE test the hold length must satisfy (spec §4.6, Fable P0-3).

    The reference is an engine that NEVER stopped - it processed the pre-commit history too.
    Equality can only hold once every sample the output depends on lies after the commit, i.e.
    after the kernel's full support BD. Comparing against a cleared-at-commit reference instead
    (what rev 2 specified) would be satisfied at ANY hold length, including zero."""
    P = 256
    BD = 1024
    ker = dsp.build_lp_kernel(BD, "hp", 200.0, 0.0, 2, 14.0, 48000)
    pre = _noise(4000, seed=7)
    post = _noise(4000, seed=99)
    T = len(pre)
    sig = pre + post
    zeros = [0.0] * len(sig)
    cleared = dsp.lp_engine_ref(sig, zeros, ker, ker, P, clear_at=T)["outA"]
    continuous = dsp.lp_engine_ref(sig, zeros, ker, ker, P)["outA"]           # never cleared
    hold = BD + P
    peak = max(abs(v) for v in continuous)
    worst = max(abs(a - b) for a, b in zip(cleared[T + hold:], continuous[T + hold:]))
    # Not bit-identical: the two runs sum different FFT blocks, so they differ by float64
    # rounding only. Measured -285 dBFS; the gate is set well above that and far below the
    # -43 dBFS the group-delay length leaves (see the companion test).
    assert worst / peak < 1e-12, f"cleared engine differs from a continuous one: {worst/peak}"


def test_v09_a_group_delay_hold_would_NOT_have_been_enough():
    """The negative half of the pair: at rev 2's lat = BD/2 + P the two still differ, so this
    test fails if anyone shortens mt_hold back to the reported latency."""
    P = 256
    BD = 1024
    ker = dsp.build_lp_kernel(BD, "hp", 200.0, 0.0, 2, 14.0, 48000)
    pre = _noise(4000, seed=7)
    post = _noise(4000, seed=99)
    T = len(pre)
    sig = pre + post
    zeros = [0.0] * len(sig)
    cleared = dsp.lp_engine_ref(sig, zeros, ker, ker, P, clear_at=T)["outA"]
    continuous = dsp.lp_engine_ref(sig, zeros, ker, ker, P)["outA"]
    lat = BD // 2 + P
    peak = max(abs(v) for v in continuous)
    window = slice(T + lat, T + lat + P)
    diff = max(abs(a - b) for a, b in zip(cleared[window], continuous[window]))
    # Measured -43 dBFS: audible, not a rounding artefact. Six orders of magnitude above the
    # full-support residual, which is what makes the choice of BD over BD/2+P non-cosmetic.
    assert diff / peak > 1e-3, \
        f"only {diff/peak} error at the group-delay length - the short hold would have done"


def test_v09_serial_pair_needs_BD0_plus_BD1_plus_P():
    """Spec §4.5: the serial composition. Engine 0's output is free of pre-commit influence
    after BD0 samples plus its own hop; engine 1 then needs BD1 samples of that clean input plus
    its own hop - hence 2P, not P. Measured residual: -219 dBFS at +P, -282 dBFS at +2P."""
    P = 256
    BD0 = 1024
    BD1 = 512
    k0 = dsp.build_lp_kernel(BD0, "hp", 200.0, 0.0, 2, 14.0, 48000)
    k1 = dsp.build_lp_kernel(BD1, "lp", 8000.0, 0.0, 2, 14.0, 48000)
    pre = _noise(4000, seed=3)
    post = _noise(4000, seed=5)
    T = len(pre)
    sig = pre + post
    zeros = [0.0] * len(sig)

    def serial(clear_at):
        a = dsp.lp_engine_ref(sig, zeros, k0, k0, P, clear_at=clear_at)["outA"]
        return dsp.lp_engine_ref(a, zeros, k1, k1, P, clear_at=clear_at)["outA"]

    cleared = serial(T)
    continuous = serial(None)
    hold = BD0 + BD1 + 2 * P
    peak = max(abs(v) for v in continuous)
    worst = max(abs(a - b) for a, b in zip(cleared[T + hold:], continuous[T + hold:]))
    assert worst / peak < 1e-12, f"serial pair not warm at BD0+BD1+2P: {worst/peak}"


def test_v09_without_the_clear_old_domain_energy_outlives_the_group_delay():
    """Proves the clear is NECESSARY: a linear-phase kernel has support BD, not BD/2, so a
    placement switch that keeps the engine state leaks old-domain output for ~BD+P samples."""
    P = 256
    BD = 1024
    ker = dsp.build_lp_kernel(BD, "hp", 200.0, 0.0, 2, 14.0, 48000)
    pre = _noise(3000, seed=7)
    post = [0.0] * 3000                      # silence after the switch
    T = len(pre)
    zeros = [0.0] * (T + len(post))
    kept = dsp.lp_engine_ref(pre + post, zeros, ker, ker, P)                 # no clear
    lat = BD // 2 + P
    tail = kept["outA"][T + lat + P:T + BD + P]
    assert max(abs(v) for v in tail) > 1e-9, \
        "old-domain energy vanished by lat+P - the group-delay hold would have been enough"


def test_v09_shipping_warmup_bounds_match_the_spec_table():
    """Drives the real machine at the shipping geometry. The earlier version of this test
    asserted `bd0 + bd1 + 2*P == want` with `want` restating the same formula - it could not
    fail and was evidence of nothing (found by Fable's final review)."""
    for bd0, bd1, want in ((8192, 8192, 20480), (32768, 8192, 45056), (32768, 32768, 69632)):
        m = _tm(phase=0)
        m.slider(phase=1, hp_pl=0, lp_pl=0, bd0=bd0, bd1=bd1)
        _run_to_commit(m)
        assert m.hold == want, (bd0, bd1, m.hold, want)
        # and the hold really is consumed sample by sample, not skipped
        m.block(); m.block()
        n = 0
        while m.state == 2 and n <= want:
            m.sample(); n += 1
        assert n == want, f"hold consumed in {n} samples, expected {want}"


def _apply_machine(sig, m, events, srate=48000, block=512):
    """Run `sig` through the mute envelope, delivering @block every `block` samples and
    applying topology events at their pinned sample index. Returns the enveloped signal."""
    out = []
    for n, x in enumerate(sig):
        if n in events:
            m.slider(*events[n])
        if n % block == 0:
            m.block()
        g = m.sample()
        out.append(x if g is None else x * g)
    return out


def test_v09_no_signal_survives_the_intended_mute():
    srate = 48000
    n = srate                                     # 1 s
    sig = _noise(n, seed=11)
    m = dsp.TopoMachine(srate=srate, P=2048, phase=1, bd0=8192, bd1=8192)
    ev = {1000: (1, 1, 0, 8192, 8192)}            # placement switch at sample 1000
    out = _apply_machine(sig, m, ev, srate=srate)
    fo = max(1, int(srate * 0.005))
    start = 1000 + fo                             # fully muted from here
    end = start + 20480                           # ... until the hold expires
    worst = max(abs(v) for v in out[start:end])
    assert worst == 0.0, f"signal leaked through the mute: {worst}"


def test_v09_fade_endpoints_never_exceed_the_one_over_n_step_bound():
    srate = 48000
    n = 40000
    sig = [1.0] * n                               # DC: every envelope step is directly visible
    m = dsp.TopoMachine(srate=srate, P=2048, phase=1, bd0=8192, bd1=8192)
    out = _apply_machine(sig, m, {100: (1, 1, 0, 8192, 8192)}, srate=srate)
    fo = max(1, int(srate * 0.005))
    steps = [abs(out[i] - out[i - 1]) for i in range(1, len(out))]
    bound = 1.0 / fo * 1.000001
    assert max(steps) <= bound, f"largest step {max(steps)} exceeds 1/N = {1.0/fo}"


def test_v09_impulse_just_before_commit_does_not_reappear_after_the_clear():
    """Sustained audio can hide stale energy under new steady output; an impulse cannot."""
    P = 256
    BD = 1024
    ker = dsp.build_lp_kernel(BD, "hp", 200.0, 0.0, 2, 14.0, 48000)
    T = 2000
    sig = [0.0] * (T + 3000)
    sig[T - 1] = 1.0                              # impulse in the LAST pre-commit sample
    zeros = [0.0] * len(sig)
    cleared = dsp.lp_engine_ref(sig, zeros, ker, ker, P, clear_at=T)
    assert all(v == 0.0 for v in cleared["outA"][T:]), \
        "the pre-commit impulse survived the clear"


def test_v09_steep_filters_are_the_worst_case_for_the_hold():
    """Spec §8.12: a 96 dB/oct kernel at high resonance is the case most likely to expose a
    partially-formed response, so the hold must hold up there too - and the group-delay length
    must still be visibly wrong there."""
    P = 256
    BD = 1024
    ker = dsp.build_lp_kernel(BD, "hp", 400.0, 0.9, 8, 14.0, 48000)   # 8 sections, high res
    pre = _noise(4000, seed=21)
    post = _noise(4000, seed=22)
    T = len(pre)
    sig = pre + post
    zeros = [0.0] * len(sig)
    cleared = dsp.lp_engine_ref(sig, zeros, ker, ker, P, clear_at=T)["outA"]
    continuous = dsp.lp_engine_ref(sig, zeros, ker, ker, P)["outA"]
    peak = max(abs(v) for v in continuous)
    hold = BD + 2 * P
    worst = max(abs(a - b) for a, b in zip(cleared[T + hold:], continuous[T + hold:]))
    assert worst / peak < 1e-12, f"steep filter not warm after the hold: {worst/peak}"
    lat = BD // 2 + P
    win = slice(T + lat, T + lat + P)
    short = max(abs(a - b) for a, b in zip(cleared[win], continuous[win]))
    assert short / peak > 1e-3, f"group-delay length looks fine here: {short/peak}"


# ---- V0.9 re-trigger paths (spec §8.10). Fable's final review found these were implemented on
# both sides of the oracle/JSFX pair but exercised by NEITHER: every earlier test that called
# .slider() twice used two separate machines. A transcription slip here would not have been
# caught by anything except a lucky live listen.

def test_v09_reversal_before_commit_cancels_without_committing():
    m = _tm(phase=1, hp_pl=0, lp_pl=0, bd0=8192, bd1=8192)
    m.slider(phase=1, hp_pl=1, lp_pl=0, bd0=8192, bd1=8192)     # Both -> Mid
    fo = m.fo
    for _ in range(fo // 2):                                     # halfway down
        m.sample()
    g_mid = m.g
    assert 0.0 < g_mid < 1.0
    m.slider(phase=1, hp_pl=0, lp_pl=0, bd0=8192, bd1=8192)     # back to Both before commit
    assert m.pend == 0, "reversal did not cancel the pending commit"
    assert m.state == 3, "reversal did not turn into a fade-in"
    assert m.block() == "", "a commit happened despite the reversal"
    # the envelope must resume from where it was, never jump
    first = m.sample()
    assert abs(first - g_mid) <= 1.0 / fo + 1e-9, f"envelope jumped: {g_mid} -> {first}"
    while m.state == 3:
        m.sample()
    assert m.state == 0 and m.g == 1.0
    assert m.commit_count == 0
    assert m.act_hp_pl == 0, "the active topology changed despite the reversal"


def test_v09_two_events_during_fade_out_coalesce_into_one_commit():
    m = _tm(phase=1, hp_pl=0, lp_pl=0, bd0=8192, bd1=8192)
    m.slider(phase=1, hp_pl=1, lp_pl=0, bd0=8192, bd1=8192)     # -> Mid
    for _ in range(m.fo // 3):
        m.sample()
    m.slider(phase=1, hp_pl=2, lp_pl=0, bd0=32768, bd1=8192)    # -> Side AND High, still fading
    assert m.state == 1 and m.pend == 1
    _run_to_commit(m)
    assert m.commit_count == 1, "coalescing produced more than one commit"
    assert m.act_hp_pl == 2 and m.act_bd0 == 32768, "the final selection was not the one applied"
    assert m.hold == 32768 + 8192 + 2 * 2048, "hold not computed from the FINAL geometry"


def test_v09_event_after_commit_restarts_the_fade_without_a_jump():
    m = _tm(phase=1, hp_pl=0, lp_pl=0, bd0=8192, bd1=8192)
    m.slider(phase=1, hp_pl=1, lp_pl=0, bd0=8192, bd1=8192)
    _run_to_commit(m)                                            # now in the hold, g == 0
    m.block(); m.block()
    for _ in range(100):
        m.sample()
    m.slider(phase=1, hp_pl=2, lp_pl=0, bd0=8192, bd1=8192)     # new event during the hold
    assert m.pend == 1
    assert m.g == 0.0, "envelope left zero when re-armed from silence"
    _run_to_commit(m)
    assert m.commit_count == 2 and m.act_hp_pl == 2


def test_v09_event_during_fade_in_restarts_the_fade_out_from_the_current_gain():
    m = _tm(phase=1, hp_pl=0, lp_pl=0, bd0=8192, bd1=8192)
    m.slider(phase=1, hp_pl=1, lp_pl=0, bd0=8192, bd1=8192)
    _run_to_commit(m)
    m.block(); m.block()
    while m.state == 2:
        m.sample()
    for _ in range(m.fi // 2):                                   # halfway back up
        m.sample()
    g_mid = m.g
    assert 0.0 < g_mid < 1.0 and m.state == 3
    m.slider(phase=1, hp_pl=0, lp_pl=0, bd0=8192, bd1=8192)     # switch again mid fade-in
    assert m.state == 1 and m.pend == 1
    first = m.sample()
    assert abs(first - g_mid) <= 1.0 / m.fo + 1e-9, f"envelope jumped: {g_mid} -> {first}"
    assert first < g_mid, "fade did not reverse direction"


def test_v09_rapid_switching_never_sticks_muted_and_always_resolves():
    """The live 'five flips in two seconds' case, made deterministic."""
    m = _tm(phase=1, hp_pl=0, lp_pl=0, bd0=8192, bd1=8192)
    placements = [1, 2, 3, 4, 0]
    n = 0
    for i, pl in enumerate(placements):
        m.slider(phase=1, hp_pl=pl, lp_pl=0, bd0=8192, bd1=8192)
        for _ in range(300):                                     # ~6 ms between flips
            if n % 512 == 0:
                m.block()
            m.sample(); n += 1
    # let it settle
    while m.state != 0 and n < 2_000_000:
        if n % 512 == 0:
            m.block()
        m.sample(); n += 1
    assert m.state == 0, "machine stuck muted after rapid switching"
    assert m.g == 1.0
    assert m.act_hp_pl == 0, "final selection not applied"


# ===================== Distortion hygiene (probe, 2026-08-14) =====================
# Thresholds are derived from measurement, not guessed: every linear block measures around
# -283 dB, which is float64 arithmetic itself. -250 dB leaves headroom while still failing
# loudly if any block starts distorting.

from tools import rcbitnova_probe as probe   # noqa: E402


LINEAR_FLOOR_DB = -250.0


def test_probe_measurement_floor_is_arithmetic_not_window():
    """Guards the probe itself: a smooth window would put the floor near -92 dB and every
    'clean' result below would become vacuous. Coherent sampling must keep it near float64."""
    r = probe.probe_tone(lambda s: list(s))          # identity: nothing but the tone
    assert r["thd"] < -280.0, f"probe floor degraded to {r['thd']} dB"


def test_probe_static_bands_are_linear():
    for ftype, gain in (("bell", 1.0), ("bell", 2.0), ("lowshelf", 0.5), ("highshelf", 2.0)):
        r = probe.probe_tone(lambda s: probe.run_band(s, 48000, ftype=ftype, gain_lin=gain))
        assert r["thd"] < LINEAR_FLOOR_DB, (ftype, gain, r["thd"])
        assert r["alias_peak"] < LINEAR_FLOOR_DB, (ftype, gain, r["alias_peak"])


def test_probe_hplp_paths_are_linear():
    cases = [
        lambda s: probe.run_hplp_min(s, 48000, "hp", 100.0, 0.0, 4),
        lambda s: probe.run_hplp_min(s, 48000, "lp", 8000.0, 0.0, 8),
        lambda s: probe.run_hplp_linear(s, 48000, "hp", 100.0, 0.0, 4),
        lambda s: probe.run_fir_brick(s, 48000, "lp", 15000.0),
    ]
    for fn in cases:
        r = probe.probe_tone(fn)
        assert r["thd"] < LINEAR_FLOOR_DB, r["thd"]


def test_probe_bit_gain_is_exactly_a_power_of_two():
    """Not a threshold - an identity. Halving then doubling must return the input bit-for-bit."""
    assert probe.is_bit_transparent(lambda s: [x * 2.0 for x in probe.run_bit_gain(s, macro=-1)])
    assert probe.is_bit_transparent(lambda s: probe.run_bit_gain(s, macro=0))


def test_probe_dynamics_below_threshold_add_nothing():
    """The most valuable hygiene row: a dynamics stage that is not acting must be transparent.
    No listening test reveals a detector that leaks while idle."""
    for fn in (lambda s: probe.run_modea(s, 48000, ceiling=0.9),
               lambda s: probe.run_modeb(s, 48000, ceil_soft=0.9, ceil_hard=0.9)):
        r = probe.probe_tone(fn, amp=0.5)
        assert r["thd"] < LINEAR_FLOOR_DB, r["thd"]


def test_probe_modeb_aliasing_stays_far_below_modea():
    """Pins the 2026-08-14 finding that drives the oversampling decision: Mode B is clean and
    Mode A is not. If a future change closes that gap, this test should be revisited - and if it
    inverts, the oversampling plan is wrong."""
    a = probe.probe_tone(
        lambda s: probe.run_modea(s, 48000, fc=19000, ceiling=0.125, atk=0.05, rel=70.0),
        target_hz=19000, amp=0.5)
    b = probe.probe_tone(
        lambda s: probe.run_modeb(s, 48000, fc=19000, ceil_soft=0.125, ceil_hard=0.125,
                                  look=5.0, rel=70.0),
        target_hz=19000, amp=0.5)
    assert b["alias_peak"] < -110.0, f"Mode B aliasing regressed to {b['alias_peak']}"
    assert a["alias_peak"] > -80.0, f"Mode A unexpectedly clean ({a['alias_peak']}) - re-measure"
    assert b["alias_peak"] < a["alias_peak"] - 40.0


def test_probe_modea_aliasing_improves_with_slower_attack():
    """The mitigation offered in the report must actually hold."""
    fast = probe.probe_tone(
        lambda s: probe.run_modea(s, 48000, fc=19000, ceiling=0.125, atk=0.05, rel=70.0),
        target_hz=19000, amp=0.5)
    slow = probe.probe_tone(
        lambda s: probe.run_modea(s, 48000, fc=19000, ceiling=0.125, atk=50.0, rel=70.0),
        target_hz=19000, amp=0.5)
    assert slow["alias_peak"] < fast["alias_peak"] - 15.0, (fast["alias_peak"], slow["alias_peak"])


# ===================== V1.0 GUI curve maths =====================
# EVERYTHING IS IN BITS. band_bits/hplp_bits return log2|H|, and domain_bits SUMS them.
# The earlier draft mixed linear magnitudes with bit grids and multiplied one by the other -
# a silent arithmetic error. One currency removes that class entirely.

from tools import rcbitnova_curve as curve   # noqa: E402


def _band(**kw):
    b = dict(enable=1, type="bell", freq=1000.0, q=0.707, macro=0, micro=0.0,
             ratio=1.0, placement="both", qchar=0.0)
    b.update(kw)
    return b


def _hp(**kw):
    h = dict(ftype="hp", slope=4, freq=100.0, res=0.0, placement="both")
    h.update(kw)
    return h


def test_v10_bell_at_fc_is_the_full_bit_gain():
    for bits in (2.0, -2.0, 0.5):
        b = _band(macro=int(bits), micro=(bits - int(bits)) * 100)
        assert abs(curve.band_bits(b, 1000.0, 48000) - bits) < 1e-9, bits


def test_v10_shelf_at_fc_is_exactly_half_the_gain():
    """The shipping TPT shelf uses A = sqrt(gain_lin), so at fc it is EXACTLY bits/2 - measured
    with svf_response, the exact closed form. An earlier draft pinned 0.9966 here, which was an
    artefact of reading FFT bin 171 (1002 Hz) instead of 1000 Hz."""
    for ftype in ("lowshelf", "highshelf"):
        for bits in (2.0, -2.0):
            for fc in (100.0, 1000.0, 8000.0):
                for q in (0.4, 0.707, 3.0):
                    b = _band(type=ftype, freq=fc, q=q, macro=int(bits))
                    got = curve.band_bits(b, fc, 48000)
                    assert abs(got - bits / 2) < 1e-9, (ftype, bits, fc, q, got)


def test_v10_disabled_band_contributes_zero_bits():
    assert curve.band_bits(_band(enable=0, macro=4), 1000.0, 48000) == 0.0


def test_v10_band_far_from_centre_tends_to_zero_bits():
    assert abs(curve.band_bits(_band(macro=4, q=4.0), 20.0, 48000)) < 0.01


def test_v10_band_width_follows_q_eff_not_the_knob():
    wide = _band(macro=4, q=1.0, qchar=0.0)
    narrow = _band(macro=4, q=1.0, qchar=1.0)
    off = 1000.0 * 2 ** (1 / 6)
    assert curve.band_bits(narrow, off, 48000) < curve.band_bits(wide, off, 48000)


def test_v10_bit_ratio_scales_the_gain():
    """The node is drawn at (macro + micro/100) * ratio - the same expression as the audio."""
    assert abs(curve.band_bits(_band(macro=2, ratio=0.5), 1000.0, 48000) - 1.0) < 1e-9
    assert abs(curve.band_bits(_band(macro=2, ratio=0.0), 1000.0, 48000)) < 1e-12


def test_v10_min_phase_brick_is_identity():
    """Brick maps to nsec = 0 in the min path, so the audible response IS no filter. Drawing a
    cutoff there would show something that is not being heard."""
    for f in (20.0, 100.0, 1000.0, 15000.0):
        assert curve.hplp_bits(_hp(slope=6), f, 48000, act_phase=0) == 0.0


def test_v10_min_phase_hplp_matches_the_oracle():
    """The slope slider holds an ENUM, not a section count: 5 means 96 dB/oct = 8 sections."""
    import math
    for slope_enum, nsec in ((1, 1), (2, 2), (4, 4), (5, 8)):
        for f in (50.0, 100.0, 400.0):
            got = curve.hplp_bits(_hp(slope=slope_enum), f, 48000, act_phase=0)
            want = math.log2(dsp.hplp_digital_mag("hp", 100.0, 0.0, nsec, f, 48000))
            assert abs(got - want) < 1e-12, (slope_enum, nsec, f)


def test_v10_hplp_is_minus_3db_at_cutoff_only_without_resonance():
    plain = curve.hplp_bits(_hp(slope=4, res=0.0), 100.0, 48000, act_phase=0)
    assert abs(plain * 6.0206 + 3.0) < 0.2
    assert curve.hplp_bits(_hp(slope=4, res=1.0), 100.0, 48000, act_phase=0) > plain


def test_v10_domain_trace_sums_both_blocks_and_its_own():
    """A Both block applies identical coefficients to L and R, which by linearity is identical
    to applying them to M and S - so it belongs in EVERY domain trace."""
    bands = [_band(macro=2, placement="both"), _band(freq=4000.0, macro=2, placement="mid")]
    f = 1000.0
    mid = curve.domain_bits(bands, [], "mid", f, 48000, 1)
    side = curve.domain_bits(bands, [], "side", f, 48000, 1)
    both_only = curve.band_bits(bands[0], f, 48000)
    assert abs(mid - (both_only + curve.band_bits(bands[1], f, 48000))) < 1e-12
    assert abs(side - both_only) < 1e-12


def test_v10_domain_trace_excludes_other_domains():
    """Guards the rev-1 mistake: folding every block into one scalar curve."""
    bands = [_band(macro=3, placement="left"), _band(macro=3, placement="right")]
    f = 1000.0
    left = curve.domain_bits(bands, [], "left", f, 48000, 1)
    assert abs(left - curve.band_bits(bands[0], f, 48000)) < 1e-12
    assert abs(left - 3.0) < 1e-9


def test_v10_audible_activity_excludes_off_and_min_brick():
    """A filter dict has no 'enable' key. Counting an Off slope as active would light up its
    domain and falsely dash every trace as a mixed placement family."""
    assert curve.is_audible(_band(), 1) is True
    assert curve.is_audible(_band(enable=0), 1) is False
    assert curve.is_audible(_hp(slope=0), 1) is False          # Off
    assert curve.is_audible(_hp(slope=6), 0) is False          # Min + Brick == identity
    assert curve.is_audible(_hp(slope=6), 1) is True           # Linear + Brick is real
    assert curve.is_audible(_hp(slope=4), 0) is True


def test_v10_mixed_placement_families_only_when_audible():
    ms = [_band(placement="mid")]
    lr_off = [_hp(slope=0, placement="left")]
    assert curve.mixed_placement_families(ms, lr_off, 1) is False, "an Off filter dashed the traces"
    lr_on = [_hp(slope=4, placement="left")]
    assert curve.mixed_placement_families(ms, lr_on, 1) is True


# ---- V1.0 axis mapping and the single-slider gesture solvers ----
# One gesture writes one slider, so there is deliberately NO canonical split, NO write ordering,
# NO fractional snapping and NO rounding-tie parity problem here. If any of those reappear, the
# gesture rule has been broken somewhere.

def test_v10_frequency_axis_round_trips():
    for f in (20.0, 100.0, 1000.0, 12345.0, 20000.0):
        x = curve.f_to_x(f, 40, 800)
        assert abs(curve.x_to_f(x, 40, 800) - f) < 1e-6, f


def test_v10_bits_axis_round_trips_and_clamps():
    for b in (-4.0, -1.5, 0.0, 2.25, 4.0):
        y = curve.bits_to_y(b, 10, 400)
        assert abs(curve.y_to_bits(y, 10, 400) - b) < 1e-9, b
    assert curve.bits_to_y(99.0, 10, 400) == curve.bits_to_y(4.0, 10, 400)
    assert curve.bits_to_y(-99.0, 10, 400) == curve.bits_to_y(-4.0, 10, 400)


def test_v10_rounding_is_half_away_from_zero_in_both_signs():
    """Python's round() is ties-to-even, EEL2's floor(x+0.5) is ties-toward-positive; they
    disagree exactly here. One rule, one shared helper, both languages."""
    table = {0.5: 1, 1.5: 2, 2.5: 3, -0.5: -1, -1.5: -2, -2.5: -3,
             0.4: 0, -0.4: 0, 2.6: 3, -2.6: -3}
    for x, want in table.items():
        assert curve.round_half_away(x) == want, (x, curve.round_half_away(x), want)


def test_v10_macro_step_is_relative_to_mouse_down():
    """Relative, not an absolute solve: an absolute inverse flips sign with negative gain and
    is undefined at zero base."""
    assert curve.macro_from_drag(0, 0.0, 1.0) == 0
    assert curve.macro_from_drag(0, -24.0, 1.0) == 1        # up is negative y, +1 bit
    assert curve.macro_from_drag(2, 48.0, 1.0) == 0         # down 2 bits from 2
    assert curve.macro_from_drag(0, -23.0, 1.0) == 0        # not a full step yet


def test_v10_drag_threshold_keeps_a_click_from_writing():
    assert curve.drag_steps(0.0, 24) == 0
    assert curve.drag_steps(3.9, 24) == 0
    assert curve.drag_steps(-3.9, 24) == 0
    assert curve.drag_steps(24.0, 24) == 1
    assert curve.drag_steps(-48.0, 24) == -2
    assert curve.drag_steps(12.0, 12) == 1


def test_v10_macro_clamps_to_the_slider_range():
    assert curve.macro_from_drag(16, -24.0 * 5, 1.0) == 16
    assert curve.macro_from_drag(-16, 24.0 * 5, 1.0) == -16


def test_v10_ratio_drag_stays_on_the_005_grid_and_clamps():
    assert abs(curve.ratio_from_drag(1.0, -12.0) - 1.05) < 1e-12
    assert abs(curve.ratio_from_drag(1.0, 12.0) - 0.95) < 1e-12
    assert curve.ratio_from_drag(0.0, 12.0 * 5) == 0.0        # clamps at 0
    assert curve.ratio_from_drag(3.0, -12.0 * 5) == 3.0       # clamps at 3
    for steps in range(-20, 21):
        v = curve.ratio_from_drag(1.0, steps * 12.0)
        assert abs(round(v / 0.05) - v / 0.05) < 1e-9, v


def test_v10_ratio_025_is_reachable_only_on_the_005_grid():
    """The owner's criterion: a quarter is a simple binary fraction and 0.2 is not, and they
    differ in character. At the shipping 0.1 step 0.25 does not exist at all."""
    reachable = {round(curve.ratio_from_drag(0.0, -12.0 * i), 3) for i in range(0, 61)}
    assert 0.25 in reachable
    assert 0.2 in reachable
    assert 0.25 not in {round(i * 0.1, 3) for i in range(31)}


def test_v10_q_drag_clamps_to_the_slider_range():
    assert abs(curve.q_from_drag(1.0, -12.0, False) - 1.01) < 1e-12
    assert abs(curve.q_from_drag(1.0, -12.0, True) - 1.005) < 1e-12
    assert curve.q_from_drag(10.0, -12.0 * 100, False) == 10.0
    assert curve.q_from_drag(0.1, 12.0 * 100, False) == 0.1


def test_v10_gestures_never_produce_micro():
    """The rule that replaced the whole pair-write hazard. Every solver returns ONE parameter,
    and none of them is Micro - it is typed only."""
    import inspect
    for fn in (curve.macro_from_drag, curve.ratio_from_drag, curve.q_from_drag):
        src = inspect.getsource(fn)
        assert "micro" not in src.lower(), f"{fn.__name__} touches Micro"


# ---- V1.0 realized linear-phase / Brick magnitude, from ONE fft of the windowed kernel ----

def _dtft_bits(ker, sr, f):
    """Slow but obviously-correct reference: direct DTFT at one frequency, in bits."""
    import math
    w = 2 * math.pi * f / sr
    re = sum(h * math.cos(-w * n) for n, h in enumerate(ker))
    im = sum(h * math.sin(-w * n) for n, h in enumerate(ker))
    return curve.mag_to_bits(math.hypot(re, im))


def test_v10_realized_grid_matches_a_direct_dtft():
    BD, sr = 1024, 48000
    ker = dsp.fir_brick_kernel(BD, "lp", 8000.0, 14.0, sr)
    grid = curve.realized_bits_grid(ker, sr, n_out=512)
    for f in (100.0, 1000.0, 4000.0, 7000.0, 9000.0, 14000.0):
        got = curve.sample_grid_bits(grid, f)
        want = _dtft_bits(ker, sr, f)
        assert abs(got - want) < 0.05, (f, got, want)


def test_v10_realized_covers_ordinary_kernels_not_only_brick():
    """A transcription that works for Brick but mis-samples an ordinary windowed kernel would
    pass a Brick-only suite. Cover HP and LP at several slopes and resonances."""
    sr = 48000
    for ftype, freq, nsec, res in (("hp", 200.0, 2, 0.0), ("hp", 200.0, 4, 0.8),
                                   ("lp", 6000.0, 2, 0.0), ("lp", 6000.0, 8, 0.5)):
        ker = dsp.impulse_fft_kernel(1024, ftype, freq, res, nsec, 14.0, sr)
        grid = curve.realized_bits_grid(ker, sr, n_out=512)
        for f in (freq * 0.5, freq, freq * 2, freq * 4):
            if f >= sr * 0.45:
                continue
            got = curve.sample_grid_bits(grid, f)
            want = _dtft_bits(ker, sr, f)
            assert abs(got - want) < 0.1, (ftype, freq, nsec, res, f, got, want)


def test_v10_realized_brick_is_not_identity():
    """Linear + Brick must draw an actual cutoff. Drawing 'no filter' is the min-phase answer
    and would be wrong here."""
    BD, sr = 2048, 48000
    ker = dsp.fir_brick_kernel(BD, "lp", 5000.0, 14.0, sr)
    grid = curve.realized_bits_grid(ker, sr, n_out=512)
    assert abs(curve.sample_grid_bits(grid, 1000.0)) < 0.1
    assert curve.sample_grid_bits(grid, 12000.0) < -10.0


def test_v10_realized_grid_never_runs_past_nyquist():
    """ktime is real, so X[N-k] = conj(X[k]); only bins 0..N/2 carry information."""
    ker = dsp.fir_brick_kernel(1024, "hp", 500.0, 14.0, 48000)
    grid = curve.realized_bits_grid(ker, 48000, n_out=256)
    assert max(f for f, _ in grid) <= 48000 / 2 + 1e-9


def test_v10_high_resolution_differs_from_normal_on_a_steep_low_cut():
    """The case that motivated V0.7. If the drawn curve did not differ here it would not be
    showing the realized kernel at all."""
    sr = 96000
    lo = curve.realized_bits_grid(dsp.fir_brick_kernel(8192, "hp", 40.0, 14.0, sr), sr, 512)
    hi = curve.realized_bits_grid(dsp.fir_brick_kernel(32768, "hp", 40.0, 14.0, sr), sr, 512)
    at20_lo = curve.sample_grid_bits(lo, 20.0)
    at20_hi = curve.sample_grid_bits(hi, 20.0)
    assert at20_hi < at20_lo - 3.0, (at20_lo, at20_hi)


def test_v10_grid_reduction_error_is_bounded_against_the_full_fft():
    """The 2048-point cache must not re-create the sparse grid the FFT was chosen to avoid.

    Measured behaviour, worst case being a Brick cutoff placed deliberately off the grid
    (3777 Hz), inside the VISIBLE range only (below about -8 bits the curve is pinned to the
    bottom edge and nothing is drawn there):

        BD=8192,  n_out=2048 -> 0.311 bits    BD=8192,  n_out=4096 -> 0.103 bits
        BD=2048,  n_out=2048 -> 0.659 bits    BD=2048,  n_out=4096 -> 0.810 bits

    The error sits at the knee and is set by the FFT's own resolution, not by n_out - which is
    why a denser grid does not help at BD=2048 and slightly hurts. Production geometries are
    BD 8192 and 32768, so the contract is written for those.
    """
    sr = 48000
    ker = dsp.fir_brick_kernel(8192, "lp", 3777.0, 14.0, sr)
    grid = curve.realized_bits_grid(ker, sr, n_out=2048)
    worst = 0.0
    for i in range(len(grid) - 1):
        f_mid = math.sqrt(grid[i][0] * grid[i + 1][0])
        if f_mid < 100.0 or f_mid > 16000.0:
            continue
        want = _dtft_bits(ker, sr, f_mid)
        if want > -8.0:
            worst = max(worst, abs(curve.sample_grid_bits(grid, f_mid) - want))
    assert worst < 0.4, worst


def test_v10_grid_error_away_from_a_knee_is_negligible():
    """Away from a near-vertical skirt the reduction is essentially exact - the 0.3 bits above
    is a property of the knee, not of the whole curve."""
    sr = 48000
    ker = dsp.impulse_fft_kernel(8192, "hp", 200.0, 0.0, 2, 14.0, sr)
    grid = curve.realized_bits_grid(ker, sr, n_out=2048)
    for f in (400.0, 1000.0, 4000.0, 12000.0):
        assert abs(curve.sample_grid_bits(grid, f) - _dtft_bits(ker, sr, f)) < 0.01, f


def test_v10_log_floor_keeps_everything_finite():
    """FIR Brick's target contains exact zeros; log2(0) would corrupt a whole line strip."""
    ker = dsp.fir_brick_kernel(1024, "lp", 2000.0, 14.0, 48000)
    grid = curve.realized_bits_grid(ker, 48000, n_out=256)
    for f, b in grid:
        assert math.isfinite(b), (f, b)
        assert b >= curve.BITS_FLOOR


# ---- V1.0 publication protocol: per-engine grids, target/active generations, trace frames ----

def test_v10_reader_never_sees_an_unpublished_write():
    """Reserving memory does not make an array update atomic. A frame must show one kernel or
    the other, never a mixture."""
    c = curve.CurveCache(n_out=8)
    c.write_inactive("hp", [(100.0, 1.0)] * 8)
    c.publish("hp")
    snap = c.snapshot()
    before = list(c.read(snap, "hp"))
    c.write_inactive("hp", [(100.0, 0.0)] * 8)      # a new build lands, NOT yet published
    assert list(c.read(snap, "hp")) == before, "reader saw an unpublished write"
    c.publish("hp")
    assert list(c.read(c.snapshot(), "hp")) != before


def test_v10_one_engine_rebuild_leaves_the_other_byte_identical():
    """The defect a SHARED active index causes: an HP-only rebuild flips the pair, so LP reads
    a half nobody wrote - and a later LP-only rebuild resurrects the OLD HP grid."""
    c = curve.CurveCache(n_out=4)
    c.write_inactive("hp", [(100.0, 1.0)] * 4); c.publish("hp")
    c.write_inactive("lp", [(200.0, 2.0)] * 4); c.publish("lp")
    lp_before = list(c.read(c.snapshot(), "lp"))
    for k in range(3):
        c.write_inactive("hp", [(100.0, 9.0 + k)] * 4); c.publish("hp")
        assert list(c.read(c.snapshot(), "lp")) == lp_before, "LP changed on an HP-only rebuild"
    hp_now = list(c.read(c.snapshot(), "hp"))
    c.write_inactive("lp", [(200.0, 3.0)] * 4); c.publish("lp")
    assert list(c.read(c.snapshot(), "hp")) == hp_now, "HP resurrected by an LP-only rebuild"


def test_v10_generation_moves_only_on_publish():
    c = curve.CurveCache(n_out=4)
    g0 = c.snapshot()[0]
    c.write_inactive("hp", [(100.0, 1.0)] * 4)
    assert c.snapshot()[0] == g0, "generation moved before publication"
    c.publish("hp")
    assert c.snapshot()[0] != g0


def test_v10_frame_is_discarded_when_a_grid_publishes_mid_read():
    """The reader half of the seqlock: @gfx snapshots once, draws, then re-checks. If anything
    published while it was drawing, it keeps the previous completed frame rather than showing a
    mixture of two kernels."""
    c = curve.CurveCache(n_out=4)
    c.write_inactive("hp", [(100.0, 1.0)] * 4); c.publish("hp")
    c.begin_frame()
    c.write_inactive("hp", [(100.0, 5.0)] * 4); c.publish("hp")     # lands mid-draw
    assert c.commit_frame([1.0] * 4) is False, "a torn frame was published"
    c.begin_frame()
    assert c.commit_frame([2.0] * 4) is True
    assert c.completed_trace() == [2.0] * 4


def test_v10_target_and_active_generations_are_separate():
    """act_* commits in @block and @slider may never run again afterwards, so one counter
    cannot serve both: the graph would keep showing a superseded topology."""
    c = curve.CurveCache(n_out=4)
    t0, a0 = c.gen_target, c.gen_active
    c.bump_target()
    assert c.gen_target != t0 and c.gen_active == a0
    c.bump_active()
    assert c.gen_active != a0


def test_v10_watched_fields_notice_every_single_field():
    base = dict(bands=[_band()], filters=[_hp()], phase=0, res0=0, res1=0, srate=48000)
    ref = curve.watched_fields(**base)
    for v in (dict(base, bands=[_band(enable=0)]),
              dict(base, bands=[_band(type="lowshelf")]),
              dict(base, bands=[_band(freq=1001.0)]),
              dict(base, bands=[_band(q=0.708)]),
              dict(base, bands=[_band(macro=1)]),
              dict(base, bands=[_band(micro=0.1)]),
              dict(base, bands=[_band(ratio=1.05)]),
              dict(base, bands=[_band(placement="mid")]),
              dict(base, bands=[_band(qchar=0.5)]),
              dict(base, filters=[_hp(slope=2)]),
              dict(base, filters=[_hp(freq=101.0)]),
              dict(base, filters=[_hp(res=0.5)]),
              dict(base, filters=[_hp(placement="side")]),
              dict(base, phase=1), dict(base, res0=1), dict(base, res1=1),
              dict(base, srate=96000)):
        assert curve.watched_fields(**v) != ref, v


def test_v10_watched_fields_cannot_collide_like_an_arithmetic_signature():
    """A weighted sum can merge two different configurations and leave a stale but entirely
    plausible curve on screen. A tuple snapshot cannot."""
    a = curve.watched_fields(bands=[_band(macro=1, micro=0.0)], filters=[], phase=0,
                             res0=0, res1=0, srate=48000)
    b = curve.watched_fields(bands=[_band(macro=0, micro=100.0)], filters=[], phase=0,
                             res0=0, res1=0, srate=48000)
    assert a != b, "two configurations with the same gain sum compared equal"


# ===================================================================================
# V1.1 - eight fully dynamic bands. The memory map as data.
# Spec: docs/superpowers/specs/2026-08-22-rcbitnova-v1.1-eight-dynamic-bands-design.md (rev 3)
# ===================================================================================

from tools import rcbitnova_layout as lay   # noqa: E402


def test_v11_low_map_reproduces_the_shipped_four_band_addresses():
    """The model must produce V1.0's own numbers or it is describing another plugin."""
    m = lay.low_layout(4)
    assert m["cf"][0] == 0 and m["st"][0] == 64 and m["det"][0] == 96
    assert m["dst"][0] == 128 and m["cst"][0] == 160 and m["dp"][0] == 192
    assert m["dm"][0] == 208 and m["bp"][0] == 216 and m["eg"][0] == 256


def test_v11_eight_bands_move_only_dm_and_bp():
    """Five of seven dynamic arrays keep their base - the four-band spacing was already wide
    enough. Only dm and bp are re-based, and that is the whole low-map change."""
    m = lay.low_layout(8)
    assert m["cf"] == (0, 63) and m["st"] == (64, 95)
    assert m["det"][0] == 96 and m["dst"][0] == 128 and m["cst"][0] == 160
    assert m["dp"][0] == 192 and m["eg"][0] == 256
    assert m["dm"][0] == 224 and m["bp"][0] == 232
    assert m["eg"][1] == 271


def test_v11_low_map_leaves_room_below_mb_band():
    m = lay.low_layout(8)
    end = max(hi for _, hi in m.values()) + 1
    assert end == 272
    assert 1024 - end == 752, "mb_band is a literal 1024; this is the slack the tables live in"


def test_v11_words_per_band_and_the_memory_ceiling():
    """34 words per band, not 30 - rev 1 of the spec got this wrong and inverted the conclusion.
    Thirty bands end at 1020; thirty-one at 1054, past mb_band."""
    assert sum(w for _, w in lay.LOW) == 34
    assert lay.max_bands_by_memory() == 30


def test_v11_a_ninth_band_collides_with_the_base_tables():
    """The tables are FIXED at 272..295, and low_layout(9) puts bp at 261..287 and eg at 288..305 -
    straight through all three. Rev 2 asserted check_capacity(9) == [] because the model did not
    know the tables existed. Eight is unaffected: the low map ends at 272, exactly where stb
    begins."""
    m = lay.low_layout(9)
    assert m["bp"] == (261, 287) and m["eg"] == (288, 305)
    problems = lay.check_capacity(9)
    assert any("table" in p for p in problems), problems
    assert lay.check_capacity(8) == [], "eight ends at 272 and the tables start at 272"


def test_v11_the_real_ceiling_is_not_eight():
    """Both earlier versions of "eight is the maximum" were asserted, not computed, and both were
    wrong. Memory holds 30 bands; the fixed base tables stop a ninth; the slider budget stops a
    tenth. Eight is a product decision, recorded honestly so nobody later "discovers" headroom and
    assumes it was overlooked."""
    assert max(hi for _, hi in lay.low_layout(9).values()) + 1 == 306, "memory is not the limit"
    assert lay.check_capacity(8) == []
    problems = lay.check_capacity(10)
    assert problems and any("slider" in p for p in problems), problems


def test_v11_base_tables_keep_the_old_bands_and_stay_under_256():
    t = lay.base_tables(8)
    assert t["stb"][:4] == [10, 20, 30, 40]
    assert t["dynb"][:4] == [50, 60, 70, 80]
    assert t["ceb"][:4] == [90, 100, 110, 120]
    assert t["stb"][4:] == [150, 160, 170, 180]
    assert t["dynb"][4:] == [190, 200, 210, 220]
    assert t["ceb"][4:] == [230, 234, 238, 242]      # stride 4: at 10, band 8 would hit 261
    highest = max(t["stb"][b] + 9 for b in range(8))
    highest = max(highest, max(t["dynb"][b] + 8 for b in range(8)))
    highest = max(highest, max(t["ceb"][b] + 3 for b in range(8)))
    assert highest == 245, highest


def test_v11_new_sliders_do_not_collide_with_anything_existing():
    used = set(range(1, 5)) | set(range(11, 50)) | set(range(51, 89)) \
        | set(range(91, 124)) | set(range(131, 143))
    t = lay.base_tables(8)
    new = set()
    for b in range(4, 8):
        new |= {t["stb"][b] + o for o in range(1, 10)}
        new |= {t["dynb"][b] + o for o in range(1, 9)}
        new |= {t["ceb"][b] + o for o in range(1, 4)}
    assert not (new & used), sorted(new & used)
    assert len(new) == 80


def test_v11_audio_chain_grows_exactly_as_the_spec_says():
    a, b = lay.audio_layout(4), lay.audio_layout(8)
    assert a["mb_peak"] == 17408 and b["mb_peak"] == 33792
    assert a["mb_end"] == 33792 and b["mb_end"] == 66560
    assert a["gc_trace"] == 38275, "V1.0's own comment records 38275"
    assert b["gc_trace"] == 71087


def test_v11_lp_base_moves_one_page_and_stays_aligned():
    """The single most dangerous consequence: a 32768-point FFT off a 65536-word page corrupts
    SILENTLY. Pin both values, not just the modulus."""
    four = lay.gui_layout(lay.audio_layout(4)["gc_trace"], 4)
    eight = lay.gui_layout(lay.audio_layout(8)["gc_trace"], 8)
    assert four["lp_base"] == 65536
    assert eight["lp_base"] == 131072
    assert eight["lp_base"] % 65536 == 0
    assert eight["gc_hits"] + 8 <= eight["lp_base"]


def test_v11_gui_model_reproduces_the_shipped_clear_span():
    """V1.0 clears exactly 13638 words. Derived, the span is 13646 at four bands and 13678 at
    eight - which is why the plugin must compute it rather than carry a literal."""
    base = lay.audio_layout(4)["gc_trace"]
    assert lay.gui_layout(base, 4)["clear_span"] - 8 == 13638
    assert lay.gui_layout(base, 4)["clear_span"] == 13646
    assert lay.gui_layout(lay.audio_layout(8)["gc_trace"], 8)["clear_span"] == 13678


def test_v11_three_gui_region_ends_are_distinct_and_derived():
    """Shipped V1.0, the four-band pre-flip build, and the final eight-band build are three
    different artifacts. Rev 1 of the spec mixed the first two and printed 51953 for V1.0, whose
    real end is 51913."""
    four = lay.audio_layout(4)["gc_trace"]
    eight = lay.audio_layout(8)["gc_trace"]
    assert four + 13638 == 51913                                    # shipped V1.0
    assert four + lay.gui_layout(four, 4)["clear_span"] == 51921    # pre-flip V1.1
    assert eight + lay.gui_layout(eight, 8)["clear_span"] == 84765  # final V1.1


def test_v11_all_eight_bands_access_every_array_in_bounds():
    mem = lay.GuardedMemory(lay.low_layout(8))
    for b in range(8):
        lay.model_band_access(mem, b)               # static AND dynamic: every band is equal now


def test_v11_a_ninth_band_is_rejected_by_the_instrument():
    mem = lay.GuardedMemory(lay.low_layout(8))
    with pytest.raises(AssertionError, match=r"cf\[64\] leaves its span 0\.\.63"):
        lay.model_band_access(mem, 8)


def test_v11_an_overrun_that_clears_a_guard_word_is_still_caught():
    """Ownership checking, not sentinels: cf is indexed b*8, so a wrong band jumps well past any
    single guard word."""
    mem = lay.GuardedMemory(lay.low_layout(8))
    for name, off in (("cf", 64), ("cf", 71), ("st", 32), ("dm", 8), ("bp", 24), ("eg", 16)):
        with pytest.raises(AssertionError):
            mem.write(name, off, 1.0)


def test_v11_curve_uses_the_same_bases_as_the_layout_model():
    """One source of truth. Two copies of this table is how a band ends up editing another band's
    parameter - and the JSFX transcription reads these numbers out of here."""
    t = lay.base_tables(8)
    assert curve.STB == t["stb"]
    assert curve.DYNB == t["dynb"]
    assert curve.CEB == t["ceb"]


def test_v11_curve_reads_band_five_from_the_new_range():
    assert curve.band_slider(4, 3) == 153        # B5 Freq
    assert curve.band_slider(0, 3) == 13         # B1 Freq, unchanged


def test_v11_curve_covers_all_three_slider_families():
    """Static, dynamics and ceilings are three separate blocks with three different strides above
    band 4; every read in the JSFX goes through one of them."""
    assert curve.band_slider(0, 1) == 11 and curve.band_slider(7, 1) == 181     # Enable
    assert curve.dyn_slider(0, 1) == 51 and curve.dyn_slider(7, 1) == 221       # Dyn
    assert curve.ceil_slider(0, 1) == 91 and curve.ceil_slider(7, 1) == 243     # Hard
    assert curve.ceil_slider(7, 3) == 245, \
        "the highest BAND slider; V1.2 adds only the panel state above it, at 246"


def test_v11_curve_helpers_agree_with_the_tables_for_every_band():
    for b in range(8):
        assert curve.band_slider(b, 0) == curve.STB[b]
        assert curve.dyn_slider(b, 0) == curve.DYNB[b]
        assert curve.ceil_slider(b, 0) == curve.CEB[b]


# --- V1.1 source gate -------------------------------------------------------------------------

from tools import rcbitnova_gates as gates   # noqa: E402


def _needs_projection(text=None):
    """The gate has two phases and this suite has to be right in both. Before Task 5 the source is
    still four-band and the contract is checked against a projection; after it, against the real
    text. Hard-coding project=True made sixteen tests fail the moment the count was raised."""
    text = open(gates.V12).read() if text is None else text
    return "N_BANDS = 4;" in text


def test_v11_gate_passes_on_the_clean_source():
    """THE test that has to come first. Three earlier drafts of this gate could not be satisfied
    by the very source they were written for - a row that matched nothing, a line-anchored regex
    against four entries per line, an evaluator that read `st` as a loop counter. Mutants prove
    rejection; only this proves the contract is satisfiable at all."""
    gates.check_source(gates.V12, project=_needs_projection())


def test_v11_gate_pieces_agree_on_the_table_block():
    text = open(gates.V12).read()
    assert gates.eval_init(text, ["stb", "dynb", "ceb"]) == {"stb": 272, "dynb": 280, "ceb": 288}
    assert gates.eval_init(text, ["st"])["st"] == 64, "the address block must beat the loop counter"
    gates.check_tables(text, "clean")


def test_v11_eval_init_ceils_at_and_around_a_page_boundary():
    for expr, want in [("ceil(1 / 65536) * 65536", 65536),
                       ("ceil(51913 / 65536) * 65536", 65536),
                       ("ceil(65536 / 65536) * 65536", 65536),
                       ("ceil(65537 / 65536) * 65536", 131072),
                       ("ceil(0 / 65536) * 65536", 0)]:
        assert gates.eval_init(f"x = {expr};", ["x"])["x"] == want, expr


def test_v11_eval_init_reads_every_assignment_on_a_line():
    packed = "stb = 272; dynb = 280; ceb = 288;\n"
    assert gates.eval_init(packed, ["stb", "dynb", "ceb"]) == {"stb": 272, "dynb": 280, "ceb": 288}


SEEDED_DEFECTS = [
    # fill bounds - the class the address gate is structurally blind to
    (lambda t: t.replace("loop(N_BANDS * 2, egh[i] = 1;", "loop(4 * 2, egh[i] = 1;"), "fill-egh"),
    (lambda t: t.replace("loop(N_BANDS * 2, eg[i] = 1;", "loop(4 * 2, eg[i] = 1;"), "fill-eg"),
    (lambda t: t.replace("loop(N_BANDS * 2, mbeh[i] = 1;", "loop(4 * 2, mbeh[i] = 1;"), "fill-mbeh"),
    (lambda t: t.replace("memset(st, 0, N_BANDS * 4);", "memset(st, 0, 4 * 4);"), "fill-st"),
    # runtime loops
    (lambda t: t.replace("  nbi = 0;\n  loop(nb_n,", "  nbi = 0;\n  loop(4,"),
     "sample-band-loop"),
    (lambda t: t.replace("nb_n = 0; b = 0;\nloop(N_BANDS,", "nb_n = 0; b = 0;\nloop(4,"),
     "slider-nb-list"),
    (lambda t: t.replace("loop(N_BANDS, gc_band_setup(gc_b)", "loop(4, gc_band_setup(gc_b)"),
     "gfx-band-setup"),
    (lambda t: t.replace("gc_hit_n = 0;\ngc_b = 0;\nloop(N_BANDS,",
                         "gc_hit_n = 0;\ngc_b = 0;\nloop(4,"), "gfx-hit-test"),
    # table contents
    (lambda t: t.replace("stb[6]  = 170;", "stb[6]  = 175;"), "stb[6] = 175, expected 170"),
    (lambda t: t.replace("ceb[7]  = 242;", "ceb[7]  = 260;"), "ceb[7] = 260, expected 242"),
    (lambda t: t.replace("stb[7]  = 180;\n", ""), "stb[7] is never assigned"),
    # addresses
    (lambda t: t.replace("dm  = 224;", "dm  = 208;"), "dm = 208, model says 224"),
    (lambda t: t.replace("gc_ebuf  = gc_fc + 126;", "gc_ebuf  = gc_fc + 128;"), "gc_ebuf"),
    (lambda t: t.replace("memset(gc_trace, 0, gc_hits + 8 - gc_trace);",
                         "memset(gc_trace, 0, 13678);"), "clear-derived"),
    # forbidden reads - inside an @init-declared helper, which a per-SECTION exemption would miss
    (lambda t: t.replace("  s = stb[b];                                  // slider base: 10,20,30,40",
                         "  s = 10 * (b + 1);                            // slider base: 10,20,30,40"),
     "static-slider arithmetic"),
    # writers
    (lambda t: t.replace("b == 6 ? ( slider173 = v; slider_automate(slider173); ) :",
                         "b == 6 ? ( slider175 = v; slider_automate(slider175); ) :"),
     "gc_w_freq writes sliders"),
]


@pytest.mark.parametrize("mutate,expect", SEEDED_DEFECTS)
def test_v11_gate_rejects_each_seeded_defect(tmp_path, mutate, expect):
    clean = open(gates.V12).read()
    mutated = mutate(clean)
    assert mutated != clean, f"the seeding lambda for {expect!r} changed nothing"
    src = tmp_path / "mutant"
    src.write_text(mutated)
    with pytest.raises(AssertionError) as exc:
        gates.check_source(str(src), project=_needs_projection(mutated))
    assert expect in str(exc.value), f"rejected, but for the wrong reason: {exc.value}"


# --- V1.1 migration, every branch, before REAPER ------------------------------------------------

import sys, os                                                              # noqa: E402
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))                 # noqa: E402
import _reaper_fx_fake as fake                                              # noqa: E402
from tools.migrate_v10_to_v11 import migrate_chain, N_DECLARED_V10          # noqa: E402


def _mid_chain():
    tr, rpr = fake.chain("A", "JS: RCBitNova V1.0", "B")
    return tr, rpr, fake.FakeProject(tr)


def _undo(rpr):
    return (rpr.undo_opened, rpr.undo_closed, rpr.undos)


def test_v11_migration_success_keeps_chain_position_and_balances_undo():
    tr, rpr, pr = _mid_chain()
    src = tr.fxs[1]
    for i in range(N_DECLARED_V10):
        src.params[i].normalized = i / 100.0
    src.params[N_DECLARED_V10].normalized = 0.75          # host Bypass - the one a name search skips
    src.params[N_DECLARED_V10 + 1].normalized = 0.5       # host Wet
    out = migrate_chain(tr, rpr, pr, dry_run=False)
    assert out == "migrated 95 declared + 3 host parameters", out
    assert [f.name for f in tr.fxs] == ["A", "RCBitNova V1.1", "B"], "chain order must not change"
    dst = tr.fxs[1]
    assert [dst.params[i].normalized for i in range(N_DECLARED_V10)] == \
        [i / 100.0 for i in range(N_DECLARED_V10)]
    assert dst.params[175].normalized == 0.75, "host Bypass must reach V1.1's host Bypass"
    assert dst.params[176].normalized == 0.5
    assert dst.params[95].normalized == 0.0, "B5 Enable must stay at its default"
    assert _undo(rpr) == (1, 1, 0)


def test_v11_migration_refuses_when_add_fx_returns_none():
    tr, rpr, pr = _mid_chain()
    tr.add_fx = lambda name: None
    out = migrate_chain(tr, rpr, pr, dry_run=False)
    assert out.startswith("REFUSED, source untouched"), out
    assert "add_fx returned None" in out
    assert [f.name for f in tr.fxs] == ["A", "RCBitNova V1.0", "B"]
    assert _undo(rpr) == (1, 1, 0), "opened once, closed once, even on the failure path"


def test_v11_migration_refuses_when_add_fx_raises():
    tr, rpr, pr = _mid_chain()

    def boom(name):
        raise RuntimeError("no such effect")
    tr.add_fx = boom
    out = migrate_chain(tr, rpr, pr, dry_run=False)
    assert out.startswith("REFUSED, source untouched"), out
    assert [f.name for f in tr.fxs] == ["A", "RCBitNova V1.0", "B"]
    assert _undo(rpr) == (1, 1, 0)


def test_v11_migration_rolls_back_a_readback_mismatch():
    tr, rpr, pr = _mid_chain()
    real_add = tr.add_fx

    class Stubborn:
        """A parameter that accepts a write and reports something else - which is what a
        read-back check exists to catch."""
        def __init__(self, name):
            self.name = name
            self.envelope = None

        @property
        def normalized(self):
            return 999.0

        @normalized.setter
        def normalized(self, _value):
            pass

    def add_and_break(name):
        fx = real_add(name)
        fx.params[7] = Stubborn(fx.params[7].name)
        return fx
    tr.add_fx = add_and_break
    out = migrate_chain(tr, rpr, pr, dry_run=False)
    assert "did not take" in out and out.startswith("REFUSED, source untouched"), out
    assert [f.name for f in tr.fxs] == ["A", "RCBitNova V1.0", "B"], "the orphan must be removed"
    assert _undo(rpr) == (1, 1, 0)


def test_v11_migration_rolls_back_when_the_move_lands_wrong():
    tr, rpr, pr = _mid_chain()
    rpr.TrackFX_CopyToTrack = lambda *a: None             # the move silently does nothing
    out = migrate_chain(tr, rpr, pr, dry_run=False)
    assert "move failed" in out and out.startswith("REFUSED, source untouched"), out
    assert [f.name for f in tr.fxs] == ["A", "RCBitNova V1.0", "B"]
    assert _undo(rpr) == (1, 1, 0)


def test_v11_migration_undoes_for_real_if_the_source_is_already_gone():
    tr, rpr, pr = _mid_chain()
    real_move = rpr.TrackFX_CopyToTrack

    def move_and_eat_the_source(src_tr, src_idx, dst_tr, dst_idx, is_move):
        real_move(src_tr, src_idx, dst_tr, dst_idx, is_move)
        tr.fxs[:] = [f for f in tr.fxs if "V1.0" not in f.name]
    rpr.TrackFX_CopyToTrack = move_and_eat_the_source
    out = migrate_chain(tr, rpr, pr, dry_run=False)
    assert out.startswith("FAILED after the source was removed; undone"), out
    assert _undo(rpr) == (1, 1, 1), "grouping is not rollback - a real undo must be called"


def test_v11_migration_never_deletes_an_unrelated_v11():
    tr, rpr = fake.chain("JS: RCBitNova V1.1", "JS: RCBitNova V1.0")
    pr = fake.FakeProject(tr)
    bystander = tr.fxs[0]
    rpr.TrackFX_CopyToTrack = lambda *a: None             # force the failure path
    out = migrate_chain(tr, rpr, pr, dry_run=False)
    assert out.startswith("REFUSED, source untouched"), out
    assert tr.fxs[0] is bystander, "the pre-existing V1.1 must survive"
    assert [f.name for f in tr.fxs] == ["RCBitNova V1.1", "RCBitNova V1.0"]


def test_v11_migration_refuses_an_ambiguous_chain():
    tr, rpr = fake.chain("JS: RCBitNova V1.0", "X", "JS: RCBitNova V1.0")
    out = migrate_chain(tr, rpr, fake.FakeProject(tr), dry_run=False)
    assert out == "REFUSED: 2 V1.0 instances on this track; migrate them one by one", out
    assert _undo(rpr) == (0, 0, 0), "nothing may be created before the chain is unambiguous"


@pytest.mark.parametrize("wreck,expect", [
    (lambda fx, rpr: setattr(fx.params[3], "envelope", object()), "automation"),
    (lambda fx, rpr: fx.config.__setitem__("param.3.mod.active", "1"), "parameter modulation"),
    (lambda fx, rpr: fx.pins.__setitem__((0, 1), 3), "non-default pin map"),
    (lambda fx, rpr: fx.config.__setitem__("instance_oversample_shift", "2"), "oversampling"),
])
def test_v11_migration_refuses_unmigratable_state_before_creating_anything(wreck, expect):
    tr, rpr, pr = _mid_chain()
    wreck(tr.fxs[1], rpr)
    out = migrate_chain(tr, rpr, pr, dry_run=False)
    assert out.startswith("REFUSED") and expect in out, out
    assert [f.name for f in tr.fxs] == ["A", "RCBitNova V1.0", "B"]
    assert _undo(rpr) == (0, 0, 0), "refusals happen before the undo block opens"


def test_v11_migration_dry_run_names_what_it_cannot_detect():
    tr, rpr, pr = _mid_chain()
    out = migrate_chain(tr, rpr, pr, dry_run=True)
    assert "would copy 95 declared + 3 host parameters into chain position 1" in out
    assert "aliases are not migrated" in out, "an undetected item must never read as refused"
    assert [f.name for f in tr.fxs] == ["A", "RCBitNova V1.0", "B"]


# --- V1.2 dynamics panel: the frozen parameter map -------------------------------------------

def test_v11_declared_fixture_has_the_shape_the_contract_needs():
    """REAPER stores a parameter by its POSITION in declaration order, not by name. So a version
    that inserts a parameter in the middle makes every later one read the wrong value, silently.
    This fixture records what V1.1's 175 look like, and the boundary that must never move."""
    recs = gates.load_declared(gates.DECLARED_FIXTURE)
    assert len(recs) == 175
    assert [r[0] for r in recs] == list(range(175)), "indices must be 0..174 in order"
    assert recs[0][1] == "Bypass", recs[0]
    assert recs[94][1] == "LP Resolution (Linear only)", \
        "record 94 is slider142, the last of V1.0's block - the boundary the panel must not move"
    assert recs[95][1] == "B5 Enable", \
        "record 95 is where B5 starts; a parameter inserted before it shifts eighty records"
    assert recs[174][1] == "B8 Hard Ceiling Micro (% bit)", recs[174]


def test_v11_fixture_records_carry_ranges_and_defaults_not_just_names():
    """Names alone cannot catch a changed range, step or default - two incompatible declarations
    can share a name."""
    recs = gates.load_declared(gates.DECLARED_FIXTURE)
    by_name = {r[1]: r for r in recs}
    assert by_name["B5 Soft Ceiling Macro (bits below 0)"][2:5] == (0.0, 16.0, 0.05), \
        "the 0.05 step is what makes 0.25 bits typeable; a regression here is silent"
    assert by_name["B8 Hard Ceiling Micro (% bit)"][2:5] == (-100.0, 100.0, 0.1), \
        "Micro is PERCENT of a bit, step 0.1 - not 0.001, which is the resulting bit resolution"
