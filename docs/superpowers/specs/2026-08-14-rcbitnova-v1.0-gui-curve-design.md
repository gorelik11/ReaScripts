# RCBitNova V1.0 — GUI: EQ curve with draggable nodes

**Date:** 2026-08-14 (**rev 2**, after the weakness review
`2026-08-14-rcbitnova-v1.0-gui-curve-weaknesses.md` — disposition in §10)
**Branch:** `rcbitnova`
**New file:** `JSFX/RCBitNova V1.0` (copy of V0.9). `rcbitnova-v0.9` remains the fallback tag;
V0.9 and earlier are frozen.
**Scope:** the first GUI stage — a graph of the static response with draggable band nodes.
Spectrum analyser and dynamics display are later stages (§7).

---

## 1. Why

The plugin has **95 sliders** and four bands. Reaching a parameter means hunting through a long
list, which is the "slider-reachability pain" the roadmap has recorded since V0.3. A curve with
draggable nodes fixes the common gestures — set a frequency, set a gain, widen a bell — and shows
what the filters are actually doing.

The owner's priority, asked directly: the curve with draggable nodes first; the analyser can
wait.

## 2. Non-negotiable constraints

- **The GUI cannot change the sound.** `@gfx` never touches the signal path; it reads parameters
  and writes sliders. Bit-accuracy and every live result from V0.9 therefore hold by
  construction. Gate: a null test V0.9 vs V1.0, mouse untouched, must be digital silence.
- **Sliders stay fully usable.** No parameter becomes reachable *only* through the graph. This
  keeps automation working exactly as before and leaves a fallback if the GUI has a bug.
- **`slider_automate()` after every write.** Without it REAPER neither records the change into
  automation nor updates its own display — the classic defect of hand-written JSFX interfaces.
- V0.9 and earlier stay frozen; work happens in a new file.

## 3. The curve — one trace per placement domain

**A single combined trace is mathematically wrong here** (review P0-1). Each block can sit in
Both, Mid, Side, Left or Right, and a selective block is a stereo 2x2 matrix, not a scalar.
Serial blocks in different domains would have to be multiplied as ordered complex matrices;
multiplying their scalar magnitudes applies every filter to every domain and draws boost or cut
that neither output channel has.

**Solution, following ReEQ** (`ReJJ-1.0.11/ReEQ.jsfx`, `draw_filter_response(group, r,g,b)`):
draw **one trace per domain**, each in its own colour, and only when that domain has an enabled
block. Within one domain, multiplying magnitudes is exactly correct.

| Domain | Colour (from ReEQ, kept for familiarity) |
|---|---|
| Both / stereo | white |
| Mid | green 92,190,98 |
| Side | cyan 91,236,252 |
| Left | yellow 240,201,27 |
| Right | red 213,65,66 |

A domain trace includes the **Both** blocks as well as its own, because a Both block genuinely
processes that domain too - so the Mid trace is "what actually happens to a mid signal", not
"what the mid-placed bands do". The white trace is drawn whenever any Both block is enabled.

**Stated limitation:** when M/S-placed and L/R-placed blocks are used *at the same time*, no set
of per-domain scalar traces describes the true channel response - the stages do not factor. The
traces then read as "what each group does", exactly as ReEQ's do. This is a display limitation,
documented rather than hidden, and it is why the graph never claims to be a measurement.

### 3.1 Magnitude per block, honestly per mode

Review P0-2 is right that "Linear draws the same as Min" is false in general: the min-phase
magnitude is the kernel's *target*, and the finite Kaiser window changes what is realized -
which is the very reason Resolution exists. FIR Brick is worse: in the min-phase path its slope
maps to `nsec = 0`, i.e. **Off**, so drawing it from the min-phase helper would show no filter
at all.

