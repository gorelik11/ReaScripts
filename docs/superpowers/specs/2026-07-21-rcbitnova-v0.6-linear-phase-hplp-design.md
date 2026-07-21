# RCBitNova V0.6 — Linear-Phase HP/LP + FIR Brick — Design Spec

**Date:** 2026-07-21 (rev 2 — folds in Fable weakness review `…-weaknesses.md`)
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
- `Phase = Min` → V0.5 path (`hplp_run`), byte-identical to V0.5.
- `Phase = Linear` → `hplp_run` bypassed; HP and LP each run an independent
  partitioned-convolution engine on their own Placement domain.

### 3.2 Slope enum extension
HP (`slider131`) / LP (`slider135`) enum grows: `Off / 12 / 24 / 36 / 48 / 96 / FIR Brick`
(index 6). Range 0–6. **FIR Brick** is active only in Linear; in Min it is **treated as Off**
(Brick is a Linear-only concept; stock enum sliders cannot grey out without custom UI). The
label is `FIR Brick`, deliberately distinct from Mode-B "Brick" (a hard bit ceiling) to
avoid confusing a finite-FIR slope with a literal-guarantee limiter.

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
- Resonance bell: fixed `Q=2`, `glin = 1 + Resonance·5` (linear), identical to `hplp_bell`;
  `glin=1` → identity.
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
`fft`/`ifft`/`convolve_c` span must stay inside one 65,536-item page. The plan pins a
**page-aware layout** (not just a disjointness test): for every actual FFT/convolution call
assert `floor(start/65536) == floor((start+count-1)/65536)`, covering all per-lane buffers
(`fdlA/fdlB`, `inA/inB`, `outA/outB`, `dryA/dryB`), `Hspec` partitions, `fftw/yacc/tmpc`,
padding, the final high-water mark, the `freembuf` boundary, and a `__memtop()` guard. Two
engines ⇒ do this for both. Ref: <https://www.reaper.fm/sdk/js/advfunc.php>.

## 12. Sliders / memory / UI / pinned open items (resolves P2 #2)

- **Phase slider** — global, fresh bank; default `Min` (0). Automatable, but Phase/Slope are
  **topology changes** (not click-continuous); latency is constant so no host renegotiation.
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
