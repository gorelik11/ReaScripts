# RCBitNova V1.3 HP/LP Range: Weaknesses Review (Fable, second pass)

**Reviewed:**

- `docs/superpowers/specs/2026-09-10-rcbitnova-v13-hplp-range-design.md`, revision 2
- `docs/superpowers/specs/2026-09-10-rcbitnova-v13-hplp-range-weaknesses.md`, revision 1
- `JSFX/RCBitNova V1.2` (frozen, tag `rcbitnova-v1.2`) and `JSFX/RCBitNova V1.1`
- `tools/rcbitnova_gates.py`, `tools/rcbitnova_curve.py`, `tools/rcbitnova_nulltest.py`,
  `tools/rcbitnova_compile.py`, `tools/rcbitnova_layout.py`, `tools/migrate_v10_to_v11.py`
- `tests/test_rcbitnova_dsp.py` (281 tests, run: pass), `tests/_reaper_fx_fake.py`,
  `tests/fixtures/v11_declared_175.json`
- `python3 -m pytest tests/test_rcbitnova_dsp.py -q` -> `281 passed`
- `python3 tools/rcbitnova_gates.py --source-only` -> `OK --source-only: 34 sites, 24 table
  entries, 20 writers, 37 addresses`

Everything asserted below was run or grepped against this checkout; line numbers are quoted from
the files as they stand now, and every table in this review was produced by a script shown inline
or described exactly, not recalled.

## The dispute: is declared order textual or numeric?

**Verdict: revision 2's section 8 is right. Revision 1's P2.1 is wrong, and its premise must not
reach a plan.**

Method: extract every `^slider(\d+):` declaration from `JSFX/RCBitNova V1.1` in two orders —
**textual** (the order the regex finds them in the file) and **numeric** (sorted by the slider
number) — and diff each against `tests/fixtures/v11_declared_175.json`, which is 175 `(index,
name, lo, hi, step, default)` records captured from a **live REAPER instance** (that is the whole
reason the fixture exists).

```
textual order matches fixture:  False  (68 mismatches out of 175)
numeric order matches fixture:  True   (0 mismatches out of 175)
```

First textual mismatch, at record 104:

```
record 104:  textual order would give   'B5 Dyn'
             numeric order gives        'B6 Enable'
             the fixture (measured) is  'B6 Enable'
```

This is the exact example revision 2 cites, and it reproduces exactly. Records 85 and 89 —
`HP Freq (Hz)` and `LP Freq (Hz)` — are declared at `JSFX/RCBitNova V1.1:125` and `:129`
respectively, and both orderings happen to agree there (the B1-B4 block is declared in numeric
order), which is why an argument from either rule reaches the same two indices for this feature.
That agreement is coincidental to where HP/LP sits in the file, not evidence for the textual rule
in general: the B5-B8 block *conclusively* falsifies it. Adopting the textual rule anywhere in this
project's tooling is what produced the historical bug this task references — a slider declared
last but numbered 143 landing at record 95 and displacing the entire B5-B8 block.

**A second, independent piece of evidence that the textual rule is live-dangerous today, not just
historical:** see P0.1 below — the codebase currently contains one helper that implements the
textual rule, and it is wrong for exactly the B5-B8 block, for exactly the reason revision 2's
disproof predicts.

## Summary

Revision 2 closes every finding revision 1 raised, with source-grounded receipts for each (I
re-verified the diagnostic claims independently — see the "Verified" note under each item below).
The 24 kHz decision itself is sound and the four-coordinate-system analysis, the ID-resolver
requirement, and the separate-migrator requirement all check out against the live source.

What is still missing is one level deeper than revision 1 looked: the **tooling that will carry
this spec into a plan has a live, reproducible defect in the exact area the spec is most worried
about** (declaration-order confusion), and the **test double that must prove the new migrator's one
dangerous mechanism (Hz conversion across a range change) cannot represent that mechanism at all**.
Both are demonstrated below with a script, not asserted from memory.

| Priority | Count | Meaning |
|---|---:|---|
| P0 | 2 | Can ship a plausible wrong result or silently corrupt a migrated instance |
| P1 | 1 | Under-specified in a way a plan would need to resolve by guessing |
| P2 | 2 | Minor supporting-claim / drafting issues, no behavioral risk |

## P0 Findings

### P0.1: `_fine_ceiling_indices()` — the helper revision 2's own fixture plan is modeled on — uses the textual rule revision 2 just proved wrong, and is silently wrong for the B5-B8 block today

