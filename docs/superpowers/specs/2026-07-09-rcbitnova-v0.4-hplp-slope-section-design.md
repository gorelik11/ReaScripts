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
- Off = bit-perfect passthrough for that filter (no state, no processing) — see §3 state rule.

**Exact per-sample signal order (pinned):**
`Master bypass -> passthrough (bit-perfect, nothing touched). Otherwise: input gain +
channel-mode encode -> anti-denormal -> DEDICATED HP/LP SECTION (HP then LP) -> 4 EQ bands +
Mode A -> Mode B delayed-bus / global pass -> output trim -> out.` The HP/LP output is what
gets written into the Mode B delayed bus (Mode B limits the already-filtered signal). Because
the HP/LP cascade is **zero-latency**, it does NOT change `pdc_delay` (PDC stays exactly as in
V0.3); master bypass short-circuits BEFORE any HP/LP processing or bus writes.

**Controls (JSFX slider surface).** Eight new sliders in a fresh bank beyond V0.3's Hard
controls (V0.3 uses 1-4, 11-49, 51-88, 91-123): reserve **`slider131`=HP Slope, `132`=HP Freq,
`133`=HP Q, `134`=HP Placement, `135`=LP Slope, `136`=LP Freq, `137`=LP Q, `138`=LP Placement**
(exact numbers pinned so existing sliders never renumber; the plan confirms them free). No
separate Enable — `Slope = Off` is the enable. Slope defaults **Off**; Freq defaults sensible
(HP low, LP high); Q default `0.7071`; Placement default `Both`.

## 3. Slope — minimum-phase SVF cascade

- Slope options per filter: **Off / 12 / 24 / 36 / 48 / 96 dB/oct**, applied as cascaded
  2nd-order SVF sections in series.
- **Enum-to-section mapping (pinned — the trap: the enum is NOT the section count).** The UI
  enum slider returns `0..5` (`{Off,12,24,36,48,96}`). Convert to section count with
  `nsec = (enum == 5) ? 8 : enum` -> `Off=0, 12=1, 24=2, 36=3, 48=4, 96=8`. A naive
  "sections = slider value" makes 96 dB/oct become 5 sections (60 dB/oct) — WRONG. Test every
  option's actual section count/slope.
- Far-stopband asymptote = `nsec x 12 dB/oct` (numerically pre-validated 2026-07-09,
  `hplp_cascade_proto.py`: measured 12.0 / 24.1 / 36.1 / 48.2 / 96.3 dB/oct).
- **State / memory (plan pins exact offsets).** New block `hplp_state` **appended after the
  last V0.3 memory block** (no overlap with existing Mode B / band buffers — the plan proves
  non-overlap by a source-level range check). Worst-case size = 2 filters x 8 sections x 2
  channels x 2 SVF integrators = **64 slots**. Slot addressing keyed by
  `(filter, section, channel, ic1/ic2)`. Coefficients are precomputed in `@slider` (per
  section: `a1,a2,a3,k,m0,m1,m2`), never per sample.
- **Off / state-reset policy (accepted warm-up, matches V0.2 §5).** An `Off` filter runs NO
  cascade processing and advances NO state (its `@sample` branch is skipped). To avoid a
  stale-integrator burst, that filter's cascade state is **zeroed on any change of its Slope,
  Freq, Q, or Placement** (an `@slider`-time reset when the setting changes), so Off->On and
  slope/placement switches start from clean state. This is a control-rate reset, not a
  per-sample reset; a brief warm-up on a live change is accepted.
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
- Q range follows the existing HP/LP Q slider convention. **Worst-case stability (the
  "distortion instead of processing" class):** at high Q (up to the slider max, e.g. 10) the
  resonant first section plus up to 7 more sections can build a large narrow peak near cutoff.
  The design KEEPS the existing Q range but REQUIRES stability tests at `Q = 10`, all slopes,
  several cutoff frequencies, on impulse / sine / sweep — no NaN/Inf, bounded output (the
  TPT-SVF is unconditionally stable for `k > 0`, so this is a guard, not an expected failure).
