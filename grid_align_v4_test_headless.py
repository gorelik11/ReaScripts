#!/usr/bin/env python3
"""Headless harness for Grid Align Transients task checks."""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

SCRIPT_PATH = Path(__file__).with_name("Grid Align Transients V4.0.py")


def load_module(path: Path):
    spec = importlib.util.spec_from_file_location("grid_align_v4", str(path))
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


def test_source_label_warns_about_whole_item_move() -> None:
    module = load_module(SCRIPT_PATH)
    labels = module._SOURCE_LABELS
    assert len(labels) == len(module._SOURCES)
    assert "whole item" in labels[1].lower(), \
        "the splits mode must say it moves entire items"


def test_seam_style_option_round_trips() -> None:
    module = load_module(SCRIPT_PATH)
    assert module._SEAMS == ["crossfade", "butt"]
    assert len(module._SEAM_LABELS) == len(module._SEAMS)
    assert "overlap" in module._SEAM_LABELS[0].lower()
    assert "butt" in module._SEAM_LABELS[1].lower()


def test_butt_joint_leaves_no_overlap_at_all() -> None:
    import _reaper_fakes as F
    module = load_module(SCRIPT_PATH)
    sr = 22050
    attacks = [0.15 + i * 0.12 for i in range(12)]
    samples, ids = make_impulse_source(sr, 2.0, attacks, body=0.08)
    proj = F.FakeProject(bpm=120.0)
    # REAPER's own split auto-crossfade is ON by default (confirmed live:
    # Preferences > Item Fade Defaults > Split media items = Overlap and
    # crossfade, 5 ms, centred). Butt joint must survive it.
    proj.split_autocrossfade = 0.005
    tr = proj.add_track()
    it = tr.add_item(position=0.0, length=2.0, samples=samples)
    it.selected = True
    F.install_reaper_fakes(module, proj)
    module._run_in_reaper({"grid_threshold_ms": 15.0, "mode": "snap",
                           "transient_source": "auto", "grid_choice": "1/16",
                           "include_triplets": False, "butt_joint": True})
    spans = sorted((x.position, x.position + x.length) for x in tr.items)
    for i in range(len(spans) - 1):
        assert spans[i][1] <= spans[i + 1][0] + 1e-9, \
            "butt joint must leave zero overlap, found {:.4f} s".format(
                spans[i][1] - spans[i + 1][0])


def test_seam_overlap_trims_left_only() -> None:
    import _reaper_fakes as F
    module = load_module(SCRIPT_PATH)
    proj = F.FakeProject(bpm=120.0)
    tr = proj.add_track()
    left = tr.add_item(position=1.0, length=0.50, start_offs=0.0)
    right = tr.add_item(position=1.30, length=0.40, start_offs=0.50)
    F.install_reaper_fakes(module, proj)
    r = module.heal_seam(left, right, budget_s=1.0)
    assert r["trimmed"] is True
    assert abs(right.position - 1.30) < 1e-9, "the right note's start is inviolable"
    assert abs(right.take.start_offs - 0.50) < 1e-9, "its content must not slide"
    assert abs((left.position + left.length) - 1.305) < 1e-9, left.length


def test_seam_gap_pulls_right_within_budget() -> None:
    import _reaper_fakes as F
    module = load_module(SCRIPT_PATH)
    proj = F.FakeProject(bpm=120.0)
    tr = proj.add_track()
    left = tr.add_item(position=1.0, length=0.30, start_offs=0.0)
    right = tr.add_item(position=1.40, length=0.40, start_offs=0.40)
    F.install_reaper_fakes(module, proj)
    r = module.heal_seam(left, right, budget_s=1.0)
    # gap 0.10 -> pull the RIGHT item back; its attack must not move, so
    # position and start_offs both drop by the same amount
    assert abs(r["pulled"] - 0.105) < 1e-9, r
    assert abs(right.position - 1.295) < 1e-9, right.position
    assert abs(right.take.start_offs - 0.295) < 1e-9, right.take.start_offs
    assert abs(right.length - 0.505) < 1e-9, right.length
    assert r["unfilled"] == 0.0


def test_seam_gap_beyond_budget_reports_hole() -> None:
    import _reaper_fakes as F
    module = load_module(SCRIPT_PATH)
    proj = F.FakeProject(bpm=120.0)
    tr = proj.add_track()
    left = tr.add_item(position=1.0, length=0.30, start_offs=0.0)
    right = tr.add_item(position=1.60, length=0.40, start_offs=0.60)
    F.install_reaper_fakes(module, proj)
    r = module.heal_seam(left, right, budget_s=0.05)   # may only pull 50 ms
    assert abs(r["pulled"] - 0.05) < 1e-9, r
    assert r["unfilled"] > 0.24, "the rest must be reported, never silently left"


