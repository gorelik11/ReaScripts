#!/usr/bin/env python3
"""Grid Align Transients V4.0 - adaptive transient quantizer with a ReaImGui dialog."""

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
    """Inclusive QN positions from q0 to q1 at the given step.

    A non-positive step would loop forever (q never advances past q1), hanging
    the whole REAPER process rather than failing (audit P3-4).
    """
    if step <= 0:
        raise ValueError("grid step must be positive, got {!r}".format(step))
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
        # Triplets of the SAME note value as the straight step: three notes in
        # the space of two, i.e. step * 2/3. Using step/3 would produce the next
        # finer triplet family (1/32T for a 1/16 grid) AND would make the
        # straight family a strict subset of it, which degenerates the family
        # choice below into "triplet always wins".
        triplet = _frange_qn(q0, q1, step_straight * 2.0 / 3.0)
    return {"straight": straight, "triplet": triplet}


def choose_family_for_group(group_times_qn, families_qn, margin=0.25):
    """Pick 'straight' or 'triplet' for one group of attacks.

    Positions shared by both families (the triplet's "one") carry no
    information about which family the material belongs to - they are equally
    well explained either way. Only the triplet's 2nd/3rd partials
    discriminate, so the decision is made on distances alone plus a confidence
    margin: triplet must explain the group at least `margin` better in relative
    terms, otherwise straight wins. Without the margin, ordinary human jitter
    flips groups into triplets (audit P1-5).
    """
    def score(points):
        if not points:
            return float("inf")
        total = 0.0
        for q in group_times_qn:
            nearest = min(points, key=lambda p: abs(p - q))
            total += abs(nearest - q)
        return total

    s = score(families_qn["straight"])
    t = score(families_qn["triplet"]) if families_qn.get("triplet") else float("inf")
    if t == float("inf"):
        return "straight"
    if s <= 1e-12:
        return "straight"
    return "triplet" if t < s * (1.0 - margin) else "straight"


def group_transients(transients_proj, gap_s, max_span_s=None, max_count=None):
    """Group ascending attack times into segments.

    A new group starts when the gap to the previous attack exceeds gap_s, or
    when the group would exceed max_span_s in duration or max_count in size.
    The caps stop a dense roll from growing into one segment spanning the whole
    item, which is what made V2 look like it moved the entire file.
    """
    groups = []
    current = []
    for t in transients_proj:
        if current:
            too_far = (t - current[-1]) > gap_s
            too_long = max_span_s is not None and (t - current[0]) > max_span_s
            too_many = max_count is not None and len(current) >= max_count
            if too_far or too_long or too_many:
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

    Early-attack policy (confirmed with the user 2026-07-23): an attack that
    ARRIVES EARLY is always snapped to the grid. Only lateness is treated as
    groove and inherited in adaptive mode - a laid-back feel is musical,
    rushing is not. This asymmetry is deliberate, not an oversight.
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
        return None  # would cross into a neighbor slot - skip
    return move


def segment_collides(seg_start, seg_end, move, occupied):
    """True if the segment, once shifted by `move`, overlaps occupied material.

    `occupied` is a list of (start, end) intervals that still hold audio - the
    parts of the item that were not carved out. V2 applied `move` with no such
    check, so a segment could be dropped on top of its own item's material
    (audit P1-1).
    """
    a = seg_start + move
    b = seg_end + move
    for lo, hi in occupied:
        if a < hi - 1e-9 and b > lo + 1e-9:
            return True
    return False


def plan_corrections(transients_proj, families_per_transient, qn_of_time,
                     time_of_qn, threshold_s, mode, grid_step_for,
                     prev_lag=None):
    """Pure decision pass (left-to-right) -> (edits, prev_lag).

    transients_proj: ascending attack times (project seconds).
    families_per_transient: families_per_transient[i] is the candidate QN list
        chosen for transient i, so each group may use its own family.
    qn_of_time/time_of_qn: callables wrapping TimeMap2 (injected for testability).
    grid_step_for(qn): local grid step in seconds at that QN, so a tempo map is
        honoured per transient rather than once per window.

    This is the ONLY place a correction is decided. In V2 it was dead code while
    the live path re-implemented the same logic inline, so its tests proved
    nothing about what actually ran (audit P2-11).
    """
    edits = []
    for t, fam in zip(transients_proj, families_per_transient):
        t_qn = qn_of_time(t)
        nearest_qn = min(fam, key=lambda p: abs(p - t_qn))
        grid_t = time_of_qn(nearest_qn)
        curr_delta = t - grid_t
        move = compute_move(curr_delta, threshold_s, mode, prev_lag,
                            grid_step_for(nearest_qn))
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
    return edits, prev_lag


# --------------------------------------------------------------------------
# REAPER glue (only executed inside REAPER; RPR_* are globals there). None of
# the code below runs during the headless harness - it lives inside functions
# that are only called from _run_in_reaper.
# --------------------------------------------------------------------------

