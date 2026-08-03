# RCBitNova V0.8 Crossfade + Lane Skip - Rev 2 Weakness Review

**Date:** 2026-08-03
**Reviewed spec:** `2026-07-29-rcbitnova-v0.8-crossfade-laneskip-design.md`, rev 2
**Reviewed base:** `JSFX/RCBitNova V0.7` at tag `rcbitnova-v0.7`
**Review type:** DSP transition, runtime state, memory, PDC, CPU, and verification audit

## Verdict

Rev 2 correctly replaces the hop-rate kernel staircase with a real per-sample
dual-convolution crossfade. It also closes the earlier review's lane-skip state,
warm-up, CPU-claim, and Phase=Min gaps.

Two blocking problems remain. First, the 10 ms topology dip is not synchronized
with the partitioned engine and cannot hide its queued output, old FDL history, or
post-relayout warm-up. Second, the memory section says `Hspec2` is never passed to
`convolve_c`, while the proposed runtime necessarily passes it there. The latter
can become silent page-crossing corruption if the implementation or oracle follows
the prose rather than the runtime pseudocode.

## Findings

### P0 - The topology dip ends before the topology change reaches the output

The proposed sequence is:

```text
10 ms fade-out -> apply topology -> 10 ms fade-in
```

However, `lpk_run()` does not expose a topology change immediately. It produces
and queues output in `P=2048`-sample hops. At common sample rates one hop alone is:

| Sample rate | One hop |
|---:|---:|
| 44.1 kHz | 46.4 ms |
| 48 kHz | 42.7 ms |
| 96 kHz | 21.3 ms |
| 192 kHz | 10.7 ms |

The entire fade-in therefore finishes before even the next generated hop can
become the current output at 44.1/48/96 kHz. The old block already queued in the
output ring remains audible after the envelope has returned to exactly `1.0`.

Phase and Resolution are worse. A Resolution relayout clears both engines. A
Min->Linear transition starts with empty engine histories. The first valid serial
linear output arrives only after the combined engine latency:

| Geometry | Combined latency | @48 kHz | @96 kHz |
|---|---:|---:|---:|
| Normal + Normal | 12288 samples | 256 ms | 128 ms |
| High + High | 36864 samples | 768 ms | 384 ms |

The 10 ms fade-in has long since completed when that signal appears. A sustained
waveform can therefore reappear from zero at an arbitrary phase, moving the step
later instead of removing it.

Placement does not relayout or clear the engine, so its failure mode is different:
old-domain samples remain in the FDL and output ring. For example, after Both->Mid,
lane A still contains L history and lane B still contains R history, but their
outputs are interpreted using the new Mid/complementary routing. A 10 ms dip cannot
hide up to a full FIR history emitted under the new routing.

**Required change:** do not claim the short dip fixes Placement, Phase, and
Resolution as one mechanism. Each needs a timing-aware transition:

- Placement: run old and new routing states in parallel and crossfade, or explicitly
  reset and hide the complete refill interval.
- Resolution: preserve an old engine while a new geometry is primed, then crossfade;
  otherwise specify and accept a long mute, not a 20 ms dip.
- Phase: solve both engine warm-up and host PDC switching; a local output envelope
  alone is insufficient.

Add an oracle that asserts no old-topology block or delayed zero-to-signal edge
appears after the ramp has ended.

### P0 - `Hspec2` is both convolved and declared non-convolved

Section 4 requires:

```text
yacc = sum FDL[k] * Hspec2[k]
```

In V0.7 this operation is implemented by copying one FDL partition into `tmpc` and
calling:

```eel
convolve_c(tmpc, hspec + k * lpPB2, lpB);
```

The second pass must therefore call `convolve_c(..., Hspec2 + k*lpPB2, lpB)`.
Section 7 instead says that `Hspec2` is never passed to `fft`/`ifft`/`convolve_c`
and consequently has no page-crossing constraint.

This is not editorial trivia. V0.7 documents that a misaligned large FFT span can
silently corrupt data. Every `Hspec2` partition consumed by `convolve_c` must obey
the same `PB2` alignment and no-page-crossing contract as `Hspec`.

