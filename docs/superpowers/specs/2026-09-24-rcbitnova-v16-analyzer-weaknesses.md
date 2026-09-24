# RCBitNova V1.6 Analyzer Design Weaknesses

**Reviewed:**

- `docs/superpowers/specs/2026-09-24-rcbitnova-v16-analyzer-design.md`
- implementation baseline `JSFX/RCBitNova V1.5` at `65ab7f8`
- `tools/rcbitnova_layout.py`, current gates, manifest tests, and null harness
- `/Users/macbook/Library/Application Support/REAPER/Effects/Fable Eq Mix.jsfx`
- independent read-only cross-check by GPT-6 Astra against the same files

## Summary

The two headline choices are sound: the FFT belongs in `@gfx`, and a monotonic queue can replace
the full lookahead scan without changing a sample. The current revision is not yet precise enough
to guarantee either claim in the implementation.

Two audio-equivalence holes are release-blocking. The reference queue temporarily needs 2049
entries at Nova's maximum `Lk` if its `push -> evict` order is copied, despite the proposed capacity
of 2048. More importantly, Nova's lane B is not updated in single-lane placements while the shared
band cursor continues to advance. A queue left untouched during that interval cannot equal V1.5's
ring rescan when the band returns to `Both`; an independent model reproduced a stale maximum of 9
where V1.5 returned 4.

The analyser side also needs an ownership protocol rather than a direct port. The reference clears
GUI peak arrays from the audio section and reads a live write cursor throughout both FFT copies.
Nova already documents that `@sample` and `@gfx` can touch memory concurrently. Domain changes while
stopped, coherent IN/OUT snapshots, stale magnitude decay, Nyquist handling, and widths above 2048
physical pixels therefore need explicit contracts.

| Priority | Count | Meaning |
|---|---:|---|
| P0 | 2 | Can silently change Mode-B audio while the implementation still looks like the reference |
| P1 | 8 | Core analyser, compatibility, layout, or acceptance contract is incomplete |
| P2 | 3 | Lifecycle and measurement details can produce stale or non-reproducible behaviour |

## P0 Findings

### P0.1: Lane B cannot use one eviction per sample after a single-lane interval

Section 6 treats all sixteen queues as if each receives one new position and loses one old position
per sample. V1.5 does not have that topology. In `Both`, lane B is written and scanned at
`JSFX/RCBitNova V1.5:2175-2182`; in Mid, Side, Left, or Right, that block is skipped, but the band's
shared `mbwpos[b]` still advances at line 2230.

Consequently, after `Both -> Mid -> Both`, lane B's ring window is selected by a cursor that moved
while neither its samples nor its queue moved. V1.5 rescans the actual ring positions and naturally
drops whatever rotated out. A naive queue retains entries whose positions left the window several
samples ago, and `dq_evict()`'s single equality test cannot catch up. The same risk applies when an
`Lk` change is marked while a lane or whole band is inactive and the invalidation is consumed too
early.

This is not hypothetical: the independent queue model returned a maximum of 9 after two skipped
lane-B writes while the V1.5 ring scan returned 4.

**Required change:** define validity per `(band, lane)`, not only globally. A lane that resumes after
its cursor advanced without queue maintenance must rebuild oldest-to-newest from the exact
`mb_peak` positions V1.5 would scan. An `Lk` invalidation must remain pending for every inactive lane
until that lane next processes. Pin the expected behaviour for band disable/enable, Mode B/A/B,
single-lane/Both, and bypass; do not clear history where V1.5 freezes and retains it.

### P0.2: `DQ_CAP = MAX_LOOK` overflows under the copied push-before-evict order

V1.5's scan contains `Lk + 1` values. At the clamp `Lk = MAX_LOOK - 1 = 2047`, the final queue
therefore contains 2048 values. That alone fits. The reference, however, executes
`dq_push(current)` before `dq_evict(leaving)` (`Fable Eq Mix.jsfx:923-925`). On a strictly
decreasing sequence no tail entry is removed, so occupancy temporarily becomes 2049 before the
eviction. A 2048-slot circular buffer overwrites its head at exactly this point; the position test
then observes corrupted state.

