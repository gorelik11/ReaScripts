# RCBitNova V1.3 HP/LP Range Plan: Weaknesses Review

**Reviewed:**

- `docs/superpowers/plans/2026-09-12-rcbitnova-v13-hplp-range.md` at `71770af`
- `docs/superpowers/specs/2026-09-10-rcbitnova-v13-hplp-range-design.md`, revision 3
- both earlier spec weaknesses reviews and the revision-3 dispositions
- frozen implementation baseline `JSFX/RCBitNova V1.2`
- the current curve oracle, FakeReaper, null harness, gates, and V1.0 -> V1.1 migrator
- `python3 -m pytest tests/test_rcbitnova_dsp.py -q` -> `282 passed`

## Summary

The plan carries the spec's important corrections forward: all four graph-coordinate sites are
named, the band writer retains its own 20 kHz clamp, the V1.2 fixture is new rather than rewritten,
the two filter fields use an ID resolver, and migration/null copying is defined in actual values.

It is not executable safely as written. The two new metadata rows read `GC_FMIN` and `GC_FMAX`
before those globals are assigned, so both fields initialise with a `0..0` range. The migration
then has two independent live-path defects: it asks real `reapy.FXParam` objects for attributes
they do not expose, and its read-back refusal returns from the protected block without removing the
new V1.3 instance. Several proposed tests also cannot run or cannot create the defect they claim to
seed, so the plan's stated green checkpoints are unreachable without improvisation.

| Priority | Count | Meaning |
|---|---:|---|
| P0 | 3 | Produces broken fields, a non-working live migration, or an orphaned FX on refusal |
| P1 | 5 | Test/API mismatch or workflow gap forces the implementer to invent missing behavior |
| P2 | 1 | The written red/green checkpoint reports the opposite of what its command can prove |

## P0 Findings

### P0.1: Task 6 stores `0..0` in both frequency metadata rows because the graph constants are assigned later in `@init`

Task 4 Step 3 says to put the assignments immediately above `gc_x_of_f`
(`plan:376-390`). In V1.2 that insertion point is around source line 1394. Task 6 Step 2 puts the new
metadata rows beside the existing `gc_fmeta` rows near source line 315 and writes:

```eel2
gc_fmeta[50]=GC_FMIN; gc_fmeta[51]=GC_FMAX;
gc_fmeta[58]=GC_FMIN; gc_fmeta[59]=GC_FMAX;
```

These are ordinary EEL2 assignments in one sequential `@init` section, not declarations evaluated
out of order. When lines 315-327 execute, `GC_FMIN` and `GC_FMAX` have not reached their later
assignments and therefore read as zero. The field controller subsequently clamps every typed value
to `0..0`; the range table in memory stays wrong even after the globals themselves become 20 and
24000.

**Required change:** assign `GC_FMIN`, `GC_FMAX`, `GC_FSPAN`, and `GC_FLOG` before the `gc_fmeta`
initialisation. The four graph functions may remain where they are. Add a source/order gate or a
small extracted-metadata test proving rows 6 and 7 contain `(20, 24000, 1)`, rather than checking
only the Python memory interval.

### P0.2: Task 7's destination-range API exists only on the fake, not on real `reapy.FXParam`

The proposed migrator reads (`plan:915-918`):

```python
lo, hi = dst.params[i].lo, dst.params[i].hi
```

Task 3 adds exactly those convenience attributes to `FakeParam`, so the offline path can accept the
code. The installed real `reapy.FXParam` exposes the declared pair as `.range`; it has no `.lo` or
`.hi`. On the first changed record the live migrator raises `AttributeError`, rolls back, and can
never migrate any V1.2 instance.

This is precisely the kind of fake/host divergence the fake is meant to prevent: the fake's nicer
API masks invalid production code.

**Required change:** obtain the destination range through the same injected RPR boundary already
used by `_hz` (`TrackFX_GetParam(...)[4:6]`), or use `dst.params[i].range` consistently in both fake
and live models. Add a host-contract test whose fake exposes only the real interface; do not let the
migrator depend on fake-only fields.

### P0.3: A failed frequency read-back returns from `try` and leaves the new V1.3 instance in the chain

The inherited migrator cleans up `dst_guid` only in `except` (`migrate_v10_to_v11.py:153-163`). The
new read-back branch instead returns directly (`plan:920-925`):

```python
if abs(back - hz) > 0.5:
    return "REFUSED, source untouched: ..."
```

`finally` will balance the undo block, but it does not delete the new destination. The function can
therefore report "source untouched" while leaving the chain as `A, V1.2, B, V1.3`. This violates
both the spec and the plan's own test at lines 883-885.

**Required change:** raise an exception on read-back failure so the inherited GUID-based cleanup
runs, or factor one explicit rollback function used by every post-add refusal. Test the final chain,
the destination GUID's absence, and exactly one balanced undo close.

## P1 Findings

### P1.1: Task 3 does not provide the FakeRPR API that Task 7 calls, and the one method it does provide has the wrong `_fx` call

The current `FakeRPR._fx` signature is `_fx(self, idx)`. Task 3 proposes:

```python
p = self._fx(track_id, fx_index).params[i]
```

which raises `TypeError`. Task 7 additionally calls `rpr.TrackFX_SetParamNormalized(...)`, but no
such fake method exists now and Task 3 never adds one. The Task 3 test exercises only
`FakeParam.value`, so it cannot catch either missing host operation; the Task 7 tests cannot reach
the migration assertion with the plan's snippets.

