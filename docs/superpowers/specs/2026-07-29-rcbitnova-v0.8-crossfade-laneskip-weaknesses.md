# RCBitNova V0.8 Crossfade + Lane Skip - Weakness Review

**Date:** 2026-07-29  
**Reviewed spec:** `2026-07-29-rcbitnova-v0.8-crossfade-laneskip-design.md`  
**Context:** worktree `~/projects/reascripts/.claude/worktrees/rcbitnova/`

Both changes are well targeted and the algebra behind kernel interpolation is
correct. The main weakness is that the proposed crossfade is not continuous in
time: it is an eight-step, hop-rate transition. The lane-skip proof is plausible
for a single lane, but the shipping engine has a shared FDL write index and two
lanes, so the oracle and state contract need to model that integration explicitly.

## P0 - Eight Hop Updates Are A Staircase, Not A Click-Safe Crossfade

The active kernel changes once per `P=2048` output block. During each block the
blend coefficient is constant, then it jumps at the next hop:

`1/8, 2/8, 3/8, ... 8/8`

Linearity proves that each block equals an output blend at that block's fixed
alpha. It does not turn the eight block-boundary alpha jumps into a sample-ramped
crossfade. The first transition is still 12.5% of the full response change. For a
large Slope, Off, Brick, or Resonance change, that can remain an audible click or
produce zipper-like steps every 2048 samples.

The proposed tests exercise coefficient convergence but never measure the output
discontinuity at a hop boundary. The live check "clicks are gone" is the only
acceptance criterion for the feature named Click-Safe.

**Recommendation:** either:

- Rename the guarantee to click-reduced/hop-smoothed and define a measurable
  transition-discontinuity limit; or
- Perform an actual per-sample output-domain crossfade between old/new convolution
  results during the transition; or
- Demonstrate with worst-case time-domain tests that the eight-step design meets a
  pinned click threshold.

Test sustained sine at several phases relative to the hop boundary, impulse,
full-scale noise, Off<->Brick, 12<->96, and Resonance 0<->1. Measure maximum
sample-to-sample transition error against uninterrupted old/new references.

## P1 - The CPU Estimate For Kernel Blending Is Dimensionally Wrong

The spec calls the blend pass "comparable to a single `convolve_c`" and estimates
roughly +25% per engine. One `convolve_c` handles one partition (`PB2` words /
`B` complex bins). The blend loop touches `KMAX*PB2` words:

- Normal: 4 partition spans;
- High: 16 partition spans.

At High, the EEL loop performs 131072 scalar read/subtract/multiply/add/write
updates per hop. That is not comparable in touched data to one size-4096
`convolve_c`, and `convolve_c` is a native primitive while the coefficient blend
is an EEL loop. The actual ratio may differ substantially from +25%.

**Recommendation:** remove the estimate until benchmarked. Measure:

- Normal and High;
- Both and selective Placement after lane B has entered skip;
- One and two engines fading simultaneously;
- Small device blocks;
- A rapid sweep that rebuilds every 100 ms and therefore keeps resetting the fade.

Report steady CPU, peak block time, and dropout/xrun behavior, not only REAPER's
averaged CPU meter.

## P1 - Fade Duration Omits Rebuild Coalescing And Output-Hop Delay

Eight hops are about 171 ms at 96 kHz, but the audible response does not necessarily
begin immediately:

- A dirty target may wait up to 100 ms for V0.7's rebuild limiter;
- A newly blended convolution block reaches the output after the runtime hop/FIFO
  delay;
- Retargeting restarts the eight-hop fade.

The worst final-settle time after the last knob event is therefore longer than the
stated 170 ms. At 48 kHz, eight hops alone are about 341 ms; at 44.1 kHz they are
about 372 ms. A sweep can feel much more sluggish than the 96 kHz headline implies.

**Recommendation:** define control latency and settling time at 44.1/48/96/192 kHz,
including the 100 ms coalescer and output scheduling. The live test should measure
the delay from the last parameter event to arrival at the final response.

## P1 - Fade State Storage And Reset Rules Are Not Pinned

The spec adds `fade_left`, `fading`, target validity, and first-build behavior, but
does not assign their storage or define every reset path. V0.7 has:

