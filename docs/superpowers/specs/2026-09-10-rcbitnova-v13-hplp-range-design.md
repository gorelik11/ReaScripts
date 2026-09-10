# RCBitNova V1.3 — an HP/LP range that reaches the resampler's brickwall

**Design, 2026-09-10.** Supersedes the task note of the same date.

Everything below that describes the current source was RUN against it, not remembered. Where a
number is derived, the derivation is shown, because two of the three defects this design exists to
prevent are arithmetic that looks right until it is evaluated.

## 1. The job, and why it cannot be done today

Band-limit before a **sample-rate conversion**, with the owner's own filter rather than the
converter's. He has always done this in ReaFIR at about **21.5 kHz**, checking on an analyser that
nothing survives above 22 kHz even at extreme settings. Converting a 96 kHz session to 44.1 kHz,
the target is the OUTPUT format's Nyquist, not the session's.

RCBitNova already has the filter: `FIR Brick`, slope index 6. What it lacks is a corner that can be
put where the job needs it.

```
slider132:20<20,20000,1>-HP Freq (Hz)
slider136:20000<20,20000,1>-LP Freq (Hz)
```

**The declared RANGE is the limit, at every sample rate.** The engine's `min(..., srate * 0.49)`
clamp — six sites — binds only at LOW rates: at 44.1 kHz it caps the corner at 21609 Hz, and at
96 kHz it never binds at all, because 20000 is already far below 47040. An earlier answer in the
session blamed Nyquist for the 20 kHz ceiling. That was wrong, and the owner caught it by switching
the project to 96 kHz and seeing the same 20 kHz.

## 2. Decisions taken

| Decision | Chosen | Why |
|---|---|---|
| New maximum | **24000 Hz** | 48 kHz Nyquist. Covers both destinations anyone converts DOWN to, 44.1 and 48. Costs 2.6% of the axis. 40000 or 48000 would spend a tenth of the graph on a region nothing converts to. |
| Band frequencies | **unchanged at 20000** | Confines the range change — and therefore the migration, the dangerous part — to exactly TWO records out of 176. A bell at 22 kHz has no musical use, and a band node that cannot enter the top 2.6% of the graph is honest: that strip belongs to the brickwall. |
| Numeric entry | **two fields in the top bar** | 21.5 kHz cannot be set by dragging: at the top of a log axis one logical pixel is worth hundreds of Hz. The top bar is visible at every window size, unlike the panel, and does not depend on hovering, unlike the handle's label. |

## 3. What changes in the plugin

`JSFX/RCBitNova V1.3` begins as an exact copy of V1.2 — the project's rule since V0.1. **V1.2 is
frozen the moment it is tagged, and it is tagged.**

### 3.1 Two declarations

`slider132` and `slider136` become `<20,24000,1>`. **Defaults are not touched** — HP stays 20, LP
stays 20000 — so the record differs in its upper bound alone, not in the triple of range, step and
default. A fresh V1.3 instance therefore holds the same frequencies as a fresh V1.2 one.

### 3.2 The axis

```
current  gc_x_of_f(f) = gc_px + gc_pw * (log(min(max(f,20),20000) / 20) / log(1000))
         gc_f_of_x(x) = 20 * pow(1000, min(max((x - gc_px) / gc_pw, 0), 1))
new      the clamp becomes 24000, and 1000 becomes 1200
```

`log10(1200) = 3.07918` against `log10(1000) = 3`, so every node's distance from the left edge
scales by `3 / 3.07918 = 0.97428`. A node at 10 kHz moves from 0.900 of the width to 0.877 —
about 2.3% left. Visible only by comparison; V1.2's projects keep V1.2's graph, and a migrated
project shows the same frequencies drawn on a wider ruler.

The frequency grid needs no change: `loop(3, gc_gx = gc_x_of_f(100 * pow(10, gc_i)); ...)` goes
through `gc_x_of_f` and moves with it.

### 3.3 The clamp that widening the axis silently REMOVES

The band-node drag writes the frequency straight from the axis:

```
gc_v = gc_f_of_x(mouse_x);
gc_v != slider(gc_s + 3) ? gc_w_freq(gc_drag, gc_v, 1);
```

There is no clamp here. There has never needed to be one: `gc_f_of_x` could not return more than
20000, which is exactly the band sliders' maximum. Widen the axis and it returns up to 24000, and a
band node dragged into the new strip writes a frequency past its own declared range. The keyboard
path already clamps — `min(max(gc_val,20),20000)` — and the drag path only appeared to.

**`gc_w_freq` clamps to 20..20000 itself.** Putting it in the writer rather than at the call site
covers the drag, the graph and anything added later, and the gate can assert it is there.

This is the third instance in this design of one class: **a range change removing a guarantee that
was never written down, only implied.** The other two are in section 4.

### 3.4 Two named writers, and the fields

`gc_w_hpfreq(v)` and `gc_w_lpfreq(v)`: write the named slider, `slider_automate` it, then call
`gc_apply_hplp(eng)` — write, automate, THEN rebuild, the order every writer in this plugin uses,
because `@slider` is not guaranteed to run after `slider_automate` (established live in V1.0).

