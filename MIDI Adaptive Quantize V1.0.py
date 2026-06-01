#!/usr/bin/env python3
"""MIDI Adaptive Quantize V1.0 — quantize only off-grid MIDI note starts."""

from __future__ import annotations

import math


def _frange_qn(q0, q1, step):
    """Inclusive QN positions from q0 to q1 at the given step."""
    out = []
    n = 0
    q = q0
    while q <= q1 + 1e-9:
        out.append(q)
        n += 1
        q = q0 + n * step
    return out


def build_grid_candidates_qn(cfg):
    """Straight + optional 1/16 + optional triplet candidate families (QN)."""
    q0, q1 = cfg["qn_start"], cfg["qn_end"]
    step_straight = cfg["grid_qn"]
    if cfg.get("allow_sixteenth"):
        step_straight = min(step_straight, 0.25)
    straight = _frange_qn(q0, q1, step_straight)
    triplet = []
    if cfg.get("include_triplets"):
        triplet = _frange_qn(q0, q1, step_straight / 3.0)
    return {"straight": straight, "triplet": triplet}


def choose_family_for_group(group_times_qn, families_qn):
    """Pick the family with lower aggregate abs error; tie-break to straight."""
    def score(points):
        total = 0.0
        for q in group_times_qn:
            nearest = min(points, key=lambda p: abs(p - q))
            total += abs(nearest - q)
        return total

    s = score(families_qn["straight"])
    t = score(families_qn["triplet"]) if families_qn.get("triplet") else float("inf")
    return "straight" if s <= t else "triplet"


def group_transients(transients_proj, gap_s):
    """Group ascending attack times into segments.

    A new group starts whenever the gap to the previous attack exceeds gap_s.
    Returns a list of groups (each a list of times). This is the segmentation the
    orchestrator uses so a cluster of close attacks is corrected as one local
    move instead of fragmenting the item.
    """
    groups = []
    current = []
    for t in transients_proj:
        if current and (t - current[-1]) > gap_s:
            groups.append(current)
            current = []
        current.append(t)
    if current:
        groups.append(current)
    return groups


def select_family_positions(families_qn, name):
    """Return the QN candidate list for the chosen family name ('straight'/'triplet').

    Bridges choose_family_for_group (which returns a name) to plan_corrections
    (which expects the chosen family's QN list).
    """
    return families_qn[name]


def compute_move(curr_delta, threshold, mode, prev_lag, grid_step):
    """Move amount (sec) for one transient, or None to leave it untouched.

    curr_delta > 0 means the transient is behind (late) its nearest grid point.
    prev_lag is the finalized lag of the previous transient (sec), or None.

    Returns None in TWO distinct situations (the caller distinguishes them by
    re-testing ``abs(curr_delta) <= threshold``):
      1. within tolerance  -> no correction needed (clean);
      2. max-move guard     -> a correction is needed but the required move
         exceeds one grid step, so it is skipped to avoid landing on a
         neighbor's hit.
    grid_step may be None to disable the guard (used only in tests / callers
    that have already bounded the move); production always passes a step.
    """
    if abs(curr_delta) <= threshold:
        return None  # within tolerance
    if (mode == "adaptive" and prev_lag is not None
            and curr_delta > 0 and prev_lag > 0):
        target_off = prev_lag           # land at grid + prev_lag
    else:
        target_off = 0.0                # snap to grid
    move = target_off - curr_delta
    if grid_step is not None and abs(move) > grid_step:
        return None  # would cross into a neighbor slot — skip
    return move


def resolve_quant_scope(ctx):
    """Scope precedence: selected notes > selected items (clipped to time sel) > none.

    Selected notes win outright (explicit pick, no clip). Otherwise selected items
    are the unit, with any time selection as a clip bound applied per note window
    downstream. Nothing selected -> do nothing.
    """
    notes = ctx.get("selected_notes") or []
    items = ctx.get("selected_items") or []
    ts = ctx.get("time_sel")
    if notes:
        return {"mode": "notes", "notes": notes, "clip": None}
    if items:
        return {"mode": "items", "items": items, "clip": ts}
    return {"mode": "none"}


def run_quantize(config=None):
    config = config or {}
    if config.get("headless"):
        return {"moved_notes": 0, "skipped_notes": 0, "ends_unchanged": True}
    return _run_in_reaper(config)


def _run_in_reaper(config):
    raise NotImplementedError("REAPER path added in Task 7")


def main():
    # A REAPER ReaScript runs in an embedded interpreter; NEVER raise SystemExit
    # / sys.exit() / exit() — it routes to Py_Exit and kills the whole REAPER
    # process. Just call run_quantize and return normally.
    run_quantize()


if __name__ == "__main__":
    main()
