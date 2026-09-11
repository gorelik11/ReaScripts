# RCBitNova V1.3 HP/LP Range: Spec Weaknesses

**Reviewed:**

- `docs/superpowers/specs/2026-09-10-rcbitnova-v13-hplp-range-design.md` at `f385d5f`
- frozen implementation baseline `JSFX/RCBitNova V1.2` / tag `rcbitnova-v1.2`
- current gate, curve oracle, compile check, null harness, migrator, FakeReaper, and fixtures

## Summary

The central diagnosis is right: the declared 20 kHz ceiling, not the sample-rate clamp, prevents the
96 kHz -> 44.1 kHz workflow; widening the graph removes an implicit band-frequency clamp; and raw
normalised copying does not preserve values across a range change.

The spec is not yet safe to turn into a plan. It treats the visible axis as two formulas, but the
linear-phase curve has another producer/reader coordinate pair that would remain on 20 kHz. It also
describes a 176-record V1.2 -> V1.3 migration through a script that only migrates 95 records from
V1.0 to V1.1, and its fixture procedure neither preserves the existing frozen fixture nor covers
V1.2's 176th parameter.

| Priority | Count | Meaning |
|---|---:|---|
| P0 | 3 | Can ship a plausible wrong curve or silently change a migrated V1.2 instance |
| P1 | 3 | New fields, tool targeting, or live acceptance remain under-specified |
| P2 | 2 | Supporting claims contradict the measured parameter-order contract |

## P0 Findings

### P0.1: The linear-phase curve has a second 20 kHz coordinate system omitted from the design

Section 3.2 changes only `gc_x_of_f()` and `gc_f_of_x()`. Those functions place pixels and convert
pointer x back to frequency, but they do not define the stored realized-FIR grid.

V1.2 has two additional coupled sites:

- `gc_build_grid()` line 645 produces `GC_LIN_N` samples at
  `20 * pow(1000, t)`, ending at 20 kHz;
- `gc_hplp_bits()` line 1432 maps a requested frequency to that array with a 20 kHz clamp and
  `log(1000)`.

If only the visible axis changes to 24 kHz, the Min-phase curve follows it because it evaluates at
the requested frequency, while Linear/FIR reads a grid still built for 20 kHz. Changing only the
reader is also wrong: its 24 kHz index would point at a producer whose last sample is 20 kHz. The
result is exactly the dangerous kind already documented in this source: smooth, believable, and
wrong.

The Python oracle has the same old contract: `tools/rcbitnova_curve.py` declares
`FMAX = 20000.0`, and `realized_bits_grid()` uses it as its default upper bound. The spec's proposed
source gates do not mention either EEL2 grid site or the oracle.

**Required change:** define one graph-frequency contract, 20..24000, and apply it to all four EEL2
sites: axis producer/reader plus realized-grid producer/reader. Update the Python oracle and add
tests near 21.5, 22, 23.5, and 24 kHz that compare the reduced grid against a direct DTFT for both HP
and LP. Seed independent defects for an old grid producer and an old grid reader; changing both axis
helpers must not be enough to pass.

### P0.2: The named migrator does not implement the transition described by the spec

Section 4.1 says `tools/migrate_v10_to_v11.py` copies 176 declared records and that 174 can remain
normalised copies. The current script explicitly calls itself "the only supported migration," finds
one `RCBitNova V1.0`, creates `RCBitNova V1.1`, and copies exactly `N_DECLARED_V10 = 95` records.
It has no V1.2 source, V1.3 destination, 176-record path, or range metadata.

Retrofitting the new transition into that function without an explicit version contract risks
breaking the already-tested V1.0 -> V1.1 migration. It also leaves several necessary details
unstated: V1.2/V1.3 host-tail positions, FakeReaper's V1.3 shape, read-back in Hz for the two changed
records, and rollback/refusal coverage for the new source and destination names.

**Required change:** specify a separate `migrate_v12_to_v13.py`, or a deliberately versioned generic
migrator with source/destination manifests. Pin the changed declared indices to 85 and 89, copy all
176 declared records plus the host tail, convert those two through actual Hz, quantise to the 1 Hz
grid, and verify their actual read-back values before removing V1.2. Preserve the existing V1.0 ->
V1.1 path and its tests unchanged. Add the full failure/undo/refusal matrix for V1.2 -> V1.3.

### P0.3: Editing the existing frozen fixture destroys the baseline and still misses one parameter

Section 5 says "the frozen fixture is edited by NAME, two records." The only current fixture is
`tests/fixtures/v11_declared_175.json`. It is intentionally immutable evidence of V1.1 and is still
used to prove V1.2's first 175 records. Editing its HP/LP bounds would make it cease to describe V1.1
and would break that historical contract.

It is also one record too short for the transition being designed. V1.2 has 176 declared records;
record 175 is `slider246`, the persisted panel-card state. Comparing V1.3 only against the old
175-record fixture cannot prove that this final V1.2 parameter kept its name, range, step, default,
and position.

