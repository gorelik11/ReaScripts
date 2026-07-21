# RCBitNova V0.6 — Linear-Phase HP/LP + Brickwall — Design Spec

**Date:** 2026-07-21
**Branch:** `rcbitnova` (worktree `~/projects/reascripts/.claude/worktrees/rcbitnova/`)
**Base:** V0.5 (frozen, tag `rcbitnova-v0.5`, commit `5a6d985`) — new file `JSFX/RCBitNova V0.6`
**Reference engine:** `~/Library/Application Support/REAPER/Effects/linear_artur_slope_7.jsfx` (Arthur — partitioned convolution, linear-phase HP/LP + Brick)

---

## 1. Goal

Add a **linear-phase mode to the dedicated HP/LP section only**, plus a **Brickwall**
(infinite-slope) option available in that mode. A single global `Phase: Min / Linear`
switch selects the path for the whole HP/LP section. Everything else (per-band bells,
shelves, Mode A/B dynamics) is untouched and stays minimum-phase.

The min-phase HP/LP path from V0.5 (`hplp_run`, per-sample, zero-latency) is left
**completely intact** and runs when `Phase = Min`. Linear phase is a *separate* code path.

## 2. Scope decision — why linear phase is HP/LP-only (fundamental, not effort)

Dima's rule: linear phase goes into the bit EQ + limiter **only if it stays bit-accurate
there**; otherwise no linear phase in those blocks at all. The DSP verdict:

- **Static EQ (bells, shelves) + HP/LP are LTI** → linear phase is achievable and honest.
  Bit-accuracy lives in the *controls* (gains/ceilings on the `2^n` grid) and *pure gain
  stages*; those survive any phase mode. The filter arithmetic is ordinary float DSP in
  both min- and linear-phase (per handoff: "FIR/linear phase does not change this"). One
  caveat: exact gain *exactly at fc* is a min-phase SVF property; an FIR built from a
  truncated/windowed kernel approximates it — same float caveat every linear-phase EQ has
  (incl. Pro-Q). Control-grid bit-accuracy is unaffected.
- **Dynamics — Mode A (dynamic EQ) and Mode B (bit-exact limiter) — cannot be linear-phase
  without destroying the bit guarantee.** This is a theorem, not a difficulty:
  - Linear phase = FIR convolution = **LTI** system (linear, time-invariant), by definition.
  - A bit-exact limiter is a **nonlinear, time-varying** operation (`clamp(|x|, 2^-bits)`,
    gain depends on signal). **No LTI system can implement a clamp.** Mutually exclusive classes.
  - Ordering does not save it: `clamp → linear-FIR` re-introduces peaks above the ceiling
    (linear-phase pre/post ringing adds energy *after* the clamp → ceiling guarantee dead);
    `linear-FIR → clamp` means the clamp's output is no longer linear-phase. Either way,
    "linear phase AND bit-exact ceiling simultaneously" is unachievable.
  - Mode A is time-varying too (envelope-modulated gain); a linear-phase version would need
    per-block kernel rebuilds — no longer sample-accurate or bit-native, and Mode A never
    guaranteed an absolute ceiling anyway.

**Consequence:** a global Pro-Q-style switch that linearizes the *whole plugin including the
limiter* is impossible by physics. FabFilter Pro-Q's linear phase is a pure static LTI EQ —
it has no bit-exact clamp limiter. So V0.6 = **HP/LP linear phase only**. A future wider
"static-only linear" mode (bells/shelves linearized, dynamics forced min-phase or disabled)
is a possible V0.7+ target — deferred, decided later. This section is recorded so a future
session (or Fable) does not attempt to linearize the dynamics.

## 3. Architecture

### 3.1 Phase-mode switch
- New **global** slider `Phase: Min / Linear` for the entire HP/LP section (one switch,
  not per-filter). New slider bank (leave room per the banked-numbering convention).
