"""Static verification gates for Freqphaser 1.0."""

from __future__ import annotations

import re

from tools import freqphaser_dsp as dsp


_EXPECTED_SLIDERS = {
    1: ("200", "20,20000,1", "-Crossover 1 (Hz)"),
    2: ("1500", "20,20000,1", "-Crossover 2 (Hz)"),
    3: ("7000", "20,20000,1", "-Crossover 3 (Hz)"),
    4: ("10000", "20,20000,1", "-Crossover 4 (Hz)"),
    5: ("1", "0,3,1{12,24,48,96}", "-Slope (dB/oct)"),
    6: ("0", "0,1,1{Off,On}", "-Mono Check"),
}

for band, base in enumerate((10, 20, 30, 40, 50), start=1):
    _EXPECTED_SLIDERS[base + 1] = ("0", "0,1,0.05", f"-B{band} Amount (bit)")
    _EXPECTED_SLIDERS[base + 2] = ("0", "-180,180,1", f"-B{band} Phase (deg)")
    _EXPECTED_SLIDERS[base + 3] = ("0", "0,1,1{Add,Move}", f"-B{band} Mode")
    _EXPECTED_SLIDERS[base + 4] = ("0", "0,1,1{Off,On}", f"-B{band} Listen")


def _slider_records(source: str) -> dict[int, tuple[str, str, str]]:
    records: dict[int, tuple[str, str, str]] = {}
    pattern = re.compile(r"^slider(\d+):([^<]+)<([^>]+)>(.*)$", re.MULTILINE)
    for match in pattern.finditer(source):
        records[int(match.group(1))] = (
            match.group(2),
            match.group(3),
            match.group(4),
        )
    return records


def assert_slider_manifest(source: str) -> None:
    records = _slider_records(source)
    assert records == _EXPECTED_SLIDERS, (records, _EXPECTED_SLIDERS)
    assert "Output Trim" not in source


def assert_page_safe_layout(source: str) -> None:
    for token in (
        "FP_BD = 32768;",
        "FP_P = 2048;",
        "FP_B = 4096;",
        "FP_KMAX = 16;",
        "FP_LATENCY = 18432;",
    ):
        assert token in source
    layout = dsp.engine_layout(32768, 2048, outputs=2, targets=True)
    assert layout.latency == 18432
    for start, span in layout.fft_spans:
        assert start // 65536 == (start + span - 1) // 65536


def assert_no_nested_ternary_compound_assignments(source: str) -> None:
    dangerous = re.compile(
        r"\?\s*\([^)]*\?[^)]*(?:\+=|-=|\*=|/=)[^)]*\)\s*:",
        re.DOTALL,
    )
    assert dangerous.search(source) is None


def assert_dsp_structure(source: str) -> None:
    """Keep the first audio engine structurally aligned with the approved design."""
    for token in (
        "function fp_layout",
        "function fp_build_kernels",
        "function fp_run_hop",
        "function fp_process",
        "function fp_publish_pdc",
        "fp_fdl",
        "fp_hinj_active",
        "fp_hinj_target",
        "fp_hrem_active",
        "fp_hrem_target",
        "pow(2, bits) - 1",
        "function fp_sanitize_cuts",
        "function fp_finite",
    ):
        assert token in source, token

    # Side is analysed once per runtime hop; kernel partition FFTs are offline builds.
    run_hop = source.split("function fp_run_hop", 1)[1].split(
        "function fp_process", 1
    )[0]
    assert run_hop.count("fft(fp_fftw, FP_B)") == 1
    assert run_hop.count("memcpy(fp_fdl + fp_fdl_write") == 1
    build = source.split("function fp_build_kernels", 1)[1].split(
        "function fp_convolve_bank", 1
    )[0]
    assert "fp_sanitize_cuts();" in build


def assert_transition_structure(source: str) -> None:
    for token in (
        "fp_fading",
        "fp_fade_pos",
        "fp_fade_len",
        "function fp_commit_targets",
        "fp_dirty && !fp_fading",
        "fp_route_fading",
        "fp_route_pending",
    ):
        assert token in source, token

    assert "floor(srate * 0.05)" in source
    assert "fp_convolve_bank(fp_hinj_target" in source
    assert "fp_convolve_bank(fp_hrem_target" in source


