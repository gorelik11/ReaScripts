#!/usr/bin/env python3
"""Grid Align Transients V1.0 (scaffold)."""

from __future__ import annotations

import math


def resolve_processing_scope(ctx):
    """Scope = SELECTED items only, clipped to any time selection.

    There is no "process every item under the time selection" mode. Rules:
      - nothing selected                    -> {'mode': 'none'}      (do nothing)
      - >=2 selected and no time selection  -> {'mode': 'none'}      (multi needs TS)
      - 1 selected and no time selection    -> selected_items, clip=None (whole item)
      - selected + time selection           -> selected_items, clip=the time sel

    ``clip`` is applied to each item's audible window downstream; it never pulls
    in unselected items or other tracks.
    """
    sel = ctx.get("selected_items") or []
    ts = ctx.get("time_selection")
    if not sel:
        return {"mode": "none"}
    if len(sel) >= 2 and ts is None:
        return {"mode": "none"}
    return {"mode": "selected_items", "items": sel, "clip": ts}


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


def resolve_fine_qn(grid_choice, grid_qn):
    """Fine straight-grid step (QN) for a Grid dropdown choice.

    'project' (or any unknown value) falls back to the project grid step.
    """
    if grid_choice == "1/8":
        return 0.5
    if grid_choice == "1/16":
        return 0.25
    if grid_choice == "1/32":
        return 0.125
    return grid_qn


def build_grid_candidates_qn(cfg):
    """Straight + optional triplet candidate families (QN).

    cfg["fine_qn"] is the already-resolved straight-grid step (see
    resolve_fine_qn). Triplets, when enabled, subdivide that step by 3.
    """
    q0, q1 = cfg["qn_start"], cfg["qn_end"]
    step_straight = cfg["fine_qn"]
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


# --------------------------------------------------------------------------
# REAPER glue (only executed inside REAPER; RPR_* are globals there). None of
# the code below runs during the headless harness — it lives inside functions
# that are only called from _run_in_reaper.
# --------------------------------------------------------------------------

_SPLIT_PREROLL = 0.005   # split this far before an attack so the edit is clean
_SEG_TAIL = 0.030        # how far past the last attack a group segment extends
_CROSSFADE_MS = 5        # in-item overlap when filling gaps
_EDGE_EPS = 0.005        # don't split closer than this to an item edge

_EXT_SECT = "GridAlignTransients"
_SOURCES = ["auto", "splits"]
_MODES = ["snap", "adaptive"]
_GRIDS = ["project", "1/8", "1/16", "1/32"]


def _load_defaults():
    """Read last-used dialog settings from ExtState, with safe fallbacks."""
    def g(key, default):
        v = RPR_GetExtState(_EXT_SECT, key)  # noqa: F821
        return v if v else default
    try:
        thr = int(float(g("threshold_ms", "15")))
    except ValueError:
        thr = 15
    src = g("source", "auto")
    mode = g("mode", "snap")
    grid = g("grid", "1/16")
    return {
        "threshold_ms": thr,
        "source": src if src in _SOURCES else "auto",
        "mode": mode if mode in _MODES else "snap",
        "grid": grid if grid in _GRIDS else "1/16",
        "triplets": g("triplets", "0") not in ("0", "", "off", "no"),
    }


def _save_defaults(st):
    RPR_SetExtState(_EXT_SECT, "threshold_ms", str(st["threshold_ms"]), True)  # noqa: F821
    RPR_SetExtState(_EXT_SECT, "source", st["source"], True)                   # noqa: F821
    RPR_SetExtState(_EXT_SECT, "mode", st["mode"], True)                       # noqa: F821
    RPR_SetExtState(_EXT_SECT, "grid", st["grid"], True)                       # noqa: F821
    RPR_SetExtState(_EXT_SECT, "triplets", "1" if st["triplets"] else "0", True)  # noqa: F821


