# RCBitNova V1.1 — Eight EQ bands, four of them dynamic

**Date:** 2026-08-19 (**rev 4**, after two weakness reviews and Fable — dispositions in §9, §10, §11)
**Branch:** `rcbitnova`
**New file:** `JSFX/RCBitNova V1.1` (copy of V1.0). `rcbitnova-v1.0` remains the fallback tag;
V1.0 and earlier are frozen.

---

## 1. Goal

Four bands is not enough for mixing or mastering work. Raise the static EQ to **eight bands**,
keeping the **dynamics on the first four**.

The roadmap has tied "expand to 8 bands" to the GUI since V0.3, because the blocker was
reachability: 95 sliders were already unmanageable, and 131 would have been worse. V1.0's graph
removes that blocker — each additional band node costs the user nothing.

## 2. Why this split, and what it saves

The owner first asked for eight *fully* dynamic bands, then revised after seeing the cost. The
revision is worth recording, because the difference is not incremental:

| | 8 dynamic bands | **8 static, 4 dynamic** |
|---|---|---|
| Mode B delay rings | +32768 words | **unchanged** |
| `lp_base` | moves 65536 → 131072 | **unchanged** |
| Low fixed-address arrays | must be re-laid out | **all fit as-is** |
| New sliders | ~84 | **36** |
| Audio-path risk | high | low |

Verified against the shipped layout. **Two arrays end EXACTLY on their neighbour's address with
zero slack** — rev 1 said `cf` had "64 words of 96 available", which was wrong: it counted to
`det` @96 and overlooked `st` @64 sitting between them.

| Array | Per band | At 8 bands | Occupies | Next array | Slack |
|---|---|---|---|---|---|
| `cf` @0 | 8 | 64 | 0…63 | `st` @**64** | **zero** |
| `st` @64 | 4 | 32 | 64…95 | `det` @**96** | **zero** |
| `dp` @192, `dm` @208, `bp` @216 | — | unchanged | — | — | stay at 4 bands |

**`bp` is dynamic, not static** (rev-2 review P0-2). rev 2 put it in the eight-band column; the
code says otherwise — it is written only by `setup_band_dyn` and read only by Mode A and Mode B,
never by the static SVF path. Expanding it would have allocated 12 words that nothing writes and
nothing reads.

Eight bands is therefore the **maximum this layout supports without moving anything**. A ninth
band would silently overwrite `st`, and `st` at nine would overwrite the detector coefficients.

Acceptance tests assert **adjacency, not upper bounds** (review P0-1) — `cf ≤ 96` would pass an
implementation that destroys `st` entirely:

```
cf + N_BANDS * 8 == st   == 64
st + N_BANDS * 4 == det  == 96
bp + N_DYN * 3   <= eg   == 256
```

with sentinel values written either side of every expanded array, checked after coefficient setup
**and** after audio processing.

## 3. Architecture: two counts, not one

`N_BANDS = 8` for static EQ; a new `N_DYN = 4` for everything dynamic. Every loop and every
allocation takes whichever applies:

| Uses `N_BANDS` (8) | Uses `N_DYN` (4) |
|---|---|
| `cf` static coefficients | `det`, `dst` detector coefficients and state |
| `st` static state | `cst` Mode-A cut state |
| `gc_kc` GUI coefficients (see §2.1) | `bp` band params — **written by `setup_band_dyn` only** |
| `setup_band`, the static pass | `dp`, `dm` dynamics params and stereo mode |
| the GUI's nodes, traces and readout | `eg`, `egh` Mode-A envelopes |
| | `mb_band`/`mb_peak`/`mb_end` Mode-B rings |
| | `mbenv`, `mbgc`, `mbeh`, `mbwpos`, `hc` |

### 2.1 The GUI scratch must grow, and that moves two bases (rev-2 review P0-1)

