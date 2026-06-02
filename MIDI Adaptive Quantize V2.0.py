#!/usr/bin/env python3
"""MIDI Adaptive Quantize V2.0 — quantize only off-grid MIDI note starts."""

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

    cfg["fine_qn"] is the already-resolved straight-grid step (see resolve_fine_qn).
    Triplets, when enabled, subdivide that step by 3.
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


MIN_NOTE_TICKS = 1  # never shrink a note below this many PPQ ticks


def quantized_start_ppq(new_start, end, min_ticks=MIN_NOTE_TICKS):
    """New note start in PPQ, or None to skip (would not leave a positive length)."""
    if new_start > end - min_ticks:
        return None
    return new_start


def plan_note_moves(onsets, families, qn_of_time, time_of_qn,
                    grid_step_for, threshold_s, mode, gap_s):
    """Decide grouped note-start moves (seconds), left->right.

    onsets: ascending note start times (project seconds; chords repeat a time).
    Returns a list of {"onsets": [group times], "move": seconds}; only groups
    whose anchor exceeds the threshold (and passes the max-move guard) appear.
    """
    groups = group_transients(onsets, gap_s)
    planned = []
    prev_lag = None
    for g in groups:
        qns = [qn_of_time(t) for t in g]
        fam = select_family_positions(families, choose_family_for_group(qns, families))
        anchor_t = anchor_delta = anchor_grid = anchor_qn = None
        for t, tq in zip(g, qns):
            nearest_qn = min(fam, key=lambda p: abs(p - tq))
            grid_t = time_of_qn(nearest_qn)
            d = t - grid_t
            if anchor_t is None or abs(d) > abs(anchor_delta):
                anchor_t, anchor_delta, anchor_grid, anchor_qn = t, d, grid_t, nearest_qn
        move = compute_move(anchor_delta, threshold_s, mode, prev_lag,
                            grid_step_for(anchor_qn))
        if move is None:
            if abs(anchor_delta) <= threshold_s:
                prev_lag = anchor_delta
            continue
        prev_lag = (anchor_t + move) - anchor_grid
        planned.append({"onsets": list(g), "move": move})
    return planned


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


_EXT_SECT = "MidiAdaptiveQuantize"
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
    mode = g("mode", "snap")
    grid = g("grid", "1/16")
    return {
        "threshold_ms": thr,
        "mode": mode if mode in _MODES else "snap",
        "grid": grid if grid in _GRIDS else "1/16",
        "triplets": g("triplets", "0") not in ("0", "", "off", "no"),
    }


def _save_defaults(st):
    RPR_SetExtState(_EXT_SECT, "threshold_ms", str(st["threshold_ms"]), True)  # noqa: F821
    RPR_SetExtState(_EXT_SECT, "mode", st["mode"], True)                       # noqa: F821
    RPR_SetExtState(_EXT_SECT, "grid", st["grid"], True)                       # noqa: F821
    RPR_SetExtState(_EXT_SECT, "triplets", "1" if st["triplets"] else "0", True)  # noqa: F821


def _open_dialog():
    return None  # replaced in Task 6


def run_quantize(config=None):
    config = config or {}
    if config.get("headless"):
        return {"moved_notes": 0, "skipped_notes": 0, "ends_unchanged": True}
    if config.get("grid_threshold_ms") is not None:
        return _run_in_reaper(config)   # explicit config (automation / live tests)
    return _open_dialog()               # interactive: ReaImGui defer loop



def _note_count(take):
    # wrapper echoes params: (retval, take, notecnt, cc, text)
    return RPR_MIDI_CountEvts(take, 0, 0, 0)[2]  # noqa: F821