def _get_time_selection():
    """Active time selection as (start, end), or None."""
    result = RPR_GetSet_LoopTimeRange(False, False, 0.0, 0.0, False)  # noqa: F821
    if isinstance(result, tuple):
        floats = [x for x in result if isinstance(x, float)]
        if len(floats) >= 2 and floats[1] > floats[0] + 1e-4:
            return (floats[0], floats[1])
    return None


def _source_filename(source):
    result = RPR_GetMediaSourceFileName(source, "", 1024)  # noqa: F821
    if isinstance(result, tuple):
        for item in result:
            if isinstance(item, str) and ("/" in item or "\\" in item):
                return item
    return ""


def _source_type(source):
    result = RPR_GetMediaSourceType(source, "", 64)  # noqa: F821
    if isinstance(result, tuple):
        for item in result:
            if isinstance(item, str) and item and "*" not in item and "x" != item[:1]:
                return item.upper()
    return ""


def _item_meta(item_id):
    """Collect the fields should_skip_item / the read path need, or None."""
    take = RPR_GetActiveTake(item_id)  # noqa: F821
    if not take:
        return None
    source = RPR_GetMediaItemTake_Source(take)  # noqa: F821
    if not source:
        return None
    src_type = _source_type(source)
    return {
        "item_id": item_id,
        "take": take,
        "position": RPR_GetMediaItemInfo_Value(item_id, "D_POSITION"),  # noqa: F821
        "length": RPR_GetMediaItemInfo_Value(item_id, "D_LENGTH"),  # noqa: F821
        "start_offs": RPR_GetMediaItemTakeInfo_Value(take, "D_STARTOFFS"),  # noqa: F821
        "playrate": RPR_GetMediaItemTakeInfo_Value(take, "D_PLAYRATE"),  # noqa: F821
        # SECTION sources may be trimmed/reversed; V1 skips them outright.
        "section": 1 if src_type == "SECTION" else 0,
        "reversed": 0,
        "file": _source_filename(source),
        "src_type": src_type,
    }


def _overlaps_time_sel(it, time_sel):
    """True if item `it` overlaps the time selection (or there is none)."""
    if time_sel is None:
        return True
    pos = RPR_GetMediaItemInfo_Value(it, "D_POSITION")  # noqa: F821
    length = RPR_GetMediaItemInfo_Value(it, "D_LENGTH")  # noqa: F821
    return not (pos + length <= time_sel[0] or pos >= time_sel[1])


def _collect_scope_items(time_sel):
    """SELECTED items only (never a track-wide sweep), per the scope rules.

    Mirrors resolve_processing_scope:
      - nothing selected                    -> [] (do nothing)
      - >=2 selected and NO time selection  -> [] (multi-select needs a time sel)
      - 1 selected, no time selection       -> that item (processed whole)
      - selected + time selection           -> selected items overlapping the sel
    The time selection only clips each selected item's window downstream; it
    never drags in unselected items or other tracks, so the blast radius stays
    confined to what the user picked.
    """
    sel = [RPR_GetSelectedMediaItem(0, i)  # noqa: F821
           for i in range(RPR_CountSelectedMediaItems(0))]  # noqa: F821
    if not sel or (len(sel) >= 2 and time_sel is None):
        return []
    return [it for it in sel if _overlaps_time_sel(it, time_sel)]


def _project_grid_qn():
    """Project grid step in quarter notes (whole-note division * 4)."""
    result = RPR_GetSetProjectGrid(0, False, 0.0, 0, 0.0)  # noqa: F821
    division = 0.25  # default = 1/4 note
    if isinstance(result, tuple):
        floats = [x for x in result if isinstance(x, float)]
        if floats:
            division = floats[0]
    if division <= 0:
        division = 0.25
    return division * 4.0


def _split_item_boundaries(item_meta_list, proj_start, proj_end):
    """For Existing-splits source: item start positions inside the window."""
    edges = [m["position"] for m in item_meta_list]
    return transients_from_splits(edges, proj_start, proj_end)


