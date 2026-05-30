#!/usr/bin/env python3
"""Grid Align Transients V1.0 (scaffold)."""

from __future__ import annotations


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
    """Map a source-domain time to project time (playrate==1, guarded)."""
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


def run_grid_align(config=None):
    return {"status": "stub"}


def main() -> int:
    result = run_grid_align()
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
