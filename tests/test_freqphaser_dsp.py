import cmath
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
    assert layout.top == 978944
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


def test_single_host_crossover_edit_clamps_only_that_crossover():
    previous = (200.0, 1500.0, 7000.0, 10000.0)
    cuts = dsp.sanitize_cuts(
        (9000.0, 1500.0, 7000.0, 10000.0),
        sample_rate=48000.0,
        slope_db_oct=24.0,
        size=32768,
        previous=previous,
    )
    assert cuts[1:] == previous[1:]
    assert cuts[0] < cuts[1]


def test_zero_kernel_changes_do_not_arm_empty_rebuilds():
    assert not dsp.kernel_rebuild_needed(
        bits=(0.0,) * 5,
        listen_band=-1,
        active_injection=False,
        active_removal=False,
        target_injection=False,
        target_removal=False,
        kernel_valid=True,
        kernel_changed=False,
    )
    assert dsp.kernel_rebuild_needed(
        bits=(0.0, 0.0, 0.05, 0.0, 0.0),
        listen_band=-1,
        active_injection=False,
        active_removal=False,
        target_injection=False,
        target_removal=False,
        kernel_valid=True,
        kernel_changed=True,
    )


def test_route_only_change_does_not_rebuild_existing_kernel():
    assert not dsp.kernel_rebuild_needed(
        bits=(0.5, 0.0, 0.0, 0.0, 0.0),
        listen_band=-1,
        active_injection=True,
        active_removal=False,
        target_injection=True,
        target_removal=False,
        kernel_valid=True,
        kernel_changed=False,
    )
    assert dsp.kernel_rebuild_needed(
        bits=(0.5, 0.0, 0.0, 0.0, 0.0),
        listen_band=-1,
        active_injection=True,
        active_removal=False,
        target_injection=True,
        target_removal=False,
        kernel_valid=True,
        kernel_changed=True,
    )


def test_first_nonzero_kernel_builds_without_zero_bank_fade():
    assert dsp.kernel_rebuild_needed(
        bits=(0.0, 0.0, 0.0, 1.0, 0.0),
        listen_band=-1,
        active_injection=False,
        active_removal=False,
        target_injection=False,
        target_removal=False,
        kernel_valid=False,
        kernel_changed=True,
    )


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


def test_kernel_transition_queues_latest_request():
    state = dsp.KernelTransition(current="A", length=100)
    state.request("B")
    assert state.fading and state.target == "B"
    state.advance(40)
    state.request("C")
    state.request("D")
    assert state.pending == "D"
    state.advance(60)
    assert state.current == "B"
    assert state.fading and state.target == "D" and state.position == 0
    state.advance(100)
    assert state.current == "D" and not state.fading


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


def test_freqphaser_realtime_and_neutral_paths_are_guarded():
    gates.assert_realtime_safety(PLUGIN.read_text())


# ---------------------------------------------------------------- V1.1 Width

PLUGIN_11 = Path("JSFX/Freqphaser 1.1")


def test_side_gain_follows_the_rcbitrangegain_formula():
    # shift = 2 ^ ((Macro + Micro*0.01) * BitRatio)
    assert dsp.side_gain(0, 0.0, 1.0) == 1.0
    assert dsp.side_gain(1, 0.0, 1.0) == 2.0
    assert dsp.side_gain(-1, 0.0, 1.0) == 0.5
    assert math.isclose(dsp.side_gain(1, 0.0, 0.25), 2.0**0.25, abs_tol=1e-15)
    assert math.isclose(dsp.side_gain(0, 50.0, 1.0), 2.0**0.5, abs_tol=1e-15)


def test_fold_alone_transfers_all_side_at_ninety_degrees():
    settings = [dsp.BandSetting(0.0, 0.0, False)] * 5
    for freq in (80.0, 900.0, 5000.0, 15000.0):
        injection, removal = dsp.transfer_at(
            freq, (200.0, 1500.0, 7000.0, 10000.0), 24, settings, fold_bits=1.0
        )
        assert math.isclose(injection.real, 0.0, abs_tol=1e-15)
        assert math.isclose(injection.imag, 1.0, abs_tol=1e-15)
        assert math.isclose(removal, 1.0, abs_tol=1e-15)


def test_fold_and_band_move_share_one_side_budget():
    # Band 4 Move at 1 bit plus Fold at 1 bit would remove more Side than exists.
    settings = [dsp.BandSetting(0.0, 0.0, False)] * 5
    settings[3] = dsp.BandSetting(1.0, 0.0, True)
    _, removal = dsp.transfer_at(
        8000.0, (200.0, 1500.0, 7000.0, 10000.0), 24, settings, fold_bits=1.0
    )
    assert removal <= 1.0 + 1e-15, removal
    assert math.isclose(removal, 1.0, abs_tol=1e-15)


