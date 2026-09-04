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
| Done | Tasks 1–4 (`56af29a`, `c086457`, `2063c34`, `33d341b`) |
| Next | **Task 5** — eleven dynamics writers, 88 named assignments, per-writer gate record |
| Green | 275 tests · gate 30 sites · null 6/6 identical to V1.1 · compile 179 params |

## The one thing to know before touching parameters

**REAPER orders FX parameters by SLIDER NUMBER, not by declaration order.** Measured 2026-09-04.
The panel slider, declared last but numbered 143, landed at record 95 and pushed `B5 Enable` to 96 —
shifting all eighty B5–B8 records while V1.0's 95-record prefix stayed intact, so every V1.0-based
check still passed. It is `slider246` now, record 175.

Three spec revisions and both reviewers carried the wrong rule, because the obvious test cannot
distinguish them: sliders added later in the file *and* higher in number satisfy both.

What caught it: `tests/fixtures/v11_declared_175.json` — V1.1's 175 records frozen with ranges,
steps and defaults, compared field by field by `--live`.

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
