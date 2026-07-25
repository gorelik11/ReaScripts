# RCBitNova V0.7 — High-Resolution Linear-Phase HP/LP — Adversarial Design Review (Fable)

**Scope:** `docs/superpowers/specs/2026-07-25-rcbitnova-v0.7-hires-linear-phase-design.md`, cross-checked
against the as-shipped `JSFX/RCBitNova V0.6` source, `tools/rcbitnova_dsp.py` (oracle), the V0.6 design
spec (§9–§15), my own prior V0.6 final review, the REAPER JSFX SDK docs
(`advfunc.php`, `js.php`), and `linear_artur_slope_7.jsfx`. Role: error-finding only, not rewriting.

## Verdict up front

**NOT READY FOR A PLAN — one P0 blocker (concrete, proven with the actual oracle numbers), plus
one P0-adjacent claim (§4 lazy-commit) that is asserted without evidence and is contradicted by
the spec's own engine layout under the most natural reading of the mechanism it describes.**
Everything else in the spec (§6 FFT-ceiling hypothesis, §5 per-partition layout, PDC arithmetic,
kernel-rebuild cost, oracle test design) is sound or only needs P1/P2 tightening. This is a good,
disciplined spec — the two P0s are narrow and fixable without rearchitecting.

---

## P0-1 — The dry ring is hard-capped at 16384 words; `lp_lat` at BD=32768 is 18432. Real overflow, proven with the spec's own numbers.

**Where:** `dryA` (`JSFX/RCBitNova V0.6` lines 402/408-411/196608 offset) is written and read through
a ring whose wrap is a **hardcoded literal `16384`** in four places:

```
dryA[dwp] = comp;
drd = dwp - lp_lat; drd < 0 ? drd += 16384;
cd = dryA[drd];
dwp += 1; dwp >= 16384 ? dwp = 0;
```

`lp_lat = lpBD/2 + lpP`. At Normal (BD=8192) that's 6144 — comfortably inside the 16384-word ring.
At High (BD=32768) it's **18432 — 2048 words past the ring's capacity.** The wrap logic only
compensates a single 16384 deficit (`drd < 0 ? drd += 16384`); it does not handle `lp_lat > 16384`
at all. The result for any engine set to High **while its Placement is Mid/Side/Left/Right** (the
`pl != 0` branch is the only one that touches `dryA` at all — `Both` bypasses it) is that the
complementary/untouched lane reads stale or wrapped-wrong history: silent, non-obvious corruption
of the untouched channel, not a crash. Given the spec's own headline use case is "HP = High (deep
sub-bass low-cut) + LP = Normal," and Placement=Both is not the only realistic setting, this will
be hit in ordinary use, not just at a parameter extreme.

**This is not hypothetical — I reproduced it from the spec's own oracle.** `tools/rcbitnova_dsp.py`
`lp_engine_buffers(BD, P)` (lines 1159-1179), the function the spec cites in §7 as proof "no new
production helpers are needed," **hardcodes `dryA`/`dryB`/`outA`/`outB` at a fixed 16384 regardless
of the `BD` parameter** — it is not actually resolution-aware for these four buffers, only for the
FFT-touched ones. Running it directly:

```
BD=8192:  lp_lat=6144,  dryA capacity=16384 -> ok
BD=32768: lp_lat=18432, dryA capacity=16384 -> OVERFLOW (2048 words short)
```

and the total-footprint number the spec quotes in §4 — **"hi-res needs 622592"** — is exactly what
`lp_engine_buffers(32768, 2048)` returns *with the undersized 16384-word `dryA`/`dryB` baked in*. In
other words, the spec's own memory-budget arithmetic already encodes the bug rather than the fix.

**The fix is cheap and fits inside the already-reserved budget.** If `dryA` (and `dryB`, currently
unused padding) are sized to the next convenient round number that covers `lp_lat_max = 18432`
— e.g. 32768, matching the ring-power-of-two convention already used elsewhere in the engine
block — the corrected hi-res per-engine total becomes `622592 - 16384 + 32768 = 638976`, which is
still **under the 655360-word slot** the spec already reserves (16384 words of slack remain). So
this is not a scope/latency change, just: (a) size `dryA` per-engine from `lp_lat` (or a
conservative max), and (b) replace the four hardcoded `16384` literals in `lpk_run`/`lpk_process`
with a per-engine ring-size variable read from the same offset table §5 already proposes for
everything else. **§5 item 1 (per-engine offset table) does not mention this** — it enumerates
`hspec = eb + 32768`-style hardcodes as the thing being fixed, but the `16384` ring-wrap literals
are a different kind of hardcode (a *size*, not an *offset*) and are not called out. Recommend
adding it explicitly to §5 and to the "grep the JSFX for 8192/16384/... literals" audit the spec's
own review brief asked for — this literal is exactly the kind of thing that grep would have caught.

