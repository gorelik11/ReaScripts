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
