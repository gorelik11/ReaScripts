# RCBitNova — Dynamics Panel

**Revision 2**, 2026-09-02 (after a weakness review: 2 P0, 5 P1, 2 P2 — all accepted).

## 1. Why

V1.1 gave every one of the eight bands full dynamics, and then left all eleven of each band's
dynamics and ceiling parameters reachable only through REAPER's **Param** list. Eighty-eight
parameters in a flat alphabetical list is not an interface. The owner's words: until the dynamics
have a panel, the plugin cannot be used in real work — and it is already in real work
(`Magdalena.RPP`, on a bus, Phase=Linear at both resolutions High).

This is the editor deferred in `2026-08-22-rcbitnova-v1.1-eight-dynamic-bands-design.md` §8.1. It
adds no DSP. If it changes a single sample, it is wrong, and the null test says so.

## 2. Shape, as decided with the owner

Collapsible rows below the graph — Arthur's `Fable Eq Dynamic` pattern, which the owner already
uses daily. Eight rows always visible, one card expanded at a time.

| Decision | Chosen | Rejected, and why |
|---|---|---|
| How many bands at once | eight rows, one expandable card | one selected band (cannot compare); eight full cards (no room) |
| What edits a value | numeric field + vertical drag | knobs (new graphics from scratch, and right-click is already the menu); horizontal bars (new graphics, less precise) |
| Where the panel lives | below the graph, graph shrinks | a graph/dynamics toggle (cannot see both); a right-hand column (the log frequency axis loses the low end worst) |
| In the collapsed row | Dyn, Mode, **both** ceilings with their toggles | a live GR bar — the node already tints orange, and that is enough |

### 2.1 The row

```
B4  [Dyn] [A|B]   [S] Soft 3.05    [H] Hard 1.00
```

`B4` expands and collapses the card. `Dyn`, `S` and `H` are toggles; `A|B` picks the dynamics mode.
Each ceiling field sits **immediately after its own toggle**, because the two stages are
independent and cascade — and a layout that hides one of them misrepresents the engine.

**Soft and Hard are not exclusive.** Verified in the source, not assumed:

```eel2
soft_on = slider(dynb[b] + 8);   hard_on = slider(ceb[b] + 1);
gA = gsA * ghA;
```

A disabled stage contributes a local 1; both enabled multiply. Each stage has its own threshold —
`Soft Ceiling Macro/Micro` and `Hard Ceiling Macro/Micro` are four separate sliders. Running both
at different thresholds is a normal working configuration, so the row shows both.

### 2.2 The card

One row of five controls: `Stereo`, `Attack`, `Release`, `Soft Micro`, `Hard Micro`. Beside each
Micro, the resulting total for that stage in bits, `Macro + Micro/100`, to two decimals.

**Every step is the slider's own declared step. Nothing is invented:**

| Control | Declared | Field step | Notes |
|---|---|---|---|
| Soft/Hard Ceiling Macro | `<0,16,0.05>` | 0.05 bit | |
| Soft/Hard Ceiling Micro | `<-100,100,0.1>` | **0.1 %** = 0.001 bit | rev 1 said "step 0.001" — wrong unit, that is the *resulting* bit resolution |
| Attack | `<0.05,50,0.01>` | 0.01 ms | |
| Release | `<1,500,1>` | 1 ms | |
| Dyn, Soft, Hard | `<0,1,1>` | toggle | |
| Dyn Mode | `<0,1,1>` | two-state | |
| Stereo | `<0,2,1>` | three-state | see below |

Off-grid writes are what left −62 dB of null residue in V1.0. Every drag quantises to the step, and
typed values are clamped and quantised too.

**Stereo is not a numeric field.** `gc_field_at` renders a number and the keyboard parser accepts
digits; showing `0`, `1`, `2` is not the card that was agreed. It is a **segmented control**: three
labelled cells, `Linked | Dual L/R | Dual M/S`, the active one lit, a click selects that cell. It
reuses `gc_button` three times, so no new primitive and no enum-parsing in the keyboard path.
Dyn Mode `A|B` is the same control with two cells.

