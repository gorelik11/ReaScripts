# RCBitNova V1.0 GUI Curve Plan Rev 8: Weakness Review

**Reviewed plan:** `2026-08-14-rcbitnova-v1.0-gui-curve.md`
**Design baseline:** `2026-08-14-rcbitnova-v1.0-gui-curve-design.md`, rev 8
**Review posture:** executable-plan completeness, Python/EEL2 parity, cross-thread state ownership, interaction safety, and release-gate validity

## Overall Assessment

The revised plan fixes several important defects from its first review: realized caches now publish independently per engine, metadata slots are named, EEL2 stores bit magnitudes, `LIN_N` is raised to 2048, drag thresholds and half-away rounding are pinned, and CPU acceptance has an explicit threshold.

The plan is still not executable as written. Tasks 1–4 and Tasks 5–9 now describe different systems: the Python realized-grid task remains on the old 256-point magnitude contract, the EEL2 trace reader and invalidation code are absent, and the transcription test cannot parse the dump format it specifies.

## Findings

### P0. Task 3 is still the old magnitude-domain, 256-point implementation

Task 3 declares `n_out=256`, returns `(frequency, magnitude)`, interpolates linear magnitudes, and tests that the midpoint of `1.0` and `0.5` is `0.75`. Tasks 5–6 instead allocate 2048 points and store `log2(magnitude)` because interpolation must happen in bits; their correct midpoint is `-0.5` bits, equivalent to magnitude `sqrt(0.5)`.

The interface says `sample_grid`, while Task 1 calls an undefined `sample_grid_bits`. Even if that name were fixed, `hplp_mag()` returns the sampled bit value into `domain_mag()`, which multiplies it as though it were a linear magnitude.

**Required correction:** choose one end-to-end representation. The simplest contract is:

- `realized_bits_grid(..., n_out=2048)` returns `(frequency, bits)`;
- `sample_grid_bits()` returns bits;
- either `hplp_mag()` converts with `2 ** bits`, or `domain_bits()` sums every block in bits;
- Python and EEL2 use the same names, count, floor, and interpolation rule.

Rewrite Task 3 before any EEL transcription begins.

### P0. `gc_hplp_mag`, `gc_domain_mag`, and `gc_dom_used` still have no implementation

Task 5 promises these functions, and Task 7 calls them, but only `gc_svf_mag` and `gc_band_mag` receive code. A prose sentence is left to define all difficult behavior: Min versus Linear sources, separate HP/LP grid snapshots, bit interpolation, phase-conditional placement, Off and Min+Brick identity, serial composition, and audible-domain visibility.

This gap is especially dangerous now that band responses are linear magnitudes while realized grids are bits. A worker must invent the conversion point and can easily double-log or multiply bits.

**Required correction:** provide complete EEL2 code and transcription tests for all three functions before Task 6. Include Off, Min+Brick, Linear+Brick, separate HP/LP resolutions, and mixed placement families.

### P0. `gc_trace` is never filled, validated, or published

The plan reserves two final-trace buffers and separate `GCM_TIDX/GCM_TGEN` metadata, but Task 7 draws directly from `gc_domain_mag()` and never writes `gc_trace`, flips its index, or rechecks the HP/LP generations at frame end.

Consequences:

- the promised reader half of the seqlock is absent;
- a grid publication during drawing can mix generations in one frame;
- Task 9 attempts to dump “what the graph actually drew” from an array that no task populates.

**Required correction:** Task 7 must compute each candidate frame into inactive `gc_trace`, snapshot both engine `(generation,index)` pairs at start, recheck them after the final point, and publish `GCM_TIDX/TGEN` only if unchanged. Otherwise retain the previous completed trace.

### P0. Target invalidation is modeled in Python but never transcribed to `@slider`

`gc_snap`, `GCM_GTGT`, and `watched_fields()` exist on paper, but no JSFX task compares the 48 watched fields or bumps `gen_target`. Task 6 only bumps `GCM_GACT` in `topo_commit`; it does not implement immediate active-state paths or the cheap analytic-curve invalidation that §3.3 requires.

Band, Min HP/LP, sample-rate, Phase, and Resolution edits can therefore leave `gc_trace` stale even after its publication code is added.

