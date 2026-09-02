# RCBitNova — Dynamics Panel

**Revision 4**, 2026-09-02 (three reviews: rev 1 → 2 P0/5 P1/2 P2, rev 2 → 2 P0/3 P1/2 P2, rev 3 → 2 P0/4 P1/3 P2; all accepted).

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

**This deliberately follows the minority precedent, and the split is worth naming.** Five of the six
existing numeric fields take typed values *unquantised* — the source says so outright: "typed values
are NOT quantised… the keyboard is the precision path". Only `gc_w_qchar` clamps and quantises, and
its comment explains why. The panel follows `gc_w_qchar`, for every field: its parameters map to
ceilings and times that the host also writes on its own grid, and a GUI-only value the host cannot
reproduce is the defect the V1.1 ceiling work already had to fix once. Bringing the older five into
line is a separate change to shipped behaviour and stays out of scope.

**Stereo is not a numeric field.** `gc_field_at` renders a number and the keyboard parser accepts
digits; showing `0`, `1`, `2` is not the card that was agreed. It is a **segmented control**: three
labelled cells, `Linked | Dual L/R | Dual M/S`, the active one lit, a click selects that cell. It
reuses `gc_button` three times, so no new primitive and no enum-parsing in the keyboard path.
Dyn Mode `A|B` is the same control with two cells.

Six parameters in the row plus five in the card is all eleven.

### 2.3 The ceiling fields write Macro, and show Macro

A ceiling is two sliders: `Macro` (step 0.05 bit since V1.1) and `Micro` (percent of a bit, step
**0.1 %**, which yields 0.001 bit after the division by 100). The row field **edits `Macro` and displays `Macro`**; `Micro` lives in the card with the
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

**Every hit test is in logical units too, not only the layout.** The plugin this panel copies its
shape from has *zero* Retina awareness — `Fable Eq Dynamic.jsfx` never references
`gfx_ext_retina`, and hit-tests against raw constants (`CLIP_TOP = 42`, a knob radius of
`sqr(...) <= 100`). Those thresholds are simply wrong by the device pixel ratio on the machine this
runs on. RCBitNova already carries the discipline (`gc_ret`, `gc_sc`); the panel keeps it for the
4-pixel drag threshold, every row and cell rectangle, and every field bound.

**Minimum graph height: 180 logical pixels** — logical, like every number in this section: the
reservations, the row height and this threshold are all multiplied by `gc_sc` when drawn, and
`gc_small` compares `gfx_w / gc_ret` and `gfx_h / gc_ret` for the same reason.

**Insufficient height is a derived visibility state and never writes a parameter.** `slider143` says
which card the user opened; the window says whether there is room to draw it. Resizing must not
automate a parameter write — that would survive into the project, replay under automation, and land
in the undo history, all because someone dragged a window edge. So: below 180 the card is not drawn
and the reservation stays at 228; grow the window back and the same card reopens, because the enum
was never touched. Below 180 collapsed, the whole panel hides, exactly as `gc_small` already does.

A legacy 900×500 window therefore shows the eight rows (graph 262) and simply does not draw a card
until the window is taller. Nothing is clipped and nothing scrolls.

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

**Reusable as-is:** `gc_button(bx, by, bw, label, on)` already takes absolute coordinates, draws,
and returns whether the pointer is over it. It does **not** consume the click — the caller combines
`hot` with the frame's `gc_click`, and under the single-owner arbitration below that is the
arbitration's job. Every toggle and every segmented cell is one call.

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

**`writer` is a numeric family ID, not a callable.** EEL2 has no first-class function references, and
the temptation the tuple creates is worse than the inconvenience: a "generic" writer built from
`(table, offset)` would assign through `slider(computed_index)` — which V1.0 proved live moves the
GUI's own reading and never reaches the parameter. So the controller ends in one explicit
dispatcher:

```eel2
w == W_DYN      ? ( gc_w_dyn(b, v); )      :
w == W_DYNMODE  ? ( gc_w_dynmode(b, v); )  :
...
```