`gc_kc` holds the GUI's own band coefficients — 8 words per band, 32 today — and `gc_fc` starts
immediately after it. At eight bands `gc_kc + b*8` for B5–B8 would overwrite the first 32 words
of `gc_fc`, i.e. the GUI's HP/LP coefficients. I checked every audio array for this and missed the
scratch I added in V1.0.

Pinned: **`gc_kc` grows to 64 words; `gc_fc` and `gc_ebuf` shift up by 32**, and the initialiser's
clear span goes from 13638 to **13670**. So verification cannot ask that *every* `gc_*` base be
unchanged — it asks that:

- every **audio** base is unchanged (§6.3), and `lp_base` stays 65536;
- the `gc_*` region stays wholly below `lp_base` and internally non-overlapping.

Bands 5–8 have no detector, no Mode-B ring and no ceilings — not disabled ones, but none
allocated. That is what keeps the memory flat.

**The `@sample` band loop splits in two**: bands 0–3 run the existing full path; bands 4–7 run
static filtering only. The dynamics branch is not entered for them at all.

### 3.1 Signal order — normative (review P0-4)

The plugin is not one per-band cascade: static filtering and Mode A happen in the first pass,
Mode B is a **later nonlinear pass**. "Bands 5–8 are static only" therefore has two readings that
sound different, and the spec must pick one:

```
input
  -> HP / LP section
  -> bands 1-4: static SVF + Mode A          (existing first pass)
  -> bands 5-8: static SVF                   (NEW - joins the same first pass)
  -> bands 1-4: Mode B split limiting        (existing nonlinear pass)
  -> output trim
```

**Bands 5–8 run in the first pass, before Mode B.** Consequence, stated plainly: a boost on B5
*is* seen by B1–B4's Mode-B detection and limiting. That is the consistent reading — Mode B has
always operated on whatever the static EQ produced — and it is what makes an 8-band EQ behave
like one EQ rather than two stages with a limiter wedged between them.

**The split must be STRUCTURAL, not conditional** (rev-2 review P0-3). V1.0's "static" section is
not actually free of dynamics: before any filtering it evaluates `dp[b*4+3] == 1 && dm[b] == 2`
to decide whether Placement Both means L/R or M/S. Simply raising the loop bound to 8 would read
past the four-band arrays *before* B5's filter ever runs — a read overrun, not a write one, and
therefore invisible to write canaries.

So bands 5–8 get their **own loop**, in which:

- Placement Both always means **L/R** (there is no dynamics mode that could make it M/S);
- **no expression mentions** `dp`, `dm`, `mbmode`, `bp`, `det`, `dst`, `cst`, `eg`, `egh` or `hc`.

A source audit enforces that list against the B5–B8 loop body. That is a stronger guarantee than
"we guarded the dynamics branch", and it is checkable mechanically.

Test that distinguishes the orders: enable a B5 boost that pushes a B1 Mode-B band over its
ceiling. In the chosen order Mode B reacts to it; in the rejected order it does not.

### 3.2 Every `N_BANDS` site, enumerated (review P0-3, Fable P0)

Fable's finding: **`@init` computes every downstream address by multiplying the literal
`N_BANDS`**, so `N_BANDS = 8` alone silently relocates the entire map. Missing `mb_peak`/`mb_end`
alone shifts everything after them by **16384 words** — including `hplp_state`, the GUI block and
`lp_base` — with no crash and no error, just a plugin whose memory map no longer matches the one
this spec calls "unchanged".

rev 3 called this "several address calculations". It is 28 sites, listed here so the
implementation is transcription rather than judgement:

| Line | Section | Site | Becomes |
|---|---|---|---|
| 138 | `@init` | `N_BANDS = 4` | `N_BANDS = 8; N_DYN = 4;` |
| 141 | `@init` | `memset(st, …)` | **`N_BANDS`** (static state) |
| 151, 152 | `@init` | `memset(dst)`, `memset(cst)` | `N_DYN` |
| 153 | `@init` | `eg` init | `N_DYN` |
| 159, 160 | `@init` | `mb_peak`, `mb_end` | `N_DYN` ← **the 16384-word one** |
| 163, 164, 165 | `@init` | `mbmode`, `mbwpos`, `bus_dry` | `N_DYN` |
| 168, 169, 172 | `@init` | `mbenv`, `mbwpos`, `mbgc` init | `N_DYN` |
| 173, 174, 176 | `@init` | `mbeh`, `hc`, `egh` bases | `N_DYN` |
| 175, 177 | `@init` | `mbeh`, `egh` init | `N_DYN` |
| 185 | `@init` | `hplp_state = egh + …` | `N_DYN` |
| 1019, 1032 | helpers | `gc_domain_bits`, `gc_dom_used` | **`N_BANDS`** |
| 1096 | `@slider` | `setup_band(b); setup_band_dyn(b);` | **split**: `setup_band` over `N_BANDS`, `setup_band_dyn` over `N_DYN` |
| 1103 | `@slider` | Mode-B scan (`hc`, `mbmode`) | `N_DYN` |
| 1290 | `@sample` | the band loop | **split** into the two loops of §3.1 |
| 1489 | `@sample` | Mode-B pass | `N_DYN` |
| 1675, 1749, 1828 | `@gfx` | coefficients, hit-test, node drawing | **`N_BANDS`** |

Seventeen sites become `N_DYN`, eight stay `N_BANDS`, two split. Anything not on this list keeps
its current meaning.

**Confirmed safe to run at eight bands** (Fable, verified in code): `setup_band` and `band_qeff`
read only sliders and touch no dynamic array, so they need nothing beyond routing their internal
`10*(b+1)` through `band_slider_base`.

### 3.3 Runtime canaries

`N_BANDS` currently drives allocation, initialisation, `setup_band`, `setup_band_dyn`, the
`@slider` Mode-B scan, Mode-A processing, Mode-B processing, envelope resets and several address
calculations. Leaving one dynamic site at 8 would reinterpret hard-ceiling sliders as B5
dynamics controls or write past the four-band arrays.

The implementation starts by inventorying every occurrence and labelling it static or dynamic,
and the acceptance suite includes runtime canaries around `det`, `dst`, `cst`, `dp`, `dm`, `eg`,
`egh`, `mbenv`, `mbmode`, `mbwpos`, `mbgc`, `mbeh` and `hc` while all four new bands are being
driven hard.

## 4. Sliders

Bands 1–4 keep their numbers exactly — `11–49` static, `51–88` dynamics, `91–123` ceilings.
**Nothing in that range moves.** REAPER stores parameters by number, so any shift would silently
corrupt every existing project.

Bands 5–8 take **151–189**, nine per band in the same order as bands 1–4:

```
15x1 Enable · 15x2 Type · 15x3 Freq · 15x4 Q · 15x5 Macro
15x6 Micro  · 15x7 Bit Ratio · 15x8 Placement · 15x9 Q Character
```

Explicit ranges, since they are not contiguous: **151–159, 161–169, 171–179, 181–189**.

**Reads** go through one helper instead of open-coded arithmetic:

```
function band_slider_base(b) ( b < 4 ? 10 * (b + 1) : 150 + 10 * (b - 4); );
```

A source audit rejects the old open-coded `10 * (b + 1)` outside this helper (review P1-8): V1.0
open-codes it in coefficient setup, curve construction, domain visibility, hit-testing, node
drawing, drag start, wheel handling and the readout. One missed site makes B5–B8 read
non-existent sliders while the rest of the UI looks correct.

**Writes must NOT use the helper** (review P0-2). V1.0 established that assigning through
`slider(computed_index)` updates what the GUI reads back but never reaches the parameter. So each
writer needs an explicit **eight-way** named branch:

```
b == 0 ? ( slider15 = v; slider_automate(slider15); ) :
...
b == 7 ? ( slider185 = v; slider_automate(slider185); );
```

This matters more than it looks: V1.0's writers branch on B1–B3 and **fall through to B4**, so
without this change dragging B5–B8 would silently edit B4.

