# RCBitNova V0.6 — Linear-Phase HP/LP + FIR Brick — Design Spec

**Date:** 2026-07-21 (rev 3 — rev 2 folded Codex review `…-weaknesses.md`; rev 3 folds Fable
review `…-weaknesses-fable.md`: Brick-in-Min mapping fix, exact bell Q=2√glin, Phase-toggle
crossfade, pinned page layout, Phase slider #, Mode-B sample-index contract)
**Branch:** `rcbitnova` (worktree `~/projects/reascripts/.claude/worktrees/rcbitnova/`)
**Base:** V0.5 (frozen, tag `rcbitnova-v0.5`, commit `5a6d985`) — new file `JSFX/RCBitNova V0.6`
**Reference engine:** `~/Library/Application Support/REAPER/Effects/linear_artur_slope_7.jsfx`

---

## 1. Goal

Add a **linear-phase mode to the dedicated HP/LP section only**, plus a **FIR Brick**
(finite-FIR brick-style slope) option available in that mode. A single global
`Phase: Min / Linear` switch selects the path for the whole HP/LP section. Everything else
(per-band bells, shelves, Mode A/B dynamics) is untouched and stays minimum-phase.

The V0.5 min-phase HP/LP path (`hplp_run`, per-sample) is left **completely intact** and
runs when `Phase = Min`. Linear phase is a *separate* code path.

## 2. Scope — why linear phase is HP/LP-only (fundamental, not effort)

Dima's rule: linear phase goes into the bit EQ + limiter **only if it stays bit-accurate
there**; otherwise no linear phase in those blocks at all. DSP verdict:

- **Static EQ (bells, shelves) + HP/LP are LTI** → linear phase achievable and honest.
  Bit-accuracy lives in the *controls* (`2^n` grid) and *pure gain stages*; those survive
  any phase mode. Filter arithmetic is ordinary float DSP in both modes. Caveat: exact gain
  *exactly at fc* is a min-phase SVF property an FIR only approximates — same float caveat
  every linear-phase EQ has. Control-grid bit-accuracy is unaffected.
- **Dynamics — Mode A (dynamic EQ) and Mode B (bit-exact limiter) — cannot be linear-phase
  without destroying the bit guarantee** (theorem, not difficulty):
  - Linear phase = FIR = **LTI**, by definition.
  - A bit-exact limiter is **nonlinear + time-varying** (`clamp(|x|, 2^-bits)`). No LTI
    system can implement a clamp.
  - Ordering does not save it: `clamp → linear-FIR` re-introduces peaks above the ceiling
    (pre/post ringing after the clamp → guarantee dead); `linear-FIR → clamp` means the
    clamp output is no longer linear-phase. "Linear phase AND bit-exact ceiling" is
    unachievable.
  - Mode A is time-varying too; a linear version needs per-block kernel rebuilds — no longer
    sample-accurate or bit-native, and it never guaranteed a ceiling anyway.

**Consequence:** a global Pro-Q-style switch that linearizes the *whole plugin including the
limiter* is impossible by physics (Pro-Q's linear phase is a pure static LTI EQ — no clamp
limiter). V0.6 = **HP/LP linear phase only**. A future "static-only linear" mode
(bells/shelves linearized, dynamics forced min-phase or disabled) is a possible V0.7+
target — deferred. Recorded so a future session/Fable does not attempt to linearize the
dynamics.

## 3. Architecture

### 3.1 Phase-mode switch (global)
- New **global** slider `Phase: Min / Linear` for the entire HP/LP section. Fresh bank.
- `Phase = Min` → V0.5 path (`hplp_run`), byte-identical to V0.5 (except the intentional
  constant-latency delay of §9).
- `Phase = Linear` → `hplp_run` bypassed; HP and LP each run an independent
  partitioned-convolution engine on their own Placement domain.

**Phase toggle is click-safe (resolves the residual gap in the constant-PDC contract).**
Constant MAXLAT removes the *latency* jump but not audio-content continuity across the
Min↔Linear code-path swap. Because the linear engines are kept **warm** (§8) and **both** the
Min path and the Linear path are delayed to the same MAXLAT origin (§9), their outputs are
sample-aligned. On a Phase change, do a short **output crossfade** (≈ one partition `P`)
between the Min-path buffer and the Linear-path buffer — the same click-safe treatment
Freq/Slope/Placement get. No host latency renegotiation occurs (PDC is constant).

### 3.2 Slope enum extension
HP (`slider131`) / LP (`slider135`) enum grows: `Off / 12 / 24 / 36 / 48 / 96 / FIR Brick`
(index 6). Range 0–6. **FIR Brick** is active only in Linear; in Min it is **treated as Off**
(Brick is a Linear-only concept; stock enum sliders cannot grey out without custom UI). The
label is `FIR Brick`, deliberately distinct from Mode-B "Brick" (a hard bit ceiling) to
avoid confusing a finite-FIR slope with a literal-guarantee limiter.

**MANDATORY mapping fix (else index 6 mis-runs in Min):** V0.5 computes
`hp_nsec = slider131 == 5 ? 8 : slider131` (line 342) and the LP analogue (356). Extending
the enum to index 6 without updating this makes Min mode run a **6-section (72 dB/oct)**
cascade instead of Off. Both mappings MUST become, in Min mode:
`nsec = slider == 6 ? 0 : slider == 5 ? 8 : slider` (Brick → Off = 0 sections). In Linear
mode index 6 selects the FIR Brick kernel (magnitude step), not a min-phase cascade.

### 3.3 Two independent serial engines (chosen tradeoff — NOT a requirement)
Independent HP/LP Placement means the two filters do not share one scalar transfer function
in a single fixed domain. **Note (recorded per review):** this does *not* force two FFT
stages — HP∘LP over Placement is one frequency-dependent 2×2 L/R matrix
(`H_LL,H_LR,H_RL,H_RR`) that a single engine could apply at one engine-latency. We
**deliberately choose two serial engines** for a simpler kernel builder and lower DSP/
transcription risk (fits the verify-first method), accepting the doubled latency. The 2×2
matrix engine is the documented latency-halving alternative for a future version.

Two engines run **in series** in `@sample`; latencies **add**: each `6144` samples
(≈128 ms @48k / ≈64 ms @96k), both Linear ≈ `12288` samples (≈256 ms @48k / ≈128 ms @96k),
plus Mode-B lookahead. Accepted; PDC compensates (see §9).

## 4. Convolution engine (ported from Arthur)

Ported partitioned-convolution engine, instantiated **twice** (HP + LP):

| Constant | Value | Meaning |
|---|---|---|
| `P` | 2048 | partition / hop |
| `B` | 4096 | runtime FFT size |
| `BD` | 8192 | project kernel FFT size |
| `KMAX` | `BD/P = 4` | partitions |
| latency/engine | `BD/2 + P = 6144` samples | integer, PDC-compensated (see §5, §9) |

Per engine: kernel buffers `desbuf, ktime, win_k, Hspec`; runtime buffers
`fdl, fftw, yacc, tmpc, in, out, dry`; **two lanes** (A/B) mapped onto the engine's Placement
domain (see §7). Runtime convolution loop = Arthur's (`convolve_c`, FDL, overlap-save).
Kernel rebuilt only on signature change (see §8).

## 5. Kernel construction, symmetry & delay contract (resolves review P0-2)

Build (Arthur's method): sample the desired magnitude over `BD` bins (natural order,
mirrored above Nyquist) as a real zero-phase spectrum → `fft_ipermute` + `ifft` → `fftshift`
by `BD/2` → Kaiser window (fixed beta, §6) → scale `1/BD` → partition into `Hspec`.

**Symmetry axis is the integer center `BD/2 = 4096`, not `N-1`.** For a real, even,
zero-phase magnitude the `ifft` is real and circularly even about index 0
(`desbuf[j]=desbuf[BD-j]`); after `fftshift` by `half=BD/2`,
`ktime[half+d] = ktime[half-d] = desbuf[d]`. So the kernel is symmetric about index `4096`
with **integer group delay `BD/2 = 4096` samples** (the endpoint `ktime[0]` is unpaired but
the window ≈ 0 there). The identity-magnitude case is a single delta at `4096` — a pure
4096-sample delay, trivially linear phase.

**Contract:** group delay `= BD/2` (integer) per engine; reported PDC per engine `= BD/2 + P`
(runtime partition adds `P`). Verification tests (§10) assert **symmetry about `BD/2`**
(`k[4096+d] ≈ k[4096-d]`), unwrapped-phase residual ≈ 0, and impulse peak/centroid at the
predicted sample — never infer latency from constants alone.

## 6. Magnitude parity — EXACT digital V0.5 transfer (resolves P1 #5, #6)

Kernel bins come from the **exact digital transfer function of V0.5's SVF coefficients**, not
Arthur's analog ratio `r=f/fc`. V0.5 uses TPT/bilinear SVF with `g = tan(pi*fc_eff/srate)`
(verified in `hplp_coef`); the two diverge toward Nyquist. The Python oracle computes each
cascade section's digital response from its `a1,a2,a3,k,m0,m1,m2` coefficients (state-space /
`svf_response` at each bin frequency) and multiplies sections + the resonance bell:

```
mag(f) = Π_k svf_response(section_k, f) · svf_response(resonance_bell, f)
```

- Sections use `butter_q(k, N) = 1/(2·cos(pi·(2k+1)/(4N)))` (same as V0.5), HP or LP shape.
- Resonance bell: `glin = 1 + Resonance·5` (linear), `A = sqrt(glin)`, and the SVF `k`-term
  is `bk = 1/(2A)` → **effective `Q = 2A = 2·sqrt(glin)`, NOT a fixed 2** (Q equals 2 only at
  `glin=1`; it rises with Resonance). This is exactly `hplp_bell` (`bk=1/(2A)`,
  `m1=bk·(A²−1)`); the oracle must use this coupled `bk`, not a constant Q. `glin=1` → identity.
- `fc_eff = min(freq, srate·0.49)` (same Nyquist guard).
- **FIR Brick** → magnitude step (HP `f≥fc?1:0`, LP `f≤fc?1:0`), no resonance.

**Windowing changes the realized response**, so parity is stated as **measurable tolerances,
not "exact"** (fixed beta=14 makes them deterministic):

| Metric | Target (to pin numerically in the plan at 44.1/48/96k) |
|---|---|
| Passband ripple | ≤ small dB bound outside a documented transition neighborhood |
| Stopband attenuation | ≥ bound set by beta=14 (~−150 dB class) |
| Cutoff / peak-gain error | ≤ bound vs analytic `mag(fc)` |
| Resonance peak-freq / bandwidth error | ≤ bound vs analytic bell |
| Transition-width error | ≤ bound |