def _get_note(take, i):
    """Note i as a dict, or None if not found. Wrapper return shape:
    (retval, take, idx, selected, muted, startppq, endppq, chan, pitch, vel)."""
    r = RPR_MIDI_GetNote(take, i, 0, 0, 0, 0, 0, 0, 0)  # noqa: F821
    if not r[0]:
        return None
    return {"sel": r[3], "muted": r[4], "start": r[5], "end": r[6],
            "chan": r[7], "pitch": r[8], "vel": r[9]}


def _active_editor_selected_notes():
    """(take, [note indices]) for selected notes in the active MIDI editor, or (None, [])."""
    ed = RPR_MIDIEditor_GetActive()  # noqa: F821
    if not ed:
        return None, []
    take = RPR_MIDIEditor_GetTake(ed)  # noqa: F821
    if not take or not RPR_TakeIsMIDI(take):  # noqa: F821
        return None, []
    sel = [i for i in range(_note_count(take))
           if (_get_note(take, i) or {}).get("sel")]
    return (take, sel) if sel else (None, [])


def _selected_midi_takes():
    """List of takes for selected MIDI items."""
    out = []
    for i in range(RPR_CountSelectedMediaItems(0)):  # noqa: F821
        take = RPR_GetActiveTake(RPR_GetSelectedMediaItem(0, i))  # noqa: F821
        if take and RPR_TakeIsMIDI(take):  # noqa: F821
            out.append(take)
    return out


def _time_selection():
    r = RPR_GetSet_LoopTimeRange(False, False, 0.0, 0.0, False)  # noqa: F821
    fs = [x for x in r if isinstance(x, float)]
    return (fs[0], fs[1]) if len(fs) >= 2 and fs[1] > fs[0] + 1e-4 else None


def _quantize_take(take, cfg, note_indices, time_sel):
    """Decide+apply moves for one take. Returns (moved, skipped)."""
    grid_qn = RPR_MIDI_GetGrid(take, 0.0, 0.0)[0]  # noqa: F821  (QN)
    qn_of_time = lambda t: RPR_TimeMap2_timeToQN(0, t)          # noqa: F821,E731
    time_of_qn = lambda q: RPR_TimeMap2_QNToTime(0, q)         # noqa: F821,E731
    straight_qn = resolve_fine_qn(cfg["grid_choice"], grid_qn)
    fine_qn = straight_qn / 3.0 if cfg["include_triplets"] else straight_qn
    grid_step_for = lambda q0: time_of_qn(q0 + fine_qn) - time_of_qn(q0)  # noqa: E731

    # gather (index, onset_time, end_ppq), filtered to time selection if any
    notes = []
    for i in note_indices:
        nt = _get_note(take, i)
        if nt is None:
            continue
        t = RPR_MIDI_GetProjTimeFromPPQPos(take, nt["start"])  # noqa: F821
        if time_sel and not (time_sel[0] <= t <= time_sel[1]):
            continue
        notes.append({"i": i, "t": t, "end": nt["end"], "note": nt})
    if not notes:
        return 0, 0
    notes.sort(key=lambda n: n["t"])
    onsets = [n["t"] for n in notes]

    qn_lo = qn_of_time(min(onsets))
    q0 = math.floor(qn_lo / straight_qn) * straight_qn  # align to chosen fine grid
    families = build_grid_candidates_qn({
        "fine_qn": straight_qn, "include_triplets": cfg["include_triplets"],
        "qn_start": q0, "qn_end": qn_of_time(max(onsets)) + straight_qn})

    gap_s = max(0.01, 0.5 * grid_step_for(q0))
    plans = plan_note_moves(onsets, families, qn_of_time, time_of_qn,
                            grid_step_for, cfg["grid_threshold_ms"] / 1000.0,
                            cfg["mode"], gap_s)
    move_by_t = {}
    for p in plans:
        for t in p["onsets"]:
            move_by_t[round(t, 9)] = p["move"]

    moved = skipped = 0
    RPR_MIDI_DisableSort(take)  # noqa: F821
    for n in notes:
        mv = move_by_t.get(round(n["t"], 9))
        if mv is None:
            continue
        new_sppq = RPR_MIDI_GetPPQPosFromProjTime(take, n["t"] + mv)  # noqa: F821
        guarded = quantized_start_ppq(new_sppq, n["end"])
        if guarded is None:
            skipped += 1
            continue
        nt = n["note"]
        RPR_MIDI_SetNote(take, n["i"], nt["sel"], nt["muted"], guarded, n["end"],  # noqa: F821
                         nt["chan"], nt["pitch"], nt["vel"], True)
        moved += 1
    RPR_MIDI_Sort(take)  # noqa: F821
    return moved, skipped


