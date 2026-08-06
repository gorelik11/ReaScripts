# RCBitNova V0.8 — Per-Sample Kernel Crossfade + Lane-B Skip — Design Spec

**Date:** 2026-07-29 (**rev 3** — rev 2 folded the first weakness review and Arthur's patterns;
rev 3 folds the rev-2 review `…-v0.8-crossfade-laneskip-weaknesses.md`: the topology ramp is
**removed from V0.8** because a 20 ms dip cannot cover the engine's own timing, `Hspec2` is
corrected to a live `convolve_c` buffer, rebuilds queue instead of snapping, one validity flag,
honest pass counts, pinned hop ordering)
**Branch:** `rcbitnova` (worktree `~/projects/reascripts/.claude/worktrees/rcbitnova/`)
**Base:** V0.7 (frozen, tag `rcbitnova-v0.7`, commit `90a72b3`) — new file `JSFX/RCBitNova V0.8`

---

## 1. Goal

Two things, both inside the linear-phase engines:

1. **Per-sample kernel crossfade** — a kernel rebuild currently swaps `Hspec` in place, so the
   output steps at a hop boundary. Measured: a Slope 24→48 switch under audio is a
   **full-amplitude step**.
2. **Lane-B skip** — in selective placement lane B convolves a permanently-zero input; skipping
   it halves that engine's convolution work.

**Explicitly NOT in V0.8:** transitions for Placement / Phase / Resolution. See §9.

## 2. Evidence: the artefact is real, and so is the owner's ear

The owner reported hearing no clicks, so the artefact was quantified before committing to a fix.
Metric: worst curvature anomaly in the transition window, dB relative to signal peak, probed
where the two kernels actually differ (a passband probe shows nothing — both kernels agree there).

| Event | Artefact |
|---|---|
| Slow Freq turn (0.5–2 Hz per 100 ms rebuild) | −51 … −38 dB — **inaudible under programme** |
| Fast Freq sweep (10–25 Hz per rebuild) | −23 … −12.5 dB — audible zipper |
| **Slope 24 → 48 under audio** | **+6.4 dB** — a full-amplitude step |
| **Resonance 0 → 1 under audio** | −2.6 dB — loud |

Both observations hold: severe on **discrete switches** and fast sweeps, genuinely inaudible on
the slow turns that were tested. Physics check: at 60 Hz an HP-100 Hz kernel passes 0.343 at
24 dB/oct and 0.0125 at 48 dB/oct — an instant swap drops that component to ~4 % mid-waveform.

**Independent corroboration.** Arthur solved the same class in his own plugins: `Fable Eq Mix`
— *"RAMPA PRZY ZMIANIE M/S TARGET … 10 ms rampy … W stanie ustalonym waga jest DOKŁADNIE 1 albo 0
i blend jest POMIJANY — tor bit w bit"*; `Fable Eq Dynamic` — 15 ms with *"końce rampy dokładne
(licznik CAŁKOWITY)"*; `smart_eq_techiv_5` — 10 ms fade-in after a flush. **His discipline is
adopted: outside a transition the blend is skipped entirely, so the steady-state path stays
bit-identical.**

## 3. Why per-sample crossfade, not per-hop kernel blending

rev 1 proposed blending the kernel once per hop (8 hops). Measured on the same transitions:

| Transition | instant (V0.7) | 8-hop kernel blend | **per-sample output crossfade** |
|---|---|---|---|
| sweep 100→110 Hz 24 dB/oct | −24.5 dB | −34.9 dB | **−96.8 dB** |
| 12 → 96 dB/oct | −1.2 dB | −18.4 dB | **−87.1 dB** |
| Off → FIR Brick | −4.6 dB | −18.5 dB | **−73.9 dB** |

The per-hop blend buys only 10–17 dB and leaves −18 dB on discrete switches — audible, so it
cannot be called click-safe. rev 1 also justified it with a CPU estimate that was dimensionally
wrong (an interpreted EEL blend over `KMAX*PB2` versus a native `convolve_c` over `PB2`), so the
blend was likely *more* expensive than the convolution it replaced. **No CPU estimate appears in
this spec — §8 benchmarks it live.**

## 4. Kernel crossfade (per-sample, dual convolution)

