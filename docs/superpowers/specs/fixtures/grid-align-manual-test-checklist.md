# Grid Align Transients — Manual QA Checklist

- [ ] Straight 1/16 groove, triplets off
- [ ] Triplet groove, triplets on
- [ ] Sparse percussion (few transients)
- [ ] Dense material (close attacks)
- [ ] Multiple selected items with different start positions
- [ ] Trimmed item (non-zero D_STARTOFFS) aligns by audible content
- [ ] Unsupported playrate / reversed / section item warns and is skipped
- [ ] Neighbor item untouched; nothing outside time selection moves
- [ ] Auto-detect: no splits created outside corrections (track stays live)
- [ ] Existing-splits source on a pre-sliced item
- [ ] Adaptive: late-after-late inherits prev lag; rush snaps to grid; first event snaps
- [ ] 44.1k / 48k / 96k material yields consistent correction behavior
- [ ] Single undo reverts the whole operation

## V3 live checks (from the 2026-07-23 combined audit)

Each item below targets one mechanism that made V2 appear to move the whole
file. Run against `Grid Align Transients V3.0.py`.

- [ ] **Whole-item mode is honest.** One long item + `Existing splits (moves
      whole item)`. The item moves as a unit - expected, and the label now says
      so before you click Apply.
- [ ] **Dense roll stays local.** `Auto (detect transients)` on a fast roll or
      hi-hat run. Only short segments around attacks move; the item is NOT
      shifted as a whole. Group caps: no correction unit spans more than 150 ms
      or 4 attacks.
- [ ] **No overlap left behind.** Slow tempo (~40 BPM), grid = project, an
      attack off by ~200 ms. The moved segment must not sit on top of its
      neighbour: the left sibling is trimmed back, leaving a 5 ms crossfade and
      no doubled audio.
- [ ] **Unrelated material untouched.** Place ordinary separate items elsewhere
      on the same track as the target. After quantizing, their positions,
      lengths and start offsets are unchanged (V2 extended them into old gaps).
- [ ] **Time selection is a hard boundary.** With a time selection active, no
      edge moves outside it. If a segment had to be clipped, the report says
      `crossed_time_selection`.
- [ ] **Reversed item is skipped.** Reverse an item (Item properties >
      Reverse), select it, run. It must be skipped and counted in `skipped`.
      *Confirm the assumption:* reverse should surface as a SECTION source.
- [ ] **Attack near the right edge.** Item whose last transient sits ~10 ms from
      the end. The tail split must either succeed or the correction is refused -
      the remainder of the item must never move.
- [ ] **Triplets mean 1/16T.** Grid = 1/16 with triplets on. Verify candidate
      lines fall on 1/16 triplets (1/6 QN), not on 1/32 triplets, and that a
      straight groove with human jitter is NOT pulled onto triplets.
- [ ] **Adaptive stays per track.** Two tracks selected with a time selection.
      A laid-back item on track 1 must not push an on-grid item on track 2.
- [ ] **Dialog survives an error.** Close the window mid-session; no frozen
      dialog, no stuck defer loop.

## V4 live checks

- [ ] **Shaker baseline repeat.** Same 10.5 s selection measured for V3
      (1 item -> 102 items, 48 overlaps). Expect ~59 items and zero new
      overlaps. Query item geometry over MCP, do not eyeball it.
- [ ] **No flams.** Listen to a corrected dense passage: no attack should be
      heard twice. This is the failure the geometry cannot show.
- [ ] **Fixed lanes preserved.** Run on an item inside a fixed item lane
      (REAPER 7 comping). Every resulting piece must stay in that lane.
- [ ] **Seam option.** Run once with Crossfade and once with Butt joint;
      confirm the butt run leaves no overlap at all.
- [ ] **Unrelated items untouched.** Items on the same track that were not
      selected keep their position, length and start offset.
- [ ] **Report honesty.** If the dialog reports unfilled gaps, find them on the
      timeline; if it reports zero, there must be none.
- [ ] **Tonal material.** Run on sustained guitar, not just percussion: listen
      for stutter at seams where decay was duplicated.
- [ ] **Undo.** One Ctrl+Z restores the original item exactly, leaving no
      orphaned fragments (query the item count over MCP, before and after).
