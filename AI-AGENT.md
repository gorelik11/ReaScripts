# Using the AI Agent for ReaScripts

When Claude Code tokens run out, use the Gemini-powered AI agent as a backup.

## Quick Start

```bash
agent reaper              # REAPER context
agent reaper composition  # combined with MIDI composition
```

## What the Agent Can Do

- **Write scripts:** "Write a Lua script to normalize selected items to -9 LUFS"
- **Debug scripts:** "Read RCBitBrickwall.jsfx and explain the gain calculation"
- **REAPER control:** "Add RCBitBrickwall to the master track"
- **File management:** "List all Lua scripts in ~/ReaScripts"
- **Test scripts:** "Run the headless limiter on the selected item"

## Example Prompts

```
You: Write a Lua script that splits items at transients
You: Read the envelope limiter V2 and explain how it works
You: Set up a mastering chain: RCBitComp → RCBitBrickwall on the Bus track
You: Run python3 -c "import reapy; print(reapy.Project().tracks)"
```

## REAPER Access

The agent uses reapy via shell commands. Make sure `activate_reapy_server.py` is running in REAPER.

## Context File

The agent loads `contexts/reaper.md` — a comprehensive knowledge base about your REAPER setup, JSFX plugins, Lua scripts, mastering workflow, and technical gotchas. Claude Code maintains this file.

## Key Differences from Claude Code

| Task | Claude Code | Agent |
|---|---|---|
| Add FX to track | `mcp__reaper__add_fx` (instant) | reapy via shell (2-3s) |
| Read MIDI notes | `mcp__reaper__get_midi_notes` | reapy script |
| Lua script dev | Direct iterative loop | Write file + run via reapy |
| JSFX params | `TakeFX_SetParam` via MCP | reapy `TakeFX_SetParam` |

The agent is a capable backup but Claude Code's MCP integration is significantly faster and more direct.