The metadata may *choose* a writer; only a named writer may *assign* a slider. The source gate
rejects any computed slider assignment inside the field controller, in addition to checking all 88
named branches.

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

**Press, drag, focus — one state machine, because rev 2 described a contradiction.** It said a press
gives typing focus *and* arms a drag, and then that a drag never begins while the field has typing
focus: on the initiating press both are true and nothing can ever start dragging. The transition
belongs at the threshold, not at the press:

| Event | Effect |
|---|---|
| mouse-down on a field | capture it and record the value; **no edit mode yet** |
| movement past 4 logical px while captured | start dragging, and clear any existing edit focus |
| release before the threshold | give this field typing focus |
| release while dragging | disarm; focus is untouched |

Dragging itself: `steps = -floor(dy / drag_units)` applied to the captured value, clamped to
`lo..hi`, quantised to `step`, written only when the result changes. A field that already has typing
focus behaves identically — a press on it re-captures, and a drag takes focus away.

**The alternative both references chose, and why not here.** Arthur separates the two gestures
physically: right-click on a control opens keyboard entry, left-drag adjusts
(`Fable Eq Dynamic.jsfx:761`, "prawy klik = wpis z klawiatury"). That removes the press/threshold
ambiguity entirely — the one rev 2 caught as a literal contradiction. It is rejected here for a
specific reason, not by oversight: **right-click is already the band context menu** in RCBitNova,
and the owner chose that deliberately over the family convention. Overloading it a second time
inside the panel would make the same button mean three things. The left-button state machine above
is the price of that earlier decision.

**Automation:** every write goes through `slider_automate`, once per changed value, exactly as the
node writers do. There is no begin/end pair to manage because there is no continuous stream — the
value changes in discrete steps.

**Needs a scheme:** `gc_edit` currently holds a readout slot `0..5`. With up to 20 **numeric** fields on
screen — two per row × 8, plus four in the card, since Stereo is a segmented control and not a field
— it becomes an id: `0..5` keeps its present
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

**Contract, in two parts, because rebuilding and publishing must not be confused.**

`apply_band_dyn_global(b)` **rebuilds only**: `mbmode[b]`, `hc[b]`, and the full `any_b` fold.
`any_b` is a fold over all bands, so recomputing it means rescanning — a per-gesture cost, not a
per-sample one, and it is what correctness costs here.

**Publication is separate and stays where it is.** `topo_pdc()` is called at line 1412, at the end
of `@slider`, *after* the linear-engine geometry reconcile, with an explicit comment pinning that
order. Two wrong readings of "the helper publishes PDC" were both available:

| If the helper… | Consequence |
|---|---|
| does not call `topo_pdc()` | a Dyn or Dyn Mode gesture updates `any_b` while `pdc_delay` stays stale — and a gate that only requires the helper still passes |
| calls `topo_pdc()` itself | PDC gets published from the old scan site, *before* the geometry reconcile, breaking the ordering the source deliberately keeps |

So the helper never publishes — and **neither does `@gfx`**. `topo_pdc()` writes `pdc_delay`,
`pdc_bot_ch`, `pdc_top_ch` and `ext_tail_size`: variables REAPER itself reads. Calling it from a GUI
writer would write them from the graphics thread, and rev 3 left that as a question for the live
check. It does not need to be a question.

`@block` already calls `topo_pdc()` at the topology commit (line 1431). So:

- `apply_band_dyn_global(b)` rebuilds `mbmode[b]`, `hc[b]` and the `any_b` fold, and sets
  `pdc_dirty = 1;`
- `@block` begins with `pdc_dirty ? ( topo_pdc(); pdc_dirty = 0; );`
- `@slider` keeps its single post-reconcile call, unchanged.

Publication lands within one audio block — inaudible — and no REAPER-read variable is ever written
from `@gfx`. The per-writer gate requires the helper for `Dyn` and `Dyn Mode` and requires that
**no writer calls `topo_pdc()` directly**; the live check still reads reported PDC after each
gesture, now as confirmation rather than as the only defence.

**The writer gate stops treating all writers alike, and its record has an explicit schema** —
because today `check_writers()` asserts the literal substrings `"setup_band(b)"` and
`"setup_band_dyn(b)"` for *every* writer, and "make it per-writer" is not a specification.

