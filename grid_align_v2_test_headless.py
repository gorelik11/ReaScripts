#!/usr/bin/env python3
"""Headless harness for Grid Align Transients task checks."""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

SCRIPT_PATH = Path(__file__).with_name("Grid Align Transients V2.0.py")


def load_module(path: Path):
    spec = importlib.util.spec_from_file_location("grid_align_v2", str(path))
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
    R = module.resolve_processing_scope

    # 1 selected + time selection -> selected item, clipped to the time sel
    both = R({"time_selection": (1.0, 2.0), "selected_items": [object()]})
    assert both["mode"] == "selected_items"
    assert both["clip"] == (1.0, 2.0)

    # 1 selected, no time selection -> selected item processed whole (clip None)
    one = R({"selected_items": [object()]})
    assert one["mode"] == "selected_items" and one["clip"] is None

    # >=2 selected but NO time selection -> do nothing
    assert R({"selected_items": [1, 2]})["mode"] == "none"

    # >=2 selected WITH a time selection -> selected items, clipped
    multi_ts = R({"selected_items": [1, 2], "time_selection": (1.0, 2.0)})
    assert multi_ts["mode"] == "selected_items" and multi_ts["clip"] == (1.0, 2.0)

    # nothing selected (with or without a time selection) -> do nothing
    assert R({"time_selection": (1.0, 2.0)})["mode"] == "none"
    assert R({})["mode"] == "none"

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
        "fine_qn": 0.25,
        "include_triplets": True,
        "qn_start": 100.0,
        "qn_end": 102.0,
    }
    out = module.build_grid_candidates_qn(cfg)
    assert "straight" in out and "triplet" in out
    assert any(abs(x - 100.25) < 1e-9 for x in out["straight"])
    assert any(abs(x - (100.0 + 1.0 / 3.0)) < 1e-9 for x in out["triplet"])

    cfg_no_trip = dict(cfg, include_triplets=False)
    assert module.build_grid_candidates_qn(cfg_no_trip)["triplet"] == []

    # 1/8 choice -> straight spacing 0.5; no 100.25 sixteenth line present
    eighth = module.build_grid_candidates_qn(
        {"fine_qn": 0.5, "include_triplets": False,
         "qn_start": 100.0, "qn_end": 102.0})
    assert any(abs(x - 100.5) < 1e-9 for x in eighth["straight"])
    assert not any(abs(x - 100.25) < 1e-9 for x in eighth["straight"])


def test_group_family() -> None:
    module = load_module(SCRIPT_PATH)
    families = {
        "straight": [100.00, 100.25, 100.50, 100.75],
        "triplet": [100.00, 100.0 + 1.0 / 3.0, 100.0 + 2.0 / 3.0],
    }
    # group sits on triplet positions
    trip_group = [100.01, 100.0 + 1.0 / 3.0 + 0.005, 100.0 + 2.0 / 3.0 - 0.004]
    assert module.choose_family_for_group(trip_group, families) == "triplet"
    # group sits on straight positions
    straight_group = [100.01, 100.26, 100.49]
    assert module.choose_family_for_group(straight_group, families) == "straight"
    # tie / no triplet family -> straight
    assert module.choose_family_for_group([100.0], {"straight": [100.0], "triplet": []}) == "straight"


def test_correction_decision() -> None:
    module = load_module(SCRIPT_PATH)
    th = 0.015          # 15 ms threshold
    step = 0.125        # one grid step (sec)

    # within threshold -> untouched
    assert module.compute_move(curr_delta=0.010, threshold=th, mode="snap",
                               prev_lag=None, grid_step=step) is None

    # snap: move straight to grid (negate delta)
    assert abs(module.compute_move(0.040, th, "snap", None, step) - (-0.040)) < 1e-9

    # adaptive, first event (no prev) -> snap to grid
    assert abs(module.compute_move(0.040, th, "adaptive", None, step) - (-0.040)) < 1e-9

    # adaptive, both behind -> inherit prev lag: target = grid + prev_lag
    # move = prev_lag - curr_delta
    assert abs(module.compute_move(0.040, th, "adaptive", 0.010, step) - (0.010 - 0.040)) < 1e-9

    # adaptive, current rushes (early) -> snap to grid regardless of prev
    assert abs(module.compute_move(-0.040, th, "adaptive", 0.010, step) - (0.040)) < 1e-9

    # adaptive, current behind but prev ahead -> snap to grid
    assert abs(module.compute_move(0.040, th, "adaptive", -0.010, step) - (-0.040)) < 1e-9

    # max-move guard: a move larger than one grid step is skipped
    assert module.compute_move(0.200, th, "snap", None, step) is None

    # boundary: a move of exactly one grid step is allowed (guard is strictly >)
    boundary = module.compute_move(curr_delta=step, threshold=th, mode="snap",
                                   prev_lag=None, grid_step=step)
    assert boundary is not None and abs(boundary - (-step)) < 1e-9, boundary

    # adaptive inheritance can also trip the max-move guard:
    # both behind, but prev_lag so large that move = prev_lag - curr_delta > step
    assert module.compute_move(0.020, th, "adaptive", 0.200, step) is None