**Required correction:** add a dedicated `@slider` transcription step with exact snapshot offsets and one test/source audit per watched field. Define the initial snapshot state, sample-rate reinit behavior, Min-placement immediate path, and how target and active generations gate trace recomputation.

### P0. The plan declares relative Macro drag but implements an absolute pointer solve

Global constraints say every drag is relative and pin Macro to one bit per 24 logical units. Task 2 nevertheless builds `macro_target(pointer_bits, micro, ratio)`, and Task 8's `gc_drag_macro()` solves the absolute effective-gain pointer through Bit Ratio.

Those interactions are not equivalent. A relative drag should start from `macro_at_down` and add quantized steps; it does not guarantee the node follows the absolute cursor. The live checklist still says the node must follow the cursor, preserving the old model.

There is no Frequency drag writer at all, relative or absolute.

**Required correction:** make the global rev-8 contract authoritative. Implement Macro as `clamp(macro_at_down + drag_steps(delta_y, 24))`, define Frequency's relative logarithmic mapping, and update Python tests and live expectations. Delete the obsolete absolute inverse unless the spec deliberately reverts to it.

### P0. The required 0.05 Bit Ratio declarations are never edited

The plan says all four Bit Ratio sliders change from step 0.1 to 0.05, but no task edits `slider17`, `slider27`, `slider37`, or `slider47`. Writing 0.05 values from `@gfx` does not update REAPER's slider metadata or generic slider behavior.

**Required correction:** add the four declaration edits in Task 5 and a source-level test that verifies range, step, ordering, and no slider renumbering. Add the promised compatibility check for loading every old 0.1-grid value.

### P0. The transcription test cannot parse its own dump schema

Task 9 defines nine columns:

```text
case_id sample_rate phase resolution_hp resolution_lp domain engine freq_hz bits
```

The Python loop still expects exactly two values per row, hard-codes 48 kHz, Both, and Linear, and treats the dumped `bits` column as a linear magnitude by calling `mag_to_bits()` on it. It also supplies no separate realized HP/LP grids to `domain_mag()`.

The test will either fail unpacking immediately or compare the wrong quantity against the wrong fixture.

**Required correction:** parse all named columns, select the matching fixture and realized grids by case, compare dumped bits directly to oracle bits, and assert matrix completeness before evaluating tolerance.

### P1. The Ratio no-op state is specified but not implemented

Spec rev 8 says Shift+Ratio drag is visibly locked when `Macro == 0` and `Micro == 0`, because changing Ratio cannot move the effective node. `gc_drag_ratio()` writes Ratio unconditionally in that state and no node code draws either locked state.

**Required correction:** decide whether Ratio truly locks or remains editable through a stationary node/readout. Then implement that choice consistently in the helper, node style, readout, Python tests, and live checklist.

### P1. The Python publication model does not model target or active generations

`CurveCache` declares `gen_target` and `gen_active` but never changes or returns them. Its snapshot contains only per-engine grid generations and indices. There is also no test that forces a generation change during a frame read and verifies fallback to the previous completed trace.

**Required correction:** model all three publication layers: per-engine grids, target/active invalidation, and final trace publication. Test mid-frame HP publication, mid-frame LP publication, topology commit, and target-only edits.

### P1. The 2048-point accuracy contract has no Python implementation or test

The plan raises the EEL cache to 2048, but Task 3 still exercises 64, 128, and 256 points. It adds no `<= 0.01 bit` reduction-error test against the full FFT and still covers only Brick kernels in the listed realized tests. The direct-DTFT sample points are mostly below an 8 kHz Brick cutoff and do not challenge the knee.

**Required correction:** add ordinary HP/LP kernels and Brick at worst-position cutoffs, multiple resonances, both resolutions, and 48/96 kHz. Compare all 2048 stored bit values and interpolated midpoints against dense FFT/direct-DTFT references.

### P1. The static memory inventory is internally inconsistent

Task 5 correctly expands `gc_meta` to 16 words and computes a total of 13456 words, but:

- the surrounding comment still says the block ends at 44555 with about 21000 words remaining, which are the old 6280-word numbers;
- `lp_base` is calculated from `gc_meta + 8`, not `gc_meta + 16`;
- only metadata slots 0..7 are named, so it is unclear whether 8 or 16 words are actually required.

The current region remains below the same 65536 boundary, but the asserted inventory and future boundary guard are false.

