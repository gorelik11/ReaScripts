# RCBitNova V1.3 — an HP/LP range that reaches the resampler's brickwall

**Design, 2026-09-10. Revision 3** after two weaknesses reviews
(`...-weaknesses.md`, then `...-weaknesses-fable.md`). Round one: seven accepted, one rejected on
measured evidence. Round two: two more P0s, both accepted, one of them already fixed in code.
Section 8 records both rounds.

Everything below that describes the current source was RUN against it, not remembered.

## 1. The job, and why it cannot be done today

Band-limit before a **sample-rate conversion**, with the owner's own filter rather than the
converter's. He has always done this in ReaFIR at about **21.5 kHz**, checking on an analyser that
nothing survives above 22 kHz even at extreme settings. Converting a 96 kHz session to 44.1 kHz,
the target is the OUTPUT format's Nyquist, not the session's.

RCBitNova already has the filter: `FIR Brick`, slope index 6. What it lacks is a corner that can be
put where the job needs it.

```
slider132:20<20,20000,1>-HP Freq (Hz)       declared record 85
slider136:20000<20,20000,1>-LP Freq (Hz)    declared record 89
```

**The declared range caps what can be REQUESTED, at every sample rate.** That is the blocker. It is
not Nyquist: the engine's `min(..., srate * 0.49)` clamp — six sites — binds only at low rates, and
at 96 kHz never binds at all because 20000 is far below 47040. An earlier answer in this project
blamed Nyquist for the 20 kHz ceiling; the owner disproved it by switching the project to 96 kHz
and seeing the same 20 kHz.

**Requested is not effective.** Section 7 keeps the two apart throughout.

## 2. Decisions taken

| Decision | Chosen | Why |
|---|---|---|
| New maximum | **24000 Hz requested** | 48 kHz Nyquist. Covers both destinations anyone converts DOWN to, 44.1 and 48. Costs 2.6% of the axis. 40000 or 48000 would spend a tenth of the graph on a region nothing converts to. |
| Band frequencies | **unchanged at 20000** | Confines the range change — and therefore the migration, the dangerous part — to exactly TWO of 176 records. A bell at 22 kHz has no musical use, and a band node that cannot enter the top 2.6% of the graph is honest: that strip belongs to the brickwall. |
| Numeric entry | **two fields in the top bar** | 21.5 kHz cannot be dragged: at the top of a log axis one logical pixel is worth hundreds of Hz. The top bar is visible at every window size, unlike the panel, and does not depend on hovering, unlike the handle's label. |

## 3. What changes in the plugin

`JSFX/RCBitNova V1.3` begins as an exact copy of V1.2 — the project's rule since V0.1. **V1.2 is
frozen, and it is tagged `rcbitnova-v1.2`.**

### 3.1 Two declarations

`slider132` and `slider136` become `<20,24000,1>`. **Defaults are not touched** — HP stays 20, LP
stays 20000 — so each record differs in its upper bound alone, not in the triple of range, step and
default. A fresh V1.3 instance holds the same frequencies as a fresh V1.2 one.

### 3.2 ONE graph-frequency contract, and it has FOUR readers, not two

Revision 1 named two functions. That was the review's P0.1 and it is correct: the visible axis and
the realized linear-phase curve are **separate coordinate systems**, each with its own hard-coded
20 kHz and its own `log(1000)`.

```
gc_x_of_f     gc_px + gc_pw * (log(min(max(f,20),20000) / 20) / log(1000))   axis producer
gc_f_of_x     20 * pow(1000, clamp((x - gc_px)/gc_pw, 0, 1))                 axis reader
gc_build_grid f = min(20 * pow(1000, t), srate * 0.5)                        GRID producer
gc_hplp_bits  t = log(min(max(f,20),20000) / 20) / log(1000) * (GC_LIN_N-1)  GRID reader
```

Change only the axis and Min phase follows 24 kHz — it evaluates `gc_svf_mag` at the requested
frequency — while Linear and FIR Brick read a grid still built to 20 kHz. Change only the reader
and its 24 kHz index addresses a producer whose last sample is 20 kHz. Either way the curve comes
out smooth, believable and wrong, which is this plugin's established failure mode.

**The contract becomes named constants in `@init`, and all four sites read them:**

```
GC_FMIN = 20; GC_FMAX = 24000;
GC_FSPAN = GC_FMAX / GC_FMIN;      // 1200
GC_FLOG  = log(GC_FSPAN);
```

