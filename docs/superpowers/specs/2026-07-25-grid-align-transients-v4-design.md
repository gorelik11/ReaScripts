# Grid Align Transients V4.0 - design

**Date:** 2026-07-25 (rev 2, rewritten after three independent reviews)
**Status:** design decisions approved by the user; ready for an implementation plan
**Base:** `Grid Align Transients V3.0.py` - live-verified, merged, and left untouched

Rev 2 replaces rev 1's central invariant, which was wrong. See "Rejected: raw
edge extension" for why, so it is not reintroduced later.

## Problem

V3 works musically but its correction mechanism forces manual cleanup.

Measured live (REAPER via MCP, 10.5 s of shaker inside one 218 s item, Auto,
1/16 grid, 15 ms threshold, project tempo 128 BPM):

```
1 item                      ->  102 items
overlaps beyond the 5 ms crossfade:  48   (largest 224 ms)
stacks at an identical position:      2
surplus material:                  2.75 s
```

Detector re-run offline on the same audio: **94 attacks, 59 notes after
grouping, K = 47 corrections in R = 11 adjacent runs.**

Three causes, all structural:

1. **No forward collision check.** Planning walks left to right and tests a
   segment only against segments already planned to its left. A segment moved
   right lands on a neighbour not yet known at planning time.
2. **Seam healing is too local.** `_close_gap_pair` heals only the two siblings
   of one split. At shaker density a moved segment overlaps a *foreign* segment,
   which nobody heals.
3. **Fragmentation is arithmetic.** Each correction carves a ~35 ms window and
   shares no boundary with its neighbours: 2 cuts per correction, always.

## Approved decisions

| Question | Decision |
|---|---|
| Gap payment | **Duplicate decay, hard-limited** - never across an attack |
| Seams | **User-selectable per run:** `Crossfade (5 ms overlap)` (default) or `Butt joint (no overlap)` |
| Project settings | **Never modified by the script** - see "Lanes and project settings" |
| Correction unit | One item per note (attack to next attack), not a fixed window |
| Group anchor | First attack of the group |
| Early attacks | Always snapped to grid; only lateness is inherited as groove |

## Model

Let `S_i` be the anchor (first attack) of note group `i`, and
`B_i = S_i - _SPLIT_PREROLL` its source-time boundary (`_SPLIT_PREROLL` = 5 ms,
unchanged from V3). Note `i` owns source `[B_i, B_{i+1}]`.

A correction `m_i` moves the note's **frame** and keeps its content offset:

```
D_POSITION   = B_i + m_i
D_STARTOFFS  = B_i                (unchanged)
audible attack = B_i + m_i + (S_i - B_i) = S_i + m_i     [target]
```

Frames move with their notes. Between frame `i` and frame `i+1` the seam is
either an overlap (`m_{i+1} < m_i`) or a gap (`m_{i+1} > m_i`).

### The unavoidable trade

After correction the project interval between two attacks is
`(S_{i+1} + m_{i+1}) - (S_i + m_i)`, while the source interval between them is
fixed at `S_{i+1} - S_i`. When the corrected interval is **longer**, no amount of
geometry can fill it from contiguous source without repeating material. The
payment must be chosen explicitly: repeat, silence, or time-stretch. V4 repeats
decay, bounded (see below), and reports whatever it cannot fill.

### Seam policy

**Overlap** (`m_{i+1} < m_i`): trim note `i`'s tail so it ends
`_CROSSFADE_MS` past frame `i+1`'s start. Trimming only removes material, so it
can never expose an attack. Note `i`'s own start is untouched.

**Gap** (`m_{i+1} > m_i`, size `g`): pull frame `i+1`'s left edge back by `g`,
decreasing `D_POSITION` **and** `D_STARTOFFS` by the same `g`, so its attack
stays at its corrected target while `g` seconds of earlier source become
audible. That revealed material is note `i`'s decay - it is duplicated (note `i`
plays it too), but it contains no attack as long as:

```
g <= B_{i+1} - S_{i,last}          # source time, NOT project time
```

