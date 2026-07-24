# RCBitNova V0.6 — Final Whole-Branch Review (Fable)

**Scope:** `JSFX/RCBitNova V0.6` vs frozen `JSFX/RCBitNova V0.5`, cross-checked against
`tools/rcbitnova_dsp.py` (oracle, 111 tests), `linear_artur_slope_7.jsfx` (ported reference),
and `docs/superpowers/specs/2026-07-21-rcbitnova-v0.6-linear-phase-hplp-design.md` (rev 3).
Role: error-finding and bit-accuracy verification only, not rewriting.

## Verdict up front

- **BIT-ACCURACY: INTACT.** Full-file grep of V0.6 for `log(`, `log10`, `pow(10`, `20*`,
  `exp(` turns up only: comments/slider labels (`dB`), the pre-existing (V0.5, unchanged)
  `exp()` calls building the atk/rel one-pole time-constant coefficients (not a gain
  conversion), and `pow(2, ...)` sites which are all the approved bit-grid (`out_gain`,
  band `glin`, soft/hard ceilings, `anti`-denormal). The new linear-phase engine performs
  pure FFT-domain convolution — no gain stage anywhere in `lpk_build`/`lpk_run`/
  `lpk_process`; the only scalars are the mandatory `1/BD` (kernel ifft) and `1/B` (runtime
  ifft) FFT-normalization constants, applied exactly once each, matching the ported
  reference (`linear_artur_slope_7.jsfx`) verbatim. HP/LP remain pure filters (no gain
  stage) in both Phase modes, so linearizing their phase cannot and does not touch the bit
  claim.
- **Diff hygiene:** `diff` of V0.5 vs V0.6 shows the change is *exactly* additive/gated:
  desc string, slope enum `0-5`→`0-6` (+`FIR Brick`), new `slider140` (Phase), the mandatory
  `hp_nsec`/`lp_nsec` index-6→0 remap (present and correct — this was flagged in the spec as
  "MANDATORY else index 6 mis-runs in Min," and it's done right), the new V0.6 functions/init
  block, the PDC-policy line, the kernel-rebuild-trigger block, and the `@sample` Phase
  branch. Every other line of V0.5's `@init`/`@slider`/`@sample` (dynamics, Mode A, Mode B,
  static bands) is byte-identical. **Min path is confirmed byte-identical to V0.5.**
- **READY TO TAG: conditionally.** No crash, no memory-corruption, no bit-accuracy violation
  found. Two P1s below are real correctness/robustness gaps worth a quick live check (or an
  explicit, documented "known limitation, defer to V0.7") before the tag — neither is a
  blocker on its own.

## Findings

### P1 — Kernel magnitude is a *truncated* impulse response, not the analytic transfer
function the oracle verifies; the actual transcribed algorithm is untested

