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
    assert span(8192) == 229376
    assert span(16384) == 360448
    assert span(32768) == 655360


def test_packed_normal_pair_matches_v06_footprint():
    l0, l1 = dsp.lp_packed_layouts(0, 8192, 8192, 2048)
    assert l1["__top"] == 458752          # byte-identical to V0.6
    assert dsp.page_layout_ok(l0, 8192, 2048)
    assert dsp.page_layout_ok(l1, 8192, 2048)


def test_packed_layouts_all_four_combinations():
    expect = {(8192, 8192): 458752, (32768, 8192): 884736,
              (8192, 32768): 917504, (32768, 32768): 1310720}
    for (b0, b1), top in expect.items():
        l0, l1 = dsp.lp_packed_layouts(0, b0, b1, 2048)
        assert l1["__top"] == top, f"({b0},{b1}) top {l1['__top']} != {top}"
        assert dsp.page_layout_ok(l0, b0, 2048)
        assert dsp.page_layout_ok(l1, b1, 2048)


def test_hires_desbuf_page_aligned_even_when_engine_base_is_not():
    # engine 1 packed after a Normal engine 0 starts at 229376 (not page-aligned);
    # a High desbuf spans one full page so the layout must push it to 262144.
    l0, l1 = dsp.lp_packed_layouts(0, 8192, 32768, 2048)
    assert l1["desbuf"] % 65536 == 0
    assert l1["desbuf"] == 262144


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