```python
# name -> (table, offset, step, rebuilds, publishes)
#   table     "stb" | "dynb" | "ceb"      - which base table the eight numbers come from
#   offset    int                          - added to the table entry
#   step      float                        - the declared slider step, for the drag/entry contract
#   rebuilds  tuple of exact call strings the body MUST contain
#   publishes bool                         - must set pdc_dirty (via the helper); never topo_pdc()
WRITERS = {
    "gc_w_dyn":     ("dynb", 1, 1,    ("setup_band_dyn(b)", "apply_band_dyn_global(b)"), True),
    "gc_w_dynmode": ("dynb", 7, 1,    ("apply_band_dyn_global(b)",),                     True),
    "gc_w_hardceil":("ceb",  2, 0.05, ("apply_band_dyn_global(b)",),                     False),
    "gc_w_atk":     ("dynb", 5, 0.01, ("setup_band_dyn(b)",),                            False),
    ...
}
```

`rebuilds` and `publishes` are **separate fields on purpose**. One field doing double duty is how a
writer that rebuilds but never republishes PDC slips through — the exact defect this section exists
to prevent. The gate also asserts that no writer contains `topo_pdc(`.

**Order inside a writer: write the slider, automate it, then rebuild.** Every existing writer does
this (`gc_w_enable`: the named assignment and `slider_automate` first, `setup_band(b);
setup_band_dyn(b);` on the next line). It matters more for the new ones: `apply_band_dyn_global(b)`
folds `any_b` across all bands by reading sliders, so calling it before the write would fold the
*previous* value and leave the state one gesture behind. The gate checks the order, not just the
presence of the calls.

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

**It must be declared LAST, after all 175 existing declarations, despite its number** — and the
reason is worse than the one rev 2 gave.

`slider142` is record **94**; B5's first record is **95**. Declaring `slider143` next to it, where
it belongs numerically, keeps V1.0's 95-record prefix intact — records 0..94 are untouched — and
shifts the eighty B5–B8 records to 96..175. So:

- the `--live` gate **passes**: it compares V1.0's 95 records against V1.1's first 95, and those
  still match;
- the V1.0 → V1.1 migration **passes**: it copies its 95 declared values correctly;
- and **every already-saved V1.1 project reads its B5–B8 values one parameter late**. The plugin is
  in use in `Magdalena.RPP` today. This is a live project-compatibility break that no current check
  can see.

The contract therefore is not "V1.0's 95 records are a prefix" — that one is satisfied by the
broken layout. It is **"V1.1's 175 records are a prefix"**.

**The fixture is a file, and it is written before any panel work starts:**

| | |
|---|---|
| Artifact | `tests/fixtures/v11_declared_175.json` |
| Contents | 175 records, `(index, name, lo, hi, step, default)` |
| Generated by | `python3 tools/rcbitnova_gates.py --freeze` against the **current** `JSFX/RCBitNova V1.1`, before the panel exists |
| Checked by | `--live`: the panel build's first 175 records must equal it exactly, `slider143` must be record **175**, host tail **176..178** |

"Freeze it as a fixture" without naming the file is how two people invent two fixtures and the
strongest safeguard in this spec ends up not existing. Committed first, in its own commit, so the
diff shows what was frozen and when.

The V1.0 95-record comparison stays as well — it is the migration's contract, and it is a different
question.

**Seed the defect:** a build with `slider143` declared immediately after `slider142` must be
rejected, *even though the V1.0 prefix check still passes on it*. A gate that cannot fail on this
is not protecting anything.

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
pass. Miss one and the compile check rejects the build, or — with the correct append-last order but
a stale `N_DECLARED_V11` — the migration writes `Bypass`/`Wet`/`Delta` into
`Panel state`/`Bypass`/`Wet`, each one parameter early. (Rev 2 said they would land in
`B5 Enable`/`B5 Type`/`B5 Freq`; that is the *other* failure, the one caused by inserting the panel
record before B5–B8.)

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

