# RCBitNova V0.5 — Filter consolidation + decoupled resonance design

Date: 2026-07-12
Author: Dima Gorelik + Claude (Opus 4.8)
Status: approved (brainstorm), pending spec review

---

## 1. Goal and scope

Two changes to RCBitNova's filtering, both in the HP/LP path:

1. **Consolidate** — remove High Pass / Low Pass from the per-band **Type** enum. HP/LP live only in the dedicated HP/LP section (added in V0.4). The two-places-for-filters redundancy goes away.
2. **Decouple resonance from slope** — rework the dedicated section so its slope is a clean maximally-flat cascade and its resonance is a separate peak. This removes the V0.4 "wiggle/dip near cutoff at high Q + high slope" (an inherent limit of the old "Q on the first section" convention).

**In scope:** per-band Type reduced to `{Bell, Low Shelf, High Shelf}`; removal of the now-dead HP/LP branches from `svf_set`; dedicated-section slope changed to a **staggered-Butterworth** cascade; the dedicated-section `Q` control replaced by a **Resonance** control that drives a separate peaking bell at the cutoff.

**Out of scope (deferred to V0.6):** the LINEAR-phase HP/LP block (Arthur's FFT approach) + Brickwall, as a separate phase-mode option — a large separate FFT subsystem (~64 ms latency). Also out: any change to the bell/shelf dynamics, Mode A/B, or proportional-Q.

## 2. Consolidation — remove per-band HP/LP

- Per-band **Type** enum changes from `{Bell(0), Low Shelf(1), High Shelf(2), High Pass(3), Low Pass(4)}` to `{Bell(0), Low Shelf(1), High Shelf(2)}` (slider max 4 -> 2, for all four bands). Values 0/1/2 are unchanged, so the shelf/bell code (`ty==1||ty==2`, `ty==0`) and the detector `qd` logic need no change.
- Remove the now-unreachable **High Pass (ftype 3)** and **Low Pass (ftype 4)** branches from `svf_set`; restructure to `ftype==0 ? Bell : ftype==1 ? Low Shelf : High Shelf`. The dedicated section uses its own coeff builder (not `svf_set`), so this does not affect it.
- Backward compatibility: V0.5 is a new file; existing projects keep using the V0.4/earlier file. New projects get HP/LP only from the dedicated section.

## 3. Dedicated section — slope = staggered-Butterworth cascade

- Slope options unchanged: **Off / 12 / 24 / 36 / 48 / 96 dB/oct** = `0 / 1 / 2 / 3 / 4 / 8` cascaded 2nd-order SVF sections (enum `5 -> 8`).
- **Each section uses its staggered-Butterworth Q** for a maximally-flat 2N-th-order response: section `k` of `N` uses `Q_k = 1 / (2 * cos(pi*(2k+1) / (4N)))`. (Same formula RCBitBrickwall's `calc_cascade` uses.)
- Result (pre-validated `resonance_decouple_proto.py`, 2026-07-12): **|H(fc)| = -3.01 dB for EVERY slope** (12..96), monotonic rolloff, flat passband — no droop, no wiggle. This replaces V0.4's "section 0 = user Q, rest 0.7071" convention (which gave -3xN dB at fc and the high-Q dip).

## 4. Resonance — a separate peaking bell at the cutoff

- The dedicated-section per-filter **Q** slider is replaced by **Resonance** (range `0..1`, default `0`).
- Resonance drives a **separate 2nd-order peaking bell at fc**, applied in series AFTER the Butterworth cascade, with a fixed moderate bell Q (`RES_BELL_Q = 2.0`).
- **Linear peak-gain map (bit-clean, no dB / no log / no pow(10)):** the bell's linear gain is `glin = 1 + Resonance * K` with `K = 5.0` (so `Resonance=0 -> glin=1 =` identity bell = flat; `Resonance=1 -> glin=6 ≈ +15.6 dB` peak). Pre-validated peaks: `r=0.5 -> +6..+7.8 dB`, `r=1.0 -> +15..+15.8 dB`, **a clean single peak at 12 / 24 / 96 dB/oct with NO dip** (the exact defect V0.4 had is gone).
- `Resonance = 0` -> the bell is identity (`glin=1`), so the filter is a pure clean Butterworth cascade. The bell state is skipped when `Resonance = 0` (no processing, no state advance).
- Accepted cosmetic (documented): at steep slopes the resonant peak sits slightly ABOVE `fc` (the Butterworth is still rising through `fc` while the bell peaks at `fc`) — e.g. peak near `1.06*fc` at 96 dB/oct. This is a small, monotonic single peak, not a wiggle; the bell stays centered at `fc`.

## 5. Memory / coefficient layout (dedicated section rework)

The dedicated section's state and coefficients grow to hold up to 8 Butterworth sections + 1 resonance bell per filter (the plan pins exact offsets):

- **`hplp_state`**: 2 filters x (8 sections + 1 bell) x 2 channels x 2 integrators = **72 slots** (was 64). Per filter base `fi*36`; stage `s` (0..7 sections, 8 = bell), channel `c`: `base + s*4 + c*2 + {0,1}`.
- **`hplp_cf`**: 2 filters x (8 Butterworth section sets + 1 bell set) x 7 = **126 slots** (was 28). Per filter base `fi*63`; section `k` set = `base + k*7`; bell set = `base + 8*7`.
- Coefficients are computed in `@slider`: for the current `N`, each section `k` gets `hplp_coef` at Butterworth `Q_k`; the bell gets `svf_make("bell", fc, 2.0, 1+Resonance*5)` coefficients. State reset policy is unchanged from V0.4: zero a filter's state only on Slope or Placement change, NOT on Freq/Resonance (continuous).

## 6. Bit-accuracy and latency (unchanged invariants)

The slope cascade has no gain. The resonance bell adds a peak boost, but it is a FILTER-shape gain computed from a LINEAR map (`1 + r*K`) — no `log`, `dB`, `pow(10)`, or `20*` — analogous to a resonant analog filter, and it never touches the plugin's bit-accurate signal-gain (Macro/Micro/BitRatio) or ceiling stages. The section stays zero-latency (pure 2nd-order SVF cascade + bell); `pdc_delay` unchanged.

## 7. Verification

Method as before: Python DSP mirror first (TDD), then JSFX transcription, then live-verify. Numeric pre-validation done (`resonance_decouple_proto.py`).

Permanent tests (Python oracle), using `svf_response` for analytic magnitude:
1. **Butterworth cascade flat at fc:** `|H(fc)| == -3.01 dB` (within 0.05) for N in {1,2,3,4,8} (the maximally-flat property; catches a wrong staggered-Q).
2. **Slope still N x 12 dB/oct** far-stopband for N in {1,2,3,4,8}.
3. **Resonance peak height:** `Resonance=0 -> no bump` (max in-band <= +0.1 dB above passband); `0.5 -> +6..+8 dB`; `1.0 -> +14..+16 dB` peak, at 12 AND 96 dB/oct.
4. **No dip / single peak:** at 96 dB/oct with `Resonance=1`, the magnitude above fc is a single peak then monotonic decay (no local minimum in the passband) — the regression that failed the old convention.
5. **Resonance=0 == pure Butterworth cascade** (the bell is bit-exact identity at glin=1).
6. **Bit-clean map:** the resonance gain map is `1 + r*K` (asserted at the code/helper level: no dB/pow(10) in the production functions).
7. **Consolidation:** the JSFX per-band Type enum is `{Bell,Low Shelf,High Shelf}` (max 2), and `svf_set` has no HP/LP (ftype 3/4) branch (source guards).
8. **Off / placement / latency** unchanged from V0.4 (Off = identity, placement routing, zero-latency).

Live checks (Dima): each slope clean/flat with no wiggle at any Resonance; Resonance 0->1 grows a clean bump at cutoff at 12 and 96 dB/oct (the V0.4 high-Q dip is gone); per-band Type no longer offers HP/LP; Off nulls vs V0.4-with-filters-off; no zipper on Slope/Freq/Resonance automation; CPU acceptable.

## 8. Out of scope for V0.5

The LINEAR-phase HP/LP + Brickwall (Arthur's FFT block) as a phase-mode option -> V0.6. Bell shape/order modeling; saturation; any change to the dynamics/proportional-Q. Any change to frozen `JSFX/RCBitNova V0.1..V0.4` (tags `rcbitnova-v0.1..v0.4`). V0.5 is a new file `JSFX/RCBitNova V0.5`, copied from V0.4.