- **Header/manual text (JSFX header, pure ASCII), because sliders carry no help text:**
  `For slopes above 12 dB/oct, Freq is the cascade cutoff parameter, not the final -3 dB
  point; at Q = 0.7071 the level at Freq is -3 dB per active section.`

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

Permanent tests (Python oracle), using the shipped `svf_response` for analytic magnitude.
Every numeric claim from `hplp_cascade_proto.py` is promoted to a permanent test:
1. **Enum -> section mapping:** the mapping helper yields `Off=0, 12=1, 24=2, 36=3, 48=4,
   96=8` for enum `0..5` (catches the "96 -> 5 sections" trap).
2. **Slope correctness:** an N-section HP/LP cascade has a far-stopband slope of
   `N x 12 dB/oct` (measured deep in the stopband, one octave apart) for N in {1,2,3,4,8}.
3. **fc level per convention:** at `Q = 0.7071`, |H(fc)| = `-3 x N dB` for each slope
   (documents section 4's accepted behavior, catches a wrong Q wiring).
4. **Passband droop:** the ~-2.1 dB droop at `2 x fc` for 96 dB/oct is captured (documents the
   convention, catches a shape regression).
5. **Resonance:** `Q = 2` on the first section produces a peak of a few dB near fc for a
   multi-section HP; `Q = 0.7071` produces no bump.
6. **Q = 10 worst-case stability:** HP and LP, every slope, several cutoff freqs, on impulse /
   sine / sweep -> all output finite and bounded (no NaN/Inf, no runaway).
7. **Off == identity + no state advance:** a filter set to Off returns its input bit-exactly
   even with nonzero prior state; Off does not advance state; Off -> On after silence produces
   no burst (state was zeroed on the transition per section 3).
8. **Placement (routing, both levels):** Mid/Side/Left/Right each filter only the intended
   domain — an HP with Placement = Side leaves a mono (Side = 0) signal unchanged and leaves
   the Mid content of a stereo signal unchanged; Left/Right filter only that channel. Tested at
   the routing level, not just the single-channel coefficient.
9. **12 dB/oct == existing single-section HP/LP (coefficient AND routing):** a 1-section
   cascade with user Q equals the existing per-band HP/LP in both the single-channel
   coefficient/response AND the placement writeback for Both/Mid/Side/Left/Right.

Live checks (Dima):
- Each slope visibly steeper on an analyzer; the high-slope `Freq`-is-not-(-3 dB) shift is
  visible at 48/96; `Q>0.707` shows the resonant bump.
- HP-Side + LP-Both placement combos behave (mono-the-lows works); Off nulls (V0.4-with-both-
  filters-Off renders identical to V0.3).
- **Automation transitions** (the risky ones): Off->96, 96->Off, 12<->96, Both->Side->Mid,
  and a Q sweep at high slope near cutoff — no click/zipper beyond the accepted control-rate
  warm-up, no burst.
- **Mode B coexistence:** HP/LP active with Mode B active does not change `pdc_delay`, does not
  double-filter the delayed bus, and master bypass stays zero-latency / bit-perfect.
- **CPU:** measure and record the CPU delta vs V0.3 with the worst case (HP 96 Both + LP 96
  Both = 32 SVF ticks/sample + two M/S transforms); it must stay acceptable on the target
  session. Source self-review item: coefficients precomputed in `@slider`, no per-sample branch
  ladders in the 8-section inner loop.

## 8. Out of scope for V0.4

Brickwall slope; the linear-phase / FFT engine (~64 ms latency) and any linear-phase mode;
saturation; changes to the existing per-band HP/LP band types; any change to frozen
`JSFX/RCBitNova V0.1`, `V0.2`, `V0.2 SA`, `V0.3` (tags `rcbitnova-v0.1..v0.3`). V0.4 is a new
file `JSFX/RCBitNova V0.4`, copied from V0.3. The linear-phase HP/LP (with Brickwall) is the
planned next version after this one.