`lpk_build`'s `nsec>0` branch does **not** implement what `tools/rcbitnova_dsp.py`'s
`build_lp_kernel`/`hplp_digital_mag` implement. The oracle evaluates the cascade's digital
transfer function **analytically** (`svf_response` at each bin frequency — exact, no time
truncation). The JSFX instead runs a **unit impulse through the actual recursive TPT-SVF
cascade for exactly `lpBD=8192` samples** (reusing `hplp_coef`/`hplp_bell`, structurally
identical to `hplp_run`'s per-sample recursion) and takes the unnormalized FFT magnitude of
that 8192-sample-truncated response.

This is mathematically exact only in the limit that the (infinite-support, IIR) impulse
response has decayed to negligible amplitude by sample 8192 — true for typical settings, but
not guaranteed:
- **Resonance** raises the bell's effective `Q = 2·sqrt(1+Resonance·5)` up to ≈4.9 at
  Resonance=1, which lengthens ringing/decay time (`τ ≈ Q/(π·fc)`).
- **Low cutoff** (near 20 Hz) means a long time constant in *seconds*.
- **High sample rate** shrinks `BD` in *seconds* (`8192/96000 ≈ 85 ms` vs
  `8192/44100 ≈ 186 ms`) while the filter's physical decay time in seconds is unchanged —
  so the truncation window gets tighter exactly where slow decay is worst (20 Hz HP,
  Resonance→1, 96/192 kHz, steep slope).

None of the 111 Python tests exercise this specific numerical method — `build_lp_kernel` in
the oracle is the analytic implementation, and the test file never mirrors the "impulse
through the recursive cascade, truncated at BD" technique the JSFX actually runs. The
existing kernel-parity tests (`test_hp_kernel_matches_v05_digital_response` etc.) pass
**because they test the oracle's own analytic method against itself**, not because they
validate the transcribed algorithm's truncation behavior. So the header comment/claim
"Linear magnitude == Min magnitude by construction" is only approximately true, and the
degree of approximation is currently *unverified* at the parameter corners where it would be
worst (low fc + high Resonance + high slope + high srate).

**Recommendation:** before or shortly after tagging, either (a) add a Python mirror of the
actual impulse-then-FFT method and assert its deviation from `hplp_digital_mag` stays within
the already-documented tolerances (§6 of the design spec) at the worst-case corner
(20 Hz HP, Resonance=1, 96 dB/oct/8-section, 192 kHz), or (b) live-audition that exact corner
in REAPER (HP Freq=20, Resonance=1.0, Slope=96, Phase=Linear, project SR=192k) and confirm
no audible passband ripple/resonance mistuning versus the same settings in Min. If it turns
out fine (plausible — the Kaiser(β=14) window and the fact the *bell* is a modest 2nd-order
section may keep the tail short enough in practice), downgrade this to a documented
known-limitation note; if not, either compute the magnitude analytically in EEL2 (more code,
no truncation) or increase effective decay margin.

### P1 — Kernel rebuild has no click-safe crossfade; a previously-flagged issue appears
reintroduced

Design spec §8 mandates: on any Freq/Resonance/Slope signature change, build the new kernel
into a **second** `Hspec` slot and crossfade over one partition window, because the FDL
(`fdlA`/`fdlB`) retains **old-kernel-domain** frequency blocks from before the rebuild — the
spec explicitly says this crossfade "resolves P1 #8, #9" from an earlier review pass.

The actual `lpk_build` in V0.6 has no second kernel slot and no crossfade: it
`memcpy`s directly into the live `hspec` that `lpk_run`'s `convolve_c` reads every hop. Since
the FDL's older entries were FFT'd under the *previous* kernel's assumptions, the very next
`cnt>=lpP` hop after a rebuild convolves stale-signal-domain FDL blocks against the brand-new
kernel — a same-block discontinuity, not a smooth crossfade. There is also no rate-limiting
of rebuilds (§8 also calls for coalescing so automation doesn't rebuild every block); every
`@slider` call with a changed `hp_sig`/`lp_sig` rebuilds immediately.

Practically: this only fires when HP/LP **Freq, Resonance, or Slope** changes while
**Phase=Linear** and audio is flowing (not on Placement changes — placement is correctly
excluded from the signature per the code comment, matching spec). Given the "click-safe"
requirement was significant enough to be called out as resolving a prior P1 in the design
doc, and the live-verification note in the task didn't specifically call out a live sweep
test of Freq/Resonance while Linear+playing, this is worth an explicit live check before
tagging: automate/sweep HP Freq (or Resonance) in Linear mode with a continuous tone playing
and listen for a tick/click at the moment of change.

**Recommendation:** live-test the sweep scenario. If audible, implement the dual-kernel
crossfade from spec §8 (or, cheaper, coalesce the rebuild to happen once per partition
boundary and accept a small click as a documented V0.6 limitation, matching Dima's stated
"no seamless live switch needed" tolerance already accepted for the *Phase* toggle — but note
that tolerance was stated for Min↔Linear switching, not for continuous Freq/Resonance
automation within Linear).

### P2 — Placement change while Phase=Linear causes a bounded, self-healing artifact

`lpk_process`'s per-engine `dryA` ring is only **written** in the `pl != 0` (non-Both)
branch. If HP Placement is Both and then switches to, say, Mid while Linear is active and
audio is playing, `dryA` for that engine has not been written for the preceding `lp_lat`
(6144-sample, ≈128 ms @48k) window, so the first `cd = dryA[drd]` reads are stale/zero until
the ring refills with real history. Self-correcting after `lp_lat` samples; only matters for
live Placement toggling/automation in Linear mode (a much less common gesture than Freq/Slope
tweaking). Not a blocker; worth a one-line comment or a future fix (e.g., always feed dryA
regardless of placement, at negligible extra cost) if Placement automation in Linear turns
out to be a real use case.

### P2 — Implemented PDC policy differs from the written design spec §9 (documented,
intentional, not a bug — but the docs are now inconsistent)

Design spec §9 mandates a **constant `MAXLAT` for the plugin's entire loaded lifetime**,
independent of Phase (Min always pays the same latency as Linear, to make every switch
seamless). The shipped code implements a different, simpler policy instead — explicitly
labeled in a code comment as **"PDC policy (c)"**: Min = 0 latency (byte-identical to V0.5),
Linear = constant `2·(BD/2+P)=12288` (+ Mode-B lookahead), with the comment "no seamless live
switch needed - Dima." This reads as a deliberate, later supersession of §9 by the plugin
owner, not an oversight — the code is internally consistent and the Min-mode PDC formula is
verified algebraically equivalent to V0.5's original
`pdc_delay = (slider1!=1 && any_b) ? Lk : 0`. No action needed for the tag, but the design
spec doc should be updated (§9 rewritten to describe policy "(c)" instead of the abandoned
always-constant-MAXLAT scheme) so a future session doesn't "fix" the code back toward a
stale spec.

### P2 — Page-safety for engine 1 depends on an unstated numeric coincidence

`lp_base` is provably page-aligned (`ceil(x/65536)*65536`), but the per-engine stride
`229376` is **not** a multiple of `65536` (`229376 = 3.5 × 65536`), so engine 1's base
(`lp_base + 229376`) sits at a half-page offset (`≡ 32768 mod 65536`). I hand-verified every
`fft`/`ifft`/`convolve_c`-touched span (desbuf, each Hspec/fdlA/fdlB partition, fftw, yacc,
tmpc) for *both* engines against the `floor(start/page) == floor((start+size-1)/page)` rule
from spec §11, and all pass — for engine 1 specifically, only because every such span's
alignment granularity (8192 or 16384 words) evenly divides both the page size (65536) and the
half-page residual (32768). That's a correct but *fragile* invariant: it holds today because
`P=2048, B=4096, BD=8192` are fixed powers of two with this particular relationship to
65536; nothing in the source asserts or explains why it holds, so a future change to these
constants (e.g., trying `BD=16384` for deeper stopband) could silently break page-safety with
no compile-time signal. Recommend a one-line comment at the `lp_base`/engine-stride
definition recording *why* the 32768 residual is safe (or add the `__memtop()`/per-call
assertion the spec's §11 already calls out as a "Fable to run" TODO — this review is that
check, and it passes, but only by hand-derivation, not by an enforced runtime/test guard).

## Confirmed correct (no issues)

- **Memory disjointness:** `lp_rt`(38130,+16) → `lp_kc`(38146,+63) → `lp_ks`(38209,+18) →
  `lp_base`(65536, page-aligned) — no overlap with V0.5's `hplp_cf+126` end, no overlap with
  each other, sizes exactly match worst-case usage (`lp_kc`=63=9×7 sections incl. bell,
  `lp_ks`=18=9×2 state).
- **Engine block internal layout:** every offset in `lpk_build`/`lpk_run`/`lpk_process`
  (`desbuf, ktime, hspec, fdlA, fdlB, fftw, yacc, tmpc, inA, inB, outA, outB, dryA`) is
  contiguous and non-overlapping; sums to exactly `229376` words/engine, matching the
  `eng*229376` stride used everywhere consistently. (Python's `page_layout` table also
  budgets a `dryB` the JSFX never allocates — harmless, just unused padding, since only one
  lane is ever the "complementary/dry" lane at a time in non-Both placement; JSFX correctly
  needs only one dry ring per engine.)
- **Convolution engine:** `lpk_run` is a faithful, line-by-line port of
  `linear_artur_slope_7.jsfx`'s runtime loop (same FDL/overlap-save/valid-region indexing,
  same `out_wr=P`/`out_rd=0` initial offset trick). Hand-traced the ring-buffer bookkeeping
  end-to-end (input ring write → FFT block build → FDL accumulate → overlap-save valid
  region `yacc[(P+i)*2]` → output ring write/read lag) and confirmed the net engine latency
  is exactly `BD/2+P=6144` samples, matching the documented/reported figure, with the
  `out_wr` "head start" of `P` correctly implementing the "+P" hop-batching delay on top of
  the kernel's intrinsic `BD/2` group delay (kernel symmetric about the true center by
  construction of the `fftshift`).
