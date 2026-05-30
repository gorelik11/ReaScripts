#!/usr/bin/env python3
"""Headless harness for Grid Align Transients task checks."""

from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT_PATH = Path(__file__).with_name("Grid Align Transients V1.0.py")


def load_module(path: Path):
    spec = importlib.util.spec_from_file_location("grid_align_v1", str(path))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_entrypoint_presence() -> None:
    module = load_module(SCRIPT_PATH)
    assert hasattr(module, "run_grid_align"), "Missing run_grid_align(config=None) entrypoint"


def test_scope_and_guards() -> None:
    module = load_module(SCRIPT_PATH)
    ts = module.resolve_processing_scope(
        {"time_selection": (1.0, 2.0), "selected_items": [object()], "all_items": []}
    )
    assert ts["mode"] == "time_selection"
    assert ts["range"] == (1.0, 2.0)

    sel = module.resolve_processing_scope({"selected_items": [1, 2], "all_items": [9]})
    assert sel["mode"] == "selected_items"

    full = module.resolve_processing_scope({"all_items": [9]})
    assert full["mode"] == "full_range"

    assert module.should_skip_item({"playrate": 1.25, "reversed": 0, "section": 0}) is True
    assert module.should_skip_item({"playrate": 1.0, "reversed": 1, "section": 0}) is True
    assert module.should_skip_item({"playrate": 1.0, "reversed": 0, "section": 1}) is True
    assert module.should_skip_item({"playrate": 1.0, "reversed": 0, "section": 0}) is False


def test_analysis_window() -> None:
    module = load_module(SCRIPT_PATH)

    # item at project 10.0s, length 4.0s, trimmed 2.0s into a longer source
    w = module.compute_analysis_window(item_pos=10.0, item_len=4.0, start_offs=2.0)
    assert abs(w["src_start"] - 2.0) < 1e-9
    assert abs(w["src_end"] - 6.0) < 1e-9
    assert abs(w["proj_start"] - 10.0) < 1e-9
    assert abs(w["proj_end"] - 14.0) < 1e-9

    # time selection narrower than item clips both ends to the intersection
    w2 = module.compute_analysis_window(
        item_pos=10.0, item_len=4.0, start_offs=2.0, time_sel=(11.0, 13.0)
    )
    assert abs(w2["proj_start"] - 11.0) < 1e-9
    assert abs(w2["proj_end"] - 13.0) < 1e-9
    assert abs(w2["src_start"] - 3.0) < 1e-9
    assert abs(w2["src_end"] - 5.0) < 1e-9

    # time selection fully outside the item yields empty window
    assert module.compute_analysis_window(
        item_pos=10.0, item_len=4.0, start_offs=2.0, time_sel=(20.0, 21.0)
    ) is None

    # mapping a source time back to project time
    assert abs(module.source_to_project_time(3.5, item_pos=10.0, start_offs=2.0) - 11.5) < 1e-9


def test_envelope_detector() -> None:
    module = load_module(SCRIPT_PATH)
    sr = 12000
    samples = [0.0] * (sr * 1)  # 1 second of silence
    # two sharp attacks: 0.20s and 0.60s, each a short decaying burst
    for onset in (0.20, 0.60):
        start = int(onset * sr)
        for k in range(int(0.05 * sr)):
            samples[start + k] = 0.9 * (1.0 - k / (0.05 * sr))

    onsets = module.detect_transients_envelope(samples, sr)
    assert len(onsets) == 2, onsets
    assert abs(onsets[0] - 0.20) < 0.01, onsets
    assert abs(onsets[1] - 0.60) < 0.01, onsets

    # silence produces nothing
    assert module.detect_transients_envelope([0.0] * sr, sr) == []

    # retrig lockout: two close attacks (0.20s, 0.245s = 25ms apart onset-to-onset).
    # Default 30ms lockout suppresses the second; a short 5ms lockout allows both.
    # NOTE: bursts are 10ms long; 25ms separation gives a 15ms gap between them.
    # At 20ms separation the slow envelope is still elevated from the first burst's
    # decay tail, so the fast/slow ratio never exceeds the sensitivity=2.0 threshold
    # even after the 5ms lockout expires.  25ms separation clears that decay enough.
    close = [0.0] * (sr * 1)
    for onset in (0.20, 0.225):
        start = int(onset * sr)
        for k in range(int(0.01 * sr)):  # 10ms bursts
            if start + k < len(close):
                close[start + k] = 0.9 * (1.0 - k / (0.01 * sr))
    assert len(module.detect_transients_envelope(close, sr)) == 1, "default 30ms lockout should suppress the 2nd"
    assert len(module.detect_transients_envelope(close, sr, retrig_ms=5.0)) == 2, "5ms lockout should allow both"


def test_existing_splits_source() -> None:
    module = load_module(SCRIPT_PATH)
    # split boundaries in project time; window keeps only those inside [11, 13]
    edges = [10.5, 11.2, 12.0, 12.9, 13.4]
    inside = module.transients_from_splits(edges, proj_start=11.0, proj_end=13.0)
    assert inside == [11.2, 12.0, 12.9], inside
    # empty when none inside
    assert module.transients_from_splits([10.0, 14.0], 11.0, 13.0) == []


def test_grid_candidates() -> None:
    module = load_module(SCRIPT_PATH)
    cfg = {
        "allow_sixteenth": True,
        "include_triplets": True,
        "qn_start": 100.0,
        "qn_end": 102.0,
        "grid_qn": 1.0,
    }
    out = module.build_grid_candidates_qn(cfg)
    assert "straight" in out and "triplet" in out
    assert any(abs(x - 100.25) < 1e-9 for x in out["straight"])
    assert any(abs(x - (100.0 + 1.0 / 3.0)) < 1e-9 for x in out["triplet"])

    # triplets off -> empty triplet family
    cfg_no_trip = dict(cfg, include_triplets=False)
    assert module.build_grid_candidates_qn(cfg_no_trip)["triplet"] == []


TESTS = [
    test_entrypoint_presence,
    test_scope_and_guards,
    test_analysis_window,
    test_envelope_detector,
    test_existing_splits_source,
    test_grid_candidates,
]


def main() -> int:
    for test in TESTS:
        test()
        print(f"PASS: {test.__name__}")
    print(f"PASS: {len(TESTS)} checks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
