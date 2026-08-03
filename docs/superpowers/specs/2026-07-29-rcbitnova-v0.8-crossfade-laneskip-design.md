# RCBitNova V0.8 — Click-Safe Transitions + Lane-B Skip — Design Spec

**Date:** 2026-07-29 (**rev 2** — folds the weakness review
`…-v0.8-crossfade-laneskip-weaknesses.md`, the owner's live evidence, and the patterns found in
Arthur's `Fable Eq Mix` / `Fable Eq Dynamic` / `Fable smart_eq_techiv_5`)
**Branch:** `rcbitnova` (worktree `~/projects/reascripts/.claude/worktrees/rcbitnova/`)
**Base:** V0.7 (frozen, tag `rcbitnova-v0.7`, commit `90a72b3`) — new file `JSFX/RCBitNova V0.8`
**Predecessor specs:** `…-v0.6-linear-phase-hplp-design.md` §15, `…-v0.7-hires-linear-phase-design.md` §10

---

## 1. Goal

Remove the audible artefacts that remain when parameters change **while audio is playing**, and
halve the convolution cost of selective placement:

1. **Per-sample kernel crossfade** — a kernel rebuild currently swaps `Hspec` in place, so the
   output jumps at a hop boundary.
2. **Topology-change ramp** — Placement, Phase and Resolution changes hard-switch routing or
   geometry, which steps the waveform.
3. **Lane-B skip** — in selective placement lane B convolves a permanently-zero input; skipping
   it halves that engine's convolution work.

## 2. Evidence: how bad is it, really (measured, not assumed)

The owner reported not hearing clicks in normal use, so the artefact was quantified in the
oracle before committing to a fix. Metric: worst curvature anomaly of the output in the
transition window, dB relative to signal peak, probed at frequencies where the two kernels
actually differ (a passband probe shows nothing — both kernels are identical there).

| Event | Artefact |
|---|---|
| Slow Freq turn (0.5–2 Hz per 100 ms rebuild) | −51 … −38 dB — **inaudible under programme** |
| Fast Freq sweep (10–25 Hz per rebuild) | −23 … −12.5 dB — audible zipper |
| **Slope 24 → 48 under audio** | **+6.4 dB** — a full-amplitude step, i.e. a bang |
| **Resonance 0 → 1 under audio** | −2.6 dB — loud |

Both observations are therefore correct: the artefact is real and severe on **discrete
switches** and fast sweeps, and genuinely inaudible on the slow turns the owner tested. Physics
check: at 60 Hz an HP-100 Hz kernel passes 0.343 at 24 dB/oct and 0.0125 at 48 dB/oct — an
instant swap drops that component to ~4 % of its value mid-waveform.

**Independent corroboration.** Arthur hit the same class in his own plugins and fixed it the
same way: `Fable Eq Mix` — *"RAMPA PRZY ZMIANIE M/S TARGET … Teraz 10 ms rampy … W stanie
ustalonym waga jest DOKŁADNIE 1 albo 0 i blend jest POMIJANY — tor bit w bit"*; `Fable Eq
Dynamic` — a 15 ms ramp on Both↔Mid/Side with *"końce rampy dokładne (licznik CAŁKOWITY)"*;
`smart_eq_techiv_5` — a 10 ms fade-in after a flush. **His discipline is adopted here: outside a
transition the blend is skipped entirely, so the steady-state path stays bit-identical.**

## 3. Why per-sample crossfade, not per-hop kernel blending

rev 1 proposed blending the kernel toward the target once per hop (8 hops). Measured against the
same transitions:

| Transition | instant (V0.7) | 8-hop kernel blend | **per-sample output crossfade** |
|---|---|---|---|
| sweep 100→110 Hz 24 dB/oct | −24.5 dB | −34.9 dB | **−96.8 dB** |
| 12 → 96 dB/oct | −1.2 dB | −18.4 dB | **−87.1 dB** |
| Off → FIR Brick | −4.6 dB | −18.5 dB | **−73.9 dB** |

The per-hop blend only buys 10–17 dB and leaves −18 dB artefacts on discrete switches — audible,
so it cannot be called click-safe (the review's P0, confirmed numerically). Only the per-sample
crossfade reaches inaudibility.

rev 1 also justified the per-hop blend with a CPU estimate that the review correctly called
dimensionally wrong: the blend loop touches `KMAX*PB2` words (131072 at High) in **interpreted
EEL**, while `convolve_c` is a **native** primitive over `PB2`. The blend was therefore likely
*more* expensive than the convolution it replaced. The per-sample crossfade uses native
primitives only. **No CPU estimate is given in this spec — §8 benchmarks it live instead.**

## 4. Kernel crossfade (per-sample, dual convolution)

**Buffers.** `lpk_build` writes the new kernel into **`Hspec2`** (pinned at `lp_off[eng*16+15]`,
the free slot V0.7 left). `Hspec` remains the active kernel.

**Runtime, per lane, while fading:** the FDL is shared (same input history, two kernels):

```
yacc = Σ FDL[k] · Hspec [k];  ifft;  write  P samples to the out ring  with weight (1-α)
yacc = Σ FDL[k] · Hspec2[k];  ifft;  add    P samples to the out ring  with weight  α
```

No extra buffers: the second pass mixes into what the first wrote. Cost during a fade is 2×
convolution on that lane, bounded by what V0.7 already does in Both placement today.

**α is per sample**, indexed by absolute fade position, so both lanes and both engines agree:
`fade_pos` advances by `P` per hop; within a block, `α_i = clamp((fade_pos + i) / fade_len, 0, 1)`.

**`fade_len` is defined in time, not hops:** `fade_len = floor(0.05 · srate)` (50 ms) — sample-rate
independent, unlike rev 1's 8 hops (which were 171 ms @96k but 341 ms @48k; the review's P1).

**Fades can never overlap.** V0.7 rate-limits rebuilds to ≥100 ms apart and `fade_len` is 50 ms,
so a new target cannot arrive mid-fade. All retarget logic the review asked about is therefore
*absent by construction*, not handled. As a defensive guard, if a build is nonetheless requested
while `fading`, it **snaps** (copies straight to `Hspec`) rather than corrupting the fade.

**Completion:** when `fade_pos ≥ fade_len`, `memcpy(Hspec2 → Hspec)` and `fading = 0`, so the
active kernel ends bit-identical to the built one and the steady-state path returns to a single
convolution — **byte-identical to V0.7's hot path** (Arthur's bit-exactness discipline).

**Snap instead of fade** (no fade) when: the engine has no valid kernel yet (`built == 0`, V0.7's
existing flag), after a geometry (Resolution) change, or while `Phase = Min` — in Min the engines
do not run, so a fade could never advance and would leave stale state (the review's P1). Any
`lp_relayout` clears fade state before touching memory, so a fade can never point into moved or
cleared buffers.

## 5. Topology-change ramp (Placement / Phase / Resolution)

A kernel crossfade cannot smooth these: they change *which signal* a lane carries (Placement) or
the engine geometry itself (Phase, Resolution). Both leave the step the owner would hear.

**Mechanism — a short global dip**, the pattern Arthur uses for his flush/gap case: a
**10 ms fade-out → apply the change → 10 ms fade-in**, applied to `spl0/spl1` at the end of the
HP/LP section. One shared envelope covers all three triggers.

Rationale: these are discrete, manual UI actions, so a 20 ms dip is imperceptible as a dip but
decisively better than a bang. A true dual-routing crossfade (Arthur's `ms_wM/ms_wS` weight
blend) is possible in his min-phase EQ because it computes both domains anyway; in a
convolution engine it would need a second engine pass and new state, so it is **deferred to a
possible V0.9** rather than risked here.

**Bit-exactness:** the envelope is exactly `1.0` outside a transition and the multiply is
**skipped entirely** when idle, so the steady-state path is untouched. Counters are integer so
the endpoints land exactly on 0 and 1.

This also fixes the transitions V0.6/V0.7 documented as "deliberate topology change, may jump" —
Phase Min↔Linear and Resolution Normal↔High now dip rather than bang.

## 6. Lane-B skip — provable zero-run skip

**Rule.** Per lane, count consecutive **exactly zero** input samples, saturating:
`zcnt = (x == 0) ? min(zcnt + 1, SKIP_AFTER) : 0` (saturation per the review's P2). With
`SKIP_AFTER = BD + B`, once the counter is saturated the lane's whole hop is skipped: no input
FFT, no `KMAX` `convolve_c`, no inverse FFT; `P` zeros are written to its out ring. Its input
ring is still written every sample.

**Exactness.** After `BD + B` zero inputs every one of the `KMAX` FDL slots was filled from an
all-zero block, so the convolution sum is exactly zero. The skip reproduces the value the full
path would compute — it is not an approximation. Resuming is artefact-free because the skip is
only entered from, and resumed into, a genuinely zero FDL; nothing stale is left behind.

**Engine-level `fdl_wr` (review P1).** V0.7 advances `fdl_wr` once per hop *outside* the lane
blocks, and V0.8 keeps it there: the write index advances every hop regardless of either lane's
skip decision. The invariant a skipped lane relies on is that its slots already hold zeros, not
that the ring stopped rotating. §8 tests all four run/skip combinations.

**Scope of the saving (review P1).** Skipping lane B removes ~half of *that engine's steady-state
convolution work*. It does not touch lane A, the per-sample rings, routing, rebuilds, the other
engine, or the static EQ and dynamics — so whole-plugin CPU falls by less than half.

**Warm-up (review P1).** The skip engages only after `BD + B` exactly-zero samples: 12288 samples
(≈256 ms @48k, 128 ms @96k) at Normal, 36864 (≈768 ms @48k, 384 ms @96k) at High. A CPU
comparison taken sooner will show no saving. §8's live test waits longer than that.

**Anti-denormal interaction (review P2).** The skip depends on selective placement passing a
literal `0` into lane B. The global anti-denormal offset makes silent audio `±2^-100`, not zero,
so lane A never trips during silence — by design. A source-level test asserts lane B is still
exactly zero after all anti-denormal handling, so a later refactor cannot silently disable the
optimisation.

## 7. Memory

`Hspec2` is required at every resolution:

| | V0.7 | V0.8 |
|---|---|---|
| Normal engine span | 229376 | **262144** (exactly 4 pages) |
| High engine span | 655360 | **786432** (exactly 12 pages) |
| Fallback-16384 span | 360448 | 425984 |
| Packed top, Normal+Normal | 458752 | **524288** (+0.5 MB) |
| Packed top, High+Normal / Normal+High | 884736 / 917504 | 1048576 |
| Packed top, High+High | 1310720 | 1572864 |

V0.7's "Normal+Normal is byte-identical to V0.6's footprint" property is **deliberately given
up** (+512 KB); the *hi-res* zero-cost property is unaffected. `Hspec2` is never passed to
`fft`/`ifft`/`convolve_c` (the FFT happens in `fftw`; `lpk_build` `memcpy`s the result in), so it
carries no page-crossing constraint of its own — it is nevertheless aligned exactly like `Hspec`
so a future change that convolves straight from it stays legal.

**State storage, pinned (review P1):** `lp_off[eng*16+15] = Hspec2`; `lp_rt[eng*8+6] = zcntA`,
`lp_rt[eng*8+7] = zcntB` (V0.7 left both free); a new `lp_fs + eng*4` block holds
`fading, fade_pos, fade_len, built`. All are reset by `lp_rt_reset` / `lp_relayout`, on first
load, on Resolution change, and on any forced `built = 0`.

## 8. Verification

**Oracle additions** (mirroring the JSFX so behaviour is testable outside REAPER):

- `partitioned_convolve_skip(sig, ker, P, skip_after) -> (out, skipped_hops, state)` — the same
  engine with the zero-run skip, returning the skipped-hop count and the internal state (FDL,
  `fdl_wr`, ring positions, counters) so equivalence can be checked on **state**, not only output.
- `partitioned_convolve_xfade(sig, ker_a, ker_b, P, switch_hop, fade_len) -> out` — an
  **integrated, stateful** engine that changes kernel *under a running signal* with the per-sample
  dual-convolution crossfade (the review's P1: a vector-only fade helper cannot catch a
  transcription that fades one hop early, or only in the non-skip branch).

**Tests:**

1. **Crossfade kills the artefact** — reproduce §2/§3's worst cases (Slope 24→48, Resonance 0→1,
   Off→Brick, 100→110 Hz) and assert the curvature anomaly is **below −60 dB** relative to peak,
   versus the instant-swap baseline which must be shown to exceed it (so the test proves the fix,
   not merely that some number is small).
2. **Steady state is bit-exact** — with no transition in flight, `partitioned_convolve_xfade`
   output is **bit-identical** to plain `partitioned_convolve` (Arthur's discipline, machine-checked).
3. **Fade lands exactly** — after `fade_len` samples the active kernel equals the target
   bit-for-bit and only one convolution per hop is performed thereafter.
4. **Skip is bit-exact** — a lane zeroed longer than `BD + B` then re-excited produces output
   **bit-identical** to the non-skipping engine, and internal state (FDL, `fdl_wr`, rings,
   counters) matches after resume.
5. **Skip actually fires** — `skipped_hops > 0` and the output is exactly `0.0` while skipping.
6. **Hop-alignment coverage (review P1)** — parameterise the zero-run onset over phases
   `0, 1, P-1` and run lengths `BD+B-1`, `BD+B`, `BD+B+P`: no premature skip, and the skip does
   eventually engage.
7. **All four run/skip combinations** (A/B × run/skip) with resume at different hops, each
   bit-compared against the full two-lane engine.
8. **Memory** — spans, packed tops, page-safety for all four packings per §7.

**Live (REAPER, with the owner):**
1. Regression: `Phase = Min` unchanged; steady-state Linear unchanged from V0.7 (no knob motion).
2. **The cases that provably banged in §2**: switch Slope 24↔48 and Resonance 0↔1 **while
   playing** — before, a bang; after, nothing. Then a fast Freq sweep — no zipper.
3. **Topology ramp**: toggle Placement Both↔Mid↔Side, Phase Min↔Linear, Resolution Normal↔High
   under audio — a clean short dip, no bang.
4. **Lane-B skip CPU**: `HP Placement = Mid` at High, waiting **longer than `(BD+B)/srate`**
   (≈0.4 s @96k, ≈0.8 s @48k) before reading the meter; expect roughly half of that engine's
   convolution work to disappear, audibly identical.
5. **Benchmarks, not estimates (review P1)**: report steady CPU *and* peak block time at 44.1 /
   48 / 96 / 192 kHz, with a small device block, for: Normal vs High; Both vs selective after the
   skip engages; one and two engines fading; and a rapid sweep that rebuilds every 100 ms.
6. Offline render still carries the full tail; PDC unchanged.

## 9. Invariants preserved

- **Bit-accuracy INTACT**: no new gain stage. Crossfade and ramp weights are ordinary float DSP,
  and both are **skipped entirely** when idle, so the steady-state path is byte-identical to V0.7.
  No `log`/`dB`/`pow(10)` anywhere in the DSP path.
- **V0.7 and earlier stay frozen.** New file `JSFX/RCBitNova V0.8` (copy of V0.7);
  `rcbitnova-v0.7` remains the fallback tag.
- Min path byte-identical; instance-local memory only; per-engine tables keep their V0.7 roles.
- The Python DSP mirror remains THE ORACLE; live REAPER confirms transcription.

## 10. Out of scope (deferred)

- **True dual-routing placement crossfade** (instead of the dip) — needs a second engine pass;
  possible V0.9.
- Lane-A skip during silence (blocked by the anti-denormal offset, by design).
- Any change to resolutions, geometry, PDC, or the min-phase filter path.