The source gate asserts that no bare `1000`, `20000` or `24000` survives inside those four function
bodies, and that each references the constants. Checking for the literal `24000` in four places
would pass a build where one site kept its own copy and a later edit moved only three.

`tools/rcbitnova_curve.py`, the Python oracle, carries the same old contract: `FMIN, FMAX = 20.0,
20000.0`, used by `f_to_x`, `x_to_f` and `realized_bits_grid`. It moves to 24000 with them.
**Existing oracle tests that rely on the default `fmax` must be audited, not merely re-run** — one
that passes at both bounds is not testing the bound.

New oracle tests compare the reduced grid against a direct DTFT at **21.5, 22, 23.5 and 24 kHz**,
for HP and for LP. Seeded defects: an old grid producer with a new reader, and an old reader with a
new producer. Changing both axis helpers must not be enough to pass.

**The four sites are all of them.** Independently re-grepped in round two for every `20000`,
`pow(1000` and `log(1000)`. The only other hits are the eight band-frequency declarations and the
band typed-frequency clamp — both deliberately excluded, bands stay at 20000 — and one
`gfx_measurestr` label probe where "20000 Hz" and "24000 Hz" are the same width. There is no fifth
coordinate system. Recorded so nobody redoes the grep.

**One deliberate asymmetry, stated so the plan does not "fix" it.** The grid producer clamps to
`srate * 0.5`; the reader does not. At 44.1 kHz the top of the grid holds 22050 Hz while the reader
labels it 24000. Samples below the clamp are still exactly where the reader expects them — the
producer's `GC_FMIN * pow(GC_FSPAN, t)` is the reader's inverse — so only the tail flattens, which
is the truth: there is no response above Nyquist. This is correct and stays.

### 3.3 The clamp that widening the axis silently REMOVES

The band-node drag writes the frequency straight from the axis:

```
gc_v = gc_f_of_x(mouse_x);
gc_v != slider(gc_s + 3) ? gc_w_freq(gc_drag, gc_v, 1);
```

There is no clamp here, and none has been needed: `gc_f_of_x` could not return more than 20000,
which is exactly the band sliders' maximum. Widen the axis and it returns up to 24000, and a band
node dragged into the new strip writes a frequency past its own declared range. The keyboard path
clamps — `min(max(gc_val,20),20000)` — and the drag path only appeared to.

**`gc_w_freq` clamps to 20..20000 itself.** In the writer rather than at the call site, so it covers
the drag, the graph and anything added later, and the gate can assert it is there.

`gc_w_freq` is the EXISTING eight-branch BAND writer, `(b, v, qz)`. It is not one of the two new
single-argument HP/LP writers named two paragraphs down, despite the similar name. The HP/LP write
needs no clamp of its own: its declared range widens in lockstep with the axis. The band writer
needs one precisely because its range does not.

### 3.4 Two named writers, and the two fields

`gc_w_hpfreq(v)` and `gc_w_lpfreq(v)`: write the named slider, `slider_automate` it, then call
`gc_apply_hplp(eng)` — write, automate, THEN rebuild, the order every writer here uses, because
`@slider` is not guaranteed to run after `slider_automate` (established live in V1.0).

That write currently exists in exactly ONE place, the handle-drag block, as two branches. (Revision
1 claimed three sites; grepped: the right-click menu writes the SLOPE and the PLACEMENT, and the
resonance path writes sliders 133 and 137.) The writers are not consolidating a duplication that
exists — they prevent the one the field would create, and give the gate something named to assert.

**Ids 200 and 201 need an ID RESOLVER, not a branch in `gc_field_commit`.** This was the review's
P1.1 and it is correct. The band arithmetic is not confined to commit; the press/drag controller
runs it too:

```
gc_slot = (gc_cap - 100) % 10;
gc_v = gc_cap_v - floor(...) * gc_fmeta[gc_slot*8 + 4];
gc_v != slider(gc_slot_slider(floor((gc_cap - 100) / 10), gc_slot)) ? ...
```

For id 200 that yields band **10** and slot **0** — the Soft-ceiling metadata row, and
`gc_slot_slider` reading `dynb[10]`, four words past the eight-entry table. A commit-only branch
would make typing work while the drag silently compared against, and then wrote, something else.

So: one resolver, `gc_field_meta_row(id)` and `gc_field_slider(id)`, used by capture, metadata
lookup, current-value read, drag and commit alike. Ids 200/201 map to two new `gc_fmeta` rows and
to the two named writers, and never enter `gc_slot_slider`. Both ids are gated and live-tested
through **every** gesture, not only typing.

## 4. The same defect in two places: normalised copying across a changed range

