# ReaScripts Project — Claude Code Context

<EXTREMELY_IMPORTANT>
BEFORE responding to the user's first message in this session, you MUST
execute these Read tool calls in order:

1. Read /Users/macbook/Knowledge/brain.md
2. Read /Users/macbook/Knowledge/reascripts/index.md

This is not optional and not "load if relevant". Execute these two
Read calls FIRST, then answer the user.

In your response, briefly confirm (one sentence) that you read both
files — name one specific fact from each that proves you read it.
Then proceed with the user's actual request.

After this initial load, follow the lazy-load protocol in
/Users/macbook/Knowledge/CLAUDE.md: when a trigger keyword from
reascripts/index.md appears in conversation, Read the
corresponding topic file.
</EXTREMELY_IMPORTANT>


## Overview
This repo contains REAPER DAW scripts (Lua, Python, JSFX) for audio production.
GitHub: https://github.com/gorelik11/ReaScripts
JSFX also mirrored at: https://github.com/gorelik11/JSFX

## User: Dima Gorelik
- macOS Big Sur 11.0.1, REAPER v7.65
- SWS extension installed, reapy v0.10.0
- Location: Poland (CET)
- Comfortable giving Claude full autonomous access

## User Preferences
- Prefers bit-accurate gain (RCBitRangeGain / powers of 2) over traditional dB
- Values transient preservation — split-based approach preferred
- Mastering defaults: -9 LUFS, -0.5 dB peak ceiling, 0ms attack, 70ms release, 5ms window
- Always uses "Bus" track as main master. Group buses go INSIDE cosmetical folders.
- Don't set track automation mode to READ in scripts
- Renders "pre-fader, pre-pan, post fx" as standard workflow

---

## JSFX Plugins (JSFX/ directory)

### RCBitBrickwall — Brickwall Limiter Series
Bit-accurate brickwall lookahead limiter. Ceiling via `1/pow(2, bits)`.

| Version | Features |
|---------|----------|
| V1.0 | Stereo linked, cosine-windowed lookahead, no oversampling |
| V2.0 | + true Dual Mono (separate peak/gain buffers per channel) |
| V3.0 | + oversampled peak detection (1x/2x/4x/8x Hermite interpolation) |
| V4.0 | + Light/HQ mode switch (Light=no scan loops, HQ=cosine reshaping) |
| Light V1.0 | Standalone Light mode version |

**Architecture:**
- **HQ mode:** Scans entire lookahead window for worst peak (`loop(delay_len+1)`), cosine-windowed gain reshaping on new peaks (conditional). CPU heavy.
- **Light mode:** Envelope on live signal, applied to delayed audio. Zero scan loops. Near-zero CPU.
- **Oversampling:** Hermite cubic interpolation for peak detection only (not full signal path). 4 history samples per channel, `((a*t+b)*t+c)*t+d` per point.
- **Safety clamp:** `min(output, ceiling)` — brickwall guarantee, rarely fires with 5ms+ lookahead.

### RCBitLimiter V1.0 — Soft Lookahead Limiter
PurestGain IIR smoothing (AirWindows technique). Output may slightly exceed ceiling on extreme transients. Good for transparent gain riding.

### RCBitComp V1.0 — Compressor
Bit-accurate compressor. Downward + upward compression, RMS detection, sidechain HPF/LPF. Threshold/makeup/knee in bits.

### Technical Notes
- `TakeFX_SetParam` uses actual slider values for JSFX, NOT normalized 0-1
- Use `TakeFX_SetParamNormalized` / `GetParamNormalized` for 0-1 range
- JSFX slider step sizes quantize values (step=0.05 → BR=0.1841 rounds to 0.2)
- User has custom `RCBitPercents` JSFX (same desc as RCBitRangeGain, finer steps)
- `TakeFX_AddByName(take, "JS:RCBitRangeGain", -1)` may match RCBitPercents
- RCBitRangeGain: Macro Shift=-1 + variable Bit Ratio for bit-accurate reduction
- Formula: `bit_ratio = reduction_db / 6.0206`
- RCBitRangeGain sliders: slider1 Macro[-16,16,1], slider2 Micro[-100,100], slider3 BR[0,3]

---

## Lua Scripts — RCBit Limiter Series

### Envelope-Based Limiters (write FX automation to RCBit instances)
- `RCBit Envelope Limiter V3.0` / Headless — Combined mode (Macro+BR) or Micro mode
- `RCBit LUFS Envelope Limiter V3.0` / Headless — LUFS-targeted version
- `Batch Apply Envelope Limiter V1.0/V2.0` — applies to all selected items

