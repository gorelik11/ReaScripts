# RCBitNova V1.1 — Eight Fully Dynamic Bands

**Revision 3**, 2026-08-23 (after two weakness reviews: rev 1 → 4 P0/7 P1/2 P2, rev 2 → 2 P0/4 P1/2 P2). **Supersedes** `2026-08-19-rcbitnova-v1.1-eight-bands-design.md`
(rev 4) and its plan, which built eight *static* bands with dynamics on the first four only.

## 1. Goal

Raise the EQ from four bands to eight, with **every band identical**: static SVF, Mode A, Mode B,
soft and hard ceilings, detector, placement, proportional Q. No band is a lesser band.

## 2. Why this replaces the split design

The split existed for one reason — I claimed in planning that eight *fully* dynamic bands were
prohibitively hard, and the owner accepted that on my word. Measured against the shipped V1.0, the
claim does not survive:

| | Split (8 static / 4 dynamic) | Uniform (8 dynamic) |
|---|---|---|
| New constant | `N_DYN`, applied to 17 of 28 sites | none |
| `@sample` band loop | **split into two loops**, the second forbidden from touching any dynamic array | unchanged |
| GUI writers | eight-way **plus** a `b < N_DYN` guard in every one | eight-way |
| Visual language | DYN/STATIC tag + a second outline weight | none needed |
| Low memory map | five arrays stay, two move | five arrays stay, two move |
| Extra memory | +40 words | **+512 KB** |
| Slider numbers used | 36 new, max 189 | 80 new, max 245 (limit 256) |
| Reviewer P0s caused by the design | **three** (`bp` misclassified; the static loop reading `dp`/`dm`; five runtime `N_DYN` sites omitted from the gate) | those failure modes do not exist |

The split's cost was never in the sliders. It was in the *invariant* it created — "this array is
four-band, that one is eight" — which three independent review rounds each failed to apply
correctly, in a codebase where getting it wrong relocates the memory map silently.

**What the uniform design actually costs:** 512 KB of allocation, roughly double the dynamics CPU
when all eight bands run dynamics, and `lp_base` moving from 65536 to 131072.

## 3. Memory

Everything below is computed from the shipped V1.0 addresses and verified by
`tools/rcbitnova_layout.py`.

### 3.1 The low map — five of seven arrays never move

`cf` and `st` grow into the space that was always reserved for them, and the four-band spacing of
the dynamic arrays turns out to be exactly generous enough for eight:

| Array | Words/band | V1.0 (4 bands) | V1.1 (8 bands) | |
|---|---:|---|---|---|
| `cf` | 8 | 0..31 | **0..63** | grows into `st` |
| `st` | 4 | 64..79 | **64..95** | grows into `det` |
| `det` | 4 | 96..111 | **96..127** | base unchanged |
| `dst` | 4 | 128..143 | **128..159** | base unchanged |
| `cst` | 4 | 160..175 | **160..191** | base unchanged |
| `dp` | 4 | 192..207 | **192..223** | base unchanged |
| `dm` | 1 | 208..211 | **224..231** | **moves** (208 → 224) |
| `bp` | 3 | 216..227 | **232..255** | **moves** (216 → 232) |
| `eg` | 2 | 256..263 | **256..271** | base unchanged |

Ends at 272; `mb_band` is a literal 1024, so **752 words remain free**.

**"Eight is the maximum" was wrong, twice, and both versions were asserted rather than computed.**

The split design justified it with `cf + 8*8 == st` and `st + 8*4 == det` being zero-slack — true
only while `det` was pinned at 96. Here every array floats up as needed. The arrays are
**34 words per band** (`cf` 8 + `st` 4 + `det` 4 + `dst` 4 + `cst` 4 + `dp` 4 + `dm` 1 + `bp` 3 +
`eg` 2 — rev 1 said 30 and inverted the conclusion), so the low map holds **30 bands**: thirty end
at 1020, thirty-one at 1054, past `mb_band`'s literal 1024. A ninth ends at 306.

The slider budget is tighter but still not eight. After bands 5–8 are allocated, **50 numbers remain
below 256** in runs of 11 (246–256), 8 (143–150), 7 (124–130) and 6 (5–10). A ninth band needs 9 + 8
+ 3 contiguous, and it **fits** — scattered across three of those runs. A tenth does not.

So: memory allows ~34, slider numbers allow 9, and **eight is a product decision** — eight uniform
bands with tidy, regular bases. The model asserts what is true (8 fits, 9 fits, 10 does not) rather
than a ceiling that sounds firm and is not.