_SPLIT_PREROLL = 0.005   # split this far before an attack so the edit is clean
_SEG_TAIL = 0.030        # how far past the last attack a group segment extends
_CROSSFADE_MS = 5        # in-item overlap when filling gaps
_EDGE_EPS = 0.005        # don't split closer than this to an item edge
_GROUP_MAX_SPAN = 0.150  # a correction unit never spans more than 150 ms
_GROUP_MAX_COUNT = 4     # ...nor more than 4 attacks
_MIN_NOTE_LEN = 0.025    # a CORRECTED note keeps at least this much room
# REAPER snaps a split to the sample grid, so a piece never starts exactly at
# the requested time. 1 ms is far above that quantisation at any sample rate and
# far below any real note, so it identifies a piece without ambiguity.
_PIECE_MATCH_TOL = 0.001


def note_bounds(groups, window_end, preroll=_SPLIT_PREROLL):
    """Turn attack groups into contiguous note spans.

    A note owns source from its own attack (minus a preroll) up to the next
    note's start, so notes tile the window with no gaps and no overlaps. This
    replaces V3's fixed 35 ms window, which shared no boundary with its
    neighbours and cost two cuts per correction.
    """
    notes = []
    for i, g in enumerate(groups):
        start = g[0] - preroll
        end = (groups[i + 1][0] - preroll) if i + 1 < len(groups) else window_end
        notes.append({"anchor": g[0], "last_attack": g[-1],
                      "start": start, "end": end})
    return notes


def build_cut_set(notes, accepted):
    """Unique cut boundaries needed to free every accepted note.

    A corrected note needs a boundary on each side; adjacent corrections share
    one. For K corrections in R adjacent runs this yields K+R cuts and K+R+1
    items - the exact figure the regression asserts. Notes left alone are never
    cut apart from each other, which is where the item-count saving comes from.
    """
    idx = sorted(a["index"] for a in accepted)
    cuts = set()
    for i in idx:
        cuts.add(round(notes[i]["start"], 9))
        cuts.add(round(notes[i]["end"], 9))
    ordered = sorted(cuts)
    return ordered, len(ordered) + 1


def plan_notes(notes, qn_of_time, time_of_qn, families_per_note, threshold_s,
               mode, grid_step_for, sentinels, obstacles, prev_lag=None):
    """Decide every note's correction in ONE left-to-right pass.

    Acceptance and the adaptive prev_lag chain are resolved together: a refused
    correction must leave the chain exactly as if it had never been proposed.
    Deciding first and filtering afterwards would let a correction that never
    happens set the groove for every note after it.

    Returns (accepted, refusals). Each accepted entry is
    {"index", "move", "target"}; refusals counts reasons.
    """
    lo, hi = sentinels
    accepted = []
    refusals = {"max_move": 0, "monotonic": 0, "window": 0,
                "foreign": 0, "decay_budget": 0}
    # final start of the previous note, so spacing is checked against reality
    prev_final_start = lo
    # Where the previous note's LAST attack ends up. Trimming the left piece
    # must never reach it: a piece can span several uncorrected notes, so
    # over-trimming deletes a hit outright - worse than leaving an overlap.
    prev_final_last_attack = lo
    prev_note = None

    for i, note in enumerate(notes):
        t = note["anchor"]
        fam = families_per_note[i]
        t_qn = qn_of_time(t)
        nearest_qn = min(fam, key=lambda p: abs(p - t_qn))
        grid_t = time_of_qn(nearest_qn)
        delta = t - grid_t
        move = compute_move(delta, threshold_s, mode, prev_lag,
                            grid_step_for(nearest_qn))

        if move is None:
            # in tolerance -> its lag becomes the groove reference;
            # guard-skipped by max-move -> chain untouched
            if abs(delta) <= threshold_s:
                prev_lag = delta
            else:
                refusals["max_move"] += 1
            prev_final_start = note["start"]
            prev_final_last_attack = note["last_attack"]
            prev_note = note
            continue

        new_start = note["start"] + move
        new_end = note["end"] + move
        reason = None

        if new_start < lo - 1e-9 or new_end > hi + 1e-9:
            reason = "window"
        elif new_start - prev_final_start < _MIN_NOTE_LEN - 1e-9:
            reason = "monotonic"
        elif new_start < prev_final_last_attack + _SPLIT_PREROLL - 1e-9:
            # moving here would force the left piece to be trimmed through an
            # attack it still carries
            reason = "monotonic"
        elif move < 0 and -move > decay_budget(note, prev_note) + 1e-9:
            reason = "decay_budget"
        else:
            for o_lo, o_hi in obstacles:
                if new_start < o_hi - 1e-9 and new_end > o_lo + 1e-9:
                    reason = "foreign"
                    break

        if reason is not None:
            refusals[reason] += 1
            # chain and spacing continue from the UNCORRECTED note
            prev_final_start = note["start"]
            prev_final_last_attack = note["last_attack"]
            prev_note = note
            continue

        prev_lag = (t + move) - grid_t
        accepted.append({"index": i, "move": move, "target": t + move})
        prev_final_start = new_start
        prev_final_last_attack = note["last_attack"] + move
        prev_note = note

    return accepted, refusals


