---
name: reascripts
description: Use when writing, editing, or debugging a REAPER ReaScript (Python/Lua/EEL) — building an action that edits items/takes/FX/envelopes, running the headless+reapy dev loop, or when REAPER crashes, freezes, or aborts during or after a script runs.
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