Six parameters in the row plus five in the card is all eleven.

### 2.3 The ceiling fields write Macro, and show Macro

A ceiling is two sliders: `Macro` (step 0.05 since V1.1) and `Micro` (percent of a bit, step
0.001). The row field **edits `Macro` and displays `Macro`**; `Micro` lives in the card with the
total.

The alternative — showing the sum `Macro + Micro/100` in the row — was rejected: the field would
display one number and write another, and with a non-zero Micro it would simply lie. The owner's
rule that **one gesture writes one slider** is what kept V1.0 out of a whole class of defects, and
it holds here. At a 0.05-bit step in Macro, Micro is needed only below that.

## 3. Geometry

Current, read off the source rather than remembered — `gc_fy = gc_py + gc_ph + 6*gc_sc`,
`gc_fh = 20`, the summary at `gc_fy + gc_fh + 6`, the strip at `gc_fy + gc_fh + 24`:

| | y, relative to the plot's bottom |
|---|---|
| readout fields | +6 .. +26 |
| "effective … bits" | +32, plus glyph height |
| B1…B8 strip | +50 .. +68 |
| reservation | 84, so ~16 spare |

(Rev 1 of this section said +26..+40 and +44..+62 and claimed 22 spare. Those were the numbers I
intended when designing the strip, not the ones in the file.)

The panel needs eight rows at 18 px (**144**) plus, when a card is open, one more row of fields
(**~90**). So the reservation becomes 228 collapsed and ~318 expanded.

**Equations, so the placement is derived and not guessed.** With `R` the reservation:

```
gc_ph  = gfx_h - gc_py - R
rows_y = gc_fy + 74            ; first row, clear of the strip's +68
row h  = 18, eight of them     ; 144
card_y = rows_y + 144 + 4      ; only when a card is open
card h = 90                    ; label row 14 + field row 20 + total row 14 + padding
R      = 84 + 144 = 228        ; collapsed
R      = 84 + 144 + 94 = 318   ; expanded
```

**Minimum graph height: 180 px.** Below that the graph stops being readable, so the panel is the
thing that yields: under 180 the expanded card closes, and under 180 collapsed the whole panel
hides — the same rule `gc_small` already applies, extended to a height the panel itself can trigger.
This also answers what a legacy 900×500 window does: at R=228 the graph would be 262, which is
fine; opening a card would take it to 172, so the card refuses to open until the window is taller.
Nothing is clipped and nothing scrolls.

**The default window grows from `@gfx 900 500` to `@gfx 900 640`.** Then:

| | graph height |
|---|---:|
| today, at 500 | 406 |
| 640, cards collapsed | **402** |
| 640, one card open | 312 |

So in the ordinary case — cards collapsed — **the graph keeps the size it has today**, within four
pixels, and only opening a card costs it height. Stretching the window downward gives the added
height to the graph, exactly as now.

(An earlier draft of this section proposed 760 and claimed the graph would get "about 330". Both
numbers were wrong: at 760 the graph gets 522, more than it has now. The reservation had been
subtracted twice. The table above is computed, not estimated.)

**Existing projects keep their window size** — REAPER stores it per instance. A 900×500 window
still shows the eight rows (graph 262); it refuses to open a card until dragged taller, by the
minimum-height rule above. Nothing is cut off, which is what rev 1 wrongly predicted.

In `gc_small` (below 480×280) the panel is hidden entirely, like the B1…B8 strip. That mode has
room for the readout and nothing else.

## 4. What has to be built, and what already exists

**Reusable as-is:** `gc_button(bx, by, bw, label, on)` already takes absolute coordinates and
handles hover and click. Every toggle in the panel is one call.

**Needs generalising:** `gc_field(i, label, value, dec)` derives its position from a slot index and
draws only on the readout row (`fx = gc_px + i * (gc_fw + 8*gc_sc)`, fixed `gc_fy`). The panel needs
fields at arbitrary coordinates. Add `gc_field_at(id, bx, by, bw, label, value, dec)` and express
the existing five as calls to it, so there is one field primitive rather than two that drift apart.