**Verification gap this also exposes:** §7's planned test 4 ("Slot arithmetic... 655360-word slot
holds the hi-res layout") checks total footprint, not per-buffer adequacy against `lp_lat`; it
would not have caught this. Recommend a dedicated oracle test: `dryA size >= lp_lat(BD) + 1` for
every `(BD, P)` pair the plan supports, asserted directly against `lp_lat`, not against a
constant.

---

## P0-2 — The "hi-res is free when off" claim (§4) is asserted, not verified, and is not obviously true under the mechanism the spec itself proposes

§4 states: "JSFX commits memory lazily by highest-touched address, so in Normal the hi-res part of
a slot is never touched and never committed... Reserving address space is free; touching it is not."
This is the owner's explicit decision criterion for making the feature "free when unused" — the spec
itself flags it as consequential, and the review brief asked me to check it specifically.

Two problems:

1. **No source is cited for "commits lazily by highest-touched address."** I could not find this
   documented in the REAPER JSFX SDK pages (`advfunc.php`, `js.php`) — they describe a
   `__memtop()` query and a `maxmem=`/`prealloc=` directive, but say nothing about the commit
   granularity or algorithm. The oblique evidence that *does* exist points the other way: the
   documented "FFT/convolution must not cross a 65,536-item boundary" rule is most plausibly
   explained by local memory being backed by **discrete 65536-item pages/blocks allocated
   per-page on first touch** (which is why an operation straddling two blocks can silently break)
   — i.e. a **sparse per-page allocator**, not a single monotonic "everything below the
   highest-touched address is committed" scheme. Those two mechanisms have opposite implications
   for this design:
   - *Per-page sparse allocation* (more consistent with the boundary-rule evidence): touching
     engine 1's low buffers does **not** force-commit engine 0's untouched high pages. §4's
     conclusion would hold.
   - *Highest-touched-address commit* (what the spec's prose literally describes): touching **any**
     address commits everything below it.
2. **Under the spec's own literal mechanism, its own layout falsifies the claim.** Engine 1's base
   is `lp_base + 655360`, which is *above* engine 0's entire hi-res span (`lp_base + 622592` at
   most). Both engines run **unconditionally** in Linear mode regardless of Slope/Off (confirmed in
   the shipped V0.6 source — `lpk_process` is called for HP and LP with no `nsec>0` guard, and the
   V0.6 spec/final-review both document "Off engines stay warm"). So in Linear mode, engine 1's own
   buffers are touched on essentially every sample **regardless of either engine's Resolution
   setting**. If the "highest-touched-address" model in §4's own prose is taken literally, then the
   simple act of using Linear mode at all — HP=Normal, LP=Normal, nothing set to High — already
   touches an address past engine 0's entire hi-res footprint, and by the stated mechanism would
   commit it. That is the exact opposite of "free when off."

**This needs to be resolved before planning, not assumed.** Recommend: (a) do not take the
mechanism on faith — add a live smoke test alongside the §6 `fft(32768)` smoke test: load V0.7 with
both Resolutions=Normal, run for a while, and check REAPER's actual memory footprint (Task
Manager/Activity Monitor RSS, or `__memtop()` logged to the console) before and after also touching
a High-resolution engine, to see empirically whether the Normal-only footprint stays near V0.6's
~3.5 MB or jumps to the ~5 MB two-engine hi-res total; (b) if it turns out address-order matters,
the layout is trivially fixable by placing whichever engine is more likely to be low-cost-when-off
lower in address space, or — more robustly — not relying on lazy commit at all and instead
accepting the full ~5 MB hi-res reservation as the honest cost (JSFX local memory budgets are not
tight enough for this to matter — see the V0.6 spec §11 aside: "there is no hard total-page cap").
The owner's stated decision criterion ("free when unused") may simply not need to be true for the
feature to be worth shipping; if so, say that plainly in the spec rather than resting on an
unverified mechanism.