- `lp_rt` slots 0..5 used, 6..7 now claimed by zero counters;
- `lp_off` slots 0..14 used, with slot 15 currently free;
- `hp_built/lp_built` global flags;
- geometry reconcile that clears/moves engine buffers and resets both engines.

**Recommendation:** pin:

- `lp_off[eng*16+15] = Hspec2`;
- Exact per-engine fade-state variables/slots;
- Reset on `lp_relayout`, Resolution change, first load, transport re-init, and any
  forced `built=0`;
- First-build copy direction and length;
- Whether a target built while `Phase=Min` snaps, waits, or starts a dormant fade.

Add source guards so a relayout cannot leave `fading=1` while `Hspec`/`Hspec2` point
to newly cleared or moved memory.

## P1 - The Oracle Tests The Fade Formula, Not The Convolution Transition

`kernel_fade_step` proves a scalar vector reaches its target. It does not verify
where the fade step occurs relative to:

- FDL write;
- Convolution of lane A and lane B;
- Output-ring write/read;
- The one-hop runtime delay;
- A kernel rebuild in `@block`;
- A mid-fade retarget.

A transcription can call the correct helper one hop too early/late, after lane A,
or only inside a non-skip branch and still pass all proposed fade-law tests.

**Recommendation:** add an integrated, stateful partitioned-convolution oracle that
changes kernels during a nonzero signal. Compare its output to an explicit
block-alpha reference and assert:

- Both lanes use the same alpha in the same hop;
- Alpha advances exactly once per engine hop;
- Fade progresses even when one or both lanes are skipped;
- Retarget does not alter the current output block retroactively;
- First build and post-geometry build snap with no zero-kernel fade;
- Final `Hspec` is bit-identical to `Hspec2`.

## P1 - Lane Skip Must Respect The Engine-Shared FDL Write Index

V0.7 has one `fdl_wr` per engine, shared by lane A and lane B. The spec describes
each lane as if it owned an independent FDL timeline: "nothing is written to the
FDL while skipping." In the intended selective case, lane A still runs and advances
the shared `fdl_wr` every hop while lane B skips.

This can still be correct because every lane-B slot is zero and the absolute ring
rotation is irrelevant. But that invariant must be stated and tested. A naive
implementation that advances `fdl_wr` inside each lane branch, or fails to advance
it when both lanes skip, can desynchronize lane A or resume lane B against the
wrong newest-slot convention.

**Recommendation:** define `fdl_wr` as engine-level and advance it exactly once per
hop, independent of per-lane skip decisions. Test all four hop states:

- A runs / B runs;
- A runs / B skips;
- A skips / B runs;
- A skips / B skips;

then resume each lane at different hops and compare bit-for-bit with the full
two-lane engine.

## P1 - The Skip Proof Needs Hop-Alignment Coverage

`BD+B` is conservative, but entry is evaluated only at hop boundaries. The number
of zero samples needed before every overlapping `B=2P` block and all `KMAX` FDL
slots are zero depends on where the zero run starts relative to the hop.

The proposed test uses one signal arrangement. It can pass while an off-by-one
counter/check order fails for a zero run beginning one sample before or after a hop
boundary.

**Recommendation:** parameterize zero-run onset over every relevant phase
`0..P-1` (or a focused boundary set including 0, 1, P-1). Check runs of:

- `BD+B-1`;
- `BD+B`;
- `BD+B+P`;

and verify both that no premature skip occurs and that the optimization eventually
triggers. Pin whether the counter is tested before or after writing the current
sample and before or after the hop's FDL update.

## P1 - Exact Skip Equivalence Must Include Output And FDL State

Comparing only returned samples can hide divergent internal state that happens to
produce the same finite test output. The skipped path writes zero output blocks but
does not refresh zero spectra into FDL slots. After resume, state equivalence relies
on the "all slots are already exactly zero" invariant and correct pointer handling.

**Recommendation:** have the oracle expose/compare:

- FDL contents;
- `fdl_wr`;
- Input ring and write position;
- Output ring and read/write positions;
- Zero counters;
- Output for at least `BD+B` samples after resume.

The source guard should also prove the skipped lane still writes its input ring,
advances engine/output timing, writes exactly `P` output zeros, and does not call
FFT/IFFT/`convolve_c`.