def test_corrections_survive_sample_grid_snapping() -> None:
    """Live regression: the first V4 run aligned 0 notes while trimming 54 seams.

    REAPER snaps a split to the sample grid, so a piece never starts exactly at
    the requested time. Matching a note to its piece by an exact key therefore
    dropped every correction, and the seam pass then trimmed material for no
    benefit. Item position and attack times here are deliberately off-grid, as
    they are in a real project (the reported item sat at 19249.511895833333).
    """
    import _reaper_fakes as F
    module = load_module(SCRIPT_PATH)
    sr = 22050
    attacks = [0.1737, 0.4021, 0.6388, 0.8611, 1.0904, 1.3122]
    samples, ids = make_impulse_source(sr, 1.8, attacks, body=0.08)
    proj = F.FakeProject(bpm=120.0, sample_rate=96000)
    tr = proj.add_track()
    it = tr.add_item(position=19249.511895833333, length=1.8, samples=samples)
    it.selected = True
    F.install_reaper_fakes(module, proj)
    rep = module._run_in_reaper({"grid_threshold_ms": 15.0, "mode": "snap",
                                 "transient_source": "auto",
                                 "grid_choice": "1/16",
                                 "include_triplets": False})
    assert rep["refused_unmatched"] == 0, \
        "a piece could not be matched to its note: {}".format(rep)
    # if anything was cut, something must have moved - never trim for nothing
    if rep["seams_trimmed"] or rep["seams_pulled"]:
        assert rep["notes_aligned"] > 0, \
            "seams were healed but no note moved: {}".format(rep)


def test_corrections_survive_auto_crossfade_on_split() -> None:
    """Pieces must be identified by cut ORDER, never by reported position.

    Live runs aligned 0 notes with 42 unmatched: a piece's start is not the
    requested cut time. Sample-grid snapping alone is tiny, but REAPER's
    auto-crossfade on split (on by default) pulls the new right-hand piece back
    by the crossfade length, which no position tolerance can absorb safely at
    shaker density.
    """
    import _reaper_fakes as F
    module = load_module(SCRIPT_PATH)
    sr = 22050
    attacks = [0.1737, 0.4021, 0.6388, 0.8611, 1.0904, 1.3122]
    samples, ids = make_impulse_source(sr, 1.8, attacks, body=0.08)
    proj = F.FakeProject(bpm=120.0, sample_rate=96000)
    proj.split_autocrossfade = 0.010          # REAPER's default behaviour
    tr = proj.add_track()
    it = tr.add_item(position=19249.511895833333, length=1.8, samples=samples)
    it.selected = True
    F.install_reaper_fakes(module, proj)
    rep = module._run_in_reaper({"grid_threshold_ms": 15.0, "mode": "snap",
                                 "transient_source": "auto",
                                 "grid_choice": "1/16",
                                 "include_triplets": False})
    assert rep["refused_unmatched"] == 0,         "pieces were identified by position and lost: {}".format(rep)
    if rep["seams_trimmed"] or rep["seams_pulled"]:
        assert rep["notes_aligned"] > 0,             "seams healed but nothing moved: {}".format(rep)


def test_other_lanes_are_not_obstacles() -> None:
    """Live regression: on a fixed-lane track the script refused everything.

    Every lane covers the same timeline, so treating any unselected item as an
    obstacle purely by time made each lane block every other one - the run
    reported 141 of 142 corrections refused as 'neighbour' and appeared to do
    nothing. Comping tracks are exactly where this tool gets used.
    """
    import _reaper_fakes as F
    module = load_module(SCRIPT_PATH)
    sr = 22050
    attacks = [0.20, 0.55, 0.90, 1.25, 1.60]
    samples, ids = make_impulse_source(sr, 2.5, attacks)
    proj = F.FakeProject(bpm=120.0)
    tr = proj.add_track()
    target = tr.add_item(position=0.0, length=2.5, samples=samples)
    target.fixed_lane = 1
    target.selected = True
    # a comp take in ANOTHER lane, covering exactly the same timeline
    other = tr.add_item(position=0.0, length=2.5, samples=samples)
    other.fixed_lane = 0
    F.install_reaper_fakes(module, proj)
    rep = module._run_in_reaper({"grid_threshold_ms": 15.0, "mode": "snap",
                                 "transient_source": "auto",
                                 "grid_choice": "1/16",
                                 "include_triplets": False})
    assert rep["refused_foreign"] == 0, \
        "material in another lane blocked the edit: {}".format(rep)
    assert rep["notes_aligned"] > 0, \
        "nothing was corrected on a lane track: {}".format(rep)
    # the other lane must be left exactly as it was
    assert abs(other.position - 0.0) < 1e-9 and abs(other.length - 2.5) < 1e-9, \
        "the other lane was modified"


