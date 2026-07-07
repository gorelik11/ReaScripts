# RCBitNova V0.3 Proportional-Q - Weakness Review

**Date:** 2026-07-07  
**Reviewed spec:** `2026-07-07-rcbitnova-v0.3-proportional-q-design.md`  
**Context:** worktree `~/projects/reascripts/.claude/worktrees/rcbitnova/`

This review lists weak points to tighten before writing the V0.3 implementation
plan. The design is clean and appropriately scoped: one per-band control, Bell only,
default-off behavior, no new memory, no per-sample modulation, and no over-claiming
about analog color. The remaining risks are mostly around exact semantics: which Q
is used by the dynamic engines, what "bits" means when Bit Ratio is involved, and
how to prove the `s = 0` identity claim.

## P1 - Dynamic Bell Engines Need A Q_eff Decision

The spec says proportional-Q applies to Bell bands before computing bell filter
coefficients, and that dynamic engines operate on top of that shape exactly as in
V0.2. In the current V0.2 code, however, static and dynamic Q are computed in
separate places:

- `setup_band()` computes the static bell coefficients from the band Q slider.
- `setup_band_dyn()` computes detector coefficients from the same raw Q slider.
- Mode A dynamic bell-cut recomputes cut coefficients from `bp[b*3+1]`, currently
  the raw band Q.
- Mode B bell split also uses the detector/split Q path.

So V0.3 must decide whether `Q_eff` replaces Q only in the static bell, or also in
the Bell detector/cut/split paths.

**Risk:** if static Bell uses `Q_eff` but dynamics still use raw `Q_knob`, a
high-character bell can look/sound narrow at rest while its dynamic detector and
dynamic cut remain wide. That may feel wrong musically and makes "dynamic engines
operate on top of that shape" ambiguous.

**Recommendation:** state the rule explicitly in the spec and plan:

- Preferred: for Bell bands, compute one `q_eff` in `setup_band()` / shared band
  params and use it for static Bell coefficients, Bell detector coefficients, Mode A
  Bell cut, and Mode B Bell split. `q_eff` is based only on static gain, not dynamic
  gain.
- Alternative: static-only proportional Q; dynamics intentionally use raw Q. If this
  is chosen, document the mismatch and add tests proving it is intentional.

## P1 - "bits" Must Be Named As The Effective Gain Exponent

The spec says `bits` is the static bit-gain magnitude, i.e. Macro + Micro/100 scaled
by Bit Ratio. This is correct, but the formula name is easy to misread during
implementation.

Current gain law:

`gain_lin = 2^((Macro + Micro/100) * BitRatio)`

Therefore the proportional-Q input should be the signed exponent:

`gain_bits_eff = (Macro + Micro/100) * BitRatio`

not raw Macro/Micro alone.

**Risks:**

- If raw Macro/Micro is used, Bit Ratio no longer affects Q character even though it
  affects actual gain.
- If Bit Ratio is `0`, the band has no static gain, but raw Macro could still drive
  Q narrowing unless the implementation uses `gain_bits_eff`.
- If tests only use Bit Ratio `1`, this bug will be invisible.

**Recommendation:** rename the formula variable in spec/plan to `gain_bits_eff`, and
add tests:

- Bit Ratio `0` -> `Q_eff == Q_knob` for any Macro/Micro.
- Macro `2`, Bit Ratio `0.5` gives same `Q_eff` as Macro `1`, Bit Ratio `1`.
- Negative Macro/Micro narrows symmetrically via `abs(gain_bits_eff)`.

## P1 - `s = 0` Bit-Identical Claim Needs A Stronger Implementation Rule

The spec promises that `s = 0` is bit-identical to V0.2. This is a good invariant,
but it is stricter than "sounds the same" or "approximately same magnitude".

Possible ways to accidentally violate it:

- Recomputing coefficients through a new helper that changes operation order.
- Clamping via `min(max(...))` in a way that returns an equivalent but not identical
  floating value.
- Changing `setup_band()` or `bp[]` storage layout while adding the new slider.
- Adding sliders in a way that renumbers or shifts existing automation parameters.

**Recommendation:** require an explicit fast path:

`q_eff = (qchar == 0 || ftype != Bell) ? q_knob : computed_proportional_q`

and add tests stronger than magnitude approximation:

- Python coefficient tuple for `s = 0` equals the existing V0.2 coefficient tuple
  exactly for representative Bell settings.
- JSFX source-level test proves existing slider numbers 11-48, 51-88, 91-123 are not
  renumbered.
- Live/null check: V0.3 with all Q Character sliders at 0 nulls against V0.2 for
  static Bell settings.

## P1 - Q_MAX Is Not Yet A Spec Constant

The spec says `Q_MAX` is a tested-stable upper clamp, with candidate `16`, and says
the plan pins it. This leaves a critical safety constant open.