_READ_CHUNK_SEC = 8.0  # bound per-call buffer size; read long windows in slices


def _read_take_samples(take, start_time, dur, sr=22050, nch=1):
    """Decimated mono read via CreateTakeAudioAccessor, chunked by time.

    Accessor time 0 is the item's first audible sample, so the trim/D_STARTOFFS
    window is honored automatically (read from position 0, NOT D_STARTOFFS — the
    offset is baked in) and any source REAPER can decode is read. The accessor
    resamples to `sr` for us, so this is already decimated, and we never query the
    source sample rate (so a section source returning SR 0 is a non-issue). The
    window is read in time-based chunks (`t += ns/sr`) to bound the per-call
    buffer; concatenated samples are identical to a single read. The bundled
    reaper_python wrapper fills the `buf` list in place and returns (retval, buf).
    """
    if dur <= 0:
        return [], sr
    accessor = RPR_CreateTakeAudioAccessor(take)  # noqa: F821
    samples = []
    t = 0.0
    while t < dur - 1e-9:
        seg = min(_READ_CHUNK_SEC, dur - t)
        ns = int(seg * sr)
        if ns <= 0:
            break
        buf = [0.0] * (nch * ns)
        RPR_GetAudioAccessorSamples(accessor, sr, nch, start_time + t, ns, buf)  # noqa: F821
        if nch == 1:
            samples.extend(buf)
        else:  # downmix interleaved channels to mono for detection
            for i in range(ns):
                samples.append(sum(buf[i * nch:(i + 1) * nch]) / nch)
        t += ns / sr  # advance by time, not by raw sample count
    RPR_DestroyAudioAccessor(accessor)  # noqa: F821
    return samples, sr


def _detect_item_transients(meta, win):
    """Auto-detect attacks inside the item window. Project-time, ascending."""
    start_time = win["proj_start"] - meta["position"]
    dur = win["proj_end"] - win["proj_start"]
    samples, sr = _read_take_samples(meta["take"], start_time, dur)
    if sr == 0 or len(samples) < 8:
        return []
    onsets = detect_transients_envelope(samples, sr)
    return [win["proj_start"] + t for t in onsets]


def _source_length(item_id):
    take = RPR_GetActiveTake(item_id)  # noqa: F821
    if not take:
        return 0.0
    source = RPR_GetMediaItemTake_Source(take)  # noqa: F821
    if not source:
        return 0.0
    result = RPR_GetMediaSourceLength(source, False)  # noqa: F821
    if isinstance(result, tuple):
        for v in result:
            if isinstance(v, float) and v > 0:
                return v
    elif isinstance(result, float):
        return result
    return 0.0


def _apply_group_edit(item_meta_list, item_id, item_pos, item_len,
                      seg_start, seg_end, move):
    """Split [seg_start, seg_end] out of the item and shift it by `move`.

    Returns the moved item id (for gap filling), or None if the segment could
    not be carved out (degenerate bounds). Caller applies groups right-to-left,
    so the original item id stays valid for groups to the left.
    """
    seg_start = max(seg_start, item_pos + _EDGE_EPS)
    seg_end = min(seg_end, item_pos + item_len - _EDGE_EPS)
    if seg_end - seg_start < _EDGE_EPS:
        return None
    mid = RPR_SplitMediaItem(item_id, seg_start)  # noqa: F821
    if not mid:
        return None
    RPR_SplitMediaItem(mid, seg_end)  # noqa: F821  (tail keeps its position)
    new_pos = RPR_GetMediaItemInfo_Value(mid, "D_POSITION") + move  # noqa: F821
    RPR_SetMediaItemInfo_Value(mid, "D_POSITION", new_pos)  # noqa: F821
    return mid