**Required change:** state that `Hspec2` is an active convolution buffer, mark it
FFT-touched in `lp_engine_buffers()`/`page_layout()`, and test every partition in
Normal, fallback, and High layouts. Remove the claim that its alignment is only for
a possible future use.

### P1 - A plugin-local ramp does not define a safe PDC transition

Phase and Resolution change `pdc_delay`. REAPER consumes that value at host/block
level, while the proposed envelope applies per sample inside the plugin. The spec
does not define when the host adopts the new latency relative to:

- fade-out reaching zero;
- engine relayout and reset;
- the first valid output from the new geometry;
- fade-in;
- other tracks already compensated against the old latency.

Changing `pdc_delay` can shift this track relative to the rest of the project. A
zero-valued plugin sample at one instant does not guarantee that the host's timeline
realignment is inaudible or synchronized with that instant.

**Required change:** define selected versus active PDC and validate the actual
REAPER transition semantics. If REAPER cannot switch PDC at the intended boundary,
either preserve a constant maximum latency across these transitions, restrict the
operation to stopped transport, or explicitly leave live Phase/Resolution switching
out of the click-safe guarantee.

### P1 - The topology state machine is not specified

"Apply the change" requires values distinct from the raw sliders, but the spec pins
no topology state. V0.7 currently reads `slider134/138/140/141/142` directly in
layout, PDC, and sample routing. Rev 2 needs at least:

- selected/pending and active Placement for each engine;
- selected/pending and active Phase;
- selected/pending and active Resolution for each engine;
- envelope phase and integer position;
- an explicit commit point at exact zero;
- a policy for another topology event during fade-out or fade-in.

Without these shadows, `@slider` applies geometry/PDC immediately and the ramp is
only an after-the-fact gain change. Automation can also change a topology slider
more quickly than the 20 ms sequence, despite the rationale describing only manual
UI actions.

The lifecycle is also undefined while bypassed, while transport is stopped, on
first load, and when several topology sliders change in one block. A ramp inside
the `slider1 != 1` branch would not advance while bypassed.

**Required change:** pin the state slots and transition table, including coalescing,
reversal, bypass, initialization, and simultaneous events. All DSP, geometry, and
PDC decisions must use active values, not raw sliders.

### P1 - The "global dip" is placed before downstream stateful processing

The spec applies the envelope at the end of the HP/LP section. In V0.7 that section
is followed by four static/dynamic bands and output gain. Those filters can retain
state and continue producing nonzero output when their input is zero. Dynamics can
also react to the 20 ms level dip and reshape the fade or pump after it.

Consequently, reaching zero at the HP/LP boundary does not mean the plugin output
is zero when topology is committed.

**Required change:** if silence at the transition boundary is part of the proof,
apply the envelope at the final plugin output. If it intentionally belongs before
the remaining bands, remove the word "global" and test the complete plugin output,
including active dynamics and resonant static bands.

### P1 - The no-overlap proof relies on wall time, but the fade uses audio time

The fade lasts 50 ms of processed samples. V0.7's rebuild limiter uses
`time_precise()`, i.e. elapsed wall time. These clocks normally advance together,
but they are not the same invariant. Under an overrun, debugger pause, or unusually
slow block, 100 ms of wall time can pass before 50 ms of audio has advanced.

The defensive behavior then snaps `Hspec2` directly into `Hspec` while fading,
reintroducing the instantaneous kernel switch the feature is meant to eliminate.
The phrase "can never overlap" is therefore stronger than the mechanism.

**Required change:** gate rebuild commit on `!fading` and leave the dirty target
queued, or retarget from a mathematically defined current state. A snap is safe only
when output is known to be muted, not merely as an unexpected-overlap guard. Add a
test that decouples rebuild wall time from processed sample count.

### P1 - `built` has two proposed sources of truth

Section 4 calls `built` "V0.7's existing flag." V0.7 has the globals
`hp_built`/`lp_built`, which also bypass the 100 ms limiter after relayout. Section 7
then allocates another per-engine `built` value in `lp_fs` and says it is reset by
`lp_rt_reset` and `lp_relayout`.