def assert_gui_structure(source: str) -> None:
    window = re.search(r"^@gfx (\d+) (\d+)$", source, re.MULTILINE)
    assert window is not None, "no @gfx size line"
    assert int(window.group(1)) == 900, window.group(0)
    assert int(window.group(2)) >= 620, window.group(0)

    for token in (
        "gfx_ext_retina",
        "function fp_freq_to_x",
        "function fp_x_to_freq",
        "function fp_draw_knob",
        "function fp_gui_write_cut",
        "function fp_gui_write_amount",
        "function fp_gui_write_phase",
        "function fp_gui_write_listen",
        "slider_automate(slider1)",
        "slider_automate(slider11)",
        "slider_automate(slider12)",
        "gfx_getchar()",
        "(fp_drag_y-mouse_y)*0.005",
        "floor(value / 0.05 + 0.5) * 0.05",
        "floor(value + 0.5)",
    ):
        assert token in source, token

    # A drag press must never be treated as a second click and reset to zero.
    # That made a quick follow-up downward drag start from the lower clamp, so
    # the Amount knobs appeared to move only upward.
    assert "fp_double_click" not in source

    for slider in (14, 24, 34, 44, 54):
        assert f"slider{slider} = 0" in source


def assert_realtime_safety(source: str) -> None:
    for token in (
        "fp_rem_spectrum",
        "fp_build_clock",
        "FP_REBUILD_INTERVAL",
        "fp_active_injection_needed",
        "fp_active_removal_needed",
        "function fp_zero_output",
        "fp_dry_left",
        "fp_dry_right",
        "fp_neutral",
        "fp_last_cuts",
        "fp_last_bits",
        "fp_last_phase",
        "fp_last_move",
        "fp_last_listen",
        "fp_last_slope",
        "fp_last_mono",
        "function fp_sanitize_discrete",
        "function fp_arm_kernel_change",
        "function fp_kernel_signature_changed",
        "function fp_save_built_signature",
        "fp_built_cuts",
        "fp_built_bits",
        "fp_built_phase",
        "fp_built_move",
        "fp_finite(fp_left)",
        "fp_finite(fp_injection)",
        "function fp_gui_cut_bounds",
    ):
        assert token in source, token

    # Both design FFT buffers must be explicitly allocated and page-aligned.
    layout = source.split("function fp_layout", 1)[1].split(
        "function fp_i0", 1
    )[0]
    assert "p = fp_align(base, FP_BD * 2);" in layout
    assert "p = fp_align(p, FP_BD * 2);" in layout
    assert "fp_desbuf = p; p += FP_BD * 2;" in layout
    assert "fp_rem_spectrum = p; p += FP_BD * 2;" in layout
    assert "fp_accum = p; p += FP_PB2;" in layout
    assert "fp_accum_r" not in layout

    # EEL2 rejects C-style scientific numeric literals (for example 1e-30).
    executable = "\n".join(line.split("//", 1)[0] for line in source.splitlines())
    scientific = re.compile(r"(?<![A-Za-z0-9_])\d+(?:\.\d+)?[eE][+-]?\d+")
    assert scientific.search(executable) is None
    assert "FP_FINITE_LIMIT = pow(2, 300);" in source

    # EEL2 identifiers are case-insensitive.  A GUI counter named fp_b therefore
    # overwrites the DSP constant FP_B and silently changes the FFT size.
    assert re.search(r"\bfp_b\b", executable) is None


_EXPECTED_WIDTH_SLIDERS = {
    61: ("0", "0,1,0.05", "-Width Fold (bit)"),
    62: ("0", "-16,16,1", "-Side Macro Shift (bit)"),
    63: ("0", "-100,100,0.000001", "-Side Micro Shift (% of a bit)"),
    64: ("1", "0,3,0.25", "-Side Bit Ratio"),
}


def assert_distinct_desc(source: str, version: str = "1.1") -> None:
    """REAPER identifies a JSFX by its desc line, NOT by its filename.

    A new version left with the old desc is invisible: the FX browser shows
    nothing new and TrackFX_AddByName fuzzy-matches back to the old plugin,
    reporting the right parameter count and no error.
    """

    desc = next(
        line for line in source.splitlines() if line.startswith("desc:")
    )
    assert f"Freqphaser {version} -" in desc, desc
    assert "Freqphaser 1.0 -" not in desc, desc