def test_realized_fold_kernel_is_unity_at_ninety_degrees():
    """The windowed FIR the plugin actually builds, not just the ideal spectrum."""
    size = 4096
    settings = [dsp.BandSetting(0.0, 0.0, False)] * 5
    injection, _ = dsp.build_transfer_spectra(
        size, 48000.0, (200.0, 1500.0, 7000.0, 10000.0), 24, settings, fold_bits=1.0
    )
    realized = dsp.realize_kernel(injection)
    for k in range(40, size // 2 - 40):
        assert math.isclose(abs(realized[k]), 1.0, abs_tol=1e-6), (k, abs(realized[k]))
        assert math.isclose(
            math.degrees(cmath.phase(realized[k])), 90.0, abs_tol=1e-3
        ), (k, math.degrees(cmath.phase(realized[k])))


def test_freqphaser_11_declares_width_above_every_existing_slider():
    source = PLUGIN_11.read_text()
    gates.assert_width_manifest(source)
    gates.assert_distinct_desc(source)


def test_freqphaser_11_keeps_every_v10_engine_invariant():
    """1.1 is a superset of 1.0: Width must not regress the proven engine."""
    source = PLUGIN_11.read_text()
    gates.assert_page_safe_layout(source)
    gates.assert_no_nested_ternary_compound_assignments(source)
    gates.assert_dsp_structure(source)
    gates.assert_transition_structure(source)
    gates.assert_gui_structure(source)
    gates.assert_realtime_safety(source)


def _decode_lr(fold_bits, phase_deg, freq=4000.0):
    """Run Side-only material through both convolutions and decode L/R."""
    design_size, latency = 32768, 18432
    cuts, slope = (200.0, 1500.0, 7000.0, 10000.0), 24
    if phase_deg is None:  # the real Width fold: fixed +90 degrees
        settings = [dsp.BandSetting(0.0, 0.0, False)] * 5
        kwargs = {"fold_bits": fold_bits}
    else:  # a broadband band-Move at an arbitrary phase, for contrast
        settings = [dsp.BandSetting(fold_bits, phase_deg, True)] * 5
        kwargs = {}
    injection, removal = dsp.build_transfer_spectra(
        design_size, 48000.0, cuts, slope, settings, **kwargs
    )
    n = latency + 4096
    side = [math.sin(2 * math.pi * freq * i / 48000.0) for i in range(n)]
    inj = dsp.simulate_engine(side, injection)
    rem = dsp.simulate_engine(side, removal)
    # Mid is silent (Side-only input); dry Side is latency-matched.
    window = range(latency + 512, latency + 3584)
    left, right, dry = [], [], []
    for i in window:
        mid_out = inj[i]
        side_out = side[i - latency] - rem[i]
        left.append(mid_out + side_out)
        right.append(mid_out - side_out)
        dry.append(side[i - latency])
    return left, right, dry


def _rms(values):
    return math.sqrt(sum(v * v for v in values) / len(values))


def test_partial_fold_keeps_the_channels_balanced():
    """Width must narrow the image, not slide it sideways.

    At a partial fold the quadrature copy is orthogonal to the surviving Side,
    so L and R keep equal energy and the image stays centred.
    """
    bits = math.log2(1.5)  # amount = 2^bits - 1 = 0.5, half the Side folded
    left, right, dry = _decode_lr(bits, None)
    assert _rms(dry) > 0.6  # the source really was Side-only
    assert abs(_rms(left) - _rms(right)) / _rms(left) < 0.02

    mono = [(a + b) * 0.5 for a, b in zip(left, right, strict=True)]
    assert _rms(mono) > 0.3  # Side-only material now survives a mono sum


def test_a_real_coefficient_fold_slides_the_image_sideways():
    """Why the fold is fixed at +90 degrees, locked in as a regression.

    At 0 degrees L keeps the whole signal while R is drained, so a half fold is
    a pan, not a narrowing.  (At a full fold 0 degrees happens to be symmetric
    again - the damage is in between, which is where the control lives.)
    """
    bits = math.log2(1.5)
    left, right, dry = _decode_lr(bits, 0.0)
    assert abs(_rms(left) - _rms(dry)) / _rms(dry) < 0.02  # L untouched
    assert _rms(right) < 0.05 * _rms(left)                 # R drained


def test_full_fold_moves_all_side_into_the_centre():
    left, right, _ = _decode_lr(1.0, None)
    assert max(abs(a - b) for a, b in zip(left, right, strict=True)) < 0.001
    mono = [(a + b) * 0.5 for a, b in zip(left, right, strict=True)]
    assert max(abs(v) for v in mono) > 0.97
