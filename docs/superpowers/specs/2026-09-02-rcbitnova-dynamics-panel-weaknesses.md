# RCBitNova Dynamics Panel: Rev 2 Weaknesses

**Reviewed:**

- `docs/superpowers/specs/2026-09-02-rcbitnova-dynamics-panel-design.md` (rev 2, `9343018`)
- implementation baseline `JSFX/RCBitNova V1.1` at `9343018`
- current source gate, compile check, migration, FakeReaper, and migration tests

## Summary

Rev 2 substantively closes all nine findings from the rev 1 review. The control set, field
quantisation, one-card representation, geometry, per-writer rebuild manifest, and live immediate-
application matrix are now concrete enough to plan.

Two release-blocking contracts are still incomplete. The compatibility gate protects only V1.0's
95-record prefix, not the 175-record parameter map of V1.1 instances already used in projects. The
new global dynamics helper also does not say where `topo_pdc()` is called; neither possible implicit
interpretation preserves both immediate GUI application and the current `@slider` ordering.

| Priority | Count | Meaning |
|---|---:|---|
| P0 | 2 | Can silently corrupt existing V1.1 project parameters or leave host latency stale |
| P1 | 3 | Core interaction or responsive-state contract is internally ambiguous |
| P2 | 2 | Residual contradictions and incorrect supporting counts |

## P0 Findings

### P0.1: The proposed manifest still does not protect existing V1.1 projects

The instruction to declare `slider143` last is correct, but the reason and the proposed gate are
not. In the current declaration order, `slider142` is record 94 (zero-based), the final record of
V1.0's 95-record block. Declaring `slider143` immediately after it would produce:

- records 0..94: the same V1.0 prefix;
- record 95: Panel state;
- records 96..175: the shifted B5-B8 block.

Therefore the rev 2 `--live` check in section 5 still passes: it compares only V1.0's 95 records to
the first 95 V1.1 records and checks the total count. The V1.0 migration also still copies its 95
declared values correctly. What breaks is more dangerous and currently ungated: every saved V1.1
instance has its B5-B8 values interpreted one parameter later when reopened. The spec explicitly
says V1.1 is already used in `Magdalena.RPP`, so this is a live project-compatibility contract, not
only a migration concern.

The related failure description in section 4.2 is also inaccurate. With the required append-last
order but a stale migration constant, host Bypass/Wet/Delta land in Panel state/host Bypass/host Wet;
they do not land in B5 Enable/B5 Type/B5 Freq. The latter corruption comes from inserting the panel
record before B5-B8.

**Required change:** freeze the current 175 declared V1.1 records as a source or live manifest
fixture and require them to be the exact first 175 records of the panel build. Require `slider143`
at record 175 and the host tail at 176..178. Keep the separate V1.0 95-record comparison for the
migration contract. Seed an insertion-after-`slider142` defect; it must fail even though the V1.0
prefix still passes.

### P0.2: `apply_band_dyn_global()` has no ordering-safe PDC publication contract

The current source does two separate things at two deliberately separated sites:

1. lines 1313..1325 rebuild `mbmode[]`, `hc[]`, and the `any_b` fold;
2. line 1412 calls `topo_pdc()` only after linear-engine geometry reconciliation.

Rev 2 says `apply_band_dyn_global(b)` factors the first scan and is called both from `@slider` and
from affected GUI writers. It also promises that Mode-B lookahead/PDC is published from `any_b`, but
the helper contract lists only `mbmode`, `hc`, and the `any_b` contribution.

If the helper does not call `topo_pdc()`, a Dyn or Dyn Mode GUI gesture can update `any_b` while
`pdc_delay` remains stale; requiring the helper in the writer gate still passes. If the helper does
call `topo_pdc()`, calling it at the old scan site moves PDC publication before the geometry reconcile,
contrary to the source's explicit ordering contract. A second call later may overwrite it, but that
is no longer "behaviour unchanged" and publishes an intermediate value unnecessarily.

**Required change:** split rebuild from publication explicitly. For example,
`apply_band_dyn_global(b)` rebuilds `mbmode`, `hc`, and the full `any_b` fold only; affected GUI
writers then call `topo_pdc()` after it. In `@slider`, keep `topo_pdc()` at its existing post-reconcile
site. The per-writer source gate must require both calls for Dyn and Dyn Mode, and the live check must
read reported PDC immediately after each gesture.

