# RCBitNova V1.0 GUI Curve - Weakness Review

**Date:** 2026-08-14
**Reviewed spec:** `2026-08-14-rcbitnova-v1.0-gui-curve-design.md`
**Reviewed base:** `JSFX/RCBitNova V0.9` at tag `rcbitnova-v0.9`
**Review type:** response mathematics, parameter mapping, JSFX memory, interaction, and verification audit

## Verdict

The oracle-first direction is correct, and using `band_qeff()` is essential. The
fixed +/-4-bit viewport with explicit over-range labels is also a sensible display
policy.

The current curve contract is not yet mathematically well-defined. Mixed
Placement filters form a stereo transfer matrix, not one scalar magnitude whose
blocks can be multiplied. Linear HP/LP is only targeted from the min-phase
magnitude before finite windowing, and FIR Brick has an entirely separate target.
Two proposed oracle assertions are already false for the shipping SVF: shelves
have half the logarithmic gain at their cutoff, and HP/LP is not universally -3 dB
there when Resonance or FIR Brick is active.

Interaction also has one blocking ambiguity: the node is drawn at effective gain
after Bit Ratio, while vertical drag writes unscaled Macro/Micro. Without an
inverse mapping, the node cannot follow the pointer for Ratio other than 1, and
Ratio 0 has no inverse at all.

## Findings

### P0 - Mixed Placement has no single scalar combined response

Section 3 proposes multiplying the magnitudes of every enabled HP/LP and band.
That is valid only when every block processes the same scalar domain. RCBitNova can
place each block independently in Both, Mid, Side, Left, or Right.

A selective block is a stereo matrix. For example:

```text
Left placement:  [[H, 0], [0, 1]]
Mid placement:   M/S transform -> [[H, 0], [0, 1]] -> inverse transform
```

Serial blocks with different placements must be multiplied as ordered complex
2x2 matrices. Multiplying their scalar magnitudes applies every filter to every
domain and can draw attenuation or boost that neither output channel actually
has. Placement colours on nodes disclose the settings but do not repair the
combined curve's mathematics. HP/LP Placement makes the same problem apply before
the four bands.

**Required change:** define what the main curve means. Viable choices include:

- Restrict the combined curve to configurations where all enabled blocks use Both;
- Draw separate domain traces and state exactly how mixed L/R and M/S stages are handled;
- Compute the ordered complex stereo transfer matrix per frequency and display
  named probes or metrics such as L->L, R->R, Mid->Mid, Side->Side, or singular values;
- Draw individual band shapes only and remove the claim that one total trace shows
  what is heard under mixed Placement.

The oracle must include non-commuting mixed-placement sequences. A test that
defines the expected curve as the product of the same scalar helpers only proves
the implementation agrees with its own incorrect assumption.

### P0 - Linear HP/LP and FIR Brick are not the min-phase curve by construction

For ordinary Linear slopes, V0.9 samples the min-phase magnitude, transforms it to
an impulse, shifts it, and multiplies it by a finite Kaiser window. Windowing
changes the realized frequency response. The min-phase magnitude is the kernel's
**target**, not its exact final magnitude. Normal and High resolutions can differ
materially in steep low-frequency cuts; that is the reason Resolution exists.

FIR Brick is a separate and clearer contradiction. V0.9 builds it from an ideal
sampled step:

```eel
m = HP ? (f >= fe ? 1 : 0) : (f <= fe ? 1 : 0);
```

In the min-phase path the same slope selection maps to `nsec = 0`, i.e. Off. It has
no min-phase Brick equivalent to draw. The finite window then gives the actual
Brick transition and Gibbs behavior its own shape.

**Required change:** choose between a target curve and a realized curve and label
the contract honestly. If the graph must show what is heard:

- Min uses `hplp_digital_mag`;
- Linear uses the magnitude of the actual finite windowed kernel at the active
  Resolution, or a verified equivalent calculation;
- FIR Brick uses `fir_brick_kernel`, never the min-phase/Off helper.

Test Min versus Normal versus High at the low-frequency and steep-slope cases that
motivated V0.7, plus Brick transition width, passband ripple, stopband leakage, and
both sample rates and resolutions.

### P0 - Vertical drag is inconsistent with Bit Ratio

The node is drawn at effective gain:

```text
effective_bits = (Macro + Micro/100) * BitRatio
```

The proposed drag takes the pointer's Y value in bits and writes that value directly
into Macro/Micro while leaving Bit Ratio unchanged. For Ratio 2, dragging to +2
bits writes base gain +2 and the node redraws at +4. For Ratio 0, every Macro/Micro
setting still draws and sounds at 0, so vertical drag cannot move the node at all.

**Required change:** pin whether Y represents effective bits or pre-ratio parameter
bits. Because the node and audible gain already use effective bits, pointer mapping
normally requires:

```text
base_target = effective_target / BitRatio
```

