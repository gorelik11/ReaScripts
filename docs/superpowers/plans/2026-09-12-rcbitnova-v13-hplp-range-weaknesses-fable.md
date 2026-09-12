# RCBitNova V1.3 HP/LP Range Plan: Fable Weaknesses Review

**Reviewed:**

- `docs/superpowers/plans/2026-09-12-rcbitnova-v13-hplp-range.md`
- `docs/superpowers/plans/2026-09-12-rcbitnova-v13-hplp-range-weaknesses.md` (round two, all nine
  findings accepted per the task brief and treated as already fixed)
- `docs/superpowers/specs/2026-09-10-rcbitnova-v13-hplp-range-design.md`, revision 3
- `JSFX/RCBitNova V1.2` (source of truth for every EEL2 claim)
- `tools/rcbitnova_gates.py`, `tools/rcbitnova_curve.py`, `tools/rcbitnova_layout.py`,
  `tools/rcbitnova_nulltest.py`, `tools/rcbitnova_compile.py`, `tools/migrate_v10_to_v11.py`,
  `tests/_reaper_fx_fake.py`, `tests/test_rcbitnova_dsp.py`

This review looks only for defects the round-two review did not already find. Everything it
accepted is assumed fixed and not re-litigated here.

## Summary

The plan's biggest remaining problem is in its own tooling, not in the EEL2 it proposes to write.
`tools/rcbitnova_gates.py`'s `_function_body()` helper — reused, unmodified, by Task 4's new
`check_graph_frequency` — mis-extracts the body of any function declared with a `local(...)`
clause: it returns the `local()` argument list instead of the function body. Two of the plan's four
"graph-frequency contract" sites, `gc_build_grid` and `gc_hplp_bits`, are declared with exactly
that clause. This is not hypothetical: run against the live V1.2 source, `_function_body` returns
`(ob, BD, desbuf, ktime, half, i, k, b, frac, dst, f, t, m0, m1, m, idx)` for `gc_build_grid` and
`(nsec, base, k, acc, sl, idx, src, t, i, f0, f1, b0, b1)` for `gc_hplp_bits` — the local-variable
lists, not one line of the actual bodies. The new gate's own literal-absence check and its
"references GC_F" check both run against the wrong text for exactly the two functions the spec
calls the most dangerous ("the realized linear-phase GRID's producer and reader"). This is a
pre-existing latent bug that today's 282 passing tests never wake, because every current caller of
`_function_body` (`check_writers`, on the eight band writers) happens to name functions with no
`local(...)` clause.

Beyond that, there are real API/return-shape and gate-row problems inside Task 4, 6, and 7's own
new code, independent of anything the round-two review already flagged.

| Priority | Count | Meaning |
|---|---:|---|
| P0 | 2 | The plan as written produces a broken build, a wrong curve, or a corrupted migration |
| P1 | 3 | Forces the implementer to invent missing behaviour |
| P2 | 2 | Supporting claims wrong / gate rows that cannot fire |

## P0 Findings

### P0.4: `_function_body` returns the `local(...)` argument list, not the body, for two of the four graph-frequency sites — Task 4's own gate cannot pass

Verified by running it directly against the live source:

```
_function_body(text, "gc_build_grid") -> "(ob, BD, desbuf, ktime, half, i, k, b, frac, dst, f, t, m0, m1, m, idx)"
_function_body(text, "gc_hplp_bits")  -> "(nsec, base, k, acc, sl, idx, src, t, i, f0, f1, b0, b1)"
```

`_function_body` (`tools/rcbitnova_gates.py:279-303`) finds the end of the parameter list, then
does `body_open = text.find("(", i)` to locate the body's opening paren. For a function declared
`function name(args) local(...) (`, the very next `(` after the parameter list is `local(`'s own
paren, not the body's. The helper then balances THAT paren group and returns it. Every WRITERS
function that already uses this helper (`gc_w_freq`, `gc_w_dyn`, etc.) happens to have no
`local(...)` clause, so the bug has never fired in the 282 currently-passing tests — the same shape
of dormancy as the `_fine_ceiling_indices` bug the spec documents in §5.1.

