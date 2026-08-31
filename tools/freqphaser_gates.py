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