`tools/rcbitnova_gates.py:441-450`:

```python
def _fine_ceiling_indices():
    text = open(V12, encoding="utf-8", errors="replace").read()
    order = [int(n) for n in re.findall(r"^slider(\d+):", text, re.M)]
    t = layout.base_tables(8)
    targets = {t["dynb"][b] + 3 for b in range(8)} | {t["ceb"][b] + 2 for b in range(8)}
    out = {order.index(n) for n in targets}
    ...
```

`order.index(n)` returns the slider's position in the **textual** declaration list. Running this
exact computation against the real `JSFX/RCBitNova V1.2` and comparing to the position derived by
sorting `order` numerically (which section 8's proof, and my own independent check above, both
establish is what REAPER actually reports) gives:

```
slider   name                              textual_idx   numeric_idx (= true REAPER index)
193      B5 Soft Ceiling Macro (bits<0)         106            133
203      B6 Soft Ceiling Macro (bits<0)         126            141
213      B7 Soft Ceiling Macro (bits<0)         146            149
223      B8 Soft Ceiling Macro (bits<0)         166            157
232      B5 Hard Ceiling Macro (bits<0)         113            164
236      B6 Hard Ceiling Macro (bits<0)         133            167
240      B7 Hard Ceiling Macro (bits<0)         153            170
```

Seven of the sixteen "fine ceiling" indices this function returns are wrong — every one of them in
the B5-B8 block, for precisely the reason section 8 gives: B5/B6/B7/B8 are **not** declared in
slider-number order in the source text (B5's 191-198 and 231-233 rows sit textually ahead of B6's
161-169 block; grep `JSFX/RCBitNova V1.2` lines 150-171 to see it).

**Why this has not caused a visible failure yet:** its one call site, `check_live` at
`tools/rcbitnova_gates.py:497-505`, only consults `fine_ceilings` while zipping `dec10` (V1.0's 95
declared records) against the corresponding prefix of `dec11` — i.e. only indices 0-94 are ever
checked against the exemption set. All seven wrong indices are >= 106, so the bug is currently
inert: nothing in the committed test suite calls `_fine_ceiling_indices()` at all (`grep -rn
_fine_ceiling_indices tests/` returns nothing), and `check_live` itself needs `--live` REAPER to
even run.

**Why this spec makes it live:** section 5.1 explicitly proposes modeling the new 176-record
fixture's exemption on this exact helper — *"the same shape as the existing `_fine_ceiling_indices`
exemption, which already permits sixteen ceiling records to differ in step alone."* The new
comparison spans the **full** 176-record range, not just the first 95 — that is the entire point of
adding `v12_declared_176.json`. A plan that follows this pointer literally (reuses
`_fine_ceiling_indices()`, or reimplements its `order.index()` method for the new exemption set)
inherits seven wrong indices for the first time somewhere that will actually be exercised.

Separately, and worth fixing regardless of this spec: this is a *currently shipped, currently
untested* defect. It happens to matter to no live check today only by accident of which records
`check_live` walks.

**Verified:** ran the exact `_fine_ceiling_indices()` body against the live `V12` constant, plus a
`sorted(order).index(n)` variant, plus a from-scratch cross-check against
`tests/fixtures/v11_declared_175.json` by name lookup. All three agree: the true index is the
sorted (= REAPER-measured) one, and `_fine_ceiling_indices()` disagrees with it on 7 of 16.

**Required change:** before or alongside this spec's fixture work, fix `_fine_ceiling_indices()` to
compute indices from **sorted** slider order (or, better, from the same live-measured record list
`check_live` already builds, so there is one source of truth instead of two competing
computations). Do not let the new V1.2 -> V1.3 fixture-diff exemption set reuse the current
`order.index()` method even "in shape" — copy the corrected computation, not the buggy one. Add a
regression test that pins all sixteen fine-ceiling indices against the frozen fixture by name, so
this class of defect cannot go untested again.

### P0.2: The migrator's one dangerous mechanism — Hz conversion across a range change — cannot be exercised against the test double the project's own testing discipline requires

Section 4.1 correctly specifies that `migrate_v12_to_v13.py` must convert records 85 and 89
"through Hz... read the source's actual value, quantise to the 1 Hz declared step, write the
destination's normalised equivalent." This is the one operation in the whole feature that can
silently corrupt a value (worked example already in section 4, 12000 Hz -> 14398.4 Hz).

