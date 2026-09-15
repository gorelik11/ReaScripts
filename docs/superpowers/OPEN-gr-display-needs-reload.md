# Open defect: the orange gain-reduction tint appears only after a plugin reload

**Reported live 2026-09-15 by the owner, on V1.4/V1.5.** Not blocking; recorded so it is not lost.

## Symptom

Frequencies are audibly being pressed - the dynamics work - but the node's orange GR tint does not
appear until the plugin is reloaded. After a reload it works. The owner's own words: "the same as
it used to be with the filters", which is the family of three bugs fixed in V1.3 and V1.4.

## What is already established, statically

The tint is drawn at `JSFX/RCBitNova V1.5:2590`, from `gc_gr`, computed just above:

```eel2
gc_gr = 0;
(gc_en && slider(dynb[gc_b] + 1) == 1) ? (
  ...
  mbmode[gc_b] == 1 ? (
    gc_ga = (gc_soft ? mbgc[gc_b*2] : 1) * (gc_hard ? mbeh[gc_b*2] : 1);
  ) : (
    gc_ga = (gc_soft ? eg[gc_b*2]   : 1) * (gc_hard ? egh[gc_b*2]  : 1);
  );
  gc_gr = 1 - min(gc_ga, gc_gb);
);
```

Checked, and all of it lines up - so the cause is NOT any of these:

- The guard reads sliders live (`gc_en`, Dyn on), so it cannot go stale.
- `@sample` writes `mbgc[csA]`/`mbeh[csA]` with `cs = b*2 + c` (`:2119-2145`), exactly the index
  the display reads. Mode A writes `eg`/`egh` at `b*2` likewise (`:1942`).
- `mbmode[]` is read by BOTH the audio path (`:1912`, `:1980`, `:2072`) and the display (`:2581`).
  If it were stale the AUDIO would run the wrong mode too, and the owner has confirmed live that
  EQ and Split sound different from each other - so it is current.
- All four arrays are filled with 1 at `@init` (`:361`, `:364`, and the `eg`/`egh` fills), which is
  what "no reduction" means, so an unfilled array shows nothing rather than something wrong.

## What to do next

The static reading is exhausted; this needs the probe technique that settled the Phase bug.
Make a throwaway copy of the plugin with extra sliders mirroring the suspects - `mbmode[0]`,
`mbgc[0]`, `mbeh[0]`, `eg[0]`, `egh[0]` - written at the end of `@slider`, and read them through
the API while audio plays. That says in one run which value the display is reading and whether it
is the one `@sample` is writing.

Note the shape of the previous three: every one was state that only advances while audio flows,
and every one looked like "works only after reloading the plugin" because `@init` is the only
section REAPER runs unconditionally. Look there first, but do not assume it - the fourth of a
pattern is exactly where a pattern stops holding.

## Where the fix goes

Not V1.5. V1.5 is the HP/LP range and is mid-plan. This is drawing only, so it is cheap to carry,
but it earns its own version once diagnosed.