Task 4's `check_graph_frequency` (`plan:340-365`) calls `_function_body` on all four
`GRAPH_F_SITES`, including `gc_build_grid` and `gc_hplp_bits`, both of which are declared with
`local(...)` (source lines 633-634 and 1415). Consequences, checked against the actual assertions:

- The forbidden-literal loop (`for bad in ("20000","24000","1000"): assert bad not in body`) runs
  against the local-variable list for these two functions. It will pass **regardless of what the
  real function body contains** — including the exact seeded defects Task 4 Step 8 proposes
  ("gc_build_grid still carries the literal 1000", "gc_hplp_bits still carries the literal 20000").
  Both seeded mutants would go undetected by this check for the wrong reason: not because the fix
  is correct, but because the check never looked at the mutated line.
- `assert "GC_F" in body` fails unconditionally for both functions, because a local-variable list
  never contains the substring `GC_F`. This means `check_graph_frequency` cannot pass even after
  the CORRECT fix from Task 4 Step 4 is applied. The task's own Step 2 ("run to verify it fails")
  will indeed fail before the fix, but Step 9's later `--source-only` run will keep failing after
  the fix too, with the misleading message `"gc_build_grid: does not read the frequency contract"`
  — on source that does, in fact, reference `GC_FMIN`/`GC_FSPAN` correctly.
- Task 9 Step 1 ("confirm every seeded defect is rejected for ITS OWN reason") cannot pass either:
  the two seeded defects targeting these functions would fail on the wrong assertion message
  (`"does not read the frequency contract"` instead of `"still carries the literal 1000"` /
  `"...20000"`), and the clean, correctly-fixed source fails on that same message too — so mutant
  and clean source are indistinguishable to this gate.

**Required change:** fix `_function_body` to skip a `local(...)` clause before locating the real
body — e.g. after the parameter list closes, if the next non-whitespace token is the literal word
`local`, skip its own balanced-paren group before taking `body_open` as the following `(`. Add a
direct unit test asserting `_function_body(text, "gc_build_grid")` contains `"GC_FMIN"` and does
not equal the local-variable tuple, before Task 4 relies on it. This must be fixed before Task 4 is
attempted, since `check_writers` already depends on the same helper and any fix must not change its
behavior for the eight existing writers (verified above they have no `local(...)` clause, so a
correct fix is backward compatible).

### P0.5: `check_filter_writers`'s `gc_field_commit` check is compounded-vacuous by the same bug, and was already unfalsifiable before it

`check_filter_writers` (`plan:784-798`) includes:

```python
for fn in ("gc_field_commit",):
    body = _function_body(text, fn)
    assert "gc_slot_slider" not in body, ...
```

Two independent problems, verified against the actual and proposed source:

1. `gc_field_commit`'s **current** V1.2 body (`slot = (id - 100) % 10; ... gc_w_softceil(b, v); ...`)
   never calls `gc_slot_slider` — that call lives only in the `@gfx` drag block
   (`JSFX/RCBitNova V1.2:2767`), never inside `gc_field_commit` itself. The plan's own rewritten
   `gc_field_commit` (Task 6 Step 5) also never calls it. So this assertion is true both before and
   after every change the plan proposes to this function; no plan-defined mutation flips it. This
   is exactly the class of "gate row that can never fire" the earlier round singled out for
   `_fine_ceiling_indices`.
