# RCBitNova V1.0 GUI Curve Design Rev 7: Weakness Review

**Reviewed:** `2026-08-14-rcbitnova-v1.0-gui-curve-design.md`, revision 7
**Review posture:** adversarial product contract, DSP-display correctness, cross-thread cache ownership, and acceptance-test completeness

## Overall Assessment

Rev 7 makes one excellent simplifying decision: a gesture writes one slider. That removes the Macro/Micro transaction, canonical split, write ordering, and fractional endpoint hazards instead of trying to make them less dangerous.

The specification is still not implementation-ready. Its current interaction contract contradicts itself in several places, the new Bit Ratio gesture is not mathematically defined, and the cache protocol still does not say how independent HP and LP rebuilds preserve a coherent published pair.

## Findings

### P0. The primary gesture table contradicts the rev-7 gesture map

The first table in §5 says:

- vertical drag changes Gain in 0.05-bit steps;
- Shift+drag is an unspecified fine step;
- wheel changes Q;
- hover plus typing starts numeric entry.

The later normative table says:

- vertical drag writes Macro only in whole-bit steps;
- Shift+vertical drag writes Bit Ratio in 0.05 steps;
- Alt+vertical drag or wheel writes Q;
- numeric entry starts by clicking a named field.

These are different interfaces. An implementer can follow either table and reasonably claim conformance.

**Required resolution:** delete the stale table or replace it with the detailed rev-7 map verbatim. State which table is normative and make every verification item use the same gesture names.

### P0. The Bit Ratio slider step is simultaneously 0.1 and 0.05

The verified slider map still lists Bit Ratio as `0..3, step 0.1`, while the next section requires changing the declaration to 0.05 and bases the Shift gesture on that value.

This is not a harmless comment mismatch: it changes which values are reachable, the expected wheel/drag quantization, source-level tests, and the claim that 0.25 is available.

**Required resolution:** update the canonical slider map to 0.05 and add a source-level acceptance test for all four Bit Ratio declarations. Add a compatibility test that values from the old 0.1 grid reload unchanged.

### P0. Shift+drag has a step but no mapping from pointer movement to Bit Ratio

The specification says Shift+vertical drag writes Bit Ratio at step 0.05, but never defines how mouse position or delta becomes a Ratio value. At least two incompatible implementations fit the prose:

- absolute inverse: `ratio_target = pointer_bits / (Macro + Micro/100)`;
- relative editing: a fixed number of pixels or vertical distance per 0.05 step.

They behave very differently for negative gain, small base values, crossing the zero line, and clamping at 0 or 3. The two documented no-op states do not resolve those cases.

**Required resolution:** pin absolute versus relative behavior, direction, sensitivity, snapping, clamping, drag origin, and behavior when the base is negative or near zero. Add a table of pointer trajectories and expected Ratio values at Macro `-8, -1, 0, +1, +8` with positive and negative Micro.

### P0. Numeric `G` is ambiguous between Macro and effective gain

The node's Y coordinate and vertical pointer are defined in effective bits:

```text
(Macro + Micro/100) * BitRatio
```

But the readout field is named only `G`, while the one-slider rule says numeric entry edits the focused slider alone. Typing `2` could therefore mean either:

- set Macro to 2; or
- request 2 effective bits and solve for the nearest Macro, like vertical drag.

Those meanings diverge whenever Bit Ratio is not 1 or Micro is nonzero. The GUI also offers a Ratio drag without naming a Ratio readout field, so the user cannot inspect or type the parameter from the custom interface.

**Required resolution:** rename fields by actual parameter (`Macro`, `Micro`, `Ratio`, `Freq`, `Q`) or explicitly define `G` as an effective target and give its one-slider inverse rule. Add a visible Ratio field/readout and numeric-entry tests at non-unity Ratio.

### P0. The publication unit for two independent engines is still undefined

The memory layout has `gc_lin[2][2][LIN_N]` and describes one inactive buffer and one active index. HP and LP rebuild independently. If only HP writes its half of the inactive pair and the common index flips, LP comes from an older or uninitialized generation. A later LP-only publication can similarly resurrect an old HP grid.

“Fill the inactive buffer completely” could mean copy the untouched engine first, rebuild both engines, or maintain independent indices, but the specification chooses none of them. §14 says this architectural issue was fixed in the plan; the design contract itself still does not contain the fix.

**Required resolution:** choose one publication unit:

- independent `(index, generation)` per engine; or
- copy the complete active HP+LP pair to the inactive pair, replace changed engines, then publish the whole pair.

Test alternating HP-only and LP-only rebuilds and assert the untouched grid remains byte-identical through every publication.

### P0. `gc_lin` and `gc_trace` ownership cannot safely share one unspecified active index

The inventory double-buffers both realized engine grids and five final display traces, but `@block` produces `gc_lin` while `@gfx` logically produces or consumes `gc_trace`. The eight metadata words are described only as counters, one active index, and flags.

If both buffer families share an index, `@block` and `@gfx` can flip each other's buffers. If they have separate indices, the inventory and protocol need to say so. The current three-step protocol refers to “the inactive buffer” without identifying which cache or writer owns it.

**Required resolution:** define separate metadata and state machines for realized-grid publication and completed-frame publication. Pin which thread writes each region, which thread flips each index, and how a frame retains its previous trace when a `gc_lin` generation changes mid-computation.

### P1. The integer Macro rounding tie is still cross-language ambiguous

Rev 7 says the Python/EEL2 tie problem disappeared because fractional snapping was removed, but the new formula still contains:

```text
round(pointer_bits / BitRatio - Micro/100)
```

Python uses ties-to-even; a typical EEL2 `floor(x + 0.5)` implementation rounds half ties toward positive infinity. They disagree at values such as `0.5`, `2.5`, and negative counterparts. Saying exact half-steps are tested is not enough unless the expected policy is stated.

**Required resolution:** pin one rounding rule and its expected values for positive and negative half-integers, then implement the same helper in Python and EEL2.

### P1. The “dense FFT” claim is contradicted by the 256-point realized cache

The text says the `BD/2` FFT bins eliminate the sparse-grid accuracy problem, but the fixed inventory stores only 256 values per engine. Resampling 4097 or 16385 useful bins to 256 log-spaced points creates a new sparse grid before the 512-point trace is drawn.

A narrow Brick transition or resonant feature can still fall between stored points. Interpolation in bits is now correctly pinned, but no error bound is given for the reduction to `LIN_N = 256`.

**Required resolution:** either retain enough dense bins for the drawable range or define and test a maximum bit error against the full FFT. Place worst-case cutoffs halfway between stored log points at both resolutions and all supported sample rates.

### P1. “Enabled domain” is undefined for Off and Min+Brick filters

Bands have an Enable slider, but HP/LP do not. Their audible enable state comes from slope and phase:

- slope Off is identity;
- Min+Brick is also identity;
- Linear+Brick is active.

The rule “draw a domain only when it has an enabled block” does not say whether identity HP/LP blocks count. Counting them can create an unnecessary identity trace or a false mixed-family dashed warning solely because an Off filter retains a selective placement.

**Required resolution:** define domain visibility in terms of audible activity and test Off, Min+Brick, Linear+Brick, and disabled-band placements.

### P1. The target-display timeline is inaccurate during rebuild coalescing

The spec says the new Linear magnitude is published as soon as it exists and therefore the graph leads the sound “inside the 100 ms rebuild coalescing window.” Before the rebuild runs, the new kernel and its magnitude do not exist; the graph must still show the previous realized grid. It leads the sound only after the target is built and while the old/new kernel crossfade is audible.

**Required resolution:** describe the three states explicitly:

1. dirty/coalescing: old realized curve remains visible;
2. target built and published: new target curve appears;
3. 50 ms audio crossfade: graph leads the audible transition until completion.

### P1. Verification does not cover every new one-slider gesture

The acceptance list verifies Macro drag and change-only Macro automation, but rev 7 also introduces Ratio drag and Alt/Q drag. It does not require that these gestures leave every other slider byte-identical, clamp correctly, or call exactly one `slider_automate()` only when their own value changes.

**Required resolution:** add a one-gesture-one-slider matrix for Frequency, Macro, Ratio, Q, and each numeric field. Snapshot all nine band sliders before and after every gesture and assert exactly the intended index changes.

### P1. The transcription gate remains too abstract to be a release gate

The gate names a parameter matrix but does not define the dump schema, case identifiers, domain, separate HP/LP grids, active resolution, or sample-rate encoding. It also does not state that a missing dump must fail the release gate rather than skip.

**Required resolution:** specify a self-describing dump format and a mandatory command. Include case ID, sample rate, phase, domain, engine, frequency, expected source, and measured bits. The release run must fail on missing or incomplete cases.

### P1. CPU acceptance has measurements but no pass/fail limit

Peak block time and xruns are the right metrics, but “measure” is not a gate. No test duration, exact buffer sizes, sweep cadence, deadline margin, or allowable regression against V0.9 is stated.

**Required resolution:** require zero xruns and pin the device, buffer sizes, duration, sweep pattern, and maximum peak-block-time regression or minimum deadline margin. Keep 192 kHz conditional on device support.

### P2. “Dominant axis at mouse-down” is not operationally defined

At the instant of mouse-down there is no movement vector, so no dominant axis exists. Implementations may choose on the first pixel, after a threshold, or after several frames, producing accidental Frequency/Macro/Ratio edits from normal click jitter.

**Required resolution:** define a drag threshold in logical units and choose the axis from displacement once that threshold is crossed. Until then, the action remains a click/select.

### P2. The Alt-drag Q mapping is also incomplete

Wheel Q has a natural “one step per notch” contract. Alt+vertical drag has no pixels-per-step, absolute mapping, acceleration, or fine-modifier rule. “Does the same” is insufficient for a continuous pointer gesture.

**Required resolution:** define relative Q sensitivity, clamp behavior, and whether Ctrl changes Alt-drag sensitivity as it does the wheel.

## Strengths Preserved in Rev 7

The following decisions are now strong and should remain:

- One gesture writes one slider; Micro remains typed-only.
- Min+Brick identity and Linear+Brick realized magnitude are phase-correct.
- Native FFT, explicit permutation, imaginary-lane zeroing, Hermitian half-spectrum, and bit-domain interpolation are the right DSP-display foundations.
- Active versus requested topology is separated, including the unusual but correct live Min-placement rule.
- Mixed placement families are visibly marked instead of hidden in documentation.
- Exact memory placement below `lp_base`, target-display intent, overrange labels, Retina-aware hit testing, and ordinary Linear oracle coverage are all materially improved.

## Recommended Gate Before Replanning

Resolve the six P0 items in the design before rewriting the implementation plan. The key decisions are the exact rev-7 gesture contract, the mathematical Ratio-drag mapping, the meaning of numeric `G`, and independent ownership/publication of HP, LP, and completed trace buffers. Once those are pinned, the plan can delete the obsolete pair-write machinery instead of carrying two incompatible interaction models forward.
