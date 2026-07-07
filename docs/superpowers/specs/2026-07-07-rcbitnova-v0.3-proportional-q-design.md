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

> `Q_eff = clamp( Q_knob * (1 + s * |gain_bits_eff|), Q_knob, Q_MAX )`

- `Q_knob` — the band's set Q (existing per-band Q slider, range 0.1–10).
- `gain_bits_eff` — the band's **static** gain exponent in bits. RCBitNova's static
  gain law is `gain_lin = 2^((Macro + Micro/100) * BitRatio)`, so the proportional-Q
  input is the **signed exponent** `gain_bits_eff = (Macro + Micro/100) * BitRatio` —
  NOT raw Macro/Micro alone (BitRatio must scale it, else Bit Ratio would change the
  gain but not the Q character, and BitRatio = 0 must give no narrowing). `|gain_bits_eff|`
  is its absolute value, so proportional narrowing applies symmetrically to boost and
  cut. At `gain_bits_eff = 0` (unity, no bell) the term vanishes → `Q_eff = Q_knob`.
- `s` — the new per-band **Q Character** control, range **0–1**, default **0**.
  `s = 0` → `Q_eff = Q_knob` for all gains → **exact constant-Q, bit-identical to
  V0.2**. `s > 0` → the more boost/cut, the higher `Q_eff` (narrower bell).
- `Q_MAX = 16.0` — the stability clamp (§5), pinned as a spec constant (not an
  implementer choice), unless numeric pre-validation proves a safer value.

**Implementation rule for the `s = 0` bit-identity (mandatory fast path):** compute
`q_eff = (s == 0 || ftype != Bell) ? Q_knob : clamp(Q_knob*(1+s*|gain_bits_eff|), Q_knob, Q_MAX)`.
When `s = 0` the code must pass the *unmodified* `Q_knob` through the existing
coefficient path with no new arithmetic (no `min(max())` round-trip on `Q_knob`), so
the coefficients are byte-identical to V0.2, not merely close.

**Why bit-native:** 1 bit ≈ 6.02 dB, and RCBitNova's gain is already expressed in
bits, so "Q rises per bit of gain" needs **no `log10` and no dB conversion** — the law
lives entirely in the linear/bit domain, preserving the bit-accuracy invariant. `s`
affects only the filter **shape** (`Q`), never a gain or a ceiling.

**Reference behavior (from §1 research):** Neve 88RS manual — "the Q also changes
automatically with gain (as gain is increased, so is the Q)"; SSL-G — "the more you
boost or cut, the narrower the Q becomes." The law reproduces both monotonically.

**Q is defined by behavior, not by matching a number.** Different plugins' "Q" knobs
use different conventions (verified live 2026-07-07: Sontec MES 432C vs DMG EQuilibrium
analog-shape models at identical nominal Q/Gain/Freq produce different curves; EQuilibrium's
internal Q readout for its models ran 1.14 up to ~46 for visually similar widths). So the
law is validated by **measured octave-bandwidth vs gain**, not by matching any unit's Q
number. Fitting `s`/the law shape to a specific measured unit is an optional later tuning
that does not change this architecture.

**A note on curve SHAPE vs Q (scope boundary).** The EQuilibrium comparison also showed a
*second* character axis beyond bandwidth: skirt slope / top flatness / filter order (a
Butterworth-flat-top or an API/Neve-skewed bell differs from a plain 2nd-order resonant
bell even at matched −3 dB width). That shape/order modeling needs higher-order filter
topologies — a separate, larger feature (possible V0.4), explicitly **out of scope** for
V0.3. V0.3 changes only the bell's Q (bandwidth) via the 2nd-order SVF; it does not reshape
the skirt or top.

## 3. Where it applies

