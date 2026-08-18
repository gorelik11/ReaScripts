# RCBitNova V1.1 — Eight EQ bands, four of them dynamic

**Date:** 2026-08-19 (**rev 2**, after the weakness review — disposition in §9)
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
| `bp` @216 | 3 | 24 | 216…239 | `eg` @256 | 16 words |
| `dp` @192 | 4 | — | unchanged | `dm` @208 | stays at 4 bands |

Eight bands is therefore the **maximum this layout supports without moving anything**. A ninth
band would silently overwrite `st`, and `st` at nine would overwrite the detector coefficients.

Acceptance tests assert **adjacency, not upper bounds** (review P0-1) — `cf ≤ 96` would pass an
implementation that destroys `st` entirely:

```
cf + N_BANDS * 8 == st   == 64
st + N_BANDS * 4 == det  == 96
bp + N_BANDS * 3 <= eg   == 256
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
| `bp` band params | `dp`, `dm` dynamics params and stereo mode |
| `setup_band`, the `@sample` static loop | `eg`, `egh` Mode-A envelopes |
| the GUI's nodes and traces | `mb_band`/`mb_peak`/`mb_end` Mode-B rings |
| | `mbenv`, `mbgc`, `mbeh`, `mbwpos`, `hc` |

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

Test that distinguishes the orders: enable a B5 boost that pushes a B1 Mode-B band over its
ceiling. In the chosen order Mode B reacts to it; in the rejected order it does not.

### 3.2 Every `N_BANDS` site is classified before any code is written (review P0-3)

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
- Bands without dynamics are visually distinguishable by a **thinner node outline** **and** a
  textual `DYN` / `STATIC` tag in the selected-band readout (review P2-1). Outline thickness alone
  is fragile: it can vanish under Retina scaling, disabled styling or reduced contrast.
- **Overlapping nodes need a way out** (review P1-7). Spread defaults only prevent overlap on
  first load; with eight bands, coincident nodes are likely, and V1.0's loop-based hit-test makes
  only one of them reachable. Pinned: the selected node wins the hit-test, and repeated clicks at
  the same position cycle through the coincident nodes in band order. A compact **B1…B8 selector
  strip** beside the readout gives a deterministic way to reach any band regardless of overlap.

## 6. Verification

**Oracle:**

1. `band_slider_base` returns 10/20/30/40 for bands 0–3 and 150/160/170/180 for bands 4–7.
2. **Adjacency, not upper bounds** (§2): `cf + 8*8 == st`, `st + 8*4 == det`, `bp + 8*3 <= eg`,
   with sentinels either side of each expanded array checked after setup and after processing.
3. **Every downstream base address is byte-equal to V1.0** (review P1-6): `mb_band`, `mb_peak`,
   `mb_end`, `mbenv`, `mbmode`, `mbwpos`, `bus_dry`, `mbgc`, `mbeh`, `hc`, `egh`, `hplp_state`,
   `hplp_cf`, `lp_rt`, every `gc_*` base, and `lp_base`. `mb_end` alone proves nothing — sizing
   any one of the small arrays by 8 shifts everything after it.
4. A curve over 8 bands equals the curve over the same 4 when bands 5–8 are disabled.
5. **Each new band is mathematically correct on its own** (review P1-5): for B5, B6, B7 and B8
   individually, compare the response against the oracle across Bell / Low Shelf / High Shelf,
   every placement, positive and negative gains, and constant vs proportional Q. Then a
   multi-band case, to catch cascade addressing and cross-band mix-ups — "eight nodes change the
   sound" would pass with B5 controlling B8.

**Live in REAPER:**

- **Null test V1.0 vs V1.1, bands 5–8 disabled → bit-identical audio.** Reproducible fixture
  (review P1-3): old-parameter state transferred programmatically rather than dialled by hand,
  GUI closed, fresh instances, fixed sample rate and block size, deterministic input, no
  automation. Worded as *bit-identical audio*, not "costs nothing" — four extra enable checks are
  not literally free, and disabled-band CPU is measured separately.
- **Signal-order test** (§3.1): a B5 boost pushing a B1 Mode-B band over its ceiling must be
  *seen* by Mode B.
- **Parameter manifest** (review P1-2): capture V1.0's host parameter list through REAPER — index,
  name, min, max, step, default, round-trip value — and assert V1.1 begins with that exact prefix,
  with the 36 new parameters appended after it, never interleaved.
- **Migration** (review P1-1): V1.1 is a new file, so an old project simply reopens V1.0. The
  supported operation is therefore stated and tested: copy the V1.0 instance's state to a V1.1
  instance (preset or FX-chain copy), including off-grid values and automation envelopes, and
  confirm every old parameter keeps its value.
- **Eight nodes** drag, select and edit correctly; overlapping nodes cycle; `DYN`/`STATIC` reads
  correctly for each band.
- **CPU, with a pass/fail contract** (review P1-9): 48 kHz, block 128 and 512, 60 s, deterministic
  material, GUI closed. Three configurations — B5–B8 disabled, four extra Bell bands enabled, and
  the worst case (8 bands with all four Mode-B dynamics active). Require **zero xruns** and peak
  block time within **+10 %** of V1.0 measured identically.

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
| **P1** the CPU check has no pass/fail contract | **Accepted** — fixture, zero xruns, +10 % peak-block ceiling (§6) |
| **P2** outline thickness is a fragile cue | **Accepted** — plus a `DYN`/`STATIC` tag in the readout (§5) |
| **P2** "ninth band node"; "151–189" implies contiguity | **Accepted** — reworded; the four ranges are listed explicitly (§1, §4) |