### Peak-Based Limiters (split items at peaks, apply RCBit gain per segment)
- `RCBit Limiter V8.0` / Headless — accessor-based, no render, no temp files
- `RCBit LUFS Limiter V8.0` / Headless — LUFS-targeted version

### Headless Versions
All headless scripts read params from `~/rcbit_*_params.txt` and write results to `~/rcbit_*_results.txt`. Run via action ID with `Main_OnCommand`.

### Production-Ready Action IDs (may change between sessions)
- RCBit LUFS Limiter V8.0 Headless: 58144
- RCBit Limiter V8.0 Headless: 58153
- Use `ReverseNamedCommandLookup` for stable named IDs

---

## Audio Alignment Scripts

### Align Track to Reference V1.0–V3.0
Python-based transient alignment using librosa/madmom.
- V3.0 has reference gap-filling implementation (`fill_gaps_and_crossfade()` line 735-839)
- Uses `BR_GetMediaItemGUID` to track moved items
- CROSSFADE = 0.005s (5ms)

### Auto Align Frame Drum V1.0/V1.1
- madmom `RNNOnsetProcessor` for onset detection
- Compares onsets to tempo map grid (32nds + triplets)
- 15ms threshold for alignment
- V1.1 added gap filling (167/467 gaps filled)

### CRITICAL: Gap Filling
Split-and-move ALWAYS creates gaps. Must fill afterwards:
- If next item moved → extend backward (D_STARTOFFS/D_POSITION)
- If current item moved → extend forward (D_LENGTH)
- If both moved → split the gap

---

## Auto Tempo Map

### Architecture
Python + madmom neural network beat/downbeat detection → REAPER tempo markers via reapy.

### Libraries
- `madmom` 0.17.dev0: `pip3 install git+https://github.com/The-Africa-Channel/madmom-py3.10-compat.git`
- Requires `scipy<1.14` and `cython`
- `RNNDownBeatProcessor` → `DBNDownBeatTrackingProcessor(beats_per_bar=[N], fps=100)`

### CRITICAL Rules
1. **BPM from downbeat-to-downbeat**, NOT from averaging beat intervals
   - `bpm = quarter_notes_per_bar * 60 / bar_duration`
   - For x/4: `bpm = x * 60 / bar_duration`
   - For x/8: `bpm = x * 30 / bar_duration`
2. **REAPER BPM is ALWAYS quarter-note based** regardless of time signature denominator
3. **Only modify tempo within item boundaries** — never delete all markers
4. Filter pickup beats/outliers (partial bars, extreme BPM values)

### Tested On
- 15/8 jazz (3x5/8), 4/4 with drums, 6/8 jazz waltz (beats_per_bar=[3])
- Comparable to Logic Pro's Smart Tempo

---

## MIDI & String Quartet Workflow

### Voice Splitting (Piano → 4 Voices)
Top/Bottom + voice-leading proximity:
1. Group notes by onset time
2. Sort by pitch (high→low)
3. Assign: highest=Vln1, next=Vln2, next=Viola, lowest=Cello
4. Fewer notes than voices → proximity logic

### String Quartet Ranges
| Instrument | Low | High | Extended |
|---|---|---|---|
| Violin 1 | G3 (55) | A6 | C7 |
| Violin 2 | G3 (55) | E5 | A5 |
| Viola | C3 (48) | D5 | G5 |
| Cello | C2 (36) | A3 | A4 |

### CC for Orchestral
CC1=Dynamics/Mod, CC7=Volume, CC11=Expression, CC64=Sustain

---

## MCP Servers

Two MCP servers for REAPER control:

### reaper (reapy-based)
- ~15 tools, requires `activate_reapy_server.py` running in REAPER
- Good for complex scripting via `python3 -c "import reapy; ..."`
- Use `inside_reaper()` context to avoid timeouts

### total-reaper (Lua file bridge)
- 600+ tools, requires `mcp_bridge.lua` in REAPER Actions
- Good for direct DAW control (create tracks, add FX, MIDI operations)
- **Fixed:** `tool_registry.py:170` and `dsl/tools.py:536` — redirected print() to stderr (was corrupting JSON-RPC stream)

### MCP Bug Report
See `claude-code-bug-report.md` in repo root. Key issues:
1. Hidden marketplace plugin MCP servers (17 `.mcp.json` files trying to launch via `bun`)
2. MCP regression in Claude Code v2.1.79-2.1.80 (fixed by downgrading to v2.1.42)
3. `ENABLE_TOOL_SEARCH=false` in settings as safety measure

---

## Iterative Script Development Loop

Headless Lua scripts → register & run via reapy → read results → undo if bad → retry.

