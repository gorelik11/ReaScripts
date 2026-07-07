# RCBitNova V0.3 — Proportional-Q (per-band) design

Date: 2026-07-07
Author: Dima Gorelik + Claude (Opus 4.8)
Status: approved (brainstorm), pending spec review

---

## 1. Goal and scope

Add **Proportional-Q** to RCBitNova's bell bands: the bell narrows as the band's
static boost/cut grows, giving the "musical" console/API character alongside the
existing surgical constant-Q. One new per-band control drives it; at its zero
position V0.3 is **bit-identical to V0.2**.

**In scope:** a per-band `s` ("Q Character") parameter on **Bell** bands; a bit-native
law `Q_eff = Q * (1 + s * |bits|)`; a stability clamp on `Q_eff`.

**Out of scope (deliberate):** brand presets (GML/SSL/Neve — sonically they collapse
to Constant vs Proportional + Q range, which the plugin already dials; see the
research note below); analog saturation / harmonics (the real "color" of hardware, a
separate future feature, never Q); proportional behavior on Shelf / HP / LP (their
"Q" is transition resonance, not bell bandwidth — the concept does not apply).

**Research basis:** `~/Knowledge/_plans/eq-q-factor-research.md` (2026-07-07). The
genuinely distinct, implementable axis across GML 8200/9500, Sontec 432, Neve 88RS,
SSL 4000 E/G is **Constant Q vs Proportional Q**. "Switched/stepped Q" (Sontec
5/6/9/11/15, Neve outer 0.7/2.0) is constant-Q at discrete values, not a new
mechanic. Numeric check (2026-07-07): at a fixed Q setting every unit gives the same
octave-width; only the Q-**mode** and Q-**range** differ. Constant vs Proportional is
the one audible, real difference.

## 2. The law (bit-native, no dB / no log)

For a **Bell** band, before computing the bell filter coefficients:

> `Q_eff = clamp( Q_knob * (1 + s * |bits|), Q_knob, Q_MAX )`

- `Q_knob` — the band's set Q (existing per-band Q slider, range 0.1–10).
- `bits` — the band's **static** bit-gain magnitude, i.e. the same signed value that
  sets the bell's boost/cut (Macro + Micro/100, scaled by Bit Ratio). `|bits|` is its
  absolute value, so proportional narrowing applies symmetrically to boost and cut. At
  0 bits (unity, no bell) the term vanishes → `Q_eff = Q_knob`.
- `s` — the new per-band **Q Character** control, range **0–1**, default **0**.
  `s = 0` → `Q_eff = Q_knob` for all gains → **exact constant-Q, bit-identical to
  V0.2**. `s > 0` → the more boost/cut, the higher `Q_eff` (narrower bell).
- `Q_MAX` — a tested-stable upper clamp (see §5).

**Why bit-native:** 1 bit ≈ 6.02 dB, and RCBitNova's gain is already expressed in
bits, so "Q rises per bit of gain" needs **no `log10` and no dB conversion** — the law
lives entirely in the linear/bit domain, preserving the bit-accuracy invariant. `s`
affects only the filter **shape** (`Q`), never a gain or a ceiling.

**Reference behavior (from §1 research):** Neve 88RS manual — "the Q also changes
automatically with gain (as gain is increased, so is the Q)"; SSL-G — "the more you
boost or cut, the narrower the Q becomes." The law reproduces both monotonically.

**Q is defined by behavior, not by matching a number.** Different plugins' "Q" knobs
use different conventions (verified live: Sontec vs ReEQ at identical nominal Q/Gain/
Freq produce different curves). So the law is validated by **measured octave-bandwidth
vs gain**, not by matching any unit's Q number. Fitting `s`/the law shape to a specific
measured unit is an optional later tuning that does not change this architecture.

## 3. Where it applies