**Required correction:** choose 8 or 16 metadata words, recompute the exact end and remaining padding, and derive `lp_base` from the true end. Pin the arithmetic in a source-level memory test.

### P1. Task 7 still does not implement the layout contract

The code computes `gc_sc` but stretches the graph directly across `gfx_w/gfx_h`; it does not establish one centered 900x500 logical transform, apply `gfx_ext_retina`, implement the 480x280 minimum branch, or drop the readout below minimum size.

Overrange labels are printed beside nodes without collision ordering, in-plot constraints, or selected-node priority. The readout fields required by Task 8 are not drawn.

**Required correction:** finish the geometry and label algorithm before interaction. Drawing and hit testing must consume the same explicit logical-to-device transform.

### P1. Task 8 is still missing the actual input state machine

The helper functions do not implement node hit testing, four-unit drag threshold, dominant-axis capture, modifier snapshot, overlapping-node cycling, mouse release outside the window, Esc restore, wheel dispatch, or Frequency writes. Numeric entry remains a prose adaptation.

Global variables such as `gc_ratio_at_down` and `gc_q_at_down` are referenced without a capture step that initializes them.

**Required correction:** split Task 8 into explicit event-state subtasks and provide the concrete `mouse_cap`, `mouse_wheel`, and `gfx_getchar` transitions. Add live verification after selection/capture before adding parameter writes.

### P1. Q “one step” does not match the actual slider step

The Q slider's declared step is 0.001. `gc_drag_q()` uses 0.01 normally and 0.005 in fine mode, while the prose calls this “one step” and says Ctrl halves it. These are ten and five slider steps respectively.

**Required correction:** name the intended Q increments explicitly. If 0.01/0.005 are product choices, stop calling them one slider step and add exact tests for drag and wheel.

### P1. Reading live coefficient arrays has an unacknowledged torn-read window

`gc_band_mag()` reads seven `cf` words while `@slider` can rewrite those words through `svf_set`. The self-review claims no cross-thread write can occur, but the plan does not establish that REAPER serializes `@slider` against `@gfx`.

This cannot corrupt audio, but it can produce the same one-frame plausible spike the cache protocol is designed to avoid.

**Required correction:** either document a verified REAPER scheduling guarantee or include the coefficient read inside the target-generation retry/final-frame publication protocol so a concurrent slider update discards the candidate frame.

### P1. Task 10 reviews and ships the wrong revision model

The final review still cites spec rev 5 and asks whether a drag can expose an intermediate slider pair, even though rev 8 deliberately removed pair writes. The commit message still says “safe Macro/Micro writes,” and the self-review lists ratio inversion, canonical split, and write order as implemented scope.

`git add -A` can also stage unrelated user changes from a dirty worktree.

**Required correction:** update the final-review brief and self-review to rev 8, rename the Task 8 commit, and stage only the intended V1.0 files before the as-shipped commit.

### P2. The plan header and file inventory still describe deleted machinery

The Goal says nodes write Macro/Micro. The file table says `rcbitnova_curve.py` provides Macro/Micro split, Ratio inversion, and write-order choice. The new module docstring still cites design rev 5.

**Required correction:** update the handoff surface before dispatching workers; these are the first instructions they will use to infer scope.

### P2. Expected test totals are inconsistent with the tests shown

The verified baseline is 183. The plan contains:

- Task 1: 10 tests -> 193, correct.
- Task 2: 8 tests -> 201, not 200.
- Task 3: 6 tests -> 207, not 214.
- Task 4: 5 tests -> 212, not 219.
- Task 9: one transcription test -> 213 if all prior shown tests exist.

The seven-test gap after Task 3 likely corresponds to required realized-grid cases that were described but never written.

**Required correction:** add the missing named tests or correct every total. Verify named coverage rather than relying on a count alone.

## Recommended Repair Order

1. Rewrite Task 3 around one 2048-point bit-grid API and repair all Python totals.
2. Implement the missing EEL magnitude/domain helpers, `@slider` invalidation, and completed `gc_trace` publication.
3. Reconcile relative gestures end to end and add the four Ratio declaration edits.
4. Complete the Task 8 event state machine and layout/readout code.
5. Replace the transcription parser with a real matrix-aware bits comparison.
6. Correct memory arithmetic, final review instructions, staging scope, and stale handoff text before dispatching workers.