1. Write headless Lua (no dialogs, hardcoded params, writes to `~/result.txt`)
2. Register: `RPR.AddRemoveReaScript(True, 0, path, True)` → action ID
3. Run: `RPR.Main_OnCommand(action_id, 0)`
4. Read results from file
5. Undo if needed: `RPR.Undo_DoUndo2(0)` (re-select items after!)
6. Modify script and go to step 3 (no re-registration needed)

### Common Pitfalls
- Stacked FX from incomplete undos — always verify `TakeFX_GetCount`
- Item selection lost after undo — always re-select
- `PreventUIRefresh` in outer script blocks inner `Main_OnCommand` from seeing state
- Process items in REVERSE position order in batch scripts
- Use `UpdateArrange()` before each inner `Main_OnCommand`

---

## Project Organization

### Template Conventions
- "Bus" track = main master, has FX chain "bus"
- Group buses send to "Bus", go inside cosmetical folders
- Cosmetical folders: `B_MAINSEND=0`, no sends, `I_FOLDERCOMPACT=2`
- Children: explicit sends to group bus, `B_MAINSEND=0`, preserve reverb/delay sends

### Script Pattern (organize_project.lua)
Find Bus → reset depths → categorize tracks → create bus/folder tracks → move groups → set routing → collapse folders

---

## Render Templates
- Archie's Render Template V2.01 pattern: save → configure → render 42230 → restore
- r8brain bug: missing mode 10 in `If_Equals_Or`
- RENDER_SETTINGS bits: 8192 (pre-fader stems), 2048 (2nd pass), 131072 (preserve SR)

## Accessor Patterns
- `CreateTakeAudioAccessor` reads raw source only (no TakeFX processing)
- Split items: read from position 0, NOT D_STARTOFFS (offset baked in)
- `GetMediaSourceSampleRate` can return 0 for section sources → fallback: parent → project → 44100
- Chunked reading: loop by time (`t += ns/sr`), not samples

## Envelope Technical Notes
- Take envelope points: time relative to item start (0 = item start)
- Track FX param envelope: project time
- `InsertEnvelopePoint` for FX param envelopes takes actual slider values, NOT normalized
- REAPER auto-creates default point at t=0 with norm=0 — delete before writing custom points
- Shape=1 (square/step) for discrete changes without interpolation

---

## Agents & Cross-Project Context
- **strategic-advisor** agent available in `.claude/agents/` (model: sonnet by default)
- Agents require git init in the project — already done
- Full strategic context: `~/.claude/projects/-Users-dimagorelik/memory/strategic-profile.md`
- After completing significant tasks, invoke strategic-advisor (sonnet) to check cross-project synergies
- Use opus only when user explicitly requests deep analysis

## Project Skills
- JSFX skills are installed locally in `.claude/skills/`:
  - `reaper-jsfx-core`
  - `reaper-jsfx-audio`
  - `reaper-jsfx-ui`
  - `reaper-jsfx-midi`
- Source: `https://github.com/mthines/jsfx-agent-skills`
- Refresh command:
  `python3 ~/.codex/skills/.system/skill-installer/scripts/install-skill-from-github.py --method git --repo mthines/jsfx-agent-skills --path skills/reaper-jsfx-core skills/reaper-jsfx-audio skills/reaper-jsfx-ui skills/reaper-jsfx-midi`

### Session Start: Agent Auto-Load (v2.1.42 workaround)
At the beginning of each session, check `.claude/agents/` for available agent files.
If the user's task aligns with an agent's purpose, proactively offer:
> "В этом проекте есть агент **[name]**. Загрузить его для этой задачи?"
To load: read the agent .md file, then launch via `Task` tool with the agent's system prompt.
Do NOT load agents for simple/quick tasks — only when strategic perspective or specialized role adds value.

---

## Knowledge Base
Vault: `~/Knowledge/` — git clone of `gorelik11/knowledge-vault` (private, shared across all machines)
This project's section: [`reascripts/`](file:///Users/macbook/Knowledge/reascripts/index.md)

### Protocol
1. At session start, read `~/Knowledge/reascripts/index.md`
2. When a topic listed in the index becomes relevant, read the corresponding .md file
3. When a subtopic appears, read the subtopic .md
4. NEVER load files from other sections without user request
5. When unsure if a file is needed — don't load it
6. `~/Knowledge/brain.md` — load on demand when cross-project context, machines, or strategic decisions are needed
7. Cross-project files (`_infrastructure/`, `_agents/`, `_shared/`) — load when their topic appears
8. Adjacent code project: `~/projects/midi-composition/` (REAPER + madmom infra is shared)