The 10 ms test at 96 kHz uses `Lk=960`, and even 192 kHz uses `Lk=1920`, so all proposed live nulls
can pass while the defect remains. The clamp is reached at higher rates such as 384 kHz.

**Required change:** either allocate at least `MAX_LOOK + 1` entries per queue and update the memory
map, or deliberately change the operation to eviction-before-push. If the latter is chosen, specify
the exact sequence: evict position `wp-Lk-1`, replay the preceding `Lk` entries oldest-to-newest on
rebuild, then insert the current sample exactly once. Test `Lk=2047` with strictly decreasing data,
equal runs, random data, and multiple ring wraps; assert both maximum and `count <= capacity` after
every operation.

## P1 Findings

### P1.1: The acceptance matrix tests steady states, not the dangerous transitions

The four exact nulls in section 7 use static analyser and lookahead settings. They do not exercise
the rebuild whose correctness section 6 identifies as the principal risk. The Python oracle proves
an algorithm, not its EEL2 transcription or its connection to `mbwpos`, placement, slider timing,
and retained rings. Rendering with Analyzer On but its window closed also never runs the `@gfx`
implementation.

**Required change:** add exact V1.6/V1.5 JSFX null cases with lookahead automated mid-stream and
with `Both -> single lane -> Both`. Include a lookahead change while lane B is inactive, Mode B
off/on, a disabled/re-enabled band, and the maximum-capacity sequence. State that the comparator is
64-bit float and seed one defect for each transition so a test that never reaches the transition
cannot pass decoratively. Keep separate live GUI tests for the analyser; an audio null cannot prove
that a display is correct.

### P1.2: Domain clearing has no safe `@sample`/`@gfx` ownership protocol

Sections 4 and 4.3 require inline reads and say a domain change clears both rings and both peak
arrays, but they do not assign the operation to a section. Neither obvious interpretation works:

- clear in `@sample`: no clear occurs while transport is stopped, contradicting the live matrix;
- clear in `@gfx`: it races the audio writer over `an_in`/`an_out`;
- copy Fable literally: audio clears `an_pkI/an_pkO`, which are simultaneously read and written by
  the GUI thread.

Clearing only the listed rings and peaks is also insufficient. `an_mi/an_mo` retain the previous
domain and decay by `0.86` per frame, so they can immediately repopulate the just-cleared peak hold.
The reference's FFT loop also rereads live `an_pos` for every sample and separately for IN and OUT;
the single write cursor prevents write-side drift but does not provide a coherent read snapshot.

**Required change:** define separate ownership and generations. `@sample` owns rings, write cursor,
and its observed domain generation; `@gfx` owns magnitudes, pixel scratch, and peaks. A GUI domain
change must immediately suppress/clear its own display state, publish a reset generation, and let
`@sample` clear/restart the rings before the next write. Capture one cursor and one domain generation
per frame before preparing both transforms; state what happens if the generation changes during the
copy. Reset magnitudes together with peaks. Specify Off -> On and transport-stop behaviour as well.

### P1.3: `L+R` is not a third domain under the proposed one-ring architecture

The table names Mid, Side, and L+R, while section 4 allocates one scalar input ring and one scalar
output ring. Fable only implements `(L+R)/2` and `(L-R)/2` (`Fable Eq Mix.jsfx:978-983`). With one
scalar ring, literal `L+R` is just Mid with a +1-bit gain offset; a normalized sum is exactly Mid.
Both cancel anti-phase material and neither represents the combined energy of the two channels.

**Required change:** choose and name the intended quantity mathematically. If it is a coherent sum,
drop either Mid or L+R and state the normalization. If it means a stereo magnitude such as power
sum or max of L/R magnitudes, retain both channels through the FFT path (or define a proven complex-
packing method) and revise the memory/CPU budget. The spectrum oracle must cover mono, left-only,
anti-phase, and uncorrelated stereo inputs.