`tests/_reaper_fx_fake.py:23-27` is the entire parameter model the offline test suite has to drive
this logic against:

```python
class FakeParam:
    def __init__(self, name, value=0.0, envelope=None):
        self.name = name
        self.normalized = value
        self.envelope = envelope
```

`FakeParam` has no `lo`, `hi`, or `step`, and no notion of an actual (non-normalized) value at all
— `.normalized` is a bare stored float with no scale behind it. `migrate_v10_to_v11.py` never
needed more than this because V1.0 -> V1.1 is a pure normalized-value copy with no range change (no
`.range` lookup anywhere in that file). The real `reapy.FXParam` (`reapy/core/fx/fx_param.py`,
installed at `/Users/macbook/Library/Python/3.11/lib/python/site-packages/reapy/`) *is* a `float`
subclass carrying the actual value, with a `.range` property backed by `TrackFX_GetParam`'s
`lo, hi` outputs and a `.normalized` computed from it — so the real host object can do exactly what
section 4.1 asks. The fake cannot represent any of it.

Concretely: any offline unit test for `migrate_v12_to_v13.py`'s Hz-conversion branch — reading
record 85's actual Hz value, quantising it, computing the destination's normalized equivalent for
`<20,24000,1>` — has nothing to assert against, because `FakeParam` cannot hold a range or an
actual value in the first place. The only place this logic could be exercised at all is live
REAPER. That directly contradicts this project's own established discipline (the FakeReaper harness
exists specifically so that ReaScript/Python glue is proven **before** live, and the currently
frozen 13-test V1.0 -> V1.1 migration suite is built entirely on this same fake), and it contradicts
revision 2's own instruction in the same section: *"Read back and verify those two values in Hz
before the V1.2 instance is removed"* — read-back verification is exactly the kind of assertion that
needs a fake capable of holding a real value and a real range to test offline.

Section 4.1's bullet list of what the fake needs only says *"`tests/_reaper_fx_fake.py` gains a
V1.3 branch; it currently knows only V1.0/V1.1/V1.2 counts"* — true, and verified
(`tests/_reaper_fx_fake.py:77`: `n = N_DECLARED_V12 if "V1.2" in name else N_DECLARED_V11 if
"V1.1" in name else N_DECLARED_V10`), but that only adds a fourth declared-count branch. It does
not add range/step/actual-value modeling, without which the count branch is the least of what the
fake is missing for this feature.