| Block / mode | Magnitude source |
|---|---|
| Bands (Bell / Low Shelf / High Shelf) | TPT/ZDF SVF magnitude from `svf_make` coefficients |
| HP/LP, Phase = Min | `hplp_digital_mag` |
| HP/LP, Phase = Linear, ordinary slopes | magnitude of the **actual windowed kernel** at the ACTIVE `BD` (Normal 8192 / High 32768) |
| HP/LP, Slope = FIR Brick | magnitude of `fir_brick_kernel`, never the min-phase helper |

- **Band gain** is `bit_gain(Macro, Micro, BitRatio)` - the same expression as the audio path.
- **Proportional-Q:** drawn width uses `band_qeff(b)`, the effective Q, not the knob Q.

Computing a windowed-kernel magnitude at 32768 taps per graph point is far too expensive per
frame, so the Linear/Brick traces are evaluated on a **coarse frequency grid at kernel-rebuild
time** (that work is already happening there) and interpolated for display. This keeps the drawn
curve tied to the kernel that is actually convolving.

### 3.2 Log floor

The curve must become bits: `bits = log(mag)/log(2)`. FIR Brick's target contains **exact
zeros**, and serial cuts underflow, so `log(0)` would produce non-finite coordinates and corrupt
a whole line strip before any clamp (review P1-5). Magnitudes are floored at `1e-7` (-140 dB, far
below the +-4-bit viewport) before the log, and the resulting bit value is clamped before pixel
conversion.

**Scope note:** the project invariant "no `log` in the DSP path" applies to `@sample`. `log` in
`@gfx` is not an audio-path regression, and the bit-accuracy grep gate must be scoped to the DSP
sections so this is not mistaken for one.

### 3.3 Cache and invalidation

~1000 points x several blocks is too much per frame, so y-values are cached.

**Memory (review P1-2):** the cache gets a **fixed region reserved before `lp_base` is aligned**,
in the static layout beside `lp_rt`/`lp_geo`/`lp_off`. It must never live relative to `lp_top`:
`lp_relayout()` clears that region and calls `freembuf(lp_top + 1)`, which would free or
overwrite a cache above it - while `@gfx` runs on another thread. `@gfx` never allocates and
never relocates audio memory. The memory-top tests gain the cache region.

**Invalidation (review P1-3):** a weighted arithmetic signature like `hp_sig` is not
collision-free, and a collision leaves a stale but plausible curve - precisely the silent failure
the oracle-first policy exists to prevent. Instead `@slider` compares a **snapshot of each
relevant value** and bumps a `curve_gen` counter on any difference. The watched set:

- per band: Enable, Type, Freq, Q, Macro, Micro, Bit Ratio, Placement, Q Character
- HP/LP: Slope, Freq, Resonance, Placement, plus **active** Phase and **active** Resolution
- `srate` - every digital response is sample-rate dependent

## 4. Axes

- **X:** logarithmic, 20 Hz – 20 kHz, gridlines at 100 / 1k / 10k with labels.
- **Y:** **in bits**, gridlines on whole bits, range **±4 bits** (= ±24 dB). Macro allows ±16
  bits, but a node parked at 16 bits would make the graph unreadable; values beyond the scale
  are clamped to the edge and labelled with their number so nothing is hidden.

Bits — not dB — because every gain parameter in this plugin is already in bits; the axis is a
direct view of the parameter rather than a conversion.

## 5. Nodes and interaction

One node per band, drawn at (frequency, gain).

