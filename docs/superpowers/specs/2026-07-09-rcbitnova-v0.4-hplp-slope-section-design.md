# RCBitNova V0.4 — Minimum-phase HP/LP filter section design

Date: 2026-07-09
Author: Dima Gorelik + Claude (Opus 4.8)
Status: approved (brainstorm), pending spec review

---

## 1. Goal and scope

Add a dedicated **High-Pass / Low-Pass filter section** to RCBitNova with selectable
slope (12/24/36/48/96 dB/oct), a resonance Q, and per-filter Mid/Side placement. The
section is **minimum-phase** (cascaded 2nd-order SVF), zero-latency, in the same clean
SVF style as the rest of the plugin.

**In scope:** two independent filters (HP, LP), each with Slope, Freq, Q, and Placement;
a min-phase cascade of 2nd-order SVF sections; the "Q on the first section" resonance
convention; full Placement (Both/Mid/Side/Left/Right) per filter.

**Out of scope (deliberate, deferred to a later LINEAR-phase version):** the **Brickwall**
slope (a true near-vertical wall belongs to the linear-phase / FFT engine, where it has no
phase artifacts — a min-phase brickwall would need a high-order elliptic with severe
cutoff-region phase ringing, self-defeating); the linear-phase FFT engine itself (~64 ms
latency, a separate large subsystem); saturation. The existing per-band HP/LP band *types*
(single 2nd-order, 12 dB/oct) stay as-is — this section is additive, not a replacement.

## 2. Structure and signal position

- New file `JSFX/RCBitNova V0.4`, copied from `JSFX/RCBitNova V0.3`.
- A **dedicated HP/LP section**, separate from the 4 EQ bands. It runs **first** in the
  per-sample chain — after input gain / channel-mode encode, **before** the 4 EQ bands and
  the dynamics — i.e. it filters what the bands and dynamics see (standard input filtering).
- Two independent filters applied in series: **HP** then **LP**. Each is its own stage with
  its own Slope, Freq, Q, and Placement; each does its own local Placement transform and
  recombine, so e.g. HP can be Side-only while LP is Both.
- Off = bit-perfect passthrough for that filter (no state, no processing).

## 3. Slope — minimum-phase SVF cascade

- Slope options per filter: **Off / 12 / 24 / 36 / 48 / 96 dB/oct** = **0 / 1 / 2 / 3 / 4 / 8**
  cascaded 2nd-order SVF sections (`svf_make("hp"/"lp", ...)`), applied in series.
- Far-stopband asymptote = sections x 12 dB/oct (numerically pre-validated 2026-07-09,
  `hplp_cascade_proto.py`: measured 12.0 / 24.1 / 36.1 / 48.2 / 96.3 dB/oct).
- Each section holds its own 2nd-order SVF state (per channel / per placement domain).
- **No Brickwall** in this version (see section 1).

## 4. Q convention — "Q on the first section" (decided)

- The **first** cascade section uses the user **Q** slider; every **subsequent** section
  uses Butterworth `Q = 0.7071`. (Matches Arthur's linear-phase design and the plugin's
  existing single-section HP/LP behavior at 12 dB/oct.)
- **Accepted, documented behavior** of this convention (pre-validated; the manual must state
  it so users are not surprised):
  - At `Q = 0.7071` the cascade is N identical 0.707 sections, so the level **at fc** is
    **-3 dB x N**: 12 -> -3, 24 -> -6, 36 -> -9, 48 -> -12, 96 -> **-24 dB**. The labeled
    cutoff frequency is therefore the -3 dB point only at 12 dB/oct; at higher slopes the
    true -3 dB point sits above `fc`. This is the price of the resonance-capable convention
    (the flat "-3 dB at fc for every slope" behavior would require staggered-Butterworth Q,
    which has no user resonance — rejected per Dima).
  - The passband droops slightly toward cutoff at high slopes (~-2.1 dB at 2xfc for 96
    dB/oct).
  - `Q > 0.7071` on the first section adds a **resonant bump at fc** (e.g. Q = 2 -> ~+4 dB),
    the desired musical feature.
- At **12 dB/oct** (1 section) the filter is **identical** to the existing per-band HP/LP
  (user Q on a single 2nd-order SVF).
- Q range follows the existing HP/LP Q slider convention.

## 5. Placement (Mid/Side) — full per-filter Placement

- Each filter (HP, LP) has its own **Placement**: **Both / Mid / Side / Left / Right** —
  the SAME control and semantics as the existing per-band Placement (running-L/R domain
  with a local M/S transform + recombine for Mid/Side). A superset of Arthur's Both/Mid/
  Side, consistent with the rest of the plugin.
- Placement is independent per filter: HP-Side + LP-Both is valid (the classic "mono the
  lows" move = HP on Side only). Each filter encodes to its target domain, filters, and
  decodes back to L/R before the next stage.
- Placement interacts with the global Channel Mode exactly as the per-band Placement already
  does (reuse that mechanism; the plan pins the exact code path).

## 6. Bit-accuracy (unchanged)

An HP/LP filter has **no gain parameter** (unity passband), so the plugin's bit-accuracy
invariant (gains/ceilings = powers of two) does not apply to it — there is no gain to
quantize. The section is a pure 2nd-order SVF cascade in the existing clean style, adds no
`log`/`dB`/`pow(10)` to any gain path, and touches no gain or ceiling. Zero latency.

## 7. Verification

Method as in S-A / S-B / V0.3: Python DSP mirror first (TDD), then line-by-line JSFX
transcription, then live-verify with Dima. Numeric pre-validation done (`hplp_cascade_proto.py`).

Permanent tests (Python oracle), using the shipped `svf_response` for analytic magnitude:
1. **Slope correctness:** an N-section HP/LP cascade has a far-stopband slope of
   `N x 12 dB/oct` (measured deep in the stopband, one octave apart) for N in {1,2,3,4,8}.
2. **fc level per convention:** at `Q = 0.7071`, |H(fc)| = `-3 x N dB` for each slope
   (documents section 4's accepted behavior, catches a wrong Q wiring).
3. **Resonance:** `Q = 2` on the first section produces a peak of a few dB near fc for a
   multi-section HP; `Q = 0.7071` produces no bump.
4. **Off == identity:** a filter set to Off is a bit-exact passthrough (no state, no change).
5. **Placement:** Mid/Side/Left/Right each filter only the intended domain; e.g. an HP with
   Placement = Side leaves a mono (Side = 0) signal unchanged, and leaves the Mid content of
   a stereo signal unchanged; Left/Right filter only that channel.
6. **12 dB/oct == existing single-section HP/LP:** a 1-section cascade with user Q equals the
   current per-band HP/LP coefficient/response (continuity check).

Live checks (Dima): each slope audibly/visibly steeper on an analyzer; Q>0.707 shows the
resonant bump; HP-Side / LP-Both placement combos behave (mono-the-lows works); Off nulls;
no zipper on slope/freq automation; CPU acceptable at 96 dB/oct on both filters.

## 8. Out of scope for V0.4

Brickwall slope; the linear-phase / FFT engine (~64 ms latency) and any linear-phase mode;
saturation; changes to the existing per-band HP/LP band types; any change to frozen
`JSFX/RCBitNova V0.1`, `V0.2`, `V0.2 SA`, `V0.3` (tags `rcbitnova-v0.1..v0.3`). V0.4 is a new
file `JSFX/RCBitNova V0.4`, copied from V0.3. The linear-phase HP/LP (with Brickwall) is the
planned next version after this one.
