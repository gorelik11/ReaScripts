# RCBitNova V1.1 Eight Dynamic Bands: Spec and Plan Weaknesses

**Reviewed:**

- `docs/superpowers/specs/2026-08-22-rcbitnova-v1.1-eight-dynamic-bands-design.md` (rev 1)
- `docs/superpowers/plans/2026-08-22-rcbitnova-v1.1-eight-dynamic-bands.md` (rev 1)
- implementation baseline `JSFX/RCBitNova V1.0` at `503a6fc`

**Review method:** checked the proposed layout, source gates, GUI work, migration, and live gates
against the shipped V1.0 source. This is not a restatement of the design.

## Summary

The uniform eight-band direction is substantially simpler than the superseded split-count design,
and the final eight-band low map and the `lp_base = 131072` result are sound. The current plan is
not yet executable as written, however. Four issues can either stop the pre-flip workflow outright
or let a wrong slider map pass its strongest gate. The GUI task also does not meet the spec's stated
20-parameter reachability contract.

| Priority | Count | Meaning |
|---|---:|---|
| P0 | 4 | Blocks implementation or permits a central mapping defect to pass |
| P1 | 7 | Material correctness, test, or workflow weakness |
| P2 | 2 | Incorrect documentation or stale references |

## P0 Findings

### P0.1: Task 6 leaves 11 of each band's 20 parameters unreachable from the custom GUI

The spec's live contract says that all 20 parameters must be reachable for all eight bands
(`design` §8.7). Task 6 adds controls only for the nine static parameters:

- enable, Type, Placement, and Q Character through the node menu;
- Frequency, Macro, Micro, Ratio, Q through the six-field readout.

It adds no custom-GUI path for Dyn Enable, Dyn Stereo, Soft Ceiling Macro/Micro, Attack, Release,
Dyn Mode, Soft, Hard, or Hard Ceiling Macro/Micro. These are the remaining 11 parameters. The host
generic parameter list is not an implementation of the custom GUI described in §6; if using it is
intended, the reachability gate becomes nearly vacuous because the sliders are already declared.

**Required change:** either add a selected-band dynamics editor covering all 11 controls, or narrow
the product contract explicitly and remove “every one of a band's 20 parameters reachable” from
the acceptance criteria. The live reachability matrix must name the interaction used for each of
the 20 parameters.

### P0.2: The pre-flip source gate requires Task 6 code before Task 6 exists

Task 4 Step 2 defines `gfx-hit-test` as:

```python
r"gc_hit_n = 0;\s*\ngc_b = 0;\nloop\((\w+),"
```

V1.0's hit test begins with `gc_hover = -1; gc_b = 0; loop(N_BANDS, ...)`; `gc_hit_n` is introduced
only by Task 6 Step 6 for coincident-node cycling. Task 4 Step 6 nevertheless requires the entire
pre-flip gate to pass before Task 5, and Task 6 comes after that. The claimed sequence cannot pass.

There is a related ownership gap: the writer manifest requires `gc_w_type`, `gc_w_place`, and
`gc_w_qchar`, but those functions do not exist in V1.0. Task 3 says all nine writers must be made
eight-way without giving a concrete step that creates the three new writers; Task 6 merely calls
them.

**Required change:** give Task 4 a pre-Task-6 manifest and a final manifest, or move cycling and the
three missing writer implementations before the pre-flip gate. Add a test proving both phases pass
at the exact commits where the plan says to run them.

### P0.3: `eval_init()` cannot parse the planned base-table declaration

Task 3 declares all bases on one line:

```eel2
stb = 272; dynb = 280; ceb = 288;
```

Task 4's `eval_init()` uses one anchored `ASSIGN.match()` per line. It can evaluate only the first
assignment, while `wanted` contains `stb`, `dynb`, and `ceb`. Consequently `dynb` and `ceb` are
reported missing and the source gate fails before checking the implementation.

The separate `base-tables` regex does not repair this because `eval_init()` is independently
required to produce all three values.

**Required change:** put each declaration on its own line or parse every assignment on a line with
`finditer`. Add a parser unit test using the exact EEL2 declaration that Task 3 will insert.

### P0.4: The gate checks table addresses but never checks table contents

Every band-slider read will depend on the 24 words in `stb[]`, `dynb[]`, and `ceb[]`. The proposed
gate verifies only that the three arrays start at 272, 280, and 288. `eval_init()` cannot execute the
`loop(N_BANDS, ...)` that fills them, the site manifest has no row for their values, and
`GuardedMemory` does not model these table accesses.

A defect such as `stb[6] = 175`, a wrong ceiling stride, swapped tables, or an uninitialised B8 entry
can therefore redirect every read for a band while the address comparison, writer manifest, and
forbidden-pattern checks all pass. The seeded-defect table also contains no mutation in this class.

**Required change:** make the 24 values part of the source contract. Either initialise them
explicitly and compare all entries, or teach the parser to evaluate the fill loop. Extend the model
and seeded defects to reject one wrong entry in each table and one missing final entry.

## P1 Findings

### P1.1: The selector strip is placed on top of the readout fields

V1.0 defines `gc_fy = gc_py + gc_ph + 6*gc_sc`, then draws the fields from `gc_fy` through
`gc_fy + 20*gc_sc`. Task 6 defines `gc_sy = gc_fy + 2*gc_sc` and gives the strip a height of
`18*gc_sc`. It therefore occupies almost exactly the same vertical interval as the fields. Its
272-logical-pixel width also covers the first field and much of the second.

The proposed ownership code has two ordering problems as well:

- `gc_fy` is currently computed near the end of `@gfx`, after node interaction, but the plan needs
  `gc_sy` before node interaction. Unless layout calculation is moved, it uses stale/uninitialised
  geometry on the first frame and after resize.