def decay_budget(note, prev_note):
    """How far `note` may be pulled back before it re-exposes an attack.

    Pulling a note's left edge back reveals earlier source - the previous
    note's decay. That is safe until the revealed window reaches the previous
    note's LAST attack: a group may hold a flam, and revealing an interior
    grace hit duplicates an attack just as audibly as the anchor would.
    Measured in SOURCE time, so it does not depend on whether the previous note
    was itself corrected.
    """
    if prev_note is None:
        return float("inf")
    # Stop a full preroll SHORT of that attack. Reaching it exactly still makes
    # it audible - the boundary case that produced a real flam in testing.
    return max(0.0, note["start"] - prev_note["last_attack"] - _SPLIT_PREROLL)

_EXT_SECT = "GridAlignTransients"
_SOURCES = ["auto", "splits"]
_MODES = ["snap", "adaptive"]
_GRIDS = ["project", "1/8", "1/16", "1/32"]
_SEAMS = ["crossfade", "butt"]


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
        "seam": g("seam", "crossfade") if g("seam", "crossfade") in _SEAMS
                else "crossfade",
    }


def _save_defaults(st):
    RPR_SetExtState(_EXT_SECT, "threshold_ms", str(st["threshold_ms"]), True)  # noqa: F821
    RPR_SetExtState(_EXT_SECT, "source", st["source"], True)                   # noqa: F821
    RPR_SetExtState(_EXT_SECT, "mode", st["mode"], True)                       # noqa: F821
    RPR_SetExtState(_EXT_SECT, "grid", st["grid"], True)                       # noqa: F821
    RPR_SetExtState(_EXT_SECT, "triplets", "1" if st["triplets"] else "0", True)  # noqa: F821
    RPR_SetExtState(_EXT_SECT, "seam", st["seam"], True)                       # noqa: F821


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
        # REAPER implements take reverse by wrapping the source in a SECTION, so
        # the section guard already covers it. Derive the field from the same
        # fact rather than hardcoding 0, which left the guard silently dead in
        # V1/V2 (audit P2-4). Confirm on the live pass.
        "reversed": 1 if src_type == "SECTION" else 0,
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


_READ_CHUNK_SEC = 8.0  # bound per-call buffer size; read long windows in slices