---

## Findings that are sound (verified, not just re-read)

- **§6 `fft(32768)` page-boundary hypothesis: CONFIRMED, not just plausible.** I fetched the
  primary SDK docs. `advfunc.php` states the FFT size list explicitly includes `32768` as a legal
  size (not merely "documented ceiling," an enumerated legal value), and states the boundary rule
  in "item" units with a worked example (a 256-point FFT = 512 items, i.e. items = real/imag array
  slots — the same unit `desbuf[i*2]`/`desbuf[i*2+1]` addressing already uses throughout the JSFX).
  So there is **no items-vs-words ambiguity** that changes the math: a 32768-point complex FFT
  buffer is exactly 65536 items, and the documented rule ("must NOT cross a 65,536 item boundary")
  means such a buffer is legal **only** starting on a page boundary — exactly the spec's hypothesis.
  The same rule text is repeated verbatim for `convolve_c`. Arthur's "practical ceiling of 8192"
  comment in `linear_artur_slope_7.jsfx` (line 6: "omija sufit fft() 8192" — "bypasses the fft()
  8192 ceiling") reads as his own workaround/folklore, not a documented hard limit — consistent
  with the spec's framing. **Do the §6 smoke test first regardless** — the docs confirm the design
  is legal, not that REAPER's actual implementation is bug-free at that size, which is exactly what
  the owner's "never worked in past attempts" experience is warning about.
- **The 655360-word slot size is a good, non-obvious design choice, worth calling out explicitly in
  the spec (it currently reads as an arbitrary "worst case + margin" number).** `655360 = 10 ×
  65536` is an exact multiple of the page size, so if `lp_base` is page-aligned (it is, per the
  existing `ceil(x/65536)*65536` code), then **engine 1's base is automatically also page-aligned**
  — which is exactly the precondition engine 1's own `desbuf` needs at BD=32768 (a full-page span
  that must start on a page boundary). Recommend the spec state this reasoning explicitly rather
  than leaving it implicit; it's the kind of thing that looks like a coincidence until someone
  checks, and a future edit to the slot size (e.g. "let's trim it to save memory") could silently
  break page-safety with no compile-time signal — the same fragility class my prior V0.6 review
  flagged (P2, `229376` stride at half-page offset).