That needs explicit behavior for Ratio 0, clamping when the inverse exceeds the
Macro/Micro range, and quantization when division by values such as 0.3 cannot land
exactly on the Micro grid. Test every Ratio step from 0 to 3 and assert the node
either follows the cursor within a stated tolerance or displays a clear constrained
state.

### P0 - The shelf centre-gain oracle assertion is false

The shipping TPT shelf uses `A = sqrt(gain_lin)`. At `f = fc`, both Low Shelf and
High Shelf have magnitude `A`, halfway to the shelf plateau in logarithmic units.
The existing oracle confirms, for a +/-2-bit shelf:

```text
plateau gain:       +/-2 bits
magnitude at fc:    +/-1 bit
```

Verification item 1 instead requires Bell, Low Shelf, and High Shelf all to equal
the full applied gain at centre. A correct implementation must fail that test.

This also means a shelf node drawn at `(fc, full_gain)` does not lie on its
individual response curve. That can be a deliberate handle convention, but it must
be stated so it is not diagnosed later as a rendering defect.

**Required change:** split the tests by type. Bell equals full gain at `fc`;
shelves equal `sqrt(gain_lin)` at `fc` and approach full gain on their boosted/cut
plateau. Pin whether shelf nodes represent parameter handles or points on the curve.

### P1 - The HP/LP -3 dB cutoff test needs scope

Verification item 3 says HP/LP is -3 dB at cutoff at every slope. That holds for
the staggered Butterworth cascade with Resonance 0. It does not hold when the
separate resonance bell is active: its centre gain multiplies the Butterworth
cutoff magnitude. FIR Brick also follows the sampled/windowed step contract rather
than the Butterworth -3 dB contract.

**Required change:** assert -3 dB only for non-Brick slopes at Resonance 0. Add
separate centre-response tests for Resonance 0..1 and realized Brick tests. Keep
"matches the production response" as the primary criterion rather than forcing
all filter types into one cutoff rule.

### P1 - The curve cache has no pinned memory ownership

The design requires roughly 1000 cached y-values but assigns no address. V0.9 uses
low instance memory for DSP state and dynamically packs large Linear engines above
`lp_base`; `lp_relayout()` clears that region and calls `freembuf(lp_top + 1)`.

An ad hoc fixed cache address can overwrite audio state. A cache placed relative to
the current `lp_top` can move or be invalidated on Resolution changes while `@gfx`
runs on a separate thread.

**Required change:** reserve a fixed `gfx_curve` region in the static layout before
`lp_base` is aligned, or otherwise prove it can never overlap any Normal/High
packing. Include it in memory-top tests and assert that every relayout leaves its
address and contents legal. Do not let `@gfx` allocate or relocate audio memory.

### P1 - A cheap arithmetic signature can leave a stale plausible curve

The proposed signature spans dozens of values. Weighted sums like `hp_sig` are not
collision-free; two different band configurations can produce the same scalar and
skip recomputation. This is precisely the silent, plausible-looking failure the
oracle-first policy is meant to prevent.

The invalidation set must also include more than band gain/frequency/Q:

- enable, type, Q Character, Bit Ratio, and Placement under any placement-aware curve;
- HP/LP slope, frequency, resonance, Placement, active Phase, and active Resolution;
- `srate`, because every digital response is sample-rate dependent.

**Required change:** compare a cached snapshot of each relevant value, or increment
a dedicated curve-generation counter from `@slider` after exact per-field change
detection. Test single-field changes and deliberate old-signature collisions.

### P1 - Python-only maths tests do not verify the EEL transcription

The nine tests can prove the Python response functions, but the shipping graph is
a separate EEL implementation of complex state-space magnitude, log-frequency
mapping, log2 conversion, clamping, and caching. A sign error in the JSFX can still
produce a smooth believable curve while every Python test remains green.

**Required change:** add a transcription gate. For a deterministic parameter
matrix, export selected JSFX cache points through a probe/debug path and compare
them numerically with the oracle, or create a source-level test around one shared,
pinned formula plus live pixel checks at known coordinates. Cover DC-side shelf
plateaus, `fc`, Nyquist-side plateaus, high-frequency warping, proportional-Q, and
Brick. Screenshot-only visual judgement is not a numeric oracle.

### P1 - Product-then-log needs a zero/underflow contract

To draw a bit axis, a magnitude product must become:

```text
bits = log(magnitude) / log(2)
```

FIR Brick's target contains exact zeros, and deep serial cuts can underflow or
approach zero. `log(0)` can produce non-finite coordinates and corrupt a line strip
before the +/-4-bit clamp is applied.

**Required change:** accumulate finite log magnitudes with a pinned epsilon/floor,
then clamp the resulting bit value before pixel conversion. Test exact zero,
subnormal magnitudes, NaN/Inf rejection, and a serial HP+LP configuration with no
meaningful passband. Scope the old "no log in DSP" invariant to `@sample`; GUI-only
`log` must not be mistaken for an audio-path regression.