## 6. What the references have and this does not — and why that is the right answer

The owner names EQall the benchmark for dynamics and Arthur's plugin a useful, buggy neighbour.
Three things they have that RCBitNova does not, examined rather than waved away:

**Knee is a different mechanism here, not a missing control.** EQall's `bufdynknee`
(`mrelwood_EQall_BETA:1542`) is not a knee width at all — it is a binary switch between two whole
transfer functions, `compsoft()` (`:1380`) and `comphard()` (`:1425`). Arthur's *is* a continuous
knee in dB (`slider106:6<0,12,0.1>-B1 Dyn Knee (dB)`, consumed at `:691`). RCBitNova reaches the
same end by a different architecture: two independent cascaded stages with their own thresholds,
`gA = gsA * ghA`, which already gives a two-regime curve per band. A literal knee slider would be
new DSP and is out of scope; more usefully, **the layout should not reserve room for it**. The row
and card are at 11 of 11 declared parameters, a future knee needs a new slider anyway, and holding
empty space against an unbuilt DSP change is premature.

**"Dynamics solo" in both references means ordinary band solo** — mute every other band so you can
hear one in isolation (`mrelwood_EQall_BETA:1553`, `Fable Eq Dynamic.jsfx:515`). It is cheap to add
later (mute logic, no new dynamics maths) and it is new DSP, so not now. Naming it precisely matters
because it is easy to confuse with a GR meter or an audition of the reduction itself, which is a
different feature and was rejected in this spec for a different reason: the node already tints.

**Multi-edit is right to leave out, and the reason is about this engine.** EQall's `multiedit`
(112 references) exists because points on one continuous curve are naturally homogeneous, so
dragging four thresholds together is a normal gesture. RCBitNova's eight bands are heterogeneous by
construction — different placement, mode, ratio and M/S role per band — so the gesture is worth
less here, while the failure mode is worse: an off-by-one in a multi-selection silently edits the
wrong band, and "a wrong number edits another band's parameter and nothing crashes" is already this
panel's single biggest risk.

## 7. Out of scope

Per-band GR meters and history (the node tint already answers "is it working"). A ceiling handle
dragged on the graph — recorded in the V1.1 spec §8.3 and still V1.2 work. Bringing V1.0's five
existing numeric fields onto their declared steps. Any change to the DSP.

## 8. Rev-2 Disposition (weakness review of rev 1)

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

## 9. Rev-3 Disposition (weakness review of rev 2)

| Finding | Disposition |
|---|---|
| **P0.1** The manifest still does not protect existing V1.1 projects | **Accepted, and it is the sharpest finding either review produced.** Verified: `slider142` is record 94 and B5 starts at record 95, so inserting the panel record there leaves V1.0's 95-record prefix **intact** — the `--live` gate passes, the migration passes — while shifting all eighty B5–B8 records, so every already-saved V1.1 project reads them one parameter late. The plugin is in `Magdalena.RPP` today. The contract is now V1.1's **175** records as a frozen fixture, `slider143` at record 175, host tail 176..178, with an insert-after-142 build seeded as a defect that must fail *even though the V1.0 prefix check passes on it*. Rev 2's description of the migration failure was also wrong and is corrected. |
| **P0.2** `apply_band_dyn_global()` has no PDC publication contract | **Accepted.** `topo_pdc()` is called at line 1412, after the linear-engine geometry reconcile, with the ordering pinned in a comment. Both readings rev 2 left open were wrong: not calling it leaves `pdc_delay` stale after a Dyn gesture while the gate still passes; calling it inside the helper publishes before the reconcile. The helper now **rebuilds only**, `@slider` keeps its single post-reconcile call, and the `Dyn` and `Dyn Mode` writers call `topo_pdc()` after the helper — safe there because a GUI gesture has no reconcile. The gate requires both calls for exactly those two writers. |
| **P1.1** A press both creates and forbids the drag state | **Accepted — it was a literal contradiction.** The transition moved from the press to the threshold: mouse-down captures without entering edit mode; crossing four logical pixels starts the drag and clears edit focus; releasing below the threshold gives typing focus. |
| **P1.2** `writer` is not an implementable dispatch contract | **Accepted.** EEL2 has no first-class callables, and a generic `(table, offset)` writer would assign through `slider(computed_index)` — the exact thing V1.0 proved never reaches the parameter. `writer` is a numeric family ID resolved by one explicit dispatcher; only named writers assign, and the gate rejects computed assignment inside the controller. |
| **P1.3** Minimum height mixes geometry with persistent state | **Accepted.** Insufficient height is a **derived visibility state**: `slider143` records what the user opened, the window decides whether it can be drawn, and dragging a window edge never automates a parameter into the project, the undo history, or automation playback. All reservations and the 180 threshold are stated as logical units, matching how `gc_sc` and `gc_ret` are already used. |
| **P2.1** §2.3 still carried the rejected Micro step | **Accepted.** Now "percent of a bit, step 0.1 %, which yields 0.001 bit after the division by 100". |
| **P2.2** The field inventory still counted Stereo | **Accepted.** Twenty numeric fields, not twenty-one — Stereo is a segmented control. Also softened the `gc_button` claim: it draws and returns `hot`; consuming the click belongs to the arbitration. |