- `Phase = Min` → existing V0.5 path: `hplp_run(0,…)` / `hplp_run(1,…)` per-sample,
  zero added latency. Frozen-compatible; bit-for-bit identical to V0.5.
- `Phase = Linear` → `hplp_run` is bypassed; HP and LP each run through an independent
  partitioned-convolution engine on their own Placement domain.

### 3.2 Slope enum extension
HP/LP slope enum grows: `Off / 12 / 24 / 36 / 48 / 96 / Brick` (index 6 = Brick).
`Brick` is active **only** in Linear mode; in Min mode it greys out / is ignored
(treat as Off, or clamp to 96 — see §7 open items).

### 3.3 Two independent convolution engines (Approach A, in the spirit of C)
Full independence of HP/LP Placement (HP may be Mid, LP may be Side, etc.) means the two
filters **cannot** share one FFT kernel (Arthur's single-kernel magnitude-multiply trick
requires a common domain). Therefore two independent partitioned-convolution engines run
**in series** in `@sample`. Their latencies **add**: each is `6144` samples (≈128 ms @48k
/ ≈64 ms @96k), so both in Linear ≈ `12288` samples (≈256 ms @48k / ≈128 ms @96k), plus
Mode B lookahead on top — accepted; PDC compensates.

## 4. Convolution engine (ported from Arthur)

Port Arthur's proven partitioned-convolution engine, instantiated **twice** (HP + LP):

| Constant | Value | Meaning |
|---|---|---|
| `P` | 2048 | partition / hop |
| `B` | 4096 | runtime FFT size |
| `BD` | 8192 | project kernel FFT size |
| `KMAX` | `BD/P = 4` | partitions |
| latency/filter | `BD/2 + P = 6144 smp` | fixed in SAMPLES: ≈128 ms @48k, ≈64 ms @96k; PDC-compensated |

Per engine (subscript for HP vs LP): kernel buffers `desbuf, ktime, win_k, Hspec`, runtime
buffers `fdl, fftw, yacc, tmpc, in, out, dry`. Kernel rebuilt only when its signature
(slope/freq/resonance/beta) changes (`need_rebuild` flag, built in `@block`, like Arthur).

**Per-channel within a domain:** each engine convolves its domain's two channels
(e.g. Mid+Side, or L+R, or a single channel duplicated for Mid-only) — Arthur runs A and B
lanes; we map the Placement domain onto those two lanes.

**PDC:** `pdc_delay = (sum of active linear-filter latencies) + (Mode B lookahead if any
Mode-B band active)`, and `0` when the whole plugin is bypassed (preserve V0.5's
zero-latency-on-bypass invariant). Detectors for Mode B still run un-delayed; the linear
HP/LP latency must be accounted so the dry/wet and Mode-B bus alignment stays correct
(integration risk — flagged for the adversarial review in the plan).

## 5. Magnitude parity (critical for Min/Linear A/B match)

The FFT kernel is built from **our** magnitude function so Linear matches Min in frequency
response (only phase differs):

```
mag(f) = butter_cascade_mag(f, fc, nsec) * resonance_bell_mag(f, fc, glin)
```

- `butter_cascade_mag` — staggered-Butterworth cascade magnitude using the SAME
  `butter_q(k, N) = 1 / (2*cos(pi*(2k+1)/(4N)))` per-section law as V0.5 `hplp_coef`.
  HP uses the highpass cascade shape; LP the lowpass shape.
- `resonance_bell_mag` — peaking bell, fixed `Q = 2`, `glin = 1 + Resonance*5` (linear),
  identical to V0.5 `hplp_bell`. `glin = 1` → identity (no bell), matching V0.5's
  no-click-on-1→0→1 behaviour.
- `fc_eff = min(freq, srate*0.49)` — same Nyquist guard as V0.5.
- `Brick` → magnitude step (HP: `f >= fc ? 1 : 0`; LP: `f <= fc ? 1 : 0`), **no resonance**.

