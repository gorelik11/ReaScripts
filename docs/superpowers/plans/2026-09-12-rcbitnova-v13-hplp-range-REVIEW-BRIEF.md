# Review brief — RCBitNova V1.3, HP/LP range

**For a third reviewer (Astra), starting cold.** Written 2026-09-12. Self-contained: do NOT read
any Knowledge-vault file, and do not run the vault-loading protocol. Everything you need is here or
in the files it names.

Worktree: `/Users/macbook/projects/reascripts/.claude/worktrees/rcbitnova/`. All paths relative.

## What is being built

RCBitNova is a bit-accurate mid/side **dynamic** EQ, JSFX (EEL2), for REAPER. V1.3 raises the HP and
LP frequency sliders — `slider132` and `slider136`, declared records **85** and **89** — from
`<20,20000,1>` to `<20,24000,1>`, so the plugin's `FIR Brick` can band-limit at about **21.5 kHz**
before a sample-rate conversion. That is a job the owner currently does in ReaFIR; 22050 is the
OUTPUT format's Nyquist, not the session's.

Band frequencies stay at `<20,20000,1>`. Two numeric entry fields are added in the top bar (edit ids
200 and 201). A new V1.2 → V1.3 migrator converts the two changed records through **Hz**, because
REAPER stores a parameter NORMALISED over its declared range and a raw copy would retune it.

## Artefacts, in reading order

| File | What it is |
|---|---|
| `docs/superpowers/specs/2026-09-10-rcbitnova-v13-hplp-range-design.md` | the spec, **revision 3** |
| `...-weaknesses.md` (same stem) | spec review, round one — 8 findings |
| `...-weaknesses-fable.md` | spec review, round two — 5 findings |
| `docs/superpowers/plans/2026-09-12-rcbitnova-v13-hplp-range.md` | the plan, 9 tasks |
| `...-weaknesses.md` (plan stem) | plan review, round one — 9 findings |
| `...-weaknesses-fable.md` (plan stem) | plan review, round two |

Implementation and tooling the plan touches: `JSFX/RCBitNova V1.2`,
`tools/rcbitnova_{gates,curve,dsp,nulltest,compile,layout}.py`, `tools/migrate_v10_to_v11.py`,
`tests/_reaper_fx_fake.py`, `tests/test_rcbitnova_dsp.py`,
`tests/fixtures/v11_declared_175.json`.

## Measured facts. Do not re-derive these wrong — one of them has already cost three spec revisions

- **REAPER orders declared parameters by SLIDER NUMBER, not by declaration order.** Measured
  2026-09-04. Confirmed twice against `tests/fixtures/v11_declared_175.json`, which was read from
  live REAPER: slider-number order matches all 175 records, textual order misses 68, first at
  record 104 (`B6 Enable` measured; textual order would say `B5 Dyn`). A previous reviewer asserted
  the opposite and was wrong. If you want to check it yourself, compare the fixture's name sequence
  against `^slider(\d+):` in `JSFX/RCBitNova V1.1`, sorted both ways.
- **A parameter is stored NORMALISED over its declared range.** Changing a range silently retunes
  every stored value: 12000 Hz normalised in `<20,20000>` is 0.5995996, which in `<20,24000>` reads
  back as 14398.4 Hz. This is the defect the whole migration and null-harness work exists to
  prevent.
- **`n_params` does not prove a build compiles.** A `@gfx` syntax error leaves it unchanged.
  `tools/rcbitnova_compile.py` floats the FX window and reads its error text; that is the check.
- **EEL2:** no `1e18` literal; parenthesise every assignment inside a ternary branch; no
  bit-shifts; `@init` is SEQUENTIAL, so a global read above its own assignment reads zero.
- **`pytest ... | tail && git commit` does not guard** — the exit code is `tail`'s. It has put
  failing tests into this repository twice. Read `$?` directly.

## Already settled — do not re-litigate

The plan's round-one review found nine defects. **All nine were independently verified against the
source and accepted**; the plan is being revised for them. Round two (Fable) adds more; read its
file. Treat everything in both plan reviews as known.

The headline four, so you recognise the class:

1. `GC_FMIN`/`GC_FMAX` would be assigned at source line ~1394 but read by the `gc_fmeta` rows at
   ~315 — sequential `@init`, so both new metadata rows would store a `0..0` range.
2. The plan reads `dst.params[i].lo` / `.hi`; real `reapy.FXParam` has only `.range`. The plan's own
   Task 3 adds `.lo`/`.hi` to the FAKE, which would have masked the live break — the exact
   fake/host divergence a fake exists to prevent.
3. A read-back refusal `return`s from inside `try`, while the inherited migrator deletes the new
   instance only in `except` — leaving an orphan V1.3 in the chain while reporting "source
   untouched".
4. Rows 6/7 give the frequency fields a 1 Hz step and 12 logical pixels per step, so dragging LP
   from 20000 to 21500 would take 18,000 pixels — in fields that exist *because* dragging is too
   coarse.

## What to look for

The project's failure mode is not a crash. It is **a smooth, believable, wrong result**, and every
expensive defect in its history has that shape. Aim there:

- **Any coordinate system or stored contract that a change leaves half-updated.** The graph has
  FOUR frequency coordinate sites — the visible axis's producer and reader, and the realized
  linear-phase grid's producer and reader — plus a Python oracle. Are there others, anywhere?
- **Any gate row, assertion or seeded defect that cannot fire.** Three earlier drafts of this
  project's gates shipped rows that matched nothing. For each seeded defect, does its `str.replace`
  target actually occur in the text it will be applied to, *after* the plan's earlier edits? A seed
  caught by the WRONG assertion is worse than one that is not caught.
- **Any test that passes for the wrong reason.** A red checkpoint that is already green. A sabotage
  that is self-consistent and therefore migrates successfully. An acceptance test that cannot fail —
  "nothing above 22 kHz" proves nothing in a 44.1 kHz project, where nothing above 22.05 kHz is
  representable at all.
- **Any code snippet that does not match the API it names** — module, function name, argument order,
  and return SHAPE. `realized_bits_grid` returns a list of `(f, bits)` pairs, not two arrays; that
  one was missed by the author and caught only on the second pass.
- **Ordering between tasks:** anything a task needs that no earlier task produced.

## The one discipline that matters

**Verify every claim by running or grepping, never by recalling.** A finding you cannot point at
with a file and a line number is not a finding, and this project has been burned by confident
assertions about its own source from the author and from two reviewers. Say which claims you
verified and how.

You may run:

```bash
python3 -m pytest tests/test_rcbitnova_dsp.py -q > /tmp/t.txt 2>&1; echo $?
python3 tools/rcbitnova_gates.py --source-only > /tmp/g.txt 2>&1; echo $?
```

Both currently pass. Do **not** run anything needing live REAPER — `--live`,
`tools/rcbitnova_nulltest.py`, `tools/rcbitnova_compile.py` — and do not modify any file except
your own output.

## Output

Write to `docs/superpowers/plans/2026-09-12-rcbitnova-v13-hplp-range-weaknesses-astra.md`, in the
same shape as the other reviews: Summary; a priority table (**P0** = the plan as written produces a
broken build, a wrong curve, or a corrupted migration; **P1** = forces the implementer to invent
missing behaviour; **P2** = supporting claims wrong); findings, each with a **Required change**;
then a Recommended Revision Order. Do not commit it.