def test_dense_material_stays_clean() -> None:
    """Shaker density: an attack every ~100 ms, which is what broke V3.

    V3's synthetic tests used one attack per 250 ms and passed while the live
    shaker produced 48 overlaps.
    """
    import _reaper_fakes as F
    module = load_module(SCRIPT_PATH)
    sr = 22050
    attacks = [0.15 + i * 0.10 for i in range(20)]
    samples, ids = make_impulse_source(sr, 2.6, attacks, body=0.08)
    proj = F.FakeProject(bpm=120.0)
    tr = proj.add_track()
    it = tr.add_item(position=0.0, length=2.6, samples=samples)
    it.selected = True
    F.install_reaper_fakes(module, proj)
    rep = module._run_in_reaper({"grid_threshold_ms": 15.0, "mode": "snap",
                                 "transient_source": "auto",
                                 "grid_choice": "1/16",
                                 "include_triplets": False})
    assert rep["new_overlaps"] == 0, rep
    rendered = proj.render_timeline(sr, 0.0, 2.6)
    for ident in ids:
        assert count_attack_hits(rendered, ident) <= 1, \
            "attack {} duplicated at shaker density; report {}".format(ident, rep)
    # item count must follow K+R+1, never 2K
    assert len(tr.items) <= rep["notes_total"] + 2, \
        "{} items for {} notes".format(len(tr.items), rep["notes_total"])


def test_property_no_new_overlaps_across_densities() -> None:
    import random
    import _reaper_fakes as F
    module = load_module(SCRIPT_PATH)
    sr = 22050
    for seed in range(12):
        random.seed(seed)
        spacing = random.choice([0.06, 0.10, 0.16, 0.25])
        spread = random.choice([0.010, 0.030, 0.050])
        n = random.randint(6, 18)
        attacks = []
        t = 0.20
        for _ in range(n):
            attacks.append(t + random.uniform(-spread, spread))
            t += spacing
        attacks = sorted(x for x in attacks if x > 0.05)
        dur = attacks[-1] + 0.5
        samples, ids = make_impulse_source(sr, dur, attacks,
                                           body=min(0.08, spacing))
        proj = F.FakeProject(bpm=120.0)
        tr = proj.add_track()
        it = tr.add_item(position=0.0, length=dur, samples=samples)
        it.selected = True
        F.install_reaper_fakes(module, proj)
        rep = module._run_in_reaper({"grid_threshold_ms": 15.0, "mode": "snap",
                                     "transient_source": "auto",
                                     "grid_choice": "1/16",
                                     "include_triplets": False})
        assert rep["new_overlaps"] == 0, "seed {}: {}".format(seed, rep)
        for x in tr.items:
            assert x.length > 0, "seed {}: zero-length item".format(seed)
        rendered = proj.render_timeline(sr, 0.0, dur)
        for ident in ids:
            assert count_attack_hits(rendered, ident) <= 1, \
                "seed {}: attack {} duplicated".format(seed, ident)


def test_every_attack_is_audible_exactly_once() -> None:
    """The test rev 1's design would have failed while reporting success."""
    import _reaper_fakes as F
    module = load_module(SCRIPT_PATH)
    sr = 22050
    attacks = [0.20, 0.55, 0.90, 1.25, 1.60]
    samples, ids = make_impulse_source(sr, 2.5, attacks)
    proj = F.FakeProject(bpm=120.0)
    tr = proj.add_track()
    it = tr.add_item(position=0.0, length=2.5, samples=samples)
    it.selected = True
    F.install_reaper_fakes(module, proj)
    rep = module._run_in_reaper({"grid_threshold_ms": 15.0, "mode": "snap",
                                 "transient_source": "auto",
                                 "grid_choice": "1/16",
                                 "include_triplets": False})
    rendered = proj.render_timeline(sr, 0.0, 2.5)
    for ident in ids:
        hits = count_attack_hits(rendered, ident)
        assert hits == 1, \
            "attack id {} audible {} times (0=lost, 2+=flam); report {}".format(
                ident, hits, rep)
    assert rep["new_overlaps"] == 0, rep