- **§5 per-partition layout (Hspec/fdlA/fdlB) is unaffected by Resolution in the way that matters
  most.** `P`/`B` stay fixed, so `PB2` (each partition's span) stays 8192 items at both
  resolutions — only `KMAX` (partition count) grows 4→16. Each partition is still well under a page
  and the existing alignment strategy (base aligned to a multiple of `PB2`) is unchanged in kind,
  just repeated more times. This part of §5's "everything else carries over unchanged in structure"
  claim holds up.
- **Latency/PDC formula (§3, §6 excepted) is arithmetically correct** against V0.6's actual
  `pdc_delay`/`lp_lat` code: per-engine `BD/2+P` generalizes cleanly to a per-engine value, series
  composition (`lat_hp+lat_lp`) matches V0.6's `2*(BD/2+P)` special case, and Mode-B's `Lk`-on-top
  policy is unaffected by resolution (Mode-B operates downstream of both linear engines regardless
  of their individual `BD`).
- **`ext_tail_size = 2 * max BD`** is a safe (if slightly loose) conservative bound: the true
  required tail is `BD_hp + BD_lp` (each engine's own FIR tail), which is always `≤ 2*max(BD_hp,
  BD_lp)`. Not a bug — offline renders keep at least as much tail as needed, possibly a bit more
  than necessary when resolutions are mixed. P2, not worth fixing.
- **Oracle test plan (§7) is well-designed apart from the two gaps above** (the dry-ring/`lp_lat`
  sizing check missing from "slot arithmetic," and the fact that `page_layout_ok` only checks
  page-crossing, never ring capacity — so neither existing nor proposed test would have caught P0-1
  on its own). Test 1's numeric margins (25 dB assert vs. 34 dB measured; group-delay/parity
  tolerances) are appropriately conservative and consistent with the stated table in §1.
- **Slider bank (141/142) is free** — confirmed against the full V0.6 slider list (nothing defined
  past `slider140`).
- **Bit-accuracy claim (§8) is untouched by this feature** — resolution only changes FFT sizes in a
  pure-filter path; no new gain/log/pow(10) surfaces are introduced by anything in this spec.

## P1s

### P1 — Kernel-rebuild cost at BD=32768 is a 4× CPU burst on (likely) the audio thread, with no crossfade — worse than the already-deferred V0.6 click issue, and not budgeted

My prior V0.6 final review flagged (P1) that Freq/Resonance/Slope changes rebuild the live `Hspec`
in place with no crossfade — audible click risk, accepted as a known V0.6 limitation, explicitly
deferred to V0.7 crossfade work (itself deferred again by this spec). V0.7 makes the **cost of each
rebuild** roughly 4× (impulse-response length, one `fft`/`ifft` at 4× the size, Kaiser-window
`lp_i0` calls 4× as many bins, and the partitioning loop runs 4× the KMAX sub-FFTs) whenever the
resolution-holding engine's Freq/Resonance/Slope changes. §6's own verification section 4 notes "the
hi-res burst is **16** `convolve_c` per hop" for the runtime path — but that undercounts by half: the
engine always processes **both lanes A and B** every hop regardless of placement (`lpk_run` doesn't
skip lane B even when `lpk_process` passes `iB=0` for non-Both placements), so it's 16×2=32
`convolve_c` calls per hop, not 16. More importantly, that number is about the steady-state runtime
cost, not the one-shot rebuild cost, which is the actual glitch risk and isn't quantified anywhere
in the spec. Recommend the plan budget/measure the rebuild's wall-clock cost at BD=32768 (worst
case: 9-section cascade + bell, srate=192k) and decide whether it's acceptable to leave unmitigated
for V0.7, same as V0.6's known limitation, or whether it needs at least rate-limiting (V0.6's design
spec §8 already calls for this and it was never implemented — recorded as a known gap, not new to
V0.7, but hi-res makes it more likely to be audible).

### P1 — §4's "one rule in code" (per-engine clear of currently-used span) needs to also gate the Kaiser-window build and any other full-BD-length loop, not just `memset`

§4 says the mandatory fix is that `memset` must become a per-engine clear of the current
resolution's used span. But `lpk_build`'s Kaiser-window construction loop (`i=0; loop(lpBD, ...
lp_win[i] = ...)`) and the impulse-response loop (`n=0; loop(lpBD, ...)`) also touch the full `BD`
span whenever a kernel is (re)built — if the window is built once at `@init` for a shared buffer
(as in V0.6) rather than per-engine/per-resolution as §5 item 3 proposes, this is fine; but the spec
should say explicitly that **every** full-BD-length loop (not just `memset`) is scoped to the
current resolution, since it's these loops, not `memset` alone, that would touch (and, if §4's
memory model is real, commit) the hi-res pages the first time a High-resolution kernel is built.
This is implied by §5 item 3 ("built when that engine's resolution changes") but should be stated
as a corollary of §4's decision criterion, in the same section, so a future implementer doesn't
treat "the memset rule" as the whole story.

## P2s

- **§7 test 1's second assertion has a thin margin.** "40 Hz HP / 48 dB/oct at 20 Hz lands within 8
  dB of the ideal IIR (measured: 6.0 dB — assert 8 dB)" — a 2 dB margin between measured and
  asserted threshold is tighter than the first assertion's margin (9 dB). Not wrong, but flag it as
  a candidate for flakiness if any future DSP tweak shifts the number; consider asserting ≤7 dB or
  documenting why 8 dB was chosen specifically.
- **`ext_tail_size = 2*max BD`** — as noted above, correct/safe but could be tightened to
  `BD_hp + BD_lp` for precision; not worth doing unless render times become a complaint.
- **The spec doesn't restate the still-open V0.6 P2s** (page-safety of the `229376` stride depending
  on an unstated numeric coincidence; `dryA` write gap on live Placement toggle) — both are
  superseded/reshaped by this spec's per-engine offset table and 655360-word slot, but the spec
  should note explicitly that the *stride* fragility is resolved (moving to an explicit
  page-multiple slot fixes it structurally) rather than leaving a reader to infer that from §5.

## Not relitigated (per the fixed-decisions list)

Crossfade-on-rebuild scope, per-filter (not global) resolution, fixed hop P=2048, no seamless
Resolution/Phase switching, Linear staying HP/LP-only — all taken as given; no comment.
