import math
from pathlib import Path

from tools import freqphaser_dsp as dsp
from tools import freqphaser_gates as gates


PLUGIN = Path("JSFX/Freqphaser 1.0")


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


def test_transfer_spectra_are_conjugate_symmetric():
    settings = [
        dsp.BandSetting(0.5, phase, index % 2 == 0)
        for index, phase in enumerate((0.0, 30.0, -90.0, 150.0, 180.0))
    ]
    injection, removal = dsp.build_transfer_spectra(
        1024,
        48000.0,
        (200.0, 1500.0, 7000.0, 10000.0),
        24,
        settings,
    )
    for k in (1, 17, 200, 500):
        assert injection[-k] == injection[k].conjugate()
        assert removal[-k] == removal[k].conjugate()
    assert injection[0].imag == 0.0
    assert injection[512].imag == 0.0


def test_engine_layout_is_page_safe_and_reports_high_resolution_latency():
    layout = dsp.engine_layout(32768, 2048, outputs=2, targets=True)
    assert layout.latency == 18432
    for start, span in layout.fft_spans:
        assert start // 65536 == (start + span - 1) // 65536


def test_partitioned_convolution_adds_one_hop_of_runtime_latency():
    signal = [1.0] + [0.0] * 47
    kernel = [0.0] * 16
    kernel[8] = 1.0
    output = dsp.partitioned_convolve(signal, kernel, 4)
    peak = max(range(len(output)), key=lambda index: abs(output[index]))
    assert peak == 12
    assert output[peak] == 1.0


def test_full_resolution_identity_peak_is_at_reported_latency():
    kernel = [0.0] * 32768
    kernel[16384] = 1.0
    signal = [1.0] + [0.0] * 18440
    output = dsp.partitioned_convolve(signal, kernel, 2048)
    peak = max(range(len(output)), key=lambda index: abs(output[index]))
    assert peak == 18432
    assert math.isclose(output[peak], 1.0, rel_tol=0.0, abs_tol=1e-12)


def test_kernel_realization_preserves_unity_move_sum():
    spectrum = [1 + 0j] * 32768
    _, realized = dsp.realize_spectrum(spectrum, beta=14.0)
    assert max(abs(abs(value) - 1.0) for value in realized) < 1e-8


def test_crossovers_are_sanitized_at_kernel_boundary():
    cuts = dsp.sanitize_cuts(
        (200.0, 1500.0, 500.0, float("nan")),
        sample_rate=192000.0,
        slope_db_oct=96.0,
        size=32768,
    )
    minimum_step = dsp.minimum_crossover_step(192000.0, 96.0, 32768)
    assert all(math.isfinite(value) for value in cuts)
    assert cuts[0] >= max(20.0, minimum_step)
    assert all(b - a >= minimum_step for a, b in zip(cuts, cuts[1:]))
    assert cuts[-1] <= 20000.0
    weights = dsp.band_weights(700.0, cuts, 96.0)
    assert min(weights) >= -1e-15


def test_freqphaser_slider_manifest_is_exact():
    gates.assert_slider_manifest(PLUGIN.read_text())


def test_freqphaser_layout_and_eel2_source_are_safe():
    source = PLUGIN.read_text()
    gates.assert_page_safe_layout(source)
    gates.assert_no_nested_ternary_compound_assignments(source)


def test_freqphaser_dsp_structure_uses_shared_side_fdl():
    gates.assert_dsp_structure(PLUGIN.read_text())


def test_crossfade_is_50_ms_at_common_sample_rates():
    for sample_rate in (44100, 48000, 88200, 96000):
        length = dsp.crossfade_length(sample_rate)
        assert length == math.floor(sample_rate * 0.05)
        assert dsp.crossfade_alpha(0, length) == 0.0
        assert dsp.crossfade_alpha(length, length) == 1.0


def test_listen_selection_and_monitoring_priority():
    assert dsp.selected_listen_band((False, True, True, False, False)) == 1
    assert dsp.selected_listen_band((False,) * 5) == -1
    assert dsp.monitor_route(listen_band=3, mono_check=True) == "listen"
    assert dsp.monitor_route(listen_band=-1, mono_check=True) == "mono"
    assert dsp.monitor_route(listen_band=-1, mono_check=False) == "stereo"


def test_freqphaser_transitions_are_dual_kernel_and_queued():
    gates.assert_transition_structure(PLUGIN.read_text())


def test_freqphaser_gui_has_exact_controls_and_writers():
    gates.assert_gui_structure(PLUGIN.read_text())