Parity is verified against the **digital** `mag(f)` (which equals V0.5 min-phase magnitude by
construction) → this is the Min/Linear A/B guarantee. **FIR Brick** additionally pins minimum
stopband attenuation, transition width, passband ripple, cutoff convention, and max ringing
for beta=14 at the tested sample rates.

## 7. Placement routing — full equations, delayed dry (resolves P1 #10)

Each engine encodes its Placement domain into two lanes, filters the active component(s), and
recombines with the **complementary component delayed by exactly the engine latency**
(`BD/2` at kernel + engine pipeline delay) so untouched signal nulls on recombination. For
the **second** serial engine, the first engine's untouched lane must enter at the same time
origin as its filtered lane. The plan pins encode / two-lane input / filtered lane /
delayed-dry lane / decode for all five placements:

- **Both** — lanes = (L, R) [or (M, S) if a dyn-stereo M/S context applies]; both filtered.
- **Mid** — M=(L+R)/2 filtered; S=(L−R)/2 delayed dry; decode L=M+S, R=M−S.
- **Side** — S filtered; M delayed dry; decode as above.
- **Left** — L filtered; R delayed dry.
- **Right** — R filtered; L delayed dry.

Routing tests (§10): impulse and random-signal prove the untouched component nulls after
compensating the exact latency (no channel/domain leakage).

### 7.1 Mode-B integration — sample-index contract (resolves Codex P1-8)

