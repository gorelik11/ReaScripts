# V1.3 — an HP/LP range that reaches the brickwall a resampler needs

**Raised by the owner, 2026-09-10, from real use.** Not a nicety: it is the difference between the
plugin being usable for a job he currently does elsewhere and not.

## The job

Band-limit before a **sample-rate conversion**, with his own filter rather than the converter's.
He has always done this in ReaFIR, at **about 21.5 kHz**, checking on an analyser that nothing
survives above 22 kHz even at extreme settings. Converting a 96 kHz project to 44.1 kHz, the
target is 22050 — the output format's Nyquist, not the session's.

RCBitNova already has the filter for it: `FIR Brick`, slope index 6. What it does not have is a
corner that can be put where the job needs it.

## Why it cannot be done today

```
slider132:20<20,20000,1>-HP Freq (Hz)
slider136:20000<20,20000,1>-LP Freq (Hz)
```

**The declared RANGE is the limit, at every sample rate.** The `min(..., srate * 0.49)` clamp in
the engine binds only at LOW rates — at 44.1 kHz it caps the corner at 21609 Hz — and never at 96
kHz, where 20000 is already far below it. An earlier answer in the session blamed Nyquist for the
20 kHz ceiling; that was wrong, and the owner caught it by switching to 96 kHz and seeing the same
20 kHz.

## What the change actually costs

**1. The range is load-bearing for migration.** REAPER stores a parameter normalised over its
declared range. `tests/fixtures/v11_declared_175.json` requires V1.2's first 175 records to BE
V1.1's — to the range, step and default — and `--live` compares them field by field. That is what
makes a V1.1 -> V1.2 migration a copy. Widen the range and a stored 1000 Hz reopens as a different
frequency: at `<20,40000,1>` the normalised 0.04905 becomes 20 + 0.04905 * 39980 = 1981 Hz.

So V1.3 needs a migration that carries the value **in Hz**, not the normalised number.
`tools/migrate_v10_to_v11.py` copies normalised and must not be reused as-is for these two records.

**2. The frequency axis is three hard-coded decades.**

```
gc_x_of_f(f) = gc_px + gc_pw * (log(min(max(f,20),20000) / 20) / log(1000))
gc_f_of_x(x) = 20 * pow(1000, ...)
```

Widen the range without the axis and everything above 20 kHz piles into the right edge, where it
cannot be dragged. Widen the axis and every band node moves — the graph changes shape, which is a
visible change to a plugin the owner has projects in.

**3. Dragging cannot set 21.5 kHz.** At the top of a log axis a logical pixel is worth hundreds of
Hz. The HP/LP corner has no numeric entry today — only the handle drag and the right-click menu.
**A numeric field for HP/LP frequency is part of this task, not a follow-up.** The field primitive
and the controller already exist (`gc_field_at`, `gc_fmeta`, `gc_field_commit`); this is a new
metadata slot and a named writer, not new machinery.

## Open decisions

- **How wide.** 40000 covers a 96 kHz session converting to anything, and leaves room at 192 kHz.
  22050 alone would cover only the 44.1 target. The wider the range, the more of the axis is spent
  on a region only this job uses.
- **Whether the axis widens for everything or only for the HP/LP handles.** A split axis is ugly
  and probably worse than moving every node once.
- **Whether the band frequencies widen too.** They are `<20,20000,1>` as well. Leaving them alone
  keeps 168 of the 175 records untouched and confines the migration to two.

## What must stay true

- V1.2 is frozen the moment it is tagged; V1.3 is a new file, as every version has been.
- The null test still compares against the previous version at zero tolerance. A range change is
  NOT a DSP change: with the same Hz on both sides the audio must still be identical.
- The gate's frozen-prefix check must be updated deliberately, with the two changed records named,
  never by regenerating the fixture. Regenerating it would agree with whatever the source says.
