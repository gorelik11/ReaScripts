# RCBitNova V0.8 — Click-Safe Kernel Crossfade + Lane-B Skip — Design Spec

**Date:** 2026-07-29
**Branch:** `rcbitnova` (worktree `~/projects/reascripts/.claude/worktrees/rcbitnova/`)
**Base:** V0.7 (frozen, tag `rcbitnova-v0.7`, commit `90a72b3`) — new file `JSFX/RCBitNova V0.8`
**Predecessor specs:** `2026-07-21-…-v0.6-linear-phase-hplp-design.md` (§15) and
`2026-07-25-…-v0.7-hires-linear-phase-design.md` (§10) — both list these two items as deferred.

---

## 1. Goal

Ship the two optimisations deferred from V0.6/V0.7, both in the linear-phase convolution
engines:

1. **Click-safe kernel crossfade** — turning HP/LP Freq, Resonance or Slope while `Phase =
   Linear` currently swaps `Hspec` in place, so the output jumps at a hop boundary and clicks.
   V0.8 blends the active kernel toward the newly built one over 8 hops.
2. **Lane-B skip** — in selective placement (Mid/Side/Left/Right) `lpk_process` calls
   `lpk_run(eng, act, 0)`, so lane B convolves a permanently-zero input. Skipping that work
   **halves** the convolution cost of those placements — the most valuable saving exactly where
   V0.7 is most expensive (a High engine runs `2 × KMAX = 32` `convolve_c` per hop).

Nothing else about V0.7 changes: same geometry, same resolutions, same PDC model, same
bit-accuracy claim.

## 2. Scope

**In:** kernel-blend crossfade with its second `Hspec` buffer and fade state; per-lane
zero-run skip; the oracle changes and tests both require; live verification.

**Out (YAGNI / deferred):**
- **Placement-change crossfade.** Placement is routing, not kernel content — a Both↔Mid switch
  changes which signal each lane carries, which no kernel blend can smooth. Still a documented
  transient (V0.6 §15 P2).
- **Phase (Min↔Linear) crossfade** — a topology + latency change; the owner confirmed in V0.6
  that seamless live switching is not needed.
- Any change to resolutions, geometry, PDC, or the min-phase path.

## 3. Lane-B skip — provable zero-run skip (not a placement flag)

**Rule.** Each engine tracks, per lane, the number of consecutive **exactly zero** input
samples (`zcntA`, `zcntB`). When a lane's counter reaches `BD + B`, its entire convolution
block is skipped for that hop: no input FFT, no `KMAX` `convolve_c`, no inverse FFT. Instead
`P` zeros are written to that lane's output ring. The lane's input ring is still written every
sample (one store).

**Why the threshold is `BD + B` and why this is exact.** A hop's input block is the last
`B = 2P` samples. After `BD + B` consecutive zero inputs, every one of the `KMAX = BD/P` FDL
slots was filled from an all-zero block, so the whole FDL is zero; the convolution sum is
therefore exactly zero, and so is the output. Skipping computes the same value the full path
would have produced — it is not an approximation.

**Why resuming is artefact-free.** The skip is only ever entered from a state where the FDL is
all zeros, and nothing is written to the FDL while skipping (the slots already hold zeros). So
when a non-zero sample arrives, the counter resets, full processing resumes on the next hop,
and the FDL it reads is genuinely zero — exactly the state the non-skipping implementation
would have been in. **There is no fade-in, no stale history, and no need for a placement flag
or a state reset.** This is the property the oracle test in §6 asserts bit-exactly.

**Applies to both lanes** for code symmetry. In practice only lane B trips in selective
placement; lane A does not, and neither lane trips during silence because the global
anti-denormal offset makes silent samples `±2^-100` rather than exactly `0`. The saving is
therefore precisely the intended one: selective placement costs half.

**State.** `lp_rt` already has stride 8 with slots 0–5 used, so `rt[6] = zcntA`,
`rt[7] = zcntB` fit with no memory growth. Both reset in `lp_rt_reset`.

## 4. Kernel crossfade — blend the kernel, not the outputs

Convolution is linear, so
`conv(x, (1−a)·H_old + a·H_new) = (1−a)·conv(x, H_old) + a·conv(x, H_new)`. Blending the
**kernel** therefore yields exactly the blended output, at the cost of one extra buffer instead
of a second convolution pass.

**Buffers.** `lpk_build` writes the newly built kernel into a second slot **`Hspec2`** (the
target). `Hspec` stays the active kernel the runtime convolves with.

**Law.** While a fade is active, once per hop (before the convolution):

```
w = 1 / fade_left
Hspec[i] += w * (Hspec2[i] - Hspec[i])        for all KMAX*PB2 words
fade_left -= 1
if fade_left == 0:  memcpy(Hspec2 -> Hspec);  fading = 0
```

`fade_left` starts at **8** hops (≈170 ms @96k, `P = 2048`). The `1/fade_left` weight gives
**exact linear arrival in exactly 8 hops**, and the final `memcpy` guarantees the active kernel
ends up bit-identical to the built one (no residual drift). Clearing `fading` stops the blend
loop from running forever once converged.

**First build snaps, never fades.** After plugin load or a geometry (Resolution) change there
is no meaningful old kernel — fading from zero would mute the engine for 170 ms. So when an
engine has no valid kernel yet (`built == 0`, the same flag V0.7 already uses to bypass the
rebuild rate-limit), `lpk_build`'s result is copied straight into `Hspec` with no fade.

