# RCBitNova — Dynamics Panel

**Revision 1**, 2026-09-02.

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

One row of five fields: `Stereo` (Linked / Dual L/R / Dual M/S), `Attack`, `Release`,
`Soft Micro`, `Hard Micro`. Beside each Micro, the resulting total for that stage in bits.

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

Current: `gc_ph = gfx_h - gc_py - 84 * gc_sc`. The chrome inside those 84 pixels ends 62 below the
plot — readout fields at +6..+26, the "effective … bits" summary at +26..+40, the B1…B8 strip at
+44..+62 — leaving 22 spare.

The panel needs eight rows at 18 px (**144**) plus, when a card is open, one more row of fields
(**~90**). So the reservation becomes 228 collapsed and ~318 expanded.

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

**Existing projects keep their window size** — REAPER stores it per instance — so the panel will
be cut off in a session saved before this change until the window is dragged taller. Say so in the
release notes rather than letting it be discovered.

In `gc_small` (below 480×280) the panel is hidden entirely, like the B1…B8 strip. That mode has
room for the readout and nothing else.

## 4. What has to be built, and what already exists

**Reusable as-is:** `gc_button(bx, by, bw, label, on)` already takes absolute coordinates and
handles hover and click. Every toggle in the panel is one call.

**Needs generalising:** `gc_field(i, label, value, dec)` derives its position from a slot index and
draws only on the readout row (`fx = gc_px + i * (gc_fw + 8*gc_sc)`, fixed `gc_fy`). The panel needs
fields at arbitrary coordinates. Add `gc_field_at(id, bx, by, bw, label, value, dec)` and express
the existing five as calls to it, so there is one field primitive rather than two that drift apart.

**Needs a scheme:** `gc_edit` currently holds a readout slot `0..5`. With up to 21 editable fields
on screen (two per row × 8, plus five in the card), it becomes an id: `0..5` keeps its present
meaning, and panel fields use `100 + band*10 + slot`. One integer, no new state.

**New writers:** eleven, one per dynamics parameter, each with eight explicit named `sliderNN`
branches — `gc_w_dyn`, `gc_w_dynmode`, `gc_w_soft`, `gc_w_hard`, `gc_w_softceil`, `gc_w_hardceil`,
`gc_w_stereo`, `gc_w_atk`, `gc_w_rel`, `gc_w_softmicro`, `gc_w_hardmicro`. That is 88 named
assignments, and it is the bulk of both the work and the risk: a wrong number edits another band's
parameter and nothing crashes. The source gate's writer manifest grows from 9 writers to 20 and
checks every number against the base tables.

**New state:** which cards are expanded, as a hidden slider bitmask `slider143:0<0,255,1>-` (143 is
free; verified). Persisted with the project, costs no memory, and mirrors Arthur's `slider68`.
Reading a bit uses a ternary lookup table, not `<<` — the family avoids bit-shift operators in
EEL2.

## 5. Verification

- **Source gate** — the writer manifest covers all twenty writers: eight named branches each, the
  right slider numbers from `stb`/`dynb`/`ceb`, `slider_automate`, and both rebuild calls. Site
  rows for the panel's loops.
- **`--live` manifest** — unchanged contract: V1.0's 95 declared records still an exact prefix,
  the host tail still positional. One new declared slider (143) means V1.1's declared count goes
  from 175 to 176; the gate's constant moves with it.
- **Null test — the load-bearing one.** This feature touches no DSP, so all five identical cases
  must stay bit-identical and `modeB_disabled_band` must keep diverging exactly as it does now.
  Any change here means the panel reached into the audio path.
- **Compile check** — `tools/rcbitnova_compile.py` after every step. `n_params` alone does not
  prove a `@gfx` section compiles; that lesson cost a broken window already.
- **Live** — a reachability matrix naming the interaction for each of the eleven parameters on
  each of the eight bands, plus: both stages on at different thresholds, the expansion bitmask
  surviving a project save and reload, and the panel hidden in `gc_small`.

## 6. Out of scope

Per-band GR meters and history (the node tint already answers "is it working"). A ceiling handle
dragged on the graph — recorded in the V1.1 spec §8.3 and still V1.2 work. Bringing V1.0's five
existing numeric fields onto their declared steps. Any change to the DSP.
