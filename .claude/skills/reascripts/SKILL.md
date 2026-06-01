---
name: reascripts
description: Use when writing, editing, debugging, or TESTING a REAPER ReaScript (Python/Lua/EEL) — building an action that edits items/takes/FX/envelopes, unit-testing the RPR_* glue with the FakeReaper harness, running the headless+reapy dev loop, or when REAPER crashes, freezes, or aborts during or after a script runs.
---

# ReaScripts (REAPER scripting)

REAPER scripting for `~/projects/reascripts`. This skill is the entry point and
the non-negotiable rules; the deep, evolving reference lives in the Knowledge
vault (`~/Knowledge/reascripts/`) — find sections with the search tool below
instead of loading whole files.

## Crash-class laws (breaking these crashes or corrupts REAPER)

- **NEVER `raise SystemExit` / `sys.exit()` / `exit()` in a Python ReaScript.**
  REAPER runs scripts in an embedded interpreter, so it routes to `Py_Exit` → C
  `exit()` and kills the whole REAPER process (SIGABRT, *after* the script ran).
  Entry point must be `if __name__ == "__main__": main()` with `main()` returning
  normally. The `def main() -> int: … return 0` + `raise SystemExit(main())` CLI
  idiom is FATAL here. An ordinary unhandled exception is safe (REAPER shows it in
  the console); only interpreter-exit calls kill the host.
- **One `Undo_BeginBlock()` … `Undo_EndBlock(name, -1)`** around all edits.
- **Batch edits: process items in REVERSE position order** (positions shift as you edit).
- **Audio accessor: read from accessor position 0, NOT `D_STARTOFFS`** (offset is baked in).
- **Never set track automation mode to READ** in scripts (Dima's standing rule).

## When REAPER crashes or freezes

Use **superpowers:systematic-debugging**. Read the crash log FIRST:
`~/Library/Logs/DiagnosticReports/REAPER-*.ips` (JSON: header line, then payload;
the triggered thread's frames + `usedImages` names locate the fault). Main-thread
(`reaper`) SIGABRT with `Py_Exit` / `PyRun_SimpleString` → the script (SystemExit
law). Audio / `livefx` IOThread segfault inside a plugin (e.g. Kontakt) → the
plugin's fault, even when it correlates with a script run (anticipative-FX
re-renders the chain after the project changes).

## FakeReaper — MANDATORY test layer BEFORE any live run

A Python ReaScript's `RPR_*` glue MUST be unit-tested against an **in-memory fake
REAPER** before you touch live REAPER. This is not optional and it is easy to
forget — you do NOT have ambient access to a running REAPER, so the fake is how you
test destructive edits (split/move/delete) safely and repeatably.

- **Proven harness:** `~/projects/midi-composition/tests/_reaper_fakes.py`
  (`ReaperFakes` builds a `{"RPR_name": callable}` map; covers selected
  items/tracks, time selection, MIDI note enum/edit/insert/delete, take names,
  PPQ↔time, undo blocks, `GetUserInputs`).
- **How to wire it:** build the map, then inject onto the loaded module's globals —
  `for n, fn in fakes.items(): setattr(module, n, fn)` — because the script calls
  bare `RPR_*` names that resolve in the module namespace. Inject a fake `imgui`
  module / `RPR_defer` the same way to test ReaImGui dialog mapping offline.
- **Coverage caveat:** the proven set is MIDI-centric. Audio-item scripts must
  extend it with the ops they use (`CreateTakeAudioAccessor` /
  `GetAudioAccessorSamples`, `SplitMediaItem`, `TimeMap2_timeToQN`/`QNToTime`,
  `GetSetProjectGrid`, `Get/SetExtState`, …) before faking that path.
- **Protocol:** (1) pure logic in plain functions → normal unit tests; (2) the
  `RPR_*` wrapper → FakeReaper tests; (3) live REAPER only as the FINAL smoke,
  inside an undo block, after the fakes pass.
- **Lua:** there is NO Lua fake harness yet. The *idea* ports, but today Lua is
  tested by a small ported fake or live smoke with `/tmp` reports.
- Full doctrine: `~/Knowledge/_infrastructure/m4/mcp-workflow.md` (§ "Тестовый fake
  REAPER for Python ReaScript").

## Headless dev loop (live REAPER, via reapy)

reapy server must be running in REAPER. Register
`RPR.AddRemoveReaScript(True,0,path,True)` → action id; run
`RPR.Main_OnCommand(id,0)`; read results from a file; undo with
`RPR.Undo_DoUndo2(0)` (re-select items — selection is lost on undo). No
re-registration between edits. Caveat: importing the module to call functions
SKIPS the `__main__` entry, so a green headless test does NOT prove the action is
crash-safe — also run the real action (or assert the entry raises no SystemExit).

## Find the deep reference (token-cheap)

```
.claude/skills/reascripts/kb-search.sh <query terms>
```
Prints `file:line § heading` for each vault section containing ALL your terms
(section-level AND, any order — not a literal phrase) — Read that section. Topic
map (`~/Knowledge/reascripts/`): JSFX / RCBit →
`jsfx-plugins.md`; script catalog, accessor / envelope / render patterns, crash
gotchas → `scripts-reference.md`; tempo / madmom / BPM → `tempo-detection.md`.