In Linear mode the downstream signal is already delayed by the HP/LP convolution, so Mode-B
must **not** add that latency again inside its own `bus_dry`. Let `n` index the original input
stream, `Dhp`/`Dlp` be the active linear-engine delays (each `BD/2+P`, or 0 if that filter is
Off/Min), `Dlin = Dhp + Dlp` (series), and `Lk` the global Mode-B lookahead. Per-sample:

```
x[n]              = original input sample
hp_out[n]         = LinearHP( x[n] )                    // delayed by Dhp
lp_out[n]         = LinearLP( hp_out[n] )               // total delay Dlin
static/ModeA[n]   = bells/shelves on lp_out[n]          // no added delay
modeB_detect[n]   = level of static/ModeA[n]            // detector on the CURRENT post-HP/LP sample (un-delayed RELATIVE to that stream)
bus_dry write[n]  = static/ModeA[n];  read = bus_dry[n − Lk]   // delay ONLY Lk, never Dlin again
correction[n]     = clamp/gain from modeB_detect[n−Lk] applied to the Lk-delayed bus
out[n]            = correction[n]
reported PDC      = MAXLAT   (constant; MAXLAT already accounts for max Dlin + Lk — §9)
```

The invariant: linear latency `Dlin` is applied **once** (by the engines); Mode-B adds only
`Lk` internally; the externally reported figure is the constant MAXLAT. Impulse tests (§10)
with one/two linear filters × {no Mode-B, Mode-B} catch any double-delay or off-by-one.

## 8. Kernel-rebuild & Off-engine policy (resolves P1 #8, #9)