where `S_{i,last}` is the **last** attack of group `i` - not its anchor. A group
may hold up to four attacks (a flam), and revealing back past an interior grace
hit duplicates an attack just as audibly as duplicating the anchor.

This budget is fixed in source time and does **not** depend on whether note `i`
was itself corrected, because a correction only ever changes a frame's left side
and content offset - never note `i`'s source end at `B_{i+1}`. Implementations
must compare against raw source attack times, not corrected positions.

Additional limits on the pull: `D_STARTOFFS - g >= 0` (cannot read before the
file start) and the pull may not cross the analysis-window left sentinel.

**Whatever cannot be filled stays silent**, gets crossfaded edges, and is
reported as `gaps_unfilled` with total duration. A run must never claim success
while leaving unreported holes.

Measured budget on the shaker fixture: mean IOI 174 ms, so budget ~169 ms
against a largest actual move of 58 ms - zero violations. The guard is not
redundant, though: in snap mode a move cannot exceed half a grid step (58.6 ms
here) because we snap to the *nearest* line, but Adaptive may reach a full step,
and at IOI < 63 ms even snap exceeds the budget.

### Lanes and project settings

The script **never changes a project or view setting** - not the overlap display,
not lane mode, nothing. Rev 1 leaned on "the user can disable the lane display",
which is not the script's call to make and does not survive contact with real
work: a track may legitimately be in **fixed item lanes** (REAPER 7 comping),
where lanes are structure rather than decoration, and a user mid-comp needs them
visible.

Two distinct REAPER mechanisms must not be conflated:

- **"Show overlapping media items in lanes"** - a view toggle. It is what turned
  V3's deliberate 5 ms crossfade overlaps into visible "floors".
- **Fixed item lanes** - real per-lane organisation of a track's items.

Because a user working in either mode cannot simply switch the display off, the
seam style is a **per-run option** instead of a fixed policy:

- `Crossfade (5 ms overlap)` - default, audio-safe, industry-normal. Costs a 5 ms
  overlap at every seam, visible as lanes when that display is on.
- `Butt joint (no overlap)` - zero overlap ever, so lanes never appear from our
  edits. Costs a possible short amplitude dip on sustained/tonal material,
  because a butt joint with fade-out/fade-in is not a constant-power crossfade.
  Fade length must stay below `_SPLIT_PREROLL` (5 ms) so a fade-in never eats
  into the following attack; assert this relationship in code rather than leaving
  it as a numeric coincidence.

**Lane preservation is a hard requirement.** Every piece produced from an item
must remain in that item's lane. If a track uses fixed item lanes and a split
piece lands in the wrong lane, the script destroys a comp - a far worse outcome
than any timing artifact. **Hypothesis, must be verified live:** whether
`SplitMediaItem` propagates `I_FIXEDLANE` (REAPER 7) to the returned piece, and
whether `D_POSITION` changes preserve it. This cannot be confirmed from
`reaper_python.py`, which passes field names through as unvalidated C strings.
If it is not inherited, V4 must read the source item's lane before cutting and
write it onto every produced piece.

The live checklist gains a comping case: run V4 on an item inside a fixed lane
and confirm every resulting piece stays in that lane.

### Rejected: raw edge extension

Rev 1 said gaps should be filled by extending the **left** neighbour's right
edge, on the reasoning that this reveals more of the previous note's decay. It
does the opposite. The left item's source content continues past `B_{i+1}` into
the *next* note, so extending it reads source `[B_{i+1}, B_{i+1} + g]`, which
contains `S_{i+1} = B_{i+1} + 5 ms`. The old attack keeps sounding at its
original time while the moved copy sounds at the corrected time: a flam, with
perfectly butt-joined geometry and zero overlaps. **Any geometry-only test
reports success.** Because the threshold is 15 ms and the preroll is 5 ms, this
would fire on essentially every rightward correction.

A raw media edge must never be extended across an original attack boundary.

## Guards

All refusals are counted separately and surfaced in the report.