**Buffers.** `lpk_build` writes the new kernel into **`Hspec2`** (pinned at `lp_off[eng*16+15]`,
the slot V0.7 left free). `Hspec` stays the active kernel.

**Runtime, per lane, while fading** — the FDL is shared (same input history, two kernels):

```
pass 1:  for k in 0..KMAX-1:  tmpc = FDL[k];  convolve_c(tmpc, Hspec  + k*PB2, B);  yacc += tmpc
         ifft(yacc);  out[ow+i]  = yacc[(P+i)*2] * sc * (1 - alpha_i)
pass 2:  for k in 0..KMAX-1:  tmpc = FDL[k];  convolve_c(tmpc, Hspec2 + k*PB2, B);  yacc += tmpc
         ifft(yacc);  out[ow+i] += yacc[(P+i)*2] * sc * alpha_i
```

No extra buffers: pass 2 mixes into what pass 1 wrote. **`Hspec2` is therefore a live
`convolve_c` operand** — see §7, this is the correction of a rev-2 error.

**α is per sample**, indexed by absolute fade position so both lanes and both engines agree:
`fade_pos` advances by `P` per hop; within a block `alpha_i = min((fade_pos + i) / fade_len, 1)`.

**`fade_len` is defined in time:** `fade_len = floor(0.05 · srate)` (50 ms) — sample-rate
independent, unlike rev 1's 8 hops (171 ms @96k but 341 ms @48k).

**Hop execution order is pinned** (rev-2 review P2 — `fade_len` is not a multiple of `P`, e.g.
2400 @48k, 2205 @44.1k, so the final hop carries a prefix with `α<1` and a suffix clamped to 1):

```
per hop, per engine:
  1. write this hop's input block into the FDL slot (unchanged from V0.7)
  2. for each lane (A, then B): if fading -> pass 1 + pass 2 (above), else single pass
     - both lanes use the SAME alpha values for the same output positions
  3. after BOTH lanes are done:  fade_pos += P
  4. if fade_pos >= fade_len:  memcpy(Hspec2 -> Hspec);  fading = 0
  5. advance fdl_wr (engine-level, once per hop, regardless of lane skips)
```

Completion therefore never happens between lane A and lane B, and the first hop that uses only
`Hspec` is the one after the hop in which `fade_pos` reached `fade_len`.

**Completion is exact:** `memcpy(Hspec2 → Hspec)` makes the active kernel bit-identical to the
built one, and `fading = 0` returns the hot path to a single convolution — **byte-identical to
V0.7's** (Arthur's bit-exactness discipline).

**Snap instead of fade** (no fade) when the engine has no valid kernel (`valid == 0`), after a
Resolution/relayout, or while `Phase = Min` — in Min the engines do not run, so a fade could
never advance and would leave stale state. `lp_relayout` clears fade state before touching
memory, so a fade can never point into moved or cleared buffers.

**Rebuild while fading: queue, never snap (rev-2 review P1).** rev 2 argued fades cannot overlap
because the rebuild limiter (100 ms) exceeds `fade_len` (50 ms) — but the limiter measures
**wall time** (`time_precise()`) while the fade measures **audio time**, and under an overrun
those diverge. V0.8 therefore does not rely on that: `@block` **only commits a rebuild when
`fading == 0`**. A dirty target simply stays queued until the current fade completes, so an
instantaneous kernel switch is structurally impossible rather than merely improbable.

**One validity flag (rev-2 review P1).** V0.7's `hp_built`/`lp_built` globals are replaced by a
single per-engine `valid` in `lp_fs`, used for *both* the rate-limiter bypass and the fade/snap
decision, so the two can never disagree. Order per build: build into `Hspec2` → if `valid == 0`
copy to `Hspec` and stay snapped, else start the fade → set `valid = 1` → clear dirty → stamp
the rebuild time.

## 5. Lane-B skip — provable zero-run skip

**Rule.** Per lane, count consecutive **exactly zero** input samples, saturating:
`zcnt = (x == 0) ? min(zcnt + 1, SKIP_AFTER) : 0`. With `SKIP_AFTER = BD + B`, a saturated
counter skips that lane's whole hop: no input FFT, no `KMAX` `convolve_c`, no inverse FFT;
`P` zeros go to its out ring. The input ring is still written every sample.

