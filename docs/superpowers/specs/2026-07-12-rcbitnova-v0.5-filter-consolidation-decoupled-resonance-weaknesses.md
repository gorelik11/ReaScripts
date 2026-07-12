# RCBitNova V0.5 Filter Consolidation + Decoupled Resonance - Weakness Review

**Date:** 2026-07-12  
**Reviewed spec:** `2026-07-12-rcbitnova-v0.5-filter-consolidation-decoupled-resonance-design.md`  
**Context:** worktree `~/projects/reascripts/.claude/worktrees/rcbitnova/`

The main DSP direction is sound: staggered Butterworth sections fix the V0.4
cutoff droop, while a separate bell makes resonance independent of slope. The
largest remaining risks are state continuity, automation claims, cutoff safety,
legacy slider values, and verification that currently exercises only a narrow
part of the advertised behavior.

## P0 - Skipped Bell State Contradicts The State-Preservation Rule

Section 4 says that the resonance bell is skipped and its state does not advance
when `Resonance = 0`. Section 5 says Resonance changes do not reset state. Together
these rules produce a stale-state path:

`Resonance > 0 -> Resonance = 0 for some time -> Resonance > 0`

The bell resumes from integrators that describe an old signal. That can produce a
click or transient, especially with a sustained input or after a long zero period.
The current verification list does not test this sequence.

**Recommendation:** choose one explicit policy:

- Always tick the identity bell while Slope is active. At `glin=1`, its output is
  exactly the input, but its state remains current; or
- Clear the bell state on both zero/nonzero edges and accept/document the restart;
  or
- Crossfade/smooth bell activation if click-free automation is a requirement.

Add a stateful time-domain test for `1 -> 0 -> 1` Resonance automation on sine,
noise, and silence, with a bound on the transition discontinuity.

## P1 - "No Zipper" Is Required Without A Mechanism That Can Guarantee It

The live checklist requires no zipper on Slope, Freq, or Resonance automation, but
the design only updates coefficients in `@slider` and preserves or clears state:

- Freq and Resonance can make block-rate coefficient jumps.
- Slope changes explicitly clear all filter state, which is inherently a
  discontinuity on nonzero input.
- Resonance zero/nonzero has the additional stale-state problem above.

State preservation alone does not make coefficient steps click-free, and a
discrete topology change cannot be expected to null without a transition policy.

**Recommendation:** either narrow the acceptance claim to "no instability or
bursts under automation" or specify smoothing/crossfades. Pin which controls are
intended for continuous automation and define a measurable transient threshold;
"no zipper by ear" is not a reproducible criterion.

## P1 - Cutoff Is Not Constrained Against The Runtime Nyquist Frequency

V0.4 exposes `20..20000 Hz`, and V0.5 keeps that surface. The coefficient formula
uses `tan(pi*fc/srate)`. At a sample rate below 40 kHz, 20 kHz is at or above
Nyquist; even at common rates it can be close enough to Nyquist to stress a
high-order cascade. The spec does not define coefficient-domain clamping.

**Recommendation:** pin an effective cutoff such as
`fc_eff = min(slider_freq, nyquist * margin)` and use the same rule in Python and
JSFX. Test at least 44.1/48/96/192 kHz, both slider endpoints, every slope, and
maximum Resonance. If sample rates below 44.1 kHz are deliberately unsupported,
state that explicitly instead.

## P1 - Worst-Case Stability And Internal Headroom Tests Were Lost

The V0.4 spec explicitly tested Q=10 stability. V0.5 removes that user-Q path, but
96 dB/oct still contains Butterworth sections with high staggered Q, followed by a
bell with up to `glin=6`. Two such filters can run in series. Analytic magnitude
tests do not expose large internal integrator values, denormals, NaN/Inf, or
transition bursts.

**Recommendation:** retain time-domain stress tests for HP and LP, alone and
together, using impulse, full-scale sine, sweep, noise, and silence tails. Check
finite output and state, bounded peak, and bounded internal state at minimum and
maximum cutoff across supported sample rates. Pin the section order too: static
transfer functions commute, but intermediate headroom and behavior during
coefficient changes do not.

## P1 - Consolidation Has An Unsafe Out-Of-Range Fallback

The proposed `svf_set` rewrite is effectively:

`Bell if 0, Low Shelf if 1, otherwise High Shelf`

That is safe only if Type can never contain an old value. A restored preset,
automation envelope, script, or copied state can still present `3` or `4`; those
old HP/LP values would silently become High Shelf. "V0.5 is a new file" protects
existing project instances, but does not define preset/state transfer into V0.5.

**Recommendation:** specify input sanitization and migration semantics. Clamp or
map invalid Type values to a documented safe type (probably Bell), and add source
and runtime tests for values `3`, `4`, negative, and above range. Do not rely only
on the slider UI maximum.

## P1 - Reusing Q Slider IDs As Resonance Needs An Explicit Compatibility Contract

