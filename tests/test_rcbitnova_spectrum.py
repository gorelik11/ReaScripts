"""Task 8 of docs/superpowers/plans/2026-09-24-rcbitnova-v16-analyzer.md.

The analyser's arithmetic, asserted here so the live matrix only has to agree with it at a
couple of points rather than judge a picture by eye.
"""
import math

import pytest

from tools.rcbitnova_spectrum import (FLOOR_BITS, apply_tilt, column_freqs, magnitudes, hann,
                                      red_state, smooth3, to_columns)

SR, FFT_N, PX, FMIN, FMAX = 96000, 8192, 900, 20.0, 24000.0
WIN = hann(FFT_N)


def _tone(freq, n=FFT_N, amp=0.5, sr=SR):
    return [amp * math.sin(2 * math.pi * freq * i / sr) for i in range(n)]


def _col_of(freq, px_n=PX):
    return math.log(freq / FMIN) / math.log(FMAX / FMIN) * (px_n - 1)


def _cols(sig, sr=SR, px_n=PX):
    return to_columns(magnitudes(sig, FFT_N, WIN), sr, px_n, FMIN, FMAX, FFT_N)


# ---- amplitude, in bits ----

def test_a_full_scale_sine_reads_zero_bits():
    assert abs(max(_cols(_tone(1000.0, amp=1.0)))) < 0.35


def test_half_amplitude_reads_minus_one_bit():
    assert abs(max(_cols(_tone(1000.0, amp=0.5))) - (-1.0)) < 0.35


def test_halving_the_amplitude_costs_exactly_one_bit():
    a = max(_cols(_tone(1000.0, amp=0.5)))
    b = max(_cols(_tone(1000.0, amp=0.25)))
    assert abs((a - b) - 1.0) < 0.05


def test_silence_sits_on_the_floor():
    assert _cols([0.0] * FFT_N) == [FLOOR_BITS] * PX


# ---- frequency placement ----

def test_a_tone_lands_on_its_own_column():
    cols = _cols(_tone(1000.0))
    peak = max(range(PX), key=lambda i: cols[i])
    assert abs(peak - _col_of(1000.0)) <= 1.0


# BELOW ~1.5 kHz THE DISPLAY CANNOT RESOLVE TO A COLUMN, and no implementation can change that.
# A column near 50 Hz is about 0.4 Hz wide while an 8192-point bin at 96 kHz is 11.7 Hz, so some
# thirty columns interpolate between the SAME pair of bins and the peak necessarily sits at a bin
# centre. The first version of these tests asserted column accuracy everywhere and failed for that
# reason - the expectation was wrong, not the code. Accuracy is therefore asserted in Hz, against
# the bin width, which is the real limit.
BIN_HZ = SR / FFT_N


@pytest.mark.parametrize("freq", [50.0, 200.0, 1000.0, 5000.0, 15000.0])
def test_tones_across_the_range_land_within_one_bin(freq):
    cols = _cols(_tone(freq))
    peak = max(range(PX), key=lambda i: cols[i])
    f_peak = column_freqs(PX, FMIN, FMAX)[peak]
    tol = max(1.2 * BIN_HZ, 2.0 * freq * (math.log(FMAX / FMIN) / (PX - 1)))
    assert abs(f_peak - freq) <= tol, (
        f"{freq} Hz peaked at column {peak} = {f_peak:.1f} Hz (tolerance {tol:.1f} Hz)")


def test_a_tone_between_two_columns_peaks_on_one_of_them():
    # only meaningful where columns are WIDER than bins, i.e. above about 1.5 kHz; column 800 is
    # around 11 kHz, where several bins fall inside one column and the maximum branch runs
    f = FMIN * (FMAX / FMIN) ** (800.5 / (PX - 1))
    cols = _cols(_tone(f))
    peak = max(range(PX), key=lambda i: cols[i])
    assert peak in (800, 801), f"{f:.1f} Hz peaked at column {peak}"


def test_the_column_grid_is_finer_than_the_bin_grid_only_below_about_1500_hz():
    # the crossover the two tests above depend on, pinned so it cannot drift silently
    edges = column_freqs(PX, FMIN, FMAX)
    widths_hz = [edges[i + 1] - edges[i] for i in range(PX - 1)]
    cross = next(i for i, w in enumerate(widths_hz) if w >= BIN_HZ)
    assert 1200.0 < edges[cross] < 1800.0, f"crossover at {edges[cross]:.0f} Hz"


# ---- the two binning branches ----

def test_the_low_end_interpolates_and_the_high_end_takes_a_maximum():
    # which branch a column uses is decided by b1 - b0; check the crossover really is where the
    # design says, or the prose and the code can drift apart unnoticed
    edges = column_freqs(PX, FMIN, FMAX)
    widths = [(edges[i + 1] - edges[i]) * FFT_N / SR for i in range(PX - 1)]
    assert widths[0] < 1.0, "the bottom of the range must interpolate"
    assert widths[-1] > 1.0, "the top of the range must take a maximum"