### 3.2 Slider-base tables (272..295)

Three eight-word tables filled in `@init`, occupying part of that free space:

```eel2
stb  = 272;   // static base per band:    10,20,30,40, 150,160,170,180
dynb = 280;   // dynamics base per band:  50,60,70,80, 190,200,210,220
ceb  = 288;   // ceiling base per band:   90,100,110,120, 230,234,238,242
```

Reads become `slider(stb[b] + 3)` — no arithmetic, no branch, no function call in the audio path.
This replaces the split design's `band_slider_base(b)` helper, which would have needed two more
helpers for the dynamics and ceiling blocks and put three calls per band per sample into `@sample`.

**Writes still go through explicit named `sliderNN` branches.** V1.0 established live that
assigning through `slider(computed_index)` updates what the GUI reads back and never reaches the
parameter.

### 3.3 The chain above 1024

`mb_peak`, `mb_end` and everything after them are derived by multiplying by the band count, so they
all move:

Three states, not two — the pre-flip build is a real artifact that Tasks 3–4 load and gate, and
rev 1's table silently mixed its span into V1.0's row:

| | shipped V1.0 | V1.1 pre-flip (4 bands) | V1.1 final (8 bands) |
|---|---:|---:|---:|
| `mb_peak` | 17408 | 17408 | 33792 |
| `mb_end` | 33792 | 33792 | 66560 |
| `gc_trace` | 38275 | 38275 | 71087 |
| GUI clear span | 13638 | 13646 | 13678 |
| GUI region end (exclusive) | **51913** | **51921** | **84765** |
| `lp_base` | 65536 | 65536 | **131072** |

Every one of these is derived by `tools/rcbitnova_layout.py`; none is typed into a document twice.

**`lp_base` moving is the single most dangerous consequence of this design.** V0.7 established that
a 32768-point FFT buffer must start on a 65536-word page or it corrupts **silently** — no error, no
crash, wrong audio. `lp_base` is computed, not hardcoded, so it re-aligns itself; but this must be
verified live in Phase=Linear at Resolution=High, not merely asserted by a gate.

### 3.4 The GUI block

`gc_kc` is sized `N_BANDS * 8` (64 words at eight bands) and `gc_fc`/`gc_ebuf` shift up by 32.
`gc_hits` (8 words) is added after `gc_ebuf` for node-cycling. The initialiser's clear span is
**derived, never typed**:

```eel2
memset(gc_trace, 0, gc_hits + 8 - gc_trace);
```

which is 13646 at four bands and 13678 at eight. A literal there cannot be right in both phases,
and it was a literal that put this plan's rev 3 and the old spec into contradiction.

## 4. Sliders

Bands 1–4 keep every number they have: static `10*(b+1)+1..9`, dynamics `50+10b+1..8`, ceilings
`90+10b+1..3`. REAPER stores parameters by number and any shift would corrupt existing projects.

