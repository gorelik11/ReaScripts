# RCBitNova V1.1 Eight Dynamic Bands: Rev-2 Weaknesses

**Reviewed:**

- `docs/superpowers/specs/2026-08-22-rcbitnova-v1.1-eight-dynamic-bands-design.md` (rev 2)
- `docs/superpowers/plans/2026-08-22-rcbitnova-v1.1-eight-dynamic-bands.md` (rev 2)
- implementation baseline `JSFX/RCBitNova V1.0`
- review target commit `95c3d6e`

The rev-1 review is preserved in Git history and its disposition is reproduced in the plan. This
file now records the follow-up review of rev 2 rather than repeating closed findings.

## Summary

Rev 2 resolves the product-scope question, moves the missing writers and hit-set work before the
pre-flip gate, fixes the GUI-region arithmetic, makes migration local and self-contained, and pins
the live artifacts much more concretely. The design direction remains viable.

The implementation plan is still not executable as written. Two independent regex contradictions
make the clean source fail its own gate, while the claimed 28-site coverage does not check several
initialisation bounds that determine whether B5-B8 start in valid states.

| Priority | Count | Meaning |
|---|---:|---|
| P0 | 2 | The source gate cannot pass or can accept broken B5-B8 state |
| P1 | 4 | Material GUI, model, or verification weakness |
| P2 | 2 | Stale or contradictory documentation |

## P0 Findings

### P0.1: The table checks contradict Task 3's exact source in two places

Task 3 now declares the bases on three separate lines:

```eel2
stb  = 272;
dynb = 280;
ceb  = 288;
```

Task 4's `SITES["base-tables"]` still requires all three on one line and even requires exactly one
space in `stb =`:

```python
r"stb = (\d+); dynb = (\d+); ceb = (\d+);"
```

That row matches nothing, so the rule “a row matching nothing is a failure” stops `--preflip`.

The new contents checker has a second, independent mismatch. `TABLE_ENTRY` is anchored at the start
of a line, while Task 3 writes four assignments per line:

```python
TABLE_ENTRY = re.compile(r"^(stb|dynb|ceb)\[(\d+)\]\s*=\s*(\d+);", re.M)
```

Applied to the exact Task 3 block, it sees only six entries: indices 0 and 4 of each table. The other
18 are reported missing. This was reproduced directly with the plan's regex and source text.

**Required change:** use three independent declaration rows or parse declarations into a mapping.
Remove `^` from `TABLE_ENTRY` and give it an assignment boundary such as `(?:^|;)\s*`, or place one
table assignment on each line. Add one test that feeds the complete exact Task 3 block through
`check_sites`, `check_tables`, and `eval_init` together and requires success.

### P0.2: The address gate does not cover the initialisation sites assigned to it

Spec §8.2 maps eighteen `@init` sites to “computed address comparison” and says this is stronger
than matching their text. It is valid for base expressions such as:

```eel2
mbeh = mbgc + N_BANDS * 2;
```

It is not valid for fill bounds. These expressions write state but do not determine any later base:

```eel2
memset(st, 0, N_BANDS * 4);
memset(dst, 0, N_BANDS * 4);
memset(cst, 0, N_BANDS * 4);
loop(N_BANDS * 2, eg[i] = 1; ...);
loop(N_BANDS * 2, mbenv[i] = 1; ...);
memset(mbwpos, 0, N_BANDS);
loop(N_BANDS * 2, mbgc[i] = 1; ...);
loop(N_BANDS * 2, mbeh[i] = 1; ...);
loop(N_BANDS * 2, egh[i] = 1; ...);
```

For example, replacing the final bound with `4 * 2` leaves B5-B8's Mode-A hard envelopes at zero,
but every address in `AUDIO`, `GUI`, and `model_low` remains correct. The current site manifest and
`FORBIDDEN` list do not reject it. The plugin can therefore pass the advertised source contract
with broken dynamics state.

**Required change:** give each fill/memset family a source row that verifies its bound, and seed at
least `eg`, `mbenv`, `mbgc`, `mbeh`, `egh`, and one four-word state array with a hard-coded four-band
bound. The inventory must distinguish address-producing sites from state-initialising sites.

## P1 Findings

### P1.1: The revised GR formula still displays stale or inactive envelope words

Rev 2 correctly selects Mode A versus Mode B, multiplies soft and hard stages, and checks band/dyn
enable. It still reads both stored stages unconditionally:

```eel2
gc_ga = eg[...] * egh[...];
gc_gb = eg[...] * egh[...];
```