1. **Max move** (from V3): a correction larger than one grid step is refused.
2. **Monotonicity** (new): the corrected order of notes must be preserved, and a
   corrected note must keep at least `_MIN_NOTE_LEN` (25 ms) of room to its
   neighbour. **This acceptance test runs inside the same left-to-right pass
   that finalizes the Adaptive `prev_lag`.** A refused correction must leave the
   chain exactly as if it had never been proposed - V3 updates `prev_lag` inline
   while deciding, so applying monotonicity as a second pass would let a
   correction that never happens poison every later note's groove.
3. **`_MIN_NOTE_LEN` applies only to intervals a correction changes.** A
   pre-existing interval shorter than 25 ms is left alone: `group_transients`
   closes a group at four attacks even when the fifth arrives 5 ms later, so
   attacks at `0, 5, 10, 15, 20 ms` legitimately yield anchors 20 ms apart. A
   global 25 ms invariant is unsatisfiable on valid detector output.
4. **Window sentinels** (new): both analysis-window edges are fixed sentinels
   participating in spacing checks. A move that would place a note start outside
   the legal window is **refused, not post-clipped** - clipping after the
   monotonicity check would silently change note duration and source mapping.
5. **Foreign material is an obstacle.** Items on the track that are not part of
   this run are fixed: any correction whose final frame would overlap one is
   refused. This is what keeps the V3 complaint "it edits unrelated items" from
   returning in a new form.
6. **Source room** on both sides: the backward pull needs `D_STARTOFFS >= g`;
   the tail trim needs enough length left for its own crossfade.

## Scope and modes

**Auto (detect transients)** uses the model above.

**Existing splits (moves whole item)** keeps V3's behaviour - selected items are
already note-items and move whole - but gains guards 1, 2, 4, 5 and the seam
policy **between selected neighbours only**. If the neighbour on either side is
not selected, it is foreign material (guard 5) and a colliding correction is
refused rather than healed. Pre-existing gaps between selected items are
preserved, not filled.

**Multi-item precondition:** selected source items on one track must not overlap
each other. If they do, the run is refused with an explanatory message, because
the "strict sequence" reasoning holds only inside one non-overlapping sequence.
The live acceptance check compares against the **pre-run** overlap set rather
than asserting absolute zero.

## Application order

1. Detect and group attacks. Detection runs **once**, up front, on the original
   item - never re-run per resulting piece.
2. Build note anchors plus fixed window sentinels.
3. Plan corrections and resolve all guards in one left-to-right pass, producing
   an accepted set with a reason code per refusal.
4. Build the complete unique cut set: `K + R` cuts for `K` accepted corrections
   in `R` adjacent runs, so exactly `K + R + 1` items per original item. On the
   shaker fixture: `47 + 11 + 1 = 59` items against V3's measured 102, a 42 %
   reduction. The regression asserts this exact number, not "roughly half".
5. Validate every planned cut and seam operation **before** touching audio.
6. Cut the original item **right to left**. `SplitMediaItem` mutates the passed
   item into the left remainder and returns the right piece, so cutting right to
   left keeps the original handle valid for every remaining boundary. This is
   V3's existing convention.
7. Move accepted frames; apply the seam policy; leave crossfades at 5 ms.
8. Verify and report.

**Transactional cuts.** If any required boundary for an original item cannot be
created, abort that item's whole correction set and undo the partial cuts. V3
leaks here: in `_apply_group_edit` a successful first split followed by a failed
tail split leaves `mid` on the track, untracked and uncounted. V4 must not
inherit that pattern, which gets worse under a cut-everything-first model.

## Reporting

```
notes_total, notes_aligned, notes_in_tolerance
refused_max_move, refused_monotonic, refused_window, refused_foreign,
refused_decay_budget          # the gap-fill limit specifically
seams_trimmed, seams_pulled
gaps_unfilled, gaps_unfilled_seconds
new_overlaps                  # must be 0; pre-existing ones reported separately
```

## Testing

The reason rev 1's defect would have shipped is that the harness could not see
audio. Two fixes are **preconditions**, not parallel work.

