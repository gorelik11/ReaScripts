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


def test_report_schema_headless() -> None:
    module = load_module(SCRIPT_PATH)
    rep = module.run_quantize({"headless": True, "grid_threshold_ms": 15.0,
                               "mode": "snap", "allow_sixteenth": True,
                               "include_triplets": False})
    for key in ("moved_notes", "skipped_notes", "ends_unchanged"):
        assert key in rep, (key, rep)
    assert rep["ends_unchanged"] is True
    assert isinstance(rep["moved_notes"], int)


def test_run_in_reaper_mock() -> None:
    """End-to-end in a fake REAPER: one take, three notes; only the off-grid one
    moves, its end is unchanged, and a degenerate move is skipped."""
    import types
    module = load_module(SCRIPT_PATH)

    # one take (id=1), 960 PPQ/QN, tempo 60 BPM so 1 QN == 1 sec, grid = 1 QN.
    # notes: n0 on-grid (0.000s), n1 late by 0.040s at QN 1, n2 a tiny note whose
    # move would cross its end (skipped). startppq in ticks (960/QN).
    notes = [
        {"start": 0,    "end": 480, "sel": True, "muted": False, "chan": 0, "pitch": 60},
        {"start": 960 + 38, "end": 1440, "sel": True, "muted": False, "chan": 0, "pitch": 62},
        {"start": 1882, "end": 1900, "sel": True, "muted": False, "chan": 0, "pitch": 64},  # early+short: snap-right crosses end -> skipped
    ]
    set_calls = []
    g = {}
    g["RPR_GetUserInputs"] = lambda *a: (1, a[0], a[1], "15,snap,1,0", a[4])
    g["RPR_GetSet_LoopTimeRange"] = lambda *a: (0, 0, 0.0, 0.0, 0)  # no time sel
    g["RPR_MIDIEditor_GetActive"] = lambda: 0                       # no editor
    g["RPR_CountSelectedMediaItems"] = lambda p: 1
    g["RPR_GetSelectedMediaItem"] = lambda p, i: 100
    g["RPR_GetActiveTake"] = lambda item: 1
    g["RPR_TakeIsMIDI"] = lambda take: True
    g["RPR_MIDI_CountEvts"] = lambda take, a, b, c: (3, take, 3, 0, 0)  # (retval, take, notecnt, cc, text)
    def get_note(take, i, *a):  # wrapper echoes all params: (retval, take, idx, sel, muted, start, end, chan, pitch, vel)
        n = notes[i]
        return (True, take, i, n["sel"], n["muted"], n["start"], n["end"], n["chan"], n["pitch"], 96)
    g["RPR_MIDI_GetNote"] = get_note
    def set_note(take, i, sel, muted, startppq, endppq, chan, pitch, vel, noSort):
        set_calls.append({"i": i, "start": startppq, "end": endppq})
        notes[i]["start"], notes[i]["end"] = startppq, endppq
        return True
    g["RPR_MIDI_SetNote"] = set_note
    g["RPR_MIDI_DisableSort"] = lambda take: None
    g["RPR_MIDI_Sort"] = lambda take: None
    g["RPR_MIDI_GetGrid"] = lambda take, a, b: (1.0, take, 0.0)      # grid = 1 QN
    g["RPR_MIDI_GetProjTimeFromPPQPos"] = lambda take, ppq: ppq / 960.0      # 1 QN == 1 sec
    g["RPR_MIDI_GetPPQPosFromProjTime"] = lambda take, t: round(t * 960.0)
    g["RPR_TimeMap2_timeToQN"] = lambda proj, t: t                  # 1 sec == 1 QN
    g["RPR_TimeMap2_QNToTime"] = lambda proj, q: q
    for noop in ("RPR_Undo_BeginBlock", "RPR_UpdateArrange"):
        g[noop] = lambda *a: None
    g["RPR_Undo_EndBlock"] = lambda *a: None
    g["RPR_ShowMessageBox"] = lambda *a: 0
    for k, v in g.items():
        setattr(module, k, v)

    rep = module._run_in_reaper({"grid_threshold_ms": 15.0, "mode": "snap",
                                 "allow_sixteenth": True, "include_triplets": False})
    moved = {c["i"] for c in set_calls}
    assert 0 not in moved, "on-grid note must not move"
    assert 1 in moved, "off-grid note must move"
    # start-only: the moved note's end is unchanged (1440)
    n1 = [c for c in set_calls if c["i"] == 1][-1]
    assert n1["end"] == 1440, n1
    assert abs(n1["start"] - 960) <= 1, n1  # snapped to QN 1 (=960 ticks)
    assert rep["ends_unchanged"] is True
    assert rep["moved_notes"] >= 1 and rep["skipped_notes"] >= 1


def test_entrypoint_no_systemexit() -> None:
    """Running the file as __main__ must NOT raise SystemExit (Py_Exit kills REAPER)."""
    import runpy
    calls = {"dialog": 0}

    def fake_dialog(*a):
        calls["dialog"] += 1
        return (0,) + tuple(a)  # retval 0 -> cancel -> run_quantize returns None

    mocks = {"RPR_GetUserInputs": fake_dialog, "RPR_ShowMessageBox": lambda *a: 0,
             "RPR_GetSet_LoopTimeRange": lambda *a: (0, 0, 0.0, 0.0, 0),
             "RPR_MIDIEditor_GetActive": lambda: 0,
             "RPR_CountSelectedMediaItems": lambda p: 0}
    try:
        runpy.run_path(str(SCRIPT_PATH), init_globals=mocks, run_name="__main__")
    except SystemExit as exc:
        raise AssertionError("entry raised SystemExit -> would kill REAPER") from exc
    assert calls["dialog"] == 1, "entry did not reach run_quantize"


TESTS = [test_entrypoint_presence, test_grid_candidates, test_group_transients, test_compute_move,
         test_resolve_scope, test_quantized_start_ppq, test_plan_note_moves,
         test_report_schema_headless, test_run_in_reaper_mock, test_entrypoint_no_systemexit]


def main() -> int:
    for test in TESTS:
        test()
        print(f"PASS: {test.__name__}")
    print(f"PASS: {len(TESTS)} checks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