def test_cut_returns_pieces_left_to_right_and_keeps_lane() -> None:
    import _reaper_fakes as F
    module = load_module(SCRIPT_PATH)
    proj = F.FakeProject(bpm=120.0)
    tr = proj.add_track()
    it = tr.add_item(position=10.0, length=4.0)
    it.fixed_lane = 2
    F.install_reaper_fakes(module, proj)
    pieces = module._cut_item_at(it, [11.0, 12.0, 13.0])
    assert pieces is not None and len(pieces) == 4, pieces
    starts = [module.RPR_GetMediaItemInfo_Value(p, "D_POSITION") for p in pieces]
    assert starts == sorted(starts), starts
    assert abs(starts[0] - 10.0) < 1e-9 and abs(starts[3] - 13.0) < 1e-9
    for p in pieces:
        assert module.RPR_GetMediaItemInfo_Value(p, "I_FIXEDLANE") == 2.0, \
            "every piece must stay in the source item's lane or comping breaks"


def test_failed_cut_leaves_no_orphan() -> None:
    import _reaper_fakes as F
    module = load_module(SCRIPT_PATH)
    proj = F.FakeProject(bpm=120.0)
    # any cut within 1.5 s of the item end fails
    proj.split_fail_within = 1.5
    tr = proj.add_track()
    it = tr.add_item(position=10.0, length=4.0)
    F.install_reaper_fakes(module, proj)
    before = len(tr.items)
    pieces = module._cut_item_at(it, [11.0, 13.5])   # second cut must fail
    assert pieces is None, "a partial cut set must be reported as failure"
    assert len(tr.items) == before, \
        "partial cuts must be undone: V3 left an orphaned fragment here"
    assert abs(it.length - 4.0) < 1e-9, "the original item must be restored"


def test_cut_set_is_k_plus_r_plus_one() -> None:
    module = load_module(SCRIPT_PATH)
    groups = [[float(i) * 0.25 + 0.10] for i in range(8)]
    notes = module.note_bounds(groups, window_end=2.5)

    # one adjacent run of 3 corrections -> K=3, R=1 -> 4 cuts, 5 items
    acc = [{"index": 2, "move": 0.01, "target": 0.0},
           {"index": 3, "move": 0.01, "target": 0.0},
           {"index": 4, "move": 0.01, "target": 0.0}]
    cuts, items = module.build_cut_set(notes, acc)
    assert len(cuts) == 4, cuts
    assert items == 5, items
    assert cuts == sorted(set(cuts)), "cuts must be unique and ordered"

    # three isolated corrections -> K=3, R=3 -> 6 cuts, 7 items
    acc = [{"index": 1, "move": 0.01, "target": 0.0},
           {"index": 4, "move": 0.01, "target": 0.0},
           {"index": 6, "move": 0.01, "target": 0.0}]
    cuts, items = module.build_cut_set(notes, acc)
    assert len(cuts) == 6, cuts
    assert items == 7, items


def _final_starts(module, notes, accepted):
    """Where each note actually ends up: moved ones shift, refused ones do not."""
    by_idx = {a["index"]: a["move"] for a in accepted}
    return [n["start"] + by_idx.get(i, 0.0) for i, n in enumerate(notes)]


def test_monotonic_guard_keeps_order_and_spacing() -> None:
    """The guard's real contract: no note may crowd or overtake its neighbour.

    Refusals are decided in the same pass that finalizes prev_lag, so spacing is
    always measured against where the previous note REALLY ended up - not
    against a corrected position that was later thrown away.
    """
    module = load_module(SCRIPT_PATH)
    ident = lambda x: x
    step = lambda q: 1.0
    # three notes crowded just after the 1.0 and 2.0 grid lines: snapping them
    # all back would stack them on top of each other
    groups = [[1.010], [1.050], [1.080], [2.040], [2.050]]
    notes = module.note_bounds(groups, window_end=4.0)
    fams = [[0.0, 1.0, 2.0, 3.0, 4.0]] * len(groups)
    accepted, refusals = module.plan_notes(
        notes, ident, ident, fams, threshold_s=0.015, mode="adaptive",
        grid_step_for=step, sentinels=(0.0, 4.0), obstacles=[])
    assert refusals["monotonic"] >= 1, refusals
    finals = _final_starts(module, notes, accepted)
    for i in range(len(finals) - 1):
        assert finals[i + 1] - finals[i] >= module._MIN_NOTE_LEN - 1e-9, \
            "notes {} and {} ended {:.4f} s apart: {}".format(
                i, i + 1, finals[i + 1] - finals[i], finals)


