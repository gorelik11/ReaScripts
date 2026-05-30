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


def run_grid_align(config=None):
    return {"status": "stub"}


def main() -> int:
    result = run_grid_align()
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