In Mode A, disabling Soft sets the local audio gain `gsA = 1` but does not reset `eg[]`; disabling
Hard similarly uses local `ghA = 1` without resetting `egh[]`. The tint therefore includes stale
reduction from a disabled stage. In linked mode, audio sets `gB = gA` without updating the B envelope
words; for Mid, Side, Left, or Right placement there is no active B channel at all. Taking the
minimum of both stored channels can again show stale reduction that is not applied to audio.

Mode B resets disabled stages more aggressively, but linked and one-channel placements still make
the second stored channel an invalid aggregate input.

**Required change:** substitute 1 for every disabled stage, mirror A for linked operation, and ignore
B when Placement is not Both. Derive the display from the same stage/mode/placement predicates as
`@sample`. The existing hard-only, soft-only, linked, and one-channel live cases should assert both
activation and release to catch stale state.

### P1.2: The selector's new row overlaps the existing effective-value line and is clipped in small mode

The fields themselves no longer overlap the strip. V1.0 also draws this line, however:

```eel2
gfx_y = gc_fy + gc_fh + 6 * gc_sc;  // "B1 effective ... bits"
```

Rev 2 places the selector at `gc_sy = gc_fy + gc_fh + 4*gc_sc`, with height `18*gc_sc`. The existing
summary text begins two pixels inside that selector row.

There is also no revised `gc_small` policy. V1.0 small mode reserves only 24 logical pixels below the
plot; the new selector starts 30 pixels below the plot and ends at 48. It is therefore outside the
reserved area and can be clipped or collide with the window edge. Adding a sixth 150-pixel field
also needs an explicit compact-width policy.

**Required change:** assign fields, effective summary, and selector distinct rows; update the
`gc_small` branch; verify normal, Retina, narrow, and short windows with screenshots and pointer
tests.

### P1.3: The ninth-band capacity test ignores collisions with the base tables

The product choice of eight is safe: the low map ends at 272 and the three tables occupy 272..295.
The plan nevertheless asserts `check_capacity(9) == []` and the spec says a ninth band fits.

Under the model's own `low_layout(9)`, `bp` occupies 261..287 and `eg` occupies 288..305. Those spans
overlap all three fixed tables: `stb` 272..279, `dynb` 280..287, and `ceb` 288..295. The model and
`GuardedMemory` do not include the table ranges, so the collision is invisible.

**Required change:** either state that a ninth band fits only after relocating/resizing all three
tables, or include the tables in the capacity and ownership models. Remove the unconditional
`check_capacity(9) == []` assertion in its current form. This does not change the eight-band layout.

### P1.4: The gate remains a collection of fragments, not the runnable contract Task 4 invokes

Rev 2 supplies complete-looking `check_forbidden` and `check_tables`, but still does not define
`check_sites`, `check_writers`, `check_addresses`, the CLI modes, or `SEEDED_DEFECTS`. The main
mutation table also omits the table-content mutations described separately in Step 2a. As a result,
the commands in Task 4 cannot be implemented by transcription; critical failure semantics are left
for the implementer to invent.

This matters because the two P0 contradictions above would have been caught immediately by a single
clean-source acceptance test written in the plan itself.

**Required change:** make `tools/rcbitnova_gates.py` a complete listing or specify every omitted
function with tests. The minimum meta-test is: exact Task 3 source passes once, then every listed
mutant fails for its named reason.

## P2 Findings

### P2.1: Rev-1 capacity language remains after the arithmetic correction

The spec correctly derives a 30-band low-map ceiling in §3.1, but two nearby statements still say
“memory allows ~34”. The same stale number remains in `check_capacity()`'s plan docstring. In
addition, the plan header still links its spec as “rev 1”.

**Required change:** replace the stale figures and update the plan's spec pointer to rev 2.

### P2.2: The rev-2 disposition overstates closure

The disposition marks all 13 rev-1 findings accepted. The scope, migration, arithmetic, and task
ordering fixes are real, but P0.4/P1.6 are only partially closed: the new table checker cannot read
the planned table block, and the full gate is still absent. P1.1 is also only partially closed
because stage and channel activity are not reflected in the tint expression.

**Required change:** mark those items partial until the exact clean source passes the complete gate
and the GR cases use only gains that audio actually applies.

## Recommended Revision Order

1. Repair the declaration and table-entry parsers, then add the exact-clean-source pass test.
2. Gate all initialisation bounds independently of address calculations.
3. Make the GR aggregate stage-, link-, and placement-aware.
4. Allocate separate GUI rows and define small-window behaviour.
5. Add table ranges to capacity modelling and clean up the stale revision text.

After these corrections, Tasks 1-5 have a coherent path: the eight-band memory map itself, slider
allocation, append-only declaration strategy, and `lp_base = 131072` conclusion remain valid.
