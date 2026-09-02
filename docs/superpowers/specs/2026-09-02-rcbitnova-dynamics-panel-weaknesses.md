# RCBitNova Dynamics Panel: Spec Weaknesses

**Reviewed:**

- `docs/superpowers/specs/2026-09-02-rcbitnova-dynamics-panel-design.md` (rev 1)
- implementation baseline `JSFX/RCBitNova V1.1` at `c892d4c`
- current source gate, compile check, migration, FakeReaper, and null harness

## Summary

The chosen product shape is coherent: eight comparable rows, both cascade stages visible, and one
expanded detail area. The separation between Macro and Micro also preserves the established
one-gesture/one-slider rule.

The spec is not yet safe to implement. It treats all eleven new writers as local band rebuilds, but
three parameter families depend on state maintained only by the global `@slider` pass. It also
updates only one of several contracts affected by adding a declared parameter. The remaining gaps
are mostly interaction-state and geometry decisions that need to be made before code, not while
debugging the finished panel.

| Priority | Count | Meaning |
|---|---:|---|
| P0 | 2 | Can produce a GUI that displays new values while audio or migration remains wrong |
| P1 | 5 | Material interaction, persistence, range, or geometry ambiguity |
| P2 | 2 | Incorrect or incomplete supporting claims |

## P0 Findings

### P0.1: “Both rebuild calls” do not apply several dynamics parameters to the engine

The proposed writer contract requires every new writer to call `setup_band(b)` and
`setup_band_dyn(b)`. In the current source, `setup_band_dyn()` updates detector coefficients,
`dp[]`, `dm[]`, and `bp[]`. It does **not** update:

- `mbmode[b]`, which owns Dyn Mode;
- `hc[b]`, which owns Hard Ceiling Macro + Micro;
- `any_b` and the resulting Mode-B lookahead/PDC state.

Those values are rebuilt only in the global `@slider` scan. The current source explicitly says GUI
writers must not rely on `@slider` running after `slider_automate`, which is why existing writers
recompute their derived state inline.

Consequences:

- `gc_w_dynmode` can move the field and Param value while audio keeps the old mode;
- `gc_w_hardceil` and `gc_w_hardmicro` can display a new threshold while `hc[]` stays old;
- `gc_w_dyn` can enable/disable local dynamics while `any_b`, lookahead, and PDC remain stale.

The null test does not catch this because it renders static loaded state; the failure occurs after a
GUI gesture.

**Required change:** extract the relevant global scan/topology publication into an explicitly safe
helper or give the affected writers exact inline updates. The writer gate must express per-writer
side effects, not merely require the same two calls from all twenty writers. Add live or deterministic
tests that change Dyn, Mode, and both Hard threshold components through the panel and immediately
verify `dp[]`, `mbmode[]`, `hc[]`, `any_b`, and reported PDC before any unrelated parameter change.

### P0.2: Adding slider143 changes more contracts than the live-gate constant

The spec says the declared count moves 175 -> 176 and mentions updating the live gate. Current code
also hard-codes the old shape in:

- `tools/migrate_v10_to_v11.py` (`N_DECLARED_V11 = 175`, host tail at 175..177);
- `tests/_reaper_fx_fake.py` (`N_DECLARED_V11 = 175`);
- migration tests that assert host Bypass at index 175 and Wet at 176;
- `tools/rcbitnova_compile.py`, which requires 178 total parameters;
- messages and shape checks that expect V1.1 to report 175 + 3.

If only `rcbitnova_gates.py` changes, the compile check fails and the supported V1.0 -> V1.1
migration refuses the panel build or writes the host tail to the wrong positions.

Declaration **order** is equally important. `slider143` is numerically between the global/filter
block and B5 declarations, but V1.1 compatibility is based on declaration order, not numeric ID.
Inserting it beside `slider142` shifts all eighty B5-B8 records and breaks the claimed 175-record
prefix. It must be declared textually after all 175 existing declarations, despite its number.

**Required change:** define one shared declared-count/host-tail contract and list every consumer.
Require the exact existing 175 records to remain a prefix, append `slider143` as record 175, and
place host Bypass/Wet/Delta at 176..178. Extend migration and FakeReaper tests before changing the
plugin.

## P1 Findings

### P1.1: The core numeric-entry and vertical-drag state machine is not designed

The product decision says every value uses a numeric field plus vertical drag, but §4 specifies only
field drawing and an ID namespace. It does not define:

- drag capture, threshold, origin value, sensitivity, fine modifier, or release;
- clamp and quantisation rules for each parameter;
- keyboard dispatch from `100 + band*10 + slot` to the correct writer;
- how a click is arbitrated between focus, toggle, expansion, and drag;
- how the existing readout click handler avoids clearing a panel field focused earlier in the frame;
- automation begin/end behaviour for a continuous drag.

The current `gc_field()` only draws, hit-tests, and displays the shared edit buffer. All click focus,
keyboard parsing, and commit dispatch are open-coded later in `@gfx`; generalising the drawing
primitive alone does not generalise the interaction.