- clearing `gc_hover` and `gc_hit_n` before the later hit-test loop does not reserve the event; that
  loop immediately repopulates them.

**Required change:** allocate a separate row in the layout, move all geometry calculation before
hit testing, and guard node hit testing/click handling with `!gc_strip_hot`. Add normal and small
window screenshots plus click tests proving that fields, strip, and nodes do not overlap.

### P1.2: The GR tint does not represent the gain actually applied

Task 6 computes:

```eel2
gc_gr = 1 - min(eg[gc_b * 2], mbgc[gc_b * 2]);
```

This reads only the first channel and ignores the hard-stage envelopes `egh`/`mbeh`. Audio gain is
the product `eg * egh` in Mode A or `mbgc * mbeh` in Mode B, per channel. Taking the minimum of the
two mode memories also lets an inactive mode's stale state light the node after mode changes,
dynamics disable, band disable, or stage disable.

**Required change:** select the active mode, include enabled-stage guards, derive the displayed GR
from the actual per-channel cascade, and define whether the tint shows the maximum reduction across
channels or another documented aggregate. Add live cases for Mode A/B, linked/dual, soft-only,
hard-only, dynamics off, and band off.

### P1.3: The low-memory capacity claim is arithmetically wrong

The arrays consume 34 words per band, not 30:

`cf 8 + st 4 + det 4 + dst 4 + cst 4 + dp 4 + dm 1 + bp 3 + eg 2 = 34`.

With the proposed floating layout, 30 bands end at 1020 and 31 end at 1054, crossing literal
`mb_band = 1024`. Therefore the low map fits 30 bands, not “about 34”. The ninth-band value of 306
and the eight-band product decision remain valid.

**Required change:** correct §3.1 and the matching plan text, and make the model derive/report the
maximum instead of carrying a prose estimate.

### P1.4: The V1.0 GUI-region arithmetic is inconsistent with the source

The design §3.3 table gives V1.0 “GUI region end” as 51953. Shipped V1.0 has `gc_trace = 38275` and
clears 13638 words, so its exclusive end is 51913. A four-band pre-flip file with the new eight-word
`gc_hits` block ends at 51921. The final eight-band end 84765 is consistent, but the baseline and
delta in the table are not.

**Required change:** distinguish shipped V1.0, four-band pre-flip V1.1, and final V1.1 in the table;
derive every end and delta from the layout model.

### P1.5: The migration task is not self-contained and points at a dirty external repository

Task 7 Step 1 delegates its core implementation to “the superseded plan §Task 9”. A superseded
document should not be the only source for destructive migration details. Step 2 then asks for
changes to `/Users/macbook/projects/midi-composition/tests/_reaper_fakes.py`, outside this worktree
and project. That file currently already has uncommitted changes, so following the plan risks mixing
this feature with unrelated user work and leaves the test dependency outside the RCBitNova commit.

**Required change:** include the migration algorithm and invariants in this plan, and create a local
FakeReaper fixture under this repository. The migration tests and implementation must travel in the
same branch.

### P1.6: The strongest source-gate pieces are still pseudocode rather than an implementable gate

The plan names `check_source`, `check_sites`, `check_writers`, `SEEDED_DEFECTS`, CLI modes, and the
`@init` exemption, but does not define their complete implementations. The exemption is especially
risky: most helper functions are declared in the `@init` section, so exempting the whole section
from forbidden reads would also exempt real runtime readers.

**Required change:** specify section/function boundary handling and include a complete runnable gate
before Task 4's acceptance command. Seed defects inside an `@init`-declared helper to prove only the
table-fill statements are exempt.

### P1.7: The null/live gates do not yet justify “zero tolerance” or reproducibility

The null gate specifies a 32-bit float render with zero tolerance. That can prove equality of the
written 32-bit samples, but it cannot support a stronger claim of internal bit identity because
differences below output quantisation disappear. The plan also does not pin render bounds, sample
rate, block size, channel count, input fixture, tail, latency-alignment procedure, or the exact
sample comparator.

The CPU and `lp_base` checks remain manual prose without a result schema or capture script, so two
runs cannot be compared mechanically.

**Required change:** define the claim as exact equality of the rendered output, or capture/compare
64-bit output if internal differences matter. Pin the complete render fixture and comparator. Give
manual live/CPU results a checked-in schema and validation command.

## P2 Findings

### P2.1: Several task references still point to the wrong task

The plan says Task 9 performs the null or `lp_base` live checks in the introduction, Task 3, and
Task 7. Those checks are now Task 8 Steps 2 and 3; Task 9 is review/tagging.

**Required change:** replace the stale references so implementation order and acceptance ownership
are unambiguous.

### P2.2: The “28 sites” statement is no longer an auditable inventory

The design says all 28 sites from the old spec become `N_BANDS`, but the current document neither
lists those 28 sites nor maps them to the 15-row `SITES` manifest. A reader cannot establish whether
all 28 were retained, consolidated, or omitted without reopening a superseded document.

**Required change:** include the authoritative 28-site inventory in the current spec or plan and
give every site a gate row or a documented many-to-one mapping. The current revision should stand
on its own.

## Recommended Revision Order

1. Decide the real GUI reachability scope and add the missing dynamics UI if the 20-parameter
   contract stands.
2. Make Tasks 3–4 internally executable: create all writers, fix `eval_init`, split pre/final site
   manifests, and validate all 24 table entries.
3. Repair selector geometry/ownership and calculate GR from the active audio cascade.
4. Move FakeReaper into this repository and fully specify migration, null, live, and CPU artifacts.
5. Correct the memory/GUI arithmetic and stale task/site references.

After those changes, the plan's central idea is viable: one band count, regular base tables, an
append-only parameter declaration, and a live check for the page-aligned linear-phase workspace.
