# RCBitNova V1.3 HP/LP Range Plan: Weaknesses Review (Astra, third pass)

**Reviewed:** 2026-09-12, worktree HEAD `29909d4bcd154bfca69d7abb29ae5f43e937e034`.

- Read `2026-09-12-rcbitnova-v13-hplp-range-REVIEW-BRIEF.md` first.
- Reviewed the V1.3 plan, revision-3 spec, both spec reviews, and both plan reviews.
- Read the named V1.2 source, gates, curve/DSP oracles, null harness, compile checker, layout,
  migrator, fake, tests, and V1.1 fixture. Source line references below use the reviewed HEAD
  `29909d4` baseline and checkout-relative paths; `plan` means
  `docs/superpowers/plans/2026-09-12-rcbitnova-v13-hplp-range.md`.
- The Fable plan review was initially absent (`test -f` exited 1), then appeared during this
  review. It was read in full before finalization. Its extractor and commit-gate findings were
  independently reproduced and excluded from the new findings below. A concurrent extractor fix
  and accompanying test were also observed; this review did not edit those files.
- No Knowledge-vault files or live-REAPER commands were used. All projections and probes were
  in memory; no implementation files were changed.

## Summary

Both earlier plan reviews are treated as known and are not repeated here.
Six additional findings are verified below. The two behavioral problems survive correction of
those earlier findings: the proposed graph can misrepresent the new FIR knee, and the new top-bar
fields do not own their pointer events, allowing a field gesture to change an unrelated band.

Three tooling omissions prevent the intended checks from proving the intended build. One stale
test expectation makes another advertised green checkpoint fail.

| Priority | Count | Meaning |
|---|---:|---|
| P0 | 2 | Produces a wrong curve or unintended audio-affecting parameter changes |
| P1 | 3 | Missing integration forces the implementer to invent repairs to the verification path |
| P2 | 1 | A supporting green-checkpoint claim is contradicted by an existing assertion |

**Offline verification:**

```text
python3 -B -m pytest tests/test_rcbitnova_dsp.py -q -p no:cacheprovider
282 passed in 11.51s; exit 0

python3 -B tools/rcbitnova_gates.py --source-only
OK --source-only: 34 sites, 24 table entries, 20 writers, 37 addresses; exit 0
```

These are baseline results, not evidence that the proposed V1.3 edits pass. Each finding states
the separate source check or offline reproduction used.

## P0 Findings

### P0.1: Matching the nearest stored grid point hides a badly wrong FIR knee at the actual requested frequency

Task 4's test chooses the grid entry nearest `f`, then evaluates the direct DTFT at that entry's
frequency, not at `f` (`plan:448-457`). Correcting its already-known API mistakes does not repair
this test's blind spot: it never tests interpolation between entries.

The production cache remains **2048 log-spaced points**, and the trace then reduces this to
**512 display points** (`JSFX/RCBitNova V1.2:836-842`, `:2221-2223`). The realized reader
interpolates bits between cache entries (`:1432-1436`); drawing clips each display vertex to the
viewport and connects those vertices with straight segments (`:1396`, `:1469-1475`). Widening all
four coordinate sites consistently does not make either reduction accurate at a steep new knee.

**Verified:** ran `dsp.fir_brick_kernel(32768, "lp", 21500, 14, 96000)`, then
`curve.realized_bits_grid(kernel, 96000, n_out=2048, fmax=24000)`. This is the production High
geometry and Kaiser beta: `JSFX/RCBitNova V1.2:895`, `:1612-1613`, `:528-535`. The source's
Brick construction (`:968-1011`) matches `tools/rcbitnova_dsp.py:1099-1114`. The reference DTFT
used the formula in `tests/test_rcbitnova_dsp.py:2405-2411`.

All four **LP** nearest-entry assertions pass at the plan's 0.05-bit tolerance:

| Requested test frequency | Frequency actually tested | Absolute DTFT error, bits |
|---:|---:|---:|
| 21500 | 21482.040498 | 0.000000807 |
| 22000 | 22009.248691 | 0 |
| 23500 | 23506.382346 | 0 |
| 24000 | 24000 | 0 |

But the two entries bracketing **21500 Hz** are approximately
`(21482.040498, 0.000000285)` and `(21556.575620, -23.253496664)`.
At 21500, the actual reader returns **-5.610382 bits**; the direct DTFT is
**-1.173724 bits**. That is **4.436658 bits / 26.711 dB** of error before the display reduction.
A literal translation of the planned EEL2 reader reproduced the Python reader to about 1e-12.

