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
  check("no overlap -> we < ws", we < ws)
end

-- extract_pool_id: pull the POOLEDEVTS GUID from an item state chunk
do
  local chunk = "<ITEM\n<SOURCE MIDI\nHASDATA 1 960 QN\n"
             .. "POOLEDEVTS {ABCD1234-1111-2222-3333-444455556666}\n>\n>"
  check("pool id extracted",
    extract_pool_id(chunk) == "{ABCD1234-1111-2222-3333-444455556666}")
  check("nil chunk -> nil", extract_pool_id(nil) == nil)
  check("no pool line -> nil",
    extract_pool_id("<ITEM\n<SOURCE MIDI\n>\n>") == nil)
end

-- compute_effective_window: zero-width time selection collapses the window
do
  local ws, we = compute_effective_window(2.0, 2.0, 0.0, 4.0, 0.0, 4.0)
  check("zero-width TS -> ws == we", ws == we)
  check("zero-width window excludes all", in_window(2.0, ws, we) == false)
end

-- extract_pool_id: extra contract cases
do
  check("first POOLEDEVTS wins when two present",
    extract_pool_id("POOLEDEVTS {1A2B3C4D-0000-0000-0000-000000000001}\n"
                 .. "POOLEDEVTS {FFFFFFFF-0000-0000-0000-000000000002}\n")
    == "{1A2B3C4D-0000-0000-0000-000000000001}")
  check("brace-absent GUID -> nil",
    extract_pool_id("POOLEDEVTS ABCD1234-1111-2222-3333-444455556666\n") == nil)
end

if failures == 0 then print("\nALL PASS"); os.exit(0)
else print("\n" .. failures .. " FAILURE(S)"); os.exit(1) end
