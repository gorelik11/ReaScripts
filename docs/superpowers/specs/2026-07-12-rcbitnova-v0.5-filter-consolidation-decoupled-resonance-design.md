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
- **Out-of-range Type sanitization (do NOT rely on the slider max).** A restored preset,
  automation envelope, or script can still present the old values `3`/`4` (or a negative/out-of-range
  value). Because `svf_set`'s tail is "otherwise High Shelf", such a value would silently become a
  High Shelf. Guard it: before use, clamp the per-band Type to a safe value — **`ty > 2 || ty < 0 -> ty = 0` (Bell)**. At Bell with 0 gain the band is transparent, so a stale HP/LP value degrades to a no-op rather than a surprise High Shelf. Test values `3`, `4`, `-1`, and `5`.
- Backward compatibility: V0.5 is a new file. Cross-file preset/state transfer from V0.4 is **not supported** (a different JSFX file is a different plugin); existing projects keep using the V0.4/earlier file. New projects get HP/LP only from the dedicated section.

## 3. Dedicated section — slope = staggered-Butterworth cascade

- Slope options unchanged: **Off / 12 / 24 / 36 / 48 / 96 dB/oct** = `0 / 1 / 2 / 3 / 4 / 8` cascaded 2nd-order SVF sections (enum `5 -> 8`).
- **Each section uses its staggered-Butterworth Q** for a maximally-flat 2N-th-order response: section `k` of `N` uses `Q_k = 1 / (2 * cos(pi*(2k+1) / (4N)))`. (Same formula RCBitBrickwall's `calc_cascade` uses.)
- Result (session prototype, 2026-07-12; promoted to permanent test 1): **|H(fc)| = -3.01 dB for EVERY slope** (12..96), monotonic rolloff, flat passband — no droop, no wiggle. This replaces V0.4's "section 0 = user Q, rest 0.7071" convention (which gave -3xN dB at fc and the high-Q dip).

## 4. Resonance — a separate peaking bell at the cutoff

- The dedicated-section per-filter **Q** slider is replaced by **Resonance** (range `0..1`, default `0`).
- Resonance drives a **separate 2nd-order peaking bell at fc**, applied in series AFTER the Butterworth cascade, with a fixed moderate bell Q (`RES_BELL_Q = 2.0`).
- **Linear peak-gain map (bit-clean, no dB / no log / no pow(10)):** the bell's linear gain is `glin = 1 + Resonance * K` with `K = 5.0` (so `Resonance=0 -> glin=1 =` identity bell = flat; `Resonance=1 -> glin=6 ≈ +15.6 dB` peak). Pre-validated peaks: `r=0.5 -> +6..+7.8 dB`, `r=1.0 -> +15..+15.8 dB`, **a clean single peak at 12 / 24 / 96 dB/oct with NO dip** (the exact defect V0.4 had is gone).
- `Resonance = 0` -> `glin=1` -> the bell is **exact identity** (Simper bell at `glin=1`: `A=1`, `m1=k*(A*A-1)=0`, `m2=0`, so output `= m0*x = x` for ANY state). **The bell ALWAYS ticks while Slope is active** (do NOT skip it at `Resonance=0`): at `glin=1` its output is exactly the input while its integrators keep tracking the live signal, so raising Resonance from 0 resumes from **current** state — no click/transient on a `1 -> 0 -> 1` Resonance sweep. (Skipping the bell would leave stale integrators and click on re-enable — rejected.)
- **`Slope = Off` disables the ENTIRE section** (cascade AND bell), regardless of Resonance: no processing, no state advance, bit-perfect passthrough, zero latency. A standalone bell never runs when Slope is Off.
- **Resonance bandwidth is gain-dependent (accepted, documented).** The Simper bell uses `k = 1/(Q*A)` with `A=sqrt(glin)`, so a fixed input `Q=2` yields a peak that narrows slightly as Resonance rises — musically natural for a resonance (more resonance = sharper). The design fixes the input `Q=2`; a bandwidth characterization test records the actual widths at Resonance 0.25/0.5/1.0.
- Accepted cosmetic (documented): at steep slopes the resonant peak sits slightly ABOVE `fc` (the Butterworth is still rising through `fc` while the bell peaks at `fc`) — e.g. peak near `1.06*fc` at 96 dB/oct. This is a small, monotonic single peak, not a wiggle; the bell stays centered at `fc`.

**Cutoff vs Nyquist (pinned, shared Python + JSFX).** The coefficient formula uses `tan(pi*fc/srate)`, which misbehaves as `fc -> Nyquist`. Use an **effective cutoff `fc_eff = min(slider_freq, srate * 0.49)`** in BOTH the mirror and the JSFX (so 20 kHz is safe at 44.1 kHz and clamps below Nyquist at lower rates). Supported sample rates: 44.1 / 48 / 96 / 192 kHz (tested); below 44.1 kHz the clamp keeps it stable but is not a target. (This also retires the V0.4 deferred Nyquist-guard Minor.)

## 5. Memory / coefficient layout (dedicated section rework)

The dedicated section's state and coefficients grow to hold up to 8 Butterworth sections + 1 resonance bell per filter. Exact map (pinned; the plan confirms non-overlap by a source test):

- **`hplp_state = egh + N_BANDS*2`** (same base as V0.4, `egh` is the last existing block), **size 72** (`[hplp_state, hplp_state+72)`). Per filter base `fi*36` (HP `[0,36)`, LP `[36,72)`); stage `s` (0..7 sections, `8` = bell), channel `c`: `base + s*4 + c*2 + {0,1}`.
- **`hplp_cf = hplp_state + 72`**, **size 126** (`[hplp_cf, hplp_cf+126)`). Per filter base `fi*63` (HP `[0,63)`, LP `[63,126)`); section `k` set = `base + k*7` (k 0..7); bell set = `base + 56`.
- **Reset ranges (Slope/Placement change only):** HP `memset(hplp_state, 0, 36)`, LP `memset(hplp_state+36, 0, 36)` — HP reset never touches LP and vice-versa. A source test asserts `hplp_state`/`hplp_cf` are disjoint from each other and from the existing blocks, and the bell slots lie inside their owning filter's range.
- Coefficients computed in `@slider`: for the current `N`, each section `k` gets `hplp_coef` at Butterworth `Q_k = 1/(2*cos(pi*(2k+1)/(4N)))`; the bell set = `svf_make("bell", fc_eff, 2.0, 1 + Resonance*5)`. State reset only on Slope or Placement change, NOT on Freq/Resonance (continuous — see the always-tick bell rule in section 4). Increasing Slope initializes every newly-active section (they were zeroed at the last Slope change).

**Controls (pinned).** The dedicated-section per-filter Q slider is repurposed as Resonance:
`slider133` **HP Resonance** `0<0,1,0.001>` (was HP Q), `slider137` **LP Resonance** `0<0,1,0.001>` (was LP Q); default `0`, label "Resonance". Other dedicated-section sliders (131/132/134/135/136/138) keep their V0.4 meaning. No slider is renumbered. Cross-file V0.4->V0.5 preset transfer is unsupported (section 2), so the range change from `0.1..10` to `0..1` carries no migration obligation.

## 6. Bit-accuracy and latency (unchanged invariants)

The slope cascade has no gain. The resonance bell adds a peak boost, but it is a FILTER-shape gain computed from a LINEAR map (`1 + r*K`) — no `log`, `dB`, `pow(10)`, or `20*` — analogous to a resonant analog filter, and it never touches the plugin's bit-accurate signal-gain (Macro/Micro/BitRatio) or ceiling stages. The section stays zero-latency (pure 2nd-order SVF cascade + bell); `pdc_delay` unchanged.

## 7. Verification

Method as before: Python DSP mirror first (TDD), then JSFX transcription, then live-verify. A session prototype validated the numbers (ephemeral scratch, not an in-repo artifact); every claim below is a permanent test — the oracle is the authority, source-string guards only verify wiring.

**Analytic-response tests are parameterized across HP AND LP, N in {1,2,3,4,8}, Resonance in {0, 0.1, 0.5, 1.0}, cutoff in {low, mid, high}, sample rate in {44100, 48000, 96000, 192000}.** LP is tested as the mirrored case (own assertions), not only through a shared helper. "Single peak" is defined numerically on a log frequency grid: exactly one interior local maximum in the passband, no interior local minimum (within a small derivative tolerance), passband = above fc for HP / below fc for LP.

Permanent tests (Python oracle):
1. **Butterworth cascade flat at fc:** `|H(fc)| == -3.01 dB` (within 0.05) for every N, HP and LP (maximally-flat; catches a wrong staggered-Q or a mirrored LP wiring error).
2. **Slope N x 12 dB/oct** far-stopband, HP and LP, every N.
3. **Resonance peak height:** `0 -> no bump` (<= +0.1 dB over passband); `0.5 -> +6..+8 dB`; `1.0 -> +14..+16 dB`, at 12 AND 96 dB/oct, HP and LP.
4. **No dip / single peak:** at 96 dB/oct, `Resonance=1`, HP and LP — the passband is a single peak then monotonic decay (the exact V0.4 regression).
5. **Resonance=0 == pure Butterworth cascade** (bell bit-exact identity at glin=1); and **always-tick continuity:** a time-domain `Resonance 1 -> 0 -> 1` sweep on sine / noise / silence produces no transition burst beyond a pinned bound (the bell keeps ticking at glin=1).
6. **Worst-case time-domain stability (restored from V0.4):** HP and LP, alone and in series, `Resonance=1`, every slope, at min and max `fc_eff`, across the supported sample rates, on impulse / full-scale sine / sweep / noise / silence-tail — output and internal state finite (no NaN/Inf/denormal blow-up), bounded peak, bounded internal integrator state.
7. **Nyquist clamp:** `fc_eff = min(slider_freq, srate*0.49)` at 44.1/48/96/192 kHz, both slider endpoints; no instability at 20 kHz on a low-rate session.
8. **Type sanitization:** the Type-sanitize helper maps `3, 4, -1, 5 -> 0` (Bell); values `0/1/2` pass through.
9. **Bit-clean map:** resonance gain = `1 + r*K` — no `log`/`dB`/`pow(10)`/`20*` in the production functions (grep-level assertion).
10. **Consolidation source guards:** per-band Type enum is `{Bell,Low Shelf,High Shelf}` (max 2); `svf_set` has no HP/LP (ftype 3/4) branch; the dedicated-section Resonance sliders are `slider133`/`slider137` = `0<0,1,0.001>`.
11. **Off / Slope=Off / placement / latency:** `Slope=Off` (Resonance 0 AND 1, nonzero prior state) = bit-exact passthrough, no state advance; placement routing (HP-Side leaves Mid/mono untouched) unchanged; zero-latency (`pdc_delay` unchanged).
12. **Bandwidth characterization:** record the resonance -3 dB bandwidth at Resonance 0.25/0.5/1.0 (documents the accepted gain-dependent narrowing).

Live checks (Dima): each slope clean/flat, no wiggle at any Resonance; Resonance 0->1 grows a clean bump at cutoff at 12 and 96 (the V0.4 dip is gone); per-band Type no longer offers HP/LP; Off nulls vs V0.4-filters-off; **automation (measurable, not "by ear"):** Slope and Placement changes are a discrete topology change (brief transition, state cleared — no instability/burst, not required to null); Freq and Resonance are continuous (coefficient steps may zipper like any IIR, bounded — no burst/instability); Resonance `1->0->1` click-free (always-tick). **CPU:** record the delta vs V0.4 at the worst case (HP 96 Both + LP 96 Both + Resonance 1 = up to 18 stages/sample); confirm acceptable on the target session. Source self-review: coeffs precomputed in `@slider`, no per-sample branch ladders.

## 8. Out of scope for V0.5

The LINEAR-phase HP/LP + Brickwall (Arthur's FFT block) as a phase-mode option -> V0.6. Bell shape/order modeling; saturation; any change to the dynamics/proportional-Q. Any change to frozen `JSFX/RCBitNova V0.1..V0.4` (tags `rcbitnova-v0.1..v0.4`). V0.5 is a new file `JSFX/RCBitNova V0.5`, copied from V0.4.