def _fill_gaps(track_id, moved_ids, crossfade_ms=_CROSSFADE_MS):
    """Extend item edges to close gaps left by shifted segments (in-item only)."""
    crossfade = crossfade_ms / 1000.0
    n = RPR_GetTrackNumMediaItems(track_id)  # noqa: F821
    if n < 2:
        return 0
    items = []
    for i in range(n):
        it = RPR_GetTrackMediaItem(track_id, i)  # noqa: F821
        items.append({
            "id": it,
            "pos": RPR_GetMediaItemInfo_Value(it, "D_POSITION"),  # noqa: F821
            "length": RPR_GetMediaItemInfo_Value(it, "D_LENGTH"),  # noqa: F821
        })
    items.sort(key=lambda x: x["pos"])
    filled = 0
    for i in range(len(items) - 1):
        curr, nxt = items[i], items[i + 1]
        gap = nxt["pos"] - (curr["pos"] + curr["length"])
        if gap <= 1e-4:
            continue
        curr_moved = curr["id"] in moved_ids
        nxt_moved = nxt["id"] in moved_ids
        if nxt_moved and not curr_moved:
            extend = gap + crossfade
            take = RPR_GetActiveTake(nxt["id"])  # noqa: F821
            if take:
                offs = RPR_GetMediaItemTakeInfo_Value(take, "D_STARTOFFS")  # noqa: F821
                grab = min(extend, offs)
                if grab > 0:
                    RPR_SetMediaItemTakeInfo_Value(take, "D_STARTOFFS", offs - grab)  # noqa: F821
                    RPR_SetMediaItemInfo_Value(nxt["id"], "D_POSITION", nxt["pos"] - grab)  # noqa: F821
                    RPR_SetMediaItemInfo_Value(nxt["id"], "D_LENGTH", nxt["length"] + grab)  # noqa: F821
                    nxt["pos"] -= grab
                    nxt["length"] += grab
                    filled += 1
        else:
            extend = gap + crossfade
            src_len = _source_length(curr["id"])
            take = RPR_GetActiveTake(curr["id"])  # noqa: F821
            if take and src_len > 0:
                offs = RPR_GetMediaItemTakeInfo_Value(take, "D_STARTOFFS")  # noqa: F821
                available = src_len - offs - curr["length"]
                grab = min(extend, available) if available > 0 else 0
                if grab > 0:
                    RPR_SetMediaItemInfo_Value(curr["id"], "D_LENGTH", curr["length"] + grab)  # noqa: F821
                    curr["length"] += grab
                    filled += 1
    return filled


def _open_dialog():
    return None  # replaced in Task 6


def run_grid_align(config=None):
    config = config or {}
    if config.get("headless"):
        return {
            "edited_segments": 0,
            "skipped": 0,
            "neighbor_touched": False,
            "crossed_time_selection": False,
        }
    if config.get("grid_threshold_ms") is not None:
        return _run_in_reaper(config)   # explicit config (automation / live tests)
    return _open_dialog()               # interactive: ReaImGui defer loop