### P1.4: The binning sentence specifies the opposite of the reference algorithm

Section 4.1 says to interpolate "where [bins] are denser than pixels" and take a maximum where they
are not. The reference does the reverse at `Fable Eq Mix.jsfx:1537-1545`:

- `delta_bin <= 1` (pixels denser than FFT bins): interpolate between adjacent bins;
- `delta_bin > 1` (multiple bins inside one pixel): take the maximum so narrow peaks survive.

A literal implementation of the prose loses high-frequency peaks while still producing a smooth,
believable display.

The unit contract is incomplete too. The reference computes dB and adds a dB/octave tilt, while
Nova's vertical axis is specified in bits. The required conversion is not stated.

**Required change:** write the two binning inequalities explicitly. Define either an all-dB internal
path mapped to the bit-labelled axis, or `mag_bits = log(mag)/log(2)` and
`tilt_bits = tilt_db/6.020599913 * log2(f/1000)`. Add oracle tones between sampled pixel positions
and assert peak value as well as peak pixel.

### P1.5: The fixed 2048-pixel arrays do not define the full plot at wide sizes or above Nyquist

V1.5's `gc_pw = gfx_w - gc_px - 10*gc_sc` is unbounded. On Retina, a moderately widened window can
therefore exceed the proposed 2048 physical columns. "Clamp the draw loop" can mean drawing only
the left 2048 pixels, leaving the right side blank, or silently compressing the frequency map; the
spec does not choose.

The axis also reaches 24 kHz while Nyquist is 22.05 kHz at 44.1 kHz. Reusing Fable's terminal-bin
clamp would repeat the last real bin across the impossible 22.05-24 kHz region. At high sample rates
the opposite edge appears: 20 Hz lies below bin 1 (0.853 bin at 192 kHz), and the reference computes
the fraction before clamping the index, thereby interpolating the wrong pair.

**Required change:** define one bounded integer `an_px_n` used by binning, both smoothing passes,
peak update, peak draw, fill, and contour. If it is capped at 2048, map those columns across the
entire `gc_pw`, not its left prefix. Define DC/bin-1 handling and render frequencies at or above
Nyquist as floor/no data rather than duplicating the last bin. Add 44.1, 48, 192, and 384 kHz plus a
wide Retina window to the oracle/live matrix.

### P1.6: The memory total omits queue state, invalidation state, and peak persistence metadata

The 65536-word queue line counts only values and positions. Sixteen queues also need at least
head/tail/count state; the fixes above additionally need dirty/generation or lane-valid state. The
reference's persistent peak hold uses `PK_KEEP[0..1]`, which is absent from the table. Copying its
literal `PK_KEEP=160000` is especially unsafe: under the table-order layout, address 160000 lies
inside the proposed `an_mo` span 159744..163839.

The payload itself fits: table-order packing ends at 251904 exclusive and leaves 10240 words before
`lp_base=262144`. The problem is that the claimed total is not the complete allocation and the
layout source of truth cannot gate objects it does not know exist.

**Required change:** allocate every metadata span and marker in `rcbitnova_layout.py`, including
initial values and clear ownership. Gate pairwise disjointness, exact clear spans, `an_sc` page
safety, the whole new block below `lp_base`, and the engine block beginning at 262144. Do not port
any absolute address from Fable.

### P1.7: Four new top-bar controls have neither room nor early pointer ownership

The current top bar already occupies five 110-unit slots: two frequency fields and Phase/HP res/LP
res. Its hit owner is computed before node hit-testing at `JSFX/RCBitNova V1.5:2358-2373`; this early
ownership exists because a top-bar click previously also enabled and armed a band node. Section 4.3
only says to place four more controls "beside" the resolution buttons.