**Precondition 1 - the fake accessor is source-blind.** `_reaper_fakes.py`'s
`get_samples` indexes the sample array by `start_time` alone and ignores
`take.start_offs`, so every take sharing one `FakeSource` reads from the start of
the array regardless of which split piece it is. Reads must be
`int((take.start_offs + start_time) * sr) + i`. Until this is fixed, any
"audio" test is geometry in disguise - V3's end-to-end test included.

**Precondition 2 - attacks need identity.** The fixture source must carry a
distinguishable marker per attack (distinct amplitude or pattern), not uniform
clicks. Counting anonymous clicks cannot tell "attack moved" from "attack
duplicated".

Then:

1. **Source-render regression.** Sum every item's audible source interval into a
   project-timeline buffer and assert: every planted attack appears **exactly
   once**; each corrected attack sits at its planned time; untouched attacks are
   unmoved; no attack appears that edge work exposed; nothing outside the
   time-selection source window becomes audible. This is the only test shape
   that catches the rev 1 class of defect.
2. **Dense-material regression** on a shaker-like fixture (attack every ~100 ms):
   exact item count `K + R + 1`, no new overlaps, and an asserted refusal
   breakdown - so a future change that "fixes" overlaps by refusing everything
   is caught.
3. **Property test** over randomized densities and spreads: no new overlaps,
   order preserved, no note crossing a sentinel, no unreported gap, positive
   length on every item, unique cut boundaries, report counts equal to observed
   operations. Cases must include attacks closer than 25 ms, more than four
   attacks inside 25 ms, adjacent and isolated corrections, alternating
   left/right moves, first and last note corrections, partial time selections,
   several original items per track, pre-existing gaps, and a forced split
   failure.
4. **Adaptive-chain regression:** three notes where A sets a positive lag, B
   earns an Adaptive move but is refused for spacing, and C must be planned from
   the last *physically applied* note - not from B's rejected target.
5. **Live comparison via MCP** against the captured baseline
   (`1 item -> 102 items, 48 overlaps, 2 stacks`): expect 59 items, zero new
   overlaps. Headless green is not evidence on its own - every past live bug in
   this project (em-dash crash, argument count, `c_int` types) passed headless
   first.

## Non-goals

- **Note-end / release detection.** A note's end is already the next attack
  rather than a fixed 30 ms constant, which covers half of the concern about
  long notes. True decay detection layers on later without redesign.
- **Time-stretch gap filling.** Rejected for now: pitch-preserving stretch over
  10-40 ms windows is the regime where such algorithms perform worst, so it
  risks trading a stutter for a warble. Revisit only with a listening test.
- **Material-adaptive gap policy** (duplicate for percussion, silence for
  tonal). Noted as plausible - duplicated decay is more audible on sustained
  guitar than on shaker - but out of scope until the fixed policy is heard on
  real material.
- V3 is not modified. V4 is a new file, per the project's V1/V2/V3 pattern.
- The five `isinstance`-based RPR return parsers (V3 audit P2-8) still need live
  `repr()` inspection first.
- **Fade field names cannot be verified from this repo.**
  `reaper_python.py` passes the key straight through as a C string with no
  validation, so a misspelled field silently returns 0.0. The `Crossfade` seam
  style reuses V3's behaviour and adds no new fields. The `Butt joint` style does
  need `D_FADEINLEN` / `D_FADEOUTLEN` and possibly the `_AUTO` variants and shape
  fields, since REAPER's auto-fade preference may override a manual length on
  items created by a split - all of which require a live check before that style
  can be trusted.

## Files

| File | Responsibility |
|---|---|
| `Grid Align Transients V4.0.py` | New. Forked from V3; correction model replaced per this design. |
| `grid_align_v4_test_headless.py` | New. Adds source-render, dense, property, and Adaptive-chain tests. |
| `_reaper_fakes.py` | Accessor honours `D_STARTOFFS` (precondition 1); render helper; identifiable attack markers. |
| `docs/superpowers/specs/fixtures/grid-align-manual-test-checklist.md` | Gains a V4 live section. |