def test_a_narrow_peak_between_bins_survives_the_high_end():
    # the reason the high end takes a maximum rather than a mean: one loud bin among many quiet
    # ones must still read loud
    mags = [1e-9] * (FFT_N // 2)
    f = 15000.0
    mags[int(round(f * FFT_N / SR))] = 1.0
    cols = to_columns(mags, SR, PX, FMIN, FMAX, FFT_N)
    assert max(cols) > -0.5
    assert abs(max(range(PX), key=lambda i: cols[i]) - _col_of(f)) <= 1.5


# ---- the edges ----

def test_columns_at_or_above_nyquist_read_the_floor():
    cols = _cols(_tone(1000.0, sr=44100), sr=44100)
    first_dead = next(i for i, f in enumerate(column_freqs(PX, FMIN, FMAX)) if f >= 22050.0)
    assert all(c == FLOOR_BITS for c in cols[first_dead:])


def test_nyquist_is_not_the_last_bin_repeated():
    # the obvious clamp would paint the 22.05-24 kHz region with the top real bin, in exactly the
    # octave this plugin's FIR Brick is judged by
    cols = _cols(_tone(20000.0, sr=44100), sr=44100)
    first_dead = next(i for i, f in enumerate(column_freqs(PX, FMIN, FMAX)) if f >= 22050.0)
    assert cols[first_dead] == FLOOR_BITS
    assert max(cols[:first_dead]) > -3.0        # the tone itself is still there


def test_the_low_edge_clamps_the_index_before_the_fraction():
    # at 192 kHz, 20 Hz is bin 0.853; a fraction computed before the clamp interpolates the wrong
    # pair and the first column jumps
    cols = _cols(_tone(100.0, sr=192000), sr=192000)
    assert cols[0] <= cols[1] + 6.0


def test_no_column_reads_below_the_floor():
    cols = _cols(_tone(1000.0, amp=1e-6))
    assert min(cols) >= FLOOR_BITS


# ---- tilt ----

def test_tilt_is_zero_at_1k_and_exact_one_octave_up():
    t = apply_tilt([0.0] * PX, SR, PX, FMIN, FMAX, 6.020599913)
    assert abs(t[int(round(_col_of(1000.0)))]) < 0.02
    assert abs(t[int(round(_col_of(2000.0)))] - 1.0) < 0.02


def test_zero_tilt_changes_nothing():
    c = [float(i % 5) for i in range(PX)]
    assert apply_tilt(c, SR, PX, FMIN, FMAX, 0) == c


def test_tilt_cancels_out_of_a_mid_side_comparison():
    # the red rule is tilt-independent by construction; this pins it
    mid = [float(i % 7) for i in range(PX)]
    side = [m + 0.5 for m in mid]
    tm = apply_tilt(mid, SR, PX, FMIN, FMAX, 4.5)
    ts = apply_tilt(side, SR, PX, FMIN, FMAX, 4.5)
    assert [round(b - a, 9) for a, b in zip(tm, ts)] == [0.5] * PX


# ---- smoothing ----

def test_smoothing_preserves_length_and_leaves_the_ends_alone():
    c = [float(i % 7) for i in range(PX)]
    s = smooth3(c, passes=2)
    assert len(s) == PX and s[0] == c[0] and s[-1] == c[-1]


def test_smoothing_uses_the_unsmoothed_left_neighbour():
    # a 3-tap pass that feeds its own output back reads as a much heavier filter; the reference
    # keeps the previous ORIGINAL value, which is what `prev = cur` does
    c = [0.0, 0.0, 1.0, 0.0, 0.0]
    s = smooth3(c, passes=1)
    assert s[1] == pytest.approx(0.25)
    assert s[2] == pytest.approx(0.5)
    assert s[3] == pytest.approx(0.25)


def test_smoothing_conserves_a_flat_line():
    assert smooth3([3.0] * 20, passes=2) == pytest.approx([3.0] * 20)


# ---- the red rule ----

def test_red_needs_the_floor():
    mid, side = [-30.0] * 4, [-25.0] * 4        # side is louder, but both are near the bottom
    assert red_state(mid, side, [0] * 4) == [0, 0, 0, 0]


def test_red_turns_on_warm_then_bright_and_holds_through_hysteresis():
    mid = [-10.0] * 4
    side = [-10.05, -9.8, -8.5, -10.05]
    assert red_state(mid, side, [0, 0, 0, 1]) == [0, 1, 2, 1]


def test_red_releases_once_side_drops_a_clear_tenth_of_a_bit():
    assert red_state([-10.0], [-10.2], [1]) == [0]
    assert red_state([-10.0], [-10.05], [1]) == [1]      # inside the hysteresis, still red


def test_mono_never_goes_red():
    # a mono source has Side at the arithmetic floor; no column may colour at any level
    mid = [-3.0] * PX
    side = [FLOOR_BITS] * PX
    assert red_state(mid, side, [0] * PX) == [0] * PX


def test_anti_phase_goes_red_everywhere_it_is_audible():
    mid = [-40.0] * PX                           # below the floor gate
    side = [-2.0] * PX
    st = red_state(mid, side, [0] * PX)
    assert st == [2] * PX                        # side is more than a bit above mid, and audible
