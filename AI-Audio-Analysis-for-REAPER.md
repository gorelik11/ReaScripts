# AI Audio Analysis for REAPER

A guide to setting up neural-network-powered audio analysis tools for REAPER using Python, madmom, and Claude Code. Covers automatic tempo map building (like Logic Pro's Smart Tempo) and beat-accurate audio alignment (split-and-move or stretch markers).

## What This Enables

- **Auto Tempo Map** — Analyze a recording and build a beat-by-beat tempo map with correct bar lines, even for complex time signatures (15/8, 7/8, 5/4, etc.). Comparable to Logic Pro's Smart Tempo.
- **Auto Align to Grid** — Detect onsets in a recording and align them to the tempo map grid using either split-and-move (preserves audio exactly) or stretch markers (no splits, continuous audio).
- **AI-Powered** — Uses pre-trained recurrent neural networks (madmom) for musically intelligent beat and onset detection, not just simple transient detection.

## Prerequisites

- **REAPER** (v6.37+ recommended, v7.x tested)
- **SWS Extension** for REAPER ([download](https://www.sws-extension.org/))
- **macOS** (tested on macOS; Linux/Windows should work with path adjustments)
- **Claude Code** (Anthropic's CLI agent) — orchestrates the Python analysis and REAPER script execution

## Step 1: Install Python 3.11

madmom requires Python 3.10 or 3.11. Python 3.12+ is not supported due to dependency issues.

### macOS

> **Detailed visual guide:** John Tidey wrote an excellent step-by-step PDF guide for installing Python for REAPER on macOS, with screenshots of every step including the REAPER Preferences setup: [REAPER Python install for macOS (PDF)](https://www.dropbox.com/scl/fi/ni7mcve8z4123nef1vrg7/REAPER-AAF-python-script-install-for-MacOS.pdf?rlkey=j1enceherfgka4qfku4pzjmop&e=2&dl=0)

1. Go to [python.org/downloads/macos](https://www.python.org/downloads/macos/)
2. Click **"Latest Python 3 Release - Python 3.11.x"**
3. Scroll to bottom, download **macOS 64-bit universal2 installer**
4. Run the installer to completion

Python will be installed to `/Library/Frameworks/Python.framework`.

Alternatively, use Homebrew:

```bash
brew install python@3.11
```

#### Configure REAPER to use Python

1. Open REAPER → **Preferences** → **Plug-ins** → **ReaScript**
2. Check **"Enable Python for use with ReaScript"**
3. Set **Custom path to Python dll directory** to: `/Library/Frameworks/Python.framework`
4. Set **Force ReaScript to use specific Python .dylib** to: `libpython3.11.dylib`
5. Click **Apply** and restart REAPER

#### Install pip (if not already present)

```bash
python3 --version
curl https://bootstrap.pypa.io/get-pip.py -o get-pip.py
python3 get-pip.py
```

Verify:

```bash
python3.11 --version
# Python 3.11.x
```

### Windows

Download the installer from [python.org](https://www.python.org/downloads/release/python-3110/). Check "Add Python to PATH" during installation.

### Linux

```bash
sudo apt install python3.11 python3.11-venv python3.11-dev
```

## Step 2: Install Python Dependencies

The order matters — scipy must be installed before madmom, and Cython before both.

```bash
# Install Cython first (required for madmom build)
pip3 install cython

# Install scipy < 1.14 (1.14+ has build issues on some systems)
pip3 install "scipy<1.14"

# Install numpy
pip3 install numpy

# Install madmom (Python 3.10+ compatible fork)
pip3 install git+https://github.com/The-Africa-Channel/madmom-py3.10-compat.git
```

> **Why the fork?** The original madmom package uses `collections.MutableSequence` which was removed in Python 3.10. The fork patches this.

Verify the installation:

```bash
python3 -c "import madmom; print('madmom', madmom.__version__)"
# madmom 0.17.dev0
```

## Step 3: Install python-reapy (Python ↔ REAPER Bridge)

[python-reapy](https://github.com/RomeoDespres/reapy) allows Python scripts to control REAPER remotely.

```bash
pip3 install python-reapy
```

### Enable in REAPER

1. Open REAPER → **Preferences** → **Plug-ins** → **ReaScript**
2. Make sure Python is enabled and points to your Python 3.11 installation
3. In REAPER's Actions list, run the script `activate_reapy_server.py` (comes with reapy):

```bash
python3 -c "import reapy; print(reapy.config.REAPY_SERVER_PORT)"
```

If this prints a port number, reapy is configured. You need to run `activate_reapy_server.py` inside REAPER each time you restart REAPER.

### Test the connection

```bash
python3 -c "
import reapy
with reapy.inside_reaper():
    n = reapy.reascript_api.CountTracks(0)
    print(f'REAPER has {n} tracks')
"
```

## Step 4: Install Claude Code

Claude Code is Anthropic's CLI agent that orchestrates the entire workflow — running Python analysis, generating Lua scripts, and executing them in REAPER.

```bash
npm install -g @anthropic-ai/claude-code
```

See the [Claude Code documentation](https://docs.anthropic.com/en/docs/claude-code) for setup and API key configuration.

## Step 5 (Optional): Install Total REAPER MCP

[Total REAPER MCP](https://github.com/shiehn/total-reaper-mcp) provides 600+ tools for direct REAPER control from Claude Code. Not required for the workflows below, but very useful for general REAPER automation.

```bash
cd ~
git clone https://github.com/shiehn/total-reaper-mcp.git
cd total-reaper-mcp
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e .
```

Add to `~/.claude.json` under `"mcpServers"`:

```json
"total-reaper": {
  "transport": "stdio",
  "command": "/path/to/total-reaper-mcp/.venv/bin/python",
  "args": ["-m", "server.app", "--profile", "full"],
  "cwd": "/path/to/total-reaper-mcp"
}
```

In REAPER, load `mcp_bridge.lua` from the Actions list (must be running for total-reaper to communicate with REAPER).

---

## Workflow 1: Auto Tempo Map Builder

Build a tempo map from a live recording — the neural network detects beats and downbeats, then places tempo markers in REAPER.

### How It Works

1. **Render** your audio (full mix and/or drum stem) to WAV files
2. **madmom's `RNNDownBeatProcessor`** analyzes the audio using a pre-trained recurrent neural network that understands musical rhythm — not just transient peaks, but the underlying beat structure
3. **`DBNDownBeatTrackingProcessor`** (Dynamic Bayesian Network) tracks the tempo through the recording, handling natural fluctuations
4. A **Lua script** places tempo markers in REAPER at each bar line with the calculated BPM

### The Python Analysis

```python
import madmom
import numpy as np

# Load audio
audio_file = "/path/to/your/rendered-audio.wav"

# Beat + downbeat detection (neural network)
proc = madmom.features.downbeats.RNNDownBeatProcessor()
activations = proc(audio_file)
# activations shape: [frames, 2] — beat probability + downbeat probability

# Track beats through the recording
# beats_per_bar: [3] for 3 groups (e.g., 15/8 = 3×5/8)
# Adjust min_bpm/max_bpm to your music's range
tracker = madmom.features.downbeats.DBNDownBeatTrackingProcessor(
    beats_per_bar=[3],  # adjust to your time signature
    min_bpm=80,
    max_bpm=140,
    fps=100
)
beats = tracker(activations)
# beats: [[time_seconds, beat_position], ...]
# beat_position = 1 means downbeat (bar start)
```

### Combining Multiple Sources

For better accuracy, analyze both the full mix and a drum stem, then blend:

```python
proc = madmom.features.downbeats.RNNDownBeatProcessor()

act_mix = proc("/path/to/full-mix.wav")
act_drums = proc("/path/to/drum-stem.wav")

# Blend: weight the mix heavier (drums may fluctuate independently)
combined = 0.7 * act_mix + 0.3 * act_drums

beats = tracker(combined)
```

### Downbeat Phase Correction

madmom sometimes places bar lines offset by one beat. Fix this by testing all phase offsets:

```python
def find_best_phase(beats, beats_per_bar):
    """Test all phase offsets, score by downbeat alignment."""
    best_score, best_offset = -1, 0
    for offset in range(beats_per_bar):
        shifted = beats.copy()
        # Reassign beat positions with this offset
        for i in range(len(shifted)):
            shifted[i, 1] = ((i + offset) % beats_per_bar) + 1

        # Score: how many beat_position=1 entries match madmom's downbeat predictions
        downbeat_times = shifted[shifted[:, 1] == 1, 0]
        original_downbeats = beats[beats[:, 1] == 1, 0]

        score = sum(1 for d in downbeat_times
                    if any(abs(d - od) < 0.05 for od in original_downbeats))

        if score > best_score:
            best_score = score
            best_offset = offset

    return best_offset
```

### REAPER BPM Convention

REAPER BPM is **always quarter-note based**, regardless of the time signature denominator:

| Time Signature | BPM Formula |
|---|---|
| x/4 | `BPM = x * 60 / bar_duration` |
| x/8 | `BPM = x * 30 / bar_duration` |
| x/16 | `BPM = x * 15 / bar_duration` |

### Applying to REAPER (Lua Script)

The Lua script receives the calculated tempo data and sets markers:

```lua
-- Clear existing tempo markers (iterate backwards!)
local n = reaper.CountTempoTimeSigMarkers(0)
for i = n - 1, 0, -1 do
    reaper.DeleteTempoTimeSigMarker(0, i)
end

-- Add new markers (one per bar at each downbeat)
for i, bar in ipairs(bars) do
    reaper.SetTempoTimeSigMarker(0, -1,
        bar.time,        -- project time (seconds)
        -1,              -- measurepos (-1 = auto)
        0.0,             -- beatpos
        bar.bpm,         -- tempo (quarter-note based)
        bar.ts_num,      -- time sig numerator (e.g., 15)
        bar.ts_denom,    -- time sig denominator (e.g., 8)
        false            -- lineartempo (false = instant change)
    )
end

reaper.UpdateTimeline()
```

### Orchestration with Claude Code

In practice, Claude Code handles the full pipeline:

1. You tell Claude the time signature, approximate tempo range, and point it to the audio files
2. Claude runs the Python analysis with madmom
3. Claude generates a Lua script with the tempo data embedded
4. Claude registers and executes the script in REAPER via reapy
5. You verify the result — if the bar lines are off, Claude adjusts the phase offset or parameters and retries

Example prompt:
> "Build a tempo map for my project. Time signature is 15/8 (3 groups of 5/8). Tempo starts around 106 and settles around 116. The drum stem is rendered and selected in REAPER."

---

## Workflow 2: Auto Align to Grid

Align a recorded instrument to the tempo map grid using neural-network onset detection.

### How It Works

1. **Render** the instrument to a WAV file (or use an existing rendered take)
2. **madmom's `RNNOnsetProcessor`** detects note onsets using a neural network
3. **Build a musical grid** from the tempo map (32nd notes + triplet 8ths)
4. **Compare** each onset to the nearest grid position
5. **Correct** onsets beyond a threshold (e.g., 15ms) using either split-and-move or stretch markers

### Onset Detection

```python
import madmom
import numpy as np

audio_file = "/path/to/instrument.wav"

# Neural network onset detection
proc = madmom.features.onsets.RNNOnsetProcessor()
activations = proc(audio_file)

# Peak picking to get discrete onset times
picker = madmom.features.onsets.OnsetPeakPickingProcessor(
    threshold=0.3,  # lower = more sensitive
    fps=100
)
onsets = picker(activations)
# onsets: array of onset times in seconds
```

### Building the Musical Grid

Build grid positions from the tempo map — 32nd notes and triplet 8ths give comprehensive coverage:

```python
# For each tempo marker region:
beat_dur = 60.0 / bpm  # quarter note duration

# 32nd notes: 8 per quarter note
for k in range(8):
    grid.add(beat_start + k * beat_dur / 8.0)

# Triplet 8ths: 3 per quarter note
for k in range(3):
    grid.add(beat_start + k * beat_dur / 3.0)
```

### Option A: Split-and-Move (No Stretching)

Preserves audio exactly — splits at onset positions, moves each segment to the grid.

**Important:** Always include gap filling after split-and-move. Without it, gaps appear between items.

```
Before:  [====onset====onset====onset====]
After:   [====|onset===|onset====|onset==]
               ↓ moved    ↓ moved
         [====|onset==|onset====|onset===]
              gap filled via extending items
```

Gap filling pattern (from Align Track to Reference V3.0):
- If next item was moved → extend it backward (decrease `D_POSITION` + `D_STARTOFFS`)
- If current item was moved → extend it forward (increase `D_LENGTH`)
- If both → split the gap between them
- REAPER crossfade settings handle overlaps automatically

### Option B: Stretch Markers (No Splits)

Places stretch markers at every detected onset. Corrected onsets get moved to grid positions (stretching audio between markers). "Good" onsets within threshold get anchored in place to prevent drift.

```lua
-- For each onset:
-- srcpos = where the onset IS in the source (item-relative)
-- pos = where we WANT it (grid position, item-relative)
reaper.SetTakeStretchMarker(take, -1, pos, srcpos)
```

Key points:
- Anchor ALL onsets (not just corrected ones) to prevent nearby corrections from shifting good beats
- With `D_STARTOFFS=0` and `playrate=1.0`: `srcpos = onset_proj - item_pos`
- Target position: `pos = grid_proj - item_pos`

### Choosing Between Options

| | Split-and-Move | Stretch Markers |
|---|---|---|
| Audio quality | Bit-perfect (no processing) | Time-stretched (minor artifacts) |
| Transient preservation | Perfect | Good (depends on stretch algorithm) |
| Visual result | Many items with crossfades | Single item with markers |
| Best for | Percussion, drums | Melodic/tonal instruments |
| Undo | Single undo point | Single undo point |

---

## Complete Installation Checklist

```bash
# 1. Python 3.11
python3.11 --version

# 2. Core dependencies
pip3 install cython
pip3 install "scipy<1.14"
pip3 install numpy

# 3. madmom (AI audio analysis)
pip3 install git+https://github.com/The-Africa-Channel/madmom-py3.10-compat.git

# 4. python-reapy (Python ↔ REAPER bridge)
pip3 install python-reapy

# 5. Claude Code (orchestration)
npm install -g @anthropic-ai/claude-code

# 6. Verify everything
python3 -c "
import madmom, numpy, scipy, reapy
print('madmom:', madmom.__version__)
print('numpy:', numpy.__version__)
print('scipy:', scipy.__version__)
print('reapy:', reapy.__version__)
print('All good!')
"
```

In REAPER:
- [ ] SWS extension installed
- [ ] Python enabled in Preferences → Plug-ins → ReaScript
- [ ] `activate_reapy_server.py` running (Actions list)
- [ ] (Optional) `mcp_bridge.lua` running for total-reaper MCP

## Troubleshooting

### `ModuleNotFoundError: No module named 'Cython'`
Install Cython first: `pip3 install cython`

### scipy build fails with clang errors
Use a pre-built wheel: `pip3 install "scipy<1.14"`

### `collections.MutableSequence` error from madmom
You installed the original madmom, not the py3.10-compat fork. Uninstall and reinstall:
```bash
pip3 uninstall madmom
pip3 install git+https://github.com/The-Africa-Channel/madmom-py3.10-compat.git
```

### reapy connection refused
Make sure `activate_reapy_server.py` is running inside REAPER (not from the terminal — it must be loaded as a ReaScript action inside REAPER).

### madmom processing is slow
Normal. RNNDownBeatProcessor takes ~125 seconds for ~286 seconds of 96kHz audio. The neural network is the bottleneck. Lower sample rate files process faster.

### Tempo map bar lines are offset by one beat
Use the phase correction technique described above. Or manually shift in REAPER — the beat positions will be correct, only bar lines need adjustment.

### Stretch markers: some markers not added
REAPER rejects stretch markers that are too close together (< ~1ms apart). This is normal — 906 out of 915 is typical.

## Technical References

- [madmom documentation](https://madmom.readthedocs.io/)
- [madmom paper](https://madmom.readthedocs.io/en/latest/introduction.html) — S. Bock et al., "madmom: a New Python Audio and Music Signal Processing Library"
- [python-reapy](https://github.com/RomeoDespres/reapy)
- [REAPER API documentation](https://www.reaper.fm/sdk/reascript/reascripthelp.html)
- [Total REAPER MCP](https://github.com/shiehn/total-reaper-mcp)
- [Claude Code](https://docs.anthropic.com/en/docs/claude-code)

## License

MIT