**Exactness.** After `BD + B` zero inputs every one of the `KMAX` FDL slots was filled from an
all-zero block, so the convolution sum is exactly zero — the skip reproduces the value the full
path would compute. Resuming is artefact-free because the skip is only entered from, and resumed
into, a genuinely zero FDL.

**Engine-level `fdl_wr`.** V0.7 advances it once per hop outside the lane blocks; V0.8 keeps that
(step 5 above). A skipped lane relies on its slots already holding zeros, not on the ring pausing.

**Scope of the saving.** Roughly half of *that engine's steady-state convolution work*. Lane A,
the per-sample rings, routing, rebuilds, the other engine, and the static EQ/dynamics are
untouched — whole-plugin CPU falls by less than half.

**Warm-up.** The skip engages only after `BD + B` exactly-zero samples: 12288 (≈256 ms @48k,
128 ms @96k) at Normal, 36864 (≈768 ms @48k, 384 ms @96k) at High. A CPU reading taken sooner
shows no saving.

**Anti-denormal interaction.** The skip depends on selective placement passing a literal `0` into
lane B; the global anti-denormal offset makes silent audio `±2^-100`, so lane A never trips
during silence — by design. A source test asserts lane B is still exactly zero after all
anti-denormal handling.

## 6. CPU, stated honestly (rev-2 review P1)

Pass counts per hop per engine (one `convolve_c` per partition per pass):

| State | Both placement | Selective placement (after skip engages) |
|---|---|---|
| V0.7 steady | 2 lanes × KMAX | 2 lanes × KMAX |
| V0.8 steady | 2 × KMAX (unchanged) | **1 × KMAX** (halved) |
| V0.8 fading | **4 × KMAX** (2 lanes × 2 kernels) | 2 × KMAX |

So a fade in Both placement is **2× V0.7's Both work**, not "bounded by it" — the rev-2 wording
was too generous. Also, "native primitives only" was incomplete: `convolve_c`, `fft` and `ifft`
are native, but the per-partition accumulation and the new per-sample weighting are interpreted
EEL loops. §8 therefore benchmarks rather than estimates, and includes **peak block time and
xrun behaviour**, because a 2× transient at High+High is exactly where an average-CPU meter hides
a peak-block failure.

## 7. Memory

**Correction of a rev-2 error (review P0):** rev 2 claimed `Hspec2` is never passed to
`convolve_c` and therefore needs no page-crossing guarantee. The §4 runtime passes it to
`convolve_c` on every fading hop. `Hspec2` is therefore **FFT-touched**: marked as such in
`lp_engine_buffers`, aligned per-partition to `PB2` exactly like `Hspec`, and page-tested in
every layout. Getting this wrong is the silent-corruption class V0.7's `fft(32768)` gate exposed.

Verified layout (marking `Hspec2` FFT-touched adds **zero** padding — every preceding block is
already a `PB2` multiple):

| | V0.7 | V0.8 |
|---|---|---|
| Normal engine span | 229376 | **262144** (exactly 4 pages) |
| High engine span | 655360 | **786432** (exactly 12 pages) |
| Fallback-16384 span | 360448 | 425984 |
| Packed top, Normal+Normal | 458752 | **524288** (4.00 MB) |
| Packed top, High+Normal / Normal+High | 884736 / 917504 | 1048576 (8.00 MB) |
| Packed top, High+High | 1310720 | 1572864 (12.00 MB) |

V0.7's "Normal+Normal is byte-identical to V0.6's footprint" property is **deliberately given up**
(+512 KB); the *hi-res* zero-cost property is unaffected.

**State storage, pinned:** `lp_off[eng*16+15] = Hspec2`; `lp_rt[eng*8+6] = zcntA`,
`lp_rt[eng*8+7] = zcntB` (both free in V0.7); new `lp_fs + eng*4` = `fading, fade_pos, fade_len,
valid`. All reset by `lp_rt_reset` / `lp_relayout`, on first load, on Resolution change, and
whenever `valid` is forced to 0.

## 8. Verification

**Oracle additions** (mirroring the JSFX so behaviour is testable outside REAPER):