REAPER stores a parameter NORMALISED over its declared range. Two pieces of this project's tooling
copy that number between versions, and both are correct only while the ranges match.

```
12000 Hz in V1.2  ->  (12000 - 20) / (20000 - 20)  =  0.5995996
0.5995996 in V1.3 ->  20 + 0.5995996 * (24000 - 20)  =  14398.4 Hz
```

A 24 dB/oct low-pass moved from 12 kHz to 14.4 kHz, with no error anywhere.

### 4.1 The migration is a NEW tool

Revision 1 described this transition as happening inside `tools/migrate_v10_to_v11.py`. It cannot:
that script calls itself "the only supported migration", finds one `RCBitNova V1.0`, creates
`RCBitNova V1.1`, and copies exactly `N_DECLARED_V10 = 95` records. There is no V1.2 source, no
V1.3 destination, no 176-record path and no range metadata. Retrofitting would put the already-
tested V1.0 -> V1.1 contract at risk for nothing.

**`tools/migrate_v12_to_v13.py`, a separate tool.** It reuses the older script's *shape* — the same
refusals, the same GUID-string identity, the same positional host tail, the same undo discipline —
and none of its constants.

- 176 declared records plus the three host parameters, all positional.
- Records **85** and **89** (`HP Freq (Hz)`, `LP Freq (Hz)`) are converted through **Hz**, not
  normalised: read the source's actual value, quantise to the 1 Hz declared step, write the
  destination's normalised equivalent for `<20,24000,1>`.
- **Read back and verify those two values in Hz before the V1.2 instance is removed.** A migration
  that cannot prove the frequency survived must refuse, not report success.
- Refusals carried over verbatim: automation, parameter modulation, non-default pin maps, instance
  oversampling, an ambiguous chain. **Rescaling automation envelopes is therefore out of scope** —
  the precedent is already set and stays.
- **`tests/_reaper_fx_fake.py` cannot express this migration today, and that blocks the project's
  own FakeReaper-first rule.** `FakeParam` holds a name, an envelope and a bare `.normalized`
  float — no declared range, no step, no actual value. The one dangerous mechanism in the new
  migrator is precisely the one it cannot model: converting records 85 and 89 through real Hz
  across two different ranges, and reading the result back to verify. So the fake gains `lo`,
  `hi`, `step` and an actual-value accessor, and a V1.3 count/name branch, BEFORE the migrator is
  written. Offline tests must be able to fail on a normalised copy.
- The V1.0 -> V1.1 script and its thirteen tests are **not touched**.

### 4.2 The null harness — the same trap, and it is SILENT

`tools/rcbitnova_nulltest.py` renders the baseline from named VALUES, reads back the first 95
normalised numbers, and writes those raw into the version under test:

```
a, norms10 = render(BASE, values=values)
b, norms11 = render(UNDER_TEST, norms=norms10)
assert norms10 == norms11
```

The handshake exists to make the two instances equal BY CONSTRUCTION. A range change destroys that
construction, and the assertion cannot see it: it compares normalised against normalised, and those
do agree.

The 95 is V1.0's declared count, carried over deliberately, and **both frequency records fall
inside it: they are records 85 and 89**, read from the frozen manifest. Had they landed above 95
this section would be moot; they do not.

Concretely, `min_hplp` and `linear_hplp` both set `LP Freq (Hz): 12000` with a live slope. V1.3
would render at 14398 Hz. The suite would go half green, half red — `defaults` passes because its
`LP Slope` is `Off` and the frequency is inert — and the red would read as a DSP regression in the
one tool whose whole job is to say the DSP did not change.

### 4.3 One cure for both

A **range-change table**, today two rows: `(declared index, old (lo, hi), new (lo, hi))`.

- The migrator converts through Hz for every record the table names and copies normalised for every
  record it does not.
- The null harness writes the version under test **by value** rather than by raw normalised, and its
  post-write assertion compares read-back **values**, not normalised numbers. Strictly stronger than
  today, and it catches a future range divergence without being told about it.

  Concretely, because prose here admits two incompatible readings and one of them defeats the fix:
  **read back all `N_DECLARED_V12` actual values from the BASE render by INDEX** — not the handful
  of names a `CASES` entry happens to mention — and replay all of them into `UNDER_TEST` through
  its own live `lo, hi`. The `values=` path in `render()` already does exactly this conversion for
  one parameter; it is generalised from a name dict to a full index-wise state copy, and the
  `norms=` path goes away. The post-write check
  `got = [...GetParamNormalized... for k in range(95)]` widens to `range(N_DECLARED_V12)`, so it
  spans every record the migrator also touches rather than the historical 95. A version that
  copies the `CASES` names by value and everything else by raw normalised would pass its own
  assertion and still compare two different low-pass frequencies.