## 10. Rev-4 Disposition (review against EQall and Arthur's plugin)

| Finding | Disposition |
|---|---|
| **P0** `check_writers()` is the blanket gate the spec claims to replace, and the replacement has no schema | **Accepted.** "Per-writer" is not a specification. §4.1 now gives the record literally, and splits `rebuilds` from `publishes` — one field doing both is exactly how a writer that rebuilds but never republishes PDC passes the gate. The gate also asserts no writer calls `topo_pdc(` at all. |
| **P0** The 175-record fixture is described but never located | **Accepted.** It is `tests/fixtures/v11_declared_175.json`, generated by `--freeze` against the current build **before** panel work, committed on its own. Unnamed, it is how two people invent two fixtures and this spec's strongest safeguard turns out not to exist. |
| **P1** Write-then-rebuild order is unstated | **Accepted.** `apply_band_dyn_global(b)` folds `any_b` by reading sliders, so calling it before the write folds the previous value and leaves the state one gesture behind. The order is stated and gated. |
| **P1** §2.2 silently contradicts five of six keyboard-entry precedents | **Accepted.** The source says outright that typed values are NOT quantised for the five older fields; only `gc_w_qchar` clamps and quantises. The panel follows the minority, and now says so and why, instead of letting an implementer find two templates and guess. |
| **P1** Arthur's plugin has no Retina awareness and this could be copied | **Accepted.** He hit-tests raw constants (`CLIP_TOP = 42`, radius `<= 100`) and never touches `gfx_ext_retina`. The spec already stated the layout in logical units; it now says the same for every hit test, including the 4-pixel drag threshold. |
| **P1** The right-click alternative is an unrecorded trade-off | **Accepted.** Both references use right-click for keyboard entry, which removes the press/threshold ambiguity outright. Rejected here because right-click is already the band context menu — a deliberate earlier choice of the owner's — and a third meaning for one button is worse than the state machine. Now recorded as considered. |
| **P2** Knee is a difference in kind, not a gap | **Accepted, with the layout consequence.** EQall's "knee" is a binary switch between two transfer functions; Arthur's is a real dB knee; RCBitNova's cascaded soft+hard stages already give two regimes. Do **not** reserve screen space now. |
| **P2** "Solo" means band solo, not GR audition | **Accepted.** Named precisely in §6 so a future reader does not build the wrong feature. |
| **P2** Multi-edit deserves a stated reason | **Accepted.** Rejected because these eight bands are heterogeneous by construction, unlike points on one curve, while the off-by-one failure mode is this panel's worst. |
| *(reviewer's open question)* Does `@gfx` writing `pdc_delay` race the audio thread? | **Removed by construction rather than tested.** `topo_pdc()` writes variables REAPER reads; no GUI writer calls it now. The helper sets `pdc_dirty`, and `@block` — which already publishes PDC at topology commit — consumes it. Publication lands within one audio block, and the live PDC check becomes confirmation instead of the only defence. |