### 4.3 One field controller, because generalising the drawing does not generalise the interaction

`gc_field` only draws, hit-tests and shows the shared edit buffer; every click, keystroke and commit
is open-coded further down `@gfx` for exactly five fields. Twenty-one editable fields cannot be
open-coded, so the interaction gets a single controller and a metadata table.

**Metadata, one record per parameter:** `(table, offset, lo, hi, step, decimals, drag_units, writer)`.
`drag_units` is logical pixels per step, matching the node's 12-per-step feel. Everything below reads
this table; nothing hard-codes a range twice.

**Click arbitration, in one pass and in this order.** A frame resolves exactly one owner:

1. the band strip (`gc_strip_hot`) — already implemented,
2. a panel toggle or segmented cell,
3. a `B<n>` label (expand/collapse),
4. a panel field (focus for typing, and arm a drag),
5. a readout field,
6. the graph.

The existing readout click handler ends with `( gc_edit = -1; )` — an unconditional else that would
clear a panel field focused earlier in the same frame. It becomes conditional on nothing above it
having claimed the click.

**Typing:** `gc_edit` is an id — `0..5` keeps its present meaning, panel fields use
`100 + band*10 + slot`. Enter parses, clamps to `lo..hi`, quantises to `step`, and dispatches
through the metadata record's writer. Escape cancels. Clicking elsewhere transfers focus, and does
not commit — same as today.