- **Signature** = per-filter `slope, freq, resonance, placement` (compared **individually**,
  never Arthur's floating weighted `sig` — distinct params can collide). beta is fixed, so it
  never triggers a rebuild.
- **Click-safe rebuild:** a rebuild swaps `Hspec` while the FDL holds old-kernel history. Use
  a **dual-kernel delayed-domain crossfade**: build the new `Hspec` into a second slot, run
  both for one crossfade window (≈ one partition `P`), fade old→new, then release the old
  slot. Rebuilds are **coalesced/rate-limited** to at most once per crossfade window so rapid
  Freq/Resonance automation cannot rebuild every block (bounds audio-thread CPU).
- **Placement change** is a routing/domain change (old FDL/history is in the previous domain)
  → same dual-kernel crossfade, treating it as a topology change of the recombination lanes.
- **Off / dormant engines stay warm:** while the plugin is loaded, an Off engine keeps
  collecting input history (identity FDL fill) so Off→On and one-filter↔two-filter are
  seamless. This is consistent with the fixed-max-PDC choice (§9) and is the accepted CPU
  tradeoff for a mastering tool (documented; revisit at live test if CPU is an issue).

## 9. PDC / transition contract — fixed max-PDC while loaded (Dima's decision; resolves P0-3)

To avoid timeline jumps on Phase/Slope/Filter/bypass changes, the plugin holds a **constant
reported latency `MAXLAT` for its entire loaded lifetime** and internally delays every path
to `MAXLAT`:

- `MAXLAT` = worst-case linear latency (two engines = `2·(BD/2+P) = 12288`) **+** the
  Mode-B lookahead allowance, as a fixed value (independent of how many filters are actually
  On or the current Phase). The Min path, Off filters, and the dry/complementary lanes are
  all delayed to `MAXLAT`.
- Consequence: even Min-only use carries the full linear latency. This is the accepted cost
  of seamless switching (Dima chose seamless over low-latency). **Flag for live test:** if the
  constant latency in a Min-only session bothers Dima, revisit (e.g. constant only while
  Phase=Linear).
- `ext_tail_size = MAXLAT` (covers two serial FIR tails + lookahead) so offline renders keep
  the full post-ringing tail (resolves P1 #12). Transport stop/seek: rely on host flush;
  `@init` clears all large buffers.
- Master bypass: because latency is held constant and dry is delayed to `MAXLAT`, bypass does
  not jump. (V0.5's `pdc_delay=0`-on-bypass invariant is intentionally **replaced** by
  constant-latency for the linear build — noted as a deliberate deviation.)

## 10. Verification (Python oracle, stdlib-only; resolves P1 #13, P2 #1)

`partitioned == direct` alone is insufficient (shared shift/scaling bugs pass it). Add
permanent tests, and **separate fast analytic tests from a few golden full-kernel cases**
(use small power-of-two kernels for exhaustive partition bookkeeping; reserve `BD=8192` for
representative acceptance):

1. **Magnitude parity** — FIR-kernel magnitude (hand-written radix-2 FFT on `cmath`) ≈ digital
   `mag(f)` within §6 tolerances; digital `mag(f)` == V0.5 min-phase magnitude.
2. **Linear phase** — kernel symmetric about `BD/2` (`k[4096+d]≈k[4096-d]`); unwrapped-phase
   residual ≈ 0.
3. **Identity / all-pass** — unit gain and exact delay.
4. **Unit impulse** — full impulse response; exact peak/centroid sample = predicted PDC.
5. **DC & Nyquist bin** handling correct.
6. **Scaling** — `1/BD` (kernel IFFT) and `1/B` (runtime IFFT) checked **independently**.
7. **Partitioned == direct** — on short signals, arbitrary host block sizes, and a hop
   spanning a block boundary.
8. **Routing null** — every Placement: untouched component nulls after latency compensation.
9. **JSFX source guards** — `fft_permute`/`fft_ipermute` order; per-call **page-boundary**
   assertions (§11); Off, FIR Brick, and Mode-B integration paths.

Method unchanged: oracle green FIRST → line-by-line transcription into `JSFX/RCBitNova V0.6`
→ live-verify with Dima → tag `rcbitnova-v0.6`.

## 11. Memory — 65,536-page-safe layout (resolves P0-1)

Contiguity after `hplp_cf` guarantees disjointness but **not** JSFX FFT page-safety: every
`fft`/`ifft`/`convolve_c` span must stay inside one 65,536-item page. (There is **no** hard
total-page cap — JSFX local memory is large; the constraint is strictly per-call, so padding
to align is fine and does not "overflow a budget.") But the footprint is tight enough that
placement is not automatic: one engine's Arthur-style allocation is ≈`229,736` words
(`desbuf 16384 + ktime 8192 + win_k 8192 + Hspec 32768 + fdlA 32768 + fdlB 32768 + fftw 8192
+ yacc 8192 + tmpc 8192 + inA 4096 + inB 4096 + outA 16384 + outB 16384 + dryA 16384 +
dryB 16384`; drop `real_db` display buffer), ×2 engines ≈`459,472` words ≈ 7 pages.

**This spec pins the layout rule (not deferred to the plan):** every buffer that is passed to
`fft`/`ifft`/`fft_permute`/`convolve_c` — `desbuf`(BD), each `Hspec` partition (span `B*2`),
each `fdl` partition (span `B*2`), `fftw`/`yacc`/`tmpc` (span `B*2`) — must be placed so its
whole span lies within a single page. Because each such span is ≤ `16384` and pages are
`65536`, aligning each FFT-touched block's **base** to a multiple of its own span (or to a
page start) is sufficient; pure ring buffers never touched by an FFT call (`inA/inB`,
`outA/outB`, `dryA/dryB`) have no page constraint and fill the gaps. The plan carries the
concrete base-offset table + a per-call assertion
`floor(start/65536) == floor((start+count-1)/65536)` for both engines, plus the `freembuf`
boundary and a `__memtop()` guard. Ref: <https://www.reaper.fm/sdk/js/advfunc.php>.

## 12. Sliders / memory / UI / pinned open items (resolves P2 #2)

- **Phase slider** — `slider140:0<0,1,1{Min,Linear}>Phase` (global, default `Min`). Fresh
  bank past the HP/LP block (131–138), leaving 139 as a gap per the banked-numbering
  convention. Automatable; Phase/Slope changes are click-safe via the §3.1/§8 crossfade, and
  latency is constant so there is no host renegotiation.
- **Slope enum** HP/LP: add `FIR Brick` (index 6), range 0–6. Brick-in-Min = Off.
- **beta** — fixed `14` (no slider). Deterministic Min/Linear parity.
- **Freq / Resonance** — continuous, automatable; changes coalesced with the dual-kernel
  crossfade (§8), so real-time sweeps are click-safe but rate-limited.
- **Memory** — all linear engine buffers allocate after `hplp_cf` under the §11 page-aware
  layout. Fable to run a memory-disjointness + page-boundary source test.
- **UI** — minimal for now; explicit filter-enable and the FFT-analyzer GUI remain separate
  UX debt.

## 13. Non-goals (V0.6)

- No linear phase for bells/shelves (LTI-capable but deferred — §2).
- No linear phase for Mode A / Mode B (impossible with bit guarantee — §2).
- No 2×2 matrix engine (documented latency-halving alternative — §3.3).
- No new GUI / analyzer; no explicit filter-enable redesign; no second HP/LP pair.

## 14. Safety / invariants

- V0.5 min-phase path byte-identical when `Phase = Min` (except the intentional constant-
  latency deviation of §9).
- Bit-accuracy claim untouched: HP/LP are pure filters (no gain stage); linearizing their
  phase does not touch the bit claim.
- New file `JSFX/RCBitNova V0.6` (copy V0.5); V0.5 stays frozen + tagged.
- Python DSP mirror remains THE ORACLE (pure stdlib); live REAPER confirms transcription.

## 15. As-shipped outcome, known limitations & deferred to V0.7 (2026-07-25, tagged)

**Shipped as tagged `rcbitnova-v0.6`.** Live-verified: Min == V0.5; Linear HP/LP + FIR
Brick work; pass/stopband parity 0.002 dB; Mid/Side/Left/Right route cleanly; Mode-B works
in Linear; high-cut FIR Brick reaches −150 dB within ~600 Hz near Nyquist (ReaFIR-class, at
BD=8192 ⇒ ~64 ms/engine, lower latency than ReaFIR@32768). Fable final review: bit-accuracy
INTACT, no P0.

**Implementation deviations from the earlier sections (intentional, live-driven):**
- **Kernel magnitude via impulse-FFT, not analytic (§6).** `lpk_build` builds the magnitude
  from the FFT of the ACTUAL min-phase cascade's impulse response (reuses `hplp_coef`/
  `hplp_bell`), not the analytic `svf_response`. Proven equivalent to the analytic build in
  the passband/transition (oracle test `test_impulse_fft_kernel_matches_analytic_*`, <0.1 dB).
