# RCBitNova — Bit-Accurate Mid-Side Dynamic EQ — Design Spec

**Date:** 2026-06-29
**Status:** Design approved, pending spec review
**Author:** Dima Gorelik (design with Claude)
**Type:** JSFX plugin (REAPER), GPL

---

## 1. Purpose

A mid-side **dynamic** parametric EQ in the spirit of TDR Nova / FabFilter Pro-Q,
with **bit-denominated controls and bit-accurate gain staging** (RCBit) rather than
dB logic. It fixes the weaknesses of "Artur Mix bit eq" and adds per-band dynamics
modelled as **limiters, not compressors**.

### What "bit logic" means here (scope of the claim)
"Bit logic" is about the **control grid and gain stages**, not the filter arithmetic:
- All user-facing **gains, ceilings, thresholds** live on the bit grid (units of
  `2^n`), with the RCBit macro/micro/bit-ratio workflow.
- Any **pure gain stage** (input/output trim, the band-split limiter's ceiling clamp)
  is applied as an exact power of two — a mantissa-preserving exponent change, the
  "bit shift" purity from `RCBitRangeGain`. (Only integer Macro shifts are exactly
  lossless; Micro shifts are `2^fraction` and, like all fine trims, are not.)
- **Filtering itself is ordinary float DSP.** Frequency selectivity requires summing
  delayed samples with non-power-of-two coefficients, so no EQ topology (IIR, SVF,
  FIR, or analog) can make the band's *coloration* a bit shift. This is true of every
  EQ, including "Artur Mix bit eq"; it is not a limitation introduced by FIR mode.
  The bit-accuracy lives in the gains/decisions, not in the filter coloration.

### Core philosophy
- 1 bit = 6.0206 dB; bit gain via exact powers of two (`pow(2, bits)`), with RCBit
  anti-zipper smoothing (PurestGain) inherited from `RCBitRangeGain` and Dima's
  `RCBitLimiter`/`RCBitBrickwall`.
- Static band gain uses the **full RCBitRangeGain model, per band**: Macro Shift
  (integer bit jumps — exact powers of two, "musical"), Micro Shift (% of a bit —
  fine-tuning), and **Bit Ratio per band** (a dimensionless multiplier on the bit
  count, e.g. 0.25/0.2/0.3). Workflow: set a clear macro, then fine-tune with micro.
  - `gain_lin = 2 ^ ((Macro + Micro/100) * BitRatio)`
  - `display_dB = (Macro + Micro/100) * BitRatio * 6.0206`
- Dynamic ceiling is set in **bits below 0 dBFS** as a power of two: `ceiling_lin =
  2 ^ (-(CeilMacro + CeilMicro/100))` (as in RCBitBrickwall/RCBitLimiter). The exact
  detector definition this ceiling is compared against is specified in §4.1.
- **No final/global limiter.** This is a pure dynamic EQ.
- Dynamics is conceived as a **per-band limiter**: a frequency should not exceed a
  ceiling. There is **no ratio**; depth = how much the band exceeds the ceiling.

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

## 2. Reference materials (exact paths)

Paths are verified against this machine. `$REPO` = `~/projects/reascripts`;
`$FX` = `~/Library/Application Support/REAPER/Effects`. Items needed at runtime
(includes) must be **vendored into `$REPO/JSFX/`** before implementation; the rest
are read-only references.

| File | Verified path | Role | License | Action |
|---|---|---|---|---|
| RCBitRangeGain | `$FX/RCJacH Scripts/JSFX/Audio/RCBitRangeGain.jsfx` | Bit-gain core (powers of 2, PurestGain) | GPL | reference |
| RCBitLimiter V1.0 | `$REPO/JSFX/RCBitLimiter V1.0` | Soft limiter envelope (Dima's own) | GPL | reference |
| RCBitBrickwall V4.0 | `$REPO/JSFX/RCBitBrickwall V4.0` | Brickwall envelope + bit-exact clamp (Dima's own) | GPL | reference |
| RCBitLimiter V2.0 | `$FX/RCBitLimiter V2.0` | HQ/Light soft limiter (newer than repo V1.0) | GPL | reference |
| Artur Mix bit eq | `$FX/Artur Mix bit eq.jsfx` | Static bit-EQ being superseded | — (assume GPL-incompatible until confirmed) | reference only — do not copy |
| Artur Linear Faze | `$FX/artur_linear_faze_eq_1_1.jsfx` | Linear-phase FIR method (impulse→FFT→mag→IFFT→Kaiser→OLA) | — | reference only — do not copy |
| EQall BETA | `$FX/mrelwood_EQall_BETA` | Per-band dynamics concept | unknown | reference only — do not copy |
| ReEQ v1.2.0 | `$FX/ReJJ/ReEQ/ReEQ.jsfx` | Node GUI + Eco/HQ oversampling pattern | MIT | reference (may adapt) |
| spectrum.jsfx-inc | `$FX/ReJJ-1.0.11/spectrum.jsfx-inc` | FFT spectrum analyzer library | LGPL | **vendor** |
| svf_filter.jsfx-inc | `$FX/ReJJ-1.0.11/svf_filter.jsfx-inc` | State-variable filter | LGPL | **vendor** |
| rbj_filter.jsfx-inc | `$FX/ReJJ-1.0.11/rbj_filter.jsfx-inc` | RBJ biquad coefficients | GPL | **vendor** (optional — our coeffs are written fresh) |

**Licensing:** RCBit plugins are already GPL; mixing GPL/LGPL/MIT into a GPL plugin
is fine. The final plugin is GPL with all upstream copyright headers preserved.
We **reuse** the LGPL/GPL includes (analyzer + SVF) rather than rebuilding; only the
bit-logic, dynamics, bell-character math, and node interaction are written fresh.
Artur's and mrelwood's files are **conceptual references only** — their methods are
re-implemented from scratch, not copied, since their licenses are unconfirmed.

---

## 3. Signal architecture

### 3.1 Stereo placement engine (running L/R, per-band domain)
The running signal stays **L/R**; each band locally derives the domain it needs
(`M=(L+R)/2`, `S=(L−R)/2`; recombine `L=M+S`, `R=M−S`). This is more general than a
global M/S encode and delivers the full FabFilter-like placement set.

- **Per-band Placement** (governs static *and* dynamic routing):
  `Both | Mid | Side | Left | Right`.
  - For a *static* (linear) filter, `Both` applied identically to L&R = identically to
    M&S, so the linked/dual distinction does **not** exist statically — it only matters
    for the dynamic envelope (§4.1). `Mid/Side` work in M/S, `Left/Right` in L/R.
- **Per-band Dyn Stereo Mode** (only meaningful when Placement=`Both` and dynamics on):
  `Linked | Dual L/R | Dual M/S`.
  - `Linked` — one envelope from `max(chA, chB)` applied to both channels; preserves
    image (default).
  - `Dual L/R` — L and R limited by independent envelopes (classic dual-mono).
  - `Dual M/S` — M and S limited independently (a band spiking in Side is limited in
    Side only — de-toxifies phase — without touching Mid).
- Each band's working domain per sample:
  - `Mid`/`Side` → M/S (single channel). `Left`/`Right` → L/R (single channel).
  - `Both` + (`Linked`|`Dual L/R`) → L/R (both). `Both` + `Dual M/S` → M/S (both).
- Each band holds filter/detector/cut state for **two working channels** (slot A/B),
  reinterpreted per the band's domain; single-target placements use slot A only.

### 3.2 Bands (up to 8 nodes)
Each band has: type, frequency, Q, gain (Macro Shift + Micro Shift + Bit Ratio,
per §1), placement (§3.1: Both/Mid/Side/Left/Right + Dyn Stereo Mode), bell character,
and a dynamics section (§4). Node count is dynamic (0–8), created/removed by
double-click on the analyzer.

Dragging a node vertically on the analyzer adjusts the **Macro** bit grid (snaps to
clear bit jumps); Micro Shift is the fine readout/handle for sub-bit tuning.

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
  via the impulse→FFT→magnitude→IFFT→Kaiser-window→overlap-add method (re-implemented
  from `artur_linear_faze_eq`'s approach). Kernel rebuilt only on static-param change.
  Adds PDC latency reported to REAPER.

**Honest labelling — this is a *hybrid* mode, not "linear-phase dynamic EQ":** when
Linear Phase is on AND any band has dynamics active, the **static** curve is
linear-phase (FIR) but the **dynamic processing stays minimum-phase** (zero-latency),
to avoid pre-ringing smearing transients. The UI label reflects this:
- No active dynamics → **"Linear Phase"**.
- Linear Phase + active dynamics → **"Linear (Static) · Min-Phase Dynamic"**.

The FIR kernel contains only the static curve; the dynamic stage runs after it as a
min-phase modulation. Acceptance tests assert this explicitly (§7): impulse symmetry
and flat group delay for the static-only case; the documented asymmetry once dynamics
engage. We never claim a fully linear-phase result while dynamics are active.

### 3.4 Quality, cramping & aliasing
Two distinct problems, two distinct fixes — they are often conflated.

**Cramping (an LTI filter problem).** Standard RBJ biquads warp near Nyquist (bilinear
transform compresses the frequency axis), so high bells/shelves lose shape at the top
octave — this is exactly what bit-step the friend's hand-built bit EQ to ring/cramp.
Fixes, in order of preference:
- **Low-cramping filter topology (always-on, default, no latency):** all filter types
  use the **TPT state-variable filter (Andy Simper / Cytomic)** — the same family as
  the vendored `svf_filter.jsfx-inc`. It gives **exact gain at center/cutoff** (kills
  the most audible cramping symptom), stays stable under fast modulation (so one
  topology serves both static filters and Mode-A dynamics), and has well-known exact
  coefficients. This is the primary, free fix at any sample rate.
  - *Future refinement (out of scope v1):* full Vicanek "matched second-order IIR"
    magnitude-matching for the top octave, if listening warrants it.
- **Native high sample rate:** Dima usually runs **96 kHz**, where Nyquist = 48 kHz and
  cramping is already mild — the common case is well covered.
- **Oversampling (HQ):** as a further backstop for 44.1/48k sessions.

Cramping is purely about coefficients; the LTI EQ does **not** alias on its own.

**Aliasing (a nonlinear problem).** Aliasing comes from the **dynamic** processing —
time-varying gain, and especially the Mode-B clamp/limiter — which is nonlinear and
generates harmonics that can fold back. Static EQ is LTI and does not alias. Fixes:
- **Oversampled peak detection** in the limiter envelopes (inherited from
  `RCBitLimiter`/`RCBitBrickwall`).
- **Oversampling the dynamic stage** in HQ.

**Quality (Eco / HQ button)** — controls the oversampling factor (pattern from ReEQ):
- **Eco** = 1×, no latency. Fine at 96 kHz with matched coefficients.
- **HQ** = oversampled (more headroom against cramping at low SR *and* against
  dynamic-stage aliasing), at the cost of latency.

---

## 4. Dynamic section (per-band limiter)

Dynamics is a **limiter, not a compressor** (no ratio; depth = excess over ceiling).
Each dynamics-enabled band picks one of **two modes** (per-band switch). Dynamics is
available on **Bell and Shelf** types; **HP/LP are static-only** in v1.

### 4.1 Detector (shared by both modes) — formal definition
The threshold must be operational, so the detector is defined exactly:
- **Detection filter:** a dedicated **bandpass** at the band's `freq`/`Q` (for shelf
  types, the corresponding shelf-region detector), independent from the audio-path
  filter, fed the signal **after the band's static EQ** in the band's M/S domain.
- **Measure:** **peak** of the rectified detector output, smoothed by the band's
  Attack/Release envelope. (RMS is a possible future option; v1 = peak.)
- **Normalisation:** the detector's passband gain is normalised to unity at `freq`
  so the comparison is "band energy vs ceiling", independent of `Q` and filter shape.
- **Comparison:** the envelope is compared to `ceiling_lin = 2^(-(CeilMacro +
  CeilMicro/100))`. Excess (in bits) = `log2(env / ceiling_lin)` when `env > ceiling`.
- **Placement & stereo linking (per §3.1):**
  - *Mid/Side/Left/Right* placement → detector and gain act in that single channel.
  - *Both* placement uses the Dyn Stereo Mode:
    - `Linked` → detector = `max(chA, chB)`, one gain to both → **width does not pump**.
    - `Dual L/R` → independent envelopes on L and R (classic dual-mono).
    - `Dual M/S` → independent envelopes on M and S (limit a Side-spiking band in Side
      only, leaving Mid untouched).

### 4.2 Mode A — Dynamic EQ (bell/shelf-cut, Nova-style)
Phase-clean, smooth, **no absolute ceiling guarantee**.
- When the detector exceeds the ceiling, a **dynamic cut** is applied to the same
  bell/shelf, equal to the excess ("pull the frequency down"). Static gain and dynamic
  cut are independent.
- Two attack/character sub-options:
  - **Soft** — gentle approach using `RCBitLimiter`-style envelope (+ PurestGain
    smoothing). Musical, may momentarily exceed.
  - **Hard/Fast** (renamed from "Brick" to avoid a false guarantee) — instant attack,
    maximum cut depth, runs as a stage after Soft. Strongly pins the band toward the
    ceiling but, because it is a bell/shelf-gain modulation, it **cannot guarantee** an
    absolute ceiling on the bandpass detector or on the reconstructed L/R output
    (overlapping bands, phase, M/S decode, neighbouring frequencies can re-introduce
    overshoot). The UI says "Hard", never "guaranteed".
- Gain reduction here is **smooth float** (phase-clean is the point). Users who find
  frequent float gain-riding "synthetic/lifeless" should use Mode B.

### 4.3 Mode B — Band-Split RCBit Limiter (bit-accurate)
True per-band limiting in **bit logic**, for the "alive" RCBit sound.
- The band is **split out** (bandpass at `freq`/`Q`), limited as its own signal by the
  real RCBit envelopes, then **summed back** into the M/S bus:
  - **Soft** = `RCBitLimiter` logic (PurestGain-smoothed, may slightly exceed).
  - **Brick** = `RCBitBrickwall` logic: instant attack + lookahead + **bit-exact
    safety clamp** to `ceiling_lin` (a power of two). This is the bit-accurate
    "last policeman".
- **Guarantee scope (honest):** the clamp guarantees the **split band's own
  contribution** stays at/under ceiling — NOT the summed L/R output (other bands and
  M/S decode add on top; only a removed broadband brickwall could bound the master).
- **CPU:** heavier than Mode A — each Mode-B band adds split filters + a limiter with
  a lookahead buffer (and oversampling if HQ). Cost scales with the number of Mode-B
  bands and is **opt-in per band**. A few Mode-B bands among mostly Mode-A/static
  bands is fine; all 8 in Mode-B + HQ is the heavy extreme.

### 4.4 Per-band controls
Dyn on/off, **Mode (A: Dynamic EQ / B: Band-Split)**, **Soft on/off**, **Hard on/off**
(independent — both can be on = cascade), **Soft Ceiling** (Macro+Micro), **Hard Ceiling**
(Macro+Micro), Attack, Release, Dyn Stereo Mode (§4.1), global Lookahead (§4.5).

### 4.6b Soft + Hard cascade ("last policeman")
Soft and Hard are **independent stages with their own ceilings** (Hard Ceiling is
typically *higher* — louder, fewer bits below 0 — so Hard only catches what Soft let
through). Behaviour per mode:
- **Mode B (band-split):** `limited = clamp( band_delayed · gSoft , ceiling_hard )`,
  where `gSoft` is the PurestGain-smoothed envelope toward `ceiling_soft` (=1 if Soft off),
  and the clamp is applied only if Hard on. So: Soft-only = smoothed ride to soft ceiling
  (may exceed); Hard-only = bit-exact brick at hard ceiling; both = Soft rides musically,
  Hard bit-exact clamps the remainder at the higher ceiling.
- **Mode A (bell-cut):** bell gain = `gSoft(→ceiling_soft, smooth) · gHard(→ceiling_hard,
  instant attack)`. No clamp (gain modulation); Hard is a fast instant-attack cut at the
  higher ceiling stacked on Soft's smooth cut.
Implementation note: the current build ships an *exclusive* Dyn Char {Soft|Hard} switch
as a stepping stone; the cascade phase replaces it with the two independent toggles +
two ceilings above.

### 4.5 Lookahead data model (corrected)
A single shared delay does NOT by itself solve control timing for 8 independent
dynamic filters. The correct model:
- **One shared audio delay line** of `L` samples on the main M/S bus; `pdc_delay = L`
  (plus FIR latency when Linear Phase is active) reported to REAPER.
- **Per-band detector state** (envelope, and for Mode B a per-band gain/peak history
  + ring buffer) is computed on the **un-delayed** signal, so each detector "sees the
  future" by `L` samples relative to the delayed audio it controls.
- Therefore each band keeps its **own** detector envelope and (Mode B) its own
  lookahead histories; the delay line is shared, the control state is per-band.

### 4.6 CPU strategy
- Mode-A detectors are lightweight envelope followers; Mode-A is the cheap default.
- Dynamic **SVF** (`svf_filter.jsfx-inc`) for Mode-A modulated bands: stable under
  fast coefficient changes, unlike direct-form biquad.
- Mode-B cost is opt-in and localised to bands that use it.

---

## 5. GUI (node + FFT analyzer)

- **FFT analyzer** via `spectrum.jsfx-inc` (LGPL) as a library — pre/post spectrum on
  the background. Its instance memory allocator also helps avoid `gmem`.
- **Nodes** dragged by mouse over frequency/gain; **double-click** on the curve adds a
  node, on a node removes it (up to 8). Interaction approach inspired by `ReEQ.jsfx`
  (MIT), not copied verbatim.
- **Selected-node panel** (bottom/side): type, bell character, Q, placement
  (Both/Mid/Side/Left/Right) + Dyn Stereo Mode (Linked/Dual L/R/Dual M/S), gain
  (Macro / Micro / Bit Ratio), Dyn on/off, **Dyn Mode (A: Dynamic EQ / B: Band-Split)**,
  Soft/Hard·Brick, Ceiling (Macro/Micro), Attack/Release.
- **Visualisation:** static EQ curve + live dynamic curve (how much each node is
  currently cutting) overlaid on the spectrum — the per-band limiters are visible at
  work.
- **Top bar:** Phase mode (Zero-Latency / Linear Phase, with the hybrid label of §3.3),
  Quality (Eco / HQ), global bypass, output trim (bits).
- Dark theme in the RCBit/Artur family; built with the `reaper-jsfx-ui` skill.

### 5.1 State, serialization & automation (JSFX)
Node state is not a UI afterthought in JSFX — it must survive save/recall, automation,
and undo. Model:
- **Every per-band parameter is backed by a real `slider`** (declared, possibly hidden
  from the default UI but present), so REAPER gives us **automation, preset recall, and
  undo for free**. With up to 8 bands this is a fixed, pre-declared slider bank
  (8 × {enable, type, freq, Q, macroGain, microGain, bitRatio, character, msTarget,
  dynOn, dynMode, soft, hard, ceilMacro, ceilMicro, attack, release}) plus globals.
- **`@serialize`** persists only **editor-only state** that should not be automatable:
  selected-node index, analyzer settings (FFT size, slope, pre/post), window size.
- **Param changes from the GUI write to the backing sliders** (via `slider_automate`)
  so dragging a node is automatable and undoable like any native control.
- Sample-rate changes and `@slider` recompute all coefficients and envelope
  coefficients from `srate` (no cached absolutes).

---

## 6. Module boundaries

| Unit | Responsibility | Depends on |
|---|---|---|
| Bit-gain core | bits↔linear, PurestGain smoothing | — |
| M/S codec | encode/decode, per-band domain routing | bit-gain |
| Static filter bank | TPT-SVF (Simper) coeffs per type + bell character | bit-gain |
| Linear-phase engine | FIR kernel build + OLA convolution; PDC | static filter bank |
| Detector | per-band normalised bandpass + envelope; M/S linking | static filter bank |
| Dynamics Mode A | bell/shelf-cut modulation (smooth float) | detector, SVF |
| Dynamics Mode B | band-split + RCBit Soft/Brick + bit-exact clamp; per-band lookahead | detector, bit-gain, shared delay |
| Analyzer | FFT spectrum pre/post | spectrum.jsfx-inc |
| State/serialize | slider-backed params + @serialize editor state | — |
| GUI | nodes, dragging, panels, curve draw | all of the above |

Each unit is independently reasoned about; the GUI is a thin layer over the engine.

---

## 7. Testing strategy

JSFX cannot use the Python FakeReaper harness. Plan:
- **Python DSP mirror + unit tests** (pure stdlib — no numpy/scipy on this machine;
  magnitude from the transfer function via `cmath`) for the numeric core:
  - bit↔linear gain (`gain_lin`/`display_dB` formulas, integer-macro exactness);
  - biquad / bell-character coefficients (magnitude at center/DC/Nyquist);
  - **cramping check**: shelf/high-bell magnitude error at the top octave vs target,
    with and without matched-biquad correction (§3.4);
  - detector normalisation (unity passband gain at `freq` across Q);
  - limiter envelope math; band-split sum reconstruction; FIR kernel magnitude.
- **Live A/B in REAPER** against the references: tonal match (static), null tests
  where applicable, Soft vs Hard vs Mode-B transient behaviour, M/S targeting and
  **Stereo-linked width stability** (no width pumping), bit-exact ceiling clamp on a
  Mode-B band.
- **Robustness checks (live + mirror where possible):** sample-rate change (44.1 →
  48 → 96k) recomputes coefficients correctly; **denormal/NaN** guards in feedback
  paths; automation smoothing has no zipper; `@serialize` round-trip restores all
  state; **PDC** value correct in Zero-Latency, Linear Phase, and Mode-B lookahead.
- **Phase acceptance tests (§3.3):** impulse symmetry + flat group delay for
  static-only Linear Phase; documented asymmetry once dynamics engage.
- **Aliasing check:** spectrum of a sine through an active Mode-B clamp at Eco vs HQ —
  HQ must show reduced aliasing images (§3.4).
- Multi-instance test (two instances on two tracks) to confirm the gmem bug is gone.

---

## 8. Phasing

1. **Engine, no GUI (slider-backed):** M/S codec, static bands (Bell + Shelf + HP/LP),
   bit-gain (Macro/Micro/BitRatio), matched-biquad cramping correction (§3.4),
   instance-local memory (gmem fix). Zero-latency only. Slider-backed param bank.
2a. **Placement engine:** refactor the static engine from global-M/S to running-L/R
   with per-band placement (Both/Mid/Side/Left/Right), local domain transforms (§3.1).
2b. **Dynamics Mode A (Soft):** per-band normalised detector + Soft bell-cut, with
   Dyn Stereo Mode (Linked / Dual L/R / Dual M/S); zero-latency. (Hard cascade,
   shared lookahead, shelf dynamics → Phase 2c.)
3. **Dynamics Mode B:** band-split + RCBit Soft/Brick + bit-exact clamp, per-band
   lookahead histories.
4. **Bell characters:** GML / Butterworth / house models.
5. **Phase + Quality modes:** Linear-Phase FIR engine (+ hybrid labelling); Eco/HQ
   oversampling of the dynamic stage for aliasing control.
6. **GUI:** FFT analyzer + draggable nodes + selected-node panel + live dynamic curve;
   `@serialize` editor state.

Each phase ends with offline numeric tests and a live REAPER check before the next.
This spec is approved for **Phase 1**; later phases get their own implementation plans.

---

## 9. Out of scope (YAGNI)
- Final/global limiter (explicitly unwanted) — and therefore no absolute ceiling
  guarantee on the summed master output (Mode B guarantees only the split band's
  own contribution, §4.3).
- RMS detector (v1 detector = peak, §4.1).
- Dynamics on HP/LP types (Bell + Shelf only in v1).
- Spectrum-grab / match-EQ, presets browser, automation-noise tricks.
- Exact analog emulation claims for bell characters.

---

## 10. Future: VST port (intent, not committed work)

If RCBitNova is later ported to a native plugin (VST3/AU), this is the blueprint so
the intent isn't lost. Porting is a transcription job, not a redesign.

**Canonical DSP reference = `tools/rcbitnova_dsp.py` + `tests/test_rcbitnova_dsp.py`.**
The math is already language-neutral and unit-verified (TPT-SVF, bit gain, M/S). Port
JSFX→C++ the same way we ported Python→JSFX: transcribe against the Python mirror and
keep the tests as the cross-language oracle. Target framework: **JUCE** or **iPlug2**.

**Portable vs JSFX-specific:**
- *Portable (carries straight over):* bit-logic gain (`2^bits`), TPT-SVF coefficients
  and recurrence, M/S codec, detector/limiter envelope math, FIR linear-phase kernel
  build, the whole Phase 2–5 DSP.
- *JSFX-specific (re-implement in the host framework):* the `gfx`/ReaImGui GUI, the
  slider-backed parameter model + `@serialize` (→ the framework's parameter/state API),
  PDC reporting (→ host latency API), instance memory layout (→ member fields).

**Licensing — decide before porting:**
- The JSFX vendors LGPL/GPL includes (`spectrum.jsfx-inc`, `svf_filter.jsfx-inc`) and
  is GPL. A **GPL/open** VST is unconstrained.
- A **closed/commercial** VST must re-implement those: the SVF is already written from
  scratch in the Python mirror (clean), and the FFT analyzer would need an independent
  implementation. Plan this re-implementation cost in if commercial.

**Where this lives:** code stays in git on the `rcbitnova` branch (and eventually
`main`); this intent stays here in the spec. No VST work is scheduled — this section
exists only so a future decision starts from a clear map.