- **Bell bands only.** For Shelf / High Pass / Low Pass, `s` is ignored (their Q is
  transition steepness / resonance, not a bell bandwidth; proportional-Q is undefined
  there and absent from the research units' shelf sections).
- **`Q_eff` drives ALL Bell paths of the band, from static gain only (decided).**
  For a Bell band, `q_eff` is computed once (in `setup_band` / shared band params) and
  used for: the static Bell coefficients, the Bell **detector** coefficients, the Mode A
  Bell **cut**, and the Mode B Bell **split**. This keeps the resting shape and the
  dynamic behavior consistent (a high-character narrow bell also detects/cuts/splits
  narrow). Rejected alternative: static-only `q_eff` with dynamics on raw `Q_knob` —
  that makes a bell look narrow at rest but detect/cut wide, which is musically wrong.
- **Driven by STATIC gain, not dynamic gain.** `q_eff` uses the band's **set**
  (`gain_bits_eff`) value only. The dynamic gain movement (Mode A/B envelopes) does NOT
  feed back into `q_eff` — Q character is a function of the knob setting, as in analog.
  So `q_eff` is recomputed on `@slider`, not per sample; the dynamic engines then run
  their existing per-sample math using the band's `q_eff` in place of raw `Q_knob`.
- Wherever V0.2 currently reads the raw band Q for a Bell band (e.g. `bp[b*3+1]` and the
  detector/cut/split coefficient setup), V0.3 substitutes `q_eff`. For non-Bell bands the
  stored band-Q value is unchanged (see §3 first bullet and §7 tests).

## 4. Bit-accuracy invariant (unchanged, paramount)

All gains and ceilings stay linear `2^(-bits)`. `s` and `Q_eff` touch only the bell's
`Q` (filter shape), never a gain path. No `log`, `log10`, `dB`, `pow(10, ...)`, or
`20*` conversion is introduced anywhere. `s = 0` reproduces V0.2 bit-for-bit — the
change is purely additive, like the S-A shelf sibling block.

## 5. Stability (guards the spec's "distortion instead of processing" class)

Large `|gain_bits_eff| * s` could drive `Q_eff` very high → an extremely narrow,
high-resonance bell → ringing / self-oscillation → the unstable-coefficient distortion
class (V0.2 spec section 8, cause 4). Guards:

- **Clamp `Q_eff` to `[Q_knob, Q_MAX]`**, with **`Q_MAX = 16.0`** pinned as a spec
  constant (the plan confirms it against the TPT-SVF stability envelope already used by
  the static engine during numeric pre-validation; a safer value may only replace it
  with evidence). `Q_eff` never drops below the set `Q_knob`.
- **`s` range 0–1** bounds the multiplier: at the gain ceiling (±16 macro bits) and
  `s = 1`, `Q_eff` would be `Q_knob * 17` before clamping — the clamp is what actually
  bounds it, so the clamp is mandatory, not cosmetic.
- No new memory, no per-sample state: `Q_eff` is a coefficient input, so there is no
  stale-state transient beyond the existing `@slider` recompute.

## 6. Controls and JSFX surface

- **One new per-band slider `s` — "B<n> Q Character"**, range `0–1`, default `0`,
  fine step. **Reserved indices (pinned, appended — never inserted mid-list so existing
  automation/TCP/preset parameter numbers do not shift): `slider19` = B1, `slider29` =
  B2, `slider39` = B3, `slider49` = B4** (the free per-band slots after the 11–18 /
  21–28 / 31–38 / 41–48 static banks). Four bands → four new sliders. Slider crowding is
  accepted until the future GUI phase (per Dima; the GUI removes slider-reachability pain).
- UI labels are neutral (**`Q Character`**, `0` reads as Constant, increasing reads as
  Proportional) — no `SSL`/`Neve`/`API`/`GML`/`Sontec` naming (V0.3 is a musical control,
  not a fit to any unit; brand-style presets belong to a later measured-matching phase).
- No other slider changes. The existing per-band Q slider keeps its meaning (`Q_knob`,
  the base width at rest); existing slider numbers 11–48 / 51–88 / 91–123 are NOT
  renumbered.

## 7. Verification

Method as in S-A / S-B: Python DSP mirror first (TDD), then line-by-line JSFX
transcription, then live-verify with Dima. Numeric pre-validation before the plan.

Permanent tests (Python oracle):
1. **`s = 0` == constant-Q bit-identity:** for representative Bell settings the V0.3
   coefficient tuple with `s = 0` **equals the V0.2 coefficient tuple exactly** (not
   approximately) — exercise the mandatory fast path. Covers several `Q_knob`, freq, and
   gain values.
2. **`gain_bits_eff` correctness (Bit Ratio edges):** (a) `BitRatio = 0` → `Q_eff ==
   Q_knob` for any Macro/Micro; (b) `Macro = 2, BitRatio = 0.5` gives the same `Q_eff`
   as `Macro = 1, BitRatio = 1`; (c) negative Macro/Micro narrows symmetrically via
   `|gain_bits_eff|`.
3. **Proportional narrowing (defined measurement):** with `s > 0`, the **−3 dB bandwidth
   in octaves** decreases monotonically as `|gain_bits_eff|` increases. Convention: use
   **boost** cases (e.g. +0.5, +1, +2 effective bits); measure the width at the level
   halfway (in dB) between unity and the peak; center frequencies away from band edges
   (1 kHz and 3 kHz at 48 kHz). (Cut symmetry is a separate assertion via test 2c.)
4. **Clamp holds:** worst case `Q_knob = 10, gain_bits_eff = 16, s = 1` → `Q_eff == 16.0`;
   a high-frequency Bell at `Q_eff = Q_MAX` produces no NaN/Inf and bounded output on
   sine, sweep, and impulse-like input.
5. **Non-bell untouched (two levels):** (a) static Shelf / HP / LP coefficient tuples are
   identical for `s = 0` and `s = 1`; (b) the stored band-Q the dynamics read (`bp[]`)
   for a Shelf band is unchanged by `s`, so Mode A shelf dynamics and Mode B shelf split
   are bit-identical when `s` changes.
6. **Slider-surface source guard:** existing V0.2 slider numbers 11–48 / 51–88 / 91–123
   are unchanged in the JSFX source; the only added sliders are 19/29/39/49; each new
   slider's default is exactly `0`.

Live checks (Dima):
- Bell boost/cut at low vs high static gain audibly/visibly widens/narrows as `s` rises;
  `s = 0` sounds like V0.2 (ideally a null/near-null static render against V0.2).
- **Automate `s` 0→1 while audio plays** — no zipper/click beyond normal coefficient
  recompute.
- **Automate Macro/Micro gain while `s` is high** — narrowing follows gain, no explosive
  resonance.
- **Toggle band type Bell → Shelf → Bell with `s` nonzero** — Shelf ignores `s`, Bell
  resumes expected behavior; no click.
- Optionally compare the octave-width against a reference analyzer if matching a specific
  unit is desired (tuning only, not a correctness gate).

## 8. Out of scope for V0.3

Brand presets; analog saturation / harmonics ("color"); **curve-shape / skirt-slope /
top-flatness / filter-order modeling** (the second character axis seen in DMG EQuilibrium's
model zoo — a higher-order-filter feature, candidate for a later V0.4); proportional
behavior on Shelf / HP / LP; dynamic-gain-driven Q; any change to frozen
`JSFX/RCBitNova V0.1`, `RCBitNova V0.2` (tag `rcbitnova-v0.2`), or `RCBitNova V0.2 SA`.
V0.3 is a new file `JSFX/RCBitNova V0.3`, copied from V0.2.