At the 900x500 reference size, four more controls of the same style do not fit in the existing row.
If they are drawn to the left without extending `gc_topbar_hot`, clicks can again fall through to
the plot and alter audio. Small mode, labels, three-way Domain/Tilt controls, and right-click peak
reset are also not placed.

**Required change:** specify the complete responsive geometry before implementation: rectangles,
compact/segmented widths, small-mode visibility, and whether a second row changes plot height.
Publish the union of every new rectangle in the early top-bar ownership calculation before node hit
collection. Gate the 900x500 layout and live-test overlap at minimum, default, and Retina sizes.

### P1.8: Slider numbers alone do not protect V1.5 project compatibility

Numbers 247-250 correctly append after the highest existing number, but section 7 checks only that
fact. V1.5 has 176 declared records, and the repository already contains the exact expected V1.5
manifest. A build may change or remove an old declaration and still satisfy "all new sliders are
above 246."

**Required change:** require the full expected V1.5 176-record manifest as an exact prefix, then
exactly four records 176..179 with pinned names, defaults, ranges, steps, and enum labels. The live
build must report 180 declared plus the three host parameters at 180..182. Add save/reload and
automation round-trips for all four controls; state explicitly that no migration is needed because
the audio-bearing prefix is unchanged and the appended defaults are display-only.

## P2 Findings

### P2.1: "Persistent peak hold" does not define persistence across `@init`

Fable uses a memory marker because REAPER calls `@init` again at transport start and ordinary
variables reset while memory survives (`Fable Eq Mix.jsfx:260-267`). The V1.6 spec says peak hold is
persistent and only mentions domain/right-click clears, but does not say whether transport start,
sample-rate change, Analyzer Off/On, or plot-width change clears it.

**Required change:** list the reset matrix. If peaks survive `@init`, allocate and gate a first-load
marker at a modeled address. If they do not, remove "persistent" or qualify it as frame-persistent.
In either case initialize all active peak columns to an explicit floor, never zero.

### P2.2: The four parameter defaults and Analyzer Off -> On fill policy are absent

The parameter table gives values but no defaults. When Analyzer is Off the rings do not advance, so
turning it back On either exposes an old complete frame, mixes old and new data for 8192 samples, or
starts empty. Those are visibly different behaviours, especially while stopped.

**Required change:** give literal slider declarations/defaults and define enable transitions. A
clean contract is to invalidate the display on Off -> On, refill both rings under the new generation,
and draw nothing until a complete frame exists; if warm history is deliberately retained, say so and
test it.

### P2.3: The CPU acceptance number has no reproducible analyser condition or tolerance

"At 10 ms lookahead approximately 1.4%" does not say whether the FX window is open, Analyzer is On,
peak hold is enabled, or REAPER's Performance Meter includes the GUI thread. The original 1.4% is a
fit intercept, not a measured post-change threshold, so machine scheduling can move it.

**Required change:** pin project rate, block size, active bands/modes, window state, analyser state,
measurement duration, meter field, and an acceptance band. Report audio-thread and GUI-open numbers
separately; the real invariant is loss of the linear `Lk` slope, not one exact percentage.

## Recommended Revision Order

1. Specify per-lane queue validity, exact rebuild order, and a capacity-safe eviction order.
2. Add transition nulls that execute those contracts in the real JSFX, not only in Python.
3. Define analyser domain math and an explicit `@sample`/`@gfx` generation/ownership protocol.
4. Correct binning direction and pin bit conversion, Nyquist, low-bin, and wide-window behaviour.
5. Complete the memory map, including queue metadata and peak-lifetime markers.
6. Design the full top-bar geometry and extend early pointer ownership over every new control.
7. Freeze the 176-record V1.5 prefix and specify new defaults/lifecycle and CPU measurement.

After those changes, the plan can preserve the design's intended headline: a display that never
writes audio, and a detector optimization that is exactly the old detector at every transition, not
only at two steady-state lookahead values.