## P1 - First Selective Placement Does Not Save CPU Immediately

Lane B can skip only after a long exact-zero flush:

- Normal: `BD+B = 12288` samples, about 256 ms at 48 kHz;
- High: `36864` samples, about 768 ms at 48 kHz.

Until then it must convolve the old lane-B history and its tail. The live instruction
to toggle Both<->Mid and observe "roughly half" CPU may be read too soon and produce
an apparent failure or misleading result.

**Recommendation:** document the warm-up interval and make the CPU test wait longer
than `(BD+B)/srate` plus one hop. Separately verify that switching back to Both
resumes on the next hop without a silence block.

## P1 - "Half The Cost" Overstates The Whole-Plugin Saving

Skipping lane B removes one lane's FFT, `KMAX` convolutions, accumulation, and IFFT
after the zero-history threshold. It does not remove:

- Lane A;
- Per-sample rings and Placement routing;
- Kernel rebuilds;
- The crossfade blend pass;
- The other HP/LP engine;
- Static EQ and dynamics.

Therefore selective Placement can approach half of one engine's steady convolution
runtime, but the REAPER FX CPU for the whole plugin will generally fall by less than
half. During a High kernel fade, the large blend loop can narrow the saving further.

**Recommendation:** scope the claim to "approximately half of that engine's
steady-state two-lane convolution work" and set realistic whole-plugin benchmarks.

## P1 - Crossfade While `Phase=Min` Is Undefined

V0.7 marks and rebuilds kernels even while the Min path is active. In V0.8, a later
build writes `Hspec2` and normally starts a fade, but `lpk_run` does not execute in
Min mode, so the fade cannot advance.

On the next Min->Linear switch, possibilities include:

- Fade from the old active kernel to the target;
- Snap because Linear was inactive;
- Resume a partially completed fade from an earlier Linear session.

Phase switching is allowed to be non-seamless, but stale/dormant fade state still
needs deterministic behavior.

**Recommendation:** while Min, either copy every rebuilt target directly to active
and clear fade state, or defer the build and snap/rebuild on Linear entry. Add a
Min-edit->Linear test and a Linear-mid-fade->Min->Linear test.

## P2 - Counter Growth Should Saturate

A permanently zero lane does not need an ever-growing sample count. Saturating
`zcnt` at `BD+B` avoids needless large values and makes reset/check behavior easier
to reason about:

`zcnt = sample == 0 ? min(zcnt+1, skip_after) : 0`

This is not a practical floating-point overflow risk at normal session lengths,
but it makes the invariant explicit and simplifies tests.

## P2 - Anti-Denormal Interaction Needs A Source-Level Test

The optimization depends on lane B receiving literal `0`, while the global input
receives alternating `±2^-100`. The current V0.7 routing does pass literal zero in
`lpk_run(eng, act, 0)`, but a future refactor that moves anti-denormal injection
inside `lpk_run` would silently disable the skip forever.

**Recommendation:** add a source/integration assertion that selective lane B is
exactly zero after all anti-denormal handling, while lane A/global silence is not
expected to skip under the current policy.

## P2 - Retarget Tests Need Adversarial Direction Changes

The proposed retarget test says "without overshoot" but does not define target
sequences. A monotonic A->B->C case is weak.

**Recommendation:** include:

- Positive-to-negative coefficient changes;
- A->B then back past A;
- Rapid alternating targets every allowed rebuild;
- Brick/Off/96 targets whose spectra differ strongly by bin.

Assert convex movement from the current active value toward each newest target and
eventual exact final copy.

## Suggested Pre-Implementation Edits

1. Replace "click-safe" with a measurable claim, or use a true per-sample output
   crossfade.
2. Benchmark the full `KMAX*PB2` EEL blend loop before accepting the +25% estimate.
3. Pin `Hspec2` and all fade-state offsets/reset paths.
4. Add an integrated changing-kernel convolution oracle, not only a vector helper.
5. Specify shared `fdl_wr` behavior for every A/B run/skip combination.
6. Parameterize skip entry/resume over hop alignment and compare internal state.
7. Document lane-skip warm-up and narrow the "half CPU" claim.
8. Define deterministic fade behavior while Phase=Min and across geometry resets.