## P1 Findings

### P1.1: A field press both creates and forbids the state needed to drag

The click-arbitration rule says a panel field press gives it typing focus and arms a drag. The drag
rule then says a drag never begins while that same field has typing focus. On the initiating press,
both conditions are true, so a literal implementation can never cross from armed to dragging.

**Required change:** define the transition at release/threshold. A common contract is: mouse-down
arms capture without entering edit mode; release below four logical pixels gives typing focus;
crossing the threshold starts dragging and clears any old edit focus. If already-focused fields need
different behaviour, state that separately. Test click-release-type-Enter and press-move-release as
distinct flows.

### P1.2: A metadata `writer` is not yet an implementable JSFX dispatch contract

The metadata tuple contains `writer`, and Enter is said to dispatch through it. EEL2 does not provide
the kind of first-class callable reference that this wording suggests. More importantly, this plugin
has already proved that writing `slider(computed_index)` can move the GUI value without reaching the
real parameter. A generic implementation based on `(table, offset)` would reintroduce that exact
failure while appearing consistent with the tuple.

**Required change:** define `writer` as a numeric writer-family ID and specify one explicit dispatcher
that calls `gc_w_dyn`, `gc_w_dynmode`, and the other named writers. The metadata may choose a writer;
only the named writer may assign the slider. The source gate should reject computed slider assignment
inside the field controller as well as checking all 88 named branches.

### P1.3: The minimum-height fallback mixes geometry with persistent parameter state

The spec says an expanded card "closes" when the graph falls below 180 px, but the open card is now
an automated, persisted slider. It does not say whether resizing a window writes and automates
`slider143 = 0`, or merely suppresses the card until enough height returns. Those behaviours differ
after resize, undo, project save, and automation playback. Window geometry should not silently write
a plugin parameter unless that is an explicit product decision.

The unit also needs pinning. Current `@gfx` uses physical `gfx_w/gfx_h` on Retina and scales logical
coordinates through `gc_sc`; `gc_small` separately divides by `gc_ret`. The raw equations and the
"180 px" threshold do not state whether 180 means logical or physical pixels.

**Required change:** make insufficient height a derived visibility state, or explicitly require a
persisted/automated close on resize. State that all reservations and the 180 threshold are logical
units and show the `gc_sc`/`gc_ret` comparison. Add Retina plus shrink-and-regrow expectations to the
resize test.

## P2 Findings

### P2.1: Section 2.3 still gives Micro the rejected step

The table correctly says Micro is declared in percent with step 0.1%, yielding 0.001 bit after
division by 100. Section 2.3 still says "Micro (percent of a bit, step 0.001)." That is the rev 1
unit error the disposition says was removed.

**Required change:** replace it with "Micro (percent of a bit, step 0.1%, yielding 0.001 bit)."

### P2.2: The controller inventory still counts Stereo as an editable numeric field

Section 4.3 says there are 21 editable fields: two per row times eight, plus five in the card. But
Stereo was correctly changed to a segmented control, leaving four numeric fields in the card:
Attack, Release, Soft Micro, and Hard Micro. The maximum is therefore 20 numeric fields, plus the
Stereo segmented control. The metadata inventory should say whether it contains only numeric fields
or all panel controls.

The nearby claim that `gc_button` "handles hover and click" is also slightly too strong: current
`gc_button()` draws and returns `hot`; the caller combines that with the frame's `gc_click`. The new
single-owner arbitration remains responsible for consuming the click.

## Recommended Revision Order

1. Add the frozen 175-record V1.1 prefix oracle and correct the compatibility explanation.
2. Separate global dynamics rebuild from post-rebuild PDC publication and pin both call sites.
3. Resolve field focus-versus-drag transitions and define writer-ID dispatch.
4. Define resize as either derived visibility or a deliberate parameter write, in logical units.
5. Correct the two residual Micro/count statements.

After those changes, the implementation plan can be written against contracts that fail loudly for
both known danger classes: audio state that lags the GUI and project state that shifts by one host
parameter.