def test_guard_refuses_move_past_decay_budget() -> None:
    module = load_module(SCRIPT_PATH)
    ident = lambda x: x
    step = lambda q: 1.0
    groups = [[1.000, 1.200], [1.235]]
    notes = module.note_bounds(groups, window_end=3.0)
    fams = [[0.0, 1.0, 2.0, 3.0]] * 2
    accepted, refusals = module.plan_notes(
        notes, ident, ident, fams, threshold_s=0.015, mode="snap",
        grid_step_for=step, sentinels=(0.0, 3.0), obstacles=[])
    assert refusals["decay_budget"] >= 1 or refusals["monotonic"] >= 1, refusals


def test_guard_refuses_move_onto_foreign_material() -> None:
    module = load_module(SCRIPT_PATH)
    ident = lambda x: x
    step = lambda q: 1.0
    groups = [[1.040]]
    notes = module.note_bounds(groups, window_end=2.0)
    fams = [[0.0, 1.0, 2.0]]
    accepted, refusals = module.plan_notes(
        notes, ident, ident, fams, threshold_s=0.015, mode="snap",
        grid_step_for=step, sentinels=(0.0, 2.0),
        obstacles=[(0.90, 1.20)])
    assert refusals["foreign"] == 1, refusals
    assert accepted == []


def test_guard_refuses_move_outside_sentinels() -> None:
    module = load_module(SCRIPT_PATH)
    ident = lambda x: x
    step = lambda q: 1.0
    groups = [[0.030]]
    notes = module.note_bounds(groups, window_end=2.0)
    fams = [[0.0, 1.0, 2.0]]
    accepted, refusals = module.plan_notes(
        notes, ident, ident, fams, threshold_s=0.015, mode="snap",
        grid_step_for=step, sentinels=(0.020, 2.0), obstacles=[])
    assert refusals["window"] == 1, refusals
    assert accepted == []


def test_note_bounds_are_contiguous() -> None:
    module = load_module(SCRIPT_PATH)
    groups = [[1.00, 1.01], [1.50], [2.00, 2.02, 2.03]]
    notes = module.note_bounds(groups, window_end=3.0)
    assert len(notes) == 3
    assert abs(notes[0]["anchor"] - 1.00) < 1e-9
    assert abs(notes[0]["last_attack"] - 1.01) < 1e-9
    assert abs(notes[0]["start"] - 0.995) < 1e-9       # anchor - 5 ms
    # each note ends exactly where the next begins: no gaps, no overlaps
    assert abs(notes[0]["end"] - notes[1]["start"]) < 1e-12
    assert abs(notes[1]["end"] - notes[2]["start"]) < 1e-12
    assert abs(notes[2]["end"] - 3.0) < 1e-9


def test_decay_budget_uses_last_attack_of_previous_group() -> None:
    module = load_module(SCRIPT_PATH)
    groups = [[1.00, 1.08], [1.50]]                    # a flam: 2 attacks
    notes = module.note_bounds(groups, window_end=2.0)
    b = module.decay_budget(notes[1], notes[0])
    # note 1 starts at 1.495; pulling back must stop at the flam's LAST
    # attack (1.08), not its anchor (1.00), and keep a preroll clear of it:
    # 1.495 - 1.08 - 0.005 = 0.410
    assert abs(b - 0.410) < 1e-9, b
    assert module.decay_budget(notes[0], None) == float("inf")


# A one-sample marker is not survivable: nearest-neighbour resampling can drop
# it or smear it across two output samples. 1 ms is wide enough to survive any
# rate conversion and far narrower than a note.
_MARKER_SEC = 0.001


def make_impulse_source(sr, dur, attacks, body=0.30):
    """Source where every attack carries a unique amplitude id (1.0, 2.0, ...).

    Counting anonymous clicks cannot distinguish "attack moved" from "attack
    duplicated"; unique amplitudes can.
    """
    n = int(dur * sr)
    samples = [0.0] * n
    ids = []
    width = max(2, int(_MARKER_SEC * sr))
    for k, t in enumerate(attacks):
        # Powers of two: at a crossfade two pieces are summed, and no sum of
        # markers can ever equal another marker, so a coincidence cannot be
        # mistaken for a real hit.
        ident = float(2 ** k)
        i = int(t * sr)
        for w in range(width):
            if 0 <= i + w < n:
                samples[i + w] = ident
        ids.append(ident)
        # decaying body so the detector sees a real note, never as tall as an id
        for j in range(1, int(body * sr)):
            if i + j < n:
                samples[i + j] += 0.25 * (1.0 - j / (body * sr))
    return samples, ids