**Required change:** specify one field controller with capture/edit states and a parameter metadata
table (range, step, decimals, drag scale, writer ID). Give at least one complete flow for click-type-
Enter and one for vertical drag, including cancellation and focus transfer.

### P1.2: “One card expanded” conflicts with an unconstrained eight-bit mask

The geometry reserves space for one expanded card, while `slider143` accepts every value 0..255.
That representation permits any subset of the eight cards. It can acquire multiple bits through
Param, automation, a preset, or a faulty click transition. The spec gives no load-time sanitation or
single-card transition rule.

**Required change:** either use an enum (`0 = none`, `1..8 = expanded band`) or define the only valid
mask states as zero and powers of two. On every load and write, normalise invalid values. Specify
whether clicking the open band collapses all, and require persistence/automation tests for invalid
and valid states. The slider write itself also needs a named assignment plus `slider_automate`.

### P1.3: The Micro step is stated in the wrong unit

The spec calls Soft/Hard Micro a slider with step `0.001`. In V1.1 all ceiling Micro sliders are
declared in **percent of a bit** with step `0.1`; multiplying by `0.01` makes that a resulting
resolution of `0.001 bit`.

This distinction controls the writer's quantisation and keyboard behaviour. Using a slider step of
0.001 would create off-grid Param values and repeat the exact GUI/host reproducibility defect that
the current writers were built to avoid.

**Required change:** state `Micro: -100..100 %, step 0.1 % (0.001 bit after /100)`. Pin writer steps:
Macro 0.05 bit, Micro 0.1 %, Attack 0.01 ms, Release 1 ms, enums/toggles 1. Define the displayed total
as `Macro + Micro/100` bits and its decimal precision.

### P1.4: Stereo cannot be rendered or edited by the proposed numeric primitive as written

The card promises `Stereo` as `Linked / Dual L/R / Dual M/S`, but `gc_field_at(..., value, dec)`
renders a number and the existing keyboard parser accepts numeric characters. No enum-label path,
menu, cycle behaviour, or vertical-drag mapping is specified.

**Required change:** define Stereo as a segmented/three-state control, an enum field with label
mapping, or explicitly map integer entry/drag to the three labels. Its visual and keyboard contract
must be testable; showing `0`, `1`, `2` does not meet the stated card design.

### P1.5: Geometry claims do not match the current V1.1 layout or define legacy-window behaviour

Relative to the plot bottom, current V1.1 places:

- fields at +6..+26;
- the effective-value text at y = +32 (plus its glyph height);
- the band strip at +50..+68.

The spec reports the summary at +26..+40, the strip at +44..+62, and 22 spare pixels. The real
84-pixel reservation leaves about 16 pixels after the strip. The final reservations 228/318 can
still be made to work, but their internal placement must be derived from the actual offsets.

The release-note claim that an existing 900x500 window cuts off the panel also contradicts the
proposed “graph shrinks” model. With reservation 228, that window yields a roughly 262-pixel graph;
with 318, roughly 172 pixels. The panel fits unless a minimum graph height is imposed, but no such
minimum or clipping/scrolling policy is defined. The expanded area is described as one row of five
fields yet budgeted at approximately 90 vertical pixels, also without an exact card height.

**Required change:** provide equations and y-ranges for graph, existing chrome, eight rows, expanded
card, and bottom padding in collapsed/expanded/small states. Decide a minimum graph height and what
happens below it. Verify 900x500 legacy, 900x640 default, Retina, narrow, short, and resize while a
card is open.

## P2 Findings

### P2.1: The writer-manifest description hides its required table mapping

The existing writer gate assumes every writer uses `stb` plus one offset. The eleven new writers
span `dynb` and `ceb`, with different offsets and behaviours. “Checks every number against the base
tables” is not enough to prevent an implementation from extending the current static-only
`WRITERS` structure incorrectly.

**Required change:** specify each writer as `(table, offset, step, derived-effects)` and generate all
eight expected named sliders from that record. Include one seeded wrong-table defect, not only a
wrong numeric branch.

### P2.2: Verification checks reachability but not immediate audible application

The live matrix asks whether each parameter is reachable. A writer can satisfy that by changing the
slider and Param display while leaving `mbmode[]`, `hc[]`, or PDC stale, which is exactly P0.1.

**Required change:** for Dyn Mode, Dyn Enable, Hard Macro, and Hard Micro, require an immediate audio
or internal-state observation after the panel gesture. Also test one gesture per writer on B1, B4,
B5, and B8 so both legacy and appended slider-number branches are exercised.

## Recommended Revision Order

1. Design the global dynamics-apply helper and per-writer derived-effects contract.
2. Define declaration order and update every 175/178 consumer, migration first.
3. Replace or constrain the expansion mask to enforce one open card.
4. Specify the shared field interaction state machine and exact parameter metadata.
5. Correct the Micro units and derive the complete geometry from current V1.1 coordinates.

The panel concept itself is strong. Once these contracts are explicit, implementation can remain a
GUI-only change while still respecting V1.1's unusually strict audio and project-compatibility
guarantees.
