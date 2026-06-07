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
- **Wrap edits in one undo block.** For MIDI-API edits (`MIDI_SetNote`/`…Delete`)
  prefer EXPLICIT registration over a bare block: `Undo_BeginBlock2(0)` … then
  `MarkProjectDirty(0)` + `Undo_OnStateChange2(0,label)` + `Undo_EndBlock2(0,label,-1)`
  (see scripts-reference "Editing & undo gotchas"). A bare `Undo_BeginBlock/EndBlock`
  has registered MIDI undo in practice but isn't guaranteed.
- **Batch edits: process items in REVERSE position order** (positions shift as you edit).
- **Audio accessor: read from accessor position 0, NOT `D_STARTOFFS`** (offset is baked in).
- **Never set track automation mode to READ** in scripts (Dima's standing rule).
- **REAPER runs the file the ACTION points to** (per `reaper-kb.ini`), re-read each
  run — NOT whatever copy you just edited elsewhere. "Fixed it but REAPER still does
  the old thing" → the action points at a stale copy; keep the registered file in sync.

## MIDI edit traps (silent data corruption — FakeReaper won't catch these)

These don't crash; they quietly edit the WRONG notes live while offline tests stay
green. Both cost real debugging on the repeated-note-merge tool (2026-06).

- **`MIDI_CountEvts`/`MIDI_GetNote` return ALL notes in the TAKE, not just the
  visible item.** A trimmed item is a window onto its take; a Jam-Origin MIDI-Guitar
  take can run hundreds of notes and tens of seconds past the item edges (seen: 768
  notes, −35 s … +108 s, for a ~6 s item). Editing "the whole item" then
  merges/deletes notes the user can't even see — and if the take is POOLED (ghost
  copies), the change hits every copy on other tracks. ALWAYS clip read notes to the
  item's project-time bounds `[D_POSITION, D_POSITION+D_LENGTH)` (intersect with the
  time selection if present). A time selection ALONE does not bound it if it's wider
  than the item or the item has no TS.
- **In-place `MIDI_SetNote` invalidates note indices; a later `DeleteNote(idx)` then
  deletes the WRONG note.** REAPER re-sorts events on edit, so indices captured from
  `GetNote` go stale after any `SetNote` (especially timing changes) — even with the
  `noSort` arg set. Symptom: deletes unrelated different-pitch notes and fails to
  extend the intended one. FakeReaper does NOT model the re-sort, so index-based
  in-place edits pass offline and corrupt live. SAFE pattern (the project's proven
  one): compute the final note set, DELETE every in-scope note by index high-to-low,
  then RE-INSERT the result, with a single `MIDI_Sort` at the end. Never interleave
  `SetNote` with index-based `DeleteNote`.

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