def _read_take_samples(take, start_time, dur, sr=22050, nch=1):
    """Decimated mono read via CreateTakeAudioAccessor, chunked by time.

    Accessor time 0 is the item's first audible sample, so the trim/D_STARTOFFS
    window is honored automatically (read from position 0, NOT D_STARTOFFS - the
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
    try:
        t = 0.0
        while t < dur - 1e-9:
            seg = min(_READ_CHUNK_SEC, dur - t)
            ns = int(seg * sr)
            if ns <= 0:
                break
            buf = [0.0] * (nch * ns)
            res = RPR_GetAudioAccessorSamples(  # noqa: F821
                accessor, sr, nch, start_time + t, ns, buf)
            # The wrapper returns (retval, buf). A non-positive retval means no
            # data was written; continuing would feed a silent buffer to the
            # detector and look exactly like "no transients here" (audit P2-6).
            if isinstance(res, tuple) and res and isinstance(res[0], int) and res[0] <= 0:
                break
            if nch == 1:
                samples.extend(buf)
            else:  # downmix interleaved channels to mono for detection
                for i in range(ns):
                    samples.append(sum(buf[i * nch:(i + 1) * nch]) / nch)
            t += ns / sr  # advance by time, not by raw sample count
    finally:
        # Must run even if a read raises, or the accessor handle leaks (P2-5).
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


def _restore_lane(src_lane, item_id):
    """Force a produced piece into the source item's lane.

    If SplitMediaItem does not inherit I_FIXEDLANE, a piece landing in the
    wrong lane silently destroys a comp - far worse than any timing artifact.
    Setting it unconditionally is cheap and correct either way.
    """
    try:
        RPR_SetMediaItemInfo_Value(item_id, "I_FIXEDLANE", src_lane)  # noqa: F821
    except Exception:
        pass   # pre-REAPER-7 hosts have no fixed lanes


def _delete_item(item_id):
    """Remove a piece from its track (used only to undo a partial cut set)."""
    tr = RPR_GetMediaItem_Track(item_id)          # noqa: F821
    RPR_DeleteTrackMediaItem(tr, item_id)         # noqa: F821


def _cut_item_at(item_id, cuts):
    """Cut one item at every boundary. All or nothing.

    Cuts are applied RIGHT TO LEFT: SplitMediaItem mutates the item it is given
    into the left remainder and returns the right piece, so working right to
    left keeps `item_id` valid for every remaining boundary. If any cut fails,
    the pieces already made are removed and the original is restored - V3 left
    the successful half behind as an untracked fragment.
    """
    pos = RPR_GetMediaItemInfo_Value(item_id, "D_POSITION")     # noqa: F821
    length = RPR_GetMediaItemInfo_Value(item_id, "D_LENGTH")    # noqa: F821
    try:
        lane = RPR_GetMediaItemInfo_Value(item_id, "I_FIXEDLANE")   # noqa: F821
    except Exception:
        lane = 0.0
    inside = [c for c in sorted(cuts)
              if pos + _EDGE_EPS < c < pos + length - _EDGE_EPS]
    made = []
    for c in reversed(inside):
        piece = RPR_SplitMediaItem(item_id, c)                  # noqa: F821
        if not piece:
            for pc in made:
                _delete_item(pc)
            RPR_SetMediaItemInfo_Value(item_id, "D_POSITION", pos)     # noqa: F821
            RPR_SetMediaItemInfo_Value(item_id, "D_LENGTH", length)    # noqa: F821
            return None
        _restore_lane(lane, piece)
        made.append(piece)
    _restore_lane(lane, item_id)
    return [item_id] + list(reversed(made))


def normalise_pieces(pieces, cuts, item_pos):
    """Force pieces onto their exact cut boundaries, undoing REAPER's own fades.

    With Preferences > Item Fade Defaults > "Split media items: Overlap and
    crossfade" enabled (the default), REAPER pulls each new right-hand piece
    back by half the crossfade and extends the left one, so a fresh cut already
    overlaps before we touch it. Butt joint promises zero overlap, which is
    impossible unless that is undone.

    Position and D_STARTOFFS move together, so no audio shifts - only the frame
    is squared up.
    """
    for j, c in enumerate(cuts):
        if j + 1 >= len(pieces):
            break
        pc = pieces[j + 1]
        pos = RPR_GetMediaItemInfo_Value(pc, "D_POSITION")     # noqa: F821
        delta = c - pos
        if abs(delta) < 1e-12:
            continue
        length = RPR_GetMediaItemInfo_Value(pc, "D_LENGTH")    # noqa: F821
        take = RPR_GetActiveTake(pc)                           # noqa: F821
        if take:
            offs = RPR_GetMediaItemTakeInfo_Value(take, "D_STARTOFFS")   # noqa: F821
            RPR_SetMediaItemTakeInfo_Value(take, "D_STARTOFFS", offs + delta)  # noqa: F821
        RPR_SetMediaItemInfo_Value(pc, "D_POSITION", c)                   # noqa: F821
        RPR_SetMediaItemInfo_Value(pc, "D_LENGTH", max(0.0, length - delta))  # noqa: F821
    if pieces and cuts:
        first_len = cuts[0] - item_pos
        if first_len > 0:
            RPR_SetMediaItemInfo_Value(pieces[0], "D_LENGTH", first_len)  # noqa: F821


def heal_seam(left_id, right_id, budget_s, crossfade_ms=_CROSSFADE_MS,
              butt_joint=False):
    """Resolve one seam between two adjacent pieces.

    Overlap -> trim the LEFT piece's tail. Trimming only removes material, so
    it can never expose an attack.

    Gap -> pull the RIGHT piece back, dropping D_POSITION and D_STARTOFFS by
    the same amount so its attack stays exactly where the correction put it,
    while earlier source (the previous note's decay) becomes audible. Never
    extend the left piece instead: its source continues into the next note, so
    extending it re-exposes that note's attack and produces a flam with
    perfectly clean geometry.

    The pull is capped by `budget_s` (see decay_budget) and by the take's own
    start offset. Anything left over stays silent and is reported.
    """
    cf = 0.0 if butt_joint else crossfade_ms / 1000.0
    l_pos = RPR_GetMediaItemInfo_Value(left_id, "D_POSITION")     # noqa: F821
    l_len = RPR_GetMediaItemInfo_Value(left_id, "D_LENGTH")       # noqa: F821
    r_pos = RPR_GetMediaItemInfo_Value(right_id, "D_POSITION")    # noqa: F821
    r_len = RPR_GetMediaItemInfo_Value(right_id, "D_LENGTH")      # noqa: F821
    out = {"trimmed": False, "pulled": 0.0, "unfilled": 0.0}

    gap = r_pos - (l_pos + l_len)
    if gap < -1e-9:                      # overlap
        # A trim may only SHORTEN. Without the min(), an overlap smaller than
        # the crossfade would extend the left piece instead - and extending a
        # raw edge walks straight into the next note's attack.
        new_len = min(l_len, max(0.0, (r_pos + cf) - l_pos))
        if new_len < l_len:
            RPR_SetMediaItemInfo_Value(left_id, "D_LENGTH", new_len)  # noqa: F821
            out["trimmed"] = True
        return out
    if gap <= 1e-9:
        return out

    take = RPR_GetActiveTake(right_id)                            # noqa: F821
    if not take:
        out["unfilled"] = gap
        return out
    offs = RPR_GetMediaItemTakeInfo_Value(take, "D_STARTOFFS")    # noqa: F821
    want = gap + cf
    pull = min(want, max(0.0, budget_s), max(0.0, offs))
    if pull > 0:
        RPR_SetMediaItemTakeInfo_Value(take, "D_STARTOFFS", offs - pull)   # noqa: F821
        RPR_SetMediaItemInfo_Value(right_id, "D_POSITION", r_pos - pull)   # noqa: F821
        RPR_SetMediaItemInfo_Value(right_id, "D_LENGTH", r_len + pull)     # noqa: F821
        out["pulled"] = pull
    out["unfilled"] = max(0.0, gap - pull)
    return out


def _item_lane(item_id):
    """Fixed-lane index of an item, or 0 on hosts without fixed lanes."""
    try:
        return int(RPR_GetMediaItemInfo_Value(item_id, "I_FIXEDLANE"))  # noqa: F821
    except Exception:
        return 0


def _track_obstacles(track_id, own_ids, lane=None):
    """Intervals owned by items this run does not touch, IN THE SAME LANE.

    On a fixed-lane track (REAPER 7 comping) every lane covers the same
    timeline, so comparing by time alone makes each lane an obstacle to every
    other one - live this refused 141 of 142 corrections and the script
    appeared to do nothing. Material in another lane is not in the way.
    """
    out = []
    n = RPR_GetTrackNumMediaItems(track_id)        # noqa: F821
    for i in range(n):
        it = RPR_GetTrackMediaItem(track_id, i)    # noqa: F821
        if it in own_ids:
            continue
        if lane is not None and _item_lane(it) != lane:
            continue
        pos = RPR_GetMediaItemInfo_Value(it, "D_POSITION")   # noqa: F821
        ln = RPR_GetMediaItemInfo_Value(it, "D_LENGTH")      # noqa: F821
        out.append((pos, pos + ln))
    return out


def _count_overlaps(track_id, tolerance):
    """Overlaps beyond the allowed crossfade, on one track."""
    n = RPR_GetTrackNumMediaItems(track_id)        # noqa: F821
    spans = []
    for i in range(n):
        it = RPR_GetTrackMediaItem(track_id, i)    # noqa: F821
        pos = RPR_GetMediaItemInfo_Value(it, "D_POSITION")   # noqa: F821
        ln = RPR_GetMediaItemInfo_Value(it, "D_LENGTH")      # noqa: F821
        spans.append((pos, pos + ln))
    spans.sort()
    return sum(1 for i in range(len(spans) - 1)
               if spans[i][1] - spans[i + 1][0] > tolerance + 1e-6)


_SOURCE_LABELS = ["Auto (detect transients)",
                  "Existing splits (moves whole item)"]
_MODE_LABELS = ["Snap to grid", "Adaptive (groove)"]
_GRID_LABELS = ["Project grid", "1/8", "1/16", "1/32"]
# Crossfade needs a 5 ms overlap, which REAPER shows as lanes when that view is
# on - and a user mid-comp cannot just switch it off. Butt joint trades a
# possible tiny dip for never producing an overlap at all. The script itself
# never touches a project or view setting.
_SEAM_LABELS = ["Crossfade (5 ms overlap)", "Butt joint (no overlap)"]
# labels are index-aligned with the value lists (_SOURCES/_MODES/_GRIDS); a Combo
# returns the chosen index, so a length mismatch would silently mis-map a dropdown.
assert (len(_SOURCE_LABELS) == len(_SOURCES)
        and len(_MODE_LABELS) == len(_MODES)
        and len(_GRID_LABELS) == len(_GRIDS)
        and len(_SEAM_LABELS) == len(_SEAMS))

_GA = None  # holds {"imgui", "ctx", "ui"} while the dialog is open


def _items(labels):
    """ReaImGui Combo expects null-terminated, null-separated items."""
    return "\0".join(labels) + "\0"


def _open_dialog():
    """Open the ReaImGui settings window; on Apply, run the core once.

    Returns None immediately (the window runs on a defer loop). Any failure to load
    ReaImGui returns None without crashing the host.
    """
    global _GA
    try:
        import os
        import sys
        api = os.path.join(RPR_GetResourcePath(),  # noqa: F821
                           "Scripts", "ReaTeam Extensions", "API")
        if api not in sys.path:
            sys.path.insert(0, api)
        import imgui as _ImGui
    except Exception:
        try:
            RPR_ShowMessageBox(  # noqa: F821
                "ReaImGui is required for the Grid Align dialog.\n\n"
                "Install it via ReaPack:\n"
                "Extensions > ReaPack > Browse packages > search 'ReaImGui'.",
                "Grid Align Transients V4", 0)
        except Exception:
            pass
        return None

    try:
        st = _load_defaults()
        ctx = _ImGui.CreateContext("Grid Align Transients V4")
        _GA = {
            "imgui": _ImGui,
            "ctx": ctx,
            "ui": {
                "thr": st["threshold_ms"],
                "src": _SOURCES.index(st["source"]),
                "mode": _MODES.index(st["mode"]),
                "grid": _GRIDS.index(st["grid"]),
                "trip": st["triplets"],
                "seam": _SEAMS.index(st["seam"]),
            },
        }
        RPR_defer("_ga_frame()")  # noqa: F821
    except Exception:
        _GA = None
    return None


def _ga_frame():
    """One ReaImGui frame. Re-defers itself until Apply / Cancel / window close.

    Wrapped so an exception inside the frame cannot skip the re-defer and leave
    the dialog frozen with no way to close it (audit P2-7).
    """
    global _GA
    if _GA is None:
        return
    try:
        _ga_frame_body(_GA)
    except Exception as exc:
        _GA = None
        try:
            RPR_ShowMessageBox(  # noqa: F821
                "Grid Align dialog error:\n\n{}".format(exc),
                "Grid Align Transients V4.0", 0)
        except Exception:
            pass


def _destroy_ctx(ImGui, ctx):
    """Release the ReaImGui context if this build exposes DestroyContext."""
    try:
        ImGui.DestroyContext(ctx)
    except Exception:
        pass   # older ReaImGui builds clean up when the script instance ends


def _ga_frame_body(g):
    global _GA
    ImGui = g["imgui"]
    ctx = g["ctx"]
    ui = g["ui"]

    visible, open_ = ImGui.Begin(ctx, "Grid Align Transients V4", True)
    apply_clicked = False
    cancel_clicked = False
    if visible:
        _, ui["thr"] = ImGui.InputInt(ctx, "Threshold (ms)", ui["thr"])
        _, ui["src"] = ImGui.Combo(ctx, "Source", ui["src"], _items(_SOURCE_LABELS))
        _, ui["mode"] = ImGui.Combo(ctx, "Mode", ui["mode"], _items(_MODE_LABELS))
        _, ui["grid"] = ImGui.Combo(ctx, "Grid", ui["grid"], _items(_GRID_LABELS))
        _, ui["trip"] = ImGui.Checkbox(ctx, "Include triplet grid", ui["trip"])
        _, ui["seam"] = ImGui.Combo(ctx, "Seam", ui["seam"], _items(_SEAM_LABELS))
        apply_clicked = ImGui.Button(ctx, "Apply")
        ImGui.SameLine(ctx)
        cancel_clicked = ImGui.Button(ctx, "Cancel")
    ImGui.End(ctx)  # ImGui requires End even when Begin returns not-visible

    if apply_clicked:
        thr = int(ui["thr"]) if ui["thr"] and ui["thr"] > 0 else 15
        st = {"threshold_ms": thr, "source": _SOURCES[ui["src"]],
              "mode": _MODES[ui["mode"]], "grid": _GRIDS[ui["grid"]],
              "triplets": bool(ui["trip"]), "seam": _SEAMS[ui["seam"]]}
        _save_defaults(st)
        cfg = {"grid_threshold_ms": float(thr),
               "transient_source": st["source"], "mode": st["mode"],
               "grid_choice": st["grid"], "include_triplets": st["triplets"],
               "butt_joint": st["seam"] == "butt"}
        _GA = None
        _destroy_ctx(ImGui, ctx)
        _run_in_reaper(cfg, show_report=True)
        return
    if cancel_clicked or open_ == 0:
        _GA = None
        _destroy_ctx(ImGui, ctx)
        return
    RPR_defer("_ga_frame()")  # noqa: F821


def _empty_report():
    """Every counter the run can report, so callers never guess a key."""
    return {"notes_total": 0, "notes_aligned": 0, "notes_in_tolerance": 0,
            "refused_max_move": 0, "refused_monotonic": 0, "refused_window": 0,
            "refused_foreign": 0, "refused_decay_budget": 0,
            "refused_unmatched": 0,
            "seams_trimmed": 0, "seams_pulled": 0,
            "gaps_unfilled": 0, "gaps_unfilled_seconds": 0.0,
            "new_overlaps": 0, "skipped": 0}


def run_grid_align(config=None):
    config = config or {}
    if config.get("headless"):
        return _empty_report()
    if config.get("grid_threshold_ms") is not None:
        return _run_in_reaper(config)   # explicit config (automation / live tests)
    return _open_dialog()               # interactive: ReaImGui defer loop


def _group_by_track(metas):
    """Group item metas by their track, preserving first-seen track order.

    Adaptive chaining must not run across tracks, so every caller iterates
    track by track (audit P2-1).
    """
    order = []
    buckets = {}
    for m in metas:
        tr = RPR_GetMediaItem_Track(m["item_id"])  # noqa: F821
        key = id(tr)
        if key not in buckets:
            buckets[key] = (tr, [])
            order.append(key)
        buckets[key][1].append(m)
    return [buckets[k] for k in order]


def _process_item_auto(m, time_sel, families_for, grid_step_for, gap_for,
                       threshold_s, mode, qn_of_time, time_of_qn,
                       obstacles, butt_joint, report):
    """Detect -> plan -> cut once -> move -> heal, for ONE original item.

    Everything is decided before a single cut is made, so the cut set is known
    exactly (K+R+1 pieces) and a failure can abort without leaving fragments.
    """
    item_pos, item_len = m["position"], m["length"]
    win = compute_analysis_window(item_pos, item_len, m["start_offs"], time_sel)
    if win is None:
        return
    transients = sorted(t for t in _detect_item_transients(m, win)
                        if win["proj_start"] <= t <= win["proj_end"])
    if not transients:
        return

    families, q0 = families_for(win)
    groups = group_transients(transients, gap_for(grid_step_for(q0)),
                              max_span_s=_GROUP_MAX_SPAN,
                              max_count=_GROUP_MAX_COUNT)
    notes = note_bounds(groups, win["proj_end"])
    report["notes_total"] += len(notes)

    fams = [select_family_positions(
                families,
                choose_family_for_group([qn_of_time(t) for t in g], families))
            for g in groups]

    sentinels = (max(win["proj_start"], item_pos),
                 min(win["proj_end"], item_pos + item_len))
    # groove is a local property: the chain never crosses an original item
    accepted, refusals = plan_notes(notes, qn_of_time, time_of_qn, fams,
                                    threshold_s, mode, grid_step_for,
                                    sentinels, obstacles, None)
    for key, n in refusals.items():
        report["refused_" + key] += n
    report["notes_in_tolerance"] += (len(notes) - len(accepted)
                                     - sum(refusals.values()))
    if not accepted:
        return

    cuts, _expected = build_cut_set(notes, accepted)
    pieces = _cut_item_at(m["item_id"], cuts)
    if pieces is None:
        return                      # transactional: nothing was moved

    # Map each note to its piece BY CUT ORDER, never by position. A piece's
    # reported start is not the requested cut time: REAPER snaps to the sample
    # grid and, with auto-crossfade on split enabled, pulls the right-hand piece
    # back by the crossfade length. Position matching lost every correction on
    # the live runs (exactly, then within 1 ms). Cut order is exact by
    # construction: _cut_item_at applies the same filter and returns pieces
    # left to right, so inside[j] is the start of pieces[j+1].
    inside = [c for c in sorted(cuts)
              if item_pos + _EDGE_EPS < c < item_pos + item_len - _EDGE_EPS]
    if butt_joint:
        # Butt joint cannot promise zero overlap while REAPER's split
        # auto-crossfade is adding one, so square the frames up first.
        normalise_pieces(pieces, inside, item_pos)
    piece_of_cut = {}
    for j, c in enumerate(inside):
        if j + 1 < len(pieces):
            piece_of_cut[round(c, 9)] = pieces[j + 1]

    def _piece_at(t):
        return piece_of_cut.get(round(t, 9))

    # Map EVERY piece to the note it begins - not just the moved ones. A seam
    # whose right side was left in place still needs its decay budget: without
    # it the pull is unbounded and re-exposes the previous attack.
    # Built before anything moves, while piece starts still equal note starts.
    note_of_piece = {}
    for idx, note in enumerate(notes):
        pc = _piece_at(note["start"])
        if pc is not None:
            note_of_piece[id(pc)] = idx

    moved_any = False
    for a in accepted:
        note = notes[a["index"]]
        pc = _piece_at(note["start"])
        if pc is None:
            report["refused_unmatched"] += 1
            continue
        RPR_SetMediaItemInfo_Value(  # noqa: F821
            pc, "D_POSITION",
            RPR_GetMediaItemInfo_Value(pc, "D_POSITION") + a["move"])  # noqa: F821
        report["notes_aligned"] += 1
        moved_any = True

    if not moved_any:
        # Nothing actually moved: cutting and trimming here would damage the
        # material for no benefit, which is exactly what the first live run did.
        return

    # heal every seam once, left to right over the final sequence
    ordered = sorted(pieces,
                     key=lambda x: RPR_GetMediaItemInfo_Value(x, "D_POSITION"))  # noqa: F821
    for i in range(len(ordered) - 1):
        left, right = ordered[i], ordered[i + 1]
        r_idx = note_of_piece.get(id(right))
        if r_idx is None or r_idx == 0:
            # No known note starts here (or it is the window's first note):
            # there is no proven attack-free room behind it, so do not pull.
            budget = 0.0
        else:
            budget = decay_budget(notes[r_idx], notes[r_idx - 1])
        res = heal_seam(left, right, budget, butt_joint=butt_joint)
        if res["trimmed"]:
            report["seams_trimmed"] += 1
        if res["pulled"] > 0:
            report["seams_pulled"] += 1
        if res["unfilled"] > 1e-6:
            report["gaps_unfilled"] += 1
            report["gaps_unfilled_seconds"] += res["unfilled"]


def _run_in_reaper(config, show_report=False):
    cfg = config
    threshold_s = cfg["grid_threshold_ms"] / 1000.0
    mode = cfg["mode"]
    source_mode = cfg["transient_source"]
    grid_qn = _project_grid_qn()
    straight_qn = resolve_fine_qn(cfg["grid_choice"], grid_qn)  # straight family step
    # Max-move guard must use the straight step. The triplet family is offset,
    # not finer, so it must not shrink the guard.
    fine_qn = straight_qn

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
                "Grid Align Transients V4.0", 0)
        return _empty_report()
    metas = []
    unsupported = 0
    for it in scope_items:
        m = _item_meta(it)
        if m is None or m["src_type"] in ("MIDI", ""):
            # MIDI or unreadable source: report it instead of hiding it (P3-3)
            unsupported += 1
            continue
        metas.append(m)

    ok = [m for m in metas if not should_skip_item(m)]
    skipped = (len(metas) - len(ok)) + unsupported

    RPR_Undo_BeginBlock()       # noqa: F821
    RPR_PreventUIRefresh(1)     # noqa: F821
    moved_ids = set()
    edited = 0
    report = _empty_report()
    try:
        if source_mode == "splits":
            # Each pre-cut item is its own segment: align its start, move whole.
            edits = []
            obstacles_by_track = {}
            for _tr, group in _group_by_track(ok):
                own = set(x["item_id"] for x in group)
                for x in group:
                    lane = _item_lane(x["item_id"])
                    key = (id(_tr), lane)
                    if key not in obstacles_by_track:
                        obstacles_by_track[key] = _track_obstacles(_tr, own, lane)
                    x["_track_key"] = key
                group.sort(key=lambda m: m["position"])  # L->R within the track
                prev_lag = None   # adaptive state never crosses a track boundary
                in_range = [m for m in group
                            if not (time_sel and not
                                    (time_sel[0] <= m["position"] <= time_sel[1]))]
                starts = [m["position"] for m in in_range]
                fams = []
                for t in starts:
                    fam, _q0 = families_for({"proj_start": t, "proj_end": t})
                    tq = qn_of_time(t)  # one TimeMap RPC per item
                    fams.append(select_family_positions(
                        fam, choose_family_for_group([tq], fam)))
                planned, prev_lag = plan_corrections(
                    starts, fams, qn_of_time, time_of_qn, threshold_s, mode,
                    grid_step_for, prev_lag)
                by_time = {e["time"]: e["move"] for e in planned}
                for m in in_range:
                    if m["position"] in by_time:
                        edits.append((m, by_time[m["position"]]))
            for m, move in edits:
                new_pos = m["position"] + move
                new_end = new_pos + m["length"]
                # never land on material this run does not own
                blocked = any(new_pos < o_hi - 1e-9 and new_end > o_lo + 1e-9
                              for o_lo, o_hi
                              in obstacles_by_track.get(m.get("_track_key"), []))
                if blocked:
                    report["refused_foreign"] += 1
                    continue
                RPR_SetMediaItemInfo_Value(m["item_id"], "D_POSITION", new_pos)  # noqa: F821
                moved_ids.add(m["item_id"])
                report["notes_aligned"] += 1
                edited += 1
        else:
            butt_joint = bool(cfg.get("butt_joint"))
            for _tr, group in _group_by_track(ok):
                own = set(x["item_id"] for x in group)
                before = _count_overlaps(_tr, _CROSSFADE_MS / 1000.0)
                lane_cache = {}
                for m in sorted(group, key=lambda x: x["position"]):
                    lane = _item_lane(m["item_id"])
                    if lane not in lane_cache:
                        lane_cache[lane] = _track_obstacles(_tr, own, lane)
                    _process_item_auto(
                        m, time_sel, families_for, grid_step_for, gap_for,
                        threshold_s, mode, qn_of_time, time_of_qn,
                        lane_cache[lane], butt_joint, report)
                after = _count_overlaps(_tr, _CROSSFADE_MS / 1000.0)
                report["new_overlaps"] += max(0, after - before)
    finally:
        RPR_PreventUIRefresh(-1)   # noqa: F821
        RPR_UpdateArrange()        # noqa: F821
        RPR_Undo_EndBlock("Grid Align Transients V4.0", -1)  # noqa: F821

    report["skipped"] = skipped
    if show_report:
        RPR_ShowMessageBox(  # noqa: F821
            "Grid Align Transients V4.0\n\n"
            "Notes aligned: {}\nIn tolerance: {}\n"
            "Notes detected: {}\n"
            "Refused - spacing {}, window {}, neighbour {}, decay {}, max move {},"
            " unmatched {}\n"
            "Seams: {} trimmed, {} pulled\n"
            "Unfilled gaps: {} ({:.3f} s)\n"
            "New overlaps: {}\nItems skipped: {}\n"
            "Mode: {} / source: {}".format(
                report["notes_aligned"], report["notes_in_tolerance"],
                report["notes_total"],
                report["refused_monotonic"], report["refused_window"],
                report["refused_foreign"], report["refused_decay_budget"],
                report["refused_max_move"], report["refused_unmatched"],
                report["seams_trimmed"], report["seams_pulled"],
                report["gaps_unfilled"], report["gaps_unfilled_seconds"],
                report["new_overlaps"], skipped, mode, source_mode),
            "Grid Align Transients V4.0", 0)
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
