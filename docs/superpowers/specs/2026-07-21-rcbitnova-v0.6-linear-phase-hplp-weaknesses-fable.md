# RCBitNova V0.6 Linear-Phase HP/LP — Second-Pass Adversarial Review (rev 2)

**Date:** 2026-07-21
**Reviewed spec:** `2026-07-21-rcbitnova-v0.6-linear-phase-hplp-design.md` (rev 2)
**Prior review:** `2026-07-21-rcbitnova-v0.6-linear-phase-hplp-weaknesses.md` (10 P1s + 2 P2s
under a continuous P0(1-3)/P1(4-13)/P2(14-15) numbering scheme that rev 2's `#N` citations
correctly key into — I checked every citation against the source finding and they all map to
the right content, so the traceability itself is sound.)

## Verdict up front

Rev 2 is a real, substantive revision — not a cosmetic pass. Two of Codex's three P0s are
**genuinely resolved**, one is **resolved on paper but not mathematically closed**, and I found
three new concrete issues (one is an actual code-level contradiction, not a nitpick) that must
be pinned before this goes to a plan. None of the new findings invalidate the architecture;
they're transcription-risk and completeness gaps of the kind this spec's own method (oracle
before code) exists to catch.

---

## Per-Codex-P0 resolution status

### P0-2 (even-kernel symmetry/delay) — **GENUINELY RESOLVED.** I re-derived it independently.

I traced Arthur's actual `build_kernel_slope()` (lines 96-120 of
`linear_artur_slope_7.jsfx`): magnitude sampled in natural order with `kk = i<=BD/2 ? i : BD-i`
(so the pre-IFFT spectrum is exactly Hermitian/even about bin 0), `fft_ipermute`+`ifft`, then
`ktime[i] = desbuf[(i+half) mod BD] * inv * win_k[i]` with `half = BD/2`.

Because the input spectrum is real and even, its IFFT `desbuf` is real and **circularly even
about index 0**: `desbuf[d] = desbuf[BD-d]`. Substituting into the shift:
- `ktime[half+d] = desbuf[(2*half+d) mod BD] = desbuf[d]`
- `ktime[half-d] = desbuf[(BD-d) mod BD] = desbuf[BD-d]`

Since `desbuf[d] = desbuf[BD-d]`, these are identical: `ktime[half+d] = ktime[half-d]`. So the
kernel genuinely is symmetric about the **integer** index `4096`, with integer group delay
`BD/2`, and the original review's `k[i]==k[N-1-i]` (Type-II, half-sample-delay) framing was the
wrong test for *this specific construction* — it's the right test for a generic centered FIR,
but Arthur's circular-shift-of-an-even-sequence approach sidesteps that entirely. The
identity-magnitude check (constant-1 spectrum → circular delta at 0 → shifted to `4096`) also
checks out: `ktime[0]` is unpaired in the `4096`-symmetry test, correctly window-suppressed at
the tap edges.

**This P0 is closed.** Rev 2's test (`k[4096+d]≈k[4096-d]`) is the correct one; Codex's
original test was the actual error. Good catch.

### P0-3 (dynamic PDC vs. seamless switching) — **Resolved in design, with one real gap.**

The constant-`MAXLAT` + delayed-dry + warm-Off-engine approach is sound and eliminates the
*reported-latency* jump Codex flagged. However:

- **Phase Min↔Linear itself is still an uncrossfaded code-path swap.** §8's dual-kernel
  crossfade is scoped to Freq/Resonance/Slope/Placement changes *within* the Linear engine. It
  is never invoked for the Phase switch. Constant PDC guarantees the *host* doesn't see a
  latency jump, but the audio content still swaps from IIR-state output to FIR-ring-buffer
  output (or back) at a hard sample boundary — two independently-running signal paths with
  unrelated internal state. Nothing in §9 claims (or delivers) audio continuity across that
  edge, only latency-number continuity. These are different guarantees and the spec conflates
  them by putting the Phase switch under the "seamless switching" umbrella that's actually
  built for the crossfade case.
  - **Recommendation:** either (a) explicitly scope Phase toggling as "no audio click-guarantee,
    latency-guarantee only" (honest, cheap), or (b) extend the dual-kernel crossfade concept to
    Phase changes by running Min and Linear in parallel across the transition window and
    crossfading, matching what §8 already does for in-Linear parameter changes. Pin one of these
    before planning — right now the spec implies more safety than it delivers.

### P0-1 (page-safety) — **Necessary-but-insufficient, as Codex's own review predicted; rev 2 restates the fix, it doesn't perform it.**