def count_attack_hits(rendered, ident, tol=0.35, gap_samples=8):
    """How many DISTINCT times a given attack id sounds in a rendered timeline.

    Counts clusters, not samples: one marker spans several samples and
    resampling can stretch it, so sample counting would report phantom repeats.
    The tolerance absorbs the decaying body (<=0.25) that a crossfade adds on
    top of the marker.
    """
    hits = 0
    run = False
    silent = 0
    for v in rendered:
        if abs(v - ident) < tol:
            if not run:
                hits += 1
            run, silent = True, 0
        elif run:
            silent += 1
            if silent > gap_samples:
                run = False
    return hits


def _click_track(sr, dur_s, attack_times, amp=0.5, click_len=200):
    """Silence with short bursts at the given times - a detectable transient."""
    buf = [0.0] * int(dur_s * sr)
    for t in attack_times:
        start = int(t * sr)
        for i in range(click_len):
            if start + i < len(buf):
                buf[start + i] = amp * (1.0 - i / float(click_len))
    return buf


def test_auto_moves_a_segment_not_the_whole_item() -> None:
    """The user-reported bug: auto mode must not shift the entire file."""
    import _reaper_fakes as F
    module = load_module(SCRIPT_PATH)
    proj = F.FakeProject(bpm=120.0)   # 1/16 grid = 0.125 s
    tr = proj.add_track()
    sr = 22050
    # one attack 20 ms late relative to the 10.5 s grid line
    samples = _click_track(sr, 2.0, [0.52])
    it = tr.add_item(position=10.0, length=2.0, samples=samples)
    it.selected = True
    F.install_reaper_fakes(module, proj)
    rep = module._run_in_reaper({"grid_threshold_ms": 15.0, "mode": "snap",
                                 "transient_source": "auto",
                                 "grid_choice": "1/16",
                                 "include_triplets": False})
    assert rep["notes_aligned"] >= 1, "the late attack should be corrected"
    # the ORIGINAL item must still start where it did: only a carved-out
    # segment may move
    assert abs(it.position - 10.0) < 1e-9, \
        "the source item moved as a whole - this is the reported bug"
    # and the edit must have produced more items than we started with
    assert len(tr.items) > 1, "a segment should have been split out"


def test_skipped_counts_every_ignored_item() -> None:
    import _reaper_fakes as F
    module = load_module(SCRIPT_PATH)
    proj = F.FakeProject()
    tr = proj.add_track()
    audio = tr.add_item(position=1.0, length=1.0)
    midi = tr.add_item(position=3.0, length=1.0, src_type="MIDI")
    stretched = tr.add_item(position=5.0, length=1.0, playrate=1.5)
    for it in (audio, midi, stretched):
        it.selected = True
    proj.time_selection = (0.0, 10.0)
    F.install_reaper_fakes(module, proj)
    rep = module._run_in_reaper({"grid_threshold_ms": 15.0, "mode": "snap",
                                 "transient_source": "splits",
                                 "grid_choice": "1/16",
                                 "include_triplets": False})
    assert rep["skipped"] == 2, \
        "MIDI and stretched items must both be counted, got {}".format(rep["skipped"])


def test_dead_planning_helpers_are_gone() -> None:
    module = load_module(SCRIPT_PATH)
    assert not hasattr(module, "_split_item_boundaries"), \
        "unused helper must be removed, not left as dead code"


def test_accessor_released_on_error() -> None:
    import _reaper_fakes as F
    module = load_module(SCRIPT_PATH)
    proj = F.FakeProject()
    tr = proj.add_track()
    it = tr.add_item(position=0.0, length=1.0)
    F.install_reaper_fakes(module, proj)

    def boom(*a, **k):
        raise RuntimeError("read failed")

    module.RPR_GetAudioAccessorSamples = boom
    try:
        module._read_take_samples(it.take, 0.0, 1.0)
    except RuntimeError:
        pass
    assert proj.accessors and all(a.destroyed for a in proj.accessors), \
        "accessor must be destroyed even when reading raises"


def test_frange_rejects_nonpositive_step() -> None:
    module = load_module(SCRIPT_PATH)
    for bad in (0.0, -0.25):
        try:
            module._frange_qn(0.0, 4.0, bad)
        except ValueError:
            continue
        raise AssertionError("non-positive step must raise, not hang")


