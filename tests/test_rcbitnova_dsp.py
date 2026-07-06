import math
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