**Required change:** make `TrackFX_GetParam` call `self._fx(fx_index)`, and either implement
`TrackFX_SetParamNormalized` with the real four ReaScript arguments (plus `self`) or write through
`dst.params[i].normalized` as the old migrator does. Add a direct return-shape/write test before
Task 7.

### P1.2: The read-back sabotage is self-consistent and therefore does not cause a read-back failure

The test changes the destination's `hi` from 24000 to 20000 (`plan:870-885`). The implementation
then reads that same `hi`, calculates the normalised value with it, and reads the actual value back
through it:

```text
n = (12000 - 20) / (20000 - 20)
back = 20 + n * (20000 - 20) = 12000
```

The destination is not "lying" from the migrator's point of view; its write and read contracts
agree. The function migrates successfully, so the test does not exercise rollback or the direct
return defect in P0.3.

Only LP record 89 is tested for preservation as well. A swapped/wrong HP index can escape while the
generic non-range test deliberately excludes both 85 and 89.

**Required change:** sabotage the write or the read-back independently (for example, make the fake
ignore/perturb a write to the destination's record 89), then parameterise preservation over records
85 and 89. Include values near both bounds so clamping and 1 Hz quantisation are covered.

### P1.3: The proposed DTFT tests do not match any current oracle API

Task 4's test body (`plan:447-463`) calls `curve.brick_kernel` and `curve.dtft_bits`; neither exists.
The kernel builder is `dsp.fir_brick_kernel(BD, ftype, freq, beta, sr)`, while `_dtft_bits` is a
test-local helper with argument order `(kernel, sr, frequency)`. More importantly,
`curve.realized_bits_grid()` returns one list of `(frequency, bits)` pairs, not the two arrays that
the plan unpacks as `freqs, bits`.

The note to "use the existing names" acknowledges part of this but does not resolve the different
module, required `BD`/`beta`, argument order, or return shape. The shown test fails before making an
assertion.

**Required change:** give the exact test against today's APIs, e.g. build with
`dsp.fir_brick_kernel`, keep `grid = curve.realized_bits_grid(...)`, select a `(freq, bits)` pair,
and compare it with the existing `_dtft_bits(kernel, sr, freq)`. Pin the chosen `BD`, beta, and error
tolerance so the implementer does not invent a different oracle case.

### P1.4: A frequency field moves by one hertz per 12 logical pixels, making its required drag gesture unusable

Rows 6 and 7 specify `step=1` and `drag_units=12` (`plan:676-681`). The existing controller changes
one `step` per `drag_units`, so moving LP from its 20 kHz default to 21.5 kHz takes 18,000 logical
pixels. Moving HP from 20 Hz to 21.5 kHz takes 257,760. Task 9 nevertheless requires both fields to
be exercised by dragging, and the spec introduced numeric fields because the high-frequency axis
itself is too coarse.

This can prove that a one-hertz nudge calls the writer, but it does not produce a usable frequency
control.

**Required change:** separate storage/typing quantisation (1 Hz) from drag increment (for example
100 Hz coarse plus a fine modifier), or use a logarithmic/accelerated drag. Add a bounded gesture
test that reaches a musically relevant change within an ordinary window height.

### P1.5: The plan knowingly disables its main no-DSP-regression oracle for three task commits even though the fix has no dependency on the range change

Task 5 changes the declarations and explicitly postpones the null harness until Task 8
(`plan:626-629`, `1126-1128`). Tasks 5, 6, and 7 are therefore committed while the headline
constraint, "same Hz, zero tolerance", cannot be checked meaningfully.

Task 8's value-copy mechanism needs the V1.3 copy and the range-capable fake, but not widened
declarations; it works when both versions still have equal ranges. There is no technical reason for
the red window.

**Required change:** run Task 8 immediately after Tasks 2 and 3, before changing either declaration.
Then every later commit retains a meaningful six-case null result. If the ordering remains, squash
Tasks 5-8 into one non-checkpoint rather than presenting knowingly unverifiable commits as safe
milestones.

## P2 Finding

### P2.1: Task 5's stated failing test is already green before the declarations change

Task 5 Steps 1-2 add `RANGE_CHANGES`, `expected_v13_manifest()`, and two tests that compare the
derived fixture with V1.2. Step 3 then runs only:

```bash
python3 -m pytest tests/test_rcbitnova_dsp.py -q -k v13_manifest
```

Neither test reads the V1.3 declarations. Once Step 1 is implemented, both pass while V1.3 still
says 20000. The plan itself notes that only `--live` would fail, but that command is absent from the
red step.

**Required change:** either call a source manifest parser in the offline test and compare it to
`expected_v13_manifest()`, or run the live gate as the declared red check. Record the expected
failing assertion, not a non-zero result from a command whose selected tests are green.

## Recommended Revision Order

1. Move the graph-frequency assignments ahead of `gc_fmeta`, and add an order/value gate (P0.1).
2. Correct the fake host methods and pin their real signatures (P1.1).
3. Move the value-based null harness before the declaration change (P1.5).
4. Rewrite Task 7 around one real range API and one exception-driven rollback path (P0.2, P0.3).
5. Replace the self-consistent sabotage and cover both changed records (P1.2).
6. Make the oracle snippets executable against the current API (P1.3).
7. Decide a usable drag law independently of the 1 Hz storage step (P1.4).
8. Repair Task 5's red checkpoint, then retain the remaining source/live gates as written (P2.1).
