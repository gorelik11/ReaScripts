-- Unit tests for pure helpers. Run from repo root: lua tests/test_swap_midi_core.lua
-- reaper is nil here, so the script's bottom guard skips main().
dofile("Swap MIDI Events In Time Selection V1.0.lua")

local failures = 0
local function check(name, cond)
  if cond then print("ok   - " .. name)
  else print("FAIL - " .. name); failures = failures + 1 end
end

-- in_window: half-open [winStart, winEnd)
check("start is inside",      in_window(2.0, 2.0, 4.0) == true)
check("end is exclusive",     in_window(4.0, 2.0, 4.0) == false)
check("just before outside",  in_window(1.999, 2.0, 4.0) == false)
check("middle inside",        in_window(3.0, 2.0, 4.0) == true)

-- compute_effective_window: intersection of time selection and both item bodies
do
  local ws, we = compute_effective_window(1.0, 5.0, 0.0, 4.0, 2.0, 9.0)
  check("eff start = max(1,0,2) = 2", ws == 2.0)
  check("eff end   = min(5,4,9) = 4", we == 4.0)
end
do
  local ws, we = compute_effective_window(0.0, 1.0, 2.0, 3.0, 0.0, 5.0)
  check("no overlap -> we <= ws", we <= ws)
end

if failures == 0 then print("\nALL PASS"); os.exit(0)
else print("\n" .. failures .. " FAILURE(S)"); os.exit(1) end