The displayed polyline is not identical to that reader-at-cutoff result, so it must also be tested:
its neighboring 512-point vertices are 21478.546170 and 21778.636019 Hz. Following the source's
per-vertex clipping and straight-line drawing gives approximately **-0.287815 bits** at 21500,
also wrong versus the DTFT's -1.173724. These are numerical source projections, not a claimed
live screenshot or audio measurement.

**Required change:** test the exact requested frequencies through `sample_grid_bits`, include
off-grid knee probes for both HP/LP and Normal/High, and bound the final displayed-polyline error
as well. Specify a rendering solution that resolves the new knees, such as cutoff-aware sampling
or a suitably validated denser representation. Do not merely relax the nearest-entry tolerance.
Any cache-size change must also update the layout/address proof; no audio-DSP change is needed.

### P0.2: A click on the new frequency field can enable and drag a band underneath it

Task 6 places both fields inside the plot, beside the global buttons (`plan:760-772`), and only
requires drawing them before the field controller. That is too late for pointer ownership.

The source calculates `gc_in_plot` without excluding the top bar
(`JSFX/RCBitNova V1.2:2195-2197`), collects band hits at `:2292-2298`, and excludes only the
bottom strip/panel at `:2316`. A disabled hit is enabled at `:2386`, and a band drag is armed at
`:2389-2398`. Only afterward are the top-bar controls drawn at `:2600` onward and the field
controller run at `:2758-2768`. Publishing `gc_pfield` there cannot undo an earlier band write.

**Verified:** evaluated the proposed rectangles and existing hit-test formulas at the source's
900x500 reference size. The HP field occupies `x=308..418`, `y=14..34`. A legal disabled band at
260 Hz, Macro=4, Micro=0, Ratio=1 has its widened-axis node at approximately `(347.501174, 10)`.
Clicking `(347.501174, 15)` is simultaneously inside the HP field and within the node's 8-pixel
hit radius. The band-enable condition and band-drag capture both fire before field capture.
Dragging down 24 logical pixels then lowers that band's Macro from 4 to 3 through `:2427-2436`
while the new field controller also handles the same drag. A simple focus click alone already
enables the previously disabled band.

This is distinct from the known field-drag sensitivity and ID-resolver defects: even correctly
resolved metadata and usable sensitivity leave both controllers handling the event.

**Required change:** compute top-bar hit rectangles before node arbitration and give those
controls exclusive ownership for click, drag, wheel and context-menu handling. Suppress underlying
node enable/selection/drag paths for a control-owned press, retaining ownership until release.
Add an offline overlap case for each new field, with a disabled and an enabled band underneath,
asserting that no unrelated slider changes.

## P1 Findings

### P1.1: Default-only source retargeting leaves the CLI and clean-source test explicitly checking V1.2

Task 2 changes `check_source`'s default to `V13` and retargets the four `gates.V12` file opens
(`plan:166-168`, `:185`). It misses two explicit call arguments:

- `tools/rcbitnova_gates.py:556`: `check_source(V12, project=...)` in the CLI.
- `tests/test_rcbitnova_dsp.py:2811`: `gates.check_source(gates.V12, project=...)` in the
  clean-source test. This is a call, not one of the four opens.

**Verified:** replaced `check_source` in memory with a recorder whose default path was V1.3,
then called `main(["gate", "--source-only"])`. It still received
`JSFX/RCBitNova V1.2`. Grepped the separate test call above.

Thus the CLI can initially report success against the frozen source. Once the new frequency
checks are added, it instead fails against V1.2's intentionally unchanged declarations/constants.
Neither result says whether V1.3 is correct. The clean-source test has the same problem even
after all four file opens are changed.

**Required change:** explicitly retarget both call sites, or route them through a single
under-test source constant. Add an offline CLI-dispatch test that records the path and requires
V1.3; make success/failure diagnostics identify that path. Keep historical V1.2 checks separate.

### P1.2: The live gate still demands unchanged HP/LP ranges in its earlier V1.0-prefix comparison

Task 5 replaces the frozen 175-record prefix comparison with the new 176-record expected manifest
(`plan:553-564`). It does not replace the **earlier, independent** comparison against V1.0 in
`tools/rcbitnova_gates.py:508-516`. Task 2 retargets the under-test manifest to V1.3, so this loop
then compares V1.0's first 95 records to V1.3's.

The only exemption in that loop is the sixteen ceiling-step records. HP/LP frequency records
85 and 89 are not in it. The `else` branch requires complete record equality, including `hi`,
before the new expected-manifest assertion is reached.

