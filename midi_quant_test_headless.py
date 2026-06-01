#!/usr/bin/env python3
"""Headless harness for MIDI Adaptive Quantize checks."""

from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT_PATH = Path(__file__).with_name("MIDI Adaptive Quantize V1.0.py")


def load_module(path: Path):
    spec = importlib.util.spec_from_file_location("midi_quant_v1", str(path))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_entrypoint_presence() -> None:
    module = load_module(SCRIPT_PATH)
    assert hasattr(module, "run_quantize"), "Missing run_quantize(config=None)"


def test_grid_candidates() -> None:
    module = load_module(SCRIPT_PATH)
    cfg = {"allow_sixteenth": True, "include_triplets": True,
           "qn_start": 100.0, "qn_end": 102.0, "grid_qn": 1.0}
    out = module.build_grid_candidates_qn(cfg)
    assert any(abs(x - 100.25) < 1e-9 for x in out["straight"])
    assert any(abs(x - (100.0 + 1.0 / 3.0)) < 1e-9 for x in out["triplet"])
    assert module.build_grid_candidates_qn(dict(cfg, include_triplets=False))["triplet"] == []


def test_group_transients() -> None:
    module = load_module(SCRIPT_PATH)
    assert module.group_transients([0.10, 0.12, 0.50, 0.52, 1.20], 0.1) == \
        [[0.10, 0.12], [0.50, 0.52], [1.20]]


def test_compute_move() -> None:
    module = load_module(SCRIPT_PATH)
    th, step = 0.015, 0.125
    assert module.compute_move(0.010, th, "snap", None, step) is None       # within tol
    assert abs(module.compute_move(0.040, th, "snap", None, step) + 0.040) < 1e-9
    assert abs(module.compute_move(0.040, th, "adaptive", 0.010, step) - (0.010 - 0.040)) < 1e-9
    assert module.compute_move(0.200, th, "snap", None, step) is None       # max-move guard


TESTS = [test_entrypoint_presence, test_grid_candidates, test_group_transients, test_compute_move]


def main() -> int:
    for test in TESTS:
        test()
        print(f"PASS: {test.__name__}")
    print(f"PASS: {len(TESTS)} checks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