def _undo_begin():
    if "RPR_Undo_BeginBlock2" in globals():
        RPR_Undo_BeginBlock2(0)  # noqa: F821
    else:
        RPR_Undo_BeginBlock()  # noqa: F821


def _undo_end(label):
    # MIDI-API edits (MIDI_SetNote) land in the undo history only if the state
    # change is explicitly registered: MarkProjectDirty + Undo_OnStateChange2.
    # A bare Undo_BeginBlock/EndBlock pair does NOT record them ("undo doesn't
    # save"). Guarded with globals() so headless tests / older APIs degrade safely.
    if "RPR_MarkProjectDirty" in globals():
        RPR_MarkProjectDirty(0)  # noqa: F821
    if "RPR_UpdateArrange" in globals():
        RPR_UpdateArrange()  # noqa: F821
    if "RPR_Undo_OnStateChange2" in globals():
        RPR_Undo_OnStateChange2(0, label)  # noqa: F821
    elif "RPR_Undo_OnStateChangeEx2" in globals():
        RPR_Undo_OnStateChangeEx2(0, label, -1, -1)  # noqa: F821
    if "RPR_Undo_EndBlock2" in globals():
        RPR_Undo_EndBlock2(0, label, -1)  # noqa: F821
    else:
        RPR_Undo_EndBlock(label, -1)  # noqa: F821


def _run_in_reaper(config, show_report=False):
    cfg = config

    time_sel = _time_selection()
    note_take, sel_notes = _active_editor_selected_notes()
    scope = resolve_quant_scope({
        "selected_notes": sel_notes,
        "selected_items": [] if sel_notes else _selected_midi_takes(),
        "time_sel": time_sel})

    if scope["mode"] == "none":
        if show_report:
            RPR_ShowMessageBox(  # noqa: F821
                "Nothing to quantize.\n\nSelect notes in the MIDI editor, or select "
                "MIDI item(s). Nothing selected = no-op.",
                "MIDI Adaptive Quantize V2.0", 0)
        return {"moved_notes": 0, "skipped_notes": 0, "ends_unchanged": True}

    _undo_begin()
    moved = skipped = 0
    try:
        if scope["mode"] == "notes":
            moved, skipped = _quantize_take(note_take, cfg, scope["notes"], None)
        else:
            for take in scope["items"]:
                all_idx = list(range(_note_count(take)))
                m, s = _quantize_take(take, cfg, all_idx, scope["clip"])
                moved += m
                skipped += s
    finally:
        _undo_end("MIDI Adaptive Quantize V2.0")

    report = {"moved_notes": moved, "skipped_notes": skipped, "ends_unchanged": True}
    if show_report:
        RPR_ShowMessageBox(  # noqa: F821
            "MIDI Adaptive Quantize V2.0\n\nMoved: {}\nSkipped (would cross end): {}\n"
            "Mode: {}".format(moved, skipped, cfg["mode"]),
            "MIDI Adaptive Quantize V2.0", 0)
    return report


def main():
    # A REAPER ReaScript runs in an embedded interpreter; NEVER raise SystemExit
    # / sys.exit() / exit() — it routes to Py_Exit and kills the whole REAPER
    # process. Just call run_quantize and return normally.
    run_quantize()


if __name__ == "__main__":
    main()