def test_report_schema_headless() -> None:
    module = load_module(SCRIPT_PATH)
    report = module.run_grid_align({
        "headless": True,
        "grid_threshold_ms": 15.0,
        "mode": "snap",
        "transient_source": "auto",
        "grid_choice": "1/16",
        "include_triplets": False,
    })
    for key in ("edited_segments", "skipped", "neighbor_touched", "crossed_time_selection"):
        assert key in report, (key, report)
    assert report["neighbor_touched"] is False
    assert report["crossed_time_selection"] is False
    assert isinstance(report["edited_segments"], int)


def test_plan_corrections_chain() -> None:
    module = load_module(SCRIPT_PATH)
    fam = [0.0, 0.5, 1.0, 1.5]          # straight candidates in QN
    qn_of_time = lambda t: t            # 1 QN == 1 sec for the test
    time_of_qn = lambda q: q
    # first behind by 0.04 (snap), second behind by 0.04 with prev_lag 0 -> snap
    edits = module.plan_corrections(
        [0.54, 1.04], fam, qn_of_time, time_of_qn,
        threshold_s=0.015, mode="adaptive", grid_step_s=0.5,
    )
    assert len(edits) == 2
    assert abs(edits[0]["move"] - (-0.04)) < 1e-9
    # after edit 1, prev_lag lands at exactly 0.0, so adaptive falls back to snap
    # (strict prev_lag > 0 guard) and edit 2 is also a pure snap.
    assert abs(edits[1]["move"] - (-0.04)) < 1e-9


def test_plan_corrections_branches() -> None:
    module = load_module(SCRIPT_PATH)
    ident = lambda x: x  # identity QN<->time (1 QN == 1 sec) for the test
    fam = [0.0, 1.0, 2.0, 3.0]

    # adaptive inherit FIRES: a within-tolerance transient sets prev_lag>0,
    # the next (behind, above threshold) inherits it.
    #   t=0.010 -> within 0.015 tol -> no edit, prev_lag=0.010
    #   t=1.040 -> delta +0.040 > tol, prev_lag 0.010>0 -> inherit:
    #              move = prev_lag - delta = 0.010 - 0.040 = -0.030
    edits = module.plan_corrections(
        [0.010, 1.040], fam, ident, ident,
        threshold_s=0.015, mode="adaptive", grid_step_s=1.0,
    )
    assert len(edits) == 1, edits
    assert abs(edits[0]["move"] - (-0.030)) < 1e-9, edits

    # guard-skip: a move larger than grid_step produces NO edit.
    #   t=0.5, nearest grid 0.0, delta 0.5 > tol; snap move -0.5; abs>0.1 -> skip
    skipped = module.plan_corrections(
        [0.5], fam, ident, ident,
        threshold_s=0.015, mode="snap", grid_step_s=0.1,
    )
    assert skipped == [], skipped


def test_group_transients() -> None:
    module = load_module(SCRIPT_PATH)
    ts = [0.10, 0.12, 0.50, 0.52, 0.53, 1.20]
    groups = module.group_transients(ts, gap_s=0.1)
    assert groups == [[0.10, 0.12], [0.50, 0.52, 0.53], [1.20]], groups
    assert module.group_transients([], 0.1) == []
    assert module.group_transients([0.4], 0.1) == [[0.4]]


def test_select_family_positions() -> None:
    module = load_module(SCRIPT_PATH)
    fams = {"straight": [0.0, 0.25], "triplet": [0.0, 0.333]}
    assert module.select_family_positions(fams, "triplet") == [0.0, 0.333]
    assert module.select_family_positions(fams, "straight") == [0.0, 0.25]


def test_docs_present() -> None:
    assert os.path.exists("docs/superpowers/specs/fixtures/grid-align-manual-test-checklist.md")


def test_resolve_fine_qn() -> None:
    module = load_module(SCRIPT_PATH)
    f = module.resolve_fine_qn
    assert f("1/8", 1.0) == 0.5
    assert f("1/16", 1.0) == 0.25
    assert f("1/32", 1.0) == 0.125
    assert f("project", 1.0) == 1.0
    assert f("project", 0.5) == 0.5
    assert f("bogus", 0.75) == 0.75   # unknown choice -> project grid


def test_entrypoint_no_systemexit() -> None:
    """Running the file as __main__ must NOT raise SystemExit.

    REAPER runs a ReaScript in an embedded interpreter; SystemExit there routes to
    Py_Exit -> C exit() and kills REAPER. In plain Python the ReaImGui import path
    cannot resolve, so the interactive dialog returns None cleanly. Guard that the
    entry returns without SystemExit. (Regression guard for the crash law.)
    """
    import runpy
    mocks = {
        "RPR_ShowMessageBox": lambda *a: 0,
        "RPR_GetResourcePath": lambda *a: "/nonexistent",
    }
    try:
        runpy.run_path(str(SCRIPT_PATH), init_globals=mocks, run_name="__main__")
    except SystemExit as exc:  # pragma: no cover - this is the bug we guard against
        raise AssertionError(
            "ReaScript __main__ raised SystemExit -> would terminate REAPER"
        ) from exc


