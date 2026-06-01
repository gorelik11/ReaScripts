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


def test_resolve_scope() -> None:
    module = load_module(SCRIPT_PATH)
    R = module.resolve_quant_scope

    # selected notes win outright (no clip applied)
    s = R({"selected_notes": [1, 2], "selected_items": [9], "time_sel": (1.0, 2.0)})
    assert s["mode"] == "notes" and s["notes"] == [1, 2] and s["clip"] is None

    # no notes, items + time selection -> items clipped
    s = R({"selected_items": [9], "time_sel": (1.0, 2.0)})
    assert s["mode"] == "items" and s["items"] == [9] and s["clip"] == (1.0, 2.0)

    # no notes, items, no time selection -> items whole
    s = R({"selected_items": [9]})
    assert s["mode"] == "items" and s["clip"] is None

    # nothing selected -> none (with or without time selection)
    assert R({"time_sel": (1.0, 2.0)})["mode"] == "none"
    assert R({})["mode"] == "none"


def test_quantized_start_ppq() -> None:
    module = load_module(SCRIPT_PATH)
    # ok: new start leaves >= MIN_NOTE_TICKS before end
    assert module.quantized_start_ppq(new_start=100, end=960, min_ticks=1) == 100
    # skip: new start would reach/cross the end (returns None)
    assert module.quantized_start_ppq(new_start=959, end=960, min_ticks=2) is None
    assert module.quantized_start_ppq(new_start=960, end=960, min_ticks=1) is None
    # exact boundary allowed (start + min_ticks == end)
    assert module.quantized_start_ppq(new_start=959, end=960, min_ticks=1) == 959


def test_plan_note_moves() -> None:
    module = load_module(SCRIPT_PATH)
    ident = lambda x: x                       # 1 QN == 1 sec for the test
    families = {"straight": [0.0, 1.0, 2.0, 3.0], "triplet": []}
    grid_step_for = lambda q0: 1.0            # constant 1s grid step

    # two lone onsets, each 0.04 late of an integer grid point, snap mode
    moves = module.plan_note_moves(
        onsets=[1.04, 2.04], families=families, qn_of_time=ident, time_of_qn=ident,
        grid_step_for=grid_step_for, threshold_s=0.015, mode="snap", gap_s=0.1)
    assert len(moves) == 2
    assert abs(moves[0]["move"] - (-0.04)) < 1e-9
    assert moves[0]["onsets"] == [1.04]

    # within-tolerance onset is left out entirely
    none_moves = module.plan_note_moves(
        onsets=[1.005], families=families, qn_of_time=ident, time_of_qn=ident,
        grid_step_for=grid_step_for, threshold_s=0.015, mode="snap", gap_s=0.1)
    assert none_moves == []


TESTS = [test_entrypoint_presence, test_grid_candidates, test_group_transients, test_compute_move,
         test_resolve_scope, test_quantized_start_ppq, test_plan_note_moves]


def main() -> int:
    for test in TESTS:
        test()
        print(f"PASS: {test.__name__}")
    print(f"PASS: {len(TESTS)} checks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