**Verified:** read `tests/_reaper_fx_fake.py` in full (105 lines); confirmed `FakeParam` has no
range or actual-value concept anywhere in the file. Read the installed `reapy.FXParam` source and
confirmed it *does* carry both, via `.range` (backed by `GetParam`'s last two return values) and
its own float value. Confirmed by grep that `migrate_v10_to_v11.py` never calls `.range` or reads
an actual (non-normalized) value anywhere — consistent with it never needing to.

**Required change:** extend `FakeParam`/`FakeFX` with a declared `(lo, hi, step)` per parameter (at
minimum for records 85 and 89) and an actual-value accessor, so `migrate_v12_to_v13.py`'s Hz
conversion and its read-back verification can be driven and asserted offline, the same way the
existing 13 V1.0 -> V1.1 tests drive normalized copying offline today. Do this before writing the
new migrator, not after — the new migrator's tests are what will need it.

## P1 Findings

### P1.1: The null harness's fix ("write and compare by value, not by normalised number") has no concrete mechanism, and the existing plumbing only half-supports it

Section 4.3 states the cure in prose: *"The null harness writes the version under test BY VALUE
rather than by raw normalised, and its post-write assertion compares read-back VALUES, not
normalised numbers."* `tools/rcbitnova_nulltest.py`'s `render()` (lines ~168-193) already has two
write modes: `values={name: value}` (converts through `TrackFX_GetParam`'s live `lo, hi` before
calling `SetParamNormalized` — this is genuinely value-based) and `norms=[...]` (a raw pass-through
of normalized floats — this is the flawed path section 4 diagnoses). The fix direction is right,
but going from "the CASES dict already uses named values for a handful of parameters" to "copy the
**other instance's actual state**, all 176 records, by value" is not the same code path: it needs
reading back all 176 actual values from the BASE render (by index, not by a hand-authored name
dict) and replaying them into `UNDER_TEST` through its own range — a generalization the spec never
states explicitly, only implies. This is not wrong, just under-specified enough that two
implementers could reasonably build incompatible versions of it (e.g. one that still enumerates
only the CASES-dict names, silently leaving the other ~170 records copied by raw normalized number
as before, which would defeat the fix's own stated purpose).

**Verified:** read `tools/rcbitnova_nulltest.py` end to end; confirmed `render()`'s current
`values=` path already resolves a name to `lo, hi = r[4], r[5]` from the **destination**
instance's live range before writing — the right primitive — and confirmed the current `norms=`
call sites (`b, norms11 = render(UNDER_TEST, norms=norms10)`) are exactly the flawed raw-copy path
sections 4.2-4.3 describe.

**Required change:** state explicitly that the fix means reading back **all** N declared actual
values from the BASE render (not just the CASES-dict subset) and replaying all of them into
`UNDER_TEST` by value, and that `got = [...GetParamNormalized... for k in range(95)]` becomes
`range(N_DECLARED_V12)` (176) so the post-write equality check actually spans every record the
migration path also touches, not just the historical 95.

## P2 Findings

### P2.1: Section 3.2's four-site claim is complete and correctly scoped — verified, not a weakness, recorded so a plan does not re-litigate it

Grepped every occurrence of `20000`, `pow(1000`, and `log(1000)` in `JSFX/RCBitNova V1.2`. Beyond
the four cited sites (`gc_build_grid` line 645, `gc_x_of_f`/`gc_f_of_x` at 1394-1395,
`gc_hplp_bits` at 1432), the only other `20000` occurrences are: the eight band-frequency slider
declarations (correctly excluded — section 2 keeps bands at `<20,20000,1>`), one `gfx_measurestr`
label-width probe at line 2575 (both "20000 Hz" and "24000 Hz" are five digits, so no behavior
change needed), and the band-panel typed-frequency clamp at line 2811 (`gc_w_freq` for the
currently-selected **band**, correctly excluded for the same reason as the declarations). No fifth
coordinate site exists. No required change; recorded so a future reviewer does not need to redo
this grep.

### P2.2: `gc_w_freq(b, v, qz)` in section 3.3 is the band writer, not a new function — worth stating plainly since the name is reused

Section 3.3's clamp requirement ("`gc_w_freq` clamps to 20..20000 itself") refers to the
**existing** band-frequency writer at `JSFX/RCBitNova V1.2:1086-1097`, called from the band-node
drag at line 2412 (`gc_w_freq(gc_drag, gc_v, 1)`, `gc_drag` being a band index 0-7) — a different
function from the two **new** single-argument writers `gc_w_hpfreq(v)`/`gc_w_lpfreq(v)` proposed in
section 3.4 for the HP/LP handle. The spec is internally correct (bands keep `<20,20000,1>`, so
their writer needs the new clamp once the shared axis reads up to 24000; HP/LP's own declared range
widens in lockstep with the axis, so the direct write at lines 2562-2563 needs none), but a reader
skimming section 3.3 in isolation could mistake `gc_w_freq` for one of the new HP/LP writers named
two paragraphs later. No required change beyond naming this explicitly in the plan so an
implementer does not go looking for a `gc_w_freq` clamp inside the wrong function.

## Recommended Revision Order

1. Fix `_fine_ceiling_indices()` to use numeric (measured) slider order, and pin all sixteen
   indices with a name-based regression test, before building the new 176-record fixture's
   exemption set on top of it (P0.1).
2. Extend `FakeParam`/`FakeFX` with declared range/step and an actual-value accessor for at least
   records 85 and 89, before writing `migrate_v12_to_v13.py`'s Hz-conversion path and its offline
   tests (P0.2).
3. Spell out the null-harness fix as "read back and replay all `N_DECLARED_V12` actual values,
   not the CASES-dict subset, and widen the post-write equality check to the same range" (P1.1).
4. Carry the rest of revision 2 forward as written — the four-site coordinate contract, the
   separate migrator, the new 176-record fixture, the ID resolver, and the version-consumer list
   all check out against the live source with no changes needed (P2.1, P2.2).

The dispute in section 8 is settled: measured REAPER order is slider-number order, not textual
order, with zero exceptions across all 175 frozen V1.1 records. The one place in this codebase that
currently assumes otherwise (`_fine_ceiling_indices()`) is dormant only by accident, and this
feature is what would wake it up.