I computed the actual per-engine footprint from Arthur's own allocator (`desbuf` 16384,
`ktime`/`win_k` 8192 each, `Hspec`/`fdlA`/`fdlB` 32768 each, `fftw`/`yacc`/`tmpc` 8192 each,
`inA`/`inB` 4096 each, `outA`/`outB` 16384 each, `dryA`/`dryB` 16384 each) = **229,376 real
slots/engine**. Two engines = **458,752 slots — exactly `65536 × 7`, with zero slack.** V0.5's
existing memory map (bells/dynamics/HP-LP state) already occupies several thousand words before
`hplp_cf`, so the two engines' buffers will not start at a page boundary by default; contiguous
placement (as literally written in earlier text and still implied by "allocate after `hplp_cf`"
in §12) will almost certainly straddle pages on multiple buffers.

§11 upgrades the *test* (an `assert floor(start/65536)==floor((start+count-1)/65536)` per FFT
call) from Codex's version — that part is a real improvement and is the correct check. But it
is still only a test, not a layout. The spec explicitly punts the actual page-aligned allocator
to "the plan" (§11: "The plan pins a page-aware layout... not just a disjointness test" — this
sentence describes what the *plan* must do, it is not itself the layout). Given the exact
zero-slack coincidence above, any page-rounding padding *will* push the total over 7 pages, which
means the plan needs a concrete `ptr = ceil_to_page(ptr)`-style allocator (or reordering large
buffers to be power-of-two-sized and pre-aligned) worked out with real numbers, not left as "the
plan will handle it."

**Verdict: this P0 is acknowledged and given a correct verification method, but is not
mathematically closed by the spec text itself. Treat as P1 — must be pinned with actual offsets
before implementation starts**, not deferred a second time.

---

## New findings (rev 2 specific)

### P1 — `hp_nsec`/`lp_nsec` selection expression contradicts §3.2's own "Brick-in-Min = Off" rule

V0.5's actual code (`JSFX/RCBitNova V0.5:342`, `:352`):
```
hp_nsec = slider131 == 5 ? 8 : slider131;
lp_nsec = slider135 == 5 ? 8 : slider135;
```
This works today because slider131 ranges 0-5 and value 5 ("96") is the only value needing a
remap (to 8 Butterworth sections); every other value equals its own section count directly
(index 1→12dB/oct = 1 section, ... index 4→48dB/oct = 4 sections).

§3.2 adds index 6 = `FIR Brick` and states "in Min it is treated as Off." But nothing in the
spec calls out that the `hp_nsec`/`lp_nsec` expressions above must change. As written, selecting
FIR Brick in Min mode would fall through to `hp_nsec = 6` (the `else` branch), silently running
a **6-section (72 dB/oct) Butterworth cascade** — not Off, and not any of the documented slopes.
This is a concrete, verifiable contradiction between a stated design invariant (§3.2) and the
unmodified source it's layered onto.

**Recommendation:** pin the corrected expression explicitly in the spec, e.g.
`hp_nsec = slider131==5 ? 8 : (slider131==6 ? 0 : slider131)`, so the plan doesn't have to
rediscover this. Add a unit test: Brick selected + Phase=Min ⇒ `hp_nsec==0` (no filtering, not
72 dB/oct).

### P1 — §6's "fixed Q=2" resonance-bell description is measurably wrong and could mislead the oracle author