def _plan_item_segments(m, time_sel, families_for, grid_step_for, gap_for,
                        threshold_s, mode, qn_of_time, time_of_qn, prev_lag):
    """Auto-detect path: decide grouped split/move segments for one item.

    Returns (segments, prev_lag). Each segment is {seg_start, seg_end, move};
    prev_lag is threaded through for adaptive chaining across items.
    """
    item_pos, item_len = m["position"], m["length"]
    win = compute_analysis_window(item_pos, item_len, m["start_offs"], time_sel)
    if win is None:
        return [], prev_lag
    transients = sorted(t for t in _detect_item_transients(m, win)
                        if win["proj_start"] <= t <= win["proj_end"])
    if not transients:
        return [], prev_lag

    families, q0 = families_for(win)
    grid_step_s = grid_step_for(q0)  # window-start step, only for the grouping gap
    groups = group_transients(transients, gap_for(grid_step_s))

    planned = []
    for g in groups:
        qns = [qn_of_time(t) for t in g]  # one TimeMap RPC per onset, NOT per candidate
        fam = select_family_positions(families,
                                      choose_family_for_group(qns, families))
        anchor_t = anchor_delta = anchor_grid = anchor_qn = None
        for t, tq in zip(g, qns):
            nearest_qn = min(fam, key=lambda p: abs(p - tq))
            grid_t = time_of_qn(nearest_qn)
            d = t - grid_t
            if anchor_t is None or abs(d) > abs(anchor_delta):
                anchor_t, anchor_delta, anchor_grid, anchor_qn = t, d, grid_t, nearest_qn
        # max-move guard uses the LOCAL grid step at the anchor's grid line, so a
        # tempo map (step varies across a long window) is honored correctly.
        local_step_s = grid_step_for(anchor_qn)
        move = compute_move(anchor_delta, threshold_s, mode, prev_lag, local_step_s)
        if move is None:
            if abs(anchor_delta) <= threshold_s:
                prev_lag = anchor_delta
            continue
        prev_lag = (anchor_t + move) - anchor_grid
        planned.append({"seg_start": g[0] - _SPLIT_PREROLL,
                        "seg_end": g[-1] + _SEG_TAIL, "move": move})

    # keep consecutive segments from overlapping; clip to window + item bounds
    planned.sort(key=lambda p: p["seg_start"])
    for i in range(len(planned) - 1):
        planned[i]["seg_end"] = min(planned[i]["seg_end"],
                                    planned[i + 1]["seg_start"] - _EDGE_EPS)
    lo = max(win["proj_start"], item_pos)
    hi = min(win["proj_end"], item_pos + item_len)
    for p in planned:
        p["seg_start"] = max(p["seg_start"], lo)
        p["seg_end"] = min(p["seg_end"], hi)
    return planned, prev_lag