def test_ext_state_defaults() -> None:
    module = load_module(SCRIPT_PATH)
    store = {}
    module.RPR_GetExtState = lambda sect, key: store.get((sect, key), "")
    module.RPR_SetExtState = lambda sect, key, val, persist: store.__setitem__((sect, key), val)

    # empty store -> V1 defaults
    assert module._load_defaults() == {
        "threshold_ms": 15, "source": "auto", "mode": "snap",
        "grid": "1/16", "triplets": False}

    # round-trip
    module._save_defaults({"threshold_ms": 22, "source": "splits",
                           "mode": "adaptive", "grid": "1/32", "triplets": True})
    assert module._load_defaults() == {
        "threshold_ms": 22, "source": "splits", "mode": "adaptive",
        "grid": "1/32", "triplets": True}

    # invalid stored values fall back to defaults
    store[("GridAlignTransients", "source")] = "garbage"
    store[("GridAlignTransients", "grid")] = "1/3"
    d = module._load_defaults()
    assert d["source"] == "auto" and d["grid"] == "1/16"


def test_dialog_apply_mapping() -> None:
    module = load_module(SCRIPT_PATH)
    from _reaper_fakes import FakeImGui
    calls = {"run": [], "defer": 0, "saved": None}
    module._run_in_reaper = lambda cfg, show_report=False: calls["run"].append((cfg, show_report))
    module.RPR_defer = lambda s: calls.__setitem__("defer", calls["defer"] + 1)
    module._save_defaults = lambda st: calls.__setitem__("saved", st)

    fake = FakeImGui(apply=True)
    module._GA = {"imgui": fake, "ctx": object(),
                  "ui": {"thr": 22, "src": 1, "mode": 1, "grid": 3, "trip": True}}
    module._ga_frame()

    assert module._GA is None            # dialog closed on Apply
    assert calls["defer"] == 0           # not re-deferred
    assert fake.ended == 1               # End always called
    assert len(calls["run"]) == 1
    cfg, show_report = calls["run"][0]
    assert show_report is True
    assert cfg == {
        "grid_threshold_ms": 22.0,
        "transient_source": "splits",     # src index 1
        "mode": "adaptive",               # mode index 1
        "grid_choice": "1/32",            # grid index 3
        "include_triplets": True,
    }
    assert calls["saved"]["mode"] == "adaptive" and calls["saved"]["grid"] == "1/32"


def test_dialog_cancel_and_redefer() -> None:
    module = load_module(SCRIPT_PATH)
    from _reaper_fakes import FakeImGui
    calls = {"run": 0, "defer": 0}
    module._run_in_reaper = lambda cfg, show_report=False: calls.__setitem__("run", calls["run"] + 1)
    module.RPR_defer = lambda s: calls.__setitem__("defer", calls["defer"] + 1)
    module._save_defaults = lambda st: None
    base_ui = {"thr": 15, "src": 0, "mode": 0, "grid": 2, "trip": False}

    # Cancel -> no core call, no redefer, closed
    module._GA = {"imgui": FakeImGui(cancel=True), "ctx": object(), "ui": dict(base_ui)}
    module._ga_frame()
    assert calls["run"] == 0 and calls["defer"] == 0 and module._GA is None

    # neither clicked, window open -> re-defer, stays open
    module._GA = {"imgui": FakeImGui(open_=1), "ctx": object(), "ui": dict(base_ui)}
    module._ga_frame()
    assert calls["run"] == 0 and calls["defer"] == 1 and module._GA is not None

    # window closed via X (open_ == 0) -> stop, no further redefer
    module._GA = {"imgui": FakeImGui(open_=0), "ctx": object(), "ui": dict(base_ui)}
    module._ga_frame()
    assert calls["defer"] == 1 and module._GA is None


TESTS = [
    test_entrypoint_presence,
    test_scope_and_guards,
    test_analysis_window,
    test_envelope_detector,
    test_existing_splits_source,
    test_grid_candidates,
    test_group_family,
    test_correction_decision,
    test_report_schema_headless,
    test_plan_corrections_chain,
    test_plan_corrections_branches,
    test_docs_present,
    test_group_transients,
    test_select_family_positions,
    test_entrypoint_no_systemexit,
    test_resolve_fine_qn,
    test_ext_state_defaults,
    test_dialog_apply_mapping,
    test_dialog_cancel_and_redefer,
]


def main() -> int:
    for test in TESTS:
        test()
        print(f"PASS: {test.__name__}")
    print(f"PASS: {len(TESTS)} checks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