def test_adaptive_lag_resets_per_track() -> None:
    import _reaper_fakes as F
    module = load_module(SCRIPT_PATH)
    proj = F.FakeProject(bpm=120.0)
    t1, t2 = proj.add_track(), proj.add_track()
    # i1 is late but WITHIN tolerance -> it finalizes a positive prev_lag of
    # 10 ms. i2 is on another track and late beyond tolerance: if the lag leaks
    # across the track boundary, adaptive mode lands it on grid+10ms (2.010)
    # instead of snapping it to the grid (2.000).
    i1 = t1.add_item(position=1.010, length=0.4)
    i2 = t2.add_item(position=2.020, length=0.4)
    for it in (i1, i2):
        it.selected = True
    proj.time_selection = (0.0, 10.0)
    F.install_reaper_fakes(module, proj)
    module._run_in_reaper({"grid_threshold_ms": 15.0, "mode": "adaptive",
                           "transient_source": "splits", "grid_choice": "1/16",
                           "include_triplets": False})
    assert abs(i2.position - 2.000) < 1e-6, \
        "on-grid item must not be pushed out by another track's lag"


def test_segment_collision_detection() -> None:
    module = load_module(SCRIPT_PATH)
    f = module.segment_collides
    # segment [1.00,1.035] moved -0.20 lands on material occupied at [0.0,0.99]
    assert f(1.0, 1.035, -0.20, [(0.0, 0.99)]) is True
    # same segment moved -0.005 stays clear
    assert f(1.0, 1.035, -0.005, [(0.0, 0.99)]) is False
    # no occupied regions -> never collides
    assert f(1.0, 1.035, -5.0, []) is False


def test_report_flags_are_computed() -> None:
    module = load_module(SCRIPT_PATH)
    report = module.run_grid_align({"headless": True})
    assert set(report) >= {"notes_aligned", "skipped", "new_overlaps",
                           "gaps_unfilled"}
    assert isinstance(report["new_overlaps"], int)
    assert isinstance(report["gaps_unfilled"], int)


def test_group_span_and_count_caps() -> None:
    module = load_module(SCRIPT_PATH)
    # dense roll: every attack within the gap, would form ONE group without caps
    times = [i * 0.02 for i in range(20)]
    groups = module.group_transients(times, gap_s=0.05,
                                     max_span_s=0.12, max_count=4)
    assert len(groups) > 1, "caps must break a dense chain into several groups"
    for g in groups:
        assert len(g) <= 4
        assert (g[-1] - g[0]) <= 0.12 + 1e-9


def test_group_caps_default_off() -> None:
    module = load_module(SCRIPT_PATH)
    times = [0.0, 0.02, 0.04]
    assert module.group_transients(times, gap_s=0.05) == [[0.0, 0.02, 0.04]]


def test_triplet_family_is_not_superset() -> None:
    module = load_module(SCRIPT_PATH)
    cfg = {"fine_qn": 0.25, "include_triplets": True,
           "qn_start": 0.0, "qn_end": 2.0}
    fam = module.build_grid_candidates_qn(cfg)
    straight = set(round(x, 6) for x in fam["straight"])
    triplet = set(round(x, 6) for x in fam["triplet"])
    # 1/16 triplet step must be 1/6 QN, not 1/12 QN
    assert abs((fam["triplet"][1] - fam["triplet"][0]) - 0.25 * 2.0 / 3.0) < 1e-9
    # families must be distinguishable, otherwise family choice is meaningless
    assert not straight <= triplet, "straight must not be a subset of triplet"


def test_family_choice_prefers_straight_under_jitter() -> None:
    module = load_module(SCRIPT_PATH)
    cfg = {"fine_qn": 0.25, "include_triplets": True,
           "qn_start": 0.0, "qn_end": 4.0}
    fam = module.build_grid_candidates_qn(cfg)
    # straight 1/16 material with human jitter must stay straight
    jittered = [0.25 + 0.03, 0.5 - 0.04, 0.75 + 0.05, 1.0 - 0.03]
    assert module.choose_family_for_group(jittered, fam) == "straight"
    # genuine triplet material must still be detected
    third = 0.25 * 2.0 / 3.0
    trips = [third, 2 * third, 4 * third, 5 * third]
    assert module.choose_family_for_group(trips, fam) == "triplet"


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
    for key in ("notes_total", "notes_aligned", "notes_in_tolerance",
                "refused_max_move", "refused_monotonic", "refused_window",
                "refused_foreign", "refused_decay_budget",
                "seams_trimmed", "seams_pulled",
                "gaps_unfilled", "gaps_unfilled_seconds",
                "new_overlaps", "skipped"):
        assert key in report, (key, report)
    assert report["new_overlaps"] == 0
    assert report["gaps_unfilled"] == 0
    assert isinstance(report["notes_aligned"], int)