The table is data, not two special cases in code, because it is what the gate compares against the
fixture diff.

## 5. Fixtures and gates

### 5.1 A NEW frozen fixture; the old one is evidence and is not edited

Revision 1 said the frozen fixture is "edited by name, two records". The review's P0.3 is correct
that this destroys it. `tests/fixtures/v11_declared_175.json` is immutable evidence of what V1.1
declared, and it still proves V1.2's first 175 records. Edited, it would describe neither.

It is also one record short of this transition: **V1.2 declares 176** (`N_DECLARED_V12 = 176`), and
record 175 is `slider246`, the persisted panel-card state — the very parameter whose numbering cost
this project three spec revisions. `check_live` compares `dec11[:len(frozen)]`, so that record is
currently frozen nowhere.

- Add `tests/fixtures/v12_declared_176.json`, captured from the **tagged** V1.2.
- Compare V1.3 against it with exactly two permitted differences: `hi` on records 85 and 89, and
  nothing else — the same shape as the `_fine_ceiling_indices` exemption, which permits sixteen
  ceiling records to differ in `step` alone.

  **That template was itself broken, and this feature is what would have woken it.** It derived its
  sixteen indices from the TEXTUAL order of the declarations, so seven were wrong — every one in
  B5-B8, where the orders diverge. `B5 Hard Ceiling Macro` pointed at `B7 Enable`. It never fired
  because its only caller stops at V1.0's 95 records and no wrong index is below 95; the
  176-record comparison proposed here is the first thing that walks past them. Fixed and pinned by
  name against the measured manifest in `d7b1712`, before anything is built on it.
- `v11_declared_175.json` stays untouched and keeps proving V1.1.
- The expected V1.3 manifest is DERIVED in memory from the V1.2 fixture plus the range-change
  table. Never regenerated from source: `--freeze` agrees with whatever the source says, which is
  the one thing a frozen fixture must not do.
- Seed a changed and a missing panel-state record as compatibility defects.

### 5.2 Source gate rows

- the two declarations carry `24000`;
- `GC_FMIN`/`GC_FMAX`/`GC_FSPAN`/`GC_FLOG` exist, and no bare `1000`/`20000`/`24000` survives in the
  four coordinate function bodies;
- `gc_w_freq` clamps to the band range (3.3);
- the two HP/LP writers exist, write their named slider, automate it and call `gc_apply_hplp`.
  `check_writers` cannot cover them — it asserts eight branches and a `(b, v)` signature, and these
  take `(v)` — so they get their own check rather than a loosened shared one;
- ids 200/201 resolve through `gc_field_meta_row`/`gc_field_slider` and never through
  `gc_slot_slider`.

Seeded defects, each rejected for its own reason: axis widened with a clamp left at 20000; the
declaration widened but the axis not; the axis widened but the realized grid not; the grid producer
widened but its reader not; `gc_w_freq` without its clamp; the migrator copying normalised for a
record the range table names; id 200 falling through to the band path.

### 5.3 Null

**V1.3 against V1.2, the same Hz on both sides, zero tolerance, 6 of 6.** A range change is not a
DSP change, and this is what says so.

## 6. Version ownership

Creating a new plugin file retargets more tools than revision 1 admitted. This is the review's P1.2
and the list is:

| Consumer | V1.3 | Stays on V1.2 |
|---|---|---|
| `rcbitnova_gates.py` — `V12`, `_fine_ceiling_indices`, `--live` | the file under test | the frozen comparison source |
| `rcbitnova_compile.py` | loads and deletes V1.3 | — |
| `rcbitnova_nulltest.py` | `UNDER_TEST` | `BASE` |
| `tests/_reaper_fx_fake.py` | a V1.3 count/name branch | V1.0/V1.1/V1.2 branches |
| `tests/test_rcbitnova_dsp.py` — four direct `gates.V12` opens | the source under test | — |
| `migrate_v10_to_v11.py` and its tests | untouched | untouched |

Stale docstrings go with them: `rcbitnova_compile.py` still opens with "Does JSFX/RCBitNova V1.1
actually COMPILE?" and the null harness with a V1.0/V1.1 premise.

**The compile check and both gates must identify the loaded effect as V1.3.** Without that, a plan
can pass every unit test against V1.2 and never compile V1.3 at all.