The spec says Q is replaced by Resonance but does not pin the slider declarations.
The likely implementation reuses `slider133` and `slider137`, changing their range
from `0.1..10` to `0..1`. This preserves later slider numbers, but an imported V0.4
state value such as Q=0.707 becomes about 71% Resonance rather than the intended
neutral default.

**Recommendation:** pin exact slider numbers, declarations, defaults, and policy
for V0.4 preset transfer. If transfer is unsupported, say so. If it is supported,
use new slider IDs or add an explicit migration/version marker rather than
reinterpreting the same numeric slot.

## P1 - The Memory Contract Is Deferred To The Plan

The totals (72 state slots and 126 coefficient slots) and per-filter indexing are
useful, but the base addresses, end address, allocation boundary, and proof of
non-overlap with the existing Mode B blocks are left for the implementation plan.
This is a correctness contract, not just an implementation detail.

**Recommendation:** pin:

- `hplp_state` base and exclusive end;
- `hplp_cf` base and exclusive end;
- `freembuf` boundary if used;
- exact reset ranges for HP and LP;
- a source-level test proving all blocks are disjoint and the bell slots are inside
  their owning filter's range.

Also test that increasing slope initializes every newly active section and that HP
reset cannot touch LP state or coefficients.

## P1 - Response Verification Is Too HP-Centric And Too Narrow

The "no dip / single peak" test is specified only as behavior above `fc`, which is
the HP passband case. Peak-height checks mention 12 and 96 dB/oct but do not require
both HP and LP, intermediate slopes, multiple Resonance values, cutoff extremes, or
multiple sample rates. A mirrored LP wiring error could pass the proposed suite.

**Recommendation:** parameterize the permanent tests across:

- HP and LP;
- N in `{1,2,3,4,8}`;
- Resonance in `{0, small nonzero, 0.5, 1}`;
- low/mid/high cutoff and supported sample rates.

Define "single peak" numerically (frequency grid, tolerance for flat/noisy
derivatives, and which side of `fc` is the passband). Test LP as the mirrored case,
not merely through a shared coefficient helper.

## P2 - "Fixed Q" Does Not Fully Specify Resonance Width

The existing Simper bell uses `A=sqrt(glin)` and `k=1/(Q*A)`. Therefore fixing the
input parameter at `Q=2` does not by itself prove that perceived or measured
bandwidth stays constant as Resonance changes. The spec validates peak height but
does not define the intended width behavior.

**Recommendation:** state whether gain-dependent bandwidth is accepted. Add
bandwidth measurements at Resonance 0.25/0.5/1.0, or choose a Q/bandwidth convention
whose behavior is explicitly intended. This matters because the feature is named
"decoupled resonance", which users may reasonably read as shape independent of
slope and predictable across amount.

## P2 - Resonance Off Semantics Should Include Slope Off

The verification says Off is unchanged, but the interaction is not directly
stated: if Slope is Off and Resonance is nonzero, does the standalone bell run?
The likely intended answer is no, because Off must remain bit-perfect and the
section is one unit.

**Recommendation:** explicitly state `Slope=Off` disables both cascade and bell,
regardless of Resonance, advances no section state, and preserves zero latency.
Test Off with Resonance at both 0 and 1 and with deliberately nonzero prior state.

## P2 - CPU Acceptance Is Still Subjective

At maximum settings the section performs up to 18 stages per stereo sample:
8 HP + HP bell + 8 LP + LP bell, or 36 SVF channel ticks for Both placement. This is
higher than V0.4's 32 ticks. "CPU acceptable" has no target or comparison method.

**Recommendation:** define a target-machine benchmark and maximum acceptable
increase versus V0.4 with both filters at 96 dB/oct, Resonance=1, Placement=Both.
Confirm the zero-Resonance skip policy's CPU benefit only after its state-continuity
problem is resolved.

## P2 - Prototype Evidence Is Not Reproducible In The Repository

The spec cites `resonance_decouple_proto.py`, but that artifact is not present in
the worktree. The numeric claims may be correct, but reviewers cannot reproduce
the exact grid, sample rate, HP/LP cases, or local-extrema logic used to obtain
them.

**Recommendation:** either keep the prototype under `tools/` or promote every
claim into permanent tests before implementation. The permanent oracle should be
the authority; source-string guards should only verify transcription/wiring, not
stand in for behavioral tests.

## Suggested Pre-Implementation Edits

1. Resolve the Resonance=0 bell-state contradiction.
2. Define realistic automation behavior and transition handling.
3. Pin Nyquist clamping and supported sample rates.
4. Specify exact slider IDs and old-value/preset migration behavior.
5. Move the complete memory map and non-overlap contract into the spec.
6. Restore worst-case time-domain stability/headroom tests.
7. Parameterize response tests across HP/LP, all slopes, cutoff regions, and sample
   rates.
8. Define resonance bandwidth behavior and a measurable CPU acceptance target.