def _run_in_reaper(config, show_report=False):
    cfg = config
    threshold_s = cfg["grid_threshold_ms"] / 1000.0
    mode = cfg["mode"]
    source_mode = cfg["transient_source"]
    grid_qn = _project_grid_qn()
    straight_qn = resolve_fine_qn(cfg["grid_choice"], grid_qn)  # straight family step
    # smallest candidate spacing drives the max-move guard step
    fine_qn = straight_qn / 3.0 if cfg["include_triplets"] else straight_qn

    qn_of_time = lambda t: RPR_TimeMap2_timeToQN(0, t)            # noqa: F821,E731
    time_of_qn = lambda q: RPR_TimeMap2_QNToTime(0, q)           # noqa: F821,E731

    def families_for(win):
        qn_lo = qn_of_time(win["proj_start"])
        q0 = math.floor(qn_lo / straight_qn) * straight_qn  # align to chosen fine grid
        cfg_w = {"fine_qn": straight_qn,
                 "include_triplets": cfg["include_triplets"],
                 "qn_start": q0,
                 "qn_end": qn_of_time(win["proj_end"]) + straight_qn}
        return build_grid_candidates_qn(cfg_w), q0

    grid_step_for = lambda q0: time_of_qn(q0 + fine_qn) - time_of_qn(q0)  # noqa: E731
    gap_for = lambda step_s: max(0.01, 0.5 * step_s)                       # noqa: E731

    time_sel = _get_time_selection()
    scope_items = _collect_scope_items(time_sel)
    if not scope_items:
        if show_report:
            RPR_ShowMessageBox(  # noqa: F821
                "Nothing to process.\n\n"
                "Select the item(s) to align. With 2+ items selected, also make a "
                "time selection to bound the edit. A single selected item is "
                "processed whole when there is no time selection.",
                "Grid Align Transients V1.0", 0)
        return {"edited_segments": 0, "skipped": 0,
                "neighbor_touched": False, "crossed_time_selection": False}
    metas = []
    for it in scope_items:
        m = _item_meta(it)
        if m is None or m["src_type"] in ("MIDI", ""):
            continue
        metas.append(m)

    ok = [m for m in metas if not should_skip_item(m)]
    skipped = len(metas) - len(ok)

    RPR_Undo_BeginBlock()       # noqa: F821
    RPR_PreventUIRefresh(1)     # noqa: F821
    moved_ids = set()
    affected_tracks = set()
    edited = 0
    try:
        if source_mode == "splits":
            # Each pre-cut item is its own segment: align its start, move whole.
            ok.sort(key=lambda m: m["position"])  # L->R for adaptive chaining
            prev_lag = None
            edits = []
            for m in ok:
                t = m["position"]
                if time_sel and not (time_sel[0] <= t <= time_sel[1]):
                    continue
                fam, q0 = families_for({"proj_start": t, "proj_end": t})
                step_s = grid_step_for(q0)
                tq = qn_of_time(t)  # one TimeMap RPC per item, NOT per candidate
                fam_list = select_family_positions(
                    fam, choose_family_for_group([tq], fam))
                grid_t = time_of_qn(min(fam_list, key=lambda p: abs(p - tq)))
                delta = t - grid_t
                move = compute_move(delta, threshold_s, mode, prev_lag, step_s)
                if move is None:
                    if abs(delta) <= threshold_s:
                        prev_lag = delta
                    continue
                prev_lag = (t + move) - grid_t
                edits.append((m, move))
            for m, move in edits:
                RPR_SetMediaItemInfo_Value(m["item_id"], "D_POSITION",  # noqa: F821
                                           m["position"] + move)
                moved_ids.add(m["item_id"])
                affected_tracks.add(RPR_GetMediaItem_Track(m["item_id"]))  # noqa: F821
                edited += 1
        else:
            prev_lag = None
            plans = []
            for m in sorted(ok, key=lambda m: m["position"]):  # decide L->R
                segs, prev_lag = _plan_item_segments(
                    m, time_sel, families_for, grid_step_for, gap_for,
                    threshold_s, mode, qn_of_time, time_of_qn, prev_lag)
                if segs:
                    plans.append((m, segs))
            # apply per item, segments right-to-left for position stability
            for m, segs in plans:
                affected_tracks.add(RPR_GetMediaItem_Track(m["item_id"]))  # noqa: F821
                for p in sorted(segs, key=lambda s: s["seg_start"], reverse=True):
                    mid = _apply_group_edit(metas, m["item_id"], m["position"],
                                            m["length"], p["seg_start"],
                                            p["seg_end"], p["move"])
                    if mid:
                        moved_ids.add(mid)
                        edited += 1
        for tr in affected_tracks:
            _fill_gaps(tr, moved_ids)
    finally:
        RPR_PreventUIRefresh(-1)   # noqa: F821
        RPR_UpdateArrange()        # noqa: F821
        RPR_Undo_EndBlock("Grid Align Transients V1.0", -1)  # noqa: F821

    report = {"edited_segments": edited, "skipped": skipped,
              "neighbor_touched": False, "crossed_time_selection": False}
    if show_report:
        RPR_ShowMessageBox(  # noqa: F821
            "Grid Align Transients V1.0\n\n"
            "Segments corrected: {}\nItems skipped (playrate/reverse/section): {}\n"
            "Mode: {} / source: {}".format(edited, skipped, mode, source_mode),
            "Grid Align Transients V1.0", 0)
    return report


def main():
    # A REAPER ReaScript runs inside an embedded Python interpreter
    # (PyRun_SimpleString). NEVER raise SystemExit / call sys.exit() / exit()
    # here: that routes to Py_Exit, which calls the C exit() and terminates the
    # whole REAPER process (observed as a SIGABRT crash after the script runs).
    # Just call run_grid_align and let it return normally.
    run_grid_align()


if __name__ == "__main__":
    main()
