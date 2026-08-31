import math

from tools import freqphaser_dsp as dsp


def test_amount_curve_has_zero_and_unity_endpoints():
    assert dsp.amount_from_bits(0.0) == 0.0
    assert dsp.amount_from_bits(1.0) == 1.0
    assert math.isclose(
        dsp.amount_from_bits(0.05),
        2.0**0.05 - 1.0,
        rel_tol=0.0,
        abs_tol=1e-15,
    )


def test_masks_are_nonnegative_and_complementary():
    cuts = (200.0, 1500.0, 7000.0, 10000.0)
    for slope in (12, 24, 48, 96):
        for k in range(16385):
            weights = dsp.band_weights(24000.0 * k / 16384.0, cuts, slope)
            assert min(weights) >= -1e-15
            assert math.isclose(sum(weights), 1.0, rel_tol=0.0, abs_tol=2e-15)


def test_phase_rotation_control_points():
    assert dsp.phase_factor(0) == 1 + 0j
    assert abs(dsp.phase_factor(90) - 1j) < 1e-15
    assert abs(dsp.phase_factor(-90) + 1j) < 1e-15
    assert abs(dsp.phase_factor(180) + 1) < 1e-15


def test_all_move_at_one_removes_all_side():
    settings = [
        dsp.BandSetting(1.0, phase, True)
        for phase in (-30.0, 0.0, 45.0, 90.0, 180.0)
    ]
    injection, removal = dsp.transfer_at(
        8000.0,
        (200.0, 1500.0, 7000.0, 10000.0),
        24,
        settings,
    )
    assert math.isclose(removal, 1.0, rel_tol=0.0, abs_tol=2e-15)
    assert isinstance(injection, complex)
