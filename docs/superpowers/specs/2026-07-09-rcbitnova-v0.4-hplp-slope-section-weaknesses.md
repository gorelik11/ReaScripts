# RCBitNova V0.4 HP/LP Slope Section - Weakness Review

**Date:** 2026-07-10  
**Reviewed spec:** `2026-07-09-rcbitnova-v0.4-hplp-slope-section-design.md`  
**Context:** worktree `~/projects/reascripts/.claude/worktrees/rcbitnova/`

This review lists weak points to tighten before writing the V0.4 implementation
plan. The design is musically clear and appropriately scoped: a minimum-phase
dedicated HP/LP section, no brickwall/linear-phase claims, additive new V0.4 file,
and explicit documentation of the high-slope cutoff convention. The remaining risks
are mostly integration details: JSFX slider mapping, state/memory layout, automation
behavior, CPU, and exact signal ordering relative to Mode B lookahead.

## P1 - Slope Selector Values Need An Explicit JSFX Mapping

The spec defines slope options as section counts:

`Off / 12 / 24 / 36 / 48 / 96 dB/oct = 0 / 1 / 2 / 3 / 4 / 8 sections`

This is correct DSP-wise, but easy to implement incorrectly as a JSFX enum. A normal
enum slider such as:

`sliderX:0<0,5,1{Off,12,24,36,48,96}>`

would return values `0..5`, not `0,1,2,3,4,8`. If the code then treats the slider
value as section count, 96 dB/oct becomes 5 sections (60 dB/oct), not 8.

**Recommendation:** pin the mapping in the spec/plan:

- UI enum value `0..5`.
- Convert with a helper/table: `sections = value == 5 ? 8 : value`.
- Add tests for every option proving actual section count/slope:
  `Off=0`, `12=1`, `24=2`, `36=3`, `48=4`, `96=8`.

## P1 - New State/Memory Map Is Not Specified

The HP/LP section needs state for two filters, up to eight 2nd-order sections each,
and up to two working channels per placement. That is at least:

`2 filters * 8 sections * 2 channels * 2 SVF integrators = 64 state slots`

The spec says each section holds its own state, but it does not define memory
offsets, reset behavior, or how this new state appends after V0.3's existing memory
blocks.

**Risks:**

- State block overlaps existing Mode B buffers or future blocks.
- Off filters still update state accidentally.
- Changing slope from low to high activates stale unused section states.
- Changing placement from Side to Both reuses stale channel-B state.

**Recommendation:** require the plan to define an exact memory map:

- `hplp_state` base offset after the last V0.3 block.
- Slot formula: `filter_index`, `section_index`, `channel_index`, `ic1/ic2`.
- Whether unused sections/channels are zeroed when slope/placement changes.
- Source-level test or code comment proving no overlap with existing memory ranges.

## P1 - Off == Bit-Perfect Needs A Stronger State Rule

The spec says Off is bit-perfect passthrough: no state, no processing. That should
mean more than "gain approximately unity".

**Risks:**

- Off branch still runs SVF state updates but outputs dry signal.
- Off filter resumes with stale states after a long bypass/off period.
- Automation Off -> 96 dB/oct can inject a transient from old integrators.

**Recommendation:** define Off behavior explicitly:

- Off skips all cascade processing and state updates.
- On transition to Off, state may either be cleared immediately or left dormant; pick
  one and test it.
- On transition from Off to On, either clear state or document warm-up transient.

Add tests:

- Off output exactly equals input for nonzero prior state in the Python model.
- Off does not advance state.
- Off -> On after silence does not produce a burst.

## P1 - Signal Position Relative To Mode B Lookahead Needs Precision

The spec says the HP/LP section runs first, before EQ bands and dynamics. In V0.3,
Mode B uses a global delayed bus and PDC; static bands and Mode A run before Mode B's
global pass.

For V0.4, the plan must say exactly whether HP/LP is:

1. Applied before the signal enters the static band loop.
2. Included in the signal written into Mode B's delayed bus.
3. Bypassed together with the plugin bypass before any PDC/bus writes.

The likely answer is "yes" to all three, but it should be explicit.

**Recommendation:** add an ordering statement:

`Plugin bypass -> passthrough. Otherwise anti-denormal/input section -> dedicated
HP/LP -> four EQ bands + Mode A -> Mode B delayed bus/pass -> output trim.`

Then add a regression test/live check: HP/LP active with Mode B active does not
change PDC, does not double-filter the delayed bus, and bypass remains zero-latency.

## P1 - Q Range At High Slopes May Be Too Dangerous