- **1/BD, 1/B scaling:** each applied exactly once (`inv=1.0/lpBD` after the kernel `ifft`;
  `sc=1.0/lpB` after the runtime `ifft`), matching the unnormalized-forward/normalize-once
  convention used identically in the ported reference.
- **FIR Brick:** magnitude-step construction (`f>=fe?1:0` HP / `f<=fe?1:0` LP) matches
  `fir_brick_kernel` in the oracle exactly; correctly skips the resonance bell.
  Off/identity (`nsec<=0`) correctly produces an all-ones (all-pass) spectrum, matching
  `hplp_digital_mag`'s `nsec==0 → 1.0` and the oracle's dedicated identity-kernel test.
- **Placement + dry delay (static placement, not mid-stream toggled):** hand-verified the
  per-sample alignment between the engine's inherent output delay and the dry ring's
  explicit `lp_lat`-sample delay — both advance in lockstep (one index/sample, unconditional),
  so the complementary (untouched) lane and the filtered lane recombine at the same virtual
  time origin with no comb filtering, matching the owner's live confirmation. Series
  HP→LP composition is safe because each engine's `lpk_process` output is a *uniformly*
  `lp_lat`-delayed full L/R stream regardless of placement (via either the engine's own
  pipeline delay for Both, or the dry ring for non-Both), so chaining two engines needs no
  special-casing to keep the "same time origin" property from spec §7.1.