**`setup_band_dyn(b)` must be guarded by `b < N_DYN`.** Every V1.0 writer calls it
unconditionally; at `b ≥ 4` it would write past `det`, `dp` and `dm` into neighbouring arrays —
memory corruption from an ordinary mouse drag.

**Defaults for the new bands:** Enable off, Bell, Q 0.707, Macro 0, Ratio 1, Placement Both,
Q Character 0. Frequencies spread so the nodes do not stack: **150 / 700 / 5000 / 15000 Hz**.
An old project therefore opens with four inaudible extra bands.

## 5. GUI

Already parameterised by `N_BANDS`, so nodes, traces and hit-testing scale by changing the
constant. Two additions:

- The readout names the band (`B5`), and the numeric fields address it through the same
  `band_slider_base` helper.
- **A right-click menu on a band node** for the parameters gestures cannot reach (rev-2 review
  P0-4): **Enable/Disable, Type (Bell / Low Shelf / High Shelf), Placement (Both / Mid / Side /
  Left / Right), Q Character**. V1.0's GUI reaches only six of a band's nine parameters, and has
  no way to switch a band *off* — clicking a disabled node enables it, and that gesture has no
  inverse. Without this, B5–B8 would be usable only as Bell / Both / constant-Q bands, which
  contradicts the whole premise that the graph removed the reachability blocker. The menu mirrors
  the HP/LP one that already exists, and every write is an explicit named-slider branch.
- Bands without dynamics are visually distinguishable by a **thinner node outline** **and** a
  textual `DYN` / `STATIC` tag in the selected-band readout (review P2-1). Outline thickness alone
  is fragile: it can vanish under Retina scaling, disabled styling or reduced contrast.
- **Overlapping nodes need a way out** (review P1-7). Spread defaults only prevent overlap on
  first load; with eight bands, coincident nodes are likely, and V1.0's loop-based hit-test makes
  only one of them reachable. Pinned precisely (rev-2 review P2): the hit set is every node within the hit radius of the
  pointer, **including disabled ones**; the first click selects the lowest-numbered band in that
  set, and each subsequent click **at the same position within 400 ms** advances to the next in
  band order, wrapping. Pointer movement beyond the hit radius, or the timeout, resets to the
  lowest. Cycling overrides selected-node priority — otherwise the selected node would trap the
  cursor and the others stay unreachable. A compact **B1…B8 selector
  strip** beside the readout gives a deterministic way to reach any band regardless of overlap.

## 6. Verification

### 6.1 Oracle

1. `band_slider_base` returns 10/20/30/40 for bands 0–3 and 150/160/170/180 for bands 4–7.
2. **Adjacency, not upper bounds**: `cf + 8*8 == st == 64`, `st + 8*4 == det == 96`.
3. The `gc_*` region: `gc_kc` is 64 words, `gc_fc`/`gc_ebuf` follow without overlap, the clear
   span equals the region size (13670), and the whole region ends below `lp_base`.
4. A curve over 8 bands equals the curve over the same 4 when bands 5–8 are disabled.
5. **Each new band is correct on its own**: for B5…B8 individually, compare the response against
   the oracle across Bell / Low Shelf / High Shelf, every placement, positive and negative gains,
   constant vs proportional Q — then a multi-band case. "Eight nodes change the sound" would pass
   with B5 controlling B8.

### 6.2 Three kinds of memory test, kept distinct (rev-2 review P1-1)

The corrected arithmetic means `cf` ends exactly where `st` begins and `st` exactly where `det`
begins. **There is no spare word for a guard**: a sentinel at `cf[64]` *is* `st[0]`, which audio
legitimately changes. rev 2 asked for canaries either side of every array, which is impossible
here — so:

| Test | Where |
|---|---|
| exact address arithmetic | source-level assertions against the production layout |
| bounds / overrun detection | an **instrumented shadow layout** in the Python model, with real guard words |
| invariants | on the real compact layout, checking values rather than sentinels |

### 6.3 Every audio base address, in order, unchanged (rev-2 review P1-2)

