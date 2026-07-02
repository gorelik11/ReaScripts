# RCBitNova V0.2 — Shelf Dynamics (dynamic de-esser / low-end tamer)

**Status:** design approved by Dima 2026-07-02; **tightened 2026-07-02 per the weakness
review** (`2026-07-02-rcbitnova-v0.2-shelf-dynamics-weaknesses.md`): Mode B Q semantics,
three-gate guard checklist, state-reuse & reset policy, low-shelf DC decision, permanent
test list, Mode B observation point. (Weak review items — worktree-path note and the
"overcompressed" framing — intentionally not adopted.) **Parent spec:**
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
- Normalisation: the detector is **unity in its passband** (not at the cutoff point);
  measured at fc = 6 kHz, 48 kHz: |H(1k)| = 0.025, |H(fc)| = **0.7071** (−3 dB at
  cutoff), |H(16k)| = 0.9983, global max 0.9999 (no bump). Comparison vs `ceiling_lin`
  is "shelf-**region** energy vs ceiling" — like Bell in that it is a normalised
  detector peak, but it measures a whole region, not a single centre frequency. Control
  text should say so literally ("Shelf ceiling = peak of the shelf-region detector;
  −3 dB at cutoff, passband → unity"), not imply a single-frequency point.
- **Low-shelf DC / subsonic (decided per review):** the low-shelf detector taps the LP
  output, which is **unity at DC**, so it reacts to DC offset and subsonic rumble. This
  is **kept and intentional** (the low-shelf-dynamics use case *is* a rumble/boom tamer).
  The anti-denormal `anti` (±~8e-31) is far below any ceiling and never false-triggers.
  A detector-only DC-blocker / minimum-frequency floor is a **future opt-in**, out of
  scope for V0.2; document the DC sensitivity in the manual.

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

- **Perfect-reconstruction split** from one SVF at `freq`, **fixed Q = 0.7071**:
  `LP + k*BP + HP == input` (verified to 2e-16). High shelf splits out the **HP
  branch**; low shelf the **LP branch**; the remainder (`LP + k*BP` resp.
  `HP + k*BP`) passes untouched.
- **Q semantics (decided per review — document in the manual):** Mode B's split region
  is **intentionally Butterworth-wide and ignores the band's shelf Q** — the fixed
  0.7071 SVF is *required* for perfect reconstruction; an arbitrary Q would break
  `LP + k*BP + HP == input` and leak/duplicate energy. So the visible **Q control shapes
  the Mode A shelf-cut (§3) but NOT the Mode B split region.** This asymmetry is
  deliberate; it must be stated so users don't expect Q to reshape Mode B.
- **Observation point (precise):** as with Bell Mode B, the shelf detector runs inside
  the **global Mode B pass**, i.e. it observes the current post-static + post-Mode-A
  running bus at the band's position — not only its own static shelf output. This is a
  pre-existing property (identical for Bell), not shelf-specific. The guarantee remains
  **only for the extracted split contribution**, never the summed output.
- The split branch runs the **existing Mode B cascade**: Soft = PurestGain-smoothed
  ride toward Soft Ceiling; Hard = instant attack + **bit-exact clamp** at Hard
  Ceiling; global shared lookahead `L`, detectors on un-delayed signal, corrections
  on the delayed bus, `pdc_delay = L` (0 when bypassed) — all reused as-is.
- **Guarantee scope (honest, same as Bell):** the clamp bounds the split region's
  own contribution, NOT the summed output.

## 5. Controls and JSFX surface

- **No new sliders.** Shelf-type bands gain access to the existing per-band dyn
  controls (Dyn on/off, Mode A/B, Soft/Hard on/off, two ceilings, Attack/Release,
  Dyn Stereo Mode). The detector/cut path is selected by type.

- **Bell-only guard checklist (per review — all THREE must change together).** In
  V0.2 the `type == Bell` gate (`slider(10*(b+1)+2) == 0`) appears in exactly three
  places; a shelf that misses one silently stays static in a mode or fails to enable
  PDC. Change each to a `dyn_type` predicate = `type <= 2` (0 Bell, 1 Low Shelf,
  2 High Shelf); keep HP/LP (`type == 3 || type == 4`) static-only:
  1. `@slider` `any_b` / PDC gate — **line ~213**: `... && slider(10*(b+1)+2) == 0`.
  2. Mode A processing gate — **line ~267**: `(dp[b*4+3]==1 && slider(...)==0 && mbmode[b]==0)`.
  3. Mode B pass gate — **line ~346**: `(slider(50+10*b+1)==1 && mbmode[b]==1 && slider(...)==0)`.
  Add a Python + live check proving Low Shelf and High Shelf **activate PDC in Mode B**.

- **State reuse & memory (per review — no loose "append").** Band type is **mutually
  exclusive** (a band is Bell OR Shelf OR HP/LP), so the shelf detector and shelf-cut
  **reuse the existing per-band blocks**: `dst` (detector SVF state, 4/band) and `cst`
  (cut SVF state, 4/band) — the coefficients differ by type, the state slots do not.
  **No new memory block is added** for Mode A shelf; Mode B reuses `mb_band`/`mb_peak`/
  `mbenv`/`mbgc`/`mbeh` exactly as Bell. This keeps the V0.1 memory map (handoff §5)
  unchanged — safer than appending.
- **State reset on type/freq/Q change:** switching a band's type (or large freq/Q jump)
  leaves stale integrator state in `dst`/`cst`, producing a brief warm-up transient.
  V0.2 policy: **accept the warm-up** (converges within a few ms; matches the existing
  Mode-B re-enable behaviour) — do NOT hard-reset per sample. If a click is audible in
  testing, add a `@slider` one-shot zeroing of that band's `dst`/`cst` on type change
  (track previous type per band); document if added.

## 6. Verification

Design-stage numerical prototype (scratchpad `shelf_dyn_proto.py`, 8/8 PASS,
2026-07-02): split identity 2e-16; fast coeff update == svf_make; stability under
150 Hz gain modulation (peak 0.999, no NaN); end-to-end de-esser on 1 kHz tone +
8 kHz burst at ceiling 0.25: burst -6.3 dB toward ceiling, tone +0.000 dB during
and after (full release).

Implementation follows the handoff method: TDD into the Python mirror first, then
line-by-line JSFX transcription, deploy, live-verify with Dima.

**The scratchpad claims are not reproducible on their own — convert them into permanent
`tests/test_rcbitnova_dsp.py` tests (per review):**
1. Shelf-region detector shape: `|H|` low/high magnitude + unity-in-passband, 0.7071 at fc.
2. Perfect-reconstruction split identity: `LP + k*BP + HP == input` to ~2e-16.
3. Mode A shelf: dynamics off (Soft off, Hard off) **== static shelf** (equivalence).
4. Mode B shelf: both stages off **== identity** on the split path.
5. Fast per-sample coeff update **== full `svf_make`** recompute (machine-zero).
6. High/low shelf **mirror symmetry**.
7. De-esser burst: 8 kHz burst on a 1 kHz tone ducks toward ceiling; tone unaffected,
   full release after.
8. Low-shelf DC/subsonic: detector reacts to a DC-offset / subsonic input (documents the
   kept behaviour of §2).

**Live checks:** Low Shelf and High Shelf each — Mode A and Mode B, Soft/Hard/cascade —
plus an explicit **PDC-activates-for-shelf-in-Mode-B** check (the review's guard risk).

## 7. Out of scope for V0.2

- Dynamics on HP/LP; bell character models; phase modes / oversampling; GUI;
  RMS detector option; any change to `JSFX/RCBitNova V0.1` (frozen, tag
  `rcbitnova-v0.1`).
