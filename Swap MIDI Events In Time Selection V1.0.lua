-- Swap MIDI Events In Time Selection V1.0.lua
-- Swaps ALL MIDI events (notes, CC, pitch bend, sustain, program change,
-- text/sysex) between the two selected MIDI items, within the current time
-- selection, WITHOUT splitting either item. An event belongs to the swap if
-- its START falls inside the effective window (time selection intersected with
-- both item bodies); it moves whole to the same absolute project time in the
-- other item.
--
-- Caveat: pooled MIDI copies elsewhere in the project are edited in place
-- (REAPER's normal pooling behavior). Two items sharing one source are rejected.

-- ===== pure helpers (no REAPER deps; unit-tested via lua CLI) =====
-- (added in Tasks 2-4)

-- ===== REAPER-bound (added in Task 6) =====

-- ===== entry point =====
if reaper ~= nil and reaper.CountSelectedMediaItems ~= nil then
  main()
end
