# ReaScripts

A collection of REAPER ReaScripts for audio production.

## Scripts

### Envelope-based Limiter V1.0

Brick-wall peak limiter via volume automation envelope. Analyzes selected audio item for peaks exceeding a user-defined ceiling and creates precise volume automation to tame them.

- Configurable ceiling (dB), attack (ms), release (ms), and analysis window (ms)
- Infinity ratio — true brick-wall limiting
- Per-window gain reduction for precise automation
- Fully undoable (Ctrl+Z / Cmd+Z)

**Note:** Volume automation is post-FX. To measure results with a plugin, route the track to a bus and place the meter there.

### Envelope-based Limiter (Item) V1.0

Same as Envelope-based Limiter V1.0 but writes to the **item's own take volume envelope** instead of the track volume envelope. Keeps the track envelope clean.

- All the same features as the track version
- Automation lives on the item — moves with it if repositioned
- Take volume envelope is pre-FX, so you can measure directly with plugins on the same track

### RCBit Limiter V1.0

Split-based peak limiter using [JS:RCBitRangeGain](https://github.com/RCJacH/ReaScripts) for bit-accurate gain reduction. Instead of writing automation, it splits the audio item at peak boundaries and applies RCBitRangeGain as Take FX only on peak segments.

- Bit-accurate gain reduction (no floating-point truncation artifacts)
- Preserves transients — no lookahead or envelope shaping
- Each peak window gets its own precisely calculated Bit Ratio
- Non-peak segments remain completely clean with no plugins
- Configurable ceiling (dB), attack (ms), release (ms), and analysis window (ms)

**Requires:** JS:RCBitRangeGain JSFX plugin by RCJacH. Install via ReaPack: **Extensions > ReaPack > Import repositories** and add `https://github.com/RCJacH/ReaScripts/raw/master/index.xml`

### Align Track to Reference V1.0

Cross-instrument timing alignment by splitting and moving waveforms. Aligns a target track to a reference track without stretch markers and without quantizing to a grid.

The script analyzes transient onsets in both tracks, matches them, and identifies where the timing difference exceeds a user-defined threshold. It then splits and moves only those moments, leaving everything else untouched.

**How it works:**

The threshold (e.g., 15ms) means: "ignore timing differences smaller than this." If the target is 10ms late compared to the reference, it's left alone. If it's 20ms late, it gets corrected. Lower threshold = more corrections, higher = only fix the big ones.

What makes this script feel natural is the grouping logic. When multiple onsets are close together, it picks the one with the biggest timing difference and moves the whole section. That's why sometimes it moves one note, sometimes a whole phrase. It's approximating what a human editor would do: fix the anchor beat, let the surrounding notes follow naturally.

This means the result isn't a rigid lock to the reference. It's more like a tighter conversation between the two instruments. In some moments it feels amazing, more natural than moving every single note to match the reference. The groove breathes, but the important hits land together.

**Features:**
- Works with any time signature, any tempo, or completely free-tempo material
- No stretch markers, no grid quantization
- Splits and moves only where musically necessary
- Supports 16/24/32-bit PCM and 32/64-bit float WAV files
- Pure Python, no external dependencies
- Creates a new track with the aligned version, original untouched
- Single undo point for all changes

**Parameters:**
- **Reference track #** -- the track to align TO (e.g., the Pandero)
- **Target track #** -- the track to be aligned (e.g., the Jarana)
- **Threshold (ms)** -- minimum timing error that triggers a correction

**V2 roadmap:**
- "Smart" mode (current behavior) -- automatic grouping, musical approximation
- "Precise" mode -- every matched onset gets its own split/move, for crucial moments where you want exact sync
- Visual preview of which onsets will be adjusted before applying
- User control to blend between musical feel and tight lock

## Installation

Copy script files directly into your REAPER Scripts folder:
- **macOS:** `~/Library/Application Support/REAPER/Scripts/`
- **Windows:** `%APPDATA%\REAPER\Scripts\`
- **Linux:** `~/.config/REAPER/Scripts/`

Then load via **Actions > Show action list > Load ReaScript**.

**For Python scripts (.py):** Make sure Python is enabled in REAPER Preferences > Plug-ins > ReaScript.

## Usage

### Limiter scripts (Lua)
1. Select an audio item on a track
2. Run the script from the Actions list
3. Adjust parameters in the dialog box
4. Click OK

### Align Track to Reference (Python)
1. Run the script from the Actions list
2. Enter reference track number, target track number, and threshold
3. The script creates a new track with the aligned version

All scripts are fully undoable.

## License

MIT