- `partitioned_convolve_skip(sig, ker, P, skip_after) -> (out, skipped_hops, state)` — returns
  the skipped-hop count and internal state (FDL, `fdl_wr`, ring positions, counters) so
  equivalence is checked on **state**, not only output.
- `partitioned_convolve_xfade(sig, ker_a, ker_b, P, switch_hop, fade_len) -> out` — an
  **integrated, stateful** engine that changes kernel under a running signal with the per-sample
  dual-convolution crossfade, in the §4 hop order (a vector-only fade helper cannot catch a
  transcription that fades one hop early or only in the non-skip branch).

**Tests:**

1. **The crossfade kills the artefact** — reproduce §2/§3's worst cases (Slope 24→48,
   Resonance 0→1, Off→Brick, 100→110 Hz): curvature anomaly **below −60 dB** relative to peak,
   while the instant-swap baseline is asserted to exceed it (proving the fix, not merely a small
   number).
2. **Steady state is bit-exact** — with no fade in flight, `partitioned_convolve_xfade` output is
   **bit-identical** to plain `partitioned_convolve`.
3. **Fade lands exactly** — after `fade_len` samples the active kernel equals the target
   bit-for-bit, and only one convolution pass per hop is performed thereafter.
4. **Endpoint ordering** — fade lengths `P-1`, `P`, `P+1`, `2205`, `2400`: assert the α applied to
   the first and last weighted samples, that both lanes used the same α, the exact pass count per
   hop, and which hop is the first to use `Hspec` alone.
5. **Skip is bit-exact** — a lane zeroed longer than `BD + B` then re-excited is
   **bit-identical** to the non-skipping engine, with internal state matching after resume.
6. **Skip actually fires** — `skipped_hops > 0`, output exactly `0.0` while skipping.
7. **Hop-alignment coverage** — zero-run onset at phases `0, 1, P-1`, run lengths `BD+B-1`,
   `BD+B`, `BD+B+P`: no premature skip, and the skip does engage.
8. **All four run/skip combinations** (A/B × run/skip), resuming at different hops, each
   bit-compared against the full two-lane engine.
9. **Fade + skip interact correctly** — a fade in progress while one lane is skipped: the skipped
   lane stays silent, `fade_pos` still advances once per hop, and the active lane matches the
   non-skipping reference bit-for-bit.
10. **Memory** — spans, packed tops, and page-safety **including every `Hspec2` partition** in
    Normal, fallback and High layouts.

**Live (REAPER, with the owner):**
1. Regression: `Phase = Min` unchanged; steady-state Linear unchanged from V0.7 (no knob motion).
2. **The cases that provably banged in §2**: Slope 24↔48 and Resonance 0↔1 **while playing** —
   before, a bang; after, nothing. Then a fast Freq sweep — no zipper.
3. **Lane-B skip CPU**: `HP Placement = Mid` at High, waiting **longer than `(BD+B)/srate`**
   (≈0.4 s @96k, ≈0.8 s @48k) before reading the meter; expect roughly half of that engine's
   convolution work to disappear, audibly identical.
4. **Benchmarks, not estimates**: steady CPU *and* peak block time at 44.1 / 48 / 96 / 192 kHz
   with a small device block, for Normal vs High, Both vs selective after the skip engages, one
   and two engines fading, and a rapid sweep that rebuilds every 100 ms. Report xruns.
5. Offline render still carries the full tail; PDC unchanged (V0.8 changes no latency).

## 9. Deferred to V0.9 — topology transitions (and why they are not a 20 ms dip)

rev 2 proposed a 10 ms fade-out / 10 ms fade-in dip covering Placement, Phase and Resolution.
The rev-2 review showed that this **cannot work**, and the analysis is recorded here so V0.9
starts from the right place:

- **The dip is shorter than the engine's own granularity.** One hop is `P = 2048` samples =
  42.7 ms @48k, 21.3 ms @96k. A 20 ms dip ends *before* the engine can even produce its first
  block under the new topology, so the already-queued old block plays after the envelope is back
  at 1.0 — the step is moved, not removed.
- **Phase and Resolution are far worse.** A relayout clears both engines, so the first valid
  output arrives only after the combined engine latency: 12288 samples (256 ms @48k) at
  Normal+Normal, 36864 (768 ms @48k) at High+High.