Word indices — not "byte-equal", which is wrong for EEL2 memory:

`mb_band`, `mb_peak`, `mb_end`, `mbenv`, `mbmode`, `mbwpos`, `bus_dry`, `mbgc`, `mbeh`, `hc`,
`egh`, `hplp_state`, `hplp_cf`, `lp_rt`, `lp_kc`, `lp_ks`, `lp_geo`, `lp_off`, `lp_fs`, `lp_base`.

rev 2 omitted `lp_kc`, `lp_ks`, `lp_geo`, `lp_off`, `lp_fs`, any of which can invalidate the
packed-engine geometry while the listed endpoints still match. The `gc_*` bases are exempt by
§2.1 but must stay below `lp_base` and non-overlapping.

### 6.4 Null test — an executable contract (rev-2 review P1-4)

**48 kHz, block 512, 30 s of deterministic material, GUI closed, fresh instances, no automation.**
State is transferred programmatically, not dialled by hand. Render both versions to file and
compare **sample for sample with zero tolerance**; a length or reported-latency mismatch is a
failure, not a caveat. Cases: default state; all four original bands active in **Mode A**; the
same in **Mode B**; and both **Min** and **Linear** topologies — a single default-state null does
not exercise the loops being edited.

Wording: **bit-identical audio while B5–B8 are disabled**. Not "costs nothing" — four extra
enable checks are not free, and that cost is measured separately below.

### 6.5 CPU — regression and feature cost are different questions (rev-2 review P1-5)

| Comparison | Question |
|---|---|
| V1.1 with B5–B8 **disabled** vs V1.0 | **regression** — must be within +5 % |
| V1.1 eight bands enabled vs V1.1 four enabled | **feature cost** — informational, no ceiling |

48 kHz, blocks 128 and 512, five 60-second runs each, first discarded as warm-up, compare the
**median** of the per-run peak block time rather than one maximum — a single 60 s max is decided
by one unrelated OS spike. **Zero xruns is an absolute gate** in every configuration.

### 6.6 Migration — one mechanism, not a list (rev-2 review P1-3)

rev 2 offered "preset or FX-chain copy" and claimed automation survives. Those are different
operations with different semantics, and the claim was untested. Also, §4 said an old project
"opens with four extra bands" while §6 said it reopens V1.0 — both cannot be true. **V1.1 is a
new file, so an old project reopens V1.0 and is unaffected.**

The single supported operation: a **ReaScript/reapy migration script** that inserts a V1.1
instance, copies all 95 old parameter values by host index, leaves the 36 new ones at their
defaults, and removes the V1.0 instance. Automation envelopes are **explicitly out of scope** —
if a parameter is automated, the script reports it and leaves that instance alone rather than
silently dropping the envelope.

### 6.7 Live in REAPER

- Eight nodes drag, select and edit; overlapping nodes cycle; `DYN`/`STATIC` reads correctly.
- **Reachability matrix**: every one of the nine parameters of B5–B8 can be set and read back
  from the graph alone, without opening the parameter list.
- **Signal order** (§3.1): a B5 boost pushing a B1 Mode-B band over its ceiling must be seen by
  Mode B.
- **Parameter manifest**: V1.0's host parameter list (index, name, min, max, step, default,
  round-trip value) is a strict prefix of V1.1's, with the 36 new parameters appended, never
  interleaved.

## 7. Out of scope

- Dynamics on bands 5–8. If the owner ever needs them, it is a separate version with the memory
  re-layout described in §2 — and the cost is known in advance now.
- Spectrum analyser (V1.2) and the dynamics display (V1.3), both already deferred.

## 8. Method

Unchanged: verify in Python first → TDD the oracle → transcribe to JSFX → live-verify with the
owner → Fable final review → tag `rcbitnova-v1.1`.

**Carried forward from V1.0's seven live defects** (spec §16 of the V1.0 design), because this
version touches the same seams: write sliders by name and never through a computed index;
recompute dependants inline rather than trusting `@slider`; quantise mouse writes to the declared
step; and check function definition order — EEL2 resolves in file order, which broke four builds.

