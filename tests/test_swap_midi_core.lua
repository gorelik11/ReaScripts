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

if failures == 0 then print("\nALL PASS"); os.exit(0)
else print("\n" .. failures .. " FAILURE(S)"); os.exit(1) end
