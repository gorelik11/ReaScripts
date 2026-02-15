# ReaScripts

A collection of REAPER ReaScripts (Lua) for audio production.

## Scripts

### Envelope-based Limiter V1.0

Brick-wall peak limiter via volume automation envelope. Analyzes selected audio item for peaks exceeding a user-defined ceiling and creates precise volume automation to tame them.

- Configurable ceiling (dB), attack (ms), release (ms), and analysis window (ms)
- Infinity ratio — true brick-wall limiting
- Per-window gain reduction for precise automation
- Fully undoable (Ctrl+Z / Cmd+Z)

**Note:** Volume automation is post-FX. To measure results with a plugin, route the track to a bus and place the meter there.

### RCBit Limiter V1.0

Split-based peak limiter using [JS:RCBitRangeGain](https://github.com/RCJacH/ReaScripts) for bit-accurate gain reduction. Instead of writing automation, it splits the audio item at peak boundaries and applies RCBitRangeGain as Take FX only on peak segments.

- Bit-accurate gain reduction (no floating-point truncation artifacts)
- Preserves transients — no lookahead or envelope shaping
- Each peak window gets its own precisely calculated Bit Ratio
- Non-peak segments remain completely clean with no plugins
- Configurable ceiling (dB), attack (ms), release (ms), and analysis window (ms)

**Requires:** JS:RCBitRangeGain JSFX plugin by RCJacH. Install via ReaPack: **Extensions > ReaPack > Import repositories** and add `https://github.com/RCJacH/ReaScripts/raw/master/index.xml`

## Installation

1. Open REAPER
2. Go to **Actions > Show action list**
3. Click **New action > New ReaScript...**
4. Save the .lua file and paste the script contents

Or copy .lua files directly into your REAPER Scripts folder:
- **macOS:** `~/Library/Application Support/REAPER/Scripts/`
- **Windows:** `%APPDATA%\REAPER\Scripts\`
- **Linux:** `~/.config/REAPER/Scripts/`

Then load via Actions > Show action list > Load ReaScript.

## Usage

1. Select an audio item on a track
2. Run the script from the Actions list
3. Adjust parameters in the dialog box
4. Click OK

Both scripts are fully undoable.

## License

MIT