## 9. Weakness-review disposition (rev 1 → rev 2)

| Finding | Disposition |
|---|---|
| **P0** the `cf` bound is wrong and would permit an overlap | **Accepted — my error.** rev 1 said "64 words of 96 available"; it counted to `det` @96 and missed `st` @64 in between. `cf` and `st` each end **exactly** on their neighbour with zero slack, so eight bands is the maximum this layout holds. Tests now assert adjacency (§2) |
| **P0** the GUI writers map every band above B3 to B4 | **Accepted** — V1.0's writers branch B1–B3 and fall through to B4, so B5–B8 would have edited B4. Eight-way named writes required; the read helper must not be used for writes (§4) |
| **P0** `setup_band_dyn` would corrupt memory for B5–B8 | **Accepted** — guarded by `b < N_DYN`. Every V1.0 writer calls it unconditionally, so an ordinary drag on B5 would have written past `det`/`dp`/`dm` (§4) |
| **P0** no exhaustive static/dynamic inventory | **Accepted** — every `N_BANDS` site is classified before coding, with runtime canaries around all dynamic arrays (§3.2) |
| **P0** DSP order relative to Mode B undefined | **Accepted** — normative stage diagram; bands 5–8 join the first pass, so Mode B *does* see them, with a test that distinguishes the two orders (§3.1) |
| **P1** old-project compatibility is not a migration | **Accepted** — the supported state-transfer operation is stated and tested, including off-grid values and automation (§6) |
| **P1** slider IDs alone are not a parameter ABI test | **Accepted** — full host parameter manifest compared prefix-wise (§6) |
| **P1** the null gate is under-specified and "costs nothing" overclaims | **Accepted** — reproducible fixture pinned, reworded as bit-identical audio, disabled CPU measured separately (§6) |
| **P1** nothing proves an enabled new band is correct | **Accepted** — per-band oracle comparison across types, placements, gains and Q modes, plus a multi-band addressing case (§6) |
| **P1** `mb_end` alone does not prove the layout stayed flat | **Accepted** — every downstream base address asserted byte-equal (§6) |
| **P1** the helper is tested but its adoption is not | **Accepted** — source audit rejects open-coded `10*(b+1)` outside the helper, with named writes exempt (§4) |
| **P1** eight nodes make overlap a reachability problem | **Accepted** — selected-node priority, click cycling, and a B1…B8 selector strip (§5) |
| **P1** the CPU check has no pass/fail contract | **Accepted** — fixture, zero xruns, peak-block ceiling (rev 3 tightened this to +5 % and split regression from feature cost — see §6.5, which is authoritative) |
| **P2** outline thickness is a fragile cue | **Accepted** — plus a `DYN`/`STATIC` tag in the readout (§5) |
| **P2** "ninth band node"; "151–189" implies contiguity | **Accepted** — reworded; the four ranges are listed explicitly (§1, §4) |

## 10. Rev-2 weakness review disposition (rev 2 → rev 3)

Four P0s, all accepted. Three of them are facts about the shipped V1.0 code that I asserted
without checking.