def assert_width_manifest(
    source: str, band_modes: str = "0,1,1{Add,Move}", band_mode_default: str = "0"
) -> None:
    records = _slider_records(source)

    # Every band slider keeps its exact declaration.  A Mode slider may only
    # widen its range in place: same number, same default, same name.
    expected_sliders = dict(_EXPECTED_SLIDERS)
    for band, base in enumerate((10, 20, 30, 40, 50), start=1):
        expected_sliders[base + 3] = (band_mode_default, band_modes, f"-B{band} Mode")
    for number, expected in expected_sliders.items():
        assert records[number] == expected, (number, records.get(number), expected)

    for number, expected in _EXPECTED_WIDTH_SLIDERS.items():
        assert records[number] == expected, (number, records.get(number), expected)

    # REAPER orders FX parameters by slider NUMBER, not by position in the file.
    # A new parameter numbered among the existing ones shifts every higher
    # parameter down by one, silently breaking saved projects that address
    # parameters by position.
    assert min(_EXPECTED_WIDTH_SLIDERS) > max(_EXPECTED_SLIDERS), (
        min(_EXPECTED_WIDTH_SLIDERS),
        max(_EXPECTED_SLIDERS),
    )
    assert set(records) == set(_EXPECTED_SLIDERS) | set(_EXPECTED_WIDTH_SLIDERS)
    assert "Output Trim" not in source

    # The fold rides the existing combined kernel: +90 degrees means it adds to
    # the imaginary part only, and it shares the Side budget with per-band Move.
    transfer = source.split("function fp_transfer", 1)[1].split(
        "function fp_partition_kernel", 1
    )[0]
    assert "fp_ti += fp_fold_amount;" in transfer
    assert "fp_rr += fp_fold_amount;" in transfer
    assert "fp_rr > 1 ? fp_rr = 1;" in transfer

    # The Side Gain is a plain M/S gain and must never reach the kernel builder.
    build = source.split("function fp_build_kernels", 1)[1].split(
        "function fp_convolve_bank", 1
    )[0]
    for token in ("fp_side_gain", "fp_side_macro", "fp_side_micro", "fp_side_ratio"):
        assert token not in build, token
    assert "(fp_side_delayed - fp_removal) * fp_side_gain_current" in source

    # Width is reachable from the custom GUI, not only the generic parameter list.
    for token in (
        "function fp_gui_write_fold",
        "function fp_gui_write_side_macro",
        "function fp_gui_write_side_micro",
        "function fp_gui_write_side_ratio",
        "slider_automate(slider61)",
        "slider_automate(slider62)",
        "slider_automate(slider63)",
        "slider_automate(slider64)",
    ):
        assert token in source, token

    # EEL2 rejects C-style scientific numeric literals.
    executable = "\n".join(line.split("//", 1)[0] for line in source.splitlines())
    assert re.compile(r"(?<![A-Za-z0-9_])\d+(?:\.\d+)?[eE][+-]?\d+").search(
        executable
    ) is None


def assert_fold_mode_structure(source: str) -> None:
    """Band Mode 2 = constant-power Fold at +90 degrees, folded per frequency."""

    executable = "\n".join(line.split("//", 1)[0] for line in source.splitlines())

    # Mode is sanitized as a 0/1/2 integer; the 1.1 boolean squash would turn
    # Fold (2) back into Move.
    assert "fp_move[b] = fp_move[b] > 0.5;" not in executable
    assert "fp_move[b] = min(max(floor(fp_move[b] + 0.5), 0), 2);" in executable

    gains = source.split("function fp_prepare_band_gains", 1)[1].split(
        "function fp_transfer", 1
    )[0]
    assert "fp_move[b] == 1 ? amount : 0" in gains
    assert "fp_gain_fold[b]" in gains

    transfer = source.split("function fp_transfer", 1)[1].split(
        "function fp_partition_kernel", 1
    )[0]
    assert "folded += w * fp_gain_fold[b];" in transfer
    assert "fp_ti += folded;" in transfer
    assert "fp_rr += 1 - sqrt(1 - folded * folded);" in transfer
    # The fold must be added before the negative-bin conjugation.
    assert transfer.index("fp_ti += folded;") < transfer.index("negative_bin ? fp_ti = -fp_ti;")

    assert "fp_gain_fold = 176;" in source

    # GUI cycles ADD -> MOVE -> FOLD.
    assert '"FOLD"' in source
    assert "(fp_gui_mode(fp_band) + 1) % 3" in source


def assert_phase_snap_buttons(source: str) -> None:
    """A small per-band "90" button snaps Phase to +90 (GUI only, no new slider)."""

    gfx = source.split("@gfx", 1)[1]
    # Drawn and hit-tested next to the Phase knob, hidden in Fold mode where
    # Phase is ignored.
    assert "fp_hit = 700+fp_band;" in gfx
    assert 'fp_draw_button(fp_cx+40, fp_phase_y-12, 38, 24, "90"' in gfx
    # A standalone press handler, not another branch of the nested ternary.
    assert "fp_left_pressed && fp_hit >= 700 && fp_hit < 800 ? fp_gui_write_phase(fp_hit-700, 90);" in gfx
    assert max(_slider_records(source)) == 64