§6 says: "Resonance bell: fixed `Q=2`, `glin = 1 + Resonance·5` (linear), identical to
`hplp_bell`." Reading `hplp_bell` (`JSFX/RCBitNova V0.5:223-228`):
```
A = sqrt(glin); ... bk = 1 / (2 * A); ... dst[3] = bk;
```
`bk` (the SVF's `k = 1/Q` parameter) is `1/(2·sqrt(glin))`, so the bell's **actual Q is
`2·sqrt(glin)`** — it is *not* fixed at 2 except in the special case `glin=1` (Resonance=0). As
Resonance increases from 0→1, `glin` goes 1→6, so `Q` goes 2→~4.9 while the gain (`m1`) also
rises. Q and gain are coupled through the same `A`, by design (a proportional-Q-style bump), but
the sentence "fixed Q=2" directly contradicts that and is simply incorrect as English — even
though it's immediately followed by "identical to `hplp_bell`," which, if actually followed
literally by whoever writes the Python oracle, produces the right math anyway. The risk is that
a plan-writer or oracle-implementer trusts the prose ("fixed Q=2") over re-deriving from the
source, hard-codes `k=0.5` decoupled from `glin`, and silently breaks magnitude parity exactly
at nonzero Resonance — the one place §6 says parity is hardest to hold.

**Recommendation:** delete "fixed Q=2" or replace with the correct statement: "bell `Q =
2·sqrt(glin)`, coupled to Resonance identically to gain (both driven by `A=sqrt(glin)`); `Q=2`
only at Resonance=0." Add an oracle self-check: assert the Python bell coefficients numerically
equal `hplp_bell`'s formula at several `glin` values before trusting downstream magnitude tests.

### P1 — Mode-B sample-level timing is claimed fixed by a test-list bullet, not actually specified

Codex's P1-8 ("Mode-B Integration Needs A Sample-Level Timing Diagram") is not listed among the
"(resolves ...)" tags anywhere in rev 2 — correctly, because it isn't resolved. §10 test item 9
just appends "...and Mode-B integration paths" to a JSFX-source-guard test bullet; no
sample-index equation, no statement of where in `@sample` the linear engines sit relative to
`bus_dry`/`Lk`.

Having traced V0.5's own `@sample` order (`hplp_run` for HP then LP runs *before* the per-band
loop that contains Mode-A/B and the `bus_dry`/`Lk` lookahead mechanism, all within one sequential
`@sample` call), I believe the architecture is very likely fine as long as the FIR engines are
substituted in at the same point: they present per-sample continuous output (like Arthur's ring
buffer, not block-jumpy), so `bus_dry` downstream naturally starts capturing the
already-linear-delayed signal, and `MAXLAT = 2·(BD/2+P) + Lk` correctly reflects the total
in-stream delay only if Off/Min paths are *actually* delayed to match (per §9). But this is my
inference from re-reading V0.5's control flow, not something the spec states. Given this is
exactly the kind of order-of-operations detail that's cheap to get backwards during
transcription (e.g., a future edit that moves Mode-B ahead of HP/LP, or an Off-engine "identity
fill" that doesn't preserve exact per-sample causality), it should be pinned explicitly rather
than left to be re-derived by whoever writes the plan.

**Recommendation:** add the sample-index diagram Codex asked for (input → HP-linear-out →
LP-linear-out → Mode-A/dynamics → Mode-B detector/bus_dry/correction → final output → reported
PDC), even briefly, before calling this resolved. It's a paragraph, not a redesign.

### P2 — Phase slider number still not pinned

Codex's P2 list item explicitly asked to pin "Exact Phase slider number/default" before
planning. §3.1/§12 still only say "global, fresh bank; default Min (0)" — no literal slider
index (e.g. `slider139`). Minor, but it's the one item off the P2 checklist that rev 2 doesn't
actually close despite tagging §12 as resolving that finding. "Fresh bank" is also ambiguous:
`slider131-138` are already inside JSFX's 129-192 UI tab, so `slider139` would *not* start a new
UI tab/bank — if a new tab is actually wanted, the number needs to jump to 193+.

**Recommendation:** pin the literal number and clarify whether "fresh bank" means a new UI tab
or just an unused slider slot.

---

## Things I checked and found fine (worth stating so the spec isn't over-scrutinized)

- `fc_eff = min(freq, srate*0.49)` in §6 exactly matches V0.5's `hp_fe`/`lp_fe` computation
  (`JSFX/RCBitNova V0.5:343,353`) — correctly transcribed.
- `butter_q(k,N) = 1/(2·cos(π(2k+1)/(4N)))` in §6 is character-for-character V0.5's formula
  (`:220`) — correct.
- §7's placement encode/decode equations match `hplp_run`'s own Mid/Side/Left/Right logic
  (`:234-273`) exactly — Both/Mid/Side/Left/Right semantics are consistent between the min-phase
  reference and the spec's linear-phase contract.
- Serial-engine domain composition (HP→LP): since each engine's internal delayed-dry
  recombination produces a *uniformly* time-aligned L/R stream regardless of which lane was
  filtered, the second engine re-encoding M/S from that stream is safe — no extra leakage beyond
  what §7 already specifies per-engine. The "two-engine handoff" concern from Codex's P1-7 is
  adequately addressed by composition, not by anything extra needed in §7.
- PDC arithmetic (`BD/2+P=6144` per engine, `2×6144=12288` total) matches Arthur's own
  `pdc_delay=klen/2+P` and is internally consistent throughout §5/§9.
- FIR Brick magnitude-step tolerances (§6's closing paragraph) do substantively answer Codex's
  P1-4 ("Brickwall Is Not Infinite Slope"), even though it isn't tagged with a "(resolves...)"
  marker — content-wise it's covered.

---

## Summary ranking

| Sev | Item | Status |
|---|---|---|
| P0→downgraded | Page-safety layout | Correct test defined; **no actual layout given** — treat as must-pin-before-plan (effectively P1) |
| — | Kernel symmetry/delay | **Genuinely resolved**, verified independently |
| P1 | Phase Min↔Linear click-safety | Latency-continuity ≠ audio-continuity; gap not acknowledged |
| P1 | `hp_nsec`/`lp_nsec` Brick-in-Min | Concrete code contradiction with §3.2, unaddressed |
| P1 | Bell "fixed Q=2" | Factually wrong description, real transcription-risk vector |
| P1 | Mode-B sample-timing diagram | Still not written despite being tagged elsewhere as resolved-adjacent |
| P2 | Phase slider number/bank | Still open despite §12 claiming resolution |

**Is it plan-ready?** Not quite as-is. The architecture and the two hardest DSP questions
(symmetry/delay, magnitude-parity strategy) are sound and verified. But hand this to a plan
today and the plan will either rediscover the `hp_nsec` bug live, get the bell Q wrong in the
Python oracle, or defer page-layout again. Close the five P1s above (all are small, concrete
edits, not new design work) and it's ready.