- **Placement has a third failure mode.** No relayout happens, but the FDL still holds
  old-domain history and the complementary dry ring returns stale content for `lat` samples
  (64–192 ms @96k), under the new routing.
- **PDC is a host-level concern.** Phase and Resolution change `pdc_delay`; a per-sample envelope
  inside the plugin says nothing about when REAPER adopts the new latency relative to other
  tracks.

A correct V0.9 therefore needs one of: parallel old/new engine instances crossfaded at the
output; or an explicit mute covering the full warm-up (with the latency stated honestly); plus a
pinned selected/pending/active topology state machine (commit at exact zero, coalescing,
reversal, bypass, simultaneous events), an envelope applied at the **final plugin output** (the
bands and dynamics downstream are stateful, so silence at the HP/LP boundary is not silence at
the output), and a stateful topology oracle with an event log rather than a subjective listen.

## 10. Invariants preserved

- **Bit-accuracy INTACT**: no new gain stage; the crossfade weights are ordinary float DSP and
  are **skipped entirely** when idle, so the steady-state path is byte-identical to V0.7. No
  `log`/`dB`/`pow(10)` anywhere in the DSP path.
- **V0.7 and earlier stay frozen.** New file `JSFX/RCBitNova V0.8` (copy of V0.7);
  `rcbitnova-v0.7` remains the fallback tag.
- Min path byte-identical; instance-local memory only; per-engine tables keep their V0.7 roles;
  no latency/PDC change.
- The Python DSP mirror remains THE ORACLE; live REAPER confirms transcription.

## 11. As-shipped outcome (2026-08-07, tagged `rcbitnova-v0.8`)

**Shipped as specified.** Fable final review: **bit-accuracy INTACT, no P0/P1, READY TO TAG**
(it independently recomputed the memory layout, traced the fade ordering in `lpk_run`, and
confirmed the steady-state path is byte-identical to V0.7).

**Live-verified with the owner:**
- **The crossfade does what it was built for.** Switching `HP Slope` 24↔48 **under playback** —
  measured in §2 as a full-amplitude step (+6.4 dB relative to peak) — is now **completely
  silent**. Mid/Side and knob sweeps behave normally.
- **The intermediate refactor was proven behaviour-neutral by a NULL TEST**: V0.7 and V0.8 with
  identical settings, one polarity inverted, summed to silence.
- **Lane-B skip, after the fix below** (playback running, FX CPU per track):

  | | Both | Mid |
  |---|---|---|
  | Normal | 0.90 % | **0.80 %** |
  | High | 1.6 % | **1.2 %** |

  At High that is −40 % `convolve_c` calls per hop on that engine (40 → 24), worth −25 % of
  whole-plugin CPU — consistent with §5's deliberately narrow claim that the saving is scoped
  to one engine's convolution work.
- PDC readings confirmed the geometry independently: 12288 at Normal+Normal, 24576 at
  High+Normal — exactly the oracle's `BD/2 + P` per engine.

**The one real defect, and how it was found.** The zero-run counters were written as
`iB == 0 ? ( rt[7] < skip_after ? rt[7] += 1; ) : ( rt[7] = 0; );` — an assignment inside a
**nested ternary**, the documented EEL2 gotcha in this project (handoff §6). The increment
never took effect, the threshold was never reached, and the skip never engaged. Before the
fix, selective placement cost *more* than Both (Mid adds M/S encode and the dry ring while the
convolution saving was missing): Normal 0.92→0.97 %, High 1.6→1.7 %. Rewritten as
`rt[7] = min(rt[7] + 1, skip_after)`.

**This was found by live measurement, not by review.** The oracle could not catch it (it models
the algorithm, not EEL2 parsing) and Fable's final review passed the file — the code *reads*
correctly. Only the CPU meter exposed it. It is the clearest evidence in this project so far
that the live-verification step is not a formality.

**Deferred (unchanged):** topology transitions for Placement/Phase/Resolution → **V0.9**, with
the timing analysis in §9 as its starting point. Two smaller notes for V0.9: a fade freezes
harmlessly if Phase is switched to Min mid-fade (output correct at every instant); and the
small Gibbs bump at the corner of the FIR Brick knee is pre-existing (present in V0.7 too) and
could be softened by spreading the magnitude step over 1–2 bins.