The first section uses user Q; later sections use 0.7071. This is a reasonable
musical convention, but the existing Q slider range can go up to 10. At 96 dB/oct,
a Q=10 resonant first section plus seven more sections can create a very large,
narrow peak near cutoff.

The spec mentions Q=2 examples, but not Q=10 worst-case stability.

**Recommendation:** either:

- Keep the existing Q range but add explicit tests at Q=10 for HP and LP, all slopes,
  several cutoff frequencies, impulse/sine/sweep, no NaN/Inf and bounded output; or
- Clamp the dedicated HP/LP section Q lower than the per-band HP/LP Q and document
  the difference.

This is especially important because the spec frames V0.4 as guarding against the
"distortion instead of processing" failure class from earlier work.

## P1 - CPU Budget Needs A Concrete Acceptance Target

Worst case is not small:

`HP 96 dB/oct Both + LP 96 dB/oct Both = 32 SVF ticks per sample`

before the four EQ bands and dynamic engines. With Mid/Side placements this also
adds local encode/decode work. The spec says CPU acceptable, but does not define an
acceptance target.

**Recommendation:** add a measurable criterion:

- CPU with both filters at 96 dB/oct Both should remain below a chosen threshold on
  the target machine/session, or
- CPU increase versus V0.3 should be documented in the live check.

Also include a source self-review item: no unnecessary per-sample branch ladders in
the inner 8-section loop; precompute section count and coefficients in `@slider`.

## P2 - High-Slope Cutoff Semantics Are Honest But Need UI/Manual Text

The spec correctly documents that at high slopes, `fc` is not the -3 dB point:
with Q=0.7071, N identical sections produce `-3 dB * N` at `fc`, and the true -3 dB
point shifts.

This is a good decision, but it is user-surprising.

**Recommendation:** require header/manual text in `JSFX/RCBitNova V0.4`:

`For slopes above 12 dB/oct, Freq is the cascade cutoff parameter, not the final
-3 dB point; level at Freq is -3 dB per active section when Q=0.7071.`

Add live/analyzer check: users can see the shift at 48/96 dB slopes.

## P2 - Slider Allocation Is Deferred

The dedicated section needs at least ten controls:

- HP Slope, Freq, Q, Placement
- LP Slope, Freq, Q, Placement
- Likely HP/LP enable is encoded by Slope=Off, so no separate enable is needed

The spec does not pin slider indices. V0.3 already uses 1-4, 11-49, 51-88, 91-123.

**Recommendation:** reserve exact slider numbers in the plan header, preferably in a
new bank beyond the Hard controls, for example `slider131+`, and add source tests:

- Existing V0.3 sliders are unchanged.
- New HP/LP section sliders exist with correct defaults.
- Slope defaults are Off.

## P2 - Automation Tests Need To Include State Transitions

The live checklist says no zipper on slope/freq automation. That is good, but the
risky transitions are specific:

- Off -> 96 dB/oct
- 96 -> Off
- 12 -> 96 and 96 -> 12
- Both -> Side -> Mid placement changes
- Q sweep at high slope near cutoff

**Recommendation:** add these as explicit live checks. In Python, add stateful tests
for slope changes if the mirror models state, not only analytic magnitude.

## P2 - 12 dB/oct Equality Needs Both Coefficient And Routing Tests

The spec says a 1-section cascade with user Q equals the existing per-band HP/LP.
That should be tested in two ways:

- Coefficients/response are identical for a single channel.
- Placement routing matches the existing per-band placement semantics for Both, Mid,
  Side, Left, Right.

Otherwise a filter can pass the coefficient test but still differ in placement
writeback.

## P2 - Scratch Prototype Should Become Permanent Tests

The spec references `hplp_cascade_proto.py` for pre-validation. As with prior phases,
prototype claims are useful but not reproducible unless they are promoted into the
Python oracle.

**Recommendation:** ensure every numeric prototype claim becomes a permanent test:

- Far-stopband slopes for 1/2/3/4/8 sections.
- `fc` level = `-3 dB * N`.
- Passband droop near cutoff for high slopes.
- Resonance bump at Q=2 and stability at Q=10.

## Suggested Pre-Implementation Edits

1. Define JSFX slope enum-to-section mapping.
2. Pin slider numbers for the new HP/LP section.
3. Define exact memory/state layout and Off/slope/placement state-reset policy.
4. State exact signal order relative to bypass, Mode A, Mode B delayed bus, and output
   trim.
5. Add worst-case Q=10 stability tests.
6. Add CPU acceptance criteria for both filters at 96 dB/oct.
7. Add manual/header text explaining that high-slope `Freq` is not the final -3 dB
   point.