- **Bell bands only.** For Shelf / High Pass / Low Pass, `s` is ignored (their Q is
  transition steepness / resonance, not a bell bandwidth; proportional-Q is undefined
  there and absent from the research units' shelf sections).
- **Static gain, not dynamic.** `Q_eff` responds to the band's **set** (static) bit-gain
  — the resting bell shape. The dynamic engines (Mode A cut, Mode B split limiter)
  operate on top of that shape exactly as in V0.2; they do not feed `bits` here. This
  matches analog behavior (Q character is a function of the knob setting).
- Computed at control rate (in `setup_band`, on `@slider`), not per sample.

## 4. Bit-accuracy invariant (unchanged, paramount)

All gains and ceilings stay linear `2^(-bits)`. `s` and `Q_eff` touch only the bell's
`Q` (filter shape), never a gain path. No `log`, `log10`, `dB`, `pow(10, ...)`, or
`20*` conversion is introduced anywhere. `s = 0` reproduces V0.2 bit-for-bit — the
change is purely additive, like the S-A shelf sibling block.

## 5. Stability (guards the spec's "distortion instead of processing" class)

Large `|bits| * s` could drive `Q_eff` very high → an extremely narrow, high-resonance
bell → ringing / self-oscillation → the unstable-coefficient distortion class
(V0.2 spec section 8, cause 4). Guards:

- **Clamp `Q_eff` to `[Q_knob, Q_MAX]`**, `Q_MAX` a tested-stable maximum (candidate
  16; the plan pins it against the TPT-SVF stability envelope already used by the
  static engine). `Q_eff` never drops below the set `Q_knob`.
- **`s` range 0–1** bounds the multiplier: at the gain ceiling (±16 macro bits) and
  `s = 1`, `Q_eff` would be `Q_knob * 17` before clamping — the clamp is what actually
  bounds it, so the clamp is mandatory, not cosmetic.
- No new memory, no per-sample state: `Q_eff` is a coefficient input, so there is no
  stale-state transient beyond the existing `@slider` recompute.

## 6. Controls and JSFX surface

- **One new per-band slider `s` — "B<n> Q Character"**, range `0–1`, default `0`,
  fine step. Allocated in a free per-band slider slot (exact index in the plan). Four
  bands → four new sliders. Slider crowding is accepted until the future GUI phase
  (per Dima; the GUI removes slider-reachability pain).
- No other slider changes. The existing per-band Q slider keeps its meaning (`Q_knob`,
  the base width at rest).

## 7. Verification

Method as in S-A / S-B: Python DSP mirror first (TDD), then line-by-line JSFX
transcription, then live-verify with Dima. Numeric pre-validation before the plan.

Permanent tests (Python oracle):
1. **`s = 0` == constant-Q identity:** for any Bell band and any gain, `Q_eff == Q_knob`
   and the bell response is **bit-identical** to the V0.2 bell (the additive-safety
   guarantee).
2. **Proportional narrowing:** with `s > 0`, the measured **−3 dB bandwidth in octaves**
   decreases monotonically as `|bits|` increases (constant vs proportional is
   measurable and large — e.g. at a fixed band, +3 dB wide vs +12 dB narrow).
3. **Zero-gain no-op:** at `|bits| = 0`, `Q_eff == Q_knob` regardless of `s`.
4. **Clamp holds:** at extreme `|bits| * s`, `Q_eff == Q_MAX` and the bell stays stable
   (no NaN/Inf, bounded output on a swept input).
5. **Non-bell untouched:** Shelf / HP / LP responses are independent of `s`.

Live checks (Dima): bell boost/cut at low vs high gain audibly/visibly widens/narrows
with `s` up; `s = 0` sounds like V0.2; no ringing/instability at extreme settings;
compare the octave-width against a reference analyzer if matching a specific unit is
desired.

## 8. Out of scope for V0.3

Brand presets; analog saturation / harmonics ("color"); proportional behavior on
Shelf / HP / LP; dynamic-gain-driven Q; any change to frozen `JSFX/RCBitNova V0.1`,
`RCBitNova V0.2` (tag `rcbitnova-v0.2`), or `RCBitNova V0.2 SA`. V0.3 is a new file
`JSFX/RCBitNova V0.3`, copied from V0.2.
