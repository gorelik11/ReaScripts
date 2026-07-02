# RCBitNova V0.2 — Shelf Dynamics (dynamic de-esser / low-end tamer)

**Status:** design approved by Dima 2026-07-02. **Parent spec:**
`2026-06-29-rcbitnova-dynamic-eq-design.md` (§4 promised dynamics on Bell **and**
Shelf; this spec makes the shelf side concrete). **Target file:** `JSFX/RCBitNova V0.2`
(copy of frozen V0.1, commit 8456eb3). **Oracle:** `tools/rcbitnova_dsp.py` + tests.

## 1. Goal and scope

Extend per-band dynamics (currently Bell-only) to **Low Shelf and High Shelf** types.
HP/LP stay static-only (unchanged from parent spec).

- **High shelf + dynamics = de-esser:** the shelf ducks by the detector's excess over
  the ceiling and releases; phase-clean in Mode A, bit-exact region clamp in Mode B.
- **Low shelf + dynamics = boominess/rumble tamer:** mirror behaviour below `freq`.

Delivered in **two sub-phases**, both inside V0.2:

1. **Phase S-A:** Mode A shelf-cut (cheap, low-risk, de-esser classic) + live check.
2. **Phase S-B:** Mode B shelf-region split limiter + live check.

All existing invariants hold (handoff §5): TPT-SVF only, bit-denominated ceilings
`2^-(Macro+Micro/100)`, Soft+Hard cascade with two ceilings, instance-local memory,
running L/R with per-band placement domains, global Mode-B lookahead with PDC gated
on bypass.

## 2. Detector (shelf-region)

The Bell detector is a bandpass at `freq`/`Q`. A shelf must react to energy in its
**whole region**, so:

- Dedicated detector SVF at the band's `freq`, **fixed detector Q = 0.7071**
  (Butterworth: monotonic, no resonant bump), independent of the band's shelf Q.
- **High shelf** taps the **HP output** `v0 - k*v1 - v2`; **low shelf** taps the
  **LP output** `v2`.
- Fed post-static-EQ in the band's placement domain, envelope/linking semantics
  identical to Bell (§4.1 of parent spec: peak, Attack/Release, Linked/Dual-LR/Dual-MS).
- Normalisation: the detector is naturally unity in its passband; measured at
  fc = 6 kHz, 48 kHz: |H(1k)| = 0.025, |H(fc)| = 0.7071, |H(16k)| = 0.9983,
  global max 0.9999 (no bump). Comparison vs `ceiling_lin` is therefore
  "region energy vs ceiling", same semantics as Bell.

## 3. Mode A — dynamic shelf-cut (Phase S-A)

- A **second shelf filter** of the same `freq`/`Q` stacked after the static band
  filter (static gain and dynamic cut independent, exactly like the Bell-cut).
- Cut gain `gdyn = gSoft * gHard` from the **existing** Soft+Hard cascade
  (soft ceiling: atk/rel envelope; hard ceiling: instant attack), unchanged.
- **Per-sample coefficient update without tan():** precompute `g0 = tan(pi*fc/sr)`
  once; per sample `A = sqrt(gdyn)`, `rA = sqrt(A)`, then
  - high shelf: `g = g0 * rA`, `m0 = A*A`, `m1 = k*(1-A)*A`, `m2 = 1-A*A`
  - low shelf: `g = g0 / rA`, `m0 = 1`, `m1 = k*(A-1)`, `m2 = A*A-1`
  - `a1 = 1/(1+g*(g+k))`, `a2 = g*a1`, `a3 = g*a2`, `k = 1/q` (band's shelf Q).
  Verified: matches full `svf_make` recompute to machine zero at gains 1..2^-5.
- Same honesty as Bell Mode A: smooth float gain-riding, **no absolute guarantee**.

## 4. Mode B — shelf-region split limiter (Phase S-B)

- **Perfect-reconstruction split** from one SVF at `freq`, detector Q = 0.7071:
  `LP + k*BP + HP == input` (verified to 2e-16). High shelf splits out the **HP
  branch**; low shelf the **LP branch**; the remainder (`LP + k*BP` resp.
  `HP + k*BP`) passes untouched.
- The split branch runs the **existing Mode B cascade**: Soft = PurestGain-smoothed
  ride toward Soft Ceiling; Hard = instant attack + **bit-exact clamp** at Hard
  Ceiling; global shared lookahead `L`, detectors on un-delayed signal, corrections
  on the delayed bus, `pdc_delay = L` (0 when bypassed) — all reused as-is.
- **Guarantee scope (honest, same as Bell):** the clamp bounds the split region's
  own contribution, NOT the summed output.

## 5. Controls and JSFX surface

- **No new sliders.** Shelf-type bands gain access to the existing per-band dyn
  controls (Dyn on/off, Mode A/B, Soft/Hard on/off, two ceilings, Attack/Release,
  Dyn Stereo Mode). Implementation change: the dynamics gate currently requires
  type == Bell; it becomes type in {Bell, Low Shelf, High Shelf}, and the detector/
  cut path is selected by type.
- New state (detector SVF ic1/ic2 per band-channel, shelf-cut filter state) is
  **appended past the last block** of the V0.1 memory map (handoff §5).

## 6. Verification

Design-stage numerical prototype (scratchpad `shelf_dyn_proto.py`, 8/8 PASS,
2026-07-02): split identity 2e-16; fast coeff update == svf_make; stability under
150 Hz gain modulation (peak 0.999, no NaN); end-to-end de-esser on 1 kHz tone +
8 kHz burst at ceiling 0.25: burst -6.3 dB toward ceiling, tone +0.000 dB during
and after (full release).

Implementation follows the handoff method: TDD into the Python mirror first
(equivalence tests: shelf cascade with dynamics off == static shelf; Mode B shelf
with both stages off == identity; high/low shelf mirror symmetry), then line-by-line
JSFX transcription, deploy, live-verify with Dima.

## 7. Out of scope for V0.2

- Dynamics on HP/LP; bell character models; phase modes / oversampling; GUI;
  RMS detector option; any change to `JSFX/RCBitNova V0.1` (frozen, tag
  `rcbitnova-v0.1`).