**Verified:** read records 85/89 from the frozen fixture, projected their upper bounds to 24000,
and ran the relevant equality/exemption checks. Both equality checks fail; neither index is in
`_fine_ceiling_indices()`. Source declarations confirm V1.0 retains the old bounds. No live gate
was executed.

Even after all known migration/API repairs, Task 5's promised `--live` exit 0 is unreachable for a
correctly widened build under the retained comparison.

**Required change:** define ownership of both comparisons explicitly. Preserve the historical
V1.0-to-V1.2 check on the historical versions, and use the new fixture/table for V1.3, or replace
the old loop with an equally strict version-aware comparison. Add an offline record-comparison
test that accepts only the two authorized upper-bound differences, while still rejecting changes
to default, step, name and unrelated ranges.

### P1.3: `BASE` does not already name V1.2; leaving it unchanged compares a host parameter with panel state

Task 2 twice says the null harness's `BASE` **stays V1.2** (`plan:155`, `:173-174`). The actual
assignment is `BASE = "JS: RCBitNova V1.1"` at `tools/rcbitnova_nulltest.py:32`.
No later task supplies an explicit replacement assignment.

Task 8 then reads/replays 176 indices (`plan:984-993`). V1.1 has only 175 declared parameters:
`tools/rcbitnova_gates.py:34` and `tests/fixtures/v11_declared_175.json`. Consequently, its index
175 is the first host-tail parameter, **Bypass**, whereas V1.3 index 175 is the inherited
**panel-card state**. This is not a 176-declared-record comparison between V1.2 and V1.3.

**Verified:** parsed the null module's assignments without importing or running its live path;
counted `^slider\d+:` declarations in V1.1 (175); checked the positional host-tail contract in
`tools/rcbitnova_gates.py:417`, `:482-491`, and the V1.2 panel declaration at
`JSFX/RCBitNova V1.2:234`. The cases at `rcbitnova_nulltest.py:36-59` do not set panel state.
Zero-valued records can therefore compare equal despite having different identities.

This is separate from the known raw-normalized-copy defect and the timing of Task 8: fixing
either does not change the version named by `BASE`.

**Required change:** explicitly assign `BASE = "JS: RCBitNova V1.2"`. Assert both effect identities,
the declared count, and the names/identity of copied records before rendering, including record
175. Add an offline test of the production state-copy boundary that rejects a 175-declared-record
source instead of treating its host tail as another declared value. The standalone arithmetic
test at `plan:1013-1021` cannot detect a wrong baseline.

## P2 Finding

### P2.1: Task 6 adds a 367-endpoint assertion but leaves the existing 351-endpoint assertion active

Task 6 sets `GC_FMETA = (304, 367)` and supplies a new test with a new name (`plan:655-669`).
The current suite already asserts `lay.GC_FMETA == (304, 351)` inside
`test_panel_metadata_sits_above_the_tables_and_below_mb_band`
(`tests/test_rcbitnova_dsp.py:2883-2891`). No step updates or replaces that test.

**Verified:** compiled that existing test function and the plan's new test in memory, temporarily
set `lay.GC_FMETA` to `(304, 367)`, and ran both. The proposed test passes; the existing one fails
at its 351 assertion. Task 6 Step 9's full-suite exit 0 is therefore false even with correct
metadata initialization and addressing.

**Required change:** update the existing under-test layout assertion to 367, retaining its
adjacency and capacity checks. If a historical V1.2 assertion is retained, bind it to a separately
versioned historical layout rather than the same mutable global.

## Recommended Revision Order

1. Retarget both explicit source-check callers (P1.1), alongside Fable's already-known body
   extraction repair, then verify that each existing producer/reader seed fails for its own reason.
2. Make the comparison targets honest: separate the historical live-prefix contract from V1.3
   (P1.2), explicitly switch the null baseline and validate record identities (P1.3).
3. Replace nearest-entry-only acceptance with exact-frequency and final-polyline tests; resolve
   the reproduced 21.5 kHz knee errors without changing audio DSP (P0.1).
4. Establish top-bar pointer ownership before drawing/controller integration, and test underlying
   band immutability for both new fields (P0.2).
5. Update the existing metadata-range test rather than adding a contradictory one (P2.1).
6. Apply these alongside both earlier reviews, then rerun offline gates before the
   owner's separately authorized live acceptance. This review makes no live-compilation,
   migration-success, or rendered-audio claim.