| Finding | Disposition |
|---|---|
| **P0** eight GUI coefficient sets cannot fit while every `gc_*` base stays unchanged | **Accepted, verified.** `gc_kc` is 32 words and `gc_fc` starts immediately after it, so B5–B8 would overwrite the GUI's HP/LP coefficients. I checked every audio array for this and missed the scratch I added myself in V1.0. `gc_kc` grows to 64, `gc_fc`/`gc_ebuf` shift, the clear span becomes 13670, and verification now demands unchanged **audio** bases rather than all bases (§2.1) |
| **P0** `bp` is dynamic state, not an eight-band static array | **Accepted, verified.** Written only by `setup_band_dyn`, read only by Mode A/B. rev 2 would have allocated 12 words nothing writes and nothing reads (§2) |
| **P0** the "static" loop reads `dp` and `dm` before filtering | **Accepted, verified.** V1.0 evaluates `dp[b*4+3] == 1 && dm[b] == 2` to choose the domain, so raising the loop bound alone is a **read** overrun — invisible to write canaries. Bands 5–8 get their own loop that mentions no dynamic array, enforced by a source audit (§3.1) |
| **P0** the GUI cannot reach a new band's full contract | **Accepted.** V1.0 reaches six of nine parameters and has **no way to switch a band off** — the enable gesture has no inverse. A right-click menu adds Enable/Disable, Type, Placement and Q Character (§5). Without it the premise "the graph removed the reachability blocker" is only two-thirds true |
| **P1** canaries either side are impossible at zero-slack boundaries | **Accepted** — three distinct kinds of memory test; guard words live in an instrumented shadow layout, never in the production one (§6.2) |
| **P1** the downstream manifest is incomplete and uses the wrong unit | **Accepted** — full ordered list including `lp_kc`/`lp_ks`/`lp_geo`/`lp_off`/`lp_fs`, compared as word indices (§6.3) |
| **P1** migration is an unresolved alternative, and two sections contradict | **Accepted** — one mechanism (a reapy script), automation explicitly out of scope, and the contradiction removed: an old project reopens V1.0 and is unaffected (§6.6) |
| **P1** the null fixture has no executable comparator | **Accepted** — fixed rate/block/duration, render to file, zero-tolerance sample comparison, and cases covering Mode A, Mode B, Min and Linear (§6.4) |
| **P1** the CPU ceiling mixes regression with feature cost | **Accepted** — split into two comparisons, median of five runs after a discarded warm-up, zero xruns absolute (§6.5) |
| **P2** coincident-node cycling is not operationally defined | **Accepted** — hit set, order, 400 ms reset, and precedence over selected-node priority (§5) |

## 11. Fable review disposition (rev 3 → rev 4)

| Finding | Disposition |
|---|---|
| **P0** the spec verifies half the memory map; `@init` computes every downstream address from the literal `N_BANDS` | **Accepted.** rev 3 called this "several address calculations" — it is **28 sites**, and missing `mb_peak`/`mb_end` alone relocates everything after them by 16384 words silently. §3.2 now enumerates every line with its target constant, so implementing this is transcription rather than judgement |
| **P1** the acceptance block still sized `bp` by `N_BANDS`, contradicting the paragraph above it | **Accepted** — the leftover line now reads `bp + N_DYN * 3`. Exactly the "stated as fact, contradicted two lines up" pattern this spec has already been burned by |
| **P2** §9's historical table quotes a +10 % CPU ceiling that §6.5 tightened to +5 % | **Accepted** — the historical row now points at §6.5 as authoritative |

**Verified independently by Fable against the shipped code, no change needed:** `cf + 8*8 == st == 64`
and `st + 8*4 == det == 96` exactly, with zero slack; `gc_kc`/`gc_fc`/`gc_ebuf` sizes and the
13638 → 13670 clear span; `lp_base` is computed rather than hardcoded, so it legitimately stays
65536; `bp` is written only by `setup_band_dyn`; the static loop really does read `dp`/`dm` before
filtering, so the dedicated loop is the only sound fix; `setup_band` and `band_qeff` are purely
static; the open-coded `10*(b+1)` appears in exactly the sites §4 lists, and today reads the wrong
sliders for `b ≥ 4`; every `gc_w_*` writer falls through to B4 for any band ≥ 3 and calls
`setup_band_dyn` unconditionally; sliders 151–189 are free (highest declared is 142); and
inserting the B5–B8 loop between the existing band loop and the Mode-B pass is hazard-free —
Mode B captures its input after the static pass by design, so there is no feedback or
lookahead-ring conflict.

**One item Fable could not verify without REAPER:** that `slider189` actually registers. The file
already goes to 142, well past the classic 64-slider limit, so it is very likely fine — but it is
the first thing to check live, before any other work, because everything else depends on it.