**Dragging:** press on a field arms it, and past a 4-pixel threshold (the node's threshold) it drags:
`steps = -floor(dy / drag_units)`, applied to the value captured at press, clamped and quantised,
written on change only. Release disarms. A drag never begins while that field has typing focus.

**Automation:** every write goes through `slider_automate`, once per changed value, exactly as the
node writers do. There is no begin/end pair to manage because there is no continuous stream — the
value changes in discrete steps.

**Needs a scheme:** `gc_edit` currently holds a readout slot `0..5`. With up to 21 editable fields
on screen (two per row × 8, plus five in the card), it becomes an id: `0..5` keeps its present
meaning, and panel fields use `100 + band*10 + slot`. One integer, no new state.

### 4.1 What a writer must rebuild — and why "the same two calls" is wrong

The nine existing writers end with `setup_band(b); setup_band_dyn(b);`, and the obvious move is to
require the same of the eleven new ones. **That would ship a panel whose fields move while the audio
does not.** `setup_band_dyn` writes `det[]`, `dp[]`, `dm[]` and `bp[]` — verified — and nothing else.
Three things it does not touch are owned by the global `@slider` scan at lines 1313–1323:

| State | Owner | Which new writer needs it |
|---|---|---|
| `mbmode[b]` | `mbmode[b] = slider(dynb[b] + 7);` | `gc_w_dynmode` |
| `hc[b]` | `hc[b] = pow(2, -(slider(ceb[b]+2) + slider(ceb[b]+3) * 0.01));` | `gc_w_hardceil`, `gc_w_hardmicro` |
| `any_b`, and the Mode-B lookahead/PDC published from it | the same scan | `gc_w_dyn`, `gc_w_dynmode` |

V1.0 established live that **`@slider` is not guaranteed to run after `slider_automate`** — that is
exactly why the existing writers recompute inline. So a `gc_w_dynmode` that only calls the two
rebuilds can leave the band in Mode A while the field, the Param list and the menu all say B.

The null test cannot catch this: it renders state loaded from parameters, and this failure only
exists after a GUI gesture.

**Contract:** factor the scan body into `apply_band_dyn_global(b)` — `mbmode[b]`, `hc[b]`, and the
`any_b` contribution — and call it from `@slider` (so behaviour is unchanged) and from every writer
whose parameter feeds it. `any_b` is a fold over all bands, so recomputing it means rescanning; that
is a per-gesture cost, not a per-sample one, and it is what correctness costs here.

**The writer gate stops treating all writers alike.** Each becomes a record
`(table, offset, step, rebuilds)` and the gate checks the required rebuild calls **per writer**,
not one blanket rule for twenty.

**New writers:** eleven, one per dynamics parameter, each with eight explicit named `sliderNN`
branches — `gc_w_dyn`, `gc_w_dynmode`, `gc_w_soft`, `gc_w_hard`, `gc_w_softceil`, `gc_w_hardceil`,
`gc_w_stereo`, `gc_w_atk`, `gc_w_rel`, `gc_w_softmicro`, `gc_w_hardmicro`. That is 88 named
assignments, and it is the bulk of both the work and the risk: a wrong number edits another band's
parameter and nothing crashes. The source gate's writer manifest grows from 9 writers to 20 and
checks every number against the base tables.

**New state:** which card is expanded, as a hidden slider. Two things about it are easy to get
wrong and both would be expensive.

**It is an enum, not a bitmask.** `slider143:0<0,8,1>-` — `0` means no card open, `1..8` name the
open band. An eight-bit mask would accept all 256 subsets while the geometry budgets exactly one
open card, and Param, automation or a preset could hand the GUI a value it cannot draw. An enum
makes the invalid state unrepresentable instead of asking every reader to sanitise. Written through
a named `slider143 = v; slider_automate(slider143);`, like every other write.

**It must be declared LAST, after all 175 existing declarations, despite its number.** V1.1's
compatibility contract is that V1.0's 95 declared records are a prefix — and REAPER numbers
parameters *in declaration order*, not by slider ID. Declaring `slider143` next to `slider142`,
where it belongs numerically, would insert a record in the middle and shift all eighty B5–B8
records: the prefix breaks, and `migrate_v10_to_v11.py` writes the host tail into the wrong
parameters.

### 4.2 The declared-count contract has five consumers, not one

Adding one declared parameter moves 175 → 176 and 178 → 179. Every one of these hard-codes the old
shape today:

| File | What it holds |
|---|---|
| `tools/migrate_v10_to_v11.py` | `N_DECLARED_V11 = 175`, host tail read and written at 175..177 |
| `tools/rcbitnova_gates.py` | `N_DECLARED_V11 = 175` |
| `tools/rcbitnova_compile.py` | `n != 178` |
| `tests/_reaper_fx_fake.py` | `N_DECLARED_V11 = 175` |
| the migration branch tests | assert host Bypass at 175, Wet at 176 |

Change them **before** the plugin, migration first, so the tests fail for the right reason and then
pass. Miss one and the compile check rejects the build, or the supported migration writes
`Bypass`/`Wet`/`Delta` into `B5 Enable`/`B5 Type`/`B5 Freq`.

## 5. Verification

- **Source gate** — the writer manifest becomes a record per writer,
  `(table, offset, step, rebuilds)`, and the eight expected slider numbers are **generated from it**
  rather than listed. The current gate assumes `stb` plus an offset; the new writers span `dynb` and
  `ceb`, so a wrong-table mistake is now possible and is seeded as its own defect — a
  `gc_w_hardceil` pointing at `dynb` instead of `ceb` must be rejected, not only a wrong digit.
  Rebuild calls are checked **per writer** against that record, since they now differ. Site rows for
  the panel's loops.
- **`--live` manifest** — unchanged contract: V1.0's 95 declared records still an exact prefix,
  the host tail still positional. One new declared slider (143) means V1.1's declared count goes
  from 175 to 176; the gate's constant moves with it.
- **Null test — the load-bearing one.** This feature touches no DSP, so all five identical cases
  must stay bit-identical and `modeB_disabled_band` must keep diverging exactly as it does now.
  Any change here means the panel reached into the audio path.
- **Compile check** — `tools/rcbitnova_compile.py` after every step. `n_params` alone does not
  prove a `@gfx` section compiles; that lesson cost a broken window already.
- **Live — reachability is not enough.** A writer passes "the value changed" by moving the slider
  while `mbmode[]`, `hc[]` or the PDC stay stale, which is P0.1 exactly. So for `Dyn`, `Dyn Mode`,
  `Hard Macro` and `Hard Micro` the check is **immediate application**: make the gesture, then
  observe the engine — audibly, or by reading the derived state back through reapy — before touching
  anything else.

  The matrix names the interaction for each of the eleven parameters, and runs each writer on
  **B1, B4, B5 and B8**: the first two exercise the legacy slider numbers, the last two the appended
  ones, which are different named branches.

  Plus: both stages on at different thresholds and audibly cascading; the expansion enum surviving a
  project save and reload, and rejecting an out-of-range value written through Param; the panel
  hidden in `gc_small`; a card refusing to open below the minimum graph height; and resize while a
  card is open.

## 6. Out of scope

Per-band GR meters and history (the node tint already answers "is it working"). A ceiling handle
dragged on the graph — recorded in the V1.1 spec §8.3 and still V1.2 work. Bringing V1.0's five
existing numeric fields onto their declared steps. Any change to the DSP.

## 7. Rev-2 Disposition (weakness review of rev 1)

| Finding | Disposition |
|---|---|
| **P0.1** "Both rebuild calls" do not apply several dynamics parameters | **Accepted — verified in the source.** `setup_band_dyn` writes `det`, `dp`, `dm`, `bp` and nothing else; `mbmode[b]`, `hc[b]` and `any_b` are rebuilt only by the `@slider` scan at 1313–1323, and V1.0 established live that `@slider` is not guaranteed to run after `slider_automate`. A blanket "call the same two" would have shipped a Dyn Mode switch that moves the field and leaves the audio in the other mode. §4.1 adds `apply_band_dyn_global(b)`, called from both `@slider` and the affected writers, and the gate now checks rebuilds per writer. |
| **P0.2** Adding `slider143` changes more contracts than the live gate | **Accepted.** Five consumers hold 175/178 today, listed in §4.2, and migration is changed first. The order trap is the sharper half: REAPER numbers parameters by **declaration order**, so declaring 143 where it belongs numerically would shift all eighty B5–B8 records and break the 95-record prefix the migration depends on. It is declared last, after all 175. |
| **P1.1** The field interaction state machine is not designed | **Accepted.** §4.3: one controller, a metadata record per parameter, a single click-arbitration order that ends the readout handler's unconditional `gc_edit = -1`, and full flows for type-Enter and for drag. |
| **P1.2** "One card" conflicts with an unconstrained 8-bit mask | **Accepted.** The mask becomes an enum `0..8`. The invalid state is unrepresentable rather than sanitised on every read, and out-of-range values written through Param are a live test case. |
| **P1.3** The Micro step is in the wrong unit | **Accepted.** Declared `<-100,100,0.1>` — percent, step 0.1 %, which *yields* 0.001 bit. Rev 1 wrote the resulting resolution as if it were the slider step, which would have produced off-grid Param values — the same defect class as V1.0's −62 dB null residue. A step table now covers every control. |
| **P1.4** Stereo cannot be a numeric field | **Accepted.** It is a segmented three-cell control built from `gc_button`; Dyn Mode is the same control with two cells. No enum parsing in the keyboard path. |
| **P1.5** Geometry does not match the current layout | **Accepted — measured.** The real offsets are fields +6..+26, summary at +32, strip +50..+68, ~16 spare; rev 1 carried the numbers I had intended for the strip rather than the ones in the file. §3 now gives equations, a 180 px minimum graph height, and what a legacy 900×500 window does (rows fit at graph 262; a card refuses to open until the window is taller). |
| **P2.1** The writer manifest hides its table mapping | **Accepted.** Each writer is a record and the eight expected numbers are generated from it, with a wrong-table defect seeded alongside the wrong-digit one. |
| **P2.2** Verification checks reachability, not application | **Accepted.** For `Dyn`, `Dyn Mode`, `Hard Macro` and `Hard Micro` the live check observes the engine after the gesture, and every writer is exercised on B1, B4, B5 and B8 so both legacy and appended branches run. |