Today that write exists in exactly ONE place, the handle-drag block, as two branches:

```
gc_fdrag == 0 ? ( gc_v != slider132 ? ( slider132 = floor(gc_v + 0.5); slider_automate(slider132); gc_apply_hplp(0); ); )
              : ( gc_v != slider136 ? ( slider136 = floor(gc_v + 0.5); slider_automate(slider136); gc_apply_hplp(1); ); );
```

(An earlier draft of this spec claimed three sites. Grepped: the handle's right-click menu writes
the SLOPE and the PLACEMENT, and the resonance path writes sliders 133 and 137. One site.)

So the writers are not consolidating a duplication that exists — they are preventing the one the
field would create, and giving the gate something named to assert about. Both the drag and the
field call them; the rounding, the automate and the rebuild live in one place per engine.

The fields are `gc_field_at` calls in the top bar beside `Phase / HP res / LP res`, with edit ids
**200 and 201**. `gc_field_commit` gains a branch for `id >= 200` BEFORE its band arithmetic:
`b = floor((id - 100) / 10)` is meaningless for a filter that has no band.

Steps and ranges come from `gc_fmeta`'s two new rows, as every other field's do.

## 4. The same defect in two places: normalised copying across a changed range

REAPER stores a parameter NORMALISED over its declared range. Two pieces of this project's own
tooling copy that number from one version to another, and both are correct only while the ranges
match.

### 4.1 The migration

`tools/migrate_v10_to_v11.py` copies `param.normalized` positionally for the declared block. For
174 of the 176 records that stays right. For the two frequencies it is not:

```
12000 Hz in V1.2  ->  (12000 - 20) / (20000 - 20)  =  0.5995996
0.5995996 in V1.3 ->  20 + 0.5995996 * (24000 - 20)  =  14398.4 Hz
```

A 24 dB/oct low-pass moved from 12 kHz to 14.4 kHz, with no error anywhere.

It refuses automation, parameter modulation, non-default pin maps and instance oversampling
outright, so **rescaling automation envelopes is not part of this work** — the precedent is
already set and stays.

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
inside it** — declared order follows slider NUMBER, and 132 and 136 sit in the 131..142 block V1.0
already owned. Had they landed above 95 this section would be moot; they do not.

Concretely, `min_hplp` and `linear_hplp` both set `LP Freq (Hz): 12000` with a live slope. V1.3
would render at 14398 Hz. The suite would go half green, half red — `defaults` passes because its
`LP Slope` is `Off` and the frequency is inert — and the red would read as a DSP regression in the
one tool whose whole job is to say the DSP did not change.

### 4.3 One cure for both

A **range-change table**, today two rows: `(declared index, old (lo, hi), new (lo, hi))`.

- The migrator converts through **Hz** for every record the table names, and copies normalised for
  every record it does not.
- The null harness writes the version under test **by value** rather than by raw normalised, and
  its post-write assertion compares the read-back **values**, not the normalised numbers. That is
  strictly stronger than what it does now and catches any future range divergence without being
  told about it.

The table is data, not two special cases in code, because it is the thing the gate compares
against the frozen fixture's diff.

## 5. Gates and tests

**The frozen fixture is edited by NAME, two records, never regenerated.** `--freeze` would agree
with whatever the source happens to say, which is the one thing a frozen fixture must not do. The
gate's `--live` check keeps comparing V1.3's declared prefix to it field by field, with the two
named records expected to differ in `hi` and in nothing else — the same shape as the existing
`_fine_ceiling_indices` exemption, which already permits sixteen ceiling records to differ in
`step` and nothing else.

New source gate rows:

- the two declarations carry `24000`;
- `gc_x_of_f` and `gc_f_of_x` carry `24000` and `1200` and agree with each other;
- `gc_w_freq` clamps to the band range (section 3.3);
- the two HP/LP writers exist, write their named slider, automate it and call `gc_apply_hplp`.
  `check_writers` cannot cover them: it asserts eight branches and a `(b, v)` signature, and these
  take `(v)`. They get their own check rather than a loosened shared one.

Seeded defects, each rejected for its own reason: the axis widened but a clamp left at 20000; the
declaration widened but the axis not; `gc_w_freq` without its clamp; the migrator copying
normalised for a record the range table names.

**Null: V1.3 against V1.2, the same Hz on both sides, zero tolerance, 6 of 6.** A range change is
not a DSP change, and this is what says so.

Live: set 21.5 kHz by typing, with `FIR Brick`, and confirm on an analyser that nothing survives
above 22 kHz — the measurement the owner already makes in ReaFIR, against the tool it replaces.

## 6. What must stay true

- V1.2 is frozen; V1.3 is a new file, as every version has been.
- Nothing about the dynamics panel changes. If a sample moves, the work is wrong.
- The band frequency sliders keep `<20,20000,1>`, and the migration touches two records.
