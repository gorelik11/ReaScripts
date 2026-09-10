# Dynamics panel — where the work stands

**2026-09-04.** Written at a context handoff; read this, then the plan.

## State

| | |
|---|---|
| Branch | `rcbitnova`, worktree `.claude/worktrees/rcbitnova/` |
| Frozen | `JSFX/RCBitNova V1.1`, tag `rcbitnova-v1.1`, **in the owner's projects — never edit** |
| Working | `JSFX/RCBitNova V1.2` |
| Spec | `docs/superpowers/specs/2026-09-02-rcbitnova-dynamics-panel-design.md` **rev 5** |
| Plan | `docs/superpowers/plans/2026-09-02-rcbitnova-dynamics-panel.md`, 9 tasks |
| Done | Tasks 1–9 (`…df7e77d`, `e481cb4`, `5c8b07a`, `19bc781`) — see the live matrix note below |
| Next | Tag `rcbitnova-v1.2`, then V1.3 (`specs/2026-09-10-rcbitnova-v13-hplp-range.md`) |
| Green | 281 tests · gate 34 sites, 20 writers · live: 175 frozen records identical · compile 179 · **null 6/6 identical, zero tolerance** |

## The one thing to know before touching parameters

**REAPER orders FX parameters by SLIDER NUMBER, not by declaration order.** Measured 2026-09-04.
The panel slider, declared last but numbered 143, landed at record 95 and pushed `B5 Enable` to 96 —
shifting all eighty B5–B8 records while V1.0's 95-record prefix stayed intact, so every V1.0-based
check still passed. It is `slider246` now, record 175.

Three spec revisions and both reviewers carried the wrong rule, because the obvious test cannot
distinguish them: sliders added later in the file *and* higher in number satisfy both.

What caught it: `tests/fixtures/v11_declared_175.json` — V1.1's 175 records frozen with ranges,
steps and defaults, compared field by field by `--live`.

## Tasks 5–8, in passing

The plan's own writer sample could not have passed the plan's own gate: it aligns the assignments
(`slider51  = v;`) and the gate matches `slider(\d+) = v;` with one space. The nine V1.0 writers
are unpadded, so the house style was already the correct answer. Cost five minutes; worth knowing
that a plan's code blocks are not gate-checked before they are pasted.

The null test was NOT re-run for Task 5 — the eleven writers are not called from anywhere yet.
Task 9 owns the full 6/6 suite; Task 6 ran `defaults` only, as its step 6 asks.

**The plan's `gc_meta = 304` would have been a silent disaster.** `gc_meta` is already a
sixteen-word NAMED region at `gc_snap + 128` holding the curve buffers' indices and generations
(`GCM_IDX_HP` … `GCM_TGEN`). EEL2 takes the last assignment, so the panel's 48 words would have
gone to a dead address while every panel read landed in the curve region — no error on either
side. The table is `gc_fmeta`, and two gate sites now hold it: `panel-meta-address` and
`curve-meta-unshadowed`. Grep an address name against the source before trusting a plan for it.

`gc_pfield` must be reset to −1 at the top of every frame from Task 6 onward, not from Task 7:
undefined EEL2 variables are 0, and `gc_pfield >= 0` then makes every click capture readout
field 0.

Task 7 carried three more stale or wrong lines, all caught by reading the source:

- **`slider143` does not exist.** The panel parameter is `slider246`; the plan predates the
  measurement that moved it. EEL2 would have taken `slider143` as an ordinary variable — the panel
  opening and closing for the session and storing nothing in the project, silently.
- **The row offset was always zero.** `(gc_open == gc_b+1 ? gc_card_h : 0) * (gc_b+1 > gc_open)`
  multiplies two factors that are never both non-zero, so every row below an open card would have
  been drawn underneath it.
- **There was no strip veto to extend.** V1.1 computes `gc_strip_hot` and never reads it. The veto
  now reads it and `gc_panel_hot`, and is belt and braces: `gc_in_plot` already excludes everything
  below the plot.

Pattern across four tasks: every plan defect was found by grepping the source for the name the plan
used, and none by reading the plan carefully. `--source-only` and `--live` found the rest.

## The live matrix, as actually run (2026-09-09 / 09-10)

Confirmed by the owner, on his own material:

- fields write, and the Param list moves the parameter the field names;
- **`EQ` <-> `Split` changes the sound immediately**, without a second touch — `mbmode[b]` reaches
  the engine through `apply_band_dyn_global`, which was the one check the gates cannot make. What
  he heard also matches the topology rather than merely differing: Split presses the whole split
  band, Dynamic EQ modulates the filter's gain so the affected region follows its skirt;
- Micro presses, verified with the host's Delta on a band with `Macro 0`, where the plugin's only
  effect IS the reduction;
- an open card survives save and reopen.

**NOT confirmed: the gestures on B7/B8.** Bands 5–8 are separate named branches with the appended
slider numbers. `check_writers` proves all eight addresses statically; nothing proves the high
branches live. Small risk — the branches are generated from one table and are structurally
identical — but it is unproven, not proven.

Three GUI defects were found by using it, none by any gate: the card threshold false at every
window size, `A`/`B` meaning nothing to a reader, and the HP/LP label running off the plot at the
top of the range.

## Commands

```bash
python3 -m pytest tests/test_rcbitnova_dsp.py -q > /tmp/t.txt 2>&1; echo $?   # read the CODE
python3 tools/rcbitnova_compile.py          # floats the FX window, reads REAPER's error text
python3 tools/rcbitnova_gates.py --source-only
python3 tools/rcbitnova_gates.py --live     # needs REAPER, empty project
python3 -u tools/rcbitnova_nulltest.py      # ~12 min, V1.2 vs V1.1, needs an EMPTY project
```

`pytest | tail && git commit` does **not** guard — the exit code is `tail`'s. That has produced a
commit with failing tests twice in this project.

## Habits this project earned the hard way

- `n_params` does not prove a build compiles; a `@gfx` syntax error leaves it unchanged.
- EEL2 has no `1e18`. Parenthesise every assignment in a ternary branch. No bit-shifts.
- Never `pkill` a hung reapy client — the server writes to the dead socket and dies with it.
  `test_connection` first; it lies after a REAPER restart, so a fresh direct client decides.
- Do not open a project tab from a script: it stops the deferred reapy server being called.
- Verify claims about the source by running them, not by reading. Every review round found a regex
  or a constant that did not match reality.
