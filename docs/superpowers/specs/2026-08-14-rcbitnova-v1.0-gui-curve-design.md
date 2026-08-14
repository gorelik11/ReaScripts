# RCBitNova V1.0 — GUI: EQ curve with draggable nodes

**Date:** 2026-08-14
**Branch:** `rcbitnova`
**New file:** `JSFX/RCBitNova V1.0` (copy of V0.9). `rcbitnova-v0.9` remains the fallback tag;
V0.9 and earlier are frozen.
**Scope:** the first GUI stage — a graph of the static response with draggable band nodes.
Spectrum analyser and dynamics display are later stages (§7).

---

## 1. Why

The plugin has **96 sliders** and four bands. Reaching a parameter means hunting through a long
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

## 3. The curve

Computed **analytically**, not by FFT: for each of ~1000 x-positions, take the frequency and
multiply the magnitudes of every enabled block.

- **Bands:** the TPT/ZDF SVF magnitude derived from the same coefficients `svf_make` produces.
- **HP/LP:** `hplp_digital_mag`, already used by the oracle and already proven to match the
  real response.
- **Band gain** is `bit_gain(Macro, Micro, BitRatio)` — the identical expression used in the
  audio path, so the graph shows what is heard rather than a decorative parallel formula that
  drifts from the DSP over time.
- **Proportional-Q:** the drawn width uses `band_qeff(b)`, the effective Q, not the knob Q —
  otherwise a band with Q Character above zero would draw at the wrong width. Displaying "true
  Q" was a roadmap item and comes free here.

**FIR Brick and linear-phase mode** draw the same magnitude as their min-phase equivalents,
because that is exactly how the kernels are built (V0.6: magnitude via impulse-FFT of the
min-phase cascade, so `Linear mag == Min mag` by construction).

**Cost and caching:** ~1000 points × up to 6 blocks per frame is too much to recompute at 30 fps.
The curve is recomputed only when a relevant parameter changed (a cheap signature over the band
and filter sliders, the same trick `hp_sig`/`lp_sig` already use for kernel rebuilds) and is
otherwise redrawn from a cached array of y-values.

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

**Gain writes both Macro and Micro:** the target in bits is snapped to 0.05 first, then split
into the integer part (Macro, `+5`) and the remainder (Micro, `+6`, in % of a bit — so 0.05 bit
= 5 %, a clean multiple of Micro's own 0.1 step). Both writes get `slider_automate`.

Note the effective gain also depends on **Bit Ratio** (`+7`), which scales
`(Macro + Micro/100)`. Dragging changes Macro/Micro only and leaves Bit Ratio alone; the node's
drawn position uses the full `bit_gain(Macro, Micro, BitRatio)`, so with Bit Ratio ≠ 1 the node
still sits where the audio actually is.

**Numeric entry** follows the pattern already working in `Fable Eq Dynamic.jsfx` (the owner's own
Effects folder, lines ~2160–2190): accumulate digits, minus and dot into a small buffer via
`gfx_getchar`, parse on Enter. That is a proven implementation to adapt rather than an
experiment.

**Node colour encodes placement** (Both / Mid / Side / Left / Right). Without it the graph would
imply a band acts on the whole signal when it acts only on the side.

**Disabled bands** draw as dimmed outlines — visible, so a forgotten band is not invisible, but
clearly not contributing.

## 6. Layout

A single dark view: the graph fills the window; a readout strip along the bottom shows the
selected band's Freq / Gain (bits) / Q / effective Q / Type / Placement. `gfx_init` requests a
default size; the drawing is resolution-independent so REAPER's window resizing works.

The existing slider list remains untouched below the graph, as REAPER always shows it.

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

1. Band magnitude at the centre frequency equals the applied bit gain, for bell / low shelf /
   high shelf, across gains and Q values.
2. Band magnitude far from the centre tends to unity.
3. HP/LP magnitude matches `hplp_digital_mag` at every slope, and is −3 dB at the cutoff.
4. The combined curve equals the product of the individual magnitudes.
5. Proportional-Q: with Q Character above zero, the drawn width follows `band_qeff`, not the
   knob Q.
6. Bit-to-pixel mapping round-trips: a gain converted to y and back returns the same value, and
   the 0.05-bit snap always lands on a multiple.
7. Clamping beyond ±4 bits does not wrap or invert.
8. Macro/Micro split: for a swept target in bits, `Macro + Micro/100` reproduces it exactly, and
   Micro always lands on a multiple of its own 0.1 step (0.05 bit = 5 %).
9. With Bit Ratio ≠ 1 the node's drawn gain equals `bit_gain(Macro, Micro, BitRatio)` — a naive
   `Macro + Micro/100` would place the node in the wrong spot.

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