Arthur builds the kernel from Butterworth magnitude with no resonance; we add the resonance
bell term to the magnitude so Linear resonance equals Min resonance. Kernel build: sample
`mag(f)` over `BD` bins (natural order, mirror above Nyquist) → zero-phase spectrum →
`fft_ipermute`+`ifft` → fftshift + Kaiser window (beta) + scale → partition into `Hspec`.
(Window beta: reuse Arthur's `slider5`-style beta control, or fix a sane default — see §7.)

## 6. Verification (Python oracle, stdlib-only)

No numpy/scipy on this machine. Verify analytically (extend `tools/rcbitnova_dsp.py` +
`tests/`, TDD, equivalence-style):

1. **Magnitude parity.** Build the FIR kernel in Python (hand-written radix-2 FFT on
   `cmath`; all sizes are powers of two). Its magnitude ≈ analytic `mag(f)`
   (Butterworth×resonance) within tolerance. AND that same analytic `mag(f)` == the V0.5
   min-phase filter's magnitude response (steady-state / transfer-function `cmath`) →
   this is the Min/Linear A/B guarantee, proven numerically.
2. **Linear-phase property.** Kernel impulse response is symmetric (`k[i] == k[N-1-i]`
   within tolerance) → phase is exactly linear. Assert symmetry directly.
3. **Partitioned == direct.** Partitioned convolution equals direct convolution of the same
   kernel on a short test signal (pure-Python reference direct-conv). Guards the
   partitioning/overlap bookkeeping before it hits JSFX.

Method unchanged: Python oracle green FIRST → line-by-line transcription into
`JSFX/RCBitNova V0.6` → live-verify with Dima in REAPER → tag `rcbitnova-v0.6`.

## 7. Sliders / memory / UI / open items

- **New slider** `Phase (Min/Linear)` — global, fresh bank range.
- **Slope enum** HP (`slider131`) & LP (`slider135`): add `Brick` (index 6). Range 0–6.
- **Memory:** all linear engine buffers (desbuf, ktime, win_k, Hspec, fdl, fftw, yacc,
  tmpc, in, out, dry — ×2 for HP+LP) allocate **after** `hplp_cf` (last V0.5 block).
  Fable to run a memory-disjointness source test (FFT allocates a lot — recorded in roadmap).
- **UI:** minimal for now — working functionality over polish. Explicit filter-enable and
  the big FFT-analyzer GUI remain a separate UX debt (see memory / handoff roadmap).
- **Open items to settle in the plan:**
  - Window beta: expose a `Window beta` slider (Arthur style, deeper stopband) or fix a
    default (e.g. 14)? Default proposed; expose only if Dima wants tunable stopband.
  - `Brick` in Min mode: grey-out vs clamp-to-96 vs treat-as-Off. Proposed: treat-as-Off
    (Brick is a Linear-only concept).
  - Confirm sample-rate assumption for the ~64 ms figure (latency is in *samples*, fixed;
    ms depends on srate — display like Arthur).

## 8. Non-goals (V0.6)

- No linear phase for bells/shelves (LTI-capable but deferred — see §2).
- No linear phase for Mode A / Mode B (impossible with bit guarantee — see §2).
- No new GUI / analyzer; no explicit filter-enable redesign.
- No second HP/LP pair.

## 9. Safety / invariants preserved

- V0.5 min-phase path byte-identical when `Phase = Min` (frozen-compatible).
- Bit-accuracy claim untouched: HP/LP are pure filters (no gain stage), so linearizing
  their phase does not touch the bit claim (which lives in gains/ceilings).
- `pdc_delay = 0` on full bypass (V0.5 invariant kept).
- New file `JSFX/RCBitNova V0.6` (copy V0.5); V0.5 stays frozen + tagged.
- Python DSP mirror remains THE ORACLE (pure stdlib); live REAPER confirms transcription.