**Risk:** different implementers may choose different clamps, changing both sound and
stability. Since the clamp defines the maximum "character" of the feature, it is not
just an implementation detail.

**Recommendation:** before implementation, pin the constant in the spec or in the
plan header:

`Q_MAX = 16.0` unless numeric prevalidation proves a better value.

Also add tests at the worst cases:

- `Q_knob = 10`, `gain_bits_eff = 16`, `s = 1` clamps to `16`.
- High-frequency Bell, high boost/cut, `Q_eff = Q_MAX` produces no NaN/Inf and bounded
  output on sine, sweep, and impulse-like input.

## P1 - Slider Allocation Is Deferred But Risky

The spec says one new slider per band is allocated in a free per-band slot, exact
index in the plan. In V0.2 the static banks use 11-18, 21-28, 31-38, 41-48, leaving
apparent free slots 19, 29, 39, 49. Dynamic and Hard banks occupy later ranges.

**Risk:** a plan that inserts sliders in the middle or renumbers existing sliders can
break automation, presets, TCP parameter expectations, and tests that rely on actual
slider values.

**Recommendation:** reserve exact indices now:

- `slider19` = B1 Q Character
- `slider29` = B2 Q Character
- `slider39` = B3 Q Character
- `slider49` = B4 Q Character

Then add source-level tests:

- Existing slider labels/numbers from V0.2 remain unchanged.
- Only sliders 19/29/39/49 are added.
- New slider default is exactly `0`.

## P2 - Non-Bell Untouched Needs Both Coefficient And Runtime Tests

The spec says Shelf / HP / LP ignore `s`. That should be verified at two levels.

**Risk:** an implementation can correctly avoid changing static non-Bell
coefficients while still storing `q_eff` into shared `bp[]`, causing shelf dynamics
or later code to see a modified Q.

**Recommendation:** add tests that cover:

- Static Shelf / HP / LP coefficient tuples are identical for `s = 0` and `s = 1`.
- Mode A shelf dynamics remain identical when Q Character changes.
- Mode B shelf split remains identical when Q Character changes.

## P2 - Bandwidth Verification Needs A Precise Measurement Definition

The spec asks for measured `-3 dB bandwidth in octaves` to shrink monotonically with
gain. This is the right behavioral test, but the exact measurement procedure is not
defined.

**Risks:**

- For cuts, "-3 dB bandwidth" can be interpreted relative to unity, relative to the
  notch depth, or relative to half-depth.
- For small gains, the curve may be too shallow for stable bandwidth measurement.
- Near Nyquist, warped frequency response can make octave bandwidth estimation noisy.

**Recommendation:** define the test procedure in the plan:

- Use boost cases first, e.g. +0.5, +1, +2 effective bits.
- Measure bandwidth at halfway between unity and peak gain in linear or dB terms, and
  name that convention.
- Keep center frequencies away from edges, e.g. 1 kHz and 3 kHz at 48 kHz.
- Add cut symmetry as a separate test if needed.

## P2 - Research Claim Is Directionally Good But Should Not Be A Numerical Target

The research note supports the main axis: constant Q vs proportional Q is the useful
implementation distinction. But the proposed law is a simple musical control, not a
fit to SSL-G, Neve 88RS, API, or any specific unit.

The spec mostly says this already, but the plan should preserve it.

**Recommendation:** avoid naming any `s` value as "SSL", "Neve", "API", "GML", or
"Sontec" in V0.3. Use neutral UI labels:

- `Q Character`
- `Constant` at `0`
- `Proportional` as the control increases

Brand-style presets can come later only after measured matching.

## P2 - Live Checks Need Automation And Extreme-Change Coverage

The live checklist mentions audibility, `s = 0`, and instability at extremes. It
should also include parameter movement cases.

**Recommendation:** add live checks:

- Automate Q Character from 0 to 1 while audio plays; no zipper/click beyond normal
  coefficient-recompute behavior.
- Automate Macro/Micro gain while Q Character is high; narrowing follows gain without
  explosive resonance.
- Toggle band type Bell -> Shelf -> Bell with Q Character nonzero; Shelf ignores it,
  Bell resumes expected behavior.
- Compare V0.3 `s = 0` against V0.2 using a null or near-null static render.

## Suggested Pre-Implementation Edits

1. Decide whether dynamic Bell detector/cut/split use `Q_eff` or raw `Q_knob`.
2. Rename `bits` to `gain_bits_eff` and test Bit Ratio edge cases.
3. Pin `Q_MAX` before implementation.
4. Reserve slider indices 19/29/39/49 and add source-level slider-number tests.
5. Define the bandwidth measurement convention for proportional narrowing tests.
6. Add explicit `s = 0` exact-coefficient and V0.2 null-regression checks.