def test_plan_corrections_chain() -> None:
    module = load_module(SCRIPT_PATH)
    fam = [0.0, 0.5, 1.0, 1.5]          # straight candidates in QN
    qn_of_time = lambda t: t            # 1 QN == 1 sec for the test
    time_of_qn = lambda q: q
    # first behind by 0.04 (snap), second behind by 0.04 with prev_lag 0 -> snap
    edits, _lag = module.plan_corrections(
        [0.54, 1.04], [fam, fam], qn_of_time, time_of_qn,
        threshold_s=0.015, mode="adaptive", grid_step_for=lambda q: 0.5,
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
    edits, _lag = module.plan_corrections(
        [0.010, 1.040], [fam, fam], ident, ident,
        threshold_s=0.015, mode="adaptive", grid_step_for=lambda q: 1.0,
    )
    assert len(edits) == 1, edits
    assert abs(edits[0]["move"] - (-0.030)) < 1e-9, edits

    # guard-skip: a move larger than grid_step produces NO edit.
    #   t=0.5, nearest grid 0.0, delta 0.5 > tol; snap move -0.5; abs>0.1 -> skip
    skipped, _lag2 = module.plan_corrections(
        [0.5], [fam], ident, ident,
        threshold_s=0.015, mode="snap", grid_step_for=lambda q: 0.1,
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
        "grid": "1/16", "triplets": False, "seam": "crossfade"}

    # round-trip
    module._save_defaults({"threshold_ms": 22, "source": "splits",
                           "mode": "adaptive", "grid": "1/32", "triplets": True,
                           "seam": "butt"})
    assert module._load_defaults() == {
        "threshold_ms": 22, "source": "splits", "mode": "adaptive",
        "grid": "1/32", "triplets": True, "seam": "butt"}

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
                  "ui": {"thr": 22, "src": 1, "mode": 1, "grid": 3, "trip": True,
                         "seam": 0}}
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
        "butt_joint": False,              # seam index 0 == crossfade
    }
    assert calls["saved"]["mode"] == "adaptive" and calls["saved"]["grid"] == "1/32"
    assert calls["saved"]["seam"] == "crossfade"


def test_dialog_cancel_and_redefer() -> None:
    module = load_module(SCRIPT_PATH)
    from _reaper_fakes import FakeImGui
    calls = {"run": 0, "defer": 0}
    module._run_in_reaper = lambda cfg, show_report=False: calls.__setitem__("run", calls["run"] + 1)
    module.RPR_defer = lambda s: calls.__setitem__("defer", calls["defer"] + 1)
    module._save_defaults = lambda st: None
    base_ui = {"thr": 15, "src": 0, "mode": 0, "grid": 2, "trip": False,
               "seam": 0}

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
    test_source_label_warns_about_whole_item_move,
    test_auto_moves_a_segment_not_the_whole_item,
    test_note_bounds_are_contiguous,
    test_decay_budget_uses_last_attack_of_previous_group,
    test_monotonic_guard_keeps_order_and_spacing,
    test_seam_style_option_round_trips,
    test_butt_joint_leaves_no_overlap_at_all,
    test_seam_overlap_trims_left_only,
    test_seam_gap_pulls_right_within_budget,
    test_seam_gap_beyond_budget_reports_hole,
    test_corrections_survive_sample_grid_snapping,
    test_corrections_survive_auto_crossfade_on_split,
    test_other_lanes_are_not_obstacles,
    test_dense_material_stays_clean,
    test_property_no_new_overlaps_across_densities,
    test_every_attack_is_audible_exactly_once,
    test_cut_returns_pieces_left_to_right_and_keeps_lane,
    test_failed_cut_leaves_no_orphan,
    test_cut_set_is_k_plus_r_plus_one,
    test_guard_refuses_move_past_decay_budget,
    test_guard_refuses_move_onto_foreign_material,
    test_guard_refuses_move_outside_sentinels,
    test_skipped_counts_every_ignored_item,
    test_dead_planning_helpers_are_gone,
    test_accessor_released_on_error,
    test_frange_rejects_nonpositive_step,
    test_adaptive_lag_resets_per_track,
    test_segment_collision_detection,
    test_report_flags_are_computed,
    test_group_span_and_count_caps,
    test_group_caps_default_off,
    test_triplet_family_is_not_superset,
    test_family_choice_prefers_straight_under_jitter,
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
