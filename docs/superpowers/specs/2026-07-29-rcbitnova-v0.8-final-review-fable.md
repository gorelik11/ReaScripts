# RCBitNova V0.8 — Final Whole-Branch Review (Fable)

**Date:** 2026-08-07
**Reviewed file:** `JSFX/RCBitNova V0.8` (1057 lines) against frozen baseline `JSFX/RCBitNova V0.7`
(967 lines) and oracle `tools/rcbitnova_dsp.py` / `tests/test_rcbitnova_dsp.py` (144 passing)
**Spec:** `docs/superpowers/specs/2026-07-29-rcbitnova-v0.8-crossfade-laneskip-design.md` (rev 3)
**Scope:** error-finding and bit-accuracy verification only — no rewrite performed.

## Method

1. Full `diff -u` of V0.7 vs V0.8 — confirmed the *entire* delta is confined to: the `desc`
   line, `lp_layout` (new `ob[15]`), `lp_win_build`'s successor block (`lp_fs_reset` inserted),
   `lp_rt_reset` (+2 counters, +`lp_fs_reset` call), new `lpk_commit`, `lpk_build` (build target
   only), `lpk_run` (dual-pass fade + skip), the `lp_fs`/`lp_off` memory map, and the `@block`
   rebuild-scheduling block. Everything downstream of the HP/LP section — all four EQ bands,
   Mode A/B dynamics, output gain — is byte-for-byte untouched. This bounds the whole review to
   the linear-phase engine.
2. Hand-recomputed `lp_layout`'s offsets for Normal (BD=8192) and High (BD=32768) geometries by
   simulating the JSFX arithmetic directly, and cross-checked against the spec's claimed spans
   (262144 / 786432) and packed tops (524288 / 1048576 / 1048576 / 1572864). All four numbers
   reproduced exactly by independent calculation — not just re-reading the oracle's own output.
3. Ran `tests/test_rcbitnova_dsp.py`: **144/144 pass**, including every test category the spec's
   §8 promises (crossfade artefact-kill, steady-state bit-exactness, endpoint ordering, skip
   bit-exactness, skip+fade coexistence, Hspec2 page-safety in every layout).
4. Grepped the full V0.8 file for scientific literals, `log`/`dB`/`pow(10)`, and empty ternary
   branches — none found in executable code (the only hits are comments, slider labels, and one
   coincidental substring match on a variable name `bdB`).
5. Traced the rev-2 weakness review's 8 findings (`…-weaknesses.md`) against the rev-3 spec and
   the shipped code, one by one, to confirm each was actually closed in the implementation and
   not just in prose.

## P0 — none found

No wrong output, crash, bit-accuracy regression, or silent corruption was found.

## P1 — none found

Nothing that must block the tag.

## P2 — one observation, not a defect

**Phase→Min mid-fade freezes that engine's fade indefinitely, by design, not by accident.**
If an engine is fading (`lp_fs[eng*4]==1`) and the user flips `Phase` to `Min` before the fade
completes, `lpk_run`/`lpk_process` are no longer called (the `@sample` dispatch goes to
`hplp_run` instead), so `fade_pos` cannot advance. Any `hp_dirty`/`lp_dirty` queued during this
window stays queued too, because the `@block` guard is `hp_dirty && lp_fs[0] == 0`. This is not a
stuck state — the DSP is correct at every instant (Min-phase output is unaffected; the frozen
fade and queued rebuild simply resume the moment `Phase` returns to `Linear`, using unmodified
buffers) — but it is a state interaction the spec doesn't call out explicitly (§9 only discusses
Phase/Resolution/Placement *transitions*, not a fade paused mid-flight by a Phase change). Worth a
one-line spec note for V0.9; does not affect correctness or the tag decision.

## Verification detail, by review checklist item

**1. Bit-accuracy scan.** No `log`/`dB`/`pow(10)`/`20*` in any DSP path. The only numeric hits on
`dB`/scientific-notation patterns are: slider label text (`HP Slope (dB/oct)`), header comments,
the pre-existing `anti = pow(2, -100)` anti-denormal (unchanged from V0.7), and the variable name
`bdB` (a band-detector sample, not a decibel value). The fade weights (`a = (fpos+i)/flen`,
`(1-a)`, `a`) are ordinary linear-domain float multiplies — no new gain stage, no log/exp pair
introduced. **Bit-accuracy of the fade mechanism itself is a pure amplitude crossfade, exactly as
documented.**

**2. Steady-state identity vs V0.7.** When `fading==0` and neither lane is skipping, `lpk_run`'s
single-pass branches (`outA[ow] = yacc[(lpP+i)*2] * sc;` / same for B) are textually identical to
V0.7's only path — same buffers (`hspec`, `fdlA`/`fdlB`, `fftw`, `yacc`, `tmpc`), same scaling
(`sc = 1.0/lpB`), same ring arithmetic. The zero-run counters (`rt[6]`/`rt[7]`) are computed
unconditionally every sample as bookkeeping, but they never touch `outA`/`outB` on the non-skip,
non-fade path, so they have zero numeric effect on that path. **Steady state is byte-identical to
V0.7**, confirmed both by inspection and by `test_crossfade_steady_state_is_bit_exact` passing.