**Overlapping fades need no special handling.** V0.7 rate-limits rebuilds to ≤1 per 100 ms per
engine, so a knob sweep produces a new target mid-fade. Because the blend always chases
whatever is currently in `Hspec2`, a new target simply overwrites it and the active kernel keeps
converging — the behaviour degrades gracefully into continuous smooth tracking of the knob.
`fade_left` is reset to 8 whenever a new target is built.

**Cost.** One `KMAX*PB2` multiply-add pass per hop *while fading only* (32768 words at Normal,
131072 at High) — comparable to a single `convolve_c`, i.e. roughly +25 % on that engine during
the fade, and zero once converged.

## 5. Memory — the one real price

The second `Hspec` is needed at every resolution, not only High:

| | V0.7 | V0.8 |
|---|---|---|
| Normal engine span | 229376 | **262144** (exactly 4 pages) |
| High engine span | 655360 | **786432** (exactly 12 pages) |
| Fallback-16384 span | 360448 | 425984 |
| Packed top, Normal+Normal | 458752 | **524288** (+0.5 MB) |
| Packed top, High+Normal | 884736 | 1048576 |
| Packed top, Normal+High | 917504 | 1048576 |
| Packed top, High+High | 1310720 | 1572864 |

**V0.7's "Normal+Normal is byte-identical to V0.6's footprint" property is deliberately given
up** (+512 KB) — the crossfade cannot exist without holding both kernels. Recorded explicitly
because V0.7 made a point of that guarantee; the *hi-res* zero-cost property (High costs nothing
until selected) is unaffected.

**Page-safety status of `Hspec2`:** it is never passed to `fft`, `ifft` or `convolve_c` — the
FFT happens in `fftw`, and `lpk_build` only `memcpy`s the result into `Hspec2`, which the blend
loop then reads word by word. It therefore carries no page-crossing constraint of its own.
It is nevertheless aligned exactly like `Hspec` (per-partition `PB2` alignment) so that a future
change which convolves straight from it remains legal without revisiting the layout.

## 6. Verification

**Oracle (Python, stdlib only).** Two additions mirror the JSFX so the behaviour can be tested
outside REAPER, plus `lp_engine_buffers` gains `Hspec2`:

- `partitioned_convolve_skip(sig, ker, P, skip_after) -> (out, skipped_hops)` — the same
  overlap-save engine as `partitioned_convolve`, but tracking a consecutive-zero-input counter
  and skipping a hop's whole convolution (emitting `P` zeros) once the counter reaches
  `skip_after`. Returns the count of skipped hops so a test can prove the skip actually fired.
- `kernel_fade_step(active, target, fade_left) -> None` — one in-place `w = 1/fade_left` blend
  step over a coefficient list, mirroring the JSFX blend loop.

Tests:

1. **Skip is bit-exact, not merely quiet** — the decisive test. Feed a signal whose lane input
   is zero for longer than `BD + B` and then becomes non-zero again through both
   `partitioned_convolve` and `partitioned_convolve_skip`; assert the outputs are
   **bit-identical**, proving the skip introduces no artefact on entry or on resume.
2. **Skip actually triggers** — the same run reports `skipped_hops > 0`, and the output during
   the skipped stretch is exactly `0.0`. (Guards against a green test that never skipped.)
3. **Fade law** — from kernel A toward target B, eight `kernel_fade_step` calls with
   `fade_left = 8, 7, … 1` land **exactly** on B, every intermediate value lies between the
   endpoints, and the remaining distance shrinks linearly (`(8−k)/8` of the original).
4. **Fade retarget** — overwriting the target mid-fade converges to the new target without
   overshoot.
5. **Memory** — spans, packed tops, page-safety per §5.

**Live (REAPER, with the owner):**
1. Regression: `Phase = Min` unchanged; `Linear` at Normal/Normal unchanged from V0.7 in steady
   state (no knob movement).
2. **Crossfade:** sweep HP Freq and Resonance while playing, at Normal and at High — the clicks
   present in V0.7 are gone; no dropouts; the knob still feels responsive (≈170 ms smoothing).
   Also switch Slope (a bigger jump) under audio.
3. **Lane-B skip:** `HP Placement = Mid` (and `Side`) at High — audibly identical to V0.7, but
   CPU roughly **half** of V0.7's for that configuration. Verify by watching REAPER's CPU meter
   with the placement toggled Both↔Mid.
4. Placement toggling Both↔Mid↔Side repeatedly under audio: no new artefacts beyond the
   documented (unchanged) placement transient, and no lingering silence in a lane.
5. Offline render still carries the full tail; PDC unchanged.

## 7. Invariants preserved

- **Bit-accuracy INTACT:** neither feature introduces a gain stage. The fade weight `w` and the
  blend are ordinary float DSP inside the kernel spectrum, exactly like the existing `1/BD` and
  `1/B` normalisations; no `log`/`dB`/`pow(10)` anywhere in the DSP path.
- **V0.7 and earlier stay frozen.** New file `JSFX/RCBitNova V0.8` (copy of V0.7);
  `rcbitnova-v0.7` remains the fallback tag.
- Min path byte-identical; Linear steady-state output unchanged (both features are no-ops once
  a fade has converged and while both lanes carry signal).
- Instance-local memory only; per-engine tables (`lp_geo`, `lp_off`) keep their V0.7 roles.
- The Python DSP mirror remains THE ORACLE; live REAPER confirms transcription.