**Required change:** leave `v11_declared_175.json` untouched. Add a frozen
`v12_declared_176.json` captured from the tagged V1.2, then compare V1.3 against it with exactly two
allowed differences: `hi` for records 85 and 89. Keep the range-change table separate from the
baseline fixture; derive an expected V1.3 manifest in memory rather than rewriting historical
evidence. Seed a changed or missing panel-state record as a compatibility defect.

## P1 Findings

### P1.1: Special-casing only `gc_field_commit()` does not integrate ids 200/201 with the controller

The proposed fields reuse `gc_field_at` and ids 200/201, and the spec says only that
`gc_field_commit` branches before its band arithmetic. In V1.2, band arithmetic also exists in the
press/drag path:

- slot is `(gc_cap - 100) % 10`;
- drag step and sensitivity come from `gc_fmeta[slot*8]`;
- current-value comparison calls `gc_slot_slider(floor((gc_cap - 100) / 10), slot)`.

For ids 200/201 that produces band 10 and slots 0/1, reusing the Soft/Hard ceiling metadata and
reading beyond the eight-entry base tables. A commit-only branch can make typed entry work while
vertical drag remains inert or compares against an unrelated slider.

**Required change:** define one ID resolver used by capture, metadata lookup, current-value read,
drag, and commit. It must map 200/201 to the two HP/LP metadata rows and named writers without ever
entering `gc_slot_slider`. Alternatively declare these fields typing-only and keep them out of the
drag controller explicitly. Gate and live-test both ids through every supported gesture.

### P1.2: The version switch has more consumers than the proposed gate rows

Creating `JSFX/RCBitNova V1.3` requires retargeting or versioning several current consumers:

- `tools/rcbitnova_gates.py` hard-codes `V12`, reads it in `_fine_ceiling_indices`, and loads V1.2
  in `--live`;
- `tools/rcbitnova_compile.py` loads and deletes V1.2;
- `tools/rcbitnova_nulltest.py` still names V1.1/V1.2 and has version-specific diagnostics;
- `tests/_reaper_fx_fake.py` has no V1.3 count/name branch;
- source-gate tests open `gates.V12` directly.

The spec mentions new source rows and the null comparison, but does not give a version ownership
model or an authoritative consumer list. A plan can therefore pass unit tests against V1.2 while
never compiling or live-checking V1.3.

**Required change:** list every version consumer and decide which historical checks stay on V1.2
and which gain V1.3. The compile check and source/live gates must identify the loaded effect as V1.3,
while V1.2 remains the frozen comparison source.

### P1.3: The live analyser check can pass vacuously and has no measurable threshold

"Nothing survives above 22 kHz" proves nothing if the scratch project or source is 44.1 kHz: there
is no representable programme content above 22.05 kHz even with the filter bypassed. The stated job
is a 96 kHz session converted down, but the acceptance step does not pin 96 kHz, a broadband input,
filter phase/resolution, or an attenuation threshold. "Nothing" is also not a numeric result for a
finite windowed FIR.

**Required change:** run the live check in a 96 kHz project with known energy above 22 kHz, state
Linear + FIR Brick and the chosen resolution, and define a dBFS or relative-rejection threshold.
Prove the test fails with LP Off before requiring it to pass at 21.5 kHz. Exercise both new fields
and immediate writer application, not only one LP value.

## P2 Findings

### P2.1: Declared order does not follow slider number

Section 4.2 says sliders 132 and 136 fall inside the first 95 because "declared order follows slider
NUMBER." The measured project rule is the opposite: host indices follow textual declaration order.
V1.2 itself proves it by declaring B5's 191/231 records before B6's 161 block and by placing
`slider246` last. HP and LP frequencies are records 85 and 89 because of their textual positions,
not because 132 and 136 are numerically below some boundary.

**Required change:** state the measured indices 85 and 89 and derive them from the frozen manifest.
Do not explain them through slider-number ordering.

### P2.2: The 24 kHz maximum is not the effective maximum at every project rate

The declaration can hold 24 kHz, but the engine still uses `min(freq, srate * 0.49)`. Thus a 48 kHz
project applies at most 23.52 kHz and a 44.1 kHz project applies at most 21.609 kHz while the field
can display 24 kHz. This does not defeat the main 96 kHz conversion workflow, but phrases such as
"48 kHz Nyquist" and "the declared range is the limit, at every sample rate" can be read as an
effective-frequency guarantee.

**Required change:** distinguish requested/declared frequency from effective DSP frequency. State
that 24 kHz is reachable for the intended high-rate source session, while lower-rate projects retain
the existing 0.49 * sample-rate clamp.

## Recommended Revision Order

1. Define the four-site EEL2 graph-frequency contract and update the Python curve oracle.
2. Design an explicit V1.2 -> V1.3 migrator without changing the existing V1.0 -> V1.1 contract.
3. Add a frozen 176-record V1.2 fixture and express only the two permitted V1.3 differences.
4. Route ids 200/201 through every field-controller state, not only commit.
5. Enumerate version consumers and make the 96 kHz analyser test fail-before-pass and numeric.

The 24 kHz product decision itself is reasonable. The remaining work is making every hidden
coordinate system and every cross-version copy obey the same decision.