- **PDC policy (c), not constant-MAXLAT (§9).** Owner decided no seamless Min↔Linear switch
  during playback is needed. So Min stays zero-latency; Linear is constant (both engines
  always run); only the deliberate Min↔Linear switch changes latency. Warm engines + the
  Phase-toggle crossfade (§3.1) are therefore **not implemented** (not needed).

**Known limitation (inherent, accepted):** a fixed-length linear-phase FIR (BD=8192,
~11.7 Hz/bin @96k) cannot resolve a steep sub-cutoff transition at very low frequencies, so
Linear HP below ~50 Hz has **limited deep-stopband rejection** (documented + tested,
`test_linear_phase_lowfreq_resolution_limit_is_method_independent`). This is inherent to
linear phase — identical for the analytic and impulse-FFT builds, same as ReaFIR/Pro-Q — NOT
a bug. High-frequency cuts are unaffected (ample bin resolution near Nyquist). **Guidance:
use Min phase for deep sub-bass low-cut; Linear for tonal EQ and high-cut brickwall.**

**Deferred to V0.7:**
- Click-safe dual-kernel **crossfade** on Freq/Resonance/Slope change in Linear (spec §8;
  currently an in-place `Hspec` swap → possible click on a live knob sweep; fine for
  set-and-play mastering).
- Selectable **resolution** (BD 8192 ↔ 32768) — a "high-resolution" mode that improves
  linear-phase deep-low-cut at 4× latency. Not needed for high-cut (8192 already −150 dB).
- Placement-toggle transient (no crossfade on live placement change) — polish.
- Update spec §9 prose (still describes constant-MAXLAT); superseded by policy (c) here.
