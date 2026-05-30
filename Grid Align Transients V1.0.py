#!/usr/bin/env python3
"""Grid Align Transients V1.0 (scaffold)."""

from __future__ import annotations

import math


def resolve_processing_scope(ctx):
    """Pick processing scope: time selection > selected items > full range."""
    if ctx.get("time_selection"):
        return {"mode": "time_selection", "range": ctx["time_selection"]}
    if ctx.get("selected_items"):
        return {"mode": "selected_items", "items": ctx["selected_items"]}
    return {"mode": "full_range", "items": ctx.get("all_items", [])}


def should_skip_item(meta):
    """V1 guards: unsupported playrate, reversed take, or section source."""
    if abs(meta.get("playrate", 1.0) - 1.0) > 1e-9:
        return True
    if meta.get("reversed", 0) == 1:
        return True
    if meta.get("section", 0) == 1:
        return True
    return False


def source_to_project_time(src_t, item_pos, start_offs):
    """Map a source-domain time to project time. Caller must ensure playrate==1."""
    return item_pos + (src_t - start_offs)


def compute_analysis_window(item_pos, item_len, start_offs, time_sel=None):
    """Audible item window in source + project domains, clipped to time_sel.

    Returns dict with src_start/src_end/proj_start/proj_end, or None if the
    time selection does not overlap the item.
    """
    proj_start = item_pos
    proj_end = item_pos + item_len
    if time_sel is not None:
        ts_a, ts_b = time_sel
        proj_start = max(proj_start, ts_a)
        proj_end = min(proj_end, ts_b)
        if proj_end <= proj_start:
            return None
    src_start = start_offs + (proj_start - item_pos)
    src_end = start_offs + (proj_end - item_pos)
    return {
        "src_start": src_start,
        "src_end": src_end,
        "proj_start": proj_start,
        "proj_end": proj_end,
    }


# Fixed internal detector constants (not user-exposed).
_DET_ATT1, _DET_REL1 = 0.001, 0.010   # fast envelope (sec)
_DET_ATT2, _DET_REL2 = 0.007, 0.015   # slow envelope (sec)
_DET_SENSITIVITY = 2.0                # fast/slow ratio to trigger
_DET_RETRIG_MS = 30.0                 # lockout after a trigger
_DET_FLOOR = 0.001                    # ~ -60 dB noise floor


def detect_transients_envelope(samples, sr,
                               sensitivity=_DET_SENSITIVITY,
                               retrig_ms=_DET_RETRIG_MS,
                               floor=_DET_FLOOR):
    """Return attack times (sec from buffer start) via a dual-envelope gate."""
    if not samples:
        return []
    ga1 = math.exp(-1.0 / (sr * _DET_ATT1))
    gr1 = math.exp(-1.0 / (sr * _DET_REL1))
    ga2 = math.exp(-1.0 / (sr * _DET_ATT2))
    gr2 = math.exp(-1.0 / (sr * _DET_REL2))
    retrig_smpls = int(retrig_ms / 1000.0 * sr)
    env1 = abs(samples[0])
    env2 = env1
    retrig = retrig_smpls + 1
    onsets = []
    for i, s in enumerate(samples):
        x = abs(s)
        env1 = x + (ga1 if env1 < x else gr1) * (env1 - x)
        env2 = x + (ga2 if env2 < x else gr2) * (env2 - x)
        if retrig > retrig_smpls:
            if env1 > floor and env2 > 0.0 and (env1 / env2) > sensitivity:
                onsets.append(i / sr)
                retrig = 0
        else:
            # During lockout, hold the slow envelope equal to the fast one so the
            # ratio resets to ~1.0 and cannot re-trigger until lockout expires.
            env2 = env1
            retrig += 1
    return onsets


def transients_from_splits(edge_times, proj_start, proj_end):
    """Keep split boundaries within the analysis window, sorted ascending."""
    return sorted(t for t in edge_times if proj_start <= t <= proj_end)


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


def plan_corrections(transients_proj, candidates_qn_families, qn_of_time,
                     time_of_qn, threshold_s, mode, grid_step_s):
    """Pure decision pass (left-to-right) -> list of {time, move} edits.

    transients_proj: ascending attack times (project seconds).
    candidates_qn_families: the chosen family's candidate positions (QN).
    qn_of_time/time_of_qn: callables wrapping TimeMap2 (injected for testability).
    Returns edits with finalized prev_lag chaining for adaptive mode.
    """
    edits = []
    prev_lag = None
    for t in transients_proj:
        t_qn = qn_of_time(t)
        nearest_qn = min(candidates_qn_families, key=lambda p: abs(p - t_qn))
        grid_t = time_of_qn(nearest_qn)
        curr_delta = t - grid_t
        move = compute_move(curr_delta, threshold_s, mode, prev_lag, grid_step_s)
        if move is None:
            # finalized in tolerance (or guard-skipped): if within tolerance its
            # lag is the current delta, clamped within threshold so the chain
            # never drifts; a guard-skip leaves prev_lag unchanged.
            if abs(curr_delta) <= threshold_s:
                prev_lag = curr_delta
            continue
        final_time = t + move
        prev_lag = final_time - grid_t
        edits.append({"time": t, "move": move, "grid_time": grid_t})
    return edits


def run_grid_align(config=None):
    config = config or {}
    if config.get("headless"):
        return {
            "edited_segments": 0,
            "skipped": 0,
            "neighbor_touched": False,
            "crossed_time_selection": False,
        }
    return _run_in_reaper(config)


def _run_in_reaper(config):
    # NOTE: the live path needs the REAPER API (reaper_python / reapy) imported
    # here at call time; intentionally omitted while this remains an outline.
    # 1. Read dialog (GetUserInputs): grid_threshold_ms, transient_source,
    #    correction_mode, allow_sixteenth, include_triplets.
    # 2. resolve_processing_scope from time selection / selected items / all.
    # 3. For each item (reverse position order), skip via should_skip_item.
    # 4. compute_analysis_window; obtain transients (detect_transients_envelope
    #    on decimated accessor read, OR transients_from_splits).
    # 5. build_grid_candidates_qn; group; choose_family_for_group per group.
    # 6. plan_corrections; apply edits right-to-left within item + time-sel bounds.
    # 7. fill micro-gaps + in-item crossfade; restore selection; single undo block.
    raise NotImplementedError("REAPER path implemented during in-DAW smoke test")


def main() -> int:
    result = run_grid_align()
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