**3. Hspec2 page-safety.** Independently recomputed (not re-derived from the oracle, computed
from the JSFX `lp_layout`/`lp_align` logic by hand):
- Normal engine (BD=8192, KM=4): span = **262144** words.
- High engine (BD=32768, KM=16): span = **786432** words.
- Packed tops: Normal+Normal = **524288**, High+Normal (and Normal+High, by symmetry of the
  packing) = **1048576**, High+High = **1572864**.

All four match the spec's claimed numbers exactly. `Hspec2` is inserted between `Hspec` and
`fdlA` in `lp_layout`, aligned to `lpPB2` (8192 words) exactly like `Hspec`/`fdlA`/`fdlB`, and
`lpPB2` (8192) evenly divides the 65536-word page, so every one of `Hspec2`'s `KM` partitions is
provably page-safe in Normal, High, and both mixed-packing orders — confirmed both by hand
arithmetic and by `test_every_hspec2_partition_is_page_safe` / `test_hspec2_exists_and_is_fft_touched`.
This closes the exact P0 the rev-2 weakness review flagged (`Hspec2` claimed non-convolved while
the runtime passes it to `convolve_c`) — rev 3 correctly marks it FFT-touched in both the spec
prose and the oracle's `lp_engine_buffers`, and the JSFX code matches.

**4. Fade ordering.** Traced execution order directly in `lpk_run`: FDL write happens once
per-hop before either lane runs; lane A's two passes (`hspec` then `hspec2`) complete in full,
then lane B's two passes complete in full; `fpos`/`lp_fs[eng*4+1]` advance exactly once, in a
single statement, strictly after both lane blocks; `lpk_commit` is only reachable from that same
post-both-lanes statement (`fpos >= flen ? lpk_commit(eng);`), so it can never fire between lane A
and lane B. Both lanes read the same `fading`/`fpos`/`flen` values captured once at the top of the
hop, so both use identical `alpha_i` for the same output position `i`. Pass 1 writes with `(1-a)`
(`outA[ow] = yacc[...] * sc * (1-a)`), pass 2 accumulates with `+=` and `a`
(`outA[ow] += yacc[...] * sc * a`) — matches the spec's pinned pseudocode exactly, for both lanes
independently. `lpk_commit` copies exactly `KM * lpPB2` words (`memcpy(ob[3], ob[15], KM * lpPB2)`)
and clears `fading` (`lp_fs[eng*4] = 0`) in the same function, so commit and clear cannot get out
of sync.

**5. Rebuild scheduling.** The `@block` guard `hp_dirty && lp_fs[0] == 0` (and the LP mirror with
`lp_fs[4]`) refuses a rebuild while that engine is fading; `hp_dirty` is not cleared in that case,
so it stays queued and is picked up the first `@block` call after the fade completes and clears
`lp_fs[eng*4]`. First build after load (`lp_fs[3]==0`, i.e. `valid==0`) forces an immediate build
(bypassing the 100 ms limiter) and forces a commit rather than a fade
(`(lp_fs[3] == 0 || slider140 == 0) ? lpk_commit(eng) : (start fade)`), and the same expression
also snaps when `Phase == Min` (`slider140 == 0`), matching "never start a fade that could not
advance." `lp_fs` slot indices were checked and are correct: engine 0 owns `lp_fs[0..3]`, engine 1
owns `lp_fs[4..7]` (`lp_fs_reset(eng)` computes `fs = lp_fs + eng*4`, and every call site in
`@block`/`@slider` uses the matching `eng*4` offset for HP vs `+4` for LP) — no index slip.

**6. Skip correctness.** The zero-run counters are updated every sample, including the current
sample, before the buffered hop decision (`iA == 0 ? (rt[6] < skip_after ? rt[6] += 1;) : (rt[6] = 0;)`
runs unconditionally per sample; the hop-boundary check `cnt >= lpP` happens later using the
already-updated counter). Saturation is correct: the increment is gated by `rt[6] < skip_after`,
so the counter stops exactly at `skip_after` and stays there. A skipped lane emits exactly `P`
zeros (`loop(lpP, ... outA[ow] = 0; ...)`) and skips the FDL write entirely — the `else` branch
containing `fftw[...]=inA[...]`, `fft`, `memcpy(fdlA...)` is simply not reached. `fdl_wr` advances
once per hop unconditionally, after both lane blocks, regardless of either lane's skip state —
confirmed by its being outside both `rt[6]>=skip_after`/`rt[7]>=skip_after` conditionals. Counters
are reset in `lp_rt_reset` (`rt[6] = 0; rt[7] = 0;`). The skip can only engage on a literal-zero
sample: lane A (`act` in `lpk_process`) is always derived from `spl0`/`spl1` *after* the
anti-denormal offset (`spl0 += anti`) has already been applied earlier in `@sample`, so it is
never bit-exact zero during genuine silence; lane B in selective placement is fed a hardcoded
literal `0` (`lpk_run(eng, act, 0)`), unaffected by anti-denormal, so it is the only lane that can
actually reach the skip. This matches the design intent exactly and is independently confirmed by
`test_lane_skip_output_is_exactly_zero_while_skipping`,
`test_lane_skip_never_fires_early_and_covers_hop_phases`, and
`test_lane_skip_all_four_run_skip_combinations`.

