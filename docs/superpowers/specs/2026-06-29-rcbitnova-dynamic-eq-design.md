# RCBitNova — Bit-Accurate Mid-Side Dynamic EQ — Design Spec

**Date:** 2026-06-29
**Status:** Design approved, pending spec review
**Author:** Dima Gorelik (design with Claude)
**Type:** JSFX plugin (REAPER), GPL

---

## 1. Purpose

A mid-side **dynamic** parametric EQ in the spirit of TDR Nova / FabFilter Pro-Q,
but processing entirely in **bit logic** (RCBit) rather than dB logic. It fixes the
weaknesses of "Artur Mix bit eq" and adds per-band dynamics modelled as **limiters,
not compressors**.

### Core philosophy
- All gain in bits: 1 bit = 6.0206 dB; gain via exact powers of two (`pow(2, bits)`),
  inheriting the RCBit anti-zipper smoothing (PurestGain) from `RCBitRangeGain` and
  Dima's `RCBitLimiter`/`RCBitBrickwall`.
- Static band gain is set in **bits** (with micro-step inside one bit).
- Dynamic ceiling is set in **bits below 0 dBFS** (as in RCBitBrickwall/RCBitLimiter).
- **No final/global limiter.** This is a pure dynamic EQ.
- Dynamics is conceived as a **per-band limiter**: a frequency must simply not exceed
  a ceiling. There is **no ratio**; depth = how much the band exceeds the ceiling.

### Weaknesses of "Artur Mix bit eq" being fixed
1. **Critical: filter state lives in `gmem`** (global memory shared across *all*
   instances of the JSFX). Two instances on different tracks clobber each other's
   coefficients and state → distortion. **Fix:** all filter state and buffers in
   instance-local memory.
2. No dynamics at all (static EQ + a global limiter).
3. Global output limiter (unwanted; not a dynamic EQ).
4. M/S is global (whole-plugin Mid/Side), not per band.
5. Fixed 5 bells only; no shelf/HP/LP; unintuitive Q (0–100); slider-only UI, no
   analyzer / node dragging.

---

## 2. Reference materials (on this machine)