- **`hp_nsec`/`lp_nsec` mandatory remap:** present and correct
  (`slider131==6?0:slider131==5?8:slider131`), preventing the index-6 (FIR Brick) selection
  from mis-running as a 6-section (72 dB/oct) cascade in Min mode.
- **Both engines always run in Linear regardless of Off/Slope=0:** confirmed — the `@sample`
  Linear branch calls `lpk_process` for HP and LP unconditionally (no `hp_nsec>0`/`lp_nsec>0`
  guard, unlike the Min branch), matching "Off engines stay warm" (§8) and making the
  reported `pdc_delay` truly constant while Phase=Linear regardless of which filters are on.
- **EEL2 hazards:** no empty-both-branch ternaries, no `1e-30` literal (uses
  `pow(2,-100)` per the existing V0.5 convention), the `lp_i0` `while` loop terminates
  (fixed 39 iterations), `ceil` used correctly for page alignment, no obviously uninitialized
  reads (`lp_win` is fully built in `@init` before any `@slider`-triggered `lpk_build` can
  run; `lp_rt`/`lp_kc`/`lp_ks` are all in memory that's implicitly zero at load and
  explicitly `memset` where needed). Signature hashing
  (`slider131 + slider132*100003 + slider133*1009`) has no realistic collision within the
  actual slider ranges/steps (checked the arithmetic — the 100003 freq multiplier dominates
  by orders of magnitude, and no integer slope-difference exactly equals any
  quantized-resonance-difference times 1009 within the 0–1 resonance range).
- **V0.1–V0.5 files untouched;** only `JSFX/RCBitNova V0.6` (new file) and this branch's docs
  changed.

## Summary

No P0s. Two P1s worth a live check (kernel-magnitude truncation accuracy at extreme
low-freq/high-resonance/high-samplerate settings; kernel-rebuild click-safety while
Freq/Resonance/Slope changes in Linear with audio playing) — both are about *fidelity at the
edges*, not about the bit-accuracy guarantee or main-path correctness, which are solid. Two
P2s are documentation/robustness notes, not blockers. Recommend the two P1 live checks before
tagging `rcbitnova-v0.6`; if both come back clean (plausible), tag as-is and carry the P2 notes
into V0.7 planning.