**7. State lifecycle.** `lp_fs` is reset by `lp_fs_reset`, called from `lp_rt_reset`, called at
first load and on every relayout (Resolution change or the Min→Linear reconcile in `@slider`).
`lp_relayout` clears the fade state (via `lp_rt_reset`) *and* `memset`s the entire engine memory
block before any fade could reference stale addresses, so a fade cannot survive a relayout that
moves or clears buffers — confirmed both by code trace and by the explicit `lp_fs[3] = 0; lp_fs[7] = 0`
belt-and-suspenders forcing right after the relayout call. `hp_built`/`lp_built` are fully removed
from V0.8 (grep confirms zero remaining references) — the rev-2 weakness review's "two sources of
truth for validity" finding is closed; `lp_fs[3]`/`lp_fs[7]` (`valid`) is the single authority for
both the rate-limiter bypass and the fade/snap decision, exactly as rev 3 specifies.

**8. EEL2 hazards.** No empty ternary branches (all single-branch conditionals found are the
valid EEL2 `cond ? stmt;` form with no dangling `:`). No new scientific-notation literals in
executable code. Functions are defined before use (`lp_fs_reset` precedes `lp_rt_reset` which
calls it; `lpk_commit` precedes its only call sites in `@block`/`lpk_run`). `local()` lists were
checked variable-by-variable against each function body:
- `lp_fs_reset(eng) local(fs)` — only `fs` used. Complete.
- `lpk_commit(eng) local(ob, KM)` — only `ob`, `KM` used. Complete.
- `lpk_run(eng, iA, iB) local(ob, KM, hspec, hspec2, fdlA, fdlB, fftw, yacc, tmpc, inA, inB,
  outA, outB, rt, ir, cnt, out_rd, out_wr, fdl_wr, i, si, k, idx, ow, sc, fading, fpos, flen, a,
  skip_after)` — every one of these is referenced in the body, and no other non-parameter,
  non-global identifier appears in the body that isn't in this list. Complete — no accidental
  global leak between the two engine instances.
- `lpk_build`'s local list is unchanged from V0.7 (it reuses the same `hspec` local name to
  point at `ob[15]` instead of `ob[3]`, a naming choice, not a new variable) — still complete.

All instance-local memory (no `gmem`), matching the plugin's stated architecture.

## Cross-check against the rev-2 weakness review

The prior review round (`…-v0.8-crossfade-laneskip-weaknesses.md`, 2026-08-03) raised two P0s and
six P1/P2s against rev 2 of the spec. Verified against rev 3 and the shipped code:

| Finding | Status in V0.8 |
|---|---|
| P0: 20 ms topology dip can't cover Placement/Phase/Resolution | Removed from V0.8 scope entirely (spec §9); not reintroduced in code — confirmed no topology-transition code exists in the diff |
| P0: Hspec2 convolved but declared non-convolved | Fixed — FFT-touched, page-tested, matches runtime |
| P1: plugin-local ramp doesn't define PDC transition | N/A — no topology ramp in V0.8 |
| P1: topology state machine unspecified | N/A — deferred to V0.9 with the topology feature |
| P1: dip placed before downstream stateful bands | N/A — no dip in V0.8 |
| P1: snap-on-overlap relies on wall time vs audio time | Fixed — `@block` gates on `fading==0`, never snaps over a live fade; queued instead |
| P1: two sources of truth for `built` | Fixed — single `valid` flag in `lp_fs`, `hp_built`/`lp_built` removed |
| P1: fade CPU description too narrow | Addressed in spec §6 (honest 4×KMAX for Both-placement fade); not a code-correctness matter |
| P2: partial final-hop ordering unpinned | Fixed — hop order pinned in spec §4 and matches code; tested at `P-1, P, P+1, 2205, 2400` |
| P2: topology verification subjective | N/A — deferred with the topology feature |

Every finding that applies to what actually shipped in V0.8 is closed in both the spec and the
code, not merely in prose.

## Bit-accuracy verdict

**INTACT.** No log-domain, dB, or `pow(10)` arithmetic in any DSP path; no new gain stage; the
crossfade weights are ordinary linear float multiplies that are provably absent from the
steady-state path (confirmed by inspection and by `test_crossfade_steady_state_is_bit_exact`).
V0.7's steady-state output is reproduced byte-for-byte when no fade and no skip is active.

## Ready to tag

**Yes.** No P0 or P1 findings. One P2 observation (Phase→Min mid-fade pause) is a correct,
harmless state interaction worth a documentation note in V0.9, not a blocker. Memory layout,
page-safety, fade ordering, skip correctness, rebuild scheduling, state lifecycle, and EEL2
hygiene all check out against independent hand-verification, not just re-reading the spec's own
claims. 144/144 oracle tests pass.