### P1 - Macro/Micro splitting is non-canonical and incomplete at boundaries

Many slider pairs encode the same base gain. For example, +0.95 bits can be
`Macro=0, Micro=95` or `Macro=1, Micro=-5`. "Integer part and remainder" does not
pin truncation versus floor for negative values or behavior near +/-16.

The representable base range is also not merely the Macro range: with Micro it can
reach approximately +/-17, and Bit Ratio can take effective gain to approximately
+/-51 bits. An inverse Ratio drag may request values outside that range.

Two slider writes are not one atomic parameter. A representation change across an
integer boundary can briefly expose an unintended intermediate gain and can create
dense automation points if unchanged snapped values are written every GUI frame.

**Required change:** define one canonical split for positive and negative values,
clamp the combined base value before splitting, and choose write/notification order.
Call `slider_automate()` only when the snapped pair actually changes. Test every
integer boundary, +/-0.05, +/-16, the true combined extrema, Ratio inversion, and
recorded automation playback.

### P1 - Numeric entry does not identify which node parameter is being edited

The borrowed Fable pattern works because each hovered knob maps to one value. One
RCBitNova node represents Frequency, Gain, and Q. "Hover + type a digit" does not
say which of the three receives the number, what unit is parsed, or how the user
switches fields.

Likewise, "Shift + drag = fine" does not define whether it refines frequency, gain,
both axes, or what happens when Shift is pressed after a drag has started.

**Required change:** give keyboard focus to a concrete readout field or define
explicit F/G/Q entry modes, units, ranges, and focus indication. Pin drag capture,
axis locking, Shift sensitivity, wheel direction/step, overlapping-node selection,
release outside the window, and cancellation. Live verification should check
parameter identity and values, not only that digits can be entered.

### P1 - Resize and Retina behavior is asserted, not designed

The spec says drawing is resolution-independent but provides no logical coordinate
system, minimum plot dimensions, scaled hit radius, or text-overflow policy. On a
Retina Mac, drawing and mouse coordinates must use the same `gfx_ext_retina`
transform or nodes can render in one place and respond in another.

It also names `gfx_init` for the default size. In JSFX the preferred initial size
is declared on the `@gfx width height` section; `gfx_init()` is the ReaScript gfx
API pattern, not the normal JSFX contract.

**Required change:** pin a base coordinate space, graph/readout rectangles, Retina
transform, minimum usable size, and shared draw/hit-test transforms. Verify at 1x
and 2x scale, small/default/large windows, and edge nodes with long over-range
labels. Confirm live whether REAPER presents the generic slider list below the
custom graph or through a UI-mode switch; do not rely on that layout without a gate.

### P2 - Over-range handling covers nodes but not the total curve

Clamping and labelling an individual node prevents a +/-16-bit setting from being
hidden, as intended. The combined response can exceed +/-4 even when every node is
inside the viewport, and the spec does not define clipping or an over-range marker
for the curve itself.

Several nodes can also clamp to the same top or bottom edge, causing labels and hit
targets to overlap. Effective gain can reach far beyond +/-16 because of Micro and
Bit Ratio, so label width is not bounded by the Macro range cited in §4.

**Required change:** define curve clipping indicators and deterministic edge-label
collision handling. Test all four nodes over-range at nearby frequencies, mixed
positive/negative values, effective extrema, and a combined curve that clips
without any individual node clipping.

### P2 - The slider-count premise is off by one

`JSFX/RCBitNova V0.9` contains 95 slider declarations, not 96. The sparse highest
ID is 142, but IDs are not a count. This does not affect the GUI architecture, yet
the stated pain point should use the verified count just as the slider map does.

## What Is Already Strong

- The Y axis uses native bit units rather than an unnecessary dB abstraction.
- Values outside +/-4 bits remain visible through clamped nodes and numeric labels.
- Bell width is based on the actual `band_qeff()` law, including Q Character and Bit Ratio.
- Disabled bands remain discoverable without contributing to the response.
- Slider writes explicitly require `slider_automate()` and preserve generic controls.
- Curve maths is scheduled for oracle tests before GUI implementation.
- GUI-open versus GUI-closed CPU measurement and a V0.9 null test are explicit gates.

## Required Spec Edits Before Implementation

1. Define a mathematically valid response display for mixed Placement.
2. Separate Min, realized Linear, and FIR Brick HP/LP curves.
3. Define effective-gain drag inversion for every Bit Ratio, especially zero.
4. Correct shelf-centre and HP/LP cutoff oracle assertions.
5. Reserve collision-free curve-cache memory and collision-free invalidation.
6. Add a JSFX-versus-Python numeric transcription gate.
7. Pin finite log-floor behavior and canonical Macro/Micro splitting.
8. Define keyboard target, drag/wheel semantics, Retina scaling, and minimum layout.
9. Extend over-range behavior to the total curve and overlapping edge labels.