If both remain, one can say the kernel is valid while the other says it is a first
build. That changes whether a build snaps or fades and whether it is rate-limited.

**Required change:** keep one authoritative per-engine validity flag, use it for
both rebuild scheduling and fade/snap choice, and list the exact order of build,
copy, validity update, dirty clear, and timestamp update. Add reset-path source
tests so no duplicate `hp_built`/`lp_built` state survives accidentally.

### P1 - The fade CPU description is too narrow

"Bounded by what V0.7 already does in Both placement" is true only for one active
selective lane: two kernel passes then equal V0.7's two single-kernel lanes. During
Both placement, V0.8 performs two kernel passes for each of two lanes, twice V0.7's
Both convolution work. If both HP and LP fade, both engines incur that multiplier.

The statement that the new design uses native primitives only is also incomplete.
`convolve_c`, FFT, and IFFT are native, but V0.7 accumulates every partition through
interpreted EEL loops, and rev 2 adds per-sample weighting/addition over each output
hop.

The planned live benchmark is good and should remain the authority. The prose
should state the actual pass counts and include xrun/dropout acceptance criteria,
because a 2x transient at High+High is exactly where average CPU can hide peak-block
failure.

### P2 - Partial final-hop ordering is not pinned

At common rates `fade_len = floor(0.05*srate)` is not a multiple of `P=2048`:
2400 samples at 48 kHz and 2205 at 44.1 kHz. The final generated hop therefore
contains a prefix with `alpha < 1` and a suffix clamped to `1`.

The spec does not pin whether completion is checked before or after generating that
hop, whether `fade_pos` advances before or after both lanes, or whether the final
`memcpy` occurs before the second lane has consumed `Hspec2`. An implementation can
be one hop early and still satisfy a loose eventual-equality test.

**Required change:** define hop pseudocode in execution order and test fade lengths
`P-1`, `P`, `P+1`, 2205, and 2400. Assert every output weight around the endpoint,
both lane outputs, exact pass counts, and the first hop that uses only `Hspec`.

### P2 - Topology verification is subjective and omits delayed failures

Kernel fade and lane skip receive integrated oracle tests. Topology changes receive
only the live instruction "a clean short dip, no bang." That observation window can
miss the old queued block or the delayed first valid output described above.

**Required change:** add a stateful two-engine topology oracle with an event log for
envelope zero, active-value commit, relayout/reset, PDC request, generated hops, and
audible output. Test sustained sine at several hop phases, impulses, stereo-asymmetric
signals, all Placement pairs, Min<->Linear, every Resolution pair, rapid automation,
and topology changes during a kernel fade. Measure the whole interval through the
last old-state tail and first stable new-state output.

## What Rev 2 Already Fixes

- Replaces the eight-hop coefficient staircase with a true per-sample output blend.
- Removes the unsupported `KMAX*PB2` EEL blend CPU estimate.
- Defines fade duration in seconds rather than hops.
- Pins lane zero counters and engine-level `fdl_wr` advancement.
- Documents skip warm-up and narrows the CPU-saving claim to one engine.
- Requires integrated convolution, hop-alignment, four-state lane, and internal-state tests.
- Defines deterministic snap behavior for first build, relayout, and Phase=Min.

## Required Spec Edits Before Implementation

1. Replace the universal 20 ms topology dip with transition mechanisms aligned to
   output-hop timing, FIR history, engine warm-up, and PDC.
2. Mark `Hspec2` as a live `convolve_c` buffer and enforce page safety in code and oracle.
3. Pin selected/pending/active topology state and all retarget/bypass lifecycle rules.
4. Define and live-test host PDC switching, or narrow the click-safe scope.
5. Move the topology envelope to final output or test downstream state explicitly.
6. Queue rebuilds while fading instead of using a potentially audible snap guard.
7. Consolidate kernel validity into one `built` source of truth.
8. Specify partial-final-hop ordering and add a topology-transition oracle.