| Gesture | Effect |
|---|---|
| Drag horizontally | Frequency |
| Drag vertically | Gain, in **0.05-bit steps** (= 5 % of Micro) |
| Shift + drag | Fine step |
| Mouse wheel on a node | Q |
| Hover + type a digit | Numeric entry: Enter commits, Esc cancels, Backspace deletes |
| Click | Select (the selected node's readouts are shown) |

**Slider map per band `b` (0-based), base `10*(b+1)`** — verified against the file, not assumed:

| Offset | Parameter | Range / step |
|---|---|---|
| +1 | Enable | 0/1 |
| +2 | Type | Bell / Low Shelf / High Shelf |
| +3 | Freq | 20–20000, step 1 |
| +4 | Q | 0.1–10, step 0.001 |
| +5 | Macro (bits) | −16…16, step 1 |
| +6 | Micro (% bit) | −100…100, step 0.1 |
| +7 | Bit Ratio | 0–3, step 0.1 |
| +8 | Placement | Both / Mid / Side / Left / Right |
| +9 | Q Character | 0–1 |

**Y is EFFECTIVE gain, and drag inverts Bit Ratio** (review P0-3, owner's choice). The node is
drawn at `bit_gain(Macro, Micro, BitRatio)`, so for the node to follow the pointer the drag must
solve backwards:

```
base_target = effective_target / BitRatio      (BitRatio != 0)
```

- `BitRatio == 0` has **no inverse**: every Macro/Micro setting sounds at 0 bits. The node is
  pinned at the zero line, drawn in a distinct "locked" style, and vertical drag does nothing.
  A readout says why. Silently resetting Bit Ratio would destroy a setting the owner chose
  deliberately.
- If the inverse exceeds the representable base range, the value **clamps** and the node stops
  following the pointer rather than jumping.
- Division by e.g. 0.3 will not land on the Micro grid; the result is snapped after inversion,
  so the audible step stays a clean multiple of 0.05 bit **of effective gain** only when
  `BitRatio` is 1. Otherwise the snap applies to the base value and the readout shows the true
  effective figure.

**Canonical Macro/Micro split** (review P1-6). Many pairs encode the same gain (`+0.95` bits is
`Macro 0, Micro 95` or `Macro 1, Micro -5`), so one rule is pinned: **Macro = `floor`** of the
base value (toward negative infinity, identical for positive and negative), **Micro = the
remainder in %**, always in `[0, 100)`. The combined base is clamped to the representable range
**before** splitting.

Two slider writes are not atomic, so: write Macro first, then Micro, then `slider_automate` both;
and **call `slider_automate` only when the snapped pair actually changed** — writing every frame
would otherwise flood automation with identical points.

**Numeric entry targets a named field, not "the node"** (review P1-7). One node carries Freq,
Gain and Q, so "hover and type" is ambiguous. The readout strip at the bottom has three fields —
**F / G / Q** — and clicking one gives it keyboard focus (highlighted border). Typing then edits
that field: digits, minus and dot accumulate, Enter commits, Esc cancels, Backspace deletes.
Units are shown in the field label: Hz, bits, Q. The `gfx_getchar` loop is adapted from
`Fable Eq Dynamic.jsfx` (~lines 2160–2190).

**Drag semantics, pinned:**

| | Behaviour |
|---|---|
| Drag capture | The node grabbed on mouse-down keeps capture until release, even outside the graph |
| Axis lock | None by default; Shift held **at mouse-down** locks to the dominant axis |
| Shift after start | Changes sensitivity to fine (0.01 bit / 1 Hz), does not re-lock the axis |
| Wheel | Up = higher Q (narrower), one step per notch; Ctrl+wheel = fine |
| Overlapping nodes | The topmost by band index wins; a second click within 300 ms cycles through them |
| Release outside window | Treated as a normal release, value kept |
| Esc during drag | Cancels, restoring the value from mouse-down |

**Node colour encodes placement** (Both / Mid / Side / Left / Right). Without it the graph would
imply a band acts on the whole signal when it acts only on the side.

**Disabled bands** draw as dimmed outlines — visible, so a forgotten band is not invisible, but
clearly not contributing.

## 6. Layout and coordinates

Size is declared on the section line — **`@gfx 900 500`** — which is the JSFX contract.
(`gfx_init()` named in rev 1 is the ReaScript gfx API, not JSFX; review P1-8.)

- **Base coordinate space** 900x500 logical units; everything is drawn through one scale factor
  derived from the actual `gfx_w`/`gfx_h`, and **hit-testing uses the same transform** as
  drawing. On Retina, `gfx_ext_retina` must be applied to both or nodes render in one place and
  respond in another.
- **Rectangles:** graph occupies the top area with 40 units of left margin (bit labels) and 24
  bottom (frequency labels); the readout strip is the bottom 60 units.
- **Minimum usable size** 480x280; below it the readout strip is dropped before the graph.
- **Node hit radius** scales with the transform, minimum 8 logical units.
- Long over-range labels are clipped to the plot rectangle, never drawn over the axis.

Whether REAPER shows its generic slider list below the custom graph or behind a UI toggle is
confirmed **live**, not assumed.

## 7. Explicitly out of scope

Deferred so the first stage stays finishable:

- **Spectrum analyser** → V1.1. Heaviest part in both CPU and code.
- **Live dynamics curve** (Mode A/B action) → V1.2. Needs detector state passed from `@sample`
  to `@gfx`.
- **Eight bands** — a DSP and memory change, not a GUI one; its own cycle and spec.
- **Dragging HP/LP on the graph** — they are drawn in V1.0 but adjusted by their sliders.
- **`@serialize`** — unnecessary: REAPER already persists slider values and the GUI holds no
  state of its own.
- Themes and skins.

## 8. Verification

**Oracle (Python):** the magnitude functions are testable without a GUI, and that is where the
value is — a wrong curve is a silent, plausible-looking bug.

1. **Bell** magnitude at `fc` equals the full applied bit gain. **Shelves do NOT**: the shipping
   TPT shelf uses `A = sqrt(gain_lin)`, so at `fc` a shelf is at **half** the gain in
   logarithmic terms — measured: +-2.0000 bits on the plateau, +-0.9966 at `fc` (review P0-4;
   rev 1's assertion would have failed a correct implementation). Shelf tests assert `sqrt(gain)`
   at `fc` and full gain on the plateau.
   *Node convention, pinned:* a shelf node is a **handle** drawn at `(fc, full gain)`, so it does
   not sit on its own curve. Stated here so it is not later diagnosed as a rendering defect.
2. Band magnitude far from the centre tends to unity.
3. HP/LP magnitude matches `hplp_digital_mag`, and is **-3 dB at cutoff only for non-Brick
   slopes at Resonance 0** (review P1-1): the resonance bell multiplies the cutoff magnitude, and
   FIR Brick follows the sampled/windowed step contract instead. Separate tests cover
   Resonance 0..1 and realized Brick behaviour.
4. **Per-domain traces:** each domain's trace equals the product of the magnitudes of the Both
   blocks and that domain's blocks — and a mixed-placement configuration is included, with the
   expected values computed independently rather than by calling the same helper the
   implementation uses (otherwise the test only proves the code agrees with itself).
5. Proportional-Q: with Q Character above zero, the drawn width follows `band_qeff`, not the
   knob Q.
6. Bit-to-pixel mapping round-trips; the 0.05-bit snap always lands on a multiple.
7. Clamping beyond +-4 bits does not wrap or invert — for individual nodes **and for the total
   curve**, which can exceed the viewport while every node is inside it (review P2-1).
8. **Canonical split:** for a swept target, `floor`-based Macro plus Micro in `[0,100)`
   reproduces the value exactly at every integer boundary, at +-0.05, at +-16, and for negative
   values.
9. **Bit Ratio inversion:** for every Ratio step 0..3, the node follows the cursor within a
   stated tolerance or reports a constrained state; `Ratio = 0` is locked, not silently reset.
10. **Realized Linear/Brick magnitude:** the drawn curve for Linear at Normal vs High differs in
    the steep low-frequency case that motivated V0.7, and the Brick trace comes from
    `fir_brick_kernel` — a Brick slope must never draw as "no filter".
11. **Log floor:** exact zeros, subnormals and a serial HP+LP with no passband all produce finite
    coordinates.
12. **Curve-generation counter:** every watched field, changed alone, invalidates the cache; a
    deliberately-constructed pair of configurations that an arithmetic signature would collide on
    must NOT reuse the cache.

**Transcription gate (review P1-4).** Python tests prove the Python maths; the shipping graph is
a separate EEL implementation and a sign error there can still draw a smooth, believable curve.
So: a debug path dumps the JSFX curve cache at a pinned parameter matrix, and the values are
compared numerically against the oracle. Screenshots are not a numeric oracle. Coverage: shelf
plateaus on both sides, `fc`, near-Nyquist warping, proportional-Q, Brick, and both sample rates.

**Live in REAPER, with the owner:**

- Drag each node: frequency, gain and Q change, and the graph matches what is heard.
- The written values appear in the slider list, and **automation records them** (the
  `slider_automate` gate).
- Numeric entry: type, Enter, Esc, Backspace.
- **Null test V0.9 vs V1.0** with the mouse untouched → digital silence.
- **CPU with the GUI open vs closed** — measured, not assumed. V0.8's only real defect was found
  by the CPU meter and by nothing else.
- Placement colours match the actual placement of each band.

## 9. Method

Unchanged: verify the magnitude maths in Python first → TDD the oracle → transcribe to JSFX →
live-verify with the owner → Fable final review → tag `rcbitnova-v1.0`.

**EEL2 reminder:** V0.8's defect was a compound assignment under a conditional that read
correctly and never executed. Its exact parsing cause remains unproven, so new code avoids both
compound assignment under `?` and unparenthesized conditional branches. GUI code is dense with
conditionals and is exactly where this hides again.

## 10. Weakness-review disposition (rev 1 → rev 2)

Every finding accepted; two were verified numerically before accepting.

| Finding | Disposition |
|---|---|
| **P0** Mixed Placement has no single scalar response | **Accepted** — one trace per domain, ReEQ's model and colours (§3). The owner rejected picking a single domain: he uses all of them. The M/S-plus-L/R limitation is documented, not hidden |
| **P0** Linear/FIR Brick are not the min-phase curve | **Accepted** — three separate magnitude sources (§3.1). Confirmed in the code: a Brick slope maps to `nsec = 0` in the min path, so rev 1 would have drawn "no filter" for it |
| **P0** Vertical drag inconsistent with Bit Ratio | **Accepted** — Y is effective gain, drag inverts the Ratio; `Ratio = 0` locks the node instead of silently resetting a deliberate setting (§5) |
| **P0** Shelf centre-gain assertion is false | **Accepted, measured**: +-2 bits plateau vs **+-0.9966 at `fc`**. Tests split by type; the shelf node is pinned as a handle (§8.1) |
| **P1** -3 dB cutoff test needs scope | **Accepted** — asserted only for non-Brick at Resonance 0 (§8.3) |
| **P1** Curve cache has no memory ownership | **Accepted** — fixed region below `lp_base`; never relative to `lp_top`, which `lp_relayout` frees (§3.3) |
| **P1** Arithmetic signature can collide | **Accepted** — per-field snapshot and a `curve_gen` counter; a collision test is required (§3.3, §8.12) |
| **P1** Python tests do not verify the EEL transcription | **Accepted** — numeric dump-and-compare gate (§8) |
| **P1** Product-then-log needs a zero contract | **Accepted** — 1e-7 floor, clamp before pixels, and the "no log" invariant scoped to `@sample` (§3.2) |
| **P1** Macro/Micro split non-canonical | **Accepted** — `floor` + remainder in `[0,100)`, clamp before split, `slider_automate` only on real change (§5) |
| **P1** Numeric entry does not identify the parameter | **Accepted** — focusable F / G / Q fields with units; full drag/wheel semantics pinned (§5) |
| **P1** Resize and Retina asserted, not designed | **Accepted** — `@gfx 900 500`, one shared transform for drawing and hit-testing, minimum size, scaled hit radius (§6). rev 1's `gfx_init` was the ReaScript API, not JSFX |
| **P2** Over-range covers nodes but not the curve | **Accepted** — clipping indicators and deterministic edge-label handling (§8.7) |
| **P2** Slider count off by one | **Accepted, verified**: 95 declarations, not 96 (§1) |