2. Because the plan's rewritten `gc_field_commit` is declared `function gc_field_commit(id, v)
   local(b, r, w, lo, hi, st) (`, `_function_body` (P0.4) would return the local-argument tuple
   `(b, r, w, lo, hi, st)` for it anyway — so even if the assertion were meaningful, it would be
   checking the wrong text a second time over.

**Required change:** either drop this assertion (it protects nothing) or replace it with a check
that can actually fail — for example, assert the real regression the design worries about: that
`gc_field_row`/`gc_field_band` compute IDs 200/201 to a row **not** reachable through
`gc_slot_slider`'s `(band, slot)` addressing at all (i.e. test the resolver's arithmetic directly,
as Task 6's seeded defect for the DRAG block already does), rather than grepping a function that
never called the forbidden name in either version.

## P1 Findings

### P1.6: Task 4's DTFT/grid test signature error is more specific than the round-two review recorded, and remains wrong even after "use the existing names"

The round-two review (P1.3) already flagged that `curve.brick_kernel`/`curve.dtft_bits` do not
exist and that `realized_bits_grid` returns pairs, not two arrays, and told the implementer to "use
the existing names." Reading the actual oracle confirms the fix is not a drop-in rename:

```
$ grep -n "^def \|^FMIN\|^FMAX" tools/rcbitnova_curve.py
FMIN, FMAX = 20.0, 20000.0
def f_to_x(f): ...
def x_to_f(x): ...
def realized_bits_grid(kernel, sr, n=257): ...
```

`realized_bits_grid` takes a pre-built `kernel` and `sr` and returns `[(f, bits), ...]` pairs; it
has no notion of `kind`/`freq`/`beta` on its own — those belong to `dsp.fir_brick_kernel(BD, ftype,
freq, beta, sr)` in a **different module** (`tools/rcbitnova_dsp.py`), which the test in
`plan:453` never imports. The plan's proposed body:

```python
kernel = curve.brick_kernel(kind, 21500.0, sr)
freqs, bits = curve.realized_bits_grid(kernel, sr)
```

still calls a function that doesn't exist (in either module — `curve.brick_kernel` is nowhere) and
still unpacks a list of pairs into two parallel arrays, which raises `ValueError: too many values to
unpack` on the very first pair even if the kernel builder were fixed. "Use the existing names" is
not enough guidance to produce a runnable test — the implementer must additionally know to import
`dsp`, know `fir_brick_kernel`'s four positional arguments (`BD`, `ftype`, `freq`, `beta`), and
rewrite the unpacking as a loop over `(f, bits)` tuples plus a **separate** `_dtft_bits(kernel, sr,
f)` call, which is test-local (defined inside `tests/test_rcbitnova_dsp.py`, not `curve`) per the
round-two review.

**Required change:** the plan should give the literal, executable test body, not a paraphrase of
API names to substitute — e.g.:

```python
from tools import rcbitnova_dsp as dsp
BD = <pin a concrete value already used by an existing HP/LP kernel test>
kernel = dsp.fir_brick_kernel(BD, "lp", 21500.0, <beta>, sr)
grid = curve.realized_bits_grid(kernel, sr)
f, bits = min(grid, key=lambda p: abs(p[0] - target))
direct = _dtft_bits(kernel, sr, f)
assert abs(bits - direct) < 0.05
```
with `BD` and `beta` pinned to values an existing passing test already uses, so the implementer is
not left choosing a kernel size that changes the oracle's tolerance.

### P1.7: `GC_FMETA` row 6/7 metadata literals (`GC_FMIN`, `GC_FMAX`) are EEL2 identifiers, not the Python constant the gate compares against — the two are two different numbers until Task 4 lands first

Task 6 Step 2 writes the metadata rows as:

```eel2
gc_fmeta[50]=GC_FMIN; gc_fmeta[51]=GC_FMAX;
gc_fmeta[58]=GC_FMIN; gc_fmeta[59]=GC_FMAX;
```

This is fine IF Task 4 (which declares `GC_FMIN`/`GC_FMAX` and — once P0.1 from the round-two
review is applied — assigns them ahead of `gc_fmeta`'s own initialisation) has already landed and
the assignment order is fixed. But the plan's task order is: Task 4 (graph contract) happens
BEFORE Task 6 (the two writers and metadata rows) — plan section order Task 4 then Task 6 — so by
the time Task 6 Step 2 is written, `GC_FMIN`/`GC_FMAX` do exist. That part is fine, and P0.1
(already accepted) already tells the implementer to reorder the `@init` assignments. The remaining
gap: `test_panel_metadata_grew_by_two_rows_and_still_clears_mb_band` (`plan:664-669`) checks only
`lay.GC_FMETA`, `lay.NB_LIST`, `lay.MB_BAND` — Python-side layout constants — and never reads back
the actual EEL2-evaluated values at `gc_fmeta[50]`/`[51]`/`[58]`/`[59]`, i.e. it cannot fail even if
P0.1's ordering fix is skipped and both rows end up holding `0`. The round-two review's own
required change ("Add a source/order gate or a small extracted-metadata test proving rows 6 and 7
contain `(20, 24000, 1)`") is stated as a requirement in the earlier review but is not present
anywhere in this plan's actual tasks — Task 4 doesn't add it, and Task 6 doesn't either. It is a
requirement from the round-two review that the plan text has not actually incorporated.

**Required change:** add the extracted-metadata test the round-two review called for — e.g. run
`eval_init`-style evaluation (or a small `@init`-order source check) asserting
`gc_fmeta[50..51]==(20,24000)` and `gc_fmeta[58..59]==(20,24000)` textually AFTER `GC_FMIN`/
`GC_FMAX`'s own assignment line in the source, not merely that the Python layout constants have the
right shape.

## P2 Findings

### P2.2: The seeded defect for `gc_build_grid` in Task 4 Step 8 replaces a string that will already have been touched by Task 4 Step 4's own rewrite — verify the target text is the POST-rewrite line, not V1.2's original

Task 4 Step 8's first seed:

```python
(lambda t: t.replace("    f = min(GC_FMIN * pow(GC_FSPAN, t), srate * 0.5);",
                     "    f = min(20 * pow(1000, t), srate * 0.5);"),
 "gc_build_grid still carries the literal 1000"),
```

replaces the string Step 4 is supposed to have already written (`f = min(GC_FMIN * pow(GC_FSPAN,
t), srate * 0.5);`), confirmed to match Step 4's own snippet verbatim, and confirmed absent from
V1.2's original (`f = min(20 * pow(1000, t), srate * 0.5);`, source line 645) — so the ordering is
correct only if Step 8 runs strictly after Step 4's edit lands in the working file, which the task
list implies but does not state as a precondition the way Task 5 explicitly warns about ordering
elsewhere. This is not a defect once P0.4 is fixed (the literal check would then correctly see this
string), but note it explicitly depends on P0.4's fix landing first, or this seed's target
assertion message ("still carries the literal 1000") is unreachable for the reasons in P0.4.

### P2.3: `check_writers`'s `topo_pdc` guard and `slider_automate` count assertions do not apply to, and are not asked to apply to, the two new filter writers — but the plan's phrase "cannot cover them" undersells a related gap: `gc_apply_hplp` is never gated as a required rebuild call anywhere outside `FILTER_WRITERS`

This is a minor completeness note, not a defect: `FILTER_WRITERS` (`plan:780-798`) checks
`rebuild in body` for `gc_apply_hplp(0)`/`gc_apply_hplp(1)` textually, which is fine and does fire
correctly (verified: `gc_apply_hplp` exists at source line 1362 with the expected `hp_fe = min(...,
srate * 0.49)` shape the writers must trigger). No change required; recorded so the reviewer does
not have to re-check it.

## Recommended Revision Order

1. Fix `_function_body` to skip a function's `local(...)` clause before finding its real body, and
   add a direct test proving it against `gc_build_grid`/`gc_hplp_bits` — this blocks Task 4 entirely
   as written (P0.4).
2. Drop or replace `check_filter_writers`'s vacuous `gc_slot_slider not in gc_field_commit` check
   (P0.5).
3. Give Task 4's DTFT tests literal, runnable bodies against `dsp.fir_brick_kernel` and
   `curve.realized_bits_grid`'s actual pair-list return, with `BD`/`beta` pinned (P1.6).
4. Add the extracted-metadata test the round-two review already called for but the plan never
   wrote down (P1.7).
5. Then proceed with the round-two revision order (P0.1-P0.3, P1.1-P1.5, P2.1) as already accepted.