Bands 5–8 take free ranges, **declared after every existing slider** (verified live 2026-08-19: the
host numbers parameters densely in declaration order, so appending is what keeps V1.0's declared
list an exact prefix of V1.1's):

| Block | Per band | B5 | B6 | B7 | B8 |
|---|---|---|---|---|---|
| Static (9) | base+1..9 | 151–159 | 161–169 | 171–179 | 181–189 |
| Dynamics (8) | base+1..8 | 191–198 | 201–208 | 211–218 | 221–228 |
| Ceilings (3) | base+1..3 | 231–233 | 235–237 | 239–241 | 243–245 |

80 new sliders, highest **245**, against a limit of 256 (verified live: 151, 159, 189, 200 and 256
all register). Ceilings use a stride of 4 rather than 10 — at stride 10 band 8 would land on 261.

Declared parameters go from 95 to **175**. The host tail (`Bypass`, `Wet`, `Delta`) still follows
them, so V1.0's *full* parameter list is still not a prefix of V1.1's — only the 95 declared ones.

## 5. Code

With no `N_DYN`, every one of the 28 sites from the old §3.2 is simply `N_BANDS`, exactly as V1.0
already writes them. The JSFX change is:

1. `N_BANDS = 4` → `8`.
2. `dm` and `bp` re-based (208 → 224, 216 → 232).
3. `gc_kc` sized by `N_BANDS`; `gc_hits` added; the clear span derived.
4. 80 new slider declarations, appended.
5. The three base tables filled in `@init`.
6. Every open-coded `10*(b+1)`, `50+10*b` and `90+10*b` **read** replaced by a table read.
7. GUI writers made eight-way with explicit named sliders.

There is no loop to split, no guard to add, no array whose band count differs from its neighbour's.

## 6. GUI (owner's decisions, 2026-08-22)

- **Right-click on a band node opens a context menu** — Type, Placement, Q Character, enable/disable.
  This deviates from the family convention (in `Fable Eq Dynamic` right-click on a control means
  keyboard entry); RCBitNova already deviates, since V1.0's HP/LP handles carry a right-click menu.
  Chosen deliberately.
- **A strip of eight buttons** below the plot selects a band, rather than the family's collapsible
  per-band cards. It must sit **outside** the plot and own its clicks: V1.0 places `gc_fy` only
  6 px below the plot, so a strip drawn above that line steals clicks from nodes at the bottom edge.
- **Live gain-reduction highlight on the node**, adopted from `Fable Eq Dynamic`, where a band's
  card glows in proportion to current GR. With every band dynamic this applies to all eight and
  replaces the DYN/STATIC distinction the split design needed. Deferred display work (the V1.2
  "dynamics display") is *not* pulled in — this is the node tint only.
- **Coincident nodes cycle** on repeated clicks in the same spot within 400 ms, hit set built from
  every node within the radius including disabled ones, index taken modulo the current hit count
  every frame.
- **Q Character gets a numeric-entry field**, and typed values are **quantised to the declared
  0.001 step** — matching Arthur's family ("BITY, FINE i RANGE zaokrąglane… także przy wpisie") and
  V1.0's own −62 dB null-residue lesson from continuous GUI writes.

## 7. EEL2 conventions

- **Every assignment inside a ternary branch is parenthesised**, without exception — the family
  sweeps all of them, and V0.8's version of that defect passed both the oracle and a full review
  before the CPU meter caught it.
- **No bit-shift operators.** `bmsk()` in `Fable Eq Dynamic` is a ternary lookup table written
  specifically to avoid `<<`, keeping `AND` as the only bitwise dependency.
- **Functions resolve in file order** — four V1.0 builds broke on definitions sitting below their
  callers.

## 8. Verification

1. **Oracle** — `tools/rcbitnova_layout.py` reproduces the shipped V1.0 addresses, then the V1.1
   ones; `GuardedMemory` rejects any modelled access outside a named array's span.
2. **Source gate** — the site manifest, the forbidden read patterns, the writer manifest, and every
   address computed through `lp_base` and compared to the model. Self-tested by seeding one defect
   per class and requiring rejection.
3. **Null test** — V1.1 with bands 5–8 disabled against V1.0, 32-bit float, dither and normalization
   off, equal reported latency asserted before samples, zero tolerance.
4. **`lp_base` live** — Phase=Linear, Resolution=High, both engines, verified audibly and by
   analyzer. The gate can only assert the number; only this catches the silent-corruption mode.
5. **CPU** — no peak-block-time API exists on this build (measured 2026-08-22: the only matching
   functions are `GetAudioDeviceInfo` and `GetUnderrunTime`), so this is a documented manual
   Performance Meter protocol. Xruns via `GetUnderrunTime`, which returns **timestamps, not counts**.
   Expect the dynamics share to roughly double with eight bands running; the gate is the four-band
   regression, not the eight-band cost.
6. **Migration** — 95 declared parameters copied by index, the host tail by position, FX identity by
   `guidToString` (the raw `TrackFX_GetFXGUID` pointer does **not** survive a move), verified before
   anything is deleted, and tested against FakeReaper before REAPER.
7. **Live** — the reachability contract below, honoured for all eight bands; Mode A and Mode B
   audibly working on B5–B8; the cycling matrix.

### 8.1 Reachability contract (narrowed in rev 2)

Rev 1 claimed all 20 parameters of a band are reachable from the custom GUI. The GUI has controls
for **nine** — enable, Type, Placement and Q Character through the node's right-click menu, and
Freq, Macro, Micro, Ratio, Q through the readout fields. The other **eleven are the dynamics and
ceiling blocks**, and V1.0 never exposed them on the graph either.

The honest contract, unchanged from V1.0's shape:

- **From the graph:** the nine static parameters, for all eight bands.
- **From the host's parameter list:** the eleven dynamics/ceiling parameters. Every slider is
  declared with a `-` prefix, so it is hidden from the FX window but automatable and reachable
  through **Param**, exactly as bands 1–4's dynamics have always been.

A selected-band dynamics editor covering those eleven is a real feature and a real amount of work;
it belongs with the V1.2 dynamics display, not smuggled into V1.1. The live matrix names the
interaction used for each of the twenty so the split is auditable rather than implied.

## 8.2 The 28 sites, in this document

Rev 1 said "every one of the 28 sites from the old §3.2 is simply `N_BANDS`" and left the inventory
in a superseded file. It is here instead, mapped to the gate row that covers it, so this revision
stands on its own. Sites that were separate rows only because the split needed two counts collapse
into one gate row; that is a documented many-to-one mapping, not an omission.

| V1.0 site | Gate row |
|---|---|
| `N_BANDS = 4` declaration | `count-declaration` |
| `memset(st, …)` | address gate (`st` span) |
| `memset(dst)`, `memset(cst)`, `eg` fill | address gate (low-map spans) |
| `mb_peak`, `mb_end` | address gate (`AUDIO` chain, exact) |
| `mbmode`, `mbwpos`, `bus_dry` bases | address gate |
| `mbenv`, `mbwpos`, `mbgc` fills | address gate |
| `mbeh`, `hc`, `egh` bases; `mbeh`, `egh` fills | address gate |
| `hplp_state = egh + …` | address gate |
| `gc_domain_bits`, `gc_dom_used` | `helper-gc_domain_bits`, `helper-gc_dom_used` |
| `@slider` setup loop | `slider-setup` |
| `@slider` Mode-B scan | `slider-modeb-scan` |
| `@sample` band loop | `sample-band-loop` |
| `@sample` Mode-B pass | `sample-modeb-pass` |
| `@gfx` coefficients, hit-test, node draw | `gfx-band-setup`, `gfx-hit-test`, `gfx-node-draw` |

**Two kinds of `@init` site, and only one of them is covered by addresses.**

*Address-producing* sites (`mbeh = mbgc + N_BANDS * 2;` and its eleven siblings) are covered by
comparing **computed word addresses**: a wrong count moves an address, and the gate compares every
one to the model. That is stronger than matching the text.

*State-initialising* sites are **not**. `memset(st, 0, N_BANDS * 4)`, `memset(dst, …)`,
`memset(cst, …)`, `memset(mbwpos, …)` and the `loop(N_BANDS * 2, …)` fills for `eg`, `mbenv`,
`mbgc`, `mbeh` and `egh` write state and produce no address. Change the last one to `loop(4 * 2, …)`
and B5–B8's Mode-A hard envelopes start at zero while **every address in the model still matches**.
Rev 2 mapped these to "computed address comparison" and was wrong to. Each has its own `fill-*` gate
row and its own seeded defect.

## 8.3 Recorded for the dynamics editor (owner, 2026-08-24)

The GR tint is live and confirmed working. Looking at it, the owner asked for the thing that will
matter once the **ceiling** itself gets a control in the GUI:

> the ceiling must be operable in **0.05-bit steps**, the way the EQ is — from the track controls
> today you can only move it in whole bits.

The parameters as declared:

| | Declaration | Meaning |
|---|---|---|
| `Bx Soft/Hard Ceiling Macro` | `<0,16,1>` | whole bits below 0 |
| `Bx Soft/Hard Ceiling Micro` | `<-100,100,0.1>` | percent of a bit, so 0.1 % = 0.001 bit |

So a sub-bit ceiling is already *reachable* — Micro = 5 is 0.05 bit — but only as a second
parameter, and a TCP knob on it turns in percent rather than in 0.05-bit steps.

**The design answer, and it needs no new parameter:** give a ceiling handle the same gesture map the
band node already has, so the rule "one gesture writes one slider" survives intact.

| Gesture | Writes | Step |
|---|---|---|
| plain vertical drag | Ceiling **Macro** | whole bits |
| **Shift** + vertical drag | Ceiling **Micro** | **5 % = 0.05 bit** |
| typed | either field | exact, quantised to the declared step |

That mirrors the band node exactly (plain = Macro in whole bits, Shift = the fine axis in 0.05
units), and the readout shows the combined `Macro + Micro / 100` bits below 0 — 4.05 bits being
−24.38 dBFS.

Not V1.1 work: the eleven dynamics and ceiling parameters are reached through **Param** in this
version (§8.1), and the editor that would carry this handle is V1.2.

## 9. Out of scope

A ninth band — it collides with the fixed base tables at 272..295 (`bp` would reach 287, `eg` 305)
and would need all three relocated first; a dynamics editor in the GUI (§8.1); the V1.2 dynamics *display* beyond the node tint;
parameter aliases in migration; bringing V1.0's five existing numeric fields onto their declared
steps.