## 7. Requested frequency is not effective frequency

The declaration can hold 24 kHz; the engine still applies `min(freq, srate * 0.49)`. A 48 kHz
project therefore applies at most 23.52 kHz and a 44.1 kHz project at most 21.609 kHz, while the
field displays what was requested. This does not affect the 96 kHz conversion workflow — 24000 is
reachable there — but "48 kHz Nyquist" in section 2 names the DESIGN TARGET, not a guarantee at
every rate.

### The live acceptance test, made falsifiable

"Nothing survives above 22 kHz" proves nothing in a 44.1 kHz project: there is no representable
content above 22.05 kHz even with the filter bypassed. The review's P1.3 is correct. The test is:

- a **96 kHz** project, with source material carrying known energy above 22 kHz;
- `Phase: Linear`, `LP Slope: FIR Brick`, resolution stated;
- **fail first**: with `LP Slope: Off`, the analyser must SHOW that energy. A test that cannot fail
  has not passed;
- then `LP Freq` typed as **21500** in the new field, and rejection above 22 kHz measured against a
  stated dBFS or relative-rejection threshold. "Nothing" is not a result for a finite windowed FIR;
- both fields exercised, and both gestures on each — typing and dragging — with the writer's effect
  observed immediately, not after touching something else.

## 8. Response to the weaknesses reviews

### Round two (Fable)

**P0.1 accepted, and fixed before anything was built on it.** `_fine_ceiling_indices()` — the very
helper revision 2 named as the template for the new fixture's exemption set — derived its indices
from textual declaration order and was wrong for seven of sixteen. Verified exactly before
accepting: `B5 Hard Ceiling Macro` resolved to `B7 Enable`, `B6 Soft Ceiling Macro` to
`B8 Macro (bits)`. Dormant only because its caller stops at 95. Fixed in `d7b1712` and pinned by
name against the measured manifest. The gate that guards the parameter-order contract had the
parameter-order bug inside it.

**P0.2 accepted.** `FakeParam` has no range, no step and no actual value — so the migrator's one
dangerous mechanism cannot be tested offline at all. The fake is extended first. Section 4.1.

**P1.1 accepted.** "Write by value" had two readings, and the cheap one — converting only the
names a `CASES` entry mentions — would leave ~170 records on the raw normalised path and defeat
the fix while passing its own assertion. Section 4.3 now specifies an index-wise copy of all 176
and widens the post-write check from `range(95)`.

**P2.1 and P2.2** are confirmations, folded into sections 3.2 and 3.3 so the greps are not redone.

### Round one

Accepted in full: **P0.1** (four coordinate sites plus the oracle — verified in source),
**P0.2** (a separate migrator — the existing script is 95 records, V1.0 to V1.1 only),
**P0.3** (a new 176-record fixture; the old one is evidence), **P1.1** (an ID resolver, not a
commit branch — id 200 resolves to band 10, slot 0 today), **P1.2** (the consumer list),
**P1.3** (the analyser test was vacuous at 44.1 kHz), **P2.2** (requested versus effective).

**P2.1 is rejected on measured evidence, and its premise must not reach the plan.** Round two
settled it independently: slider-number order matches the measured manifest with 0 mismatches out
of 175, textual order with 68. The review
states that "host indices follow textual declaration order" and that declared order does NOT follow
slider number. The frozen fixture — read from a live REAPER instance, which is why it exists —
says otherwise, and the review's own example is the disproof:

```
record 104:  textual declaration order would give 'B5 Dyn'
             slider-number order gives            'B6 Enable'
             the MEASURED fixture holds           'B6 Enable'
```

Across all 175 records, `measured == slider-number order` is **True** and
`measured == textual order` is **False**. This is the finding of 2026-09-04, recorded in the vault:
the panel slider, declared last but numbered 143, landed at record 95 and displaced the entire
B5–B8 block. Adopting the textual rule would resurrect exactly that bug.

The review's *remedy* is nevertheless adopted: sections 1, 4.1 and 4.2 now state the measured
indices **85** and **89**, derived from the frozen manifest, rather than arguing from slider
numbers at all. The right index is the one the fixture reports; the ordering rule is what explains
it, not what establishes it.

## 9. What must stay true

- V1.2 is frozen; V1.3 is a new file, as every version has been.
- Nothing about the dynamics panel changes. If a sample moves, the work is wrong.
- The band frequency sliders keep `<20,20000,1>`, and the migration touches two records.
- `v11_declared_175.json` and the V1.0 -> V1.1 migrator are historical evidence and are not edited.