| Plugin | Role as reference | License |
|---|---|---|
| `RCBitRangeGain.jsfx` | Bit-logic gain core (powers of 2, PurestGain smoothing) | GPL |
| `RCBitLimiter V2.0` | Soft limiter envelope logic (Dima's own) | GPL |
| `RCBitBrickwall V4.0` | Brickwall envelope + safety logic (Dima's own) | GPL |
| `Artur Mix bit eq.jsfx` | The static bit-EQ being superseded | — |
| `artur_linear_faze_eq_1_1.jsfx` | Linear-phase FIR method (impulse→FFT→magnitude→IFFT→Kaiser→OLA) | — |
| `mrelwood_EQall_BETA` | Per-band dynamics concept (per-node detector/comp) | — |
| `ReJJ/ReEQ/ReEQ.jsfx` v1.2.0 | Node GUI + Eco/HQ oversampling pattern | MIT |
| `spectrum.jsfx-inc` | FFT spectrum analyzer library | LGPL |
| `svf_filter.jsfx-inc` | State-variable filter (stable under fast modulation) | LGPL |
| `rbj_filter.jsfx-inc` | RBJ biquad coefficients | GPL |

**Licensing:** RCBit plugins are already GPL; mixing GPL/LGPL/MIT into a GPL plugin
is fine. The final plugin stays GPL with all upstream copyright headers preserved.
We **reuse** these libraries rather than rebuilding (analyzer + filters); only the
bit-logic, dynamics, bell-character math, and node interaction are written fresh.

---

## 3. Signal architecture

### 3.1 M/S engine
- At input, encode once: `M = (L+R)/2`, `S = (L−R)/2`. All bands process in the M/S
  domain; decode back to L/R at output.
- Per-band M/S target:
  - **Stereo** = identical filter applied to both M and S (= equal L/R EQ).
  - **Mid** = M only. **Side** = S only.
  - (L/R target is a possible future extension; it breaks the pure M/S domain.)
- Each band holds **separate filter state for M and for S**.

### 3.2 Bands (up to 8 nodes)
Each band has: type, frequency, Q, gain (bits), M/S target, bell character, and a
dynamics section (§4). Node count is dynamic (0–8), created/removed by double-click
on the analyzer.

**Filter types:** Bell, Low-Shelf, High-Shelf, High-Pass, Low-Pass.

**Bell character models** (proportional-Q / curve-shaping, in the spirit of DDMF
Equilibrium): a per-band selector affecting coefficient computation. Initial set:
- `Clean` — constant-Q RBJ peaking (digital reference).
- `GML-8200-style` — proportional Q (Q narrows with gain).
- `GML-9500 / Sontec-style` — alternative proportional-Q curve.
- `Butterworth` — maximally-flat-derived bell.
- 1–2 additional house characters.

The set is extensible; these are recognisable *characters*, not claimed exact analog
emulations. Implementation = different Q-vs-gain laws and skirt shaping in the
coefficient formulas.

### 3.3 Phase modes (per-plugin button)
- **Zero-Latency** (minimum phase): the main IIR/SVF engine. No latency.
- **Linear Phase**: the **static** EQ curve is baked into a linear-phase FIR kernel
  via the impulse→FFT→magnitude→IFFT→Kaiser-window→overlap-add method (per
  `artur_linear_faze_eq`). Kernel rebuilt only on static-param change. Adds PDC
  latency reported to REAPER.

**Linear phase + dynamics:** when Linear Phase is on, the **static** curve is
linear-phase (FIR), but the **per-band dynamic limiters stay minimum-phase**
(zero-latency bell-cut modulation) to avoid pre-ringing smearing transients. So the
FIR kernel contains only the static curve; the dynamic stage runs after it as a
min-phase modulation.

### 3.4 Quality (Eco / HQ button)
Oversampling of the minimum-phase engine (pattern from ReEQ):
- **Eco** = 1×, no latency.
- **HQ** = oversampled, more accurate near Nyquist (less biquad cramping; the
  "natural/analog" character), at the cost of latency.

---

## 4. Dynamic section (per-band limiter)

Dynamics = a **limiter, not a compressor**, Nova-style, implemented as a
**dynamic bell-cut**:

1. **Detector:** a bandpass (at the node's freq/Q) reads the band level **after** the
   static bell (so a boosted band's peaks are caught; a cut band has less to catch).
   Static gain and dynamic cut are **independent**.
2. **Ceiling (bits):** when the detector exceeds the ceiling, a dynamic cut is applied
   to the same bell, equal to the excess ("pull the frequency down"). No ratio.
3. Two buttons per band:
   - **Soft** — pulls toward the ceiling gently, using `RCBitLimiter` envelope logic
     (envelope + PurestGain smoothing; may slightly exceed).
   - **Brick** ("last policeman") — a separate stage **after** Soft: instant attack +
     shared lookahead, hard ceiling (maximum ratio). Both can be on: Soft shapes the
     band first, Brick guarantees the ceiling.
4. **Per-band controls (minimum set):** Ceiling (bits), Soft on/off, Brick on/off,
   Attack, Release. (Dyn on/off master per band.)

### CPU strategy
- Detectors are lightweight envelope followers (not per-band lookahead limiters).
- **One shared global lookahead delay line** serves all bands' Brick attack timing
  (as in Nova), instead of a buffer per band.
- Dynamic SVF (`svf_filter.jsfx-inc`) for bands under dynamic modulation: stable under
  fast coefficient changes, unlike direct-form biquad.

---

## 5. GUI (node + FFT analyzer)

- **FFT analyzer** via `spectrum.jsfx-inc` (LGPL) as a library — pre/post spectrum on
  the background. Its instance memory allocator also helps avoid `gmem`.
- **Nodes** dragged by mouse over frequency/gain; **double-click** on the curve adds a
  node, on a node removes it (up to 8). Interaction approach inspired by `ReEQ.jsfx`
  (MIT), not copied verbatim.
- **Selected-node panel** (bottom/side): type, bell character, Q, M/S, Dyn on/off,
  Ceiling, Soft/Brick, Attack/Release.
- **Visualisation:** static EQ curve + live dynamic curve (how much each node is
  currently cutting) overlaid on the spectrum — the per-band limiters are visible at
  work.
- **Top bar:** Phase mode (Zero-Latency / Linear Phase), Quality (Eco / HQ), global
  bypass, output trim (bits).
- Dark theme in the RCBit/Artur family; built with the `reaper-jsfx-ui` skill.

---

## 6. Module boundaries

| Unit | Responsibility | Depends on |
|---|---|---|
| Bit-gain core | bits↔linear, PurestGain smoothing | — |
| M/S codec | encode/decode, per-band domain routing | bit-gain |
| Static filter bank | biquad/SVF coeffs per type + bell character | bit-gain |
| Linear-phase engine | FIR kernel build + OLA convolution; PDC | static filter bank |
| Dynamics engine | per-band detector, Soft/Brick envelopes, dynamic cut | static filter bank, shared lookahead |
| Analyzer | FFT spectrum pre/post | spectrum.jsfx-inc |
| GUI | nodes, dragging, panels, curve draw | all of the above |

Each unit is independently reasoned about; the GUI is a thin layer over the engine.

---

## 7. Testing strategy

JSFX cannot use the Python FakeReaper harness. Plan:
- **Python DSP mirror + unit tests** for the numeric core: bit↔linear gain, biquad /
  bell-character coefficients, limiter envelope math, FIR kernel magnitude. Verifies
  correctness offline.
- **Live A/B in REAPER** against "Artur Mix bit eq", "artur_linear_faze_eq", and TDR
  Nova: tonal match (static), null tests where applicable, transient behaviour of
  Soft vs Brick, M/S targeting, no-pre-ring check in Linear Phase + dynamics.
- Multi-instance test (two instances on two tracks) to confirm the gmem bug is gone.

---

## 8. Phasing

1. **Engine, no GUI (sliders):** M/S codec, static bands (Bell + Shelf + HP/LP),
   bit-gain, instance-local memory (gmem fix). Zero-latency only.
2. **Dynamic section:** per-band detectors + Soft/Brick limiters, shared lookahead.
3. **Bell characters:** GML / Butterworth / house models.
4. **Phase + Quality modes:** Linear-Phase FIR engine; Eco/HQ oversampling.
5. **GUI:** FFT analyzer + draggable nodes + selected-node panel + live dynamic curve.

Each phase ends with offline numeric tests and a live REAPER check before the next.

---

## 9. Out of scope (YAGNI)
- Final/global limiter (explicitly unwanted).
- L/R per-band target (M/S domain only for v1).
- Spectrum-grab / match-EQ, presets browser, automation-noise tricks.
- Exact analog emulation claims for bell characters.
